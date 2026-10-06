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
                description TEXT,
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

    def get_pending_jobs(self, platform=None):
        query = "SELECT * FROM applications WHERE status = 'pending'"
        params = []
        if platform:
            query += " AND platform = ?"
            params.append(platform)
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
        return dict(row) if row else None

    def get_jobs_by_platform(self, platform: str):
        query = "SELECT * FROM applications WHERE platform = ?"
        cursor = self._con.execute(query, (platform,))
        return [dict(row) for row in cursor.fetchall()]

    def add_job(self, job: dict) -> bool:
        """Add a new job if it doesn't exist. Returns True if added."""
        try:
            query = """
                INSERT INTO applications (platform, job_url, title, company, location, description, experience, application_open)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                job.get("platform", "unknown"),
                job.get("job_url"),
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("description", ""),
                job.get("experience", ""),
                job.get("application_open", "")
            )
            self._con.execute(query, params)
            self._con.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def update_job(self, job_id: int, status: str, error_message: str = None, match_score: float = None, action: str = None, reason: str = None):
        old_status_row = self._con.execute("SELECT status FROM applications WHERE id = ?", (job_id,)).fetchone()
        old_status = old_status_row["status"] if old_status_row else None

        now = datetime.datetime.now(datetime.UTC).isoformat()
        query = "UPDATE applications SET status = ?"
        params = [status]
        
        if status == "confirmed_submitted":
            query += ", applied_at = ?"
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

        if old_status != status:
            self._con.execute("""
                INSERT INTO audit_log (job_id, previous_status, new_status, timestamp, action, reason)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (job_id, old_status, status, now, action, reason))

        self._con.commit()

    def update_job_details(self, job_id: int, title: str, company: str, location: str, platform: str, description: str = "", experience: str = ""):
        row = self._con.execute("SELECT title, company, location, platform, description, experience, application_open FROM applications WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return
            
        new_title = row['title'] if row['title'] else title
        new_company = row['company'] if row['company'] else company
        new_location = row['location'] if row['location'] else location
        new_platform = row['platform'] if (row['platform'] and row['platform'] != 'unknown') else platform
        new_description = row['description'] if row['description'] else description
        new_experience = row['experience'] if row['experience'] else experience
        
        query = "UPDATE applications SET title = ?, company = ?, location = ?, platform = ?, description = ?, experience = ? WHERE id = ?"
        self._con.execute(query, (new_title, new_company, new_location, new_platform, new_description, new_experience, job_id))
        self._con.commit()

    def close(self):
        self._con.close()

