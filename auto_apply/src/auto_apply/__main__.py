"""CLI entry points; preview and import never enter an application workflow."""
import argparse
import csv
import sqlite3
import sys
from pathlib import Path

def _ids(value):
    from .authorization import validate_job_ids
    if value is None:
        return None
    parts = value.split(",")
    if any(not part.strip() for part in parts):
        raise ValueError("Job IDs cannot contain empty comma-separated entries.")
    return validate_job_ids([int(part.strip()) for part in parts])

def _import(args):
    from .importer import import_jobs
    from .orchestrator import _database_path, load_config
    from .tracker import TrackerDB
    config = load_config()
    jobs, row_errors = [], 0
    if args.import_csv:
        with Path(args.import_csv).expanduser().open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if not reader.fieldnames or not any(key in reader.fieldnames for key in ("job_url", "url", "apply_url")):
                raise ValueError("CSV requires a job_url, url, or apply_url header.")
            for number, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    print(f"CSV row {number}: wrong number of columns; skipped.", file=sys.stderr)
                    row_errors += 1
                    continue
                url = next((row[key].strip() for key in ("job_url", "url", "apply_url") if row.get(key, "").strip()), "")
                if not url:
                    print(f"CSV row {number}: missing URL; skipped.", file=sys.stderr)
                    row_errors += 1
                    continue
                jobs.append({
                    key: row.get(key, "").strip()
                    for key in ("platform", "apply_url", "title", "company", "location", "country", "description", "experience", "application_open")
                } | {"job_url": url})
    else:
        jobs = [{"platform": "", "job_url": args.import_url}]
    tracker = TrackerDB(_database_path(config, args.db_path), dry_run=args.dry_run)
    try:
        stats = import_jobs(jobs, tracker, config, dry_run=args.dry_run)
    finally:
        tracker.close()
    stats["errors"] += row_errors
    print("Import finished: " + ", ".join(f"{key}={value}" for key, value in stats.items()))
    if args.dry_run:
        print("Read-only preview; no records were changed.")
    return 1 if stats["errors"] else 0

def _open_browser(args):
    from .orchestrator import load_config
    from .settings import browser_profile
    from playwright.sync_api import sync_playwright
    profile = browser_profile(load_config())
    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(profile), headless=False)
        try:
            page = context.new_page()
            page.goto(args.browser_url, wait_until="domcontentloaded")
            print(f"Manual browser using {profile}. Close this tab to finish.")
            page.wait_for_event("close", timeout=0)
        finally:
            context.close()

def main():
    parser = argparse.ArgumentParser(description="Review jobs and run explicitly approved Greenhouse batches.")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--import-csv")
    actions.add_argument("--import-url")
    actions.add_argument("--preview-batch", action="store_true", help="Read-only queue or selected-job preview.")
    actions.add_argument("--preview-answers", action="store_true", help="Read-only answer-memory readiness summary.")
    actions.add_argument("--prepare-batch", action="store_true", help="Save a concrete, unapproved review manifest.")
    actions.add_argument("--run-batch", action="store_true")
    actions.add_argument("--resume-job", type=int)
    actions.add_argument("--open-browser", action="store_true", help="Open the persistent profile for manual browsing.")
    parser.add_argument("--platform", choices=("greenhouse", "linkedin", "naukri"))
    parser.add_argument("--job-ids")
    parser.add_argument("--db-path")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--authorize-submission")
    parser.add_argument("--out", help="New approval-draft path; existing files are never overwritten.")
    parser.add_argument("--phase", choices=("pilot", "daily"), default="pilot")
    parser.add_argument("--reviewed-pilot")
    parser.add_argument("--browser-url", default="about:blank")
    args = parser.parse_args()
    try:
        job_ids = _ids(args.job_ids)
        if args.preview_answers:
            import json
            from .answer_memory import preview_memory
            from .orchestrator import load_config
            print(json.dumps(preview_memory(load_config()), indent=2))
            return 0
        if args.import_csv or args.import_url:
            return _import(args)
        if args.open_browser:
            if args.dry_run:
                raise ValueError("--open-browser cannot be combined with --dry-run.")
            _open_browser(args)
            return 0
        if args.prepare_batch:
            if not job_ids or not args.out:
                raise ValueError("--prepare-batch requires --job-ids and --out.")
            from .approval import prepare_approval
            prepare_approval(job_ids, args.db_path, args.out, args.phase, args.reviewed_pilot)
            return 0
        if args.preview_batch:
            from .orchestrator import preview_batch
            preview_batch(args.platform, args.db_path, job_ids)
            return 0
        if args.run_batch:
            if not job_ids:
                raise ValueError("--job-ids is mandatory for --run-batch.")
            if not args.dry_run and not args.authorize_submission:
                raise ValueError("--authorize-submission is mandatory for a live batch.")
            from .orchestrator import run_unattended_batch
            run_unattended_batch(
                platform=args.platform or "greenhouse", dry_run=args.dry_run,
                db_path=args.db_path, retry_failed=args.retry_failed, job_ids=job_ids,
                auth_file=args.authorize_submission,
            )
            return 0
        if args.resume_job is not None:
            if not args.dry_run and not args.authorize_submission:
                raise ValueError("--authorize-submission is mandatory to resume.")
            from .orchestrator import run_resume_job
            run_resume_job(args.resume_job, args.authorize_submission, args.db_path, args.dry_run)
            return 0
        from .orchestrator import preview_batch
        preview_batch(args.platform, args.db_path, job_ids)
        return 0
    except (ValueError, OSError, RuntimeError, sqlite3.Error, csv.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
