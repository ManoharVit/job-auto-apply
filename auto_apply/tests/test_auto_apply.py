"""
Tests for the auto_apply orchestrator and automation safety rules.

All tests use local mocks only — no browsers, no network, no real accounts.
"""

import pytest
from unittest.mock import patch, MagicMock, call
from auto_apply.orchestrator import score_job, is_eligible, run_workflow, _skill_in_text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROFILE_CONFIG = {
    "profile": {
        "skills": [
            "Python", "FastAPI", "SQLAlchemy", "Pydantic", "PostgreSQL",
            "Redis", "Docker", "AWS", "SQL", "LLM", "REST API",
        ],
        "target_titles": [
            "Python Developer",
            "Python Backend Developer",
            "Backend Developer",
            "FastAPI Developer",
            "Django Developer",
            "LLM Engineer",
        ],
        "locations": ["Hyderabad", "Bengaluru", "Chennai", "Remote", "India"],
        "email": "test@example.com",
        "phone": "1234567890",
        "resume_path": "/tmp/fake_resume.pdf",
    },
    "screening": {
        "years_of_experience": "2",
        "expected_ctc": "8",
        "current_ctc": "5",
        "notice_period": "30 days",
        "highest_education": "Master's",
        "graduation_year": "2024",
    },
    "filters": {
        "min_score": 10,
        "excluded_title_keywords": [
            "Senior", "Sr.", "Lead", "Manager", "Director", "Java", "PHP",
        ],
    },
    "paths": {"db_path": "tracker.db"},
}


def _job(title, company="Test Co", location="Hyderabad", platform="linkedin", **kwargs):
    base_job = {
        "id": 1,
        "title": title,
        "company": company,
        "location": location,
        "job_url": "https://example.com/job/1",
        "platform": platform,
    }
    base_job.update(kwargs)
    return base_job


# ---------------------------------------------------------------------------
# Scoring tests
# ---------------------------------------------------------------------------

class TestScoring:
    """Verify that the scorer identifies relevant jobs from title alone."""

    def test_python_developer_matches_skill_and_title(self):
        result = score_job(_job("Python Developer"), PROFILE_CONFIG)
        assert "Python" in result["matched_skills"]
        assert result["matched_title"] is not None
        assert result["score"] >= 35  # 10 (skill) + 25 (title)

    def test_backend_developer_matches_target_title(self):
        result = score_job(_job("Backend Developer"), PROFILE_CONFIG)
        assert result["matched_title"] is not None
        assert result["score"] >= 25  # title match

    def test_backend_developer_with_python_in_title(self):
        result = score_job(_job("Python Backend Developer"), PROFILE_CONFIG)
        assert "Python" in result["matched_skills"]
        assert result["score"] >= 35

    def test_fastapi_developer_matches(self):
        result = score_job(_job("FastAPI Developer"), PROFILE_CONFIG)
        assert "FastAPI" in result["matched_skills"]
        assert result["matched_title"] is not None
        assert result["score"] >= 35

    def test_robotics_engineer_scores_zero(self):
        result = score_job(
            _job("Robotics Software Engineer (ROS/ROS2 | SLAM | Navigation)"),
            PROFILE_CONFIG,
        )
        assert result["score"] == 0
        assert result["matched_skills"] == []
        assert result["matched_title"] is None

    def test_java_developer_scores_zero(self):
        result = score_job(_job("Java Software Engineer"), PROFILE_CONFIG)
        assert result["score"] == 0

    def test_cobol_developer_scores_zero(self):
        result = score_job(_job("COBOL developer"), PROFILE_CONFIG)
        assert result["score"] == 0

    def test_react_native_scores_zero(self):
        result = score_job(_job("React Native Mobile Developer Intern"), PROFILE_CONFIG)
        assert result["score"] == 0

    def test_llm_engineer_matches(self):
        result = score_job(_job("LLM Engineer"), PROFILE_CONFIG)
        assert "LLM" in result["matched_skills"]
        assert result["matched_title"] is not None
        assert result["score"] >= 35

    def test_generic_software_engineer_scores_zero(self):
        """A generic title with no skill keywords should not score highly."""
        result = score_job(_job("Software Engineer"), PROFILE_CONFIG)
        assert result["score"] == 0

    def test_sql_does_not_match_consul(self):
        """Word-boundary matching: 'sql' must not match inside 'consul'."""
        result = score_job(_job("DevOps Consul Engineer"), PROFILE_CONFIG)
        assert "SQL" not in result["matched_skills"]

    def test_location_mismatch_flagged(self):
        result = score_job(_job("Python Developer", location="New York, USA"), PROFILE_CONFIG)
        assert result["location_assessment"] == "Mismatch"
        assert any("location" in u.lower() for u in result["uncertainties"])

    def test_missing_data_noted_when_no_skills_match(self):
        result = score_job(_job("Full Stack Developer I"), PROFILE_CONFIG)
        assert result["missing_data"]  # Should note title-only matching

    def test_senior_role_detected(self):
        result = score_job(_job("Senior Python Developer"), PROFILE_CONFIG)
        assert "Senior" in result["seniority_assessment"] or "Excluded" in result["seniority_assessment"]


