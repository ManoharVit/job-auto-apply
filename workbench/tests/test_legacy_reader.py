import hashlib
import sqlite3

import pytest

from workbench.legacy_reader import (
    LegacyDatabaseError,
    LegacyTracker,
    filter_jobs,
    find_duplicates,
    summarize,
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── Read-only guarantees ──────────────────────────────────────────────────

def test_connection_is_read_only(legacy_db):
    with LegacyTracker(legacy_db) as tracker:
        with pytest.raises(sqlite3.OperationalError):
            tracker._con.execute("UPDATE applications SET status = 'applied'")
        with pytest.raises(sqlite3.OperationalError):
            tracker._con.execute("CREATE TABLE evil (x)")


def test_reading_does_not_change_file_bytes(legacy_db):
    before = sha256(legacy_db)
    with LegacyTracker(legacy_db) as tracker:
        tracker.jobs()
    assert sha256(legacy_db) == before


def test_missing_file_raises_clear_error_and_creates_nothing(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(LegacyDatabaseError, match="not found"):
        LegacyTracker(missing)
    assert not missing.exists()


def test_missing_table_raises(tmp_path):
    path = tmp_path / "other.db"
    sqlite3.connect(path).execute("CREATE TABLE something (x)").connection.commit()
    with pytest.raises(LegacyDatabaseError, match="applications"):
        LegacyTracker(path)


def test_missing_column_raises(tmp_path):
    path = tmp_path / "partial.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE applications (id INTEGER, platform TEXT)")
    con.commit()
    con.close()
    with pytest.raises(LegacyDatabaseError, match="missing columns"):
        LegacyTracker(path)


# ── Honest status mapping ─────────────────────────────────────────────────

def test_no_row_is_ever_labelled_applied(legacy_db):
    with LegacyTracker(legacy_db) as tracker:
        jobs = tracker.jobs()
    for job in jobs:
        assert job.category != "applied"
        assert not job.status_label.lower().startswith("applied")


def test_unconfirmed_and_legacy_applied_both_map_to_unconfirmed(legacy_db):
    with LegacyTracker(legacy_db) as tracker:
        by_id = {j.id: j for j in tracker.jobs()}
    assert by_id[1].category == "unconfirmed"  # SUBMISSION_UNCONFIRMED
    assert by_id[7].category == "unconfirmed"  # raw legacy 'applied'
    assert "never verified" in by_id[1].status_label
    assert "never verified" in by_id[7].status_label


def test_pending_skipped_and_unknown(legacy_db):
    with LegacyTracker(legacy_db) as tracker:
        by_id = {j.id: j for j in tracker.jobs()}
    assert by_id[2].category == "not_applied"
    assert by_id[4].category == "skipped"
    assert by_id[4].reason_label == "Easy Apply failed or external site"
    assert by_id[6].reason_label == "Tech-stack mismatch"
    assert by_id[8].category == "unknown"
    assert "some_new_status" in by_id[8].status_label


def test_null_fields_are_handled(legacy_db):
    with LegacyTracker(legacy_db) as tracker:
        job = {j.id: j for j in tracker.jobs()}[7]
    assert job.title == "(untitled)"
    assert job.company == "(unknown company)"
    assert job.location == ""
    assert job.match_score is None


def test_jobs_are_sorted_by_id(legacy_db):
    with LegacyTracker(legacy_db) as tracker:
        ids = [j.id for j in tracker.jobs()]
    assert ids == sorted(ids)


def test_empty_database(empty_legacy_db):
    with LegacyTracker(empty_legacy_db) as tracker:
        jobs = tracker.jobs()
    assert jobs == []
    assert summarize(jobs)["total"] == 0
    assert find_duplicates(jobs) == []


# ── Summary, filters, duplicates ──────────────────────────────────────────

def test_summarize_counts(legacy_db):
    with LegacyTracker(legacy_db) as tracker:
        s = summarize(tracker.jobs())
    assert s["total"] == 9
    assert s["by_category"] == {
        "not_applied": 2, "skipped": 3, "unconfirmed": 3, "unknown": 1,
    }
    assert s["by_platform"] == {"linkedin": 5, "naukri": 4}


def test_filter_by_platform_category_and_search(legacy_db):
    with LegacyTracker(legacy_db) as tracker:
        jobs = tracker.jobs()
    assert [j.id for j in filter_jobs(jobs, platform="naukri", category="skipped")] == [5]
    assert [j.id for j in filter_jobs(jobs, search="EXAMPLE labs")] == [4, 5, 9]
    assert [j.id for j in filter_jobs(jobs, search="databricks")] == [3]
    assert filter_jobs(jobs, platform="indeed") == []


def test_duplicates_same_link_after_canonicalisation(legacy_db):
    with LegacyTracker(legacy_db) as tracker:
        groups = find_duplicates(tracker.jobs())
    link_groups = [g for g in groups if g.kind == "same_link"]
    assert [[j.id for j in g.jobs] for g in link_groups] == [[1, 2]]


def test_duplicates_same_title_and_company_normalised(legacy_db):
    with LegacyTracker(legacy_db) as tracker:
        groups = find_duplicates(tracker.jobs())
    tc = [[j.id for j in g.jobs] for g in groups if g.kind == "same_title_company"]
    # 1+2: identical; 5+9: case/whitespace differences only.
    assert tc == [[1, 2], [5, 9]]


def test_rows_without_title_or_company_never_grouped(legacy_db):
    with LegacyTracker(legacy_db) as tracker:
        groups = find_duplicates(tracker.jobs())
    assert all(7 not in [j.id for j in g.jobs] for g in groups)
