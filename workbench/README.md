# workbench

A local, **read-only** view of your legacy `job-auto-apply/tracker.db`.

It never visits job sites, never logs in, never fills forms, never uploads files and never submits applications. It has **no runtime dependencies** (standard library only).

## Run

```bash
cd job-auto-apply/workbench
export PYTHONPATH=src
.venv/bin/python -m workbench stats
.venv/bin/python -m workbench list --platform naukri --status not_applied
.venv/bin/python -m workbench list --search fastapi --limit 0
.venv/bin/python -m workbench show 265
.venv/bin/python -m workbench duplicates
```

`--db PATH` points at a different database (default: `../tracker.db`).

## Status meanings

| Shown as | Legacy value | Meaning |
|---|---|---|
| Not applied | `pending` | Queued by the old bot, never attempted |
| Skipped | `skipped` | Old bot gave up; the reason is shown |
| Unconfirmed | `SUBMISSION_UNCONFIRMED`, `applied` | Old bot *claimed* success without verification. Treat as not applied unless you have your own proof |
| Unknown | anything else | Unexpected value, shown verbatim |

Nothing is ever shown as "Applied".

## Safety guarantees (tested)

- The database is opened with SQLite `mode=ro` plus `PRAGMA query_only`; writes raise errors.
- A missing database is reported, never created.
- Static tests forbid browser, network, subprocess and legacy-bot imports, write SQL, and `eval`/`exec`.

## Develop

```bash
uv venv .venv --python 3.12
uv pip sync --python .venv/bin/python --require-hashes requirements-dev.lock
.venv/bin/pytest -q --cov=workbench --cov-report=term-missing -W error
.venv/bin/ruff check src tests
.venv/bin/pip-audit -r requirements-dev.lock --require-hashes --disable-pip
```

To change dev dependencies, edit `pyproject.toml` (keep upper bounds), then regenerate the lock:
`uv pip compile pyproject.toml --extra dev --generate-hashes --python-version 3.12 -o requirements-dev.lock`
