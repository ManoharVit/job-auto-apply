"""
Platform-specific Playwright automation for LinkedIn and Naukri.

Safety rules enforced by this module:
  - Never type '[REVIEW NEEDED]' or any placeholder into a form field.
  - Leave unknown / ambiguous fields BLANK.
  - Flag blank required fields in CLI output so the user can fill them.
  - Always pause before the final Submit button — never click it automatically.
  - Require explicit user confirmation ('s') before submission.
  - Detect success evidence from page text after submission.
"""

import time

# Type aliases for clarity; playwright is imported lazily inside
# execute_application_automated to keep module importable without it.
Page = "Page"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LABEL_JS = """
(el) => {
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
}
"""


def _context_matches(ctx: str, keywords: list[str]) -> bool:
    return any(kw in ctx for kw in keywords)


def fill_form_conservatively(page, config: dict) -> list[str]:
    """
    Fill visible empty form fields using verified profile data.

    Returns a list of field labels/descriptions that were left BLANK
    because no verified answer was available. The caller should display
    these to the user and pause.
    """
    screening = config.get("screening", {})
    profile = config.get("profile", {})
    blank_fields: list[str] = []

    # --- Standard inputs ---------------------------------------------------
    all_inputs = page.locator("input")
    for i in range(all_inputs.count()):
        inp = all_inputs.nth(i)
        try:
            if not inp.is_visible():
                continue
            inp_type = (inp.get_attribute("type") or "").lower()
            if inp_type in ("file", "hidden", "radio", "checkbox",
                            "submit", "button", "search", "password", "image"):
                continue
            if inp.input_value():
                continue

            label_text = (inp.evaluate(_LABEL_JS) or "").lower().strip()
            placeholder = (inp.get_attribute("placeholder") or "").lower()
            ctx = f"{label_text} {placeholder}"

            filled = False
            if _context_matches(ctx, ["phone", "mobile"]):
                val = str(profile.get("phone", ""))
                if val:
                    inp.fill(val)
                    filled = True
            elif _context_matches(ctx, ["email", "e-mail"]):
                val = str(profile.get("email", ""))
                if val:
                    inp.fill(val)
                    filled = True
            elif "expected" in ctx and _context_matches(ctx, ["ctc", "salary", "package"]):
                val = str(screening.get("expected_ctc", ""))
                if val:
                    inp.fill(val)
                    filled = True
            elif "current" in ctx and _context_matches(ctx, ["ctc", "salary", "package"]):
                val = str(screening.get("current_ctc", ""))
                if val:
                    inp.fill(val)
                    filled = True
            elif _context_matches(ctx, ["notice", "joining time", "start date"]):
                val = str(screening.get("notice_period", ""))
                if val:
                    inp.fill(val)
                    filled = True
            elif _context_matches(ctx, ["city", "location", "relocat"]):
                locations = profile.get("locations", [])
                if locations:
                    inp.fill(str(locations[0]))
                    filled = True
            elif _context_matches(ctx, ["graduation", "passed", "batch", "passing year"]):
                val = str(screening.get("graduation_year", ""))
                if val:
                    inp.fill(val)
                    filled = True
            elif _context_matches(ctx, ["education", "degree", "qualification", "highest"]):
                val = str(screening.get("highest_education", ""))
                if val:
                    inp.fill(val)
                    filled = True
            elif _context_matches(ctx, ["experience", "years", "year", "how many"]):
                val = str(screening.get("years_of_experience", ""))
                if val:
                    inp.fill(val)
                    filled = True

            if not filled:
                # Leave the field BLANK — do NOT type any placeholder text.
                desc = label_text or placeholder or f"input #{i}"
                blank_fields.append(desc)

        except Exception:
            pass

    # --- Textareas ---------------------------------------------------------
    textareas = page.locator("textarea")
    for i in range(textareas.count()):
        ta = textareas.nth(i)
        try:
            if ta.is_visible() and not ta.input_value():
                label = (ta.evaluate(_LABEL_JS) or "").strip()
                desc = label or f"textarea #{i}"
                # Leave BLANK
                blank_fields.append(desc)
        except Exception:
            pass

    return blank_fields


