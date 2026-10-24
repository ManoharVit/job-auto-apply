"""Reviewed exact-question answers stored separately from verified configuration."""
import hashlib
import math
import os
import re
from pathlib import Path

import yaml

from .settings import ROOT, fixture_mode, greenhouse_identity

LEGAL_FACTS = {"citizenship", "permanent_residency", "work_authorization", "visa_sponsorship"}
REUSE_MODES = {"exact_question", "manual_per_application", "notes_only"}


class AnswerMemoryError(ValueError):
    pass


def question_key(label):
    return str(label).strip().rstrip("*").strip().casefold()


def memory_path(config):
    selected = os.environ.get("AUTO_APPLY_ANSWERS") or config.get("paths", {}).get("answer_memory_path")
    isolated = fixture_mode(config) or bool(os.environ.get("PYTEST_CURRENT_TEST"))
    if not selected:
        # Synthetic/custom configuration must never implicitly read personal QA.
        if isolated or os.environ.get("AUTO_APPLY_CONFIG"):
            return None
        return ROOT / "application_qa.yaml"
    path = Path(str(selected)).expanduser()
    path = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if isolated and path.is_relative_to(ROOT):
        raise AnswerMemoryError("Tests require a separate temporary answer-memory file.")
    return path


def _validate_entry(entry, seen):
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"].strip():
        raise AnswerMemoryError("Every answer-memory question needs a nonempty string ID.")
    identifier = entry["id"]
    if identifier in seen:
        raise AnswerMemoryError(f"Duplicate answer-memory ID: {identifier}.")
    seen.add(identifier)
    if not isinstance(entry.get("question"), str) or not entry["question"].strip():
        raise AnswerMemoryError(f"{identifier}: question must be nonempty text.")
    if type(entry.get("reviewed", False)) is not bool:
        raise AnswerMemoryError(f"{identifier}: reviewed must be a YAML boolean.")
    if entry.get("reuse", "exact_question") not in REUSE_MODES:
        raise AnswerMemoryError(f"{identifier}: unsupported reuse mode.")
    labels = entry.get("exact_labels", [entry["question"]])
    if not isinstance(labels, list) or not labels or any(not isinstance(label, str) or not question_key(label) for label in labels):
        raise AnswerMemoryError(f"{identifier}: exact_labels must contain full question strings.")
    scope = entry.get("scope", {})
    if not isinstance(scope, dict) or set(scope) - {"countries", "companies", "job_urls"}:
        raise AnswerMemoryError(f"{identifier}: invalid scope.")
    for key, values in scope.items():
        if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value.strip() for value in values):
            raise AnswerMemoryError(f"{identifier}: {key} scope must be a nonempty list of strings.")
    value = entry.get("answer")
    if value is not None and type(value) not in (str, bool, int, float):
        raise AnswerMemoryError(f"{identifier}: answer must be scalar text, boolean or number.")
    if type(value) is float and not math.isfinite(value):
        raise AnswerMemoryError(f"{identifier}: nonfinite answers are not supported.")
    if entry.get("reviewed") and entry.get("reuse", "exact_question") == "exact_question":
        if value is None or (isinstance(value, str) and value.strip().casefold() in ("", "todo", "tbd", "unknown", "[unanswered]", "[unknown]", "[review needed]", "<answer>")):
            raise AnswerMemoryError(f"{identifier}: a reviewed reusable answer cannot be blank or a placeholder.")
        if entry.get("answer_type") == "number":
            try:
                number = float(value)
                if type(value) is bool or not math.isfinite(number) or number < 0:
                    raise ValueError()
            except (ValueError, TypeError) as exc:
                raise AnswerMemoryError(f"{identifier}: answer must be a nonnegative finite number.") from exc
        if entry.get("fact") in LEGAL_FACTS and entry.get("country") not in ("India", "IN"):
            raise AnswerMemoryError(f"{identifier}: legal facts need an explicit India country scope.")


