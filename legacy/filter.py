"""
filter.py — Filter and score jobs against user's resume profile.
"""

from datetime import datetime, timedelta
from utils import is_excluded_title, matches_location


def _parse_date(date_str: str) -> datetime | None:
    """Try to parse various date formats from scraped data."""
    if not date_str:
        return None
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _extract_posted_date(job: dict) -> datetime | None:
    """Extract posted date from various fields."""
    for field in ["published_at", "posted_time"]:
        val = job.get(field, "")
        if not val:
            continue
        parsed = _parse_date(val)
        if parsed:
            return parsed
    # Handle relative times like "1 day ago", "2 weeks ago"
    posted_time = job.get("posted_time", "").lower()
    if "ago" in posted_time:
        now = datetime.now()
        if "hour" in posted_time:
            return now
        if "day" in posted_time:
            try:
                days = int("".join(c for c in posted_time if c.isdigit()) or "1")
                return now - timedelta(days=days)
            except ValueError:
                return now
        if "week" in posted_time:
            try:
                weeks = int("".join(c for c in posted_time if c.isdigit()) or "1")
                return now - timedelta(weeks=weeks)
            except ValueError:
                return now
        if "month" in posted_time:
            return now - timedelta(days=30)
    return None


def _skill_overlap_score(job: dict, user_skills: list[str]) -> float:
    """Calculate skill overlap score (0-45)."""
    # Combine description + skills into searchable text
    searchable = (
        job.get("description", "").lower()
        + " "
        + job.get("title", "").lower()
        + " "
        + " ".join(str(s).lower() for s in job.get("skills", []))
    )

    user_skills_lower = [s.lower() for s in user_skills]
    matches = 0
    for skill in user_skills_lower:
        # Handle multi-word skills and common variations
        variations = [skill]
        if skill == "fastapi":
            variations.extend(["fast api", "fast-api"])
        elif skill == "sqlalchemy":
            variations.extend(["sql alchemy", "sql-alchemy"])
        elif skill == "postgresql":
            variations.extend(["postgres", "pgsql"])
        elif skill == "rest api":
            variations.extend(["restful", "rest apis", "restful api"])
        elif skill == "llm":
            variations.extend(["large language model", "gpt", "genai", "gen ai", "generative ai"])
        elif skill == "rag":
            variations.extend(["retrieval augmented", "retrieval-augmented"])
        elif skill == "docker":
            variations.extend(["containerization", "containers"])
        elif skill == "aws":
            variations.extend(["amazon web services", "cloud"])
        elif skill == "pytest":
            variations.extend(["unit test", "testing"])

        for var in variations:
            if var in searchable:
                matches += 1
                break

    if not user_skills_lower:
        return 0
    ratio = matches / len(user_skills_lower)
    return round(ratio * 45, 1)


def _title_relevance_score(job_title: str, target_titles: list[str]) -> float:
    """Calculate title relevance score (0-25)."""
    job_lower = job_title.lower()
    for target in target_titles:
        target_lower = target.lower()
        if target_lower in job_lower or job_lower in target_lower:
            return 25.0
        # Partial matches
        target_words = set(target_lower.split())
        job_words = set(job_lower.split())
        overlap = target_words & job_words
        if len(overlap) >= 1:
            return round(15.0 + 10.0 * len(overlap) / len(target_words), 1)
    # Check for generic software/developer keywords
    dev_keywords = ["developer", "engineer", "programmer", "coder"]
    for kw in dev_keywords:
        if kw in job_lower:
            return 10.0
    return 0.0


def _experience_fit_score(job: dict, max_user_experience: int = 2) -> float:
    """Calculate experience level fit score (0-20)."""
    # From LinkedIn
    exp_level = job.get("experience_level", "").lower()
    if exp_level in ("entry level", "entry", "internship", "associate"):
        return 20.0
    if exp_level in ("mid-senior level", "mid-senior"):
        return 5.0

    # From Naukri - use min/max experience
    min_exp = job.get("min_experience")
    max_exp = job.get("max_experience")
    if min_exp is not None and max_exp is not None:
        if min_exp <= max_user_experience <= max_exp:
            return 20.0
        elif min_exp <= max_user_experience + 1:
            return 15.0
        elif min_exp <= 3:
            return 10.0
        else:
            return 5.0

    # Parse from experience text
    exp_text = job.get("experience_level", "")
    if exp_text:
        try:
            nums = [int(n) for n in exp_text.replace("-", " ").split() if n.isdigit()]
            if nums and nums[0] <= 3:
                return 18.0
        except (ValueError, IndexError):
            pass

    return 10.0  # Default middle score


