"""
Orchestrator for the job auto-apply workflow.

Connects discovery, eligibility scoring, user review, application
execution, and evidence-based tracking. All external actions require
explicit per-job confirmation.  --dry-run is fully side-effect-free.
"""

import yaml
import sys
from pathlib import Path
from .tracker import TrackerDB


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config():
    """Load config.yaml from the repository root (three levels above this file)."""
    config_path = Path(__file__).resolve().parents[3] / "config.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

import re

def _normalise(text: str) -> str:
    """Lower-case and collapse whitespace for matching."""
    return " ".join(text.lower().split()) if text else ""

def _skill_in_text(skill_lower: str, text: str) -> bool:
    """
    Check whether *skill_lower* appears in *text* as a distinct token.
    Handles multi-word skills like 'rest api' and single-word skills.
    Avoids false positives like 'sql' matching inside 'consul'.
    """
    pattern = r"(?<![a-z])" + re.escape(skill_lower) + r"(?![a-z])"
    return bool(re.search(pattern, text))

def score_job(job: dict, config: dict) -> dict:
    """
    Score a job against the candidate profile.

    Returns a dict with:
      score              – integer score (higher is better)
      matched_skills     – list of profile skills found in the title
      matched_title      – the target title that matched (or None)
      title_match_reason – human-readable explanation
      exclusion_assessment
      location_assessment
      uncertainties      – list of strings explaining what's uncertain
      missing_data       – list of fields the DB doesn't have
      genuine_mismatch   - boolean indicating if it explicitly matches exclusion criteria
    """
    profile = config.get("profile", {})
    filters = config.get("filters", {})
    title_raw = job.get("title", "")
    title = _normalise(title_raw)
    company = _normalise(job.get("company", ""))

    score = 0
    matched_skills: list[str] = []
    uncertainties: list[str] = []
    missing_data: list[str] = []
    genuine_mismatch = False

    # --- Genuine Mismatch / Exclusions -------------------------------------
    excluded_kw = [kw.lower() for kw in filters.get("excluded_title_keywords", [])]
    exclusion_assessment = "Match"
    for kw in excluded_kw:
        if _skill_in_text(kw, title):
            exclusion_assessment = f"Excluded ('{kw}' in title)"
            genuine_mismatch = True
            break

    description = _normalise(job.get("description", ""))
    experience = job.get("experience", "")

    # --- Skill matching (title and description) --------
    profile_skills = profile.get("skills", [])
    for skill in profile_skills:
        skill_lower = skill.lower()
        if _skill_in_text(skill_lower, title) or _skill_in_text(skill_lower, description):
            if skill not in matched_skills:
                matched_skills.append(skill)
            score += 10

    if not description:
        missing_data.append("Missing description")
    if not experience:
        missing_data.append("Experience requirements unknown")
    else:
        candidate_exp_str = config.get("screening", {}).get("years_of_experience")
        candidate_exp = None
        try:
            if candidate_exp_str is not None:
                candidate_exp = int(candidate_exp_str)
        except ValueError:
            pass

        import re
        word_to_num = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
        }
        
        # Convert word numbers to digits in the string before regex search
        exp_lower = experience.lower()
        for word, num in word_to_num.items():
            exp_lower = re.sub(r'\b' + word + r'\b', str(num), exp_lower)
            
        match = re.search(r'(\d+)\s*(?:\+|-|to)?\s*(\d+)?\s*(?:years?|yrs?)', exp_lower)
        if match:
            req_exp = int(match.group(1))
            if candidate_exp is not None:
                if req_exp > candidate_exp:
                    genuine_mismatch = True
                    exclusion_assessment = f"Excluded (Requires {req_exp} years experience, candidate has {candidate_exp})"
            else:
                uncertainties.append(f"Candidate experience is unknown, but job requires {req_exp} years")
        else:
            uncertainties.append(f"Could not parse required years from experience text: '{experience}'")

    # --- Target-title matching ---------------------------------------------
    target_titles = profile.get("target_titles", [])
    matched_title = None
    title_match_reason = ""
    filler = {"in", "at", "the", "a", "an", "-", "&", "/", "|", "and", "or", "for", "with"}
    title_key = set(title.split()) - filler

    # Pass 1: exact (all target keywords present in job title)
    for tt in target_titles:
        tt_key = set(_normalise(tt).split()) - filler
        if tt_key and tt_key.issubset(title_key):
            matched_title = tt
            title_match_reason = f"Title matches target role '{tt}'"
            score += 25
            break

    # Pass 2: partial (≥60% overlap) — only if no exact match found
    if not matched_title:
        best_overlap = 0.0
        for tt in target_titles:
            tt_key = set(_normalise(tt).split()) - filler
            if not tt_key:
                continue
            ratio = len(tt_key & title_key) / len(tt_key)
            if ratio >= 0.6 and ratio > best_overlap:
                best_overlap = ratio
                matched_title = tt
                title_match_reason = f"Title partially matches target role '{tt}'"
        if matched_title:
            score += 15

    # If the title contains generic backend/developer keywords that align
    # with the candidate's stack but aren't in target_titles verbatim
    backend_keywords = {"backend", "back-end", "back end"}
    if not matched_title and backend_keywords & set(title.split()):
        if any(_skill_in_text(s.lower(), title) for s in ["python", "fastapi", "django", "flask"]):
            title_match_reason = "Title contains 'backend' + a profile language"
            score += 20
        else:
            title_match_reason = "Title contains 'backend' (stack unknown from title alone)"
            # Do NOT add to score to avoid marking as Review Needed for weak matches
            missing_data.append("Generic backend role, but stack is unknown from title")

    # --- Seniority (if not already excluded) -------------------------------
    seniority_assessment = exclusion_assessment
    if not genuine_mismatch:
        senior_markers = ["senior", "sr.", "sr ", "lead", "manager",
                          "director", "principal", "staff", "head", "vp"]
        if any(m in title for m in senior_markers):
            seniority_assessment = "Senior (may be above target level)"
            uncertainties.append("Title suggests senior-level role")
        elif any(m in title for m in ["junior", "jr", "entry"]):
            seniority_assessment = "Junior"
        elif "intern" in title:
            seniority_assessment = "Intern"

    # --- Location ----------------------------------------------------------
    profile_locations = [loc.lower() for loc in profile.get("locations", [])]
    job_location = _normalise(job.get("location", ""))

    if any(pl in job_location for pl in profile_locations) or "remote" in job_location:
        location_assessment = "Match"
    elif not job_location:
        location_assessment = "Unknown"
        missing_data.append("No location data")
    else:
        location_assessment = "Mismatch"
        uncertainties.append(f"Location '{job.get('location')}' may not match profile")

    # Force score to 0 if it's a genuine mismatch to ensure rejection
    if genuine_mismatch:
        score = 0

    return {
        "score": score,
        "matched_skills": matched_skills,
        "matched_title": matched_title,
        "title_match_reason": title_match_reason,
        "seniority_assessment": seniority_assessment,
        "location_assessment": location_assessment,
        "uncertainties": uncertainties,
        "missing_data": missing_data,
        "genuine_mismatch": genuine_mismatch,
    }

