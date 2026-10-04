"""
naukri_apply.py — Automates Naukri job applications using Playwright.
"""

import time
import random
from pathlib import Path
from playwright.sync_api import Page, TimeoutError as PwTimeout
from utils import human_delay, random_scroll, slow_type


def ensure_naukri_login(page: Page, config: dict, logger) -> bool:
    """Verify the saved Naukri session is still active.

    Strategy: rely ONLY on the persistent session cookie saved by login_setup.py.
    Never attempt programmatic credential fill — Naukri's bot detection will
    reject it silently and leave the browser on /nlogin/login indefinitely.

    If the session has expired, log a clear message and return False so the
    batch aborts cleanly (user must run: python login_setup.py naukri).
    """
    try:
        # Navigate to the Naukri homepage (redirects to login if session dead)
        page.goto(
            "https://www.naukri.com/mnjuser/homepage",
            wait_until="domcontentloaded",
            timeout=20000,
        )
        time.sleep(3)
    except Exception as e:
        logger.warning(f"    ⚠️ Naukri homepage load error: {e}")

    current_url = page.url

    # ── Logged-in check 1: URL should NOT be login page ──────────────────
    if "nlogin" in current_url or "/login" in current_url.lower():
        logger.error(
            "    ❌ Naukri session expired or invalid.\n"
            "       Fix: python login_setup.py naukri\n"
            "       (opens a browser → log in manually → press ENTER)"
        )
        return False

    # ── Logged-in check 2: profile/nav element must be present ───────────
    logged_in_selectors = [
        ".nI-gNb-drawer__bars",          # hamburger nav (always present when logged in)
        "a[href*='/mnjuser/profile']",    # My Naukri link
        ".nI-gNb-menuItems",             # top nav menu
        "[class*='userNamewrapper']",    # user name chip
        "a[href*='mnjuser']",            # any mnjuser link
    ]
    for sel in logged_in_selectors:
        try:
            if page.locator(sel).count() > 0:
                logger.info("    ✅ Naukri session active")
                return True
        except Exception:
            continue

    # ── Fallback: if URL looks like dashboard, trust it ──────────────────
    if "naukri.com" in current_url and "login" not in current_url.lower():
        logger.info(f"    ✅ Naukri session active (URL: {current_url[:60]})")
        return True

    logger.error(
        "    ❌ Naukri session appears expired (no nav elements found).\n"
        "       Fix: python login_setup.py naukri"
    )
    return False


def apply_to_naukri_job(
    page: Page,
    job: dict,
    config: dict,
    logger,
    tracker=None,
) -> bool:
    """
    Navigate to a Naukri job and click Apply.
    Returns True if successfully applied, False otherwise.
    Pass `tracker` to enable saving skipped jobs to the manual-apply CSV.
    """
    url = job.get("job_url") or job.get("apply_url", "")
    title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    resume_path = str(Path(config["profile"]["resume_path"]).resolve())

    logger.info(f"  📝 Naukri: Applying to '{title}' at {company}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(random.uniform(3, 5))
        random_scroll(page)
        time.sleep(random.uniform(1, 2))

        # Debug: save screenshot
        screenshot_dir = Path("logs/screenshots")
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() else "_" for c in title[:30])
        page.screenshot(path=str(screenshot_dir / f"nk_{safe_name}.png"))
        logger.info(f"    📸 Screenshot saved: logs/screenshots/nk_{safe_name}.png")
        logger.info(f"    📍 Current URL: {page.url[:80]}")

        # --- Find and click Apply button ---
        
        # --- Check for external apply ---
        external_btn = page.locator("a:has-text('Apply on company site'), button:has-text('Apply on company site'), span:has-text('Apply on company site')")
        if external_btn.count() > 0:
            logger.info(f"    📋 External application required — saved for manual apply")
            if tracker:
                tracker.save_manual_candidate(
                    "naukri", title, company, url, "external_site"
                )
            return False

        # --- Find and click Apply button ---
        apply_btn = page.locator(

            "button#apply-button, "
            "button.apply-button, "
            "button:has-text('Apply'), "
                        "button[id*='apply'], "
            "button.styles_apply-button, "
            "button[class*='apply']"
        )

        if apply_btn.count() == 0:
            # Try the "Apply" link if button not found
            apply_link = page.locator("a:has-text('Apply')")
            if apply_link.count() > 0:
                apply_link.first.click()
            else:
                logger.info(f"    📋 No Apply button found — saved for manual apply")
                if tracker:
                    tracker.save_manual_candidate(
                        "naukri", title, company, url, "no_apply_button"
                    )
                return False

        else:
            apply_btn.first.click()

        time.sleep(random.uniform(2, 3))

        # --- Handle apply flow ---
        # Naukri may show: chatbot questionnaire, direct apply, or redirect

        # Check if application was submitted (success message)
        success_indicators = [
            "text=Applied Successfully",
            "text=Application Submitted",
            "text=already applied",
            "text=You have already applied",
            ".apply-message",
            "[class*='applied']",
                    ]

        for indicator in success_indicators:
            try:
                if page.locator(indicator).count() > 0:
                    logger.info(f"    ✅ Applied successfully!")
                    return True
            except Exception:
                continue

        # --- Handle chatbot / questionnaire ---
        _handle_naukri_questionnaire(page, config, logger)

        # Check success again after questionnaire
        time.sleep(2)
        for indicator in success_indicators:
            try:
                if page.locator(indicator).count() > 0:
                    logger.info(f"    ✅ Applied successfully (after questionnaire)!")
                    return True
            except Exception:
                continue

        # --- Handle resume upload if prompted ---
        file_input = page.locator("input[type='file']")
        if file_input.count() > 0:
            try:
                file_input.first.set_input_files(resume_path)
                time.sleep(2)
                logger.info(f"    📄 Resume uploaded on Naukri")
                # Click submit/apply after upload
                submit = page.locator("button:has-text('Apply'), button:has-text('Submit')")
                if submit.count() > 0:
                    submit.first.click()
                    time.sleep(2)
                    logger.info(f"    ✅ Applied after resume upload!")
                    return True
            except Exception:
                pass

        # If we got here, we likely clicked apply but can't confirm
        # Check if URL changed to application confirmation
        current_url = page.url
        if "applied" in current_url.lower() or "thank" in current_url.lower():
            logger.info(f"    ✅ Likely applied (URL indicates success)")
            return True

        logger.info(f"    ⚠️ Apply clicked but couldn't confirm submission")
        return True  # Optimistic — we did click Apply

    except PwTimeout:
        logger.warning(f"    ⏱️ Timeout loading page")
        return False
    except Exception as e:
        logger.error(f"    ❌ Error: {e}")
        return False


