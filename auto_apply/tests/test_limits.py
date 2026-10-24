"""Attempt accounting, pilot boundaries, concurrency, and resume limits."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from auto_apply.submission_guard import SubmissionBlocked, SubmissionGuard, _day_window, _timestamp
from auto_apply.tracker import TrackerDB

@pytest.fixture
def fixed_clock(monkeypatch):
    import auto_apply.submission_guard as module
    clock = {"now": datetime(2026, 10, 8, 12, tzinfo=timezone.utc)}
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"].astimezone(tz) if tz else clock["now"].replace(tzinfo=None)
    monkeypatch.setattr(module, "datetime", Frozen)
    return clock

def _manifest(path):
    return json.loads(path.read_text())

def _legacy(tracker, count, timestamp):
    tracker._con.executemany(
        "INSERT INTO audit_log (job_id, action, timestamp) VALUES (900, 'Attempt', ?)",
        [(timestamp,)] * count,
    )
    tracker._con.commit()

def _reject(guard, job, attempt):
    return guard.complete(job["id"], "failed", json.dumps({
        "event": "submission_rejected", "attempt_id": attempt, "job_url": job["job_url"],
    }))

def test_twentieth_allowed_twenty_first_blocked(tracker, make_job, manifest_factory, fixed_clock):
    job = make_job()
    guard = SubmissionGuard(tracker, _manifest(manifest_factory(tracker, [job])), lambda con: None)
    _legacy(tracker, 19, "2026-10-08T12:00:00+05:30")
    attempt = guard.reserve(job["id"])
    assert tracker._con.execute("SELECT COUNT(*) FROM auto_apply_attempts").fetchone()[0] == 1
    _reject(guard, job, attempt)
    with pytest.raises(SubmissionBlocked, match="limit of 20"):
        guard.reserve(job["id"])
    assert tracker._con.execute("SELECT COUNT(*) FROM auto_apply_attempts").fetchone()[0] == 1

def test_repeated_attempts_for_one_job_count_separately(tracker, make_job, manifest_factory, fixed_clock):
    job = make_job()
    guard = SubmissionGuard(tracker, _manifest(manifest_factory(tracker, [job])), lambda con: None)
    for _ in range(20):
        attempt = guard.reserve(job["id"])
        _reject(guard, job, attempt)
    assert tracker._con.execute("SELECT COUNT(*) FROM auto_apply_attempts").fetchone()[0] == 20
    with pytest.raises(SubmissionBlocked):
        guard.reserve(job["id"])

def test_exact_kolkata_midnight_boundaries():
    start, end = _day_window(datetime(2026, 10, 8, 20, tzinfo=timezone.utc))
    assert datetime.fromtimestamp(start, timezone.utc).isoformat() == "2026-10-08T18:30:00+00:00"
    assert datetime.fromtimestamp(end, timezone.utc).isoformat() == "2026-10-09T18:30:00+00:00"

@pytest.mark.parametrize("value", [
    "2026-10-08 18:30:00", "2026-10-08T18:30:00Z", "2026-10-09T00:00:00+05:30",
])
def test_mixed_timestamp_formats(value):
    assert _timestamp(value) == datetime(2026, 10, 8, 18, 30, tzinfo=timezone.utc).timestamp()

def test_day_rollover_restores_slots(tracker, make_job, manifest_factory, fixed_clock):
    job = make_job()
    guard = SubmissionGuard(tracker, _manifest(manifest_factory(tracker, [job])), lambda con: None)
    _legacy(tracker, 20, "2026-10-08T12:00:00+05:30")
    with pytest.raises(SubmissionBlocked):
        guard.reserve(job["id"])
    fixed_clock["now"] += timedelta(days=1)
    assert guard.reserve(job["id"])

def test_crash_reservation_blocks_retry_after_restart(tracker, make_job, manifest_factory, fixed_clock):
    job = make_job()
    manifest = _manifest(manifest_factory(tracker, [job]))
    first = SubmissionGuard(tracker, manifest, lambda con: None)
    first.reserve(job["id"])
    connection = TrackerDB(tracker.db_path)
    try:
        restarted = SubmissionGuard(connection, manifest, lambda con: None)
        with pytest.raises(SubmissionBlocked):
            restarted.reserve(job["id"])
        assert connection._con.execute("SELECT COUNT(*) FROM auto_apply_attempts").fetchone()[0] == 1
    finally:
        connection.close()

def test_ambiguous_result_blocks_retry(tracker, make_job, manifest_factory, fixed_clock):
    job = make_job()
    guard = SubmissionGuard(tracker, _manifest(manifest_factory(tracker, [job])), lambda con: None)
    guard.reserve(job["id"])
    guard.complete(job["id"], "failed", "Browser disconnected after the click")
    assert tracker.get_job_by_url(job["job_url"])["status"] == "unconfirmed"
    tracker.update_job(job["id"], "pending", action="TEST_ONLY_RESET")
    with pytest.raises(SubmissionBlocked):
        guard.reserve(job["id"])

def test_false_confirmation_without_attempt_is_rejected(tracker, make_job, manifest_factory):
    job = make_job()
    guard = SubmissionGuard(tracker, _manifest(manifest_factory(tracker, [job])), lambda con: None)
    status, _ = guard.complete(job["id"], "confirmed_submitted", "generic applied text")
    assert status == "unconfirmed"
    assert tracker.get_job_by_url(job["job_url"])["applied_at"] is None

def test_pilot_cannot_silently_change_members(tracker, make_job, manifest_factory):
    first, second = make_job(), make_job()
    SubmissionGuard(tracker, _manifest(manifest_factory(tracker, [first])), lambda con: None)
    with pytest.raises(SubmissionBlocked, match="different jobs"):
        SubmissionGuard(tracker, _manifest(manifest_factory(tracker, [second])), lambda con: None)

def test_scope_blocks_unapproved_job(tracker, make_job, manifest_factory):
    first, second = make_job(), make_job()
    guard = SubmissionGuard(tracker, _manifest(manifest_factory(tracker, [first])), lambda con: None)
    with pytest.raises(SubmissionBlocked, match="outside"):
        guard.reserve(second["id"])

def test_daily_requires_review_of_recorded_pilot(tracker, make_job, manifest_factory):
    first, second = make_job(), make_job()
    pilot = SubmissionGuard(tracker, _manifest(manifest_factory(tracker, [first])), lambda con: None)
    daily = _manifest(manifest_factory(tracker, [second], phase="daily", reviewed_pilot=pilot.pilot_id, pilot_review_recorded=False))
    with pytest.raises(SubmissionBlocked, match="explicitly identify"):
        SubmissionGuard(tracker, daily, lambda con: None)
    daily["pilot_review_recorded"] = True
    SubmissionGuard(tracker, daily, lambda con: None)
    assert tracker._con.execute("SELECT reviewed_at FROM auto_apply_pilot").fetchone()[0] is not None

def test_concurrent_runs_cannot_exceed_cap(tracker, make_job, manifest_factory, fixed_clock):
    jobs = [make_job(), make_job()]
    manifest = _manifest(manifest_factory(tracker, jobs))
    SubmissionGuard(tracker, manifest, lambda con: None)
    _legacy(tracker, 19, "2026-10-08T12:00:00+05:30")
    def reserve(job):
        connection = TrackerDB(tracker.db_path)
        try:
            guard = SubmissionGuard(connection, manifest, lambda con: None)
            try:
                guard.reserve(job["id"])
                return True
            except SubmissionBlocked:
                return False
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, jobs))
    assert sum(results) == 1
    assert tracker._con.execute("SELECT COUNT(*) FROM auto_apply_attempts").fetchone()[0] == 1

def test_resume_obeys_exhausted_cap(tracker, make_job, manifest_factory, fixture_browser, monkeypatch, fixed_clock):
    from auto_apply.orchestrator import run_resume_job
    job = make_job()
    tracker.update_job(job["id"], "paused", action="PREPARATION", reason="challenge")
    path = manifest_factory(tracker, [job])
    _legacy(tracker, 20, "2026-10-08T12:00:00+05:30")
    monkeypatch.setattr("builtins.input", lambda prompt: "submit")
    run_resume_job(job["id"], str(path), db_path=tracker.db_path)
    assert not [request for request in fixture_browser[1] if request[0] == "POST"]
    assert tracker.get_job_by_url(job["job_url"])["status"] == "paused"
