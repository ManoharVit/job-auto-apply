import pytest
from auto_apply.orchestrator import score_job, is_eligible

@pytest.fixture
def mock_config():
    return {
        "profile": {
            "target_titles": ["Backend Engineer", "Python Developer"],
            "skills": ["Python", "FastAPI", "PostgreSQL"],
            "experience_years": 2.0,
            "locations": ["India", "Remote"]
        },
        "filters": {
            "min_score": 10,
            "excluded_title_keywords": ["Senior", "Lead"]
        }
    }

def test_missing_experience_is_review_needed(mock_config):
    job = {
        "title": "Backend Engineer",
        "company": "Test Co",
        "location": "India",
        "description": "Great backend job using Python.",
        "experience": "Unknown",
        "application_open": "Yes"
    }
    score_data = score_job(job, mock_config)
    eligible, reason = is_eligible(job, mock_config, score_data)
    assert eligible is None
    assert "Experience" in reason or "Unknown" in reason or "Needs review: Missing experience" in reason

def test_unknown_location_is_review_needed(mock_config):
    job = {
        "title": "Python Developer",
        "company": "Test Co",
        "location": "Unknown",
        "description": "Great backend job using Python.",
        "experience": "2 years",
        "application_open": "Yes"
    }
    score_data = score_job(job, mock_config)
    eligible, reason = is_eligible(job, mock_config, score_data)
    assert eligible is None
    assert "Location mismatch" in reason or "Unknown" in reason

def test_unknown_availability_is_review_needed(mock_config):
    job = {
        "title": "Python Developer",
        "company": "Test Co",
        "location": "India",
        "description": "Great backend job using Python.",
        "experience": "2 years",
        "application_open": "Unknown" 
    }
    score_data = score_job(job, mock_config)
    eligible, reason = is_eligible(job, mock_config, score_data)
    assert eligible is None, f"Expected REVIEW_NEEDED (None), got {eligible}"
    assert "availability Unknown" in reason

def test_inaccessible_description_is_review_needed(mock_config):
    job = {
        "title": "Python Developer",
        "company": "Test Co",
        "location": "India",
        "description": "Unknown text. Login required.",
        "experience": "2 years",
        "application_open": "Yes"
    }
    score_data = score_job(job, mock_config)
    eligible, reason = is_eligible(job, mock_config, score_data)
    assert eligible is None or eligible is False

def test_closed_availability_is_excluded(mock_config):
    job = {
        "title": "Python Developer",
        "company": "Test Co",
        "location": "India",
        "description": "Great backend job using Python.",
        "experience": "2 years",
        "application_open": "Closed" 
    }
    score_data = score_job(job, mock_config)
    eligible, reason = is_eligible(job, mock_config, score_data)
    assert eligible is False, f"Expected EXCLUDED (False), got {eligible}"
    assert "closed" in reason.lower()