def is_eligible(job: dict, config: dict, score_data: dict):
    """
    Returns (eligible, reason) where eligible is:
      True  – job passes all gates
      False – job is excluded
      None  – job needs human review
    """
    score = score_data["score"]
    filters = config.get("filters", {})

    if score_data["genuine_mismatch"]:
        return False, f"Genuine mismatch: {score_data['seniority_assessment']}"

    # Minimum score gate (default 10)
    min_score = filters.get("min_score", 10)
    if score < min_score:
        if not score_data["matched_skills"] and not score_data["matched_title"]:
            if not job.get("title", "").strip():
                return None, "Needs review: Missing title (URL-only import)"
            return False, f"Score {score} below minimum {min_score} (Missing Data: unknown stack/skills from title alone)"
        return False, f"Score {score} below minimum {min_score}"

    if score_data["missing_data"]:
        return None, "Needs review: " + "; ".join(score_data["missing_data"])

    # Enforce unknown availability
    avail = str(job.get("application_open", "")).strip().lower()
    if avail in ("unknown", "", "none"):
        return None, "Needs review: Application availability Unknown"
    if avail in ("false", "no", "closed"):
        return False, "Excluded: Application is closed"


    # If there are uncertainties or location issues, flag for review
    if score_data["uncertainties"] or score_data["location_assessment"] == "Mismatch":
        return None, "Needs review: " + "; ".join(
            score_data["uncertainties"]
            or [f"Location mismatch ({job.get('location')})"]
        )

    return True, ""

