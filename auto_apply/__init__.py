from pathlib import Path
src_path = Path(__file__).resolve().parent / "src" / "auto_apply"
__path__.append(str(src_path))
