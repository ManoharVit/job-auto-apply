import pytest
from auto_apply.orchestrator import score_job, is_eligible

def test_candidate_experience_unknown():
    job = {
        "title": "Python Developer",
        "description": "Valid job description.",
        "location": "Remote",
        "experience": "Requires 3+ years"
    }
    config = {
        "profile": {"skills": ["Python"], "locations": ["Remote"]},
        "screening": {},  # NO candidate experience
        "filters": {"min_score": 10}
    }
    score_data = score_job(job, config)
    eligible, reason = is_eligible(job, config, score_data)
    assert eligible is None, f"Expected None but got {eligible}, reason: {reason}"

test_candidate_experience_unknown()
print("Passed")