def read_memory(config):
    path = memory_path(config)
    if path is None:
        return {"path": None, "sha256": "disabled", "questions": []}
    if not path.is_file():
        if os.environ.get("AUTO_APPLY_ANSWERS") or config.get("paths", {}).get("answer_memory_path"):
            raise AnswerMemoryError("The explicitly selected answer-memory file is missing.")
        return {"path": str(path), "sha256": "missing", "questions": []}
    try:
        raw = path.read_bytes()
        data = yaml.safe_load(raw)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise AnswerMemoryError("Answer memory is not readable valid YAML.") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("questions"), list):
        raise AnswerMemoryError("Answer memory requires schema_version: 1 and a questions list.")
    seen = set()
    for entry in data["questions"]:
        _validate_entry(entry, seen)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "questions": data["questions"]}


def memory_integrity(config):
    memory = read_memory(config)
    return {key: memory[key] for key in ("path", "sha256")}


def _scope_matches(scope, job):
    country = str(job.get("country") or "").strip()
    if not country and re.search(r"\bindia\b", str(job.get("location") or ""), re.I):
        country = "India"
    if country.casefold() == "in":
        country = "India"
    for key, actual in (("countries", country),
                        ("companies", job.get("company", ""))):
        allowed = {value.strip().casefold() for value in scope.get(key, [])}
        if key == "countries" and "in" in allowed:
            allowed.add("india")
        if key in scope and str(actual).strip().casefold() not in allowed:
            return False
    if "job_urls" in scope:
        actual = job.get("job_url") or job.get("apply_url")
        identity = greenhouse_identity(actual)
        if not any(actual == url or (identity is not None and identity == greenhouse_identity(url)) for url in scope["job_urls"]):
            return False
    return True


def _application_agreement(label):
    return bool(re.search(
        r"\b(?:nda|nondisclosure agreement|non-disclosure agreement|certification above)\b"
        r"|\bi (?:acknowledge|agree|have read)\b|\b(?:accept|agree).*(?:terms|privacy|consent|background check)\b"
        r"|\bi understand.*(?:background check|privacy|terms)\b",
        label, re.I,
    ))


def _verify_profile_reference(entry, config):
    reference = entry.get("profile_ref")
    if not reference:
        return
    value = config
    for key in str(reference).split("."):
        value = value.get(key) if isinstance(value, dict) else None
    answer = entry["answer"]
    def comparable(item):
        if type(item) is bool:
            return "yes" if item else "no"
        return str(item).strip().casefold()
    if entry.get("answer_type") == "number":
        try:
            equal = type(value) is not bool and float(answer) == float(value)
        except (TypeError, ValueError):
            equal = False
    else:
        equal = value is not None and comparable(answer) == comparable(value)
    if not equal:
        raise AnswerMemoryError(f"{entry['id']}: answer conflicts with verified configuration at {reference}.")


def application_answers(config, job):
    memory = read_memory(config)
    records = {}
    for entry in memory["questions"]:
        if entry.get("reviewed") is not True or entry.get("reuse", "exact_question") != "exact_question":
            continue
        if not _scope_matches(entry.get("scope", {}), job):
            continue
        _verify_profile_reference(entry, config)
        record = {"value": entry["answer"]}
        for key in ("country", "fact"):
            if entry.get(key):
                record[key] = entry[key]
        for label in entry.get("exact_labels", [entry["question"]]):
            if _application_agreement(label):
                continue
            key = question_key(label)
            if key in records and records[key] != record:
                raise AnswerMemoryError(f"Conflicting reviewed answers for exact question: {label}.")
            records[key] = record
    for label, value in config.get("application_answers", {}).items():
        key = question_key(label)
        record = value if isinstance(value, dict) else {"value": value}
        if key in records and records[key] != record:
            raise AnswerMemoryError(f"Saved answer conflicts with configuration for exact question: {label}.")
        records[key] = value
    return records


def preview_memory(config):
    memory = read_memory(config)
    questions = memory["questions"]
    result = {
        "path": memory["path"], "questions": len(questions),
        "reviewed": sum(entry.get("reviewed") is True for entry in questions),
        "pending_review": sum(entry.get("reviewed") is not True for entry in questions),
        "prefilled_pending": sum(entry.get("answer") is not None and entry.get("reviewed") is not True for entry in questions),
        "manual_or_notes": sum(entry.get("reuse", "exact_question") != "exact_question" for entry in questions),
        "submission_authorized": False,
    }
    return result
