"""Static boundary tests: the workbench package must stay local and read-only."""

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "workbench"

FORBIDDEN_MODULES = {
    # browser automation
    "playwright", "selenium", "pyppeteer", "undetected_chromedriver",
    # networking
    "httpx", "requests", "aiohttp", "urllib3", "urllib.request", "http.client",
    "socket", "smtplib", "ftplib", "websocket", "websockets",
    # process / browser launching
    "subprocess", "webbrowser", "pty",
    # legacy automation modules in the parent folder
    "main", "scraper", "linkedin_apply", "naukri_apply", "login_setup",
    "debug_form", "tracker", "utils", "filter",
}

WRITE_SQL = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|VACUUM)\b")


def _sources():
    files = sorted(SRC.glob("*.py"))
    assert files, "no source files found"
    return files


def _imported_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def test_no_forbidden_imports():
    offenders = []
    for path in _sources():
        tree = ast.parse(path.read_text())
        for mod in _imported_modules(tree):
            parts = mod.split(".")
            candidates = {".".join(parts[: i + 1]) for i in range(len(parts))}
            if candidates & FORBIDDEN_MODULES:
                offenders.append(f"{path.name}: {mod}")
    assert offenders == []


def test_no_write_sql_in_string_literals():
    offenders = []
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if WRITE_SQL.search(node.value.upper()) and "SELECT" not in node.value.upper():
                    offenders.append(f"{path.name}: {node.value[:60]!r}")
    assert offenders == []


def test_no_dynamic_code_execution():
    offenders = []
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"eval", "exec", "__import__"}:
                    offenders.append(f"{path.name}: {node.func.id}")
    assert offenders == []


def test_package_declares_no_runtime_dependencies():
    pyproject = (SRC.parents[1] / "pyproject.toml").read_text()
    assert re.search(r"^dependencies\s*=\s*\[\s*\]", pyproject, re.M)
