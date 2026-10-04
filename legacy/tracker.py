"""
tracker.py — SQLite application tracker.
Prevents duplicate applications and logs daily stats.
"""

import csv
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# Skip reasons that mean "a human should apply manually"
# (as opposed to tech_mismatch / duplicate / already_applied)
MANUAL_APPLY_REASONS = {
    "easy_apply_failed_or_external",
    "no_easy_apply_external_redirect",
    "naukri_apply_failed",
    "no_apply_button",
    "external_redirect",
    "timeout",
}



class ApplicationTracker:
    def __init__(self, db_path: str = "tracker.db"):
        self.db_path = db_path
        self._db_conn = sqlite3.connect(self.db_path)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS applications (
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
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_job_url ON applications(job_url)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON applications(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_applied_at ON applications(applied_at)
            """)

    def _conn(self) -> sqlite3.Connection:
        return self._db_conn

    def is_already_applied(self, job_url: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT status FROM applications WHERE job_url = ?",
                (job_url,),
            ).fetchone()
            return row is not None and row[0] == "applied"

    def add_job(
        self,
        platform: str,
        job_url: str,
        title: str,
        company: str,
        location: str,
        match_score: float,
    ):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO applications 
                (platform, job_url, title, company, location, match_score, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (platform, job_url, title, company, location, match_score),
            )

    def mark_applied(self, job_url: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE applications SET status = 'applied', applied_at = ? WHERE job_url = ?",
                (datetime.now().isoformat(), job_url),
            )

    def mark_skipped(self, job_url: str, reason: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE applications SET status = 'skipped', error_message = ? WHERE job_url = ?",
                (reason, job_url),
            )

    def mark_failed(self, job_url: str, error: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE applications SET status = 'failed', error_message = ? WHERE job_url = ?",
                (error, job_url),
            )

    def get_today_stats(self) -> dict:
        today = date.today().isoformat()
        with self._conn() as conn:
            applied = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status = 'applied' AND DATE(applied_at) = ?",
                (today,),
            ).fetchone()[0]
            skipped = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status = 'skipped' AND DATE(created_at) = ?",
                (today,),
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status = 'failed' AND DATE(created_at) = ?",
                (today,),
            ).fetchone()[0]
        return {"applied": applied, "skipped": skipped, "failed": failed}

    def get_total_stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
            applied = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status = 'applied'"
            ).fetchone()[0]
            skipped = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status = 'skipped'"
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status = 'failed'"
            ).fetchone()[0]
        return {
            "total_tracked": total,
            "applied": applied,
            "skipped": skipped,
            "failed": failed,
        }

    def get_unapplied_jobs(
        self, platform: Optional[str] = None, limit: int = 50
    ) -> list[dict]:
        query = "SELECT job_url, title, company, location, match_score, platform FROM applications WHERE status = 'pending'"
        params: list = []
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        query += " ORDER BY match_score DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "apply_url": r[0],
                "job_url": r[0],
                "title": r[1],
                "company": r[2],
                "location": r[3],
                "match_score": r[4],
                "platform": r[5],
            }
            for r in rows
        ]

    # ── Manual-apply list ────────────────────────────────────────────────────

    _CSV_HEADERS = [
        "platform", "title", "company", "apply_url", "reason", "noted_at"
    ]
    _CSV_PATH = Path("logs/manual_apply.csv")

    def save_manual_candidate(
        self,
        platform: str,
        title: str,
        company: str,
        apply_url: str,
        reason: str,
    ) -> None:
        """Append one job to logs/manual_apply.csv for manual follow-up.

        Called in real time when the bot skips a job that a human could
        apply to (external redirect, no Easy Apply, Naukri form failure, etc.).
        Creates the file and writes a header row on first call.
        """
        self._CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self._CSV_PATH.exists() or self._CSV_PATH.stat().st_size == 0

        # Avoid duplicates: check if this URL is already in the CSV
        if self._CSV_PATH.exists():
            try:
                with open(self._CSV_PATH, newline="", encoding="utf-8") as f:
                    existing = {row["apply_url"] for row in csv.DictReader(f)}
                if apply_url in existing:
                    return
            except Exception:
                pass

        with open(self._CSV_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self._CSV_HEADERS)
            if write_header:
                writer.writeheader()
            writer.writerow({
                "platform": platform,
                "title": title,
                "company": company,
                "apply_url": apply_url,
                "reason": reason,
                "noted_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })

    def export_manual_csv(self, reasons: set | None = None) -> int:
        """Bulk-export historical skipped jobs → logs/manual_apply.csv.

        Pulls every skipped job whose error_message is in `reasons`
        (defaults to MANUAL_APPLY_REASONS) and writes them to the CSV,
        skipping duplicates already present. Returns count of rows added.
        """
        if reasons is None:
            reasons = MANUAL_APPLY_REASONS

        placeholders = ",".join("?" * len(reasons))
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT platform, title, company, job_url, error_message
                FROM applications
                WHERE status = 'skipped'
                  AND error_message IN ({placeholders})
                ORDER BY platform, title
                """,
                list(reasons),
            ).fetchall()

        added = 0
        for platform, title, company, url, reason in rows:
            before = self._CSV_PATH.stat().st_size if self._CSV_PATH.exists() else 0
            self.save_manual_candidate(platform, title or "", company or "", url, reason or "skipped")
            after = self._CSV_PATH.stat().st_size if self._CSV_PATH.exists() else 0
            if after > before:
                added += 1
        return added
