#!/bin/bash
# ============================================================
# Job Auto-Apply Bot — macOS Setup
# ============================================================
# Run this once on a fresh Mac to set up everything.
# ============================================================

set -e
echo "🚀 Setting up Job Auto-Apply Bot on macOS..."
echo ""

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Install from https://python.org or: brew install python3"
    exit 1
fi
echo "✅ Python: $(python3 --version)"

# 2. Create virtual environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate
echo "✅ Virtual environment activated"

# 3. Install dependencies
echo "📦 Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✅ Dependencies installed"

# 4. Install Playwright browsers
echo "🌐 Installing Chromium browser..."
python -m playwright install chromium
echo "✅ Chromium installed"

# 5. Create directories
mkdir -p sessions logs/screenshots resume

# 6. Check resume
if [ ! -f "resume/Giri_Manohar_Resume.pdf" ]; then
    echo ""
    echo "⚠️  IMPORTANT: Place your resume at:"
    echo "    $(pwd)/resume/Giri_Manohar_Resume.pdf"
fi

# 7. Check config
if grep -q "YOUR_" config.yaml 2>/dev/null; then
    echo ""
    echo "⚠️  IMPORTANT: Edit config.yaml with your credentials!"
fi

echo ""
echo "============================================================"
echo "✅ Setup complete! Next steps:"
echo ""
echo "  1. Edit config.yaml with your credentials"
echo "  2. Place your resume in the resume/ folder"
echo "  3. Run first login:  ./run_login.sh"
echo "  4. Test with:        ./run_test.sh"
echo "  5. Full run:         ./run_daily.sh"
echo "============================================================"
