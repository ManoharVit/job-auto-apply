"""Real browser integration against intercepted local HTTP forms."""
import json

import pytest

from auto_apply.orchestrator import run_resume_job, run_unattended_batch

def _run(tracker, job, manifest):
    run_unattended_batch(db_path=tracker.db_path, job_ids=[job["id"]], auth_file=str(manifest))

def test_successful_confirmation(tracker, make_job, manifest_factory, fixture_browser):
    job = make_job()
    manifest = manifest_factory(tracker, [job])
    _run(tracker, job, manifest)
    row = tracker.get_job_by_url(job["job_url"])
    assert row["status"] == "confirmed_submitted"
    attempt = tracker._con.execute("SELECT * FROM auto_apply_attempts").fetchone()
    assert attempt["outcome"] == "confirmed"
    receipt = json.loads(attempt["evidence"])
    assert receipt["job_id"] == job["id"]
    assert receipt["attempt_id"] == attempt["attempt_id"]
    posts = [request for request in fixture_browser[1] if request[0] == "POST"]
    assert len(posts) == 1
    assert "candidate.pdf" in posts[0][2]

@pytest.mark.parametrize("extra", [
    '<label for="q">Unknown answer</label><input id="q" name="q" required>',
    '<input name="consent" type="checkbox" required><label>Consent</label>',
    '<label>Choose one</label><input name="choice" type="radio" value="yes" required><input name="choice" type="radio" value="no">',
    '<label for="choice">Choice</label><select id="choice" name="choice" required><option value="">Select</option><option>Yes</option></select>',
    '<input role="combobox" aria-label="Custom question" aria-required="true">',
])
def test_missing_mandatory_answers(extra, tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]["extra"] = extra
    job = make_job()
    _run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job["job_url"])["status"] == "paused"
    assert not [request for request in fixture_browser[1] if request[0] == "POST"]
    assert tracker._con.execute("SELECT COUNT(*) FROM auto_apply_attempts").fetchone()[0] == 0

def test_prefilled_unknown_required_answer_is_not_verified(tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]["extra"] = '<label for="q">Years of professional Django experience</label><input id="q" name="q" value="2" required>'
    job = make_job()
    _run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job["job_url"])["status"] == "paused"
    assert not [request for request in fixture_browser[1] if request[0] == "POST"]

def test_exact_verified_question_answer_is_reused(tracker, make_job, manifest_factory, fixture_browser, app_config):
    fixture_browser[0]["extra"] = '<label for="q">Total years of experience</label><input id="q" name="q" required>'
    app_config["application_answers"] = {"Total years of experience": "2"}
    job = make_job()
    _run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job["job_url"])["status"] == "confirmed_submitted"

def test_optional_demographic_prefill_is_cleared(tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]["extra"] = '<label for="gender">Gender</label><select id="gender" name="gender"><option value="male" selected>Male</option><option value="female">Female</option></select>'
    job = make_job()
    _run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job["job_url"])["status"] == "confirmed_submitted"
    body = next(request[2] for request in fixture_browser[1] if request[0] == "POST")
    assert 'name="gender"' not in body

def test_required_demographic_prefers_nondisclosure(tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]["extra"] = '<label for="gender">Gender</label><select id="gender" name="gender" required><option value="male" selected>Male</option><option value="decline">Prefer not to answer</option></select>'
    job = make_job()
    _run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job["job_url"])["status"] == "confirmed_submitted"
    body = next(request[2] for request in fixture_browser[1] if request[0] == "POST")
    assert "decline" in body

def test_india_answer_is_not_reused_for_us_authorization(tracker, make_job, manifest_factory, fixture_browser, app_config):
    question = "Are you authorized to work in the United States?"
    fixture_browser[0]["extra"] = f'<label for="auth">{question}</label><select id="auth" name="auth" required><option value="">Select</option><option value="yes">Yes</option></select>'
    app_config["application_answers"] = {question: {"value": "Yes", "country": "India"}}
    job = make_job()
    _run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job["job_url"])["status"] == "paused"
    assert not [request for request in fixture_browser[1] if request[0] == "POST"]

def test_upload_exception_stops_before_submit(tracker, make_job, manifest_factory, fixture_browser, monkeypatch):
    from playwright.sync_api import Locator
    monkeypatch.setattr(Locator, "set_input_files", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("upload rejected")))
    job = make_job()
    _run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job["job_url"])["status"] == "failed"
    assert not [request for request in fixture_browser[1] if request[0] == "POST"]
    assert tracker._con.execute("SELECT COUNT(*) FROM auto_apply_attempts").fetchone()[0] == 0

def test_cover_letter_control_does_not_receive_resume(tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]["extra"] = '<label for="cover">Cover letter</label><input id="cover" name="cover_letter" type="file">'
    job = make_job()
    _run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job["job_url"])["status"] == "confirmed_submitted"

