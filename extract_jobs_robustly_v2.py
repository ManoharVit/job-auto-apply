from playwright.sync_api import sync_playwright
import json
import time
from bs4 import BeautifulSoup

urls = [
    ("CirclePe", "https://wellfound.com/jobs/3372575-backend-developer-python-fastapi-flask-django"),
    ("Superclaims", "https://cutshort.io/job/Backend-Python-Developer-Hyderabad-Superclaims-B2gi5nDc"),
    ("FreJun", "https://wellfound.com/jobs/4799693-backend-developer"),
    ("Toadster", "https://wellfound.com/jobs/4342774-python-aiml-developer"),
    ("Deqode", "https://cutshort.io/job/Python-Developer-Mumbai-Andheri-East-Mumbai-Deqode-Hiq68eXF"),
    ("Trendlyne Technologies", "https://cutshort.io/job/Software-Backend-Developer-1-3-yrs-Bengaluru-Bangalore-Trendlyne-Technologies-Hrn3TS69"),
    ("Qrata", "https://cutshort.io/job/Jr-Backend-Engineer-Bengaluru-Bangalore-Qrata-Q7jgl0pm")
]

PROFILE_PATH = '/Users/girimanoharv/.gemini/antigravity/scratch/job-auto-apply/sessions/chromium_profile'

def is_blocked(page):
    title = page.title().lower()
    url = page.url.lower()
    return "cloudflare" in title or "challenge" in url or "login" in url or "verify" in title

def extract_main_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['nav', 'footer', 'header', 'script', 'style']):
        tag.decompose()
        
    main = soup.find('main') or soup.find(id='job-description') or soup.find(class_='job-description')
    if main:
        return main.get_text(separator='\n', strip=True)
    return soup.body.get_text(separator='\n', strip=True)[:15000] if soup.body else "Unknown"

def extract():
    results = []
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_PATH,
            headless=False,
            viewport={'width': 1280, 'height': 800}
        )
        page = context.pages[0] if context.pages else context.new_page()

        for company, url in urls:
            try:
                print(f"Navigating to {url}")
                page.goto(url)
                
                # Check for Cloudflare / CAPTCHA / Login
                if is_blocked(page):
                    print(f"Found Challenge/Login page for {company}. Pausing...")
                    input("BROWSER IS OPEN. Please solve the CAPTCHA/Login, then press Enter here...")
                
                # Wait for content to load
                page.wait_for_timeout(4000)
                
                html = page.content()
                desc = extract_main_text(html)
                
                if "cutshort.io" in url:
                    title = page.locator('h1').first.inner_text().strip() if page.locator('h1').count() > 0 else "Unknown"
                    exp_loc = page.locator('text=yrs').first
                    exp = exp_loc.inner_text().strip() if exp_loc.count() > 0 else "Unknown"
                    loc_locator = page.locator('.cp-job-details__location, [data-test="job-location"]')
                    loc = loc_locator.first.inner_text().strip() if loc_locator.count() > 0 else "Unknown"
                    open_btn = page.locator('button:has-text("Apply")').count() > 0
                else:
                    title = page.locator('h1').first.inner_text().strip() if page.locator('h1').count() > 0 else "Unknown"
                    exp_loc = page.locator('text=years').first
                    exp = exp_loc.inner_text().strip() if exp_loc.count() > 0 else "Unknown"
                    loc_locator = page.locator('.styles_location__31o_f, .styles_locationPill__3zG9F, [data-test="LocationPill"]')
                    loc = loc_locator.first.inner_text().strip() if loc_locator.count() > 0 else "Unknown"
                    open_btn = page.locator('button:has-text("Apply")').count() > 0

                results.append({
                    "company": company,
                    "title": title,
                    "url": url,
                    "location": loc,
                    "experience": exp,
                    "open": open_btn,
                    "text": desc
                })
            except Exception as e:
                print(f"Failed on {url}: {e}")
                results.append({
                    "company": company,
                    "title": "Unknown",
                    "url": url,
                    "location": "Unknown",
                    "experience": "Unknown",
                    "open": "Unknown",
                    "text": f"Extraction error: {e}"
                })

        context.close()

    with open('robust_extracted.json', 'w') as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    extract()
