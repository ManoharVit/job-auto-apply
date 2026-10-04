"""Command-line interface: ``python -m workbench [--db PATH] <command>``.

Exit codes: 0 success, 1 item not found, 2 usage or database error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .legacy_reader import (
    CATEGORY_LABELS,
    LegacyDatabaseError,
    LegacyJob,
    LegacyTracker,
    filter_jobs,
    find_duplicates,
    summarize,
)

# workbench/src/workbench/cli.py -> job-auto-apply/tracker.db
DEFAULT_DB = Path(__file__).resolve().parents[3] / "tracker.db"

BANNER = "Read-only view of {path}. Nothing here visits job sites or applies to jobs."


def _cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _table(headers: list[str], rows: list[list[str]], widths: list[int]) -> str:
    def line(cells):
        return "  ".join(_cut(c, w).ljust(w) for c, w in zip(cells, widths, strict=True))
    out = [line(headers), "  ".join("─" * w for w in widths)]
    out += [line(r) for r in rows]
    return "\n".join(line_.rstrip() for line_ in out)


def _cmd_stats(jobs: list[LegacyJob]) -> int:
    s = summarize(jobs)
    print(f"Total tracked: {s['total']}\n")
    print("By status")
    for cat, n in s["by_category"].items():
        print(f"  {CATEGORY_LABELS.get(cat, cat):<14} {n:>5}")
    print("\nBy platform")
    for plat, n in s["by_platform"].items():
        print(f"  {plat:<14} {n:>5}")
    if s["skip_reasons"]:
        print("\nSkip reasons")
        for reason, n in s["skip_reasons"].items():
            print(f"  {reason:<38} {n:>5}")
    if s["by_category"].get("unconfirmed"):
        print("\nNote: 'Unconfirmed' rows were marked successful by the old bot without "
              "verification. Treat them as not applied unless you have your own proof.")
    return 0


def _cmd_list(jobs: list[LegacyJob], args) -> int:
    matched = filter_jobs(jobs, platform=args.platform, category=args.status, search=args.search)
    if not matched:
        print("No jobs match these filters.")
        return 0
    shown = matched[: args.limit] if args.limit > 0 else matched
    rows = [[str(j.id), j.platform, CATEGORY_LABELS.get(j.category, j.category),
             j.title, j.company, j.location] for j in shown]
    print(_table(["ID", "Platform", "Status", "Title", "Company", "Location"],
                 rows, [5, 8, 12, 38, 24, 18]))
    print(f"\n{len(matched)} of {len(jobs)} jobs match; showing {len(shown)}.")
    return 0


def _cmd_show(jobs: list[LegacyJob], job_id: int) -> int:
    job = next((j for j in jobs if j.id == job_id), None)
    if job is None:
        print(f"No job with id {job_id}.", file=sys.stderr)
        return 1
    score = "—" if job.match_score is None else f"{job.match_score:.1f} (old keyword score)"
    fields = [
        ("Title", job.title), ("Company", job.company), ("Location", job.location or "—"),
        ("Platform", job.platform), ("Status", job.status_label),
        ("Skip reason", job.reason_label or "—"), ("Tracked since", job.created_at or "—"),
        ("Old score", score), ("Link", job.canonical_url or "—"),
    ]
    print(f"Job #{job.id}")
    for name, value in fields:
        print(f"  {name:<14} {value}")
    print("\nThe workbench never opens this link. If you want to apply, open it yourself "
          "in your browser.")
    return 0


def _cmd_duplicates(jobs: list[LegacyJob]) -> int:
    groups = find_duplicates(jobs)
    if not groups:
        print("No likely duplicates found.")
        return 0
    titles = {"same_link": "Same link", "same_title_company": "Same title + company"}
    for kind in ("same_link", "same_title_company"):
        subset = [g for g in groups if g.kind == kind]
        if not subset:
            continue
        print(f"{titles[kind]} — {len(subset)} group(s)")
        for g in subset:
            ids = ", ".join(f"#{j.id}" for j in g.jobs)
            first = g.jobs[0]
            print(f"  {ids:<20} {_cut(first.title, 40)} @ {_cut(first.company, 24)}")
        print()
    print("These are suggestions only; nothing was merged or changed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="workbench",
        description="Read-only view of your legacy job tracker. Never applies to jobs.")
    p.add_argument("--db", type=Path, default=DEFAULT_DB,
                   help=f"Path to legacy tracker.db (default: {DEFAULT_DB})")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("stats", help="Counts by status, platform and skip reason")
    lst = sub.add_parser("list", help="List tracked jobs")
    lst.add_argument("--platform", choices=["linkedin", "naukri"])
    lst.add_argument("--status", choices=sorted(CATEGORY_LABELS))
    lst.add_argument("--search", help="Case-insensitive match on title or company")
    lst.add_argument("--limit", type=int, default=50, help="Max rows (0 = all)")
    show = sub.add_parser("show", help="Show one job")
    show.add_argument("id", type=int)
    sub.add_parser("duplicates", help="Likely duplicate jobs")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        with LegacyTracker(args.db) as tracker:
            jobs = tracker.jobs()
    except LegacyDatabaseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(BANNER.format(path=args.db) + "\n")
    if args.command == "stats":
        return _cmd_stats(jobs)
    if args.command == "list":
        return _cmd_list(jobs, args)
    if args.command == "show":
        return _cmd_show(jobs, args.id)
    return _cmd_duplicates(jobs)
