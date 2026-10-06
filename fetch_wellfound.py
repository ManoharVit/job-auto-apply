import requests
from bs4 import BeautifulSoup
import json

urls = [
    ("FreJun", "Backend Developer", "https://wellfound.com/jobs/4799693-backend-developer"),
    ("CirclePe", "Backend Engineer (Python)", "https://wellfound.com/jobs/3372575-backend-developer-python-fastapi-flask-django"),
    ("Toadster", "Python AIML Developer", "https://wellfound.com/jobs/4342774-python-aiml-developer")
]

results = []
for company, title, url in urls:
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
        soup = BeautifulSoup(r.text, 'html.parser')
        
        text = soup.get_text(separator='\n', strip=True)
        
        results.append({
            "platform": "wellfound",
            "company": company,
            "title": title,
            "url": url,
            "location": "India (Remote/Hybrid)",
            "experience": "1-3 years",
            "open": True, # Assume open if page exists without explicit closed message
            "text": text
        })
    except Exception as e:
        print(f"Error {url}: {e}")

with open('wellfound_full.json', 'w') as f:
    json.dump(results, f, indent=2)
print("Saved to wellfound_full.json")
