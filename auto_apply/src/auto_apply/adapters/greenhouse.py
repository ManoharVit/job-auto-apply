"""Greenhouse native-form adapter with conservative preparation and receipts.

Only a newly observed confirmation and a matching accepted POST response can
establish submission. Unknown widgets and questions remain for human review.
"""
import json
import hashlib
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import unquote, urljoin, urlparse

from ..challenge_handler import handle_challenge
from ..settings import approved_fixture_url, greenhouse_identity, resume_file, job_application_url
from ..submission_guard import SubmissionBlocked
from ..requirements import description_text
from ..answer_memory import application_answers, question_key

CONFIRMATIONS = (
    "#application_confirmation", "#application-confirmation",
    "#application_thank_you", "#confirmation",
    "[data-testid='application-confirmation']", ".application-confirmation",
    ".confirmation > .confirmation__content",
)
SUCCESS = re.compile(r"application (?:has been )?(?:submitted|received)|thank you for applying", re.I)
LABEL = """el => {
    const linked = (el.getAttribute('aria-labelledby') || '').split(/\\s+/)
        .map(id => document.getElementById(id)?.innerText || '').join(' ');
    const labels = [...(el.labels || [])].map(l => l.innerText).join(' ');
    return labels || linked || el.getAttribute('aria-label') ||
        el.getAttribute('placeholder') || el.name || el.id || 'Unknown field';
}"""

def _visible(locator, skip_proxies=False):
    elements = []
    for index in range(locator.count()):
        element = locator.nth(index)
        if not element.is_visible() or (skip_proxies and _select_proxy(element)):
            continue
        identifier = element.get_attribute("id")
        if identifier:
            stable = locator.and_(locator.page.locator("[id=" + json.dumps(identifier) + "]"))
            if stable.count() == 1:
                element = stable
        elements.append(element)
    return elements

def _label(element):
    if (element.get_attribute("type") or "").lower() == "file":
        group = element.evaluate(r"""el => {
            const parent = el.closest('[role=group][aria-labelledby]');
            return (parent?.getAttribute('aria-labelledby') || '').split(/\s+/)
                .map(id => document.getElementById(id)?.innerText || '').join(' ');
        }""")
        if group.strip():
            return group.strip()
    return str(element.evaluate(LABEL)).strip()

def _required(element):
    if (element.get_attribute("type") or "").lower() == "radio":
        return element.evaluate("""el => {
            const group = [...el.form.querySelectorAll('input[type=radio]')]
                .filter(other => other.name === el.name);
            const container = el.closest('fieldset, [role=radiogroup]');
            return group.some(other => other.required || other.getAttribute('aria-required') === 'true')
                || container?.getAttribute('aria-required') === 'true'
                || (container?.querySelector('legend')?.innerText || '').trim().endsWith('*');
        }""")
    return (
        element.get_attribute("required") is not None
        or element.get_attribute("aria-required") == "true"
        or _label(element).rstrip().endswith("*")
        or ((element.get_attribute("type") or "").lower() == "file"
            and element.evaluate("el => el.closest('[role=group]')?.getAttribute('aria-required') === 'true'"))
    )

def _control_key(element):
    return (
        element.get_attribute("id") or "",
        element.get_attribute("name") or "",
        _label(element),
    )

def _answer_value(element):
    kind = (element.get_attribute("type") or "").lower()
    if kind in ("checkbox", "radio"):
        return {"checked": element.is_checked(), "value": element.input_value()}
    if kind == "file":
        return element.evaluate("""async el => Promise.all([...el.files].map(async file => ({
            name: file.name, size: file.size,
            sha256: [...new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer()))]
                .map(byte => byte.toString(16).padStart(2, '0')).join('')
        })))""")
    if _greenhouse_select(element):
        return element.evaluate("""el => {
            const container = el.closest('.select__container');
            return {
                selected: [...container.querySelectorAll('.select__single-value, .select__multi-value__label')]
                    .map(item => item.innerText.trim()),
                pendingText: el.value || '',
                proxyValid: [...container.querySelectorAll('input[aria-hidden=true][tabindex="-1"]')]
                    .every(item => item.validity.valid)
            };
        }""")
    return element.input_value()


def _greenhouse_select(element):
    return element.evaluate("""el => el.getAttribute('role') === 'combobox'
        && el.classList.contains('select__input')
        && !!el.closest('.select__container')?.querySelector('.select__control')""")


def _select_options(element):
    element.click()
    identifier = element.get_attribute("id")
    if not identifier:
        raise ValueError("A Greenhouse select needs an identified control.")
    listbox = element.page.locator(f"[id='react-select-{identifier}-listbox'][role='listbox']")
    listbox.wait_for(state="visible", timeout=5000)
    return _visible(listbox.locator("[role='option']"))


def _choose_select(element, label):
    matches = [item for item in _select_options(element) if item.inner_text().strip() == label]
    if not matches:
        element.fill(label)
        identifier = element.get_attribute("id")
        option = element.page.locator(f"[id='react-select-{identifier}-listbox'][role='listbox']").get_by_role("option", name=label, exact=True)
        try:
            option.first.wait_for(state="visible", timeout=5000)
        except Exception:
            element.press("Escape")
            return False
        matches = _visible(option)
    if len(matches) != 1:
        element.press("Escape")
        return False
    matches[0].click()
    state = _answer_value(element)
    return state["selected"] == [label] and not state["pendingText"] and state["proxyValid"]


