import csv
from pathlib import Path
from urllib.parse import urlparse, urlunparse
import re
from .orchestrator import score_job, is_eligible, format_job_preview

def extract_job_id(url: str, platform: str) -> str | None:
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    parsed = urlparse(url)
    if platform == "linkedin" or "linkedin.com" in parsed.netloc:
        m = re.search(r'/jobs/view/(\d+)', parsed.path)
        if m:
            return m.group(1)
    elif platform == "naukri" or "naukri.com" in parsed.netloc:
        m = re.search(r'-(\d+)(?:\.html)?$', parsed.path.rstrip('/'))
        if m:
            return m.group(1)
    return None

def normalize_url(url: str) -> str:
    """Normalize URLs to prevent duplicates from tracking parameters."""
    url = url.strip()
    if not url:
        raise ValueError("Empty URL")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    parsed = urlparse(url)
    
    if not parsed.netloc or "." not in parsed.netloc:
        raise ValueError(f"Invalid URL format: {url}")
    
    # For LinkedIn jobs, the ID is in the path. Query params are just tracking.
    if "linkedin.com" in parsed.netloc and "/jobs/view/" in parsed.path:
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, "", parsed.fragment))
    
    return url

def import_jobs(jobs: list[dict], tracker, config, dry_run: bool = False):
    """
    Process imports. Returns stats:
    newly_imported, duplicate, eligible, review_needed, excluded
    """
    stats = {
        "newly_imported": 0,
        "duplicate": 0,
        "eligible": 0,
        "review_needed": 0,
        "excluded": 0,
        "errors": 0
    }
    
    # Pre-fetch existing jobs to deduplicate by platform job ID
    existing_by_platform = {}
    
    # For preview logging
    for job in jobs:
        try:
            norm_url = normalize_url(job.get("job_url", job.get("url", job.get("apply_url", ""))))
        except ValueError as e:
            print(f"Error skipping row: {e}")
            stats["errors"] += 1
            continue
            
        if not norm_url:
            continue
            
        job["job_url"] = norm_url
        if not job.get("platform"):
            job["platform"] = "linkedin" if "linkedin.com" in norm_url else ("naukri" if "naukri.com" in norm_url else "unknown")
        
        platform = job["platform"]
        
        # Check duplicate by normalized URL
        existing = tracker.get_job_by_url(norm_url)
        is_duplicate = False
        
        if existing:
            is_duplicate = True
        else:
            # Check duplicate by platform job ID
            new_job_id = extract_job_id(norm_url, platform)
            if new_job_id:
                if platform not in existing_by_platform:
                    existing_by_platform[platform] = tracker.get_jobs_by_platform(platform)
                
                for ext_job in existing_by_platform[platform]:
                    ext_job_id = extract_job_id(ext_job["job_url"], platform)
                    if ext_job_id == new_job_id:
                        existing = ext_job
                        is_duplicate = True
                        break
        
        if is_duplicate:
            stats["duplicate"] += 1
            if not dry_run and existing:
                tracker.update_job_details(existing["id"], job.get("title", ""), job.get("company", ""), job.get("location", ""), platform, job.get("description", ""), job.get("experience", ""))
            continue
            
        # If it's new, we assess it using the existing scoring engine
        score_data = score_job(job, config)
        eligible, reason = is_eligible(job, config, score_data)
        
        if eligible is True:
            stats["eligible"] += 1
        elif eligible is False:
            stats["excluded"] += 1
        else:
            stats["review_needed"] += 1
            
        print("\n" + format_job_preview(job, config, score_data, reason, eligible))
        stats["newly_imported"] += 1
        
        if not dry_run:
            tracker.add_job(job)
            if platform in existing_by_platform:
                existing_by_platform[platform].append(job) # ensure we don't insert it again in the same run

    return stats
