import json
from datetime import datetime, timedelta, timezone

import pytest

from auto_apply.authorization import AuthorizationError, get_integrity_hashes, validate_authorization

def _validate(path, tracker, records, config):
    return validate_authorization(path, [row["id"] for row in records], config, records, tracker.db_path)

def test_missing_file(tracker, make_job, app_config):
    job = make_job()
    with pytest.raises(AuthorizationError, match="not found"):
        _validate("nonexistent.json", tracker, [job], app_config)

@pytest.mark.parametrize("content", ["{bad json", "[]", '"string"', "null"])
def test_malformed_or_wrong_schema(content, tmp_path, tracker, make_job, app_config):
    job = make_job()
    file = tmp_path / "bad.json"
    file.write_text(content)
    with pytest.raises(AuthorizationError):
        _validate(file, tracker, [job], app_config)

@pytest.mark.parametrize("flag", [False, None, "true", 1])
def test_missing_approval_flag(flag, tracker, make_job, app_config, manifest_factory):
    job = make_job()
    path = manifest_factory(tracker, [job], human_approval_recorded=flag)
    with pytest.raises(AuthorizationError, match="explicitly approved"):
        _validate(path, tracker, [job], app_config)

@pytest.mark.parametrize("ids", [[], [0], [-1], [True], [1, 1], ["1"], [9999]])
def test_wrong_job_ids(ids, tracker, make_job, app_config, manifest_factory):
    job = make_job()
    path = manifest_factory(tracker, [job], approved_jobs=ids)
    with pytest.raises(AuthorizationError):
        _validate(path, tracker, [job], app_config)

def test_tampering_hash_mismatch(tracker, make_job, app_config, manifest_factory):
    job = make_job()
    path = manifest_factory(tracker, [job])
    payload = json.loads(path.read_text())
    payload["integrity_checks"]["profile"] = "changed"
    path.write_text(json.dumps(payload))
    with pytest.raises(AuthorizationError, match="profile"):
        _validate(path, tracker, [job], app_config)

def test_valid_authorization(tracker, make_job, app_config, manifest_factory):
    job = make_job()
    path = manifest_factory(tracker, [job])
    assert _validate(path, tracker, [job], app_config)["approved_jobs"] == [job["id"]]

@pytest.mark.parametrize("field,value", [
    ("location", "United States"), ("platform", "naukri"),
    ("description", "Requires senior Django experience"), ("experience", "8 years"),
    ("application_open", "Closed"), ("company", "Wrong Company"),
])
def test_changed_job_metadata_rejects_approval(field, value, tracker, make_job, app_config, manifest_factory):
    job = make_job()
    path = manifest_factory(tracker, [job])
    changed = dict(job) | {field: value}
    with pytest.raises(AuthorizationError, match="jobs"):
        _validate(path, tracker, [changed], app_config)

@pytest.mark.parametrize("section,key,value", [
    ("screening", "years_of_experience", "20"),
    ("profile", "skills", ["Invented"]),
    ("browser", "headless", False),
])
def test_changed_material_configuration(section, key, value, tracker, make_job, app_config, manifest_factory):
    job = make_job()
    path = manifest_factory(tracker, [job])
    app_config[section][key] = value
    with pytest.raises(AuthorizationError, match="Integrity check mismatch"):
        _validate(path, tracker, [job], app_config)

def test_changed_resume_bytes(tracker, make_job, app_config, manifest_factory):
    from pathlib import Path
    job = make_job()
    path = manifest_factory(tracker, [job])
    Path(app_config["profile"]["resume_path"]).write_bytes(b"different resume")
    with pytest.raises(AuthorizationError, match="resume"):
        _validate(path, tracker, [job], app_config)

def test_missing_record_cannot_mask_authorization(tracker, make_job, app_config, manifest_factory):
    job = make_job()
    path = manifest_factory(tracker, [job])
    with pytest.raises(AuthorizationError):
        validate_authorization(path, [job["id"]], app_config, [], tracker.db_path)

def test_expired_approval(tracker, make_job, app_config, manifest_factory):
    job = make_job()
    path = manifest_factory(tracker, [job], expires_at_utc="2000-01-01T00:00:00Z")
    with pytest.raises(AuthorizationError, match="expired"):
        _validate(path, tracker, [job], app_config)

def test_different_database_path_rejected(tracker, make_job, app_config, manifest_factory, tmp_path):
    job = make_job()
    path = manifest_factory(tracker, [job])
    with pytest.raises(AuthorizationError, match="different database"):
        validate_authorization(path, [job["id"]], app_config, [job], tmp_path / "other.db")

def test_pilot_rejects_six_jobs(tracker, make_job, app_config, manifest_factory):
    jobs = [make_job() for _ in range(6)]
    path = manifest_factory(tracker, jobs)
    with pytest.raises(AuthorizationError, match="at most five"):
        validate_authorization(path, [job["id"] for job in jobs], app_config, jobs, tracker.db_path)
