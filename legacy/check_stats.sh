#!/bin/bash
# Check application stats
source .venv/bin/activate
python -c "
from tracker import ApplicationTracker
t = ApplicationTracker('tracker.db')
import sqlite3
conn = sqlite3.connect('tracker.db')
total = conn.execute('SELECT COUNT(*) FROM applications').fetchone()[0]
applied = conn.execute(\"SELECT COUNT(*) FROM applications WHERE status='applied'\").fetchone()[0]
pending = conn.execute(\"SELECT COUNT(*) FROM applications WHERE status='pending'\").fetchone()[0]
skipped = conn.execute(\"SELECT COUNT(*) FROM applications WHERE status='skipped'\").fetchone()[0]
conn.close()
print(f'📊 Application Stats')
print(f'   Total tracked: {total}')
print(f'   ✅ Applied:    {applied}')
print(f'   ⏳ Pending:    {pending}')
print(f'   ⏭️  Skipped:    {skipped}')
"