def fill_chatbot_conservatively(page, config: dict) -> list[str]:
    """Handle Naukri chatbot-style inputs. Returns list of unanswered questions."""
    screening = config.get("screening", {})
    unanswered: list[str] = []

    try:
        chat_inputs = page.locator(
            ".chatbot_input input, .chatbot-input input, "
            "input[placeholder*='Type'], input[placeholder*='Enter']"
        )
        if chat_inputs.count() == 0 or not chat_inputs.first.is_visible():
            return unanswered
        if chat_inputs.first.input_value():
            return unanswered

        question_containers = page.locator(
            ".chatbot_message, .chatbot-message, .bot-msg"
        )
        if question_containers.count() == 0:
            unanswered.append("(chatbot question not detected)")
            return unanswered

        q_text = question_containers.last.inner_text().lower()
        ans = None

        if _context_matches(q_text, ["experience", "years", "year"]):
            ans = str(screening.get("years_of_experience", ""))
        elif _context_matches(q_text, ["expected ctc", "expected salary", "expected package"]):
            ans = str(screening.get("expected_ctc", ""))
        elif _context_matches(q_text, ["notice", "join", "joining", "start"]):
            ans = str(screening.get("notice_period", ""))
        elif _context_matches(q_text, ["education", "degree"]):
            ans = str(screening.get("highest_education", ""))

        if ans:
            chat_inputs.first.fill(ans)
        else:
            # Leave BLANK — do not guess
            unanswered.append(q_text[:80])
    except Exception:
        pass

    return unanswered


def _find_blank_fields(page) -> list[str]:
    """
    Scan the page for visible empty required-looking fields.
    Returns descriptions for the CLI.
    """
    blanks = []
    try:
        inputs = page.locator("input")
        for i in range(inputs.count()):
            inp = inputs.nth(i)
            try:
                if not inp.is_visible():
                    continue
                inp_type = (inp.get_attribute("type") or "").lower()
                if inp_type in ("file", "hidden", "radio", "checkbox",
                                "submit", "button", "search", "password", "image"):
                    continue
                if not inp.input_value():
                    label = (inp.evaluate(_LABEL_JS) or "").strip()
                    blanks.append(label or f"input #{i}")
            except Exception:
                pass
    except Exception:
        pass
    return blanks


def check_success_evidence(page) -> str | None:
    """Look for platform confirmation text after submission."""
    indicators = [
        "Applied Successfully",
        "Application Submitted",
        "already applied",
        "You have already applied",
        "Your application was sent",
        "Application received",
    ]
    try:
        body_text = page.locator("body").inner_text()
        for ind in indicators:
            if ind.lower() in body_text.lower():
                return ind
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# LinkedIn Easy Apply
# ---------------------------------------------------------------------------

