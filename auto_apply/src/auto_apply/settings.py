"""Shared paths and fixed limits for the supported submission workflow."""
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import os

ROOT = Path(__file__).resolve().parents[3]
DAILY_ATTEMPT_CAP = 20
PILOT_JOB_CAP = 5
GREENHOUSE_HOSTS = frozenset({
    "boards.greenhouse.io", "job-boards.greenhouse.io",
    "boards-api.greenhouse.io",
})

def resume_file(config):
    value = config.get("profile", {}).get("resume_path")
    if not value:
        return None
    path = Path(str(value)).expanduser()
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()

def fixture_mode(config):
    return (
        config.get("browser", {}).get("allow_local_fixtures") is True
        or os.environ.get("AUTO_APPLY_TEST_MODE") == "1"
    )

def browser_profile(config):
    override = os.environ.get("AUTO_APPLY_PROFILE_DIR") or config.get("browser", {}).get("user_data_dir")
    production = (ROOT / "sessions" / "chromium_profile").resolve()
    selected = Path(override).expanduser().resolve() if override else production
    if (fixture_mode(config) or os.environ.get("PYTEST_CURRENT_TEST")) and (
        selected == production or production in selected.parents or selected in production.parents
    ):
        raise ValueError("Fixture tests require a separate temporary Chromium profile.")
    return selected

def greenhouse_identity(url):
    """Return (board, job_id) for an exact, supported Greenhouse origin."""
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or parsed.hostname not in GREENHOUSE_HOSTS:
        return None
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if "jobs" in parts:
        index = parts.index("jobs")
        if index and len(parts) > index + 1 and parts[index + 1].isdigit():
            return parts[index - 1], parts[index + 1]
    query = parse_qs(parsed.query)
    board = query.get("for", [None])[0]
    job_id = query.get("token", query.get("gh_jid", [None]))[0]
    if board and job_id and str(job_id).isdigit():
        return board, str(job_id)
    return None

def approved_fixture_url(url, config):
    if not fixture_mode(config):
        return False
    parsed = urlparse(str(url))
    return parsed.scheme == "file" or (
        parsed.scheme in ("http", "https")
        and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    )


def job_application_url(job):
    listing = job.get("job_url") or ""
    selected = job.get("apply_url") or listing
    if job.get("apply_url"):
        identity = greenhouse_identity(listing)
        if identity is None or greenhouse_identity(selected) != identity:
            raise ValueError("The application URL must identify the same approved Greenhouse board and job.")
    return selected

def effective_policy(config):
    return {
        "version": 2,
        "allowed_submit_platforms": ["greenhouse"],
        "allowed_job_countries": ["India"],
        "pilot_job_cap": PILOT_JOB_CAP,
        "daily_attempt_cap": DAILY_ATTEMPT_CAP,
        "timezone": "Asia/Kolkata",
        "fixture_mode": fixture_mode(config),
        "settings": {
            key: config.get(key, {})
            for key in ("submission_policy", "browser", "demographics", "eeo", "application_answers")
        },
    }
