"""Regression coverage for import preservation and qualification integrity."""
import json
from pathlib import Path

import pytest

from auto_apply.importer import import_jobs, normalize_url
from auto_apply.orchestrator import is_eligible, score_job

@pytest.mark.parametrize("status", [
    "pending", "confirmed_submitted", "skipped", "Unconfirmed",
    "SUBMISSION_UNCONFIRMED", "failed", "paused", "applied",
])
def test_reimport_preserves_every_historical_status(status, tracker, app_config):
    url = "https://job-boards.greenhouse.io/testco/jobs/1001"
    tracker.add_job({"platform": "greenhouse", "job_url": url, "title": "Existing", "company": "Original"})
    job = tracker.get_job_by_url(url)
    tracker.update_job(job["id"], status, action="EXISTING_EVIDENCE", reason="Original submission history")
    before = tracker.get_job_by_url(url)
    audit = [tuple(row) for row in tracker._con.execute("SELECT * FROM audit_log")]
    stats = import_jobs([{
        "platform": "greenhouse", "job_url": "https://boards.greenhouse.io/testco/jobs/1001?utm_source=tracking",
        "title": "Replacement", "company": "Replacement", "location": "India",
        "description": "Verified new metadata", "experience": "2 years", "application_open": "Open",
    }], tracker, app_config)
    after = tracker.get_job_by_url(url)
    assert stats["duplicate"] == 1
    assert after["status"] == status
    assert after["applied_at"] == before["applied_at"]
    assert after["title"] == "Existing"
    assert after["company"] == "Original"
    assert after["description"] == "Verified new metadata"
    assert [tuple(row) for row in tracker._con.execute("SELECT * FROM audit_log")] == audit

@pytest.mark.parametrize("urls", [
    ["https://in.linkedin.com/jobs/view/python-developer-at-testco-123456/", "linkedin.com/jobs/view/123456?trk=abc"],
    ["https://www.naukri.com/job-listings-python-testco-123456?utm_source=x", "https://www.naukri.com/job-listings-python-testco-123456#apply"],
    ["https://boards.greenhouse.io/testco/jobs/123456?source=x", "https://job-boards.greenhouse.io/testco/jobs/123456"],
])
def test_same_platform_variants_deduplicate_in_one_import(urls, tracker, app_config):
    stats = import_jobs([{"job_url": url} for url in urls], tracker, app_config)
    assert stats["newly_imported"] == 1
    assert stats["duplicate"] == 1
    assert tracker._con.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1

def test_dry_import_deduplicates_without_changes(tracker, app_config):
    before = tracker.db_path.read_bytes()
    stats = import_jobs([{"job_url": "https://boards.greenhouse.io/testco/jobs/123456"}] * 2, tracker, app_config, dry_run=True)
    assert stats["newly_imported"] == 1 and stats["duplicate"] == 1
    assert tracker.db_path.read_bytes() == before

@pytest.mark.parametrize("url", ["ftp://example.com/job", "https://greenhouse.io.evil.test/job", "https://user:password@example.com/job", "https://example.com:abc/job", "not a url"])
def test_bad_or_untrusted_urls_do_not_become_greenhouse(url):
    from auto_apply.importer import infer_platform
    if url == "https://greenhouse.io.evil.test/job":
        assert infer_platform(url) == "unknown"
    else:
        with pytest.raises(ValueError):
            normalize_url(url)

@pytest.mark.parametrize("description", [
    "Must have: Python, LangGraph.",
    "Required skills:\nPython\nDjango",
    "Mandatory: Kubernetes, Python.",
    "Requires Python and Django or Flask.",
])
def test_unknown_mandatory_skill_blocks_keyword_score(description, app_config):
    job = {
        "title": "Python Developer", "location": "India",
        "description": description, "experience": "1-2 years", "application_open": "Open",
    }
    eligible, reason = is_eligible(job, app_config, score_job(job, app_config))
    assert eligible is None
    assert "mandatory requirement" in reason

def test_verified_alternative_satisfies_only_its_group(app_config):
    job = {
        "title": "Python Developer", "location": "India", "description": "Required: Python and FastAPI/Flask/Django.",
        "experience": "1-2 years", "application_open": "Open",
    }
    assert is_eligible(job, app_config, score_job(job, app_config))[0] is True

def test_preferred_gap_is_not_mandatory(app_config):
    job = {
        "title": "Python Developer", "location": "India", "description": "Required: Python\nNice to have: LangGraph.",
        "experience": "1-2 years", "application_open": "Open",
    }
    assert is_eligible(job, app_config, score_job(job, app_config))[0] is True

def test_description_experience_cannot_be_overridden_by_metadata(app_config):
    job = {
        "title": "Python Developer", "location": "India", "description": "Requires 8 years of backend experience.",
        "experience": "1 year", "application_open": "Open",
    }
    assert is_eligible(job, app_config, score_job(job, app_config))[0] is False

@pytest.mark.parametrize("experience", ["nan", "inf", "-1"])
def test_invalid_candidate_experience_remains_unknown(experience, app_config):
    app_config["screening"]["years_of_experience"] = experience
    job = {
        "title": "Python Developer", "location": "India", "description": "Python backend development.",
        "experience": "2 years", "application_open": "Open",
    }
    assert is_eligible(job, app_config, score_job(job, app_config))[0] is None

def test_fractional_experience_is_not_rounded_up(app_config):
    app_config["screening"]["years_of_experience"] = "1.5"
    job = {
        "title": "Python Developer", "location": "India", "description": "Python backend development.",
        "experience": "2 years", "application_open": "Open",
    }
    assert is_eligible(job, app_config, score_job(job, app_config))[0] is False

def test_indiana_is_not_india(app_config):
    job = {
        "title": "Python Developer", "location": "Indiana", "description": "Python backend development.",
        "experience": "2 years", "application_open": "Open",
    }
    assert is_eligible(job, app_config, score_job(job, app_config))[0] is None

def test_title_and_placeholder_description_cannot_establish_eligibility(app_config):
    job = {"title": "Python Developer", "location": "India", "description": "Job details",
           "experience": "2 years", "application_open": "Open"}
    eligible, reason = is_eligible(job, app_config, score_job(job, app_config))
    assert eligible is None
    assert "title matching alone" in reason

def test_closed_is_excluded_even_when_qualifications_are_missing(app_config):
    job = {"title": "Python Developer", "location": "India", "description": "",
           "experience": "", "application_open": "Closed"}
    assert is_eligible(job, app_config, score_job(job, app_config))[0] is False

@pytest.mark.parametrize("location,country,expected", [
    ("Remote", "", None), ("Remote, United States", "United States", None),
    ("Hyderabad", "India", True), ("Remote (India)", "", True),
])
def test_submission_country_scope(location, country, expected, app_config):
    from auto_apply.orchestrator import _submission_eligibility
    job = {"platform": "greenhouse", "job_url": "http://127.0.0.1:9876/jobs/1001",
           "title": "Python Developer", "location": location, "country": country,
           "description": "Python backend development.", "experience": "2 years", "application_open": "Open"}
    assert _submission_eligibility(job, app_config)[0] is expected
