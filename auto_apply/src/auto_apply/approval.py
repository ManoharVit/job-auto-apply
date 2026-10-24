"""Read-only preparation of a concrete, unapproved batch manifest."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .authorization import get_integrity_hashes, validate_job_ids
from .tracker import TrackerDB
from .settings import browser_profile, job_application_url
from .answer_memory import application_answers, memory_integrity

def prepare_approval(job_ids, db_path, output_path, phase="pilot", reviewed_pilot=None):
    from .orchestrator import (
        _database_path, _selected_records, _submission_eligibility, load_config,
    )
    ids = validate_job_ids(job_ids)
    if phase not in ("pilot", "daily"):
        raise ValueError("Phase must be pilot or daily.")
    if phase == "pilot" and len(ids) > 5:
        raise ValueError("The first pilot contains at most five jobs.")
    config = load_config()
    database = _database_path(config, db_path)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise ValueError("The output already exists; it will not be overwritten.")
    tracker = TrackerDB(database, dry_run=True)
    try:
        records = _selected_records(tracker, ids)
        previous = None
        if phase == "daily":
            try:
                row = tracker._con.execute(
                    "SELECT * FROM auto_apply_pilot WHERE singleton = 1"
                ).fetchone()
            except sqlite3.OperationalError:
                row = None
            if row is None:
                raise ValueError("No recorded pilot exists. Complete and inspect the first pilot before daily batches.")
            if reviewed_pilot and reviewed_pilot != row["pilot_id"]:
                raise ValueError("The requested pilot review does not match this database.")
            reviewed_pilot = row["pilot_id"]
            pilot_ids = json.loads(row["job_ids"])
            previous = {
                "pilot_id": reviewed_pilot,
                "outcomes": [
                    {"id": row["id"], "title": row["title"], "company": row["company"], "status": row["status"]}
                    for row in _selected_records(tracker, pilot_ids)
                ],
            }
        previews = []
        for job in records:
            eligible, reason = _submission_eligibility(job, config)
            previews.append({
                "id": job["id"], "url": job_application_url(job), "listing_url": job["job_url"], "title": job["title"],
                "company": job["company"], "location": job.get("location"),
                "country": job.get("country"),
                "description": job.get("description"), "experience": job.get("experience"),
                "availability": job.get("application_open"), "status": job["status"],
                "assessment": "eligible" if eligible is True else "excluded" if eligible is False else "review_needed",
                "reason": reason,
            })
        now = datetime.now(timezone.utc)
        payload = {
            "schema_version": 2,
            "database_path": str(database),
            "browser_profile_path": str(browser_profile(config)),
            "human_approval_recorded": False,
            "phase": phase,
            "approved_jobs": ids,
            "created_at_utc": now.isoformat(),
            "expires_at_utc": (now + timedelta(hours=24)).isoformat(),
            "integrity_checks": get_integrity_hashes(config, records),
            "job_previews": previews,
            "proposed_answers": {
                key: config.get(key, {})
                for key in ("profile", "screening", "demographics", "eeo", "application_answers")
            },
            "saved_answer_memory": {
                "integrity": memory_integrity(config),
                "answers_by_job": {str(job["id"]): application_answers(config, job) for job in records},
            },
        }
        if phase == "daily":
            payload.update({
                "reviewed_pilot": reviewed_pilot,
                "pilot_review_recorded": False,
                "previous_pilot": previous,
            })
    finally:
        tracker.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"Unapproved {phase} draft saved to {output}")
    print("Review job fit, unresolved questions, resume and proposed facts before recording human approval.")
    if phase == "daily":
        print("Inspect the previous pilot outcomes before recording pilot_review_recorded=true.")
    return output