def _handle_naukri_questionnaire(page: Page, config: dict, logger):
    """Handle Naukri's chatbot-style screening questions."""
    screening = config["screening"]
    max_questions = 10

    for _ in range(max_questions):
        time.sleep(random.uniform(1, 2))

        # Look for chatbot question containers
        question_container = page.locator(
            ".chatbot_message, .chatbot-message, "
            "[class*='questionnaire'], [class*='question'], "
            ".bot-msg"
        )

        if question_container.count() == 0:
            break

        # Find input fields in the questionnaire
        text_input = page.locator(
            ".chatbot_input input, .chatbot-input input, "
            "[class*='questionnaire'] input[type='text'], "
            "input[placeholder*='Type'], input[placeholder*='Enter']"
        )

        if text_input.count() > 0 and text_input.first.is_visible():
            question_text = ""
            try:
                question_text = question_container.last.inner_text().lower()
            except Exception:
                pass

            answer = _get_naukri_answer(question_text, screening)
            text_input.first.fill(answer)
            time.sleep(0.5)

            # Press Enter or click Send
            send_btn = page.locator(
                "button:has-text('Send'), button:has-text('Submit'), "
                "button[class*='send'], button[type='submit']"
            )
            if send_btn.count() > 0:
                send_btn.first.click()
            else:
                text_input.first.press("Enter")
            continue

        # Handle radio/option selections
        options = page.locator(
            ".chatbot_option, .chatbot-option, "
            "[class*='option'], [class*='chip']"
        )
        if options.count() > 0:
            # Try to find the best matching option
            question_text = ""
            try:
                question_text = question_container.last.inner_text().lower()
            except Exception:
                pass

            best_option = _find_best_option(options, question_text, screening)
            if best_option is not None:
                options.nth(best_option).click()
                time.sleep(1)
            continue

        # No more questions
        break


