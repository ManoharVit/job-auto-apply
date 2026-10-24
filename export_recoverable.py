"""Export selected backup rows read-only; never restore a production database."""
import argparse
import csv
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Existing database or backup to inspect.")
    parser.add_argument("--job-ids", required=True, help="Explicit comma-separated IDs to export.")
    parser.add_argument("--out", required=True, help="New CSV artifact; will not overwrite.")
    args = parser.parse_args()
    try:
        parts = args.job_ids.split(",")
        if any(not part.strip() for part in parts):
            raise ValueError("Empty job-ID entry.")
        ids = [int(part.strip()) for part in parts]
        if not ids or any(value <= 0 for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("IDs must be nonempty, positive, and unique.")
        source = Path(args.source).expanduser().resolve()
        output = Path(args.out).expanduser().resolve()
        metadata = output.with_suffix(output.suffix + ".source.json")
        if not source.is_file():
            raise ValueError("Source database does not exist.")
        if output.exists() or metadata.exists():
            raise ValueError("Output artifact already exists; it will not be overwritten.")
        connection = sqlite3.connect(f"file:{quote(str(source))}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            placeholders = ",".join("?" for _ in ids)
            rows = connection.execute(
                f"SELECT * FROM applications WHERE id IN ({placeholders}) ORDER BY id", sorted(ids)
            ).fetchall()
            columns = [row["name"] for row in connection.execute("PRAGMA table_info(applications)")]
        finally:
            connection.close()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(dict(row) for row in rows)
        found = [row["id"] for row in rows]
        missing = sorted(set(ids) - set(found))
        with metadata.open("x", encoding="utf-8") as handle:
            json.dump({
                "source_database": str(source), "requested_ids": sorted(ids),
                "exported_ids": found, "unavailable_ids": missing,
                "note": "Read-only export. Missing records and pre-deletion attempt history remain unknown.",
            }, handle, indent=2)
        print(f"Exported {len(rows)} selected records from {source} to {output}")
        print(f"IDs not present in this source: {missing}")
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
