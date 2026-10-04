"""
linkedin_apply.py — Automates LinkedIn Easy Apply using Playwright.
"""

import time
import random
from pathlib import Path
from playwright.sync_api import Page, BrowserContext, TimeoutError as PwTimeout
from utils import human_delay, random_scroll, random_mouse_move, slow_type


def ensure_linkedin_login(page: Page, config: dict, logger) -> bool:
    """Check if logged into LinkedIn; if not, log in programmatically."""
    # Check if we're already logged in
    if "feed" in page.url or "mynetwork" in page.url or "/in/" in page.url:
        return True

    # Check for login wall / sign-in prompt
    sign_in_modal = page.locator(
        "button:has-text('Sign in'), "
        "a:has-text('Sign in'), "
        "input[name='session_key']"
    )
    if sign_in_modal.count() == 0:
        return True  # No login wall detected

    logger.info("    🔐 LinkedIn login wall detected — signing in...")
    creds = config.get("credentials", {}).get("linkedin", {})
    email = creds.get("email", "")
    password = creds.get("password", "")

    if not email or not password or "YOUR_" in email:
        logger.error("    ❌ LinkedIn credentials not set in config.yaml!")
        return False

    try:
        # Close any modal first
        close_btn = page.locator("button[aria-label='Dismiss'], button.modal__dismiss")
        if close_btn.count() > 0:
            close_btn.first.click()
            time.sleep(1)

        # Navigate to login page
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=15000)
        time.sleep(2)

        # Fill credentials
        email_input = page.locator("input#username, input[name='session_key']")
        pass_input = page.locator("input#password, input[name='session_password']")

        if email_input.count() > 0 and pass_input.count() > 0:
            email_input.first.fill("")
            slow_type(email_input.first, email)
            time.sleep(random.uniform(0.5, 1))
            pass_input.first.fill("")
            slow_type(pass_input.first, password)
            time.sleep(random.uniform(0.5, 1))

            # Click Sign in
            submit = page.locator("button[type='submit'], button:has-text('Sign in')")
            if submit.count() > 0:
                submit.first.click()
                time.sleep(5)

                # Check for CAPTCHA or 2FA
                if "checkpoint" in page.url or "challenge" in page.url:
                    logger.warning("    ⚠️ LinkedIn CAPTCHA/2FA detected — waiting 30s for manual solve...")
                    time.sleep(30)

                if "feed" in page.url or "mynetwork" in page.url:
                    logger.info("    ✅ LinkedIn login successful!")
                    return True

        logger.warning(f"    ⚠️ LinkedIn login may have failed. Current URL: {page.url[:60]}")
        return "login" not in page.url.lower()

    except Exception as e:
        logger.error(f"    ❌ LinkedIn login error: {e}")
        return False


