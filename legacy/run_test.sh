#!/bin/bash
# Test run — applies to 3 jobs with visible browser
source .venv/bin/activate
python main.py --limit 3 --headed