def _clear_select(element):
    state = _answer_value(element)
    if state["selected"]:
        container = element.locator("xpath=ancestor::*[contains(concat(' ',normalize-space(@class),' '),' select__container ')][1]")
        clears = _visible(container.locator("button[aria-label='Clear selection'], button[aria-label='Clear value']"))
        if len(clears) != 1:
            raise ValueError("A preselected custom answer cannot be cleared safely.")
        clears[0].click()
    element.fill("")
    element.press("Escape")
    state = _answer_value(element)
    if state["selected"] or state["pendingText"]:
        raise ValueError("The custom select did not preserve a blank answer.")


def _select_proxy(element):
    return element.evaluate("""el => el.tagName === 'INPUT' && el.getAttribute('aria-hidden') === 'true'
        && el.getAttribute('tabindex') === '-1'
        && !el.id && !el.name && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby')
        && [...el.classList].some(value => value.endsWith('-requiredInput'))
        && el.closest('.select__container')?.querySelectorAll('input.select__input[role=combobox]').length === 1""")

def _question(element):
    if (element.get_attribute("type") or "").lower() == "radio":
        group = element.evaluate(r"""el => {
            const container = el.closest('fieldset, [role=radiogroup]');
            const linked = (container?.getAttribute('aria-labelledby') || '').split(/\s+/)
                .map(id => document.getElementById(id)?.innerText || '').join(' ');
            return container?.querySelector('legend')?.innerText || linked
                || container?.getAttribute('aria-label') || '';
        }""")
        if group.strip():
            return group.strip().rstrip("*").strip()
    return _label(element).strip().rstrip("*").strip()


def _demographic(question):
    return bool(re.search(r"\b(?:gender|sex|sexual orientation|disability|disabled|veteran|ethnicity|ethnic|race|racial|hispanic|latino)\b", question, re.I))

NONDISCLOSURE = (
    "prefer not to answer", "prefer not to say", "decline to self-identify",
    "i do not wish to answer", "decline to answer", "prefer not to disclose",
    "i don't wish to answer", "decline to self identify",
)

def _nondisclosure(label):
    return label.strip().casefold() in NONDISCLOSURE or any(
        part.strip().casefold() in NONDISCLOSURE for part in label.split("/")
    )

def _demographic_options(labels):
    choices = {label.strip().casefold() for label in labels}
    return {"male", "female"}.issubset(choices)


LEGAL_TEMPLATES = {
        "work_authorization": r"(?:are you|will you be) (?:currently )?(?:legally )?(?:authorized|eligible|permitted|allowed) to work in india",
        "citizenship": r"are you (?:an? )?(?:indian citizen|citizen of india)",
        "permanent_residency": r"are you (?:an? )?permanent resident (?:of|in) india",
        "visa_sponsorship": r"(?:do you|will you|would you) (?:now or in the future )?(?:require|need) (?:visa |employment )?sponsorship (?:to work |for employment )?in india(?: now or in the future)?",
}

def _legal_fact(question):
    normalized = " ".join(question.casefold().split()).rstrip(" ?.")
    return next((fact for fact, template in LEGAL_TEMPLATES.items()
                 if re.fullmatch(template, normalized)), None)

def _scoped_legal_answer(question, record):
    # Whole-question positive templates reject mixed/unknown country scopes.
    normalized = " ".join(question.casefold().split()).rstrip(" ?.")
    legal = re.search(r"\b(?:citizen\w*|residen\w*|national\w*|passport|green card|work permit|eligible to work|permitted to work|allowed to work|sponsor\w*|visa|right to work|work in)\b", normalized)
    legal = legal or (re.search(r"\bauthori[sz]\w*\b", normalized) and re.search(r"\b(?:work|employment|country|job|position)\b", normalized))
    technical = re.match(r"(?:explain|how|describe)\b", normalized) and re.search(r"\b(?:api|database|cloud|software|service|data)\b", normalized)
    identity = re.search(r"\b(?:citizen\w*|national\w*|passport|green card|visa|sponsor\w*|work|employment|country|employer|job|position|role)\b", normalized)
    if technical and not identity:
        legal = False
    if not legal:
        return not (isinstance(record, dict) and "country" in record)
    if not isinstance(record, dict) or str(record.get("country", "")).casefold() not in ("india", "in"):
        return False
    fact = _legal_fact(question)
    return fact is not None and record.get("fact", fact) == fact

def _answer_record(records, question, config):
    key = question_key(question)
    if key in records:
        return records[key]
    if _legal_fact(question) == "work_authorization":
        value = config.get("screening", {}).get("work_authorization_india")
        if type(value) is bool or value in ("Yes", "No"):
            return {"value": value, "country": "India", "fact": "work_authorization"}
    return None

def _option_label(value):
    return ("Yes" if value else "No") if type(value) is bool else str(value)


