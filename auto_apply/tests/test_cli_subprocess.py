import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

def _cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "auto_apply", *map(str, args)],
        cwd=Path(__file__).resolve().parents[1] / "src",
        capture_output=True, text=True,
    )

def test_run_batch_requires_job_ids(tmp_path):
    result = _cli("--run-batch", "--dry-run", "--db-path", tmp_path / "none.db")
    assert result.returncode == 1
    assert "--job-ids is mandatory" in result.stdout + result.stderr
    assert not (tmp_path / "none.db").exists()

def test_run_batch_live_requires_authorization(tmp_path):
    result = _cli("--run-batch", "--job-ids", "1", "--db-path", tmp_path / "none.db")
    assert result.returncode == 1
    assert "--authorize-submission is mandatory" in result.stdout + result.stderr
    assert not (tmp_path / "none.db").exists()

@pytest.mark.parametrize("bad", ["", "1,", ",1", "0", "-1", "1,1", "abc"])
def test_invalid_selection_fails_without_database(bad, tmp_path):
    result = _cli("--run-batch", "--job-ids", bad, "--dry-run", "--db-path", tmp_path / "none.db")
    assert result.returncode == 1
    assert not (tmp_path / "none.db").exists()

@pytest.mark.parametrize("content", [None, "{bad", '{"human_approval_recorded":true}', "[]"])
def test_invalid_authorization_with_eligible_fixture(content, tracker, make_job, tmp_path):
    job = make_job()
    path = tmp_path / "bad-approval.json"
    if content is not None:
        path.write_text(content)
    before = tracker.db_path.read_bytes()
    result = _cli("--run-batch", "--job-ids", job["id"], "--db-path", tracker.db_path, "--authorize-submission", path)
    assert result.returncode == 1
    assert tracker.db_path.read_bytes() == before

def test_run_batch_live_authorized(tracker, make_job, manifest_factory, tmp_path):
    job = make_job()
    path = manifest_factory(tracker, [job])
    script = tmp_path / "runner.py"
    script.write_text("""
import json, sys
from unittest.mock import patch
from auto_apply.__main__ import main
def execute(job, config, unattended=False, on_before_submit=None, expected_profile=None):
    assert str(expected_profile) == config["browser"]["user_data_dir"]
    attempt = on_before_submit()
    print("MOCKED_ADAPTER_CALLED")
    return "confirmed_submitted", json.dumps({
        "event":"submission_confirmed", "attempt_id":attempt,
        "job_id":job["id"], "job_url":job["job_url"]
    })
with patch("auto_apply.orchestrator.execute_application_automated", side_effect=execute):
    sys.exit(main())
""")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run([
        sys.executable, str(script), "--run-batch", "--job-ids", str(job["id"]),
        "--db-path", str(tracker.db_path), "--authorize-submission", str(path),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MOCKED_ADAPTER_CALLED" in result.stdout
    assert tracker.get_job_by_url(job["job_url"])["status"] == "confirmed_submitted"
    assert tracker._con.execute("SELECT COUNT(*) FROM auto_apply_attempts").fetchone()[0] == 1

def test_prepare_manifest_is_read_only(tracker, make_job, tmp_path):
    job = make_job()
    before = tracker.db_path.read_bytes()
    output = tmp_path / "review.json"
    result = _cli("--prepare-batch", "--job-ids", job["id"], "--db-path", tracker.db_path, "--out", output)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(output.read_text())
    assert payload["human_approval_recorded"] is False
    assert payload["job_previews"][0]["assessment"] == "eligible"
    assert tracker.db_path.read_bytes() == before
    again = _cli("--prepare-batch", "--job-ids", job["id"], "--db-path", tracker.db_path, "--out", output)
    assert again.returncode == 1
    assert output.read_text() == json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

def test_preview_selected_job_is_read_only(tracker, make_job):
    job = make_job()
    before = tracker.db_path.read_bytes()
    result = _cli("--preview-batch", "--job-ids", job["id"], "--db-path", tracker.db_path)
    assert result.returncode == 0
    assert "eligible=1" in result.stdout
    assert tracker.db_path.read_bytes() == before


def _route_csv(tmp_path, application_url):
    row = {
        "platform": "greenhouse",
        "job_url": "https://job-boards.greenhouse.io/fixtureco/jobs/1001",
        "apply_url": application_url,
        "title": "Python Developer", "company": "TestCo", "location": "India",
        "country": "India", "description": "Python and FastAPI backend development.",
        "experience": "1-2 years", "application_open": "Open",
    }
    path = tmp_path / "route.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return path, row


def test_csv_preserves_and_previews_exact_application_route(tracker, tmp_path):
    form = "https://job-boards.greenhouse.io/embed/job_app?for=fixtureco&token=1001"
    path, row = _route_csv(tmp_path, form)
    before = tracker.db_path.read_bytes()
    preview = _cli("--import-csv", path, "--dry-run", "--db-path", tracker.db_path)
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert f"Form URL:  {form}" in preview.stdout
    assert tracker.db_path.read_bytes() == before
    imported = _cli("--import-csv", path, "--db-path", tracker.db_path)
    assert imported.returncode == 0, imported.stdout + imported.stderr
    saved = tracker.get_job_by_url(row["job_url"])
    assert saved["apply_url"] == form
    assert saved["status"] == "pending"
    assert not (tmp_path / "profile").exists()


def test_csv_rejects_conflicting_application_route(tracker, tmp_path):
    path, row = _route_csv(tmp_path, "https://job-boards.greenhouse.io/embed/job_app?for=fixtureco&token=9999")
    result = _cli("--import-csv", path, "--db-path", tracker.db_path)
    assert result.returncode == 1
    assert "same approved Greenhouse" in result.stdout
    assert "errors=1" in result.stdout
    assert tracker.get_job_by_url(row["job_url"]) is None
    assert not (tmp_path / "profile").exists()
