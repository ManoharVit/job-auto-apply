import pytest
from pathlib import Path
from auto_apply.tracker import TrackerDB
from auto_apply.orchestrator import run_workflow
import sqlite3

def test_ineligible_job_status_unchanged(tmp_path, monkeypatch):
    """
    Test that an ineligible job is excluded from the session view
    but its database status remains 'pending' and is not auto-dismissed.
    """
    db_path = tmp_path / "test_tracker.db"
    
    # Track sqlite3.connect to ensure it only hits our db_path
    original_connect = sqlite3.connect
    def mock_connect(*args, **kwargs):
        arg0 = args[0] if args else kwargs.get('database')
        if not arg0.startswith(f"file:{db_path.as_posix()}?mode="):
            raise AssertionError(f"Database connection attempted to incorrect path: {arg0}")
        return original_connect(*args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", mock_connect)

    tracker = TrackerDB(db_path, dry_run=False) # allow creation
    
    # Add a job that will definitely be EXCLUDED
    # Score 0 (no title match, no skills)
    tracker.add_job({
        "platform": "test",
        "job_url": "http://test.com/1",
        "title": "Random Unrelated Job",
        "company": "TestCorp",
        "location": "Nowhere"
    })
    
    # The job is pending
    assert tracker.get_job_by_url("http://test.com/1")["status"] == "pending"
    
    tracker.close()
    
    # Make input() raise AssertionError if called
    def mock_input(prompt):
        raise AssertionError("input() should not be called for an excluded job!")
    monkeypatch.setattr('builtins.input', mock_input)
    
    # Make browser/apply raise AssertionError
    def mock_launch(*args, **kwargs):
        raise AssertionError("Browser launch should not be called!")
    monkeypatch.setattr('auto_apply.automation.apply_to_job', mock_launch, raising=False)
    monkeypatch.setattr('auto_apply.automation.apply_to_linkedin', mock_launch, raising=False)
    monkeypatch.setattr('auto_apply.automation.apply_to_naukri', mock_launch, raising=False)
    
    run_workflow(platform=None, dry_run=False, db_path=db_path)
    
    # Re-open and verify the status is still pending
    tracker2 = TrackerDB(db_path, dry_run=True)
    job = tracker2.get_job_by_url("http://test.com/1")
    assert job is not None
    assert job["status"] == "pending", "Status should not be auto-dismissed/skipped!"
    tracker2.close()

