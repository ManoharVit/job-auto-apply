import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime

urls = [
    ("Definitive Healthcare", "https://job-boards.greenhouse.io/definitivehcindia/jobs/6151223004"),
    ("Ensono", "https://job-boards.greenhouse.io/ensono/jobs/4708498005"),
    ("Sigmoid", "https://job-boards.greenhouse.io/sigmoid/jobs/8741978002"),
    ("Conga", "https://job-boards.greenhouse.io/conga/jobs/5066150007"),
    ("MariaDB plc", "https://job-boards.eu.greenhouse.io/mariadbplc/jobs/4960499101"),
    ("Phizenix", "https://job-boards.greenhouse.io/phizenix/jobs/5398758008"),
    ("Zinnia", "https://job-boards.greenhouse.io/zind-erprogram/jobs/4675835006"),
    ("Cognite", "https://job-boards.eu.greenhouse.io/cognite/jobs/4907751101"),
    ("Zenoti", "https://job-boards.greenhouse.io/zenoti/jobs/8004525003")
]

results = []
for company, url in urls:
    try:
        r = requests.get(url)
        soup = BeautifulSoup(r.text, 'html.parser')
        container = soup.find('div', class_='job-post-container') or soup.find('div', id='content')
        
        if container:
            text = container.get_text(separator='\n', strip=True)
            # Find Apply button presence
            has_apply = bool(soup.find(lambda tag: tag.name in ['button', 'a'] and 'apply' in tag.get_text(strip=True).lower()))
            
            title_tag = soup.find('h1') or soup.find('div', class_='job__title')
            title = title_tag.get_text(strip=True) if title_tag else "Unknown"
            
            loc_tag = soup.find('div', class_='location') or soup.find('div', class_='job__location')
            location = loc_tag.get_text(strip=True) if loc_tag else "Unknown"
            
            results.append({
                "company": company,
                "title": title,
                "url": url,
                "location": location,
                "open": has_apply,
                "text": text
            })
        else:
            print(f"Could not extract {url}")
    except Exception as e:
        print(f"Error {url}: {e}")

with open('scraped_jobs.json', 'w') as f:
    json.dump(results, f, indent=2)
print("Saved to scraped_jobs.json")
