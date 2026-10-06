import pytest
from pathlib import Path
import sqlite3
import subprocess
import sys

def test_dry_run_nonexistent_db(tmp_path):
    db_path = tmp_path / "nonexistent.db"
    cmd = [sys.executable, "-m", "auto_apply", "--dry-run", "--db-path", str(db_path)]
    cwd_path = str(Path(__file__).parents[1] / "src")
    result = subprocess.run(cmd, cwd=cwd_path, capture_output=True, text=True)
    assert result.returncode == 1
    assert "does not exist" in result.stdout
    assert "Cannot run dry-run without an existing database" in result.stdout
    assert not db_path.exists()

def test_dry_run_old_schema(tmp_path):
    db_path = tmp_path / "old_schema.db"
    con = sqlite3.connect(db_path)
    con.execute("""
    CREATE TABLE applications (
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
    );
    """)
    con.execute("INSERT INTO applications (platform, job_url, title, status) VALUES ('linkedin', 'http://old.com/1', 'Python Developer', 'pending')")
    con.commit()
    con.close()

    cmd = [sys.executable, "-m", "auto_apply", "--dry-run", "--db-path", str(db_path)]
    cwd_path = str(Path(__file__).parents[1] / "src")
    result = subprocess.run(cmd, cwd=cwd_path, capture_output=True, text=True)
    assert result.returncode == 0
    assert "Notice: Database schema is older" in result.stdout
    assert "Python Developer" in result.stdout
    
    # Verify no columns added
    con = sqlite3.connect(db_path)
    cursor = con.execute("PRAGMA table_info(applications)")
    cols = [row[1] for row in cursor.fetchall()]
    con.close()
    assert "description" not in cols

def test_dry_run_new_schema(tmp_path):
    db_path = tmp_path / "new_schema.db"
    con = sqlite3.connect(db_path)
    con.execute("""
    CREATE TABLE applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        job_url TEXT UNIQUE NOT NULL,
        title TEXT,
        company TEXT,
        location TEXT,
        description TEXT,
        experience TEXT,
        match_score REAL,
        status TEXT DEFAULT 'pending',
        error_message TEXT,
        applied_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    con.execute("INSERT INTO applications (platform, job_url, title, description, experience, status) VALUES ('linkedin', 'http://new.com/1', 'Python Developer', 'Good job', '2 years', 'pending')")
    con.commit()
    con.close()

    cmd = [sys.executable, "-m", "auto_apply", "--dry-run", "--db-path", str(db_path)]
    cwd_path = str(Path(__file__).parents[1] / "src")
    result = subprocess.run(cmd, cwd=cwd_path, capture_output=True, text=True)
    assert result.returncode == 0
    assert "Notice: Database schema is older" not in result.stdout
    assert "Python Developer" in result.stdout
    
    # Verify no records modified
    con = sqlite3.connect(db_path)
    row = con.execute("SELECT * FROM applications").fetchone()
    con.close()
    assert row[9] == 'pending' # status column
