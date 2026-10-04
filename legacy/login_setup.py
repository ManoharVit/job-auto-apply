"""
login_setup.py — One-time session setup for the shared Chromium profile.

Opens ONE browser window with two tabs:
  Tab 1 → LinkedIn login
  Tab 2 → Naukri login

Log in to both manually, then press ENTER here to save the session.
The bot will reuse this single profile (sessions/main_session) for all
future runs — no separate per-platform sessions needed.

Usage:
    python login_setup.py           # set up / refresh the shared profile
    python login_setup.py --check   # just verify if the session exists
"""

import sys
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright
from utils import load_config


SESSION_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "naukri": "https://www.naukri.com/nlogin/login",
}


def get_session_path(config: dict) -> Path:
    sessions_dir = Path(config["paths"]["sessions_dir"])
    session_name = config["paths"].get("session_name", "main_session")
    return sessions_dir / session_name


def setup_session(config: dict):
    """Open a single browser with tabs for LinkedIn + Naukri and save the session."""
    session_path = get_session_path(config)
    session_path.parent.mkdir(exist_ok=True)

    print(f"\n{'='*55}")
    print(f"🔐  SHARED SESSION SETUP")
    print(f"{'='*55}")
    print(f"Profile location: {session_path.resolve()}")
    print(f"\nA browser window will open with TWO tabs:")
    print(f"  Tab 1 → LinkedIn  (log in with manoharusa21@gmail.com)")
    print(f"  Tab 2 → Naukri    (log in with girimanohar.v@gmail.com)")
    print(f"\nSteps:")
    print(f"  1. Log in to LinkedIn in Tab 1")
    print(f"  2. Switch to Tab 2 and log in to Naukri")
    print(f"  3. Complete any 2FA / CAPTCHA prompted")
    print(f"  4. Come back here and press ENTER")
    print(f"{'='*55}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(session_path),
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=TranslateUI",
            ],
        )

        # Tab 1: LinkedIn
        li_page = browser.pages[0] if browser.pages else browser.new_page()
        li_page.goto(SESSION_URLS["linkedin"])

        # Tab 2: Naukri (open alongside, don't navigate away from LinkedIn tab)
        nk_page = browser.new_page()
        nk_page.goto(SESSION_URLS["naukri"])

        # Bring LinkedIn tab to front so user starts there
        li_page.bring_to_front()

        input("\n✅  Press ENTER after you have logged in to BOTH LinkedIn and Naukri...\n")

        # Verify
        results = {}
        for name, pg, check_url in [
            ("LinkedIn",  li_page, "feed"),
            ("Naukri",    nk_page, "mnjuser"),
        ]:
            try:
                current = pg.url
                ok = check_url in current or "login" not in current.lower()
                results[name] = ("✅" if ok else "⚠️ ", current[:70])
            except Exception:
                results[name] = ("❌", "page closed or crashed")

        print("\n📋 Session verification:")
        for name, (icon, url) in results.items():
            print(f"  {icon} {name}: {url}")

        browser.close()

    print(f"\n💾 Session saved → {session_path.resolve()}")
    print(f"   The bot will use this profile for all LinkedIn + Naukri runs.\n")


def check_session(config: dict) -> bool:
    """Return True if the shared session directory exists."""
    return get_session_path(config).exists()


def main():
    parser = argparse.ArgumentParser(description="Job Bot — Session Setup")
    parser.add_argument("--check", action="store_true", help="Check if session exists and exit")
    args = parser.parse_args()

    config = load_config()

    if args.check:
        path = get_session_path(config)
        if path.exists():
            print(f"✅ Session exists: {path.resolve()}")
        else:
            print(f"❌ No session found at: {path.resolve()}")
            print(f"   Run: python login_setup.py")
        return

    setup_session(config)


if __name__ == "__main__":
    main()
