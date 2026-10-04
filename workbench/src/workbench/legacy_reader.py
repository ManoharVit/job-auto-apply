"""Read-only access to the legacy job-auto-apply ``tracker.db``.

Safety contract
---------------
* The database is opened with SQLite URI ``mode=ro`` *and* ``PRAGMA query_only``,
  so any write attempt raises ``sqlite3.OperationalError``.
* A missing file raises :class:`LegacyDatabaseError`; it is never created.
* No legacy status is ever presented as "Applied". The old bot's success
  detection was unreliable, so ``applied`` and ``SUBMISSION_UNCONFIRMED`` are
  both shown as *unconfirmed*.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .urls import canonical_url

REQUIRED_COLUMNS = frozenset({
    "id", "platform", "job_url", "title", "company", "location",
    "match_score", "status", "error_message", "created_at",
})

# raw status -> (category, label)
_STATUS_MAP = {
    "pending": ("not_applied", "Not applied"),
    "skipped": ("skipped", "Skipped"),
    "failed": ("failed", "Failed"),
    "SUBMISSION_UNCONFIRMED": (
        "unconfirmed", "Unconfirmed — old bot claimed success, never verified"),
    "applied": (
        "unconfirmed", "Unconfirmed — legacy 'applied' flag, never verified"),
}

CATEGORY_LABELS = {
    "not_applied": "Not applied",
    "skipped": "Skipped",
    "failed": "Failed",
    "unconfirmed": "Unconfirmed",
    "unknown": "Unknown",
}

_REASON_LABELS = {
    "easy_apply_failed_or_external": "Easy Apply failed or external site",
    "no_easy_apply_external_redirect": "External site (no Easy Apply)",
    "naukri_apply_failed": "Naukri apply failed",
    "tech_mismatch_retroactive": "Tech-stack mismatch",
    "external_redirect": "External site",
    "no_apply_button": "No apply button found",
    "timeout": "Timed out",
}

_SELECT = (
    "SELECT id, platform, job_url, title, company, location, match_score, "
    "status, error_message, created_at FROM applications ORDER BY id"
)


class LegacyDatabaseError(Exception):
    """The legacy database is missing or does not have the expected shape."""


@dataclass(frozen=True)
class LegacyJob:
    id: int
    platform: str
    title: str
    company: str
    location: str
    match_score: float | None
    raw_status: str
    category: str
    status_label: str
    reason_label: str
    created_at: str
    url: str
    canonical_url: str


def _map_status(raw: str | None) -> tuple[str, str]:
    if raw in _STATUS_MAP:
        return _STATUS_MAP[raw]
    return "unknown", f"Unknown status: {raw!r}"


def _reason_label(raw: str | None) -> str:
    if not raw:
        return "No reason recorded"
    return _REASON_LABELS.get(raw, raw.replace("_", " ").capitalize())


class LegacyTracker:
    """Context-managed, read-only view over a legacy ``tracker.db``."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise LegacyDatabaseError(f"Database not found: {self.path}")
        uri = f"file:{quote(str(self.path))}?mode=ro"
        try:
            self._con = sqlite3.connect(uri, uri=True)
            self._con.execute("PRAGMA query_only = ON")
            self._check_schema()
        except sqlite3.DatabaseError as exc:
            raise LegacyDatabaseError(f"Cannot read {self.path}: {exc}") from exc

    def _check_schema(self) -> None:
        cols = {row[1] for row in self._con.execute("PRAGMA table_info(applications)")}
        if not cols:
            self.close()
            raise LegacyDatabaseError(f"No 'applications' table in {self.path}")
        missing = REQUIRED_COLUMNS - cols
        if missing:
            self.close()
            raise LegacyDatabaseError(
                f"'applications' table is missing columns: {', '.join(sorted(missing))}")

    def jobs(self) -> list[LegacyJob]:
        result = []
        for row in self._con.execute(_SELECT):
            (id_, platform, url, title, company, location,
             score, status, reason, created_at) = row
            category, label = _map_status(status)
            result.append(LegacyJob(
                id=id_,
                platform=platform or "unknown",
                title=(title or "").strip() or "(untitled)",
                company=(company or "").strip() or "(unknown company)",
                location=(location or "").strip(),
                match_score=score,
                raw_status=status or "",
                category=category,
                status_label=label,
                reason_label=_reason_label(reason) if category == "skipped" else "",
                created_at=str(created_at or ""),
                url=url or "",
                canonical_url=canonical_url(url),
            ))
        return result

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> LegacyTracker:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ── Pure helpers over loaded jobs ─────────────────────────────────────────

def summarize(jobs: list[LegacyJob]) -> dict:
    return {
        "total": len(jobs),
        "by_category": dict(sorted(Counter(j.category for j in jobs).items())),
        "by_platform": dict(sorted(Counter(j.platform for j in jobs).items())),
        "skip_reasons": dict(Counter(
            j.reason_label for j in jobs if j.category == "skipped").most_common()),
    }


def filter_jobs(
    jobs: list[LegacyJob],
    platform: str | None = None,
    category: str | None = None,
    search: str | None = None,
) -> list[LegacyJob]:
    needle = search.casefold().strip() if search else None
    out = []
    for job in jobs:
        if platform and job.platform != platform:
            continue
        if category and job.category != category:
            continue
        if needle and needle not in f"{job.title} {job.company}".casefold():
            continue
        out.append(job)
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


@dataclass(frozen=True)
class DuplicateGroup:
    kind: str  # "same_link" | "same_title_company"
    key: str
    jobs: tuple[LegacyJob, ...]


def find_duplicates(jobs: list[LegacyJob]) -> list[DuplicateGroup]:
    """Group likely duplicates. Rows lacking a real title or company are never grouped
    by title+company, because two unknowns are not evidence of the same job."""
    by_link: dict[str, list[LegacyJob]] = defaultdict(list)
    by_tc: dict[str, list[LegacyJob]] = defaultdict(list)
    for job in jobs:
        if job.canonical_url:
            by_link[job.canonical_url].append(job)
        if job.title != "(untitled)" and job.company != "(unknown company)":
            by_tc[f"{_norm(job.title)} | {_norm(job.company)}"].append(job)

    groups = [DuplicateGroup("same_link", k, tuple(v))
              for k, v in by_link.items() if len(v) > 1]
    groups += [DuplicateGroup("same_title_company", k, tuple(v))
               for k, v in by_tc.items() if len(v) > 1]
    return sorted(groups, key=lambda g: (g.kind, g.jobs[0].id))
