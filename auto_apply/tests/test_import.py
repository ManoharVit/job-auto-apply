import pytest
from pathlib import Path
from auto_apply.importer import import_jobs, normalize_url
from auto_apply.tracker import TrackerDB

PROFILE_CONFIG = {
    "profile": {
        "skills": ["Python", "FastAPI"],
        "target_titles": ["Backend Developer", "Python Developer"],
        "locations": ["Remote", "Hyderabad"]
    },
    "screening": {
        "years_of_experience": "3"
    },
    "filters": {
        "min_score": 10,
        "excluded_title_keywords": ["Senior", "Lead"]
    }
}

@pytest.fixture
def temp_tracker(tmp_path):
    db_path = tmp_path / "test_tracker.db"
    db_path.touch()
    tracker = TrackerDB(db_path)
    # create table schema since touch() makes an empty DB
    tracker._con.execute("""
    """)
    tracker._con.commit()
    yield tracker
    tracker.close()

def test_normalize_url():
    # Remove tracking from LinkedIn
    assert normalize_url("https://www.linkedin.com/jobs/view/12345?trackingId=abc&refId=123") == "https://www.linkedin.com/jobs/view/12345"
    # Keep query params for other domains if any
    assert normalize_url("https://example.com/jobs?id=123") == "https://example.com/jobs?id=123"

def test_import_jobs_new(temp_tracker):
    jobs = [
        {"job_url": "https://example.com/1", "title": "Python Developer", "company": "A", "location": "Remote", "description": "Good description", "experience": "2 years"},
        {"job_url": "https://example.com/2", "title": "Java Developer", "company": "B", "location": "Remote", "description": "Good description", "experience": "2 years"}
    ]
    
    stats = import_jobs(jobs, temp_tracker, PROFILE_CONFIG, dry_run=False)
    
    assert stats["newly_imported"] == 2
    assert stats["eligible"] == 1   # Python Developer
    assert stats["excluded"] == 1   # Java Developer
    
    # Check DB
    pending = temp_tracker.get_pending_jobs()
    assert len(pending) == 2

def test_import_jobs_duplicate(temp_tracker):
    # Setup initial
    jobs = [{"job_url": "https://example.com/1", "title": "Python Developer", "company": "A", "location": "Remote", "description": "Desc", "experience": "2 yrs"}]
    import_jobs(jobs, temp_tracker, PROFILE_CONFIG, dry_run=False)
    
    # Try importing duplicate and a new one
    jobs2 = [
        {"job_url": "https://example.com/1", "title": "Python Developer", "company": "A", "location": "Remote", "description": "Desc", "experience": "2 yrs"},
        {"job_url": "https://example.com/3", "title": "Backend Developer", "company": "C", "location": "Hyderabad", "description": "Desc", "experience": "2 yrs"}
    ]
    
    stats = import_jobs(jobs2, temp_tracker, PROFILE_CONFIG, dry_run=False)
    assert stats["duplicate"] == 1
    assert stats["newly_imported"] == 1
    
    pending = temp_tracker.get_pending_jobs()
    assert len(pending) == 2

def test_import_preserves_status(temp_tracker):
    jobs = [{"job_url": "https://example.com/1", "title": "Python Developer", "company": "A", "location": "Remote", "description": "Desc", "experience": "2 yrs"}]
    import_jobs(jobs, temp_tracker, PROFILE_CONFIG, dry_run=False)
    
    pending = temp_tracker.get_pending_jobs()
    job_id = pending[0]["id"]
    
    # Change status
    temp_tracker.update_job(job_id, status="confirmed_submitted", action="Manual", reason="test")
    
    # Reimport
    stats = import_jobs(jobs, temp_tracker, PROFILE_CONFIG, dry_run=False)
    assert stats["duplicate"] == 1
    
    # Check status is still confirmed_submitted
    db_job = temp_tracker.get_job_by_url("https://example.com/1")
    assert db_job["status"] == "confirmed_submitted"

def test_import_duplicate_platform_id(temp_tracker):
    # Job with LinkedIn platform URL
    jobs1 = [{"job_url": "https://in.linkedin.com/jobs/view/1234567/", "title": "Old Title", "company": "A", "location": "Remote", "description": "Old Desc", "experience": "1 yr"}]
    import_jobs(jobs1, temp_tracker, PROFILE_CONFIG, dry_run=False)
    
    pending = temp_tracker.get_pending_jobs()
    job_id = pending[0]["id"]
    temp_tracker.update_job(job_id, status="confirmed_submitted", action="Manual", reason="test")
    
    # Same job ID, different netloc/subdomain
    jobs2 = [{"job_url": "https://www.linkedin.com/jobs/view/1234567/?trackingId=xyz", "title": "New Title", "company": "B", "location": "Remote", "description": "New Desc", "experience": "2 yr"}]
    stats = import_jobs(jobs2, temp_tracker, PROFILE_CONFIG, dry_run=False)
    
    assert stats["duplicate"] == 1
    
    # Metadata should be preserved (update_job_details keeps old data if present)
    db_job = temp_tracker.get_job_by_url("https://in.linkedin.com/jobs/view/1234567/")
    assert db_job is not None
    assert db_job["status"] == "confirmed_submitted"
    assert db_job["title"] == "Old Title"
    assert db_job["company"] == "A"
    assert db_job["description"] == "Old Desc"
    assert db_job["experience"] == "1 yr"

def test_url_only_import_needs_review(temp_tracker):
    jobs = [{"job_url": "https://example.com/unknown", "title": "", "company": "", "location": ""}]
    
    stats = import_jobs(jobs, temp_tracker, PROFILE_CONFIG, dry_run=False)
    assert stats["review_needed"] == 1
    assert stats["eligible"] == 0
    assert stats["excluded"] == 0
    
def test_dry_run_does_not_save(temp_tracker):
    jobs = [{"job_url": "https://example.com/1", "title": "Python Developer", "company": "A", "location": "Remote"}]
    stats = import_jobs(jobs, temp_tracker, PROFILE_CONFIG, dry_run=True)
    assert stats["newly_imported"] == 1
    
    pending = temp_tracker.get_pending_jobs()
    assert len(pending) == 0

