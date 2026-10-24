"""Transactional attempt limits shared by batch and resume submissions.

Existing audit and attempt tables are preserved. New records use a separate
ledger so old, ambiguous history is never silently rewritten.
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .authorization import AuthorizationError
from .settings import DAILY_ATTEMPT_CAP

class SubmissionBlocked(RuntimeError):
    pass

def _day_window(now=None):
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Asia/Kolkata"))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp()

def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc).timestamp() if parsed.tzinfo is None else parsed.timestamp()
    except (TypeError, ValueError):
        raise SubmissionBlocked("An existing attempt has an invalid timestamp; review it before submitting.")

class SubmissionGuard:
    def __init__(self, tracker, manifest, preflight):
        self.tracker = tracker
        self.con = tracker._con
        self.manifest = manifest
        self.preflight = preflight
        self.attempt_id = None
        self.job_id = None
        self.pilot_id = None
        self._initialize()

    def _initialize(self):
        # These are additive schemas. Never DROP or replace historical tables.
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS auto_apply_pilot (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                pilot_id TEXT NOT NULL,
                job_ids TEXT NOT NULL,
                created_at REAL NOT NULL,
                reviewed_at REAL
            );
            CREATE TABLE IF NOT EXISTS auto_apply_attempts (
                attempt_id TEXT PRIMARY KEY,
                job_id INTEGER NOT NULL,
                pilot_id TEXT,
                phase TEXT NOT NULL,
                reserved_at REAL NOT NULL,
                completed_at REAL,
                outcome TEXT NOT NULL,
                evidence TEXT
            );
            CREATE INDEX IF NOT EXISTS auto_apply_attempt_time
                ON auto_apply_attempts(reserved_at);
            CREATE UNIQUE INDEX IF NOT EXISTS auto_apply_unresolved_job
                ON auto_apply_attempts(job_id)
                WHERE outcome IN ('reserved', 'ambiguous');
        """)
        self.con.execute("BEGIN IMMEDIATE")
        try:
            row = self.con.execute("SELECT * FROM auto_apply_pilot WHERE singleton = 1").fetchone()
            ids = sorted(self.manifest["approved_jobs"])
            phase = self.manifest["phase"]
            if phase == "pilot":
                pilot_id = hashlib.sha256(json.dumps({
                    "database": self.manifest["database_path"], "jobs": ids
                }, sort_keys=True).encode()).hexdigest()[:20]
                if row is None:
                    self.con.execute(
                        "INSERT INTO auto_apply_pilot VALUES (1, ?, ?, ?, NULL)",
                        (pilot_id, json.dumps(ids), datetime.now(timezone.utc).timestamp()),
                    )
                elif row["pilot_id"] != pilot_id:
                    raise SubmissionBlocked(
                        "The first pilot is already bound to different jobs. Review it before a daily batch."
                    )
                elif row["reviewed_at"] is not None:
                    raise SubmissionBlocked("The pilot has been reviewed; use an approved daily manifest.")
                self.pilot_id = pilot_id
            else:
                if (
                    row is None
                    or self.manifest.get("pilot_review_recorded") is not True
                    or self.manifest.get("reviewed_pilot") != row["pilot_id"]
                ):
                    raise SubmissionBlocked("Daily approval must explicitly identify and review the recorded pilot.")
                self.pilot_id = row["pilot_id"]
                self.con.execute(
                    "UPDATE auto_apply_pilot SET reviewed_at = COALESCE(reviewed_at, ?) WHERE singleton = 1",
                    (datetime.now(timezone.utc).timestamp(),),
                )
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise

    def _attempt_count(self, start, end):
        count = self.con.execute(
            "SELECT COUNT(*) FROM auto_apply_attempts WHERE reserved_at >= ? AND reserved_at < ?",
            (start, end),
        ).fetchone()[0]
        # Preserve accounting for known attempts written by the earlier runner.
        # New reservations use a different audit action and are not counted twice.
        legacy = self.con.execute("SELECT timestamp FROM audit_log WHERE action = 'Attempt'").fetchall()
        return count + sum(start <= _timestamp(row["timestamp"]) < end for row in legacy)

    def reserve(self, job_id):
        if job_id not in self.manifest["approved_jobs"]:
            raise SubmissionBlocked("This job is outside the approved submission scope.")
        if self.attempt_id is not None:
            raise SubmissionBlocked("This execution has already reserved a submission attempt.")
        self.con.execute("BEGIN IMMEDIATE")
        try:
            # Re-read the approval, configuration, and all approved job metadata
            # while the write lock prevents a second process reserving a slot.
            self.preflight(self.con)
            row = self.con.execute(
                "SELECT status FROM applications WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None or row["status"] not in ("pending", "failed", "paused"):
                raise SubmissionBlocked("This job is not in a resumable, unsubmitted state.")
            existing = self.con.execute(
                "SELECT outcome FROM auto_apply_attempts WHERE job_id = ? "
                "AND outcome IN ('reserved', 'ambiguous', 'confirmed') LIMIT 1",
                (job_id,),
            ).fetchone()
            if existing:
                raise SubmissionBlocked(
                    "This job already has a confirmed or unresolved attempt; reconcile it before retrying."
                )
            start, end = _day_window()
            if self._attempt_count(start, end) >= DAILY_ATTEMPT_CAP:
                raise SubmissionBlocked("Daily submission-attempt limit of 20 reached.")
            attempt_id = str(uuid.uuid4())
            self.con.execute(
                "INSERT INTO auto_apply_attempts "
                "(attempt_id, job_id, pilot_id, phase, reserved_at, outcome) "
                "VALUES (?, ?, ?, ?, ?, 'reserved')",
                (attempt_id, job_id, self.pilot_id, self.manifest["phase"],
                 datetime.now(timezone.utc).timestamp()),
            )
            self.tracker.update_job(
                job_id, "attempting", action="SUBMISSION_ATTEMPT_RESERVED",
                reason=f"Attempt {attempt_id}; approved {self.manifest['phase']} scope",
                commit=False,
            )
            self.con.commit()
            self.attempt_id = attempt_id
            self.job_id = job_id
            return attempt_id
        except Exception:
            self.con.rollback()
            raise

    def complete(self, job_id, status, evidence):
        if status == "deferred":
            return status, evidence
        if self.attempt_id is None:
            if status == "confirmed_submitted":
                status = "unconfirmed"
                evidence = "No reserved attempt exists for this claimed confirmation."
            self.tracker.update_job(
                job_id, status, action="APPLICATION_PREPARATION",
                reason=evidence, error_message=evidence,
            )
            return status, evidence
        try:
            receipt = json.loads(evidence)
        except (ValueError, TypeError):
            receipt = {}
        if not isinstance(receipt, dict):
            receipt = {}
        if status == "confirmed_submitted":
            current = self.con.execute("SELECT job_url, apply_url FROM applications WHERE id = ?", (job_id,)).fetchone()
            current_url, application_url = current[0], current[1]
            if (receipt.get("event") != "submission_confirmed"
                or receipt.get("attempt_id") != self.attempt_id
                or receipt.get("job_id") != job_id
                or receipt.get("job_url") != current_url
                or (application_url and receipt.get("application_url") != application_url)):
                status = "unconfirmed"
                evidence = "Submission outcome lacks a receipt bound to the reserved attempt."
                outcome = "ambiguous"
            else:
                outcome = "confirmed"
        elif (status == "failed" and receipt.get("event") == "submission_rejected"
              and receipt.get("attempt_id") == self.attempt_id):
            outcome = "rejected"
        else:
            # A browser exception after the submission boundary may have occurred
            # after the platform received the application. Never automatically retry.
            outcome = "ambiguous"
            status = "unconfirmed"
        self.con.execute("BEGIN IMMEDIATE")
        try:
            self.con.execute(
                "UPDATE auto_apply_attempts SET outcome = ?, completed_at = ?, evidence = ? "
                "WHERE attempt_id = ? AND outcome = 'reserved'",
                (outcome, datetime.now(timezone.utc).timestamp(), evidence, self.attempt_id),
            )
            self.tracker.update_job(
                job_id, status, action="SUBMISSION_ATTEMPT_COMPLETED",
                reason=evidence, error_message=evidence, commit=False,
            )
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise
        finally:
            self.attempt_id = None
            self.job_id = None
        return status, evidence
