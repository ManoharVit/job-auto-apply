"""Recorded human approval and integrity checks; this is not a signature."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .settings import browser_profile, effective_policy, resume_file
from .answer_memory import memory_integrity

class AuthorizationError(ValueError):
    pass

def _compute_hash(data):
    return hashlib.sha256(json.dumps(
        data, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()

def validate_job_ids(values):
    if not isinstance(values, list) or not values:
        raise AuthorizationError("Job IDs must be a nonempty list.")
    if any(type(value) is not int or value <= 0 for value in values):
        raise AuthorizationError("Job IDs must be positive integers.")
    if len(set(values)) != len(values):
        raise AuthorizationError("Job IDs must be unique.")
    return sorted(values)

def get_integrity_hashes(config, job_records=None):
    profile = config.get("profile", {})
    path = resume_file(config)
    resume_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else "missing"
    fields = (
        "id", "job_url", "apply_url", "platform", "title", "company", "location", "country",
        "description", "experience", "application_open", "review_reason",
        "is_fixture", "required_skills", "mandatory_requirements",
    )
    jobs = [{key: job.get(key) for key in fields} for job in sorted(
        job_records or [], key=lambda job: job["id"]
    )]
    runtime_files = (
        "settings.py", "authorization.py", "submission_guard.py",
        "requirements.py", "answer_memory.py",
        "tracker.py", "__main__.py", "approval.py", "importer.py",
        "orchestrator.py", "automation.py", "challenge_handler.py",
        "adapters/greenhouse.py",
    )
    package = Path(__file__).resolve().parent
    runtime = {
        name: hashlib.sha256((package / name).read_bytes()).hexdigest()
        for name in runtime_files
        if (package / name).is_file()
    }
    return {
        "profile": _compute_hash(profile),
        "browser_profile": _compute_hash(str(browser_profile(config))),
        "answer_memory": _compute_hash(memory_integrity(config)),
        "filters": _compute_hash(config.get("filters", {})),
        "screening": _compute_hash({
            key: config.get(key, {})
            for key in ("screening", "demographics", "eeo", "application_answers")
        }),
        "resume": resume_hash,
        "jobs": _compute_hash(jobs),
        "policy": _compute_hash({"policy": effective_policy(config), "runtime": runtime}),
    }

def validate_authorization(auth_file_path, expected_job_ids, config, job_records, db_path=None):
    ids = validate_job_ids(expected_job_ids)
    if not auth_file_path:
        raise AuthorizationError("Approval manifest is missing.")
    path = Path(auth_file_path)
    if not path.is_file():
        raise AuthorizationError("Approval file not found.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuthorizationError("Approval file is not readable, valid JSON.") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 2:
        raise AuthorizationError("Generate a current schema-version-2 approval draft.")
    if data.get("review_only") is True:
        raise AuthorizationError("A review-only staging manifest cannot authorize submission. Prepare a production-bound draft after reviewing the import.")
    if data.get("human_approval_recorded") is not True:
        raise AuthorizationError("The draft has not been explicitly approved by the human.")
    if validate_job_ids(data.get("approved_jobs")) != ids:
        raise AuthorizationError("Approved job IDs do not match the requested batch.")
    record_ids = validate_job_ids([job["id"] for job in job_records])
    if record_ids != ids:
        raise AuthorizationError("Every approved job must exist exactly once in the selected database.")
    if db_path is None or data.get("database_path") != str(Path(db_path).expanduser().resolve()):
        raise AuthorizationError("Approval is bound to a different database path.")
    phase = data.get("phase")
    if phase not in ("pilot", "daily"):
        raise AuthorizationError("Approval phase must be pilot or daily.")
    if phase == "pilot" and len(ids) > effective_policy(config)["pilot_job_cap"]:
        raise AuthorizationError("A pilot contains at most five approved jobs.")
    if phase == "daily" and (
        data.get("pilot_review_recorded") is not True or not data.get("reviewed_pilot")
    ):
        raise AuthorizationError("Daily batches require an explicit review of the previous pilot.")
    try:
        expiry = datetime.fromisoformat(data["expires_at_utc"].replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError()
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthorizationError("Approval has expired or has no valid timezone-aware expiry.") from exc
    checks = data.get("integrity_checks")
    expected = get_integrity_hashes(config, job_records)
    if not isinstance(checks, dict):
        raise AuthorizationError("Approval integrity checks are missing.")
    for key, digest in expected.items():
        if checks.get(key) != digest:
            raise AuthorizationError(f"Integrity check mismatch for '{key}'; review a new draft.")
    if expected["resume"] == "missing":
        raise AuthorizationError("The approved resume must exist before a live submission.")
    return data
