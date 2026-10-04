"""Shared fixtures: synthetic legacy tracker databases built in tmp_path.

The real job-auto-apply/tracker.db is never touched by the test suite.
"""

import sqlite3
from pathlib import Path

import pytest

# Exact schema used by the legacy tracker.py (copied verbatim).
LEGACY_SCHEMA = """
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    job_url TEXT UNIQUE NOT NULL,
    title TEXT,
    company TEXT,
    location TEXT,
    match_score REAL,
    status TEXT DEFAULT 'pending',
    error_message TEXT,
    applied_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

# (platform, job_url, title, company, location, score, status, error_message, created_at)
SAMPLE_ROWS = [
    ("linkedin", "https://in.linkedin.com/jobs/view/111?trk=public_jobs&utm_source=x",
     "Python Backend Developer", "Acme Fintech", "Hyderabad", 72.5,
     "SUBMISSION_UNCONFIRMED", None, "2026-09-24 10:00:00"),
    ("linkedin", "https://www.linkedin.com/jobs/view/111",
     "Python Backend Developer", "Acme Fintech", "Hyderabad", 72.5,
     "pending", None, "2026-09-25 10:00:00"),
    ("naukri", "https://www.naukri.com/job-listings-databricks-data-engineer-222",
     "Databricks Data Engineer", "DataCo", "Bengaluru", 40.0,
     "SUBMISSION_UNCONFIRMED", None, "2026-09-26 10:00:00"),
    ("linkedin", "https://careers.example.com/apply?jobid=333&utm_medium=social",
     "AI Engineer", "Example Labs", "Remote", 65.0,
     "skipped", "easy_apply_failed_or_external", "2026-09-27 10:00:00"),
    ("naukri", "https://www.naukri.com/job-listings-fastapi-developer-444",
     "FastAPI Developer", "  example labs ", "Pune", 58.0,
     "skipped", "naukri_apply_failed", "2026-09-28 10:00:00"),
    ("linkedin", "https://jobs.example.org/555",
     "Java Developer", "OtherCorp", "Chennai", 20.0,
     "skipped", "tech_mismatch_retroactive", "2026-09-29 10:00:00"),
    ("linkedin", "https://jobs.example.org/666",
     None, None, None, None,
     "applied", None, "2026-09-30 10:00:00"),
    ("naukri", "https://www.naukri.com/job-listings-weird-777",
     "Backend Engineer", "Mystery Inc", "India", 50.0,
     "some_new_status", None, "2026-10-01 10:00:00"),
    ("naukri", "https://www.naukri.com/job-listings-fastapi-developer-888",
     "fastapi   developer", "Example Labs", "Pune", 61.0,
     "pending", None, "2026-10-02 10:00:00"),
]


def build_legacy_db(path: Path, rows=SAMPLE_ROWS) -> Path:
    con = sqlite3.connect(path)
    con.execute(LEGACY_SCHEMA)
    con.executemany(
        "INSERT INTO applications (platform, job_url, title, company, location, "
        "match_score, status, error_message, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    con.commit()
    con.close()
    return path


@pytest.fixture
def legacy_db(tmp_path: Path) -> Path:
    return build_legacy_db(tmp_path / "tracker.db")


@pytest.fixture
def empty_legacy_db(tmp_path: Path) -> Path:
    return build_legacy_db(tmp_path / "empty.db", rows=[])