@pytest.mark.parametrize("scenario, expected", [
    ("reject", "failed"), ("no_post", "unconfirmed"), ("wrong_job", "unconfirmed"),
])
def test_rejection_and_ambiguous_confirmation(scenario, expected, tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0][scenario] = True
    job = make_job()
    _run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job["job_url"])["status"] == expected
    attempt = tracker._con.execute("SELECT * FROM auto_apply_attempts").fetchone()
    assert attempt["outcome"] == ("rejected" if expected == "failed" else "ambiguous")

def test_old_success_text_is_not_confirmation(tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]["extra"] = '<p>Application submitted for another company</p>'
    fixture_browser[0]["reject"] = True
    job = make_job()
    _run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job["job_url"])["status"] == "failed"

def test_title_mismatch_stops_before_submit(tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]["title"] = "Senior Java Developer"
    job = make_job()
    _run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job["job_url"])["status"] == "paused"
    assert not [request for request in fixture_browser[1] if request[0] == "POST"]

def test_live_description_change_stops_before_submit(tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]["description"] = "Must have: Python, LangGraph, 8 years of experience."
    job = make_job()
    _run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job["job_url"])["status"] == "paused"
    assert not [request for request in fixture_browser[1] if request[0] == "POST"]

def test_dry_run_no_browser_or_database_writes(tracker, make_job, monkeypatch):
    job = make_job()
    before = tracker.db_path.read_bytes()
    monkeypatch.setattr("auto_apply.orchestrator.execute_application_automated", lambda *args, **kwargs: pytest.fail("Browser workflow invoked"))
    run_unattended_batch(dry_run=True, db_path=tracker.db_path, job_ids=[job["id"]])
    assert tracker.db_path.read_bytes() == before
    assert not tracker._con.execute("SELECT name FROM sqlite_master WHERE name = 'auto_apply_attempts'").fetchone()

def test_changed_approval_inputs_do_not_write(tracker, make_job, manifest_factory, app_config):
    from auto_apply.authorization import AuthorizationError
    job = make_job()
    manifest = manifest_factory(tracker, [job])
    app_config["profile"]["skills"].append("Invented")
    before = tracker.db_path.read_bytes()
    with pytest.raises(AuthorizationError, match="Integrity check mismatch"):
        _run(tracker, job, manifest)
    assert tracker.db_path.read_bytes() == before

def test_unsupported_platform_never_opens_browser(tracker, make_job, manifest_factory, monkeypatch):
    job = make_job(platform="naukri")
    manifest = manifest_factory(tracker, [job])
    monkeypatch.setattr("auto_apply.orchestrator.execute_application_automated", lambda *args, **kwargs: pytest.fail("Unsupported browser workflow"))
    with pytest.raises(ValueError, match="Only the Greenhouse"):
        run_unattended_batch(platform="naukri", db_path=tracker.db_path, job_ids=[job["id"]], auth_file=str(manifest))

def test_duplicate_execution_does_not_post_twice(tracker, make_job, manifest_factory, fixture_browser):
    job = make_job()
    manifest = manifest_factory(tracker, [job])
    _run(tracker, job, manifest)
    original_timestamp = tracker.get_job_by_url(job["job_url"])["applied_at"]
    _run(tracker, job, manifest)
    assert len([request for request in fixture_browser[1] if request[0] == "POST"]) == 1
    assert tracker.get_job_by_url(job["job_url"])["applied_at"] == original_timestamp

def test_resume_uses_same_guard(tracker, make_job, manifest_factory, fixture_browser, monkeypatch):
    job = make_job()
    tracker.update_job(job["id"], "paused", action="PREPARATION", reason="challenge")
    manifest = manifest_factory(tracker, [job])
    monkeypatch.setattr("builtins.input", lambda prompt: "submit")
    run_resume_job(job["id"], str(manifest), db_path=tracker.db_path)
    assert tracker.get_job_by_url(job["job_url"])["status"] == "confirmed_submitted"
    assert tracker._con.execute("SELECT COUNT(*) FROM auto_apply_attempts").fetchone()[0] == 1

def test_resume_retains_multi_job_approval_scope(tracker, make_job, manifest_factory, fixture_browser, monkeypatch):
    first, second = make_job(), make_job()
    tracker.update_job(first["id"], "paused", action="PREPARATION", reason="challenge")
    manifest = manifest_factory(tracker, [first, second])
    monkeypatch.setattr("builtins.input", lambda prompt: "submit")
    run_resume_job(first["id"], str(manifest), db_path=tracker.db_path)
    assert tracker.get_job_by_url(first["job_url"])["status"] == "confirmed_submitted"
    assert tracker.get_job_by_url(second["job_url"])["status"] == "pending"
