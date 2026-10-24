"""Import and backfill job metadata without resetting application history."""
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .orchestrator import format_job_preview, is_eligible, score_job
from .settings import greenhouse_identity, job_application_url

def infer_platform(url):
    host = (urlparse(str(url)).hostname or "").lower()
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin"
    if host == "naukri.com" or host.endswith(".naukri.com"):
        return "naukri"
    if greenhouse_identity(url):
        return "greenhouse"
    return "unknown"

def extract_job_id(url, platform=None):
    parsed = urlparse(str(url) if "://" in str(url) else "https://" + str(url))
    inferred = infer_platform(parsed.geturl())
    if inferred == "linkedin":
        match = re.search(r"/jobs/view/(?:[^/?]*-)?(\d+)/?$", parsed.path)
        return match.group(1) if match else None
    if inferred == "naukri":
        match = re.search(r"-(\d+)(?:\.html)?/?$", parsed.path)
        return match.group(1) if match else None
    if inferred == "greenhouse":
        board, job_id = greenhouse_identity(parsed.geturl())
        return f"{board}/{job_id}"
    return None

def normalize_url(url):
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Empty or non-text URL.")
    value = url.strip()
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL port.") from exc
    if (
        parsed.scheme not in ("http", "https") or not parsed.hostname
        or "." not in parsed.hostname or parsed.username or parsed.password
        or any(character.isspace() for character in value)
    ):
        raise ValueError("URL must be a valid HTTP(S) job link without embedded credentials.")
    platform = infer_platform(value)
    job_id = extract_job_id(value, platform)
    if platform == "linkedin" and job_id:
        return f"https://www.linkedin.com/jobs/view/{job_id}"
    if platform == "greenhouse" and job_id:
        board, number = job_id.rsplit("/", 1)
        return f"https://job-boards.greenhouse.io/{board}/jobs/{number}"
    host = parsed.hostname.lower()
    if port and port not in (80 if parsed.scheme == "http" else 443,):
        host += f":{port}"
    tracking = {"trk", "trkinfo", "trackingid", "refid", "ref", "campaign", "src"}
    query = [] if platform == "naukri" and job_id else [
        (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in tracking and not key.lower().startswith("utm_")
    ]
    return urlunparse((parsed.scheme, host, parsed.path.rstrip("/") or "/", "", urlencode(query), ""))

def _identity(job):
    url = normalize_url(job["job_url"])
    platform = infer_platform(url)
    job_id = extract_job_id(url, platform)
    return (platform, job_id) if job_id else ("url", url)

def import_jobs(jobs, tracker, config, dry_run=False):
    stats = dict.fromkeys(("newly_imported", "duplicate", "eligible", "review_needed", "excluded", "errors"), 0)
    existing = {}
    for row in tracker._con.execute("SELECT * FROM applications").fetchall():
        stored = dict(row)
        try:
            existing[_identity(stored)] = stored
        except (ValueError, KeyError):
            # Invalid legacy links are preserved, not rewritten or discarded.
            continue
    for index, source in enumerate(jobs, start=1):
        job = dict(source)
        try:
            url = next((job.get(key) for key in ("job_url", "url", "apply_url") if job.get(key)), "")
            job["job_url"] = normalize_url(url)
            detected = infer_platform(job["job_url"])
            declared = str(job.get("platform") or "unknown").strip().lower()
            if detected != "unknown" and declared not in ("", "unknown", detected):
                raise ValueError("Declared platform conflicts with the URL host.")
            job["platform"] = detected if detected != "unknown" else declared
            if detected == "greenhouse":
                chosen = str(job.get("apply_url") or url).strip()
                if "://" not in chosen:
                    chosen = "https://" + chosen
                job["apply_url"] = chosen
                job_application_url(job)
            identity = _identity(job)
        except (TypeError, ValueError, KeyError) as exc:
            print(f"Import row {index}: {exc}; skipped.")
            stats["errors"] += 1
            continue
        previous = existing.get(identity)
        if previous is not None:
            stats["duplicate"] += 1
            if not dry_run and "id" in previous:
                tracker.update_job_details(
                    previous["id"], job.get("title", ""), job.get("company", ""),
                    job.get("location", ""), job["platform"],
                    job.get("description", ""), job.get("experience", ""),
                    job.get("application_open", ""),
                    job.get("country", ""),
                    job.get("apply_url"),
                )
            continue
        scored = score_job(job, config)
        eligible, reason = is_eligible(job, config, scored)
        stats["eligible" if eligible is True else "excluded" if eligible is False else "review_needed"] += 1
        print(format_job_preview(job, config, scored, reason, eligible))
        if dry_run:
            stats["newly_imported"] += 1
            existing[identity] = job
        elif tracker.add_job(job):
            stats["newly_imported"] += 1
            existing[identity] = tracker.get_job_by_url(job["job_url"])
        else:
            stats["duplicate"] += 1
    return stats
