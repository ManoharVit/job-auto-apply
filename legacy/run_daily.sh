#!/bin/bash
# Daily run — applies to 50 jobs, skips scraping if data exists
source .venv/bin/activate
python main.py --limit 50 --headed
