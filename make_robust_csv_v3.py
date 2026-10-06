import csv
import json
import re

with open('robust_extracted.json') as f:
    jobs = json.load(f)

out = []
for job in jobs:
    exp = job['experience']
    loc = job['location']
    desc = job['text']
    
    if not exp or len(exp) > 25 or "Unknown" in exp:
        # Better fallback from description
        match = re.search(r'(\d+)\s*[-to]+\s*(\d+)\s*years?', desc, re.IGNORECASE)
        if match:
            exp = f"{match.group(1)}-{match.group(2)} years"
        else:
            match = re.search(r'(\d+)\s*\+\s*years?', desc, re.IGNORECASE)
            if match:
                exp = f"{match.group(1)}+ years"
            else:
                exp = "Unknown"
    
    if not loc or len(loc) > 50 or "Unknown" in loc:
        loc = "Unknown"
        
    out.append({
        'platform': "wellfound" if "wellfound.com" in job['url'] else "cutshort",
        'job_url': job['url'],
        'title': job['title'],
        'company': job['company'],
        'location': loc,
        'description': desc[:5000] if len(desc) > 5000 else desc,
        'experience': exp,
        'application_open': "Yes" if job['open'] is True else "Unknown"
    })

with open('fresh_batch_v3.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['platform', 'job_url', 'title', 'company', 'location', 'description', 'experience', 'application_open'])
    writer.writeheader()
    writer.writerows(out)
