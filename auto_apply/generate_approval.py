"""Compatibility script; prefer python -m auto_apply --prepare-batch."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if __name__ == "__main__":
    from auto_apply.__main__ import main
    sys.argv.insert(1, "--prepare-batch")
    sys.exit(main())
