import requests
from bs4 import BeautifulSoup
import json

urls = [
    ("Superclaims", "Backend Python Developer", "https://cutshort.io/job/Backend-Python-Developer-Hyderabad-Superclaims-B2gi5nDc"),
    ("Deqode", "Python Developer", "https://cutshort.io/job/Python-Developer-Mumbai-Andheri-East-Mumbai-Deqode-Hiq68eXF"),
    ("Qrata (Pre Series A product company)", "Jr Backend Engineer", "https://cutshort.io/job/Jr-Backend-Engineer-Bengaluru-Bangalore-Qrata-Q7jgl0pm"),
    ("Trendlyne Technologies", "Software Backend Developer (1-3 yrs)", "https://cutshort.io/job/Software-Backend-Developer-1-3-yrs-Bengaluru-Bangalore-Trendlyne-Technologies-Hrn3TS69")
]

results = []
for company, title, url in urls:
    try:
        r = requests.get(url)
        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text(separator='\n', strip=True)
        
        # Get experience specifically if we can, Cutshort has it in meta title
        meta_title = soup.find('title').get_text(strip=True) if soup.find('title') else ""
        
        results.append({
            "platform": "cutshort",
            "company": company,
            "title": title,
            "url": url,
            "location": "India (Remote/Hybrid)",
            "experience": "1-3 years" if "1 - 3" in text or "1-3 yrs" in title else ("2-5 years" if "2 - 5" in text else "Unknown"),
            "open": "Apply to this job" in text,
            "text": text
        })
    except Exception as e:
        print(f"Error {url}: {e}")

with open('cutshort_full.json', 'w') as f:
    json.dump(results, f, indent=2)
print("Saved to cutshort_full.json")
