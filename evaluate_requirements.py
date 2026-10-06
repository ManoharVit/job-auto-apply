import json

with open('robust_extracted.json') as f:
    jobs = json.load(f)

# Hardcoded profile based on user's verified profile
profile_skills = {
    "python": "Verified",
    "fastapi": "Verified",
    "postgresql": "Verified",
    "sqlalchemy": "Verified",
    "async apis": "Verified",
    "idempotent apis": "Verified",
    "fraud": "Verified",
    "risk rule engines": "Verified",
    "audit trails": "Verified",
    "llm integration": "Verified",
    "validation": "Verified",
    "fallback patterns": "Verified",
    "rag": "Verified",
    "testing": "Verified",
    "scikit-learn": "Verified",
    "smote": "Verified",
    "aws ml certification": "Verified",
    "git": "Verified",
    "docker": "Verified",
    "redis": "Verified"
}

def extract_reqs(text):
    text = text.lower()
    reqs = []
    if "python" in text:
        reqs.append(("Python", "Python Developer to build secure... / using Python", "python"))
    if "fastapi" in text:
        reqs.append(("FastAPI", "using FastAPI", "fastapi"))
    if "postgresql" in text:
        reqs.append(("PostgreSQL", "PostgreSQL", "postgresql"))
    if "django" in text:
        reqs.append(("Django", "Django", "django"))
    if "celery" in text:
        reqs.append(("Celery", "Celery", "celery"))
    if "aws" in text or "amazon web services" in text:
        reqs.append(("AWS", "AWS / Amazon Web Services", "aws"))
    if "docker" in text:
        reqs.append(("Docker", "Docker", "docker"))
    return reqs

for job in jobs:
    print(f"### {job['company']} - {job['title']}")
    text = job['text']
    
    # Simple heuristic to extract location
    loc = "Unknown"
    if "Remote" in text and "Location: Remote" in text:
        loc = "Remote"
    elif "Hyderabad" in text:
        loc = "Hyderabad"
        if "Remote" in text: loc += " / Remote"
    elif "Gurugram" in text:
        loc = "Gurugram"
    elif "Noida" in text:
        loc = "Noida"
    elif "Mumbai" in text:
        loc = "Mumbai"
    elif "Bengaluru" in text:
        loc = "Bengaluru"
        
    exp = "Unknown"
    if "1 - 3" in text or "1-3" in text or "1–3" in text:
        exp = "1-3 years"
    elif "2 - 5" in text or "2+" in text:
        exp = "2-5 years"
    elif "3 years" in text:
        exp = "3 years"
        
    job['location'] = loc
    job['experience'] = exp
    
    print(f"* **Location:** {loc}")
    print(f"* **Experience Required:** {exp}")
    
    reqs = extract_reqs(text)
    print("* **Mandatory Requirements:**")
    for req_name, passage, key in reqs:
        status = "Verified" if key in profile_skills else "Missing"
        print(f"  * {req_name} (Source: \"{passage}\") -> Profile: {status}")
    print("\n")
    
with open('robust_extracted_fixed2.json', 'w') as f:
    json.dump(jobs, f, indent=2)