class TestSkillInText:
    """Word-boundary skill matching."""

    def test_exact_match(self):
        assert _skill_in_text("python", "python developer")

    def test_no_partial_match(self):
        assert not _skill_in_text("sql", "consul engineer")

    def test_multi_word_skill(self):
        assert _skill_in_text("rest api", "build rest api services")

    def test_skill_at_end(self):
        assert _skill_in_text("python", "senior python")

    def test_skill_with_punctuation(self):
        assert _skill_in_text("python", "python/django developer")
        assert _skill_in_text("c++", "c++ developer")
        assert not _skill_in_text("c++", "mac++")
        assert _skill_in_text("c#", "backend c# engineer")


# ---------------------------------------------------------------------------
# Eligibility tests
# ---------------------------------------------------------------------------

class TestEligibility:
    def test_excluded_keyword_blocks(self):
        score_data = score_job(_job("Senior Python Developer"), PROFILE_CONFIG)
        eligible, reason = is_eligible(_job("Senior Python Developer"), PROFILE_CONFIG, score_data)
        assert eligible is False
        assert "senior" in reason.lower()

    def test_java_excluded(self):
        score_data = score_job(_job("Java Software Engineer"), PROFILE_CONFIG)
        eligible, reason = is_eligible(_job("Java Software Engineer"), PROFILE_CONFIG, score_data)
        assert eligible is False

    def test_zero_score_excluded(self):
        score_data = score_job(_job("COBOL developer"), PROFILE_CONFIG)
        eligible, reason = is_eligible(_job("COBOL developer"), PROFILE_CONFIG, score_data)
        assert eligible is False
        assert "below minimum" in reason

    def test_backend_developer_eligible_or_review(self):
        """A generic 'Backend Developer' should score above min and be eligible or review."""
        job = _job("Backend Developer", location="Hyderabad")
        score_data = score_job(job, PROFILE_CONFIG)
        eligible, reason = is_eligible(job, PROFILE_CONFIG, score_data)
        # Should not be excluded
        assert eligible is not False, f"Backend Developer wrongly excluded: {reason}"

    def test_python_developer_eligible(self):
        job = _job("Python Developer", location="Remote", description="Python backend development", experience="2 years", application_open="Open")
        score_data = score_job(job, PROFILE_CONFIG)
        eligible, reason = is_eligible(job, PROFILE_CONFIG, score_data)
        assert eligible is True, f"Python Developer not eligible: {reason}"


# ---------------------------------------------------------------------------
# Workflow safety tests
# ---------------------------------------------------------------------------

@patch("auto_apply.orchestrator.load_config", return_value=PROFILE_CONFIG)
@patch("auto_apply.orchestrator.TrackerDB")
@patch("auto_apply.orchestrator.execute_application_automated")
def test_dry_run_no_side_effects(mock_exec, mock_tracker_class, mock_config):
    mock_tracker = mock_tracker_class.return_value
    mock_tracker.get_pending_jobs.return_value = [
        _job("Python Developer", location="Remote"),
    ]

    run_workflow(dry_run=True)

    mock_exec.assert_not_called()
    mock_tracker.update_job.assert_not_called()


@patch("auto_apply.orchestrator.load_config", return_value=PROFILE_CONFIG)
@patch("auto_apply.orchestrator.TrackerDB")
@patch("auto_apply.orchestrator.execute_application_automated")
@patch("builtins.input", return_value="n")
def test_declining_job_does_not_submit(mock_input, mock_exec, mock_tracker_class, mock_config):
    mock_tracker = mock_tracker_class.return_value
    mock_tracker.get_pending_jobs.return_value = [
        _job("Python Developer", location="Remote"),
    ]

    run_workflow(dry_run=False)

    mock_exec.assert_not_called()