def _clear_answer(element):
    kind = (element.get_attribute("type") or "").lower()
    tag = element.evaluate("el => el.tagName.toLowerCase()")
    if _greenhouse_select(element):
        _clear_select(element)
    elif kind == "radio":
        element.evaluate("""el => {
            el.checked = false;
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }""")
    elif kind == "checkbox":
        element.set_checked(False)
    elif kind == "file":
        if element.evaluate("el => !!el.files?.length"):
            element.set_input_files([])
    elif tag == "select":
        element.select_option([])
    else:
        element.fill("")
        if element.input_value():
            raise ValueError("This control cannot preserve a blank answer.")


def _fill_exact_text(element, value):
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    # Native maxlength uses UTF-16 units, matching the browser's string length.
    bounds = element.evaluate("""(el, text) => ({
        limit: Number.isInteger(el.maxLength) ? el.maxLength : -1,
        length: text.length
    })""", text)
    if bounds["limit"] >= 0 and bounds["length"] > bounds["limit"]:
        return f"Saved answer for {_question(element)} exceeds the field length limit; review a shorter answer."
    element.fill(text)
    actual = element.input_value().replace("\r\n", "\n").replace("\r", "\n")
    if actual != text:
        return f"The form changed the saved answer for {_question(element)}; review it before submission."
    return None


def _explicit_answers(form, job, config, approved, records=None):
    if records is None:
        records = application_answers(config, job)
    counts = {}
    radio_names = set()
    for element in _visible(form.locator("input, select, textarea"), skip_proxies=True):
        kind = (element.get_attribute("type") or "").lower()
        if kind in ("hidden", "file", "submit", "button", "image") or element.is_disabled():
            continue
        if _select_proxy(element):
            continue
        if kind == "radio":
            name = element.get_attribute("name")
            if name in radio_names:
                continue
            radio_names.add(name)
        key = question_key(_question(element))
        counts[key] = counts.get(key, 0) + 1
    ambiguous = {key for key, count in counts.items() if count > 1}
    radios = [item for item in form.locator("input[type=radio]").all() if not item.is_disabled()]
    seen = set()
    for element in radios:
        name = element.get_attribute("name")
        if name in seen:
            continue
        seen.add(name)
        group = [item for item in radios if item.get_attribute("name") == name]
        question = _question(element)
        required = any(_required(item) for item in group)
        record = None if question_key(question) in ambiguous else _answer_record(records, question, config)
        value = record.get("value") if isinstance(record, dict) else record
        chosen = None
        if _demographic(question) or _demographic_options([_label(item) for item in group]):
            if required:
                chosen = next((item for item in group if _nondisclosure(_label(item))), None)
            else:
                value = None
        if chosen is None and value is not None and _scoped_legal_answer(question, record):
            matches = [item for item in group if _label(item).strip() == _option_label(value)]
            if len(matches) == 1:
                chosen = matches[0]
        for item in group:
            _clear_answer(item)
        if chosen is not None:
            chosen.evaluate("""el => {
                el.checked = true;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }""")
        for item in group:
            if chosen is not None or not required:
                approved[_control_key(item)] = _answer_value(item)
    for element in _visible(form.locator("input, select, textarea"), skip_proxies=True):
        kind = (element.get_attribute("type") or "").lower()
        if kind in ("hidden", "submit", "button", "image", "radio") or element.is_disabled():
            continue
        if _select_proxy(element):
            continue
        if _control_key(element) in approved:
            continue
        label = _question(element)
        question = label.casefold()
        demographic = _demographic(question)
        tag = element.evaluate("el => el.tagName.toLowerCase()")
        if _greenhouse_select(element):
            if not demographic and re.fullmatch(r"(?:what do you identify as|how do you identify)\??", question.strip()):
                choices = [item.inner_text() for item in _select_options(element)]
                element.press("Escape")
                demographic = _demographic_options(choices)
            record = None if question_key(label) in ambiguous else _answer_record(records, label, config)
            value = record.get("value") if isinstance(record, dict) else record
            if demographic and not _required(element):
                _clear_select(element)
                approved[_control_key(element)] = _answer_value(element)
                continue
            chosen = None
            if demographic and _required(element):
                options = _select_options(element)
                choices = [item.inner_text().strip() for item in options if _nondisclosure(item.inner_text())]
                element.press("Escape")
                if len(choices) == 1:
                    chosen = choices[0]
            if chosen is None and value is not None and _scoped_legal_answer(label, record):
                chosen = _option_label(value)
            if chosen is not None:
                if not _choose_select(element, chosen):
                    return f"No unique supported option matches the saved answer for {label}."
                approved[_control_key(element)] = _answer_value(element)
            else:
                if not demographic and _required(element) and _answer_value(element)["selected"]:
                    # A required prefill still needs explicit review, even without a Clear button.
                    continue
                _clear_select(element)
                if not _required(element):
                    approved[_control_key(element)] = _answer_value(element)
            continue
        if tag == "select":
            demographic = demographic or _demographic_options(element.locator("option").all_text_contents())
        if demographic and not _required(element):
            _clear_answer(element)
            approved[_control_key(element)] = _answer_value(element)
            continue
        if demographic and tag == "select":
            # Required demographics prefer an offered nondisclosure option,
            # even when the platform preselected another value.
            options = element.locator("option")
            chosen = False
            for index in range(options.count()):
                option = options.nth(index)
                text = option.inner_text().strip().casefold()
                if _nondisclosure(text):
                    element.select_option(index=index)
                    approved[_control_key(element)] = element.input_value()
                    chosen = True
                    break
            if chosen:
                continue
        record = None if question in ambiguous else _answer_record(records, question, config)
        if record is None or kind == "file" or not _scoped_legal_answer(question, record):
            _clear_answer(element)
            if not _required(element):
                approved[_control_key(element)] = _answer_value(element)
            continue
        if isinstance(record, dict):
            value = record.get("value")
        else:
            value = record
        if value is None:
            continue
        if kind == "checkbox":
            if type(value) is not bool:
                continue
            element.set_checked(value)
        elif tag == "select":
            element.select_option(label=_option_label(value))
        else:
            error = _fill_exact_text(element, value)
            if error:
                return error
        approved[_control_key(element)] = _answer_value(element)