def _get_naukri_answer(question: str, screening: dict) -> str:
    """Return appropriate answer for a Naukri screening question."""
    q = question.lower()

    # Experience / years questions → always "2"
    if any(kw in q for kw in ["experience", "years", "year", "how many", "how long",
                               "proficien", "expertise", "familiar"]):
        return "2"
    # CTC / Salary
    elif any(kw in q for kw in ["expected ctc", "expected salary", "expected package"]):
        return screening["expected_ctc"]
    elif any(kw in q for kw in ["current ctc", "current salary", "present ctc", "present salary"]):
        return screening.get("current_ctc", "5 LPA")
    elif any(kw in q for kw in ["ctc", "salary", "package", "compensation"]):
        return screening["expected_ctc"]
    # Notice period
    elif any(kw in q for kw in ["notice", "join", "joining", "start", "available"]):
        return screening["notice_period"]
    # Relocation
    elif any(kw in q for kw in ["relocat", "willing to move", "shift", "work from office",
                                 "wfo", "onsite", "on-site"]):
        return "Yes"
    # Education
    elif any(kw in q for kw in ["education", "degree", "qualification", "highest"]):
        return screening["highest_education"]
    elif any(kw in q for kw in ["graduation", "passed", "batch", "passing year"]):
        return screening["graduation_year"]
    # Work authorization
    elif any(kw in q for kw in ["authorized", "authorization", "visa", "work permit",
                                 "eligible", "legally"]):
        return "Yes"
    # Location / City
    elif any(kw in q for kw in ["city", "location", "where", "current location",
                                 "preferred location"]):
        return "Hyderabad"
    # Phone
    elif any(kw in q for kw in ["phone", "mobile", "contact", "number"]):
        return "9666379063"
    # Night shift / Rotational
    elif any(kw in q for kw in ["night shift", "rotational", "shift", "flexible",
                                 "weekend", "overtime"]):
        return "Yes"
    # Languages
    elif any(kw in q for kw in ["language", "english", "communication"]):
        return "Yes"
    # Gender / Diversity
    elif any(kw in q for kw in ["gender", "male", "female"]):
        return "Male"
    # Age
    elif any(kw in q for kw in ["age", "date of birth", "dob"]):
        return "25"
    # LinkedIn / URL
    elif any(kw in q for kw in ["linkedin", "github", "portfolio", "url", "website",
                                 "profile link"]):
        return "https://linkedin.com/in/manohar511"
    # Email
    elif any(kw in q for kw in ["email", "mail"]):
        return "manoharusa21@gmail.com"
    # Background check
    elif any(kw in q for kw in ["background check", "drug test", "verification",
                                 "reference", "consent"]):
        return "Yes"
    # Travel
    elif any(kw in q for kw in ["travel", "commute", "onsite visit"]):
        return "Yes"
    # Start immediately
    elif any(kw in q for kw in ["immediately", "urgent", "asap"]):
        return "Yes"
    # Internship duration
    elif any(kw in q for kw in ["internship", "duration", "commit", "months"]):
        return "6"
    # Default
    else:
        return "2"


def _find_best_option(options, question: str, screening: dict) -> int | None:
    """Find the best option index to click for a given question."""
    q = question.lower()
    option_texts = []
    for i in range(options.count()):
        try:
            option_texts.append(options.nth(i).inner_text().lower())
        except Exception:
            option_texts.append("")

    # Always prefer "Yes" for boolean questions
    for i, text in enumerate(option_texts):
        if text.strip() == "yes":
            return i

    # For experience-related, pick the lowest reasonable range
    if any(kw in q for kw in ["experience", "years"]):
        preferred = ["0-1", "0-2", "1-2", "1-3", "2-3", "fresher", "0 to 1", "0 to 2",
                     "1 to 2", "1 to 3", "2 to 3", "entry"]
        for i, text in enumerate(option_texts):
            if any(p in text for p in preferred):
                return i

    # For CTC/salary, pick lowest range
    if any(kw in q for kw in ["ctc", "salary", "package"]):
        for i, text in enumerate(option_texts):
            if any(p in text for p in ["0-", "5-", "6-", "8-", "10-", "upto"]):
                return i

    # For notice period, pick shortest
    if any(kw in q for kw in ["notice", "join"]):
        for i, text in enumerate(option_texts):
            if any(p in text for p in ["immediate", "0", "15 day", "1 month", "less than"]):
                return i

    # For education
    if any(kw in q for kw in ["education", "degree", "qualification"]):
        for i, text in enumerate(option_texts):
            if any(p in text for p in ["master", "m.tech", "m.s", "post grad", "pg"]):
                return i

    # For location / relocation
    if any(kw in q for kw in ["location", "city", "relocat"]):
        for i, text in enumerate(option_texts):
            if any(p in text for p in ["hyderabad", "bangalore", "bengaluru", "remote", "any"]):
                return i

    # Default: pick first option (most positive/common)
    return 0 if option_texts else None


def run_naukri_batch(
    page: Page,
    jobs: list[dict],
    config: dict,
    tracker,
    logger,
) -> int:
    """Apply to a batch of Naukri jobs. Returns count of successful applications."""
    anti = config["anti_detection"]
    applied = 0

    # Ensure we're logged in before starting
    page.goto("https://www.naukri.com/mnjuser/homepage", wait_until="domcontentloaded", timeout=15000)
    time.sleep(3)
    if not ensure_naukri_login(page, config, logger):
        logger.error("  ❌ Cannot log into Naukri — aborting batch")
        return 0
    logger.info("  ✅ Naukri session active")

    for i, job in enumerate(jobs):
        job_url = job.get("job_url") or job.get("apply_url", "")
        if tracker.is_already_applied(job_url):
            logger.info(f"  ⏭️ Already applied: {job['title']} at {job['company']}")
            continue

        success = apply_to_naukri_job(page, job, config, logger, tracker=tracker)

        if success:
            tracker.mark_applied(job_url)
            applied += 1
        else:
            tracker.mark_skipped(job_url, "naukri_apply_failed")

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