def apply_to_linkedin_job(
    page: Page,
    job: dict,
    config: dict,
    logger,
    tracker=None,
) -> bool:
    """
    Navigate to a LinkedIn job and submit Easy Apply.
    Returns True if successfully applied, False otherwise.
    Pass `tracker` to enable saving skipped jobs to the manual-apply CSV.
    """
    url = job["apply_url"]
    title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    screening = config["screening"]
    resume_path = str(Path(config["profile"]["resume_path"]).resolve())

    logger.info(f"  📝 LinkedIn: Applying to '{title}' at {company}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(3, 5))
        random_scroll(page)
        time.sleep(random.uniform(1, 2))

        # Debug: save screenshot to see what the page looks like
        screenshot_dir = Path("logs/screenshots")
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() else "_" for c in title[:30])
        page.screenshot(path=str(screenshot_dir / f"li_{safe_name}.png"))
        logger.info(f"    📸 Screenshot saved: logs/screenshots/li_{safe_name}.png")
        logger.info(f"    📍 Current URL: {page.url[:80]}")

        # --- Check if job post is verified (ONLY on LinkedIn pages) ---
        # External career sites (Infosys, Workday, etc.) are always trusted
        current_url = page.url.lower()
        is_linkedin_page = "linkedin.com" in current_url

        if is_linkedin_page:
            is_verified = page.evaluate("""() => {
                const body = document.body.innerText.toLowerCase();
                const html = document.body.innerHTML.toLowerCase();
                
                // Easy Apply button = legitimate LinkedIn post
                const easyApply = document.querySelector("button[class*='jobs-apply-button'], button[aria-label*='Easy Apply']");
                if (easyApply) return true;
                
                // Check for verification indicators
                if (body.includes('verified') && !body.includes('not verified')) return true;
                if (html.includes('verification-badge') || html.includes('verified-badge')) return true;
                if (html.includes('verified employer') || html.includes('data-test-verified')) return true;
                
                // Blue checkmark badge
                const badges = document.querySelectorAll('[class*="verified"], [aria-label*="verified"], [aria-label*="Verified"]');
                if (badges.length > 0) return true;
                
                // "Promoted by hirer" = real employer
                if (body.includes('promoted by hirer')) return true;
                
                // Company page link = legitimate
                const companyLinks = document.querySelectorAll('a[href*="/company/"]');
                if (companyLinks.length > 0) return true;
                
                // Apply button present = legitimate post
                const applyBtn = document.querySelector("button[class*='apply'], a[class*='apply']");
                if (applyBtn) return true;
                
                return false;
            }""")

            if not is_verified:
                logger.info(f"    ⏭️ Unverified job post — skipping (no verified badge)")
                return False

        # --- Check if it's Easy Apply ---
        easy_apply_btn = page.locator(
            "button.jobs-apply-button, "
            "button[aria-label*='Easy Apply'], "
            "button:has-text('Easy Apply')"
        )

        if easy_apply_btn.count() > 0:
            # --- Easy Apply flow ---
            easy_apply_btn.first.click()
            time.sleep(random.uniform(2, 3))

            # Check for "Job search safety reminder" (unverified post)
            safety_warning = page.locator("text=Job search safety reminder")
            if safety_warning.count() > 0 and safety_warning.first.is_visible():
                logger.info(f"    ⏭️ Unverified job post — skipping")
                # Close the dialog
                close_btn = page.locator("button:has-text('Review job post'), button[aria-label='Dismiss']")
                if close_btn.count() > 0:
                    close_btn.first.click()
                    time.sleep(1)
                return False

            # Also dismiss "Continue applying" dialog if it appears
            continue_btn = page.locator("button:has-text('Continue applying')")
            if continue_btn.count() > 0 and continue_btn.first.is_visible():
                continue_btn.first.click()
                time.sleep(random.uniform(1, 2))
        else:
            # --- Regular Apply (external redirect) — save for manual apply ---
            # Non-Easy-Apply jobs redirect to Hired, Greenhouse, Workday, etc.
            # Save them to the manual-apply list so Giri can apply directly.
            apply_btn = page.locator(
                "button:has-text('Apply'), "
                "a:has-text('Apply'), "
                "button.jobs-apply-button"
            )
            if apply_btn.count() == 0:
                logger.info(f"    ⏭️ No Apply button found — saved for manual apply")
                if tracker:
                    tracker.save_manual_candidate(
                        "linkedin", title, company, url, "no_apply_button"
                    )
                return False

            # Check if the apply button/link points to an external domain
            try:
                apply_href = apply_btn.first.get_attribute("href") or ""
                if apply_href and "linkedin.com" not in apply_href:
                    logger.info(f"    📋 External apply link — saved for manual apply: {apply_href[:60]}")
                    if tracker:
                        tracker.save_manual_candidate(
                            "linkedin", title, company, apply_href, "external_redirect"
                        )
                    return False
            except Exception:
                pass

            # No Easy Apply button, LinkedIn-hosted Apply (opens new tab) —
            # save for manual, skip to avoid timeout trap
            logger.info(f"    📋 No Easy Apply — saved for manual apply")
            if tracker:
                tracker.save_manual_candidate(
                    "linkedin", title, company, url, "no_easy_apply_external_redirect"
                )
            return False

        # --- Handle multi-step form ---
        max_steps = 10  # Safety limit
        for step in range(max_steps):
            time.sleep(random.uniform(1.5, 2.5))

            # Save debug screenshot of the form state
            if step == 0:
                page.screenshot(path=str(screenshot_dir / f"li_{safe_name}_form.png"))
                logger.info(f"    📸 Form screenshot saved (step {step})")

            # Check for "Submit application" button (final step)
            submit_btn = page.locator(
                "button[aria-label*='Submit application'], "
                "button[aria-label*='Submit'], "
                "button:has-text('Submit application'), "
                "button:has-text('Submit'), "
                "footer button:has-text('Submit'), "
                "div[class*='footer'] button:has-text('Submit')"
            )
            for i in range(submit_btn.count()):
                btn = submit_btn.nth(i)
                try:
                    if btn.is_visible() and btn.is_enabled():
                        btn.click()
                        time.sleep(random.uniform(2, 3))

                        # Handle the "Done" / post-submit dialog
                        done_btn = page.locator(
                            "button:has-text('Done'), "
                            "button:has-text('Close'), "
                            "button:has-text('Not now'), "
                            "button[aria-label*='Dismiss']"
                        )
                        if done_btn.count() > 0:
                            try:
                                done_btn.first.click()
                            except Exception:
                                pass

                        logger.info(f"    ✅ Applied successfully!")
                        return True
                except Exception:
                    continue

            # --- Fill form fields ---
            _fill_linkedin_form_fields(page, screening, resume_path, logger)

            # Click "Next" or "Review" button — use broad selectors
            next_btn = page.locator(
                "button[aria-label*='Continue to next step'], "
                "button[aria-label*='Continue'], "
                "button[aria-label*='Review'], "
                "button[aria-label*='next'], "
                "button:has-text('Next'), "
                "button:has-text('Review'), "
                "button:has-text('Continue'), "
                "footer button.artdeco-button--primary, "
                "div[class*='footer'] button[class*='primary']"
            )
            clicked = False
            for i in range(next_btn.count()):
                btn = next_btn.nth(i)
                try:
                    if btn.is_visible() and btn.is_enabled():
                        btn_text = btn.inner_text().strip().lower()
                        # Don't click "Submit" here — that's handled above
                        if "submit" not in btn_text:
                            btn.click()
                            time.sleep(random.uniform(1.5, 2.5))
                            clicked = True
                            break
                except Exception:
                    continue

            if not clicked:
                # Last resort: try any primary/action button in the modal
                modal_btn = page.locator(
                    "div[class*='easy-apply'] button[class*='primary'], "
                    "div[role='dialog'] button[class*='primary'], "
                    "div[class*='artdeco-modal'] button[class*='primary']"
                )
                if modal_btn.count() > 0:
                    try:
                        modal_btn.first.click()
                        time.sleep(2)
                        clicked = True
                    except Exception:
                        pass

                if not clicked:
                    # Take a screenshot to debug what we're stuck on
                    page.screenshot(path=str(screenshot_dir / f"li_{safe_name}_stuck.png"))
                    logger.info(f"    📸 Stuck screenshot saved")
                    break

        logger.warning(f"    ⚠️ Reached max steps without submitting")
        _close_application_dialog(page)
        return False

    except PwTimeout:
        logger.warning(f"    ⏱️ Timeout loading page")
        return False
    except Exception as e:
        logger.error(f"    ❌ Error: {e}")
        _close_application_dialog(page)
        return False


