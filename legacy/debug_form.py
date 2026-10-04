"""
debug_form.py — Opens a LinkedIn Easy Apply form and dumps all input elements.
Run: python debug_form.py
"""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from utils import load_config

config = load_config()
sessions_dir = Path(config["paths"]["sessions_dir"])
session_path = sessions_dir / "linkedin_session"

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(session_path),
        headless=False,
        viewport={"width": 1280, "height": 800},
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    # Go to LinkedIn feed first to verify login
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=15000)
    time.sleep(3)
    print(f"Current URL: {page.url}")
    
    # Find a job with Easy Apply
    # Use one of the jobs from the tracker
    import sqlite3
    conn = sqlite3.connect(config["paths"]["db_path"])
    rows = conn.execute(
        "SELECT job_url, title FROM applications WHERE platform='linkedin' AND status='pending' ORDER BY match_score DESC LIMIT 5"
    ).fetchall()
    conn.close()
    
    if not rows:
        print("No pending LinkedIn jobs found in tracker!")
        ctx.close()
        exit()

    for url, title in rows:
        print(f"\n{'='*60}")
        print(f"Trying: {title}")
        print(f"URL: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)
        
        # Look for Easy Apply button
        easy_btn = page.locator("button:has-text('Easy Apply')")
        if easy_btn.count() == 0:
            print("  No Easy Apply button — skipping")
            continue
        
        print("  ✅ Easy Apply button found! Clicking...")
        easy_btn.first.click()
        time.sleep(3)
        
        # Take screenshot of the form
        page.screenshot(path="logs/screenshots/debug_form.png")
        print("  📸 Screenshot saved: logs/screenshots/debug_form.png")
        
        # Dump ALL elements in the dialog
        print("\n  === DIALOG ELEMENTS ===")
        
        # Find the dialog/modal container
        dialogs = page.locator("div[role='dialog'], div[class*='artdeco-modal'], div[class*='jobs-easy-apply']")
        print(f"  Dialogs found: {dialogs.count()}")
        
        # Dump all inputs
        all_inputs = page.locator("input, textarea, select")
        print(f"\n  Total inputs on page: {all_inputs.count()}")
        
        for i in range(all_inputs.count()):
            el = all_inputs.nth(i)
            try:
                if not el.is_visible():
                    continue
                tag = el.evaluate("el => el.tagName")
                inp_type = el.get_attribute("type") or "none"
                name = el.get_attribute("name") or ""
                inp_id = el.get_attribute("id") or ""
                placeholder = el.get_attribute("placeholder") or ""
                aria_label = el.get_attribute("aria-label") or ""
                value = el.input_value() if tag != "SELECT" else ""
                
                # Get parent classes
                parent_classes = el.evaluate("el => { let p = el.parentElement; let classes = []; for(let i=0; i<5 && p; i++) { classes.push(p.className?.substring(0,60) || ''); p = p.parentElement; } return classes; }")
                
                # Get associated label
                label_text = ""
                if inp_id:
                    label_el = page.locator(f"label[for='{inp_id}']")
                    if label_el.count() > 0:
                        label_text = label_el.first.inner_text()
                
                print(f"\n  [{i}] <{tag} type='{inp_type}'>")
                print(f"      id='{inp_id}' name='{name}'")
                print(f"      placeholder='{placeholder}'")
                print(f"      aria-label='{aria_label}'")
                print(f"      label='{label_text}'")
                print(f"      value='{value}'")
                print(f"      parents: {parent_classes[:3]}")
            except Exception as e:
                print(f"  [{i}] Error: {e}")
        
        # Also dump the dialog HTML structure (first 3000 chars)
        try:
            dialog = page.locator("div[role='dialog']").first
            html = dialog.evaluate("el => el.innerHTML.substring(0, 5000)")
            with open("logs/screenshots/debug_form_html.txt", "w") as f:
                f.write(html)
            print("\n  📄 Full dialog HTML saved: logs/screenshots/debug_form_html.txt")
        except Exception as e:
            print(f"\n  Dialog HTML error: {e}")
        
        break  # Only debug one job
    
    input("\nPress ENTER to close browser...")
    ctx.close()
