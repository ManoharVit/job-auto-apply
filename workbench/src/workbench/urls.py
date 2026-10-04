"""URL canonicalisation for display and duplicate detection only.

Tracking parameters are removed using an explicit allowlist. Anything not on
the list (e.g. ``jobid``, ``id``, ``source``, ``ref``, ``token``) is treated as
functional and kept, because stripping it could point to a different job.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Exact (lower-cased) names known to be pure tracking. Any ``utm_*`` is also tracking.
TRACKING_PARAMS = frozenset({
    "trk", "trkinfo", "refid", "trackingid", "gh_src",
    "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid",
})


def is_tracking_param(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith("utm_") or lowered in TRACKING_PARAMS


def canonical_url(url: str | None) -> str:
    """Return a stable form of ``url``; malformed input is returned stripped."""
    if not url:
        return ""
    raw = url.strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return raw

    host = parts.netloc.lower()
    # Regional LinkedIn hosts (in.linkedin.com, uk.linkedin.com, …) serve the same job IDs.
    if host.endswith(".linkedin.com"):
        host = "www.linkedin.com"

    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"

    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not is_tracking_param(k)]
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(kept), ""))