def _fill_linkedin_form_fields(
    page: Page, screening: dict, resume_path: str, logger
):
    """Fill in common LinkedIn Easy Apply form fields.
    
    LinkedIn 2026 uses obfuscated CSS classes and NO div[role='dialog'].
    Only reliable approach: find all visible inputs, match via label[for=id].
    """

    # --- Dismiss any "Not now" / "Update profile" / premium dialogs ---
    for dismiss_text in ["Not now", "Dismiss", "Skip"]:
        try:
            btn = page.locator(f"button:has-text('{dismiss_text}')")
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                time.sleep(0.5)
        except Exception:
            pass

    # --- Resume upload ---
    file_input = page.locator("input[type='file']")
    if file_input.count() > 0:
        try:
            file_input.first.set_input_files(resume_path)
            time.sleep(1)
            logger.info(f"    📄 Resume uploaded")
        except Exception:
            pass

    # --- Helper: get label text for any input using JavaScript ---
    def get_label_for(element) -> str:
        try:
            return (element.evaluate("""el => {
                if (el.id) {
                    try {
                        const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
                        if (label) return label.innerText;
                    } catch(e) {}
                }
                let p = el.parentElement;
                for (let i = 0; i < 6 && p; i++) {
                    const labels = p.querySelectorAll('label, span');
                    for (const l of labels) {
                        const t = l.innerText?.trim();
                        if (t && t.length > 3 && !t.includes('Invalid') && l !== el) return t;
                    }
                    p = p.parentElement;
                }
                return '';
            }""") or "").lower().strip()
        except Exception:
            return ""

    # --- Fill ALL visible text/tel/number inputs ---
    # Strategy: fill EVERYTHING with "2" first, then override specific fields
    all_inputs = page.locator("input")
    filled_count = 0

    for i in range(all_inputs.count()):
        inp = all_inputs.nth(i)
        try:
            if not inp.is_visible():
                continue
            
            inp_type = (inp.get_attribute("type") or "").lower()
            
            # Skip non-fillable input types
            if inp_type in ("file", "hidden", "radio", "checkbox", "submit", "button", "search", "password", "image"):
                continue

            current_val = inp.input_value()
            if current_val:
                continue  # Already filled

            placeholder = (inp.get_attribute("placeholder") or "").lower()
            # Skip search bars
            if "looking for" in placeholder or "search" in placeholder:
                continue

            # Get label text
            label_text = get_label_for(inp)
            ctx = f"{label_text} {placeholder}"

            # Fill based on context — most specific matches first
            if any(kw in ctx for kw in ["phone", "mobile"]):
                inp.fill("9666379063")
                logger.info(f"    ✏️ Phone → 9666379063")
            elif inp_type == "tel" and not any(kw in ctx for kw in ["ctc", "salary", "notice"]):
                # type=tel but no label → probably phone
                inp.fill("9666379063")
            elif any(kw in ctx for kw in ["email", "e-mail"]):
                inp.fill("manoharusa21@gmail.com")
                logger.info(f"    ✏️ Email → manoharusa21@gmail.com")
            elif "expected" in ctx and any(kw in ctx for kw in ["ctc", "salary", "package"]):
                inp.fill(screening["expected_ctc"])
                logger.info(f"    ✏️ Expected CTC → {screening['expected_ctc']}")
            elif "current" in ctx and any(kw in ctx for kw in ["ctc", "salary", "package"]):
                inp.fill(screening.get("current_ctc", "5 LPA"))
                logger.info(f"    ✏️ Current CTC → {screening.get('current_ctc', '5 LPA')}")
            elif any(kw in ctx for kw in ["ctc", "salary", "compensation", "pay", "package",
                                           "remuneration", "stipend"]):
                inp.fill(screening["expected_ctc"])
                logger.info(f"    ✏️ CTC → {screening['expected_ctc']}")
            elif any(kw in ctx for kw in ["notice", "joining time", "start date"]):
                inp.fill(screening["notice_period"])
                logger.info(f"    ✏️ Notice → {screening['notice_period']}")
            elif any(kw in ctx for kw in ["city", "location", "relocat", "preferred location",
                                           "current location", "where are you"]):
                inp.fill("Hyderabad")
            elif any(kw in ctx for kw in ["gpa", "cgpa", "grade", "percentage", "score"]):
                inp.fill("3.5")
            elif any(kw in ctx for kw in ["linkedin", "portfolio", "github", "url", "website",
                                           "profile link"]):
                inp.fill("https://linkedin.com/in/manohar511")
            elif any(kw in ctx for kw in ["age", "date of birth", "dob"]):
                inp.fill("25")
            elif any(kw in ctx for kw in ["gender", "male", "female"]):
                inp.fill("Male")
            elif any(kw in ctx for kw in ["internship", "duration", "commit", "months"]):
                inp.fill("6")
            elif any(kw in ctx for kw in ["graduation", "passed", "batch", "passing year"]):
                inp.fill(screening.get("graduation_year", "2024"))
            elif any(kw in ctx for kw in ["education", "degree", "qualification", "highest"]):
                inp.fill(screening.get("highest_education", "Master's"))
            elif any(kw in ctx for kw in ["how did you hear", "how did you find",
                                             "where did you hear", "source", "referral source",
                                             "hear about"]):
                inp.fill("LinkedIn")
                logger.info(f"    ✏️ {label_text[:50]} → LinkedIn")
            elif any(kw in ctx for kw in ["employed by", "worked at", "worked for",
                                           "previously employed", "been employed",
                                           "former employee", "past employee"]):
                inp.fill("No")
                logger.info(f"    ✏️ {label_text[:50]} → No")
            else:
                # DEFAULT: fill with "2" — covers all experience/years questions
                inp.fill("2")
                if label_text:
                    logger.info(f"    ✏️ {label_text[:50]} → 2")

            filled_count += 1
        except Exception:
            continue

    if filled_count > 0:
        logger.info(f"    ✏️ Filled {filled_count} field(s)")

    # --- Fill TEXTAREA elements ---
    textareas = page.locator("textarea")
    for i in range(textareas.count()):
        ta = textareas.nth(i)
        try:
            if not ta.is_visible():
                continue
            if ta.input_value():
                continue
            label_text = get_label_for(ta)
            if any(kw in label_text for kw in ["cover", "letter", "why", "about yourself", "summary"]):
                ta.fill("I am an experienced Python Developer with a Master's in Data Analytics from Northeastern University. I have hands-on experience with Python, FastAPI, PostgreSQL, Docker, AWS, and ML/AI tools. I am eager to contribute to your team.")
            elif any(kw in label_text for kw in ["additional", "comment", "note", "message"]):
                ta.fill("Looking forward to this opportunity.")
            else:
                ta.fill("2 years of relevant experience. Open to relocation.")
        except Exception:
            continue

    # --- Fill SELECT dropdowns ---
    all_selects = page.locator("select")
    for i in range(all_selects.count()):
        sel = all_selects.nth(i)
        try:
            if not sel.is_visible():
                continue

            label_text = get_label_for(sel)
            
            # Skip language selector, country code, email (usually pre-filled)
            if any(kw in label_text for kw in ["language", "country code", "email"]):
                continue

            options = sel.locator("option")
            opt_count = options.count()
            if opt_count <= 1:
                continue

            # Check if already selected (non-default)
            try:
                selected_val = sel.input_value()
                if selected_val:
                    first_val = options.nth(0).get_attribute("value") or ""
                    if selected_val != first_val:
                        continue  # Already has a meaningful selection
            except Exception:
                pass

            # Collect option texts
            opt_texts = []
            for j in range(opt_count):
                try:
                    opt_texts.append(options.nth(j).inner_text().lower().strip())
                except Exception:
                    opt_texts.append("")

            selected_idx = None

            # Context-aware option selection
            if any(kw in label_text for kw in ["experience", "years"]):
                # Pick lowest experience range
                for j, t in enumerate(opt_texts):
                    if any(p in t for p in ["0", "1", "2", "fresher", "entry", "less"]):
                        selected_idx = j
                        break
            elif any(kw in label_text for kw in ["education", "degree", "qualification"]):
                for j, t in enumerate(opt_texts):
                    if any(p in t for p in ["master", "post grad", "pg", "m.s", "m.tech"]):
                        selected_idx = j
                        break
            elif any(kw in label_text for kw in ["notice", "join", "start"]):
                for j, t in enumerate(opt_texts):
                    if any(p in t for p in ["immediate", "15", "1 month", "less", "0"]):
                        selected_idx = j
                        break
            elif any(kw in label_text for kw in ["location", "city", "relocat"]):
                for j, t in enumerate(opt_texts):
                    if any(p in t for p in ["hyderabad", "bangalore", "bengaluru", "remote", "any"]):
                        selected_idx = j
                        break
            elif any(kw in label_text for kw in ["country"]) and "code" not in label_text:
                for j, t in enumerate(opt_texts):
                    if t.strip() == "india":
                        selected_idx = j
                        break
            elif any(kw in label_text for kw in ["how did you hear", "hear about", "source",
                                                   "where did you", "referral"]):
                for j, t in enumerate(opt_texts):
                    if any(p in t for p in ["linkedin", "job board", "online", "internet", "social"]):
                        selected_idx = j
                        break
            elif any(kw in label_text for kw in ["employed by", "worked at", "been employed",
                                                   "previously", "former", "past employee"]):
                for j, t in enumerate(opt_texts):
                    if "no" == t.strip():
                        selected_idx = j
                        break

            # Generic: prefer "Yes" / positive options
            if selected_idx is None:
                for j in range(1, opt_count):
                    t = opt_texts[j]
                    if any(kw in t for kw in ["yes", "authorized", "will", "immediately",
                                               "willing", "agree", "true"]):
                        selected_idx = j
                        break

            # Fallback: select first non-placeholder option
            if selected_idx is None:
                selected_idx = 1

            sel.select_option(index=selected_idx)
            if label_text:
                logger.info(f"    ✏️ Selected: {label_text[:40]} → {opt_texts[selected_idx]}")
        except Exception:
            continue

    # --- Radio buttons / Yes-No questions ---
    # Use pure JavaScript — LinkedIn's custom radio components break Playwright selectors
    try:
        clicked_count = page.evaluate("""() => {
            let clicked = 0;
            // Find all radio inputs on the page
            const radios = document.querySelectorAll('input[type="radio"]');
            const radioGroups = {};
            
            // Group radios by name
            radios.forEach(radio => {
                const name = radio.name || radio.id || Math.random();
                if (!radioGroups[name]) radioGroups[name] = [];
                radioGroups[name].push(radio);
            });
            
            // For each group, find and click the "Yes" option
            for (const [name, group] of Object.entries(radioGroups)) {
                // Skip if already has a selection
                if (group.some(r => r.checked)) continue;
                
                for (const radio of group) {
                    // Check the radio's label text
                    let labelText = '';
                    
                    // Method 1: label[for=id]
                    if (radio.id) {
                        const label = document.querySelector('label[for="' + CSS.escape(radio.id) + '"]');
                        if (label) labelText = label.innerText.trim();
                    }
                    
                    // Method 2: parent label
                    if (!labelText) {
                        const parentLabel = radio.closest('label');
                        if (parentLabel) labelText = parentLabel.innerText.trim();
                    }
                    
                    // Method 3: next sibling text
                    if (!labelText && radio.nextElementSibling) {
                        labelText = radio.nextElementSibling.innerText?.trim() || '';
                    }
                    
                    // Method 4: next sibling of parent (common LinkedIn pattern)
                    if (!labelText) {
                        const parent = radio.parentElement;
                        if (parent && parent.nextElementSibling) {
                            labelText = parent.nextElementSibling.innerText?.trim() || '';
                        }
                    }
                    
                    if (labelText.toLowerCase() === 'yes') {
                        radio.click();
                        // Also dispatch events to trigger LinkedIn's framework
                        radio.dispatchEvent(new Event('change', { bubbles: true }));
                        radio.dispatchEvent(new Event('input', { bubbles: true }));
                        clicked++;
                        break;
                    }
                }
            }
            return clicked;
        }""")
        if clicked_count > 0:
            logger.info(f"    ✏️ Selected 'Yes' for {clicked_count} radio question(s)")
            time.sleep(0.5)
    except Exception:
        pass
    
    # Fallback: also try clicking label elements directly via Playwright
    try:
        yes_labels = page.locator("label")
        for i in range(yes_labels.count()):
            lbl = yes_labels.nth(i)
            try:
                if not lbl.is_visible():
                    continue
                txt = lbl.inner_text().strip()
                if txt == "Yes":
                    lbl.click()
                    time.sleep(0.3)
            except Exception:
                continue
    except Exception:
        pass


