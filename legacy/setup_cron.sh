#!/bin/bash
# ============================================================
# setup_cron.sh — Set up daily cron job for the auto-apply bot
# Run: bash setup_cron.sh
# ============================================================

BOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_PYTHON="${BOT_DIR}/.venv/bin/python"
MAIN_SCRIPT="${BOT_DIR}/main.py"
LOG_FILE="${BOT_DIR}/logs/cron.log"

echo "🔧 Setting up daily cron job..."
echo "   Bot directory: ${BOT_DIR}"
echo "   Python: ${VENV_PYTHON}"
echo ""

# Create the cron entry (runs at 9:00 AM IST every day)
CRON_JOB="0 9 * * * cd ${BOT_DIR} && ${VENV_PYTHON} ${MAIN_SCRIPT} >> ${LOG_FILE} 2>&1"

# Check if cron job already exists
crontab -l 2>/dev/null | grep -q "job-auto-apply" && {
    echo "⚠️  Cron job already exists. Replacing..."
    crontab -l 2>/dev/null | grep -v "job-auto-apply" | crontab -
}

# Add the cron job
(crontab -l 2>/dev/null; echo "# job-auto-apply daily run"; echo "${CRON_JOB}") | crontab -

echo "✅ Cron job installed!"
echo "   Schedule: Every day at 9:00 AM"
echo "   Logs: ${LOG_FILE}"
echo ""
echo "📋 Current crontab:"
crontab -l
echo ""
echo "To remove: crontab -e and delete the job-auto-apply lines"
echo "To test now: cd ${BOT_DIR} && ${VENV_PYTHON} ${MAIN_SCRIPT} --dry-run"