def format_job_preview(job: dict, config: dict, score_data: dict,
                       reason: str, is_eligible_flag) -> str:
    """Format a human-readable preview card for one job."""
    lines = [
        "-" * 60,
        f"Title:     {job.get('title')}",
        f"Company:   {job.get('company')}",
        f"Location:  {job.get('location')} ({score_data['location_assessment']})",
        f"URL:       {job.get('job_url') or job.get('apply_url')}",
        f"Score:     {score_data['score']}",
    ]
    if score_data["title_match_reason"]:
        lines.append(f"Title fit: {score_data['title_match_reason']}")
    lines.append(f"Seniority: {score_data['seniority_assessment']}")
    lines.append(
        f"Skills:    {', '.join(score_data['matched_skills']) if score_data['matched_skills'] else 'None matched in title'}"
    )
    if score_data["uncertainties"]:
        lines.append(f"⚠ Uncertainties: {'; '.join(score_data['uncertainties'])}")
    if score_data["missing_data"]:
        lines.append(f"ℹ Missing data: {'; '.join(score_data['missing_data'])}")

    if is_eligible_flag is False:
        if score_data["genuine_mismatch"]:
            lines.append(f"Decision:  ✗ EXCLUDED (Genuine Mismatch) – {reason}")
        else:
            lines.append(f"Decision:  ✗ EXCLUDED – {reason}")
    elif is_eligible_flag is None:
        lines.append(f"Decision:  ? REVIEW NEEDED – {reason}")
    else:
        lines.append(f"Decision:  ✓ ELIGIBLE")
    lines.append("-" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

def run_workflow(platform=None, dry_run=False, db_path=None):
    config = load_config()

    # Validate that profile loaded properly
    profile = config.get("profile", {})
    skills = profile.get("skills", [])
    target_titles = profile.get("target_titles", [])
    locations = profile.get("locations", [])
    print(f"Profile loaded: {len(skills)} skills, {len(target_titles)} target titles, {len(locations)} locations")
    if not skills:
        print("WARNING: No skills found in config.yaml profile.skills – scoring will be unreliable")
    if not target_titles:
        print("WARNING: No target_titles in config.yaml profile.target_titles – title matching disabled")

    if db_path:
        resolved_db_path = Path(db_path).resolve()
    else:
        resolved_db_path = Path(__file__).resolve().parents[3] / config.get("paths", {}).get("db_path", "tracker.db")
    tracker = TrackerDB(resolved_db_path, dry_run=dry_run)

    status_counts = tracker.get_status_counts()
    print("=== Historical Queue Status ===")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")
    print("===============================\n")

    pending_jobs = tracker.get_pending_jobs(platform=platform)

    # Pre-evaluate pending jobs
    eligible_count = 0
    review_count = 0
    excluded_count = 0
    
    evaluated_jobs = []
    for job in pending_jobs:
        score_data = score_job(job, config)
        eligible, reason = is_eligible(job, config, score_data)
        if eligible is False:
            excluded_count += 1
        elif eligible is None:
            review_count += 1
        else:
            eligible_count += 1
        evaluated_jobs.append((job, score_data, eligible, reason))

    print("=== Pending Jobs Breakdown ===")
    print(f"  Total pending: {len(pending_jobs)}")
    print(f"  Eligible:      {eligible_count}")
    print(f"  Review needed: {review_count}")
    print(f"  Excluded:      {excluded_count}")
    print("==============================\n")

    if dry_run:
        print("=== DRY RUN MODE ===")
        print("Inspects inputs, scores jobs, previews decisions, and explains reasoning.")
        print("Will NOT open a browser, contact platforms, upload files, fill forms, or modify the database.\n")

    session_stats = {
        "reviewed": 0,
        "deferred": 0,
        "dismissed": 0,
        "left_unchanged": 0
    }

    for job, score_data, eligible, reason in evaluated_jobs:
        preview = format_job_preview(job, config, score_data, reason, eligible)
        print(preview)

        if eligible is False:
            if dry_run:
                print("  [DRY-RUN] Excluding job from current session due to ineligibility (status unchanged).\n")
            else:
                print("  Excluding job from current session due to ineligibility (status unchanged).\n")
            # We explicitly do NOT update the database status here.
            # Dismissal must require explicit user action.
            session_stats["left_unchanged"] += 1
            continue


        print("  Application details:")
        print(f"    Resume: {profile.get('resume_path', '(not set)')}")
        print(f"    Answers: Verified profile data only; unknowns left BLANK for your review")

        if dry_run:
            print("  [DRY-RUN] Would prompt for Action: [R]eview now / [N]ot now / [D]ismiss / [Q]uit.\n")
            session_stats["left_unchanged"] += 1
            continue

        while True:
            ans = input("\n  Action: [R]eview now / [N]ot now / [D]ismiss / [Q]uit: ").strip().lower()
            if ans in ('r', 'n', 'd', 'q'):
                break
            print("  Invalid choice. Please enter r, n, d, or q.")

        if ans == 'q':
            print("  Quitting session.\n")
            # The remaining jobs in this loop are left unchanged
            remaining = len(pending_jobs) - (session_stats["reviewed"] + session_stats["deferred"] + session_stats["dismissed"])
            session_stats["left_unchanged"] += remaining
            break

        if ans == 'n':
            print("  Leaving for later.\n")
            session_stats["deferred"] += 1
            continue

        if ans == 'd':
            print("  Dismissing job.\n")
            tracker.update_job(job["id"], status="skipped", action="Dismiss", reason=reason, match_score=score_data["score"], error_message=reason)
            session_stats["dismissed"] += 1
            continue

        if ans == 'r':
            print("  Opening browser for application...")
            status, evidence = execute_application_automated(job, config)
            print(f"  Result: {status}")
            if evidence:
                print(f"  Evidence: {evidence}")

            tracker.update_job(job["id"], status=status, action="Review", reason=evidence, error_message=evidence,
                               match_score=score_data["score"])
            session_stats["reviewed"] += 1
            print()

    # If the loop finishes normally, we don't need to add remaining (they are added iteratively, except left_unchanged needs to capture the rest if Q was not pressed, but they were actually processed)
    # wait, if Q is not pressed, what is left_unchanged? Only what's explicitly deferred?
    # Deferred means 'n' was pressed.
    # What if they weren't processed because Q was pressed? We handled that.

    print(f"\n--- Queue Stats: {eligible_count} eligible, {review_count} review-needed, {excluded_count} excluded ---")
    print(f"--- Session Summary: {session_stats['reviewed']} reviewed, {session_stats['deferred']} deferred, {session_stats['dismissed']} dismissed, {session_stats['left_unchanged']} left unchanged ---")
    tracker.close()


from .automation import execute_application_automated