def _handle_external_apply(ext_page: Page, config: dict, resume_path: str, logger) -> bool:
    """Try to fill and submit a form on an external career site."""
    profile = config["profile"]
    screening = config["screening"]
    url = ext_page.url.lower()

    try:
        # First: look for "Apply With LinkedIn" button (PwC, Workday, etc.)
        linkedin_apply = ext_page.locator(
            "button:has-text('Apply With LinkedIn'), "
            "button:has-text('Apply with LinkedIn'), "
            "a:has-text('Apply With LinkedIn'), "
            "a:has-text('Apply with LinkedIn'), "
            "button:has-text('LinkedIn'), "
            "a[class*='linkedin']"
        )
        if linkedin_apply.count() > 0:
            try:
                linkedin_apply.first.click()
                time.sleep(5)
                logger.info(f"    🔗 Clicked 'Apply With LinkedIn'")
                # If it opens LinkedIn OAuth, it will use our saved session
                # Wait for redirect back
                time.sleep(5)
                return True
            except Exception:
                pass
        # Upload resume if file input exists
        file_input = ext_page.locator("input[type='file']")
        if file_input.count() > 0:
            try:
                file_input.first.set_input_files(resume_path)
                time.sleep(1)
                logger.info(f"    📄 Resume uploaded on external site")
            except Exception:
                pass

        # Fill common form fields by label/placeholder/name
        field_map = {
            "name": profile["name"],
            "full_name": profile["name"],
            "first_name": profile["name"].split()[0],
            "last_name": profile["name"].split()[-1],
            "email": profile["email"],
            "phone": profile["phone"],
            "mobile": profile["phone"],
            "linkedin": "https://linkedin.com/in/manohar511",
            "location": "Hyderabad",
            "city": "Hyderabad",
        }

        inputs = ext_page.locator("input[type='text'], input[type='email'], input[type='tel'], input:not([type])")
        for i in range(min(inputs.count(), 15)):
            inp = inputs.nth(i)
            if not inp.is_visible():
                continue
            current_val = inp.input_value()
            if current_val:
                continue

            # Get field identifier
            field_id = (
                (inp.get_attribute("name") or "") +
                (inp.get_attribute("placeholder") or "") +
                (inp.get_attribute("aria-label") or "") +
                (inp.get_attribute("id") or "")
            ).lower()

            for key, value in field_map.items():
                if key in field_id:
                    inp.fill(value)
                    time.sleep(0.3)
                    break

        # Try to click Submit/Apply button
        submit_btn = ext_page.locator(
            "button[type='submit'], "
            "button:has-text('Submit'), "
            "button:has-text('Apply'), "
            "input[type='submit']"
        )
        if submit_btn.count() > 0 and submit_btn.first.is_visible():
            submit_btn.first.click()
            time.sleep(3)
            logger.info(f"    ✅ Applied on external site!")
            return True

        logger.info(f"    ⚠️ External form — couldn't find submit button")
        return False

    except Exception as e:
        logger.info(f"    ⚠️ External form error: {str(e)[:50]}")
        return False