def execute_linkedin(page, job: dict, config: dict):
    url = job.get("job_url") or job.get("apply_url")
    page.goto(url)
    
    # Wait for the page to load
    page.wait_for_load_state("domcontentloaded")
    time.sleep(3)

    # Helper to find Easy Apply button
    def get_easy_apply_btn():
        return page.locator(
            "button.jobs-apply-button, "
            "button[aria-label*='Easy Apply'], "
            "button:has-text('Easy Apply')"
        )

    easy_apply_btn = get_easy_apply_btn()
    
    # If we don't see the Easy Apply button, it might be a login wall or regular Apply.
    if easy_apply_btn.count() == 0:
        print("\n  ⚠ Cannot find the 'Easy Apply' button.")
        print("  If you are not logged in, please log in now in the browser window.")
        print("  If this job only has a regular 'Apply' button (redirects to company site), you must apply manually.")
        ans = input("  Once logged in and on the job page, press Enter to retry, or type 'skip' to abort: ")
        if ans.strip().lower() == 'skip':
            return "skipped", "User aborted because Easy Apply button was not found"
        
        # Re-check after user intervention
        easy_apply_btn = get_easy_apply_btn()
        if easy_apply_btn.count() == 0:
            return "unconfirmed", "No Easy Apply button found on page even after waiting"

    # The user might have navigated around, so ensure we have a fresh locator
    try:
        easy_apply_btn.first.click()
    except Exception as e:
        print(f"  ⚠ Failed to click Easy Apply: {e}")
        return "failed", "Could not click Easy Apply button"
        
    time.sleep(2)

    max_steps = 10
    for step in range(max_steps):
        time.sleep(2)

        # Check if the Submit button is visible
        submit_btn = page.locator(
            "button[aria-label*='Submit application'], "
            "button:has-text('Submit application'), "
            "button:has-text('Submit')"
        )
        is_final_step = False
        for j in range(submit_btn.count()):
            try:
                if submit_btn.nth(j).is_visible():
                    is_final_step = True
                    break
            except Exception:
                pass

        # Fill what we can
        blank_fields = fill_form_conservatively(page, config)

        # If there are blank fields, pause for the user
        if blank_fields:
            print(f"\n  ⚠ {len(blank_fields)} field(s) left BLANK (no verified answer):")
            for bf in blank_fields:
                print(f"      • {bf}")
            input("  Please fill them in the browser, then press Enter to continue...")

        if is_final_step:
            # Re-check for any remaining blanks after user filled them
            remaining = _find_blank_fields(page)
            if remaining:
                print(f"\n  ⚠ {len(remaining)} field(s) still blank:")
                for bf in remaining:
                    print(f"      • {bf}")
                input("  Fill them in the browser, then press Enter...")

            print("\n  ═══════════════════════════════════════════════════════")
            print("  FINAL STEP: The Submit button is visible.")
            print("  Review your answers in the browser before proceeding.")
            print("  ═══════════════════════════════════════════════════════")
            ans = input("  Please click Submit in the browser manually, then type 's' to confirm, or 'skip' to abort: ")
            if ans.strip().lower() == "s":
                time.sleep(3)
                evidence = check_success_evidence(page)
                if evidence:
                    return "confirmed_submitted", f"Platform evidence: {evidence}"
                else:
                    return "unconfirmed", "User confirmed submission but no platform confirmation detected"
            else:
                return "skipped", "User aborted at final step"

        # Click Next / Continue
        next_btn = page.locator(
            "button[aria-label*='Continue to next step'], "
            "button:has-text('Next'), "
            "button:has-text('Review'), "
            "button:has-text('Continue')"
        )
        clicked = False
        for j in range(next_btn.count()):
            btn = next_btn.nth(j)
            try:
                text = btn.inner_text().strip().lower()
                if btn.is_visible() and text != "submit":
                    btn.click()
                    clicked = True
                    time.sleep(1)
                    break
            except Exception:
                pass

        if not clicked:
            evidence = check_success_evidence(page)
            if evidence:
                return "confirmed_submitted", f"Platform evidence: {evidence}"
            return "failed", "Could not find Next or Submit button"

    return "failed", "Reached max form steps without finding Submit"


# ---------------------------------------------------------------------------
# Naukri
# ---------------------------------------------------------------------------