def _unanswered(form, approved=None, require_verified=False, uploaded_resume=None):
    problems = []
    if uploaded_resume:
        problem = _uploaded_resume_problem(form, uploaded_resume)
        if problem:
            problems.append(problem)
    fields = form.locator("input, select, textarea, [role='combobox'], [role='checkbox'], [role='radiogroup']")
    for i in range(fields.count()):
        element = fields.nth(i)
        kind = (element.get_attribute("type") or "").lower()
        role = element.get_attribute("role") or ""
        if kind in ("hidden", "submit", "button", "image") or element.is_disabled():
            continue
        if _select_proxy(element):
            continue
        if kind not in ("file", "radio", "checkbox") and not element.is_visible():
            if require_verified and kind != "hidden":
                if element.evaluate("el => String(el.value || '').trim()"):
                    problems.append(f"{_label(element)} (hidden answer needs review)")
            continue
        label = _label(element)
        required = _required(element)
        if kind == "radio":
            answered = element.evaluate(
                "el => [...(el.form || document).querySelectorAll('input[type=radio]')]"
                ".some(other => other.name === el.name && other.checked)"
            )
        elif kind == "checkbox" or role == "checkbox":
            answered = element.is_checked() if kind == "checkbox" else element.get_attribute("aria-checked") == "true"
        elif kind == "file":
            answered = bool(element.evaluate("el => el.files && el.files.length"))
        elif role == "combobox" and _greenhouse_select(element):
            state = _answer_value(element)
            answered = bool(state["selected"]) and not state["pendingText"] and state["proxyValid"]
        elif role in ("combobox", "radiogroup"):
            if role == "radiogroup" and element.locator("input[type=radio]").count():
                continue
            # Custom selection semantics vary. Don't assume typed text is a selection.
            problems.append(f"{label} (custom control needs review)")
            continue
        else:
            value = element.input_value().strip()
            answered = bool(value) and value.lower() not in ("-1", "select", "select one", "please select")
        key = _control_key(element)
        if answered and require_verified and key not in (approved or {}):
            problems.append(f"{label} (answer is not verified)")
        if key in (approved or {}) and _answer_value(element) != approved[key]:
            problems.append(f"{label} (value changed from the approved answer)")
        if required and not answered:
            problems.append(label)
        if element.get_attribute("aria-invalid") == "true":
            problems.append(f"{label} (platform validation error)")
        native_valid = element.evaluate("el => !el.willValidate || el.validity.valid")
        if not native_valid:
            problems.append(f"{label} (invalid value)")
    for error in _visible(form.locator("[role='alert'], .error-message, .field-error")):
        if error.inner_text().strip():
            problems.append(error.inner_text().strip())
    return list(dict.fromkeys(problems))

def _fill_basics(form, config, approved, records=None):
    profile = config.get("profile", {})
    parts = str(profile.get("name") or "").strip().split(None, 1)
    values = {
        "first_name": profile.get("first_name") or (parts[0] if parts else ""),
        "last_name": profile.get("last_name") or (parts[1] if len(parts) > 1 else ""),
        "email": profile.get("email", ""),
        "phone": profile.get("phone", ""),
    }
    for name, label in (("first_name", "First Name"), ("last_name", "Last Name"), ("email", "Email"), ("phone", "Phone")):
        record = (records or {}).get(question_key(label))
        value = record.get("value") if isinstance(record, dict) else record
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            return f"Saved {name} needs a nonempty text answer."
        explicit = profile.get(name)
        if explicit and str(explicit).strip().casefold() != value.strip().casefold():
            return f"Saved {name} conflicts with the verified profile."
        values[name] = value
    if records and (question_key("First Name") in records or question_key("Last Name") in records) and profile.get("name"):
        combined = " ".join((str(values["first_name"]) + " " + str(values["last_name"])).split()).casefold()
        if combined != " ".join(str(profile["name"]).split()).casefold():
            return "Saved first/last name split differs from the verified full name; review both parts."
    for name, value in values.items():
        for element in _visible(form.locator(f"input[name='{name}'], input#{name}")):
            if value in (None, ""):
                _clear_answer(element)
                if not _required(element):
                    approved[_control_key(element)] = _answer_value(element)
                continue
            current = element.input_value().strip()
            if current and current.casefold() != str(value).strip().casefold():
                return f"Existing {name} differs from the approved profile."
            if not current:
                error = _fill_exact_text(element, value)
                if error:
                    return error
            approved[_control_key(element)] = _answer_value(element)
    return None