@patch("auto_apply.orchestrator.load_config", return_value=PROFILE_CONFIG)
@patch("auto_apply.orchestrator.TrackerDB")
@patch("auto_apply.orchestrator.execute_application_automated")
@patch("builtins.input", return_value="r")
def test_upload_failure_tracked_as_failed(mock_input, mock_exec, mock_tracker_class, mock_config):
    mock_tracker = mock_tracker_class.return_value
    mock_tracker.get_pending_jobs.return_value = [
        _job("Python Developer", location="Remote"),
    ]
    mock_exec.return_value = ("failed", "Resume upload failed")

    run_workflow(dry_run=False)

    mock_exec.assert_called_once()
    mock_tracker.update_job.assert_called_once()
    call_kwargs = mock_tracker.update_job.call_args[1]
    assert call_kwargs["status"] == "failed"


@patch("auto_apply.orchestrator.load_config", return_value=PROFILE_CONFIG)
@patch("auto_apply.orchestrator.TrackerDB")
@patch("auto_apply.orchestrator.execute_application_automated")
@patch("builtins.input", return_value="r")
def test_success_evidence_persisted(mock_input, mock_exec, mock_tracker_class, mock_config):
    mock_tracker = mock_tracker_class.return_value
    mock_tracker.get_pending_jobs.return_value = [
        _job("Python Developer", location="Remote"),
    ]
    mock_exec.return_value = ("confirmed_submitted", "Platform evidence: Applied Successfully")

    run_workflow(dry_run=False)

    call_kwargs = mock_tracker.update_job.call_args[1]
    assert call_kwargs["status"] == "confirmed_submitted"
    assert "Applied Successfully" in call_kwargs["error_message"]


# ---------------------------------------------------------------------------
# Automation form-filling tests
# ---------------------------------------------------------------------------

class TestFormFilling:
    """Verify that the automation never types placeholder text into fields."""

    def test_fill_returns_blank_list_not_placeholder(self):
        """Unknown fields must be left blank, not filled with '[REVIEW NEEDED]'."""
        from auto_apply.automation import fill_form_conservatively

        # Create a mock page with one visible empty text input that has no
        # recognisable label
        mock_input = MagicMock()
        mock_input.is_visible.return_value = True
        mock_input.get_attribute.side_effect = lambda attr: {
            "type": "text", "placeholder": ""
        }.get(attr, "")
        mock_input.input_value.return_value = ""
        mock_input.evaluate.return_value = ""

        mock_locator = MagicMock()
        mock_locator.count.return_value = 1
        mock_locator.nth.return_value = mock_input

        mock_page = MagicMock()
        # locator("input") returns inputs, locator("textarea") returns none
        def locator_side_effect(selector):
            if selector == "input":
                return mock_locator
            else:
                empty = MagicMock()
                empty.count.return_value = 0
                return empty
        mock_page.locator.side_effect = locator_side_effect

        blank_fields = fill_form_conservatively(mock_page, PROFILE_CONFIG)

        # The field must NOT have been filled with any text
        mock_input.fill.assert_not_called()
        # The field should be reported as blank
        assert len(blank_fields) == 1

    def test_known_field_gets_filled(self):
        """A phone field should be filled with the profile phone number."""
        from auto_apply.automation import fill_form_conservatively

        mock_input = MagicMock()
        mock_input.is_visible.return_value = True
        mock_input.get_attribute.side_effect = lambda attr: {
            "type": "tel", "placeholder": "phone number"
        }.get(attr, "")
        mock_input.input_value.return_value = ""
        mock_input.evaluate.return_value = "Phone"

        mock_locator = MagicMock()
        mock_locator.count.return_value = 1
        mock_locator.nth.return_value = mock_input

        mock_page = MagicMock()
        def locator_side_effect(selector):
            if selector == "input":
                return mock_locator
            else:
                empty = MagicMock()
                empty.count.return_value = 0
                return empty
        mock_page.locator.side_effect = locator_side_effect

        blank_fields = fill_form_conservatively(mock_page, PROFILE_CONFIG)

        mock_input.fill.assert_called_once_with("1234567890")
        assert len(blank_fields) == 0


def test_automation_module_importable():
    """Verify the automation module is importable without playwright installed."""
    from auto_apply.automation import execute_application_automated
    assert callable(execute_application_automated)


# ---------------------------------------------------------------------------
# Historical data protection
# ---------------------------------------------------------------------------

@patch("auto_apply.orchestrator.load_config", return_value=PROFILE_CONFIG)
@patch("auto_apply.orchestrator.TrackerDB")
def test_dry_run_never_touches_db(mock_tracker_class, mock_config):
    """Dry run must not call update_job at all, even for excluded jobs."""
    mock_tracker = mock_tracker_class.return_value
    mock_tracker.get_pending_jobs.return_value = [
        _job("COBOL developer"),
        _job("Python Developer", location="Remote"),
        _job("Senior Java Engineer"),
    ]

    run_workflow(dry_run=True)

    mock_tracker.update_job.assert_not_called()
