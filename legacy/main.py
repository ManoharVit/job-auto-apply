"""
main.py — Daily orchestrator for the auto-apply bot.

Usage:
    python main.py                  # Full run: scrape + filter + apply
    python main.py --dry-run        # Scrape + filter only, no applications
    python main.py --limit 5        # Apply to max 5 jobs (testing)
    python main.py --skip-scrape    # Skip scraping, use cached/tracked jobs
    python main.py --stats          # Show application statistics
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from utils import load_config, setup_logging
from tracker import ApplicationTracker
from scraper import scrape_all
from filter import filter_jobs


def get_browser_context(playwright, config: dict, headed: bool = False):
    """Get a persistent browser context using the single shared profile.

    Both LinkedIn and Naukri run in the same Chromium user-data-dir
    (sessions/main_session) so there is only ONE profile to log into.
    Run `python login_setup.py` any time the session expires.
    """
    sessions_dir = Path(config["paths"]["sessions_dir"])
    session_name = config["paths"].get("session_name", "main_session")
    session_path = sessions_dir / session_name

    if not session_path.exists():
        return None

    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(session_path),
        headless=not headed,
        viewport={"width": 1280, "height": 800},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=TranslateUI",
            "--no-sandbox",
        ],
    )
    return context


def run_stats(tracker: ApplicationTracker, logger):
    """Display application statistics."""
    today = tracker.get_today_stats()
    total = tracker.get_total_stats()

    # Count rows in manual-apply CSV
    from pathlib import Path
    manual_csv = Path("logs/manual_apply.csv")
    manual_count = 0
    if manual_csv.exists():
        with open(manual_csv, encoding="utf-8") as f:
            manual_count = max(0, sum(1 for _ in f) - 1)  # subtract header

    logger.info("=" * 50)
    logger.info("📊 APPLICATION STATISTICS")
    logger.info("=" * 50)
    logger.info(f"  Today:  {today['applied']} applied, {today['skipped']} skipped, {today['failed']} failed")
    logger.info(f"  Total:  {total['applied']} applied, {total['skipped']} skipped, {total['failed']} failed")
    logger.info(f"  Tracked: {total['total_tracked']} jobs")
    logger.info(f"  📋 Manual apply list: {manual_count} jobs → logs/manual_apply.csv")
    logger.info("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Job Auto-Apply Bot")
    parser.add_argument("--dry-run", action="store_true", help="Scrape and filter only, don't apply")
    parser.add_argument("--limit", type=int, default=0, help="Max applications (0 = use config target)")
    parser.add_argument("--skip-scrape", action="store_true", help="Skip scraping, use existing tracked jobs")
    parser.add_argument("--stats", action="store_true", help="Show statistics and exit")
    parser.add_argument("--headed", action="store_true", help="Run browser in visible mode (better for debugging & anti-bot)")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    args = parser.parse_args()

    config = load_config(args.config)
    logger = setup_logging(config["paths"]["logs_dir"])
    tracker = ApplicationTracker(config["paths"]["db_path"])

    logger.info("=" * 60)
    logger.info(f"🚀 JOB AUTO-APPLY BOT — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 60)

    if args.stats:
        run_stats(tracker, logger)
        return

    # --- Step 1 & 4 Setup: Open Browser ---
    total_applied = 0
    with sync_playwright() as playwright:
        context = get_browser_context(playwright, config, args.headed)
        if context is None:
            logger.error(
                "  ❌ No session found.\n"
                "     Run: python login_setup.py\n"
                "     (opens browser → log in to LinkedIn + Naukri → press ENTER)"
            )
            return

        try:
            main_page = context.pages[0] if context.pages else context.new_page()

            # --- Step 1: Scrape jobs (Local Playwright) ---
            if not args.skip_scrape:
                logger.info("\n📡 Step 1: Scraping jobs locally...")
                all_jobs = scrape_all(main_page, config, logger)

                if not all_jobs:
                    logger.warning("No jobs scraped.")
                    logger.info("Falling back to existing tracked jobs...")
                    args.skip_scrape = True
            
            # --- Step 2: Filter + Score ---
            if not args.skip_scrape:
                logger.info("\n🔍 Step 2: Filtering and scoring...")
                filtered_jobs = filter_jobs(all_jobs, config, logger)

                for job in filtered_jobs:
                    url = job.get("apply_url") or job.get("job_url", "")
                    if url:
                        tracker.add_job(
                            platform=job["platform"],
                            job_url=url,
                            title=job.get("title", ""),
                            company=job.get("company", ""),
                            location=job.get("location", ""),
                            match_score=job.get("match_score", 0),
                        )
                logger.info(f"  Added {len(filtered_jobs)} jobs to tracker")

            # --- Step 3: Get unapplied jobs ---
            daily_target = args.limit if args.limit > 0 else config["targets"]["total_per_day"]
            linkedin_target = max(1, int(daily_target * 0.6))
            naukri_target = max(1, daily_target - linkedin_target)

            linkedin_jobs = tracker.get_unapplied_jobs(platform="linkedin", limit=linkedin_target)
            naukri_jobs = tracker.get_unapplied_jobs(platform="naukri", limit=naukri_target)

            logger.info(f"\n📋 Step 3: Ready to apply — {len(linkedin_jobs)} LinkedIn + {len(naukri_jobs)} Naukri")

            if args.dry_run:
                logger.info("\n🏃 DRY RUN — showing top candidates without applying:\n")
                for i, job in enumerate(linkedin_jobs[:10] + naukri_jobs[:10]):
                    logger.info(
                        f"  {i+1}. [{job['platform'].upper():8s}] Score={job['match_score']:5.1f} | "
                        f"{job['title'][:40]:40s} | {job['company'][:20]:20s} | {job['location'][:20]}"
                    )
                logger.info(f"\n  Total ready: {len(linkedin_jobs) + len(naukri_jobs)} jobs")
                return

            # --- Step 4: Apply ---
            if linkedin_jobs:
                logger.info(f"\n🔵 Step 4a: Applying to {len(linkedin_jobs)} LinkedIn jobs...")
                from linkedin_apply import run_linkedin_batch
                li_applied = run_linkedin_batch(main_page, linkedin_jobs, config, tracker, logger)
                total_applied += li_applied
                logger.info(f"  🔵 LinkedIn: {li_applied}/{len(linkedin_jobs)} applied")

            if naukri_jobs:
                logger.info(f"\n🟠 Step 4b: Applying to {len(naukri_jobs)} Naukri jobs...")
                nk_page = context.new_page()
                from naukri_apply import run_naukri_batch
                nk_applied = run_naukri_batch(nk_page, naukri_jobs, config, tracker, logger)
                total_applied += nk_applied
                logger.info(f"  🟠 Naukri: {nk_applied}/{len(naukri_jobs)} applied")
                try:
                    nk_page.close()
                except Exception:
                    pass

        finally:
            context.close()


    # --- Step 5: Summary ---
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ DAILY SUMMARY — {datetime.now().strftime('%Y-%m-%d')}")
    logger.info(f"{'='*60}")
    logger.info(f"  Applied today: {total_applied}")
    run_stats(tracker, logger)
    logger.info(f"{'='*60}\n")


if __name__ == "__main__":
    main()
