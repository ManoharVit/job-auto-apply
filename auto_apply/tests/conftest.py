"""Synthetic configuration and isolated browser boundaries for every test."""
import copy
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    resume = tmp_path / "candidate.pdf"
    resume.write_bytes(b"%PDF-1.4\n1 0 obj <<>> endobj\n%%EOF\n")
    config = {
        "profile": {
            "name": "Test Candidate", "email": "candidate@example.test", "phone": "5550100",
            "resume_path": str(resume), "skills": ["Python", "FastAPI", "PostgreSQL", "Git"],
            "target_titles": ["Python Developer", "Backend Developer"],
            "locations": ["India", "Remote", "Hyderabad"],
        },
        "screening": {"years_of_experience": "2", "work_authorization_india": True},
        "filters": {"min_score": 10, "excluded_title_keywords": ["Senior", "Lead"]},
        "paths": {"db_path": str(tmp_path / "tracker.db")},
        "browser": {
            "user_data_dir": str(tmp_path / "profile"),
            "allow_local_fixtures": True,
            "headless": os.environ.get("AUTO_APPLY_SHOW_LOCAL_FIXTURE") != "1",
            "submission_timeout_seconds": 1,
        },
    }
    config_path = tmp_path / "test-config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    monkeypatch.setenv("AUTO_APPLY_CONFIG", str(config_path))
    monkeypatch.setenv("AUTO_APPLY_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("AUTO_APPLY_TEST_MODE", "1")
    return config

@pytest.fixture
def app_config(isolated_environment, monkeypatch):
    import auto_apply.orchestrator as orchestrator
    config = copy.deepcopy(isolated_environment)
    monkeypatch.setattr(orchestrator, "load_config", lambda: copy.deepcopy(config))
    return config

@pytest.fixture
def tracker(tmp_path):
    from auto_apply.tracker import TrackerDB
    database = TrackerDB(tmp_path / "tracker.db")
    yield database
    database.close()

@pytest.fixture
def make_job(tracker):
    def create(**updates):
        index = tracker._con.execute("SELECT COUNT(*) FROM applications").fetchone()[0] + 1001
        job = {
            "platform": "greenhouse", "job_url": f"http://127.0.0.1:9876/jobs/{index}",
            "title": "Python Developer", "company": "TestCo", "location": "India",
            "description": "Python and FastAPI backend development.", "experience": "1-2 years",
            "application_open": "Open",
        }
        job.update(updates)
        tracker.add_job(job)
        return tracker.get_job_by_url(job["job_url"])
    return create

@pytest.fixture
def manifest_factory(tmp_path, app_config):
    from auto_apply.authorization import get_integrity_hashes
    def create(tracker, records, **updates):
        payload = {
            "schema_version": 2, "database_path": str(Path(tracker.db_path).resolve()),
            "human_approval_recorded": True, "phase": "pilot",
            "approved_jobs": [row["id"] for row in records],
            "expires_at_utc": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "integrity_checks": get_integrity_hashes(app_config, records),
        }
        payload.update(updates)
        path = tmp_path / f"approval-{len(list(tmp_path.glob('approval-*.json')))}.json"
        path.write_text(json.dumps(payload))
        return path
    return create

@pytest.fixture
def fixture_browser(monkeypatch, tmp_path):
    """Use real Chromium/dispatcher/adapter; intercept only HTTP fixture traffic."""
    import playwright.sync_api
    original = playwright.sync_api.sync_playwright
    requests = []
    scenario = {"extra": "", "reject": False, "no_post": False, "wrong_job": False, "title": "Python Developer", "description": "Python and FastAPI backend development."}

    @contextmanager
    def controlled_playwright():
        with original() as runtime:
            launch = runtime.chromium.launch_persistent_context
            def controlled_launch(*args, **kwargs):
                selected = Path(kwargs["user_data_dir"]).resolve()
                assert selected.is_relative_to(tmp_path.resolve())
                if os.environ.get("AUTO_APPLY_SHOW_LOCAL_FIXTURE") == "1":
                    kwargs["slow_mo"] = 50
                try:
                    context = launch(*args, **kwargs)
                except Exception as exc:
                    pytest.fail(f"Isolated Chromium could not launch: {exc}", pytrace=False)
                def route_fixture(route):
                    request = route.request
                    requests.append((request.method, request.url, request.post_data or ""))
                    handler = scenario.get("request_handler")
                    if handler and handler(route):
                        return
                    if request.method == "POST":
                        if scenario["reject"]:
                            route.fulfill(status=422, content_type="application/json", body='{"errors":["resume rejected"]}')
                        else:
                            number = "9999" if scenario["wrong_job"] else urlparse(request.url).path.rstrip("/").split("/")[-1]
                            route.fulfill(
                                status=200, content_type="text/html",
                                body=f'<div id="application_confirmation" data-job-id="{number}">Application submitted</div>',
                            )
                        return
                    click = "onclick=\"event.preventDefault();document.body.innerHTML='<div id=application_confirmation>Application submitted</div>';\"" if scenario["no_post"] else ""
                    number = urlparse(request.url).path.rstrip("/").split("/")[-1]
                    html = f"""<html><body><h1>{scenario['title']}</h1><section id="content">{scenario['description']}</section>
                    <form id="application_form" action="/submit/{number}" method="POST" enctype="multipart/form-data">
                    <label for="first_name">First name</label><input id="first_name" name="first_name" required>
                    <label for="last_name">Last name</label><input id="last_name" name="last_name" required>
                    <label for="email">Email</label><input id="email" name="email" type="email" required>
                    <label for="phone">Phone</label><input id="phone" name="phone">
                    <label for="resume">Resume</label><input id="resume" name="resume" type="file" required>
                    {scenario['extra']}
                    <button id="submit_app" type="submit" {click}>Submit Application</button></form></body></html>"""
                    route.fulfill(status=200, content_type="text/html", body=html)
                context.route("http://127.0.0.1:9876/**", route_fixture)
                if scenario.get("intercept_greenhouse"):
                    context.on("page", lambda page: page.route("https://*.greenhouse.io/**", route_fixture))
                return context
            monkeypatch.setattr(runtime.chromium, "launch_persistent_context", controlled_launch)
            yield runtime

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", controlled_playwright)
    return scenario, requests
