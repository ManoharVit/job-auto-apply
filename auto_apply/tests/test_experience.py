import pytest
from auto_apply.orchestrator import score_job, is_eligible

def test_experience_insufficient():
    job = {
        "title": "Python Developer",
        "description": "Valid job description.",
        "location": "Remote",
        "experience": "Requires 3+ years of experience"
    }
    config = {
        "profile": {"skills": ["Python"], "locations": ["Remote"]},
        "screening": {"years_of_experience": "2"},
        "filters": {"min_score": 10, "max_experience_years": 3}
    }
    score_data = score_job(job, config)
    eligible, reason = is_eligible(job, config, score_data)
    assert eligible is False
    assert "Excluded (Requires 3 years experience, candidate has 2)" in reason
    assert score_data["genuine_mismatch"] is True

def test_experience_sufficient():
    job = {
        "title": "Python Developer",
        "description": "Valid job description.",
        "location": "Remote",
        "experience": "Requires 1-2 years of experience"
    }
    config = {
        "profile": {"skills": ["Python"], "locations": ["Remote"]},
        "screening": {"years_of_experience": "2"},
        "filters": {"min_score": 10}
    }
    score_data = score_job(job, config)
    eligible, reason = is_eligible(job, config, score_data)
    assert eligible is True
    assert score_data["genuine_mismatch"] is False

def test_experience_unknown():
    job = {
        "title": "Python Developer",
        "description": "Valid job description.",
        "location": "Remote",
        "experience": ""
    }
    config = {
        "profile": {"skills": ["Python"], "locations": ["Remote"]},
        "screening": {"years_of_experience": "2"},
        "filters": {"min_score": 10}
    }
    score_data = score_job(job, config)
    eligible, reason = is_eligible(job, config, score_data)
    assert eligible is None
    assert "Experience requirements unknown" in reason

def test_experience_unparsable():
    job = {
        "title": "Python Developer",
        "description": "Valid job description.",
        "location": "Remote",
        "experience": "Extensive experience required"
    }
    config = {
        "profile": {"skills": ["Python"], "locations": ["Remote"]},
        "screening": {"years_of_experience": "2"},
        "filters": {"min_score": 10}
    }
    score_data = score_job(job, config)
    eligible, reason = is_eligible(job, config, score_data)
    assert eligible is None
    assert "Could not parse required years" in reason
