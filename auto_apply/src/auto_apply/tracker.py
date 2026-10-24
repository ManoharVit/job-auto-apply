import sqlite3
import datetime
from pathlib import Path
import sys
from urllib.parse import quote

class TrackerDB:
    def __init__(self, db_path: Path, dry_run: bool = False):
        self.db_path = db_path
        self.dry_run = dry_run
        mode = "ro" if dry_run else "rwc"
        try:
            self._con = sqlite3.connect(f"file:{quote(str(self.db_path))}?mode={mode}", uri=True)
        except sqlite3.OperationalError as e:
            if dry_run and "unable to open database file" in str(e):
                print(f"Error: Database {db_path} does not exist. Cannot run dry-run without an existing database.")
                sys.exit(1)
            raise
        self._con.row_factory = sqlite3.Row

        if not dry_run:
            self._init_applications_table()
            self._init_audit_table()
            self._add_missing_columns()
        else:
            # Check if columns exist to warn about migration
            cursor = self._con.execute("PRAGMA table_info(applications)")
            columns = [row["name"] for row in cursor.fetchall()]
            if "description" not in columns or "experience" not in columns:
                print("Notice: Database schema is older and lacks 'description' or 'experience' columns.")
                print("        Dry-run will run in read-only mode with missing data handling.")
                print("        An explicit migration (running without --dry-run) is required to permanently add them.")

    def _add_missing_columns(self):
        try:
            self._con.execute("ALTER TABLE applications ADD COLUMN apply_url TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            self._con.execute("ALTER TABLE applications ADD COLUMN country TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            self._con.execute("ALTER TABLE applications ADD COLUMN description TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            self._con.execute("ALTER TABLE applications ADD COLUMN experience TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            self._con.execute("ALTER TABLE applications ADD COLUMN application_open TEXT")
        except sqlite3.OperationalError:
            pass
        self._con.commit()

    def _init_applications_table(self):
        self._con.execute("""
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                country TEXT,
                description TEXT, apply_url TEXT,
                experience TEXT, application_open TEXT
            )
        """)
        self._con.execute("CREATE INDEX IF NOT EXISTS idx_job_url ON applications(job_url)")
        self._con.execute("CREATE INDEX IF NOT EXISTS idx_status ON applications(status)")
        self._con.execute("CREATE INDEX IF NOT EXISTS idx_applied_at ON applications(applied_at)")
        self._con.commit()

    def _init_audit_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            previous_status TEXT,
            new_status TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            action TEXT,
            reason TEXT
        );
        """
        self._con.execute(query)
        self._con.commit()

    def get_pending_jobs(self, platform=None, include_failed=False, job_ids=None):
        statuses = ['pending']
        if include_failed:
            statuses.append('failed')
        status_placeholders = ','.join(['?']*len(statuses))
        query = f"SELECT * FROM applications WHERE status IN ({status_placeholders})"
        params = list(statuses)
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        if job_ids is not None:
            if not job_ids:
                return []
            id_placeholders = ','.join(['?']*len(job_ids))
            query += f" AND id IN ({id_placeholders})"
            params.extend(job_ids)
        query += " ORDER BY id"
        cursor = self._con.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_status_counts(self):
        query = "SELECT status, COUNT(*) as count FROM applications GROUP BY status"
        cursor = self._con.execute(query)
        return {row["status"]: row["count"] for row in cursor.fetchall()}

    def get_job_by_url(self, job_url: str):
        query = "SELECT * FROM applications WHERE job_url = ?"
        cursor = self._con.execute(query, (job_url,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        from .importer import extract_job_id, infer_platform, normalize_url
        try:
            normalized = normalize_url(job_url)
            platform = infer_platform(normalized)
            identifier = extract_job_id(normalized, platform)
        except ValueError:
            return None
        for candidate in self._con.execute("SELECT * FROM applications"):
            try:
                current = normalize_url(candidate["job_url"])
                if current == normalized or (
                    identifier and infer_platform(current) == platform
                    and extract_job_id(current, platform) == identifier
                ):
                    return dict(candidate)
            except ValueError:
                continue
        return None

    def get_jobs_by_platform(self, platform: str):
        query = "SELECT * FROM applications WHERE platform = ?"
        cursor = self._con.execute(query, (platform,))
        return [dict(row) for row in cursor.fetchall()]

    def add_job(self, job: dict) -> bool:
        """Add a new job if it doesn't exist. Returns True if added."""
        try:
            query = """
                INSERT INTO applications (platform, job_url, title, company, location, description, experience, application_open, country, apply_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                job.get("platform", "unknown"),
                job.get("job_url"),
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("description", ""),
                job.get("experience", ""),
                job.get("application_open", ""),
                job.get("country", ""), job.get("apply_url"),
            )
            self._con.execute(query, params)
            self._con.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def update_job(self, job_id: int, status: str, error_message: str = None, match_score: float = None, action: str = None, reason: str = None, commit: bool = True):
        old_status_row = self._con.execute("SELECT status FROM applications WHERE id = ?", (job_id,)).fetchone()
        old_status = old_status_row["status"] if old_status_row else None

        now = datetime.datetime.now(datetime.UTC).isoformat()
        query = "UPDATE applications SET status = ?"
        params = [status]

        if status == "confirmed_submitted":
            query += ", applied_at = COALESCE(applied_at, ?)"
            params.append(now)

        if error_message is not None:
            query += ", error_message = ?"
            params.append(error_message)
        if match_score is not None:
            query += ", match_score = ?"
            params.append(match_score)

        query += " WHERE id = ?"
        params.append(job_id)
        self._con.execute(query, params)

        if old_status != status or action:
            self._con.execute("""
                INSERT INTO audit_log (job_id, previous_status, new_status, timestamp, action, reason)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (job_id, old_status, status, now, action, reason))

        if commit:
            self._con.commit()

    def check_and_record_attempt(self, job_id: int, max_daily_attempts: int = 20, max_pilot_successes: int = 5, pilot_job_ids: list[int] = None) -> tuple[bool, str]:
        if self.dry_run:
            return True, ""

        import datetime
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Asia/Kolkata")
        except ImportError:
            tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

        now_ist = datetime.datetime.now(tz)
        start_of_day = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_day_utc = start_of_day.astimezone(datetime.timezone.utc).isoformat()

        # We assume auto-commit is off (default in python sqlite3). We do our checks then commit.
        row = self._con.execute("SELECT status FROM applications WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return False, "Job not found"

        if row["status"] in ("confirmed_submitted", "attempting"):
            return False, f"Job already {row['status']}"

        # 2. Daily cap check - using COUNT(id) instead of DISTINCT job_id
        cursor = self._con.execute("SELECT COUNT(id) FROM audit_log WHERE action = 'Attempt' AND timestamp >= ?", (start_of_day_utc,))
        attempts_today = cursor.fetchone()[0]
        if attempts_today >= max_daily_attempts:
            return False, "Daily attempt limit reached"

        # 3. Pilot cap check
        if pilot_job_ids:
            id_placeholders = ','.join(['?']*len(pilot_job_ids))
            cursor = self._con.execute(f"SELECT COUNT(id) FROM applications WHERE status = 'confirmed_submitted' AND id IN ({id_placeholders})", pilot_job_ids)
            total_successful = cursor.fetchone()[0]
            if total_successful >= max_pilot_successes:
                return False, "Pilot cap of 5 successful applications reached"

        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._con.execute("UPDATE applications SET status = 'attempting' WHERE id = ?", (job_id,))
        self._con.execute("INSERT INTO audit_log (job_id, previous_status, new_status, timestamp, action, reason) VALUES (?, ?, ?, ?, ?, ?)",
                          (job_id, row["status"], "attempting", now_utc, "Attempt", "Executing submission action"))
        self._con.commit()
        return True, ""

    def update_job_details(self, job_id: int, title: str, company: str, location: str, platform: str, description: str = "", experience: str = "", application_open: str = "", country: str = "", apply_url: str = None):
        row = self._con.execute("SELECT title, company, location, platform, description, experience, application_open, country, apply_url FROM applications WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return

        new_title = row['title'] if row['title'] else title
        new_company = row['company'] if row['company'] else company
        new_location = row['location'] if row['location'] else location
        new_platform = row['platform'] if (row['platform'] and row['platform'] != 'unknown') else platform
        new_description = row['description'] if row['description'] else description
        new_experience = row['experience'] if row['experience'] else experience

        new_availability = row['application_open'] if row['application_open'] else application_open
        new_country = row['country'] if row['country'] else country
        new_apply_url = row['apply_url'] if row['apply_url'] else apply_url
        query = "UPDATE applications SET title = ?, company = ?, location = ?, platform = ?, description = ?, experience = ?, application_open = ?, country = ?, apply_url = ? WHERE id = ?"
        self._con.execute(query, (new_title, new_company, new_location, new_platform, new_description, new_experience, new_availability, new_country, new_apply_url, job_id))
        self._con.commit()

    def close(self):
        self._con.close()