def execute_naukri(page, job: dict, config: dict):
    url = job.get("job_url") or job.get("apply_url")
    page.goto(url)
    
    page.wait_for_load_state("domcontentloaded")
    time.sleep(3)

    def get_apply_btn():
        return page.locator("button#apply-button, button.apply-button, button:has-text('Apply')")

    apply_btn = get_apply_btn()
    if apply_btn.count() == 0:
        print("\n  ⚠ Cannot find the 'Apply' button.")
        print("  If you are not logged in, please log in now in the browser window.")
        ans = input("  Once logged in and on the job page, press Enter to retry, or type 'skip' to abort: ")
        if ans.strip().lower() == 'skip':
            return "skipped", "User aborted because Apply button was not found"
        
        apply_btn = get_apply_btn()
        if apply_btn.count() == 0:
            return "unconfirmed", "No Apply button found on page even after waiting"

    print("\n  ═══════════════════════════════════════════════════════")
    print("  Naukri may submit instantly when 'Apply' is clicked.")
    print("  If a login modal is covering the page, please log in first.")
    print("  Review the job page in the browser before proceeding.")
    print("  ═══════════════════════════════════════════════════════")
    ans = input("  Please click 'Apply' in the browser manually, then type 's' to proceed, or 'skip' to abort: ")
    
    if ans.strip().lower() != "s":
        return "skipped", "User aborted before clicking Apply"

    # We do NOT click apply automatically! Let the user do it.
    # Just wait a moment to allow page changes if they clicked right before confirming
    time.sleep(3)
        
    time.sleep(3)

    # Check for instant success
    evidence = check_success_evidence(page)
    if evidence:
        return "confirmed_submitted", f"Platform evidence: {evidence}"

    # Handle chatbot / additional questions
    for _ in range(5):
        time.sleep(2)
        chat_inputs = page.locator(
            ".chatbot_input input, .chatbot-input input, "
            "input[placeholder*='Type']"
        )
        if chat_inputs.count() > 0 and chat_inputs.first.is_visible():
            unanswered = fill_chatbot_conservatively(page, config)
            if unanswered:
                print(f"\n  ⚠ {len(unanswered)} chatbot question(s) could not be answered automatically:")
                for q in unanswered:
                    print(f"      • {q}")
                input("  Please answer in the browser, then press Enter...")
            else:
                # Known answer was filled; ask before sending
                ans2 = input("  Chatbot answer filled. Press Enter to send, or type 'skip' to abort: ")
                if ans2.strip().lower() == "skip":
                    return "skipped", "User aborted at chatbot step"
                chat_inputs.first.press("Enter")
                time.sleep(2)
        else:
            break

    time.sleep(2)
    evidence = check_success_evidence(page)
    if evidence:
        return "confirmed_submitted", f"Platform evidence: {evidence}"

    # Handle resume upload if a file input appeared
    file_input = page.locator("input[type='file']")
    if file_input.count() > 0:
        resume_path = config.get("profile", {}).get("resume_path", "")
        if resume_path:
            try:
                file_input.first.set_input_files(resume_path)
                time.sleep(2)
            except Exception as e:
                return "failed", f"Resume upload failed: {type(e).__name__}"

            # Do NOT click submit automatically — pause for user
            print("\n  Resume uploaded. Review the form before submitting.")
            submit = page.locator(
                "button:has-text('Apply'), button:has-text('Submit')"
            )
            if submit.count() > 0:
                ans3 = input("  Please click Submit in the browser manually, then type 's' to confirm, or 'skip' to abort: ")
                if ans3.strip().lower() == "s":
                    time.sleep(2)
                    evidence = check_success_evidence(page)
                    if evidence:
                        return "confirmed_submitted", f"Platform evidence: {evidence}"
                    return "unconfirmed", "User confirmed submission but no platform confirmation detected"
                else:
                    return "skipped", "User aborted after resume upload"

    return "unconfirmed", "No platform confirmation detected"


# ---------------------------------------------------------------------------
# Entry point for the orchestrator
# ---------------------------------------------------------------------------

def execute_application_automated(job, config):
    """Open a browser and run the appropriate platform flow."""
    import os
    from pathlib import Path
    
    url = job.get("job_url") or job.get("apply_url", "")
    platform = job.get("platform", "")

    if "linkedin" in url.lower() or platform == "linkedin":
        runner = execute_linkedin
    else:
        runner = execute_naukri

    from playwright.sync_api import sync_playwright

    # Use a persistent user_data_dir so logins are saved across runs
    user_data_dir = Path(__file__).resolve().parents[3] / "sessions" / "chromium_profile"
    os.makedirs(user_data_dir, exist_ok=True)

    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=False
            )
        except Exception as e:
            return "failed", f"Failed to open browser (is the profile already open?). Please close it and try again. Error: {type(e).__name__}"

        page = context.pages[0] if context.pages else context.new_page()
        try:
            status, msg = runner(page, job, config)
            return status, msg
        except Exception as e:
            return "failed", f"Browser error: {type(e).__name__}"
        finally:
            context.close()
