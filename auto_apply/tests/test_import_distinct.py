import pytest
from auto_apply.importer import import_jobs
from test_import import temp_tracker, PROFILE_CONFIG

def test_distinct_jobs(temp_tracker):
    jobs = [
        {"job_url": "https://www.linkedin.com/jobs/view/123/", "title": "A"},
        {"job_url": "https://www.linkedin.com/jobs/view/124/", "title": "B"},
        {"job_url": "https://naukri.com/job-123", "title": "C"},
        {"job_url": "https://naukri.com/job-124", "title": "D"}
    ]
    stats = import_jobs(jobs, temp_tracker, PROFILE_CONFIG, dry_run=False)
    assert stats["newly_imported"] == 4
    assert stats["duplicate"] == 0