def _close_application_dialog(page: Page):
    """Close/dismiss any open Easy Apply dialog."""
    try:
        close_btn = page.locator(
            "button[aria-label*='Dismiss'], "
            "button[aria-label*='Close'], "
            "button:has-text('Discard')"
        )
        if close_btn.count() > 0:
            close_btn.first.click()
            time.sleep(1)
            # Confirm discard if prompted
            confirm = page.locator("button:has-text('Discard'), button:has-text('Yes')")
            if confirm.count() > 0:
                confirm.first.click()
    except Exception:
        pass


def run_linkedin_batch(
    page: Page,
    jobs: list[dict],
    config: dict,
    tracker,
    logger,
) -> int:
    """Apply to a batch of LinkedIn jobs. Returns count of successful applications."""
    anti = config["anti_detection"]
    applied = 0
    consecutive_errors = 0

    # Ensure we're logged in before starting
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=15000)
    time.sleep(3)
    if not ensure_linkedin_login(page, config, logger):
        logger.error("  ❌ Cannot log into LinkedIn — aborting batch")
        return 0
    logger.info("  ✅ LinkedIn session active")

    for i, job in enumerate(jobs):
        if tracker.is_already_applied(job["apply_url"]):
            logger.info(f"  ⏭️ Already applied: {job['title']} at {job['company']}")
            continue

        success = apply_to_linkedin_job(page, job, config, logger, tracker=tracker)

        if success:
            tracker.mark_applied(job["apply_url"])
            applied += 1
            consecutive_errors = 0
        else:
            tracker.mark_skipped(job["apply_url"], "easy_apply_failed_or_external")
            # Check if browser crashed
            try:
                page.url  # This will throw if browser is dead
                consecutive_errors = 0
            except Exception:
                consecutive_errors += 1
                if consecutive_errors >= 2:
                    logger.error("  💀 Browser crashed — stopping batch")
                    break

        # Anti-detection delay
        delay = human_delay(anti["min_delay_seconds"], anti["max_delay_seconds"])
        logger.info(f"    ⏳ Waiting {delay:.0f}s before next...")

        # Periodic break
        if (i + 1) % anti["pause_after_apps"] == 0 and i > 0:
            logger.info(f"  ☕ Taking a break after {i + 1} applications...")
            from utils import take_break
            mins = take_break(anti["pause_duration_minutes"])
            logger.info(f"  ☕ Break done ({mins:.1f} min)")

    return applied