def _uploaded_resume_problem(form, evidence):
    groups = form.locator(evidence["group_selector"])
    if groups.count() != 1:
        return "The verified resume upload control changed."
    group = groups.first
    names = _visible(group.locator(".file-upload__filename"))
    errors = _visible(group.locator(".helper-text--error, [role=alert]"))
    if (len(names) != 1 or names[0].inner_text().strip() != evidence["name"]
            or _visible(group.locator("[role=progressbar]"))
            or any(error.inner_text().strip() for error in errors)):
        return "The completed resume upload changed or has an error."
    return None


def _observe_resume_upload(page, path, config, evidence):
    """Chromium omits multipart file bytes from request data; observe native XHR.send."""
    binding = "__autoapply_upload_" + secrets.token_hex(8)
    restore = binding + "_restore"
    expected = {"name": path.name, "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    def record(source, observed):
        if source["frame"] != page.main_frame or not isinstance(observed, dict):
            return
        if any(observed.get(key) != value for key, value in expected.items()):
            return
        destination, key = observed.get("upload_url"), observed.get("key")
        if not isinstance(destination, str) or not isinstance(key, str):
            return
        target = urlparse(destination)
        fixture = approved_fixture_url(destination, config)
        if not fixture and (target.scheme != "https" or not target.hostname
                            or not target.hostname.endswith(".amazonaws.com")):
            return
        if (not key or key.startswith("/") or ".." in key.split("/")
                or target.query or target.fragment):
            return
        evidence.append({**expected, "upload_url": destination,
                         "url": destination.rstrip("/") + "/" + key})
    page.expose_binding(binding, record)
    page.evaluate("""([binding, restore, size]) => {
        const prototype = XMLHttpRequest.prototype;
        const originalOpen = prototype.open, originalSend = prototype.send;
        const requests = new WeakMap();
        function open(method, url) {
            requests.set(this, {method: String(method).toUpperCase(), url: new URL(url, location.href).href});
            return originalOpen.apply(this, arguments);
        }
        function send(body) {
            const request = requests.get(this);
            if (request?.method === 'POST' && body instanceof FormData) {
                const files = [...body.entries()].filter(([, value]) => value instanceof File);
                const keys = body.getAll('key');
                if (files.length === 1 && files[0][0] === 'file' && keys.length === 1
                        && typeof keys[0] === 'string' && files[0][1].size === size) {
                    const file = files[0][1], key = keys[0], url = request.url;
                    file.arrayBuffer().then(data => crypto.subtle.digest('SHA-256', data)).then(hash =>
                        window[binding]({name: file.name, size: file.size, key, upload_url: url,
                            sha256: [...new Uint8Array(hash)].map(byte => byte.toString(16).padStart(2, '0')).join('')})
                    ).catch(() => {});
                }
            }
            return originalSend.apply(this, arguments);
        }
        prototype.open = open; prototype.send = send;
        window[restore] = () => {
            if (prototype.open === open) prototype.open = originalOpen;
            if (prototype.send === send) prototype.send = originalSend;
        };
    }""", [binding, restore, expected["size"]])
    return restore


def _attach_resume(form, config, approved, uploaded_resume=None):
    path = resume_file(config)
    if path is None or not path.is_file():
        return "Approved resume file is missing."
    inputs = form.locator("input[type=file]")
    candidates = []
    for i in range(inputs.count()):
        element = inputs.nth(i)
        identity = " ".join((_label(element), element.get_attribute("name") or "", element.get_attribute("id") or "")).lower()
        if "resume" in identity or re.search(r"\bcv\b", identity):
            candidates.append(element)
    if len(candidates) != 1:
        return "A unique resume upload control could not be identified."
    element = candidates[0]
    group = element.locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' file-upload ')][1]")
    modern_upload = ("application--form" in (form.get_attribute("class") or "").split()
                     and group.count() == 1)
    if modern_upload:
        label_id = group.get_attribute("aria-labelledby") or ""
        if not re.fullmatch(r"[\w-]+", label_id) or uploaded_resume is None:
            return "The asynchronous resume upload control could not be bound."
        selector = '.file-upload[role="group"][aria-labelledby=' + json.dumps(label_id) + ']'
        if _visible(group.locator(".file-upload__filename")):
            return "An existing resume upload needs review before replacement."
        page = form.page
        responses, finished, observed = [], [], []
        def capture(response):
            if response.request.method == "POST":
                responses.append(response)
        def completed(request):
            finished.append(request)
        page.on("response", capture)
        page.on("requestfinished", completed)
        restore = None
        try:
            restore = _observe_resume_upload(page, path, config, observed)
            element.set_input_files(str(path))
            timeout = min(30, max(1, float(config.get("browser", {}).get("submission_timeout_seconds", 30))))
            deadline = datetime.now(timezone.utc).timestamp() + timeout
            while datetime.now(timezone.utc).timestamp() < deadline:
                if len(observed) > 1:
                    return "Multiple resume uploads were observed; review is required."
                matching = [response for response in responses if observed
                            and response.request.url == observed[0]["upload_url"]]
                if len(matching) > 1:
                    return "Multiple resume upload responses were observed; review is required."
                if matching:
                    response, evidence = matching[0], observed[0]
                    if not 200 <= response.status < 300:
                        return "The resume upload was rejected; submission stopped."
                    evidence["group_selector"] = selector
                    if (response.request in finished and response.url == response.request.url
                            and _uploaded_resume_problem(form, evidence) is None):
                        uploaded_resume.update(evidence)
                        return None
                if any(error.inner_text().strip() for error in _visible(group.locator(".helper-text--error"))):
                    return "The resume upload reported an error; submission stopped."
                page.wait_for_timeout(100)
            return "A completed upload of the approved resume bytes was not verified."
        except Exception as exc:
            return f"Resume upload failed ({type(exc).__name__}); submission stopped."
        finally:
            page.remove_listener("response", capture)
            page.remove_listener("requestfinished", completed)
            if restore:
                page.evaluate("key => window[key]();", restore)
    try:
        element.set_input_files(str(path))
        selected = element.evaluate("el => [...el.files].map(file => file.name)")
        if selected != [path.name]:
            return "Resume selection was not verified."
        value = _answer_value(element)
        if value != [{"name": path.name, "size": path.stat().st_size,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]:
            return "The selected resume bytes differ from the approved file."
        approved[_control_key(element)] = value
    except Exception as exc:
        return f"Resume upload failed ({type(exc).__name__}); submission stopped."
    return None

def _confirmation(page, expected_job=None, contract=None):
    if contract:
        actual, expected = urlparse(page.url), urlparse(contract["confirmation_url"])
        if actual.scheme != expected.scheme or actual.netloc != expected.netloc or actual.path != expected.path:
            return None
        if greenhouse_identity(contract["confirmation_url"]) and greenhouse_identity(page.url) != greenhouse_identity(contract["confirmation_url"]):
            return None
    for selector in CONFIRMATIONS:
        for element in _visible(page.locator(selector)):
            bound = element.get_attribute("data-job-id")
            if bound and expected_job and str(bound) != str(expected_job):
                continue
            text = element.inner_text().strip()
            if SUCCESS.search(text):
                return selector, text
    return None


def _submission_contract(page, job, form, fixture):
    if "application--form" not in (form.get_attribute("class") or "").split():
        return None
    contexts = page.evaluate("""() => {
        const data = window.__remixRouter?.state?.loaderData || window.__remixContext?.state?.loaderData || {};
        return Object.values(data).filter(value => value && value.jobPost).map(value => ({
            jobPostId: value.jobPostId, board: value.urlToken, title: value.jobPost.title,
            submitPath: value.submitPath, confirmationPath: value.confirmationPath
        }));
    }""")
    if len(contexts) != 1:
        raise ValueError("The Greenhouse renderer has no unique job context.")
    context = contexts[0]
    identity = greenhouse_identity(job_application_url(job))
    expected_id = identity[1] if identity else urlparse(page.url).path.rstrip("/").split("/")[-1]
    if str(context.get("jobPostId")) != expected_id or str(context.get("title", "")).strip().casefold() != str(job.get("title", "")).strip().casefold():
        raise ValueError("The Greenhouse renderer differs from the approved job.")
    if identity and context.get("board") != identity[0]:
        raise ValueError("The Greenhouse renderer differs from the approved board.")
    result = {}
    for source, destination in (("submitPath", "submit_url"), ("confirmationPath", "confirmation_url")):
        if not isinstance(context.get(source), str) or not context[source]:
            raise ValueError("The Greenhouse renderer is missing its application paths.")
        target = urljoin(page.url, context[source])
        if fixture:
            parsed, origin = urlparse(target), urlparse(page.url)
            if not approved_fixture_url(target, {"browser": {"allow_local_fixtures": True}}) or parsed.netloc != origin.netloc or parsed.path.rstrip("/").split("/")[-1] != expected_id:
                raise ValueError("The fixture application paths differ from the approved job.")
        elif greenhouse_identity(target) != identity:
            raise ValueError("The Greenhouse application paths differ from the approved job.")
        result[destination] = target
    return result


def _submission_action(page, job, form, contract, fixture):
    action = contract["submit_url"] if contract else urljoin(page.url, form.get_attribute("action") or page.url)
    if fixture:
        if not approved_fixture_url(action, {"browser": {"allow_local_fixtures": True}}):
            raise ValueError("The fixture form action is not isolated.")
    elif greenhouse_identity(action) != greenhouse_identity(job_application_url(job)):
        raise ValueError("The form action differs from the approved board and job.")
    return action


def _observe_json_response(page, action, payloads, timeout):
    binding = "__autoapply_response_" + secrets.token_hex(8)
    restore = binding + "_restore"
    def record(source, evidence):
        if source["frame"] != page.main_frame or not isinstance(evidence, dict):
            return
        if not isinstance(evidence.get("url"), str) or type(evidence.get("status")) is not int:
            return
        payloads[(evidence["url"], evidence["status"])] = (
            evidence.get("verified") is True, evidence.get("payload"),
        )
    page.expose_binding(binding, record)
    page.evaluate("""([action, binding, restore, timeout]) => {
        const original = window.fetch;
        const expected = new URL(action, location.href).href;
        const wrapped = async function(input, init) {
            const method = String(init?.method || input?.method || 'GET').toUpperCase();
            const requested = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, location.href).href;
            const response = await original.apply(this, arguments);
            if (method === 'POST' && requested === expected &&
                    (response.headers.get('content-type') || '').toLowerCase().includes('application/json')) {
                let verified = false, payload = null, timer;
                try {
                    const text = await Promise.race([
                        response.clone().text(),
                        new Promise((_, reject) => {timer = setTimeout(() => reject(new Error('Receipt timeout')), timeout);})
                    ]);
                    if (text.length <= 65536) {
                        payload = JSON.parse(text);
                        verified = payload !== null && typeof payload === 'object' && !Array.isArray(payload);
                    }
                } catch (_) {
                    verified = false;
                } finally {
                    clearTimeout(timer);
                }
                await window[binding]({url: response.url, status: response.status, verified, payload});
            }
            return response;
        };
        window.fetch = wrapped;
        window[restore] = () => {if (window.fetch === wrapped) window.fetch = original;};
    }""", [action, binding, restore, min(5000, timeout * 1000)])
    return restore

def _matching_response(response, job_url, form_action, fixture):
    if response.request.method != "POST":
        return False
    body = unquote(response.request.post_data or "")
    if "first_name" not in body or "email" not in body:
        return False
    if fixture:
        parsed = urlparse(response.url)
        return parsed.hostname in ("localhost", "127.0.0.1", "::1") and response.url.split("?")[0] == form_action.split("?")[0]
    identity = greenhouse_identity(job_url)
    if greenhouse_identity(response.url) == identity:
        target = urlparse(response.url)
        if any(part in target.path.lower() for part in ("/upload", "/resume", "/attachment")):
            return False
        action = urlparse(form_action)
        if greenhouse_identity(form_action) == identity and target.path == action.path:
            return True
        board, job_id = identity
        if target.path.rstrip("/") in (
            f"/{board}/jobs/{job_id}", f"/{board}/jobs/{job_id}/applications",
            f"/v1/boards/{board}/jobs/{job_id}",
        ):
            return True
    # Some classic forms POST to their exact application action.
    action = urlparse(form_action)
    target = urlparse(response.url)
    return (
        identity is not None and action.hostname in ("boards.greenhouse.io", "job-boards.greenhouse.io")
        and action.hostname == target.hostname and action.path == target.path
        and identity[1] in action.path.split("/")
    )

def apply_unattended(page, job, config, unattended=False, on_before_submit=None):
    try:
        url = job_application_url(job)
    except ValueError as exc:
        return "paused", str(exc)
    fixture = approved_fixture_url(url, config)
    if not greenhouse_identity(url) and not fixture:
        return "paused", "The approved URL is not a supported Greenhouse job origin."
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:
        return "failed", f"Navigation failed ({type(exc).__name__})."
    challenge = handle_challenge(page, unattended=unattended)
    if challenge:
        return challenge, "A blocking challenge needs human resolution."
    if not fixture and greenhouse_identity(page.url) != greenhouse_identity(url):
        return "paused", "Navigation no longer points to the approved board and job ID."
    expected_id = greenhouse_identity(url)[1] if greenhouse_identity(url) else urlparse(url).path.rstrip("/").split("/")[-1]
    headings = [element.inner_text().strip().casefold() for element in _visible(page.locator("h1"))]
    if str(job.get("title") or "").strip().casefold() not in headings:
        return "paused", "The rendered job title does not match the approved job metadata."
    descriptions = _visible(page.locator("#content, [data-testid='job-description'], .job__description"))
    if descriptions:
        normalize = lambda value: " ".join(description_text(value).split()).casefold()
        approved_description = normalize(job.get("description"))
        if approved_description not in [normalize(element.inner_text()) for element in descriptions]:
            return "paused", "The live job description differs from the approved full description; refresh and review it."
    elif not fixture:
        return "paused", "The live job description cannot be bound to the reviewed metadata."
    forms = _visible(page.locator("form#application_form, form#application-form, form[data-testid='application-form']"))
    if len(forms) != 1:
        return "paused", "This form layout is not supported; review it manually."
    form = forms[0]
    try:
        contract = _submission_contract(page, job, form, fixture)
        approved_action = _submission_action(page, job, form, contract, fixture)
    except ValueError as exc:
        return "paused", str(exc)
    approved = {}
    try:
        saved = application_answers(config, job)
    except Exception as exc:
        return "paused", f"Answer memory needs review ({type(exc).__name__})."
    error = _fill_basics(form, config, approved, saved)
    if error:
        return "paused", error
    uploaded_resume = {}
    error = _attach_resume(form, config, approved, uploaded_resume)
    if error:
        return "failed", error
    try:
        error = _explicit_answers(form, job, config, approved, saved)
    except Exception as exc:
        return "paused", f"Answer preparation needs review ({type(exc).__name__})."
    if error:
        return "paused", error
    if _confirmation(page):
        return "paused", "Confirmation was already present before this submission; reconcile existing history."
    reviewed_unknown = False
    while True:
        problems = _unanswered(form, approved, require_verified=unattended or not reviewed_unknown, uploaded_resume=uploaded_resume)
        if not problems:
            break
        if unattended:
            return "paused", "Unresolved required fields: " + "; ".join(problems)
        print("Resolve these fields in the browser: " + "; ".join(problems))
        if input("Press Enter to recheck, or type skip: ").strip().lower() == "skip":
            return "skipped", "User stopped before submission."
        reviewed_unknown = True
    if not unattended and reviewed_unknown:
        for element in _visible(form.locator("input, select, textarea"), skip_proxies=True):
            kind = (element.get_attribute("type") or "").lower()
            if kind not in ("hidden", "submit", "button", "image") and not element.is_disabled():
                approved[_control_key(element)] = _answer_value(element)
    buttons = _visible(form.locator("button#submit_app, button[type=submit], input[type=submit]"))
    if len(buttons) != 1 or not buttons[0].is_enabled():
        return "paused", "A unique enabled submission button is unavailable."
    if on_before_submit is None:
        return "paused", "The submission authorization and attempt guard is required."
    if not unattended:
        if input("Review the completed form. Type submit to authorize this submission, or skip: ").strip().lower() != "submit":
            return "skipped", "User stopped before submission."
    # Recheck the actual page immediately before reserving the attempt.
    if handle_challenge(page, unattended=unattended):
        return "paused", "A blocking challenge appeared before submission."
    problems = _unanswered(form, approved, require_verified=unattended, uploaded_resume=uploaded_resume)
    if problems:
        return "paused", "Required fields changed before submission: " + "; ".join(problems)
    try:
        current_contract = _submission_contract(page, job, form, fixture)
        action = _submission_action(page, job, form, current_contract, fixture)
    except ValueError as exc:
        return "paused", str(exc)
    if current_contract != contract or action != approved_action:
        return "paused", "The approved application paths changed before submission."
    responses = []
    completed_requests = []
    json_payloads = {}
    def capture(response):
        if _matching_response(response, url, action, fixture):
            responses.append(response)
    def completed(request):
        completed_requests.append(request)
    page.on("response", capture)
    page.on("requestfinished", completed)
    restore = None
    permit = {"armed": False, "sent": False}
    def guarded_request(route):
        if route.request.method == "POST":
            if not permit["armed"] or permit["sent"]:
                route.abort()
                return
            if uploaded_resume:
                try:
                    body = route.request.post_data_json
                    application = body.get("job_application") if isinstance(body, dict) else None
                    matches = (isinstance(application, dict)
                               and application.get("resume_url") == uploaded_resume["url"]
                               and application.get("resume_url_filename") == uploaded_resume["name"])
                except (ValueError, TypeError, KeyError):
                    matches = False
                if not matches:
                    permit["sent"] = True
                    route.abort()
                    return
            permit["sent"] = True
        route.fallback()
    page.route(action, guarded_request)
    try:
        timeout = min(60, max(1, float(config.get("browser", {}).get("submission_timeout_seconds", 30))))
        if contract:
            restore = _observe_json_response(page, action, json_payloads, timeout)
        attempt_id = on_before_submit()
        permit["armed"] = True
        deadline = datetime.now(timezone.utc).timestamp() + timeout
        buttons[0].click(no_wait_after=True, timeout=timeout * 1000)
        while datetime.now(timezone.utc).timestamp() < deadline:
            for response in responses:
                if response.status in (400, 422):
                    return "failed", json.dumps({
                        "event": "submission_rejected", "attempt_id": attempt_id,
                        "job_url": url, "response_url": response.url, "http_status": response.status,
                    }, sort_keys=True)
                if (200 <= response.status < 300 and response.request in completed_requests
                        and _confirmation(page, expected_id, contract)):
                    # JSON validation errors can be returned with a 200 status.
                    payload = None
                    if "application/json" in response.headers.get("content-type", "").lower():
                        verified, payload = json_payloads.get((response.url, response.status), (False, None))
                        if not verified:
                            return "unconfirmed", "The accepted response body could not be verified."
                    if isinstance(payload, dict) and (payload.get("errors") or payload.get("error") or payload.get("success") is False):
                        return "failed", json.dumps({
                            "event": "submission_rejected", "attempt_id": attempt_id,
                            "job_url": url, "http_status": response.status,
                        }, sort_keys=True)
                    return "confirmed_submitted", json.dumps({
                        "event": "submission_confirmed", "attempt_id": attempt_id,
                        "job_id": job["id"], "job_url": job["job_url"], "application_url": url,
                        "response_url": response.url, "http_status": response.status,
                        "confirmed_at_utc": datetime.now(timezone.utc).isoformat(),
                        "response_completed": True,
                    }, sort_keys=True)
            # A renderer navigation can detach the old form between locator reads.
            # After clicking, use response/confirmation evidence rather than refilling it.
            page.wait_for_timeout(250)
        return "unconfirmed", "No matching accepted response and new confirmation were observed."
    except SubmissionBlocked as exc:
        return "deferred", str(exc)
    finally:
        page.remove_listener("response", capture)
        page.remove_listener("requestfinished", completed)
        page.unroute(action, guarded_request)
        if restore:
            try:
                page.evaluate("key => {if (typeof window[key] === 'function') window[key]();}", restore)
            except Exception:
                pass