def _industry_alignment_score(job: dict) -> float:
    """Calculate industry alignment score (0-10)."""
    searchable = (
        job.get("description", "").lower()
        + " "
        + job.get("title", "").lower()
        + " "
        + job.get("company", "").lower()
    )
    # Strong alignment keywords (fintech, AI, SaaS)
    strong_keywords = [
        "fintech", "fraud", "risk", "financial", "banking",
        "ai", "machine learning", "data science", "analytics",
        "saas", "platform", "api", "backend",
    ]
    medium_keywords = [
        "healthcare", "edtech", "ecommerce", "startup",
        "consulting", "technology", "software", "digital",
    ]

    strong_matches = sum(1 for kw in strong_keywords if kw in searchable)
    medium_matches = sum(1 for kw in medium_keywords if kw in searchable)

    score = min(10.0, strong_matches * 2.5 + medium_matches * 1.0)
    return round(score, 1)


def score_job(job: dict, config: dict) -> float:
    """Score a job 0-100 based on weighted criteria."""
    profile = config["profile"]

    skill_score = _skill_overlap_score(job, profile["skills"])
    title_score = _title_relevance_score(job["title"], profile["target_titles"])
    exp_score = _experience_fit_score(job)
    industry_score = _industry_alignment_score(job)

    total = skill_score + title_score + exp_score + industry_score
    return round(total, 1)


def _is_tech_mismatch(job: dict) -> bool:
    """Return True if the job is primarily a non-Python stack with no Python/ML signal.

    Blocks Java, C#/.NET, JavaScript-only, PHP, Ruby, iOS, Android roles
    that don't also mention Python, ML, data, or AI — since Giri's stack is
    Python-first and these applications won't convert.
    """
    searchable = (
        job.get("title", "").lower()
        + " "
        + job.get("description", "").lower()
        + " "
        + " ".join(str(s) for s in job.get("skills", [])).lower()
    )

    # Non-Python primary stacks (title-level signals)
    foreign_stack_signals = [
        "java developer", "java engineer", "java backend",
        "c# developer", "c# engineer", ".net developer", ".net engineer",
        "asp.net", "dotnet developer", "c++ developer",
        "javascript developer", "node.js developer", "nodejs developer",
        "react developer", "angular developer", "vue developer",
        "php developer", "php engineer",
        "ruby developer", "ruby on rails",
        "ios developer", "android developer", "swift developer", "kotlin developer",
    ]

    # Redeeming Python/ML signals — if any present, keep the job
    python_signals = [
        "python", "fastapi", "django", "flask", "pydantic",
        "machine learning", "ml engineer", "data engineer", "data scientist",
        "ai developer", "llm", "rag", "generative ai", "gen ai",
        "scikit", "tensorflow", "pytorch", "pandas", "numpy",
    ]

    title_lower = job.get("title", "").lower()

    has_python = any(sig in searchable for sig in python_signals)
    # Only block if the JOB TITLE itself signals a foreign stack (avoids
    # false positives on mixed-stack descriptions that still want Python)
    title_is_foreign = any(sig in title_lower for sig in foreign_stack_signals)

    return title_is_foreign and not has_python


def filter_jobs(jobs: list[dict], config: dict, logger) -> list[dict]:
    """Apply filtering rules and score surviving jobs."""
    filters = config["filters"]
    profile = config["profile"]
    cutoff_date = datetime.now() - timedelta(days=filters["posted_within_days"])

    filtered = []
    reasons = {
        "excluded_title": 0,
        "location": 0,
        "too_old": 0,
        "duplicate": 0,
        "no_url": 0,
        "tech_mismatch": 0,
    }
    seen_keys = set()

    for job in jobs:
        title = job.get("title", "")
        company = job.get("company", "")
        location = job.get("location", "")
        apply_url = job.get("apply_url", "")

        # Must have apply URL
        if not apply_url:
            reasons["no_url"] += 1
            continue

        # Deduplicate by title+company
        dedup_key = f"{title.lower().strip()}|{company.lower().strip()}"
        if dedup_key in seen_keys:
            reasons["duplicate"] += 1
            continue
        seen_keys.add(dedup_key)

        # Exclude senior titles
        if is_excluded_title(title, filters["excluded_title_keywords"]):
            reasons["excluded_title"] += 1
            continue

        # Tech-stack mismatch guard (blocks Java/.NET/C#/JS-only title roles)
        if _is_tech_mismatch(job):
            reasons["tech_mismatch"] += 1
            continue

        # Location filter
        if not matches_location(location, profile["locations"]):
            reasons["location"] += 1
            continue

        # Posted date filter
        posted = _extract_posted_date(job)
        if posted and posted < cutoff_date:
            reasons["too_old"] += 1
            continue

        # Score the job
        job["match_score"] = score_job(job, config)
        filtered.append(job)

    # Sort by score descending
    filtered.sort(key=lambda j: j.get("match_score", 0), reverse=True)

    logger.info(
        f"🔍 Filtered: {len(filtered)} passed out of {len(jobs)} "
        f"(excluded_title={reasons['excluded_title']}, "
        f"tech_mismatch={reasons['tech_mismatch']}, "
        f"location={reasons['location']}, "
        f"too_old={reasons['too_old']}, "
        f"duplicate={reasons['duplicate']}, "
        f"no_url={reasons['no_url']})"
    )
    return filtered
