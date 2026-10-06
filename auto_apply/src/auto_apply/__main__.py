import argparse
import sys
from .orchestrator import run_workflow

def main():
    parser = argparse.ArgumentParser(description="Auto-Apply Job Bot")
    parser.add_argument("--platform", choices=["linkedin", "naukri"], help="Filter by platform")
    parser.add_argument("--dry-run", action="store_true", help="Dry run without applying")
    parser.add_argument("--db-path", type=str, help="Path to SQLite database to use (overrides config)")
    parser.add_argument("--open-browser", action="store_true", help="Open the persistent Chromium profile for manual browsing")
    parser.add_argument("--import-csv", type=str, help="Import jobs from a CSV file")
    parser.add_argument("--import-url", type=str, help="Import a job from a single URL")
    args = parser.parse_args()
    
    if args.open_browser:
        from pathlib import Path
        import os
        from playwright.sync_api import sync_playwright
        user_data_dir = Path(__file__).resolve().parents[3] / "sessions" / "chromium_profile"
        os.makedirs(user_data_dir, exist_ok=True)
        print(f"Opening browser using profile at: {user_data_dir}")
        print("Close the browser window to exit.")
        with sync_playwright() as p:
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(user_data_dir),
                    headless=False
                )
                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://www.linkedin.com")  # Navigate to a useful page instead of blank
                
                # Wait indefinitely for the user to close the page
                page.wait_for_event("close", timeout=0)
            except Exception as e:
                print(f"Failed to open browser. Is it already running? Error: {e}")
        return

    if args.import_csv or args.import_url:
        from pathlib import Path
        from .importer import import_jobs
        from .orchestrator import load_config
        from .tracker import TrackerDB
        
        config = load_config()
        if args.db_path:
            db_path = Path(args.db_path).resolve()
        else:
            db_path = Path(__file__).resolve().parents[3] / config.get("paths", {}).get("db_path", "tracker.db")
        tracker = TrackerDB(db_path, dry_run=args.dry_run)
        
        jobs = []
        if args.import_csv:
            import csv
            with open(args.import_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    job = {
                        "platform": row.get("platform", "unknown"),
                        "job_url": row.get("job_url", row.get("url", row.get("apply_url", ""))),
                        "title": row.get("title", ""),
                        "company": row.get("company", ""),
                        "location": row.get("location", ""),
                        "description": row.get("description", ""),
                        "experience": row.get("experience", "")
                    }
                    if job["job_url"]:
                        jobs.append(job)
                    else:
                        print(f"Warning: Skipping malformed CSV row (missing URL): {row}")
        
        if args.import_url:
            jobs.append({
                "platform": "unknown",
                "job_url": args.import_url,
                "title": "",
                "company": "",
                "location": ""
            })
            
        print(f"Prepared {len(jobs)} jobs for import...")
        stats = import_jobs(jobs, tracker, config, dry_run=args.dry_run)
        print("\n=== Import Summary ===")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        if args.dry_run:
            print("  (DRY RUN: No jobs were saved to the database)")
        tracker.close()
        return

    run_workflow(platform=args.platform, dry_run=args.dry_run, db_path=args.db_path)

if __name__ == "__main__":
    main()
