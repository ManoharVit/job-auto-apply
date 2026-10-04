"""
scraper.py — Local Playwright Scraper
Uses your existing authenticated browser session to search for jobs directly,
completely bypassing third-party APIs and limits.
"""

import time
import random
import urllib.parse
from playwright.sync_api import Page

def _normalize_title(title: str) -> str:
    return title.lower().replace("-", " ").replace("/", " ").replace("(", " ").replace(")", " ")

def scrape_linkedin_jobs(page: Page, config: dict, logger) -> list[dict]:
    """Scrape LinkedIn jobs via local browser session."""
    jobs = []
    roles = config.get("profile", {}).get("target_titles", ["Python Developer", "Generative AI Engineer", "Fraud Engineer"])
    locations = config.get("profile", {}).get("locations", ["India"])
    
    for role in roles:
      for location in locations[:3]: # Limit to top 3 locations to avoid too many requests
        logger.info(f"    🔍 Searching LinkedIn for '{role}' in '{location}'...")
        query = urllib.parse.quote(role)
        loc = urllib.parse.quote(location)
        # f_AL=true -> Easy Apply, sortBy=DD -> Most recent, f_E=1%2C2%2C3 -> Internship, Entry level, Associate
        url = f"https://www.linkedin.com/jobs/search/?keywords={query}&location={loc}&f_AL=true&sortBy=DD&f_E=1%2C2%2C3"
        
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(3, 5))
            
            # Scroll left pane to load more jobs (try 5 times)
            for _ in range(5):
                page.evaluate("""
                    const pane = document.querySelector('.jobs-search-results-list');
                    if(pane) pane.scrollTop = pane.scrollHeight;
                """)
                time.sleep(random.uniform(1.5, 2.5))
            
            # Extract jobs
            cards = page.locator(".job-card-container")
            count = cards.count()
            logger.info(f"    👉 Found {count} cards for '{role}'")
            
            for i in range(count):
                try:
                    card = cards.nth(i)
                    title_el = card.locator(".job-card-list__title, .artdeco-entity-lockup__title")
                    company_el = card.locator(".job-card-container__primary-description, .artdeco-entity-lockup__subtitle")
                    location_el = card.locator(".job-card-container__metadata-item, .artdeco-entity-lockup__caption")
                    link_el = card.locator("a.job-card-container__link, a.job-card-list__title")
                    
                    title = title_el.inner_text().strip() if title_el.count() else ""
                    company = company_el.inner_text().strip() if company_el.count() else ""
                    loc_text = location_el.first.inner_text().strip() if location_el.count() else ""
                    job_url = link_el.first.get_attribute("href") if link_el.count() else ""
                    
                    if job_url and title:
                        clean_url = job_url.split("?")[0]
                        if not clean_url.startswith("http"):
                            clean_url = "https://www.linkedin.com" + clean_url
                            
                        jobs.append({
                            "title": title,
                            "company": company,
                            "location": loc_text,
                            "apply_url": clean_url,
                            "job_url": clean_url,
                            "platform": "linkedin"
                        })
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"    ⚠️ Error scraping LinkedIn '{role}': {e}")
            
    return jobs

def scrape_naukri_jobs(page: Page, config: dict, logger) -> list[dict]:
    """Scrape Naukri jobs via local browser session."""
    jobs = []
    roles = config.get("profile", {}).get("target_titles", ["Python Developer", "Generative AI Engineer", "Fraud Engineer"])
    
    for role in roles:
        logger.info(f"    🔍 Searching Naukri for '{role}'...")
        # Naukri URLs often use hyphenated roles in the URL path, but since we are using 'k=' parameter now, we just pass the quoted string.
        # However, the path also needs a hyphenated version:
        hyphenated_role = role.lower().replace(" ", "-")
        k_param = urllib.parse.quote(role)
        url = f"https://www.naukri.com/{hyphenated_role}-jobs?k={k_param}&nignbevent_src=jobsearchDeskGNB&experience=3&ctcFilter=10to15&ctcFilter=15to25&jobAge=15&jobPostType=1"
        
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(3, 5))
            
            # Scroll down to trigger lazy loading
            for _ in range(4):
                page.mouse.wheel(0, 1000)
                time.sleep(random.uniform(1.5, 2.5))
            
            # Naukri job cards
            cards = page.locator(".srp-jobtuple-wrapper, .jobTuple")
            count = cards.count()
            logger.info(f"    👉 Found {count} cards for '{role}'")
            
            for i in range(count):
                try:
                    card = cards.nth(i)
                    title_el = card.locator("a.title")
                    company_el = card.locator("a.comp-name, .companyInfo a.subTitle")
                    location_el = card.locator(".locWdth, .locWrap")
                    
                    title = title_el.inner_text().strip() if title_el.count() else ""
                    job_url = title_el.first.get_attribute("href") if title_el.count() else ""
                    company = company_el.inner_text().strip() if company_el.count() else ""
                    loc_text = location_el.first.inner_text().strip() if location_el.count() else ""
                    
                    if job_url and title:
                        if not job_url.startswith("http"):
                            job_url = "https://www.naukri.com" + job_url
                            
                        jobs.append({
                            "title": title,
                            "company": company,
                            "location": loc_text,
                            "apply_url": job_url,
                            "job_url": job_url,
                            "platform": "naukri"
                        })
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"    ⚠️ Error scraping Naukri '{role}': {e}")
            
    return jobs

def scrape_all(page: Page, config: dict, logger) -> list[dict]:
    """Scrape from all configured platforms using local Playwright."""
    all_jobs = []
    
    li_jobs = scrape_linkedin_jobs(page, config, logger)
    logger.info(f"  ✅ Scraped {len(li_jobs)} LinkedIn jobs")
    all_jobs.extend(li_jobs)
    
    nk_jobs = scrape_naukri_jobs(page, config, logger)
    logger.info(f"  ✅ Scraped {len(nk_jobs)} Naukri jobs")
    all_jobs.extend(nk_jobs)
    
    logger.info(f"📊 Total local scraped: {len(all_jobs)} jobs")
    return all_jobs
