"""Canonical deduplication and an explicitly approved first-party form route."""
import pytest

from auto_apply.authorization import AuthorizationError, validate_authorization
from auto_apply.importer import import_jobs
from auto_apply.orchestrator import _submission_eligibility
from auto_apply.settings import job_application_url


LISTING = 'https://job-boards.greenhouse.io/fixtureco/jobs/1001'
FORM = 'https://job-boards.greenhouse.io/embed/job_app?for=fixtureco&token=1001'


def posting(**updates):
    return {'platform': 'greenhouse', 'job_url': LISTING, 'apply_url': FORM,
            'title': 'Python Developer', 'company': 'TestCo', 'country': 'India',
            'location': 'India', 'description': 'Python and FastAPI backend development.',
            'experience': '1-2 years', 'application_open': 'Open'} | updates


def test_embed_import_keeps_form_route_and_deduplicates_listing(tracker, app_config):
    result = import_jobs([posting(job_url=FORM, apply_url=None), posting(apply_url=None)], tracker, app_config)
    assert result['newly_imported'] == 1
    assert result['duplicate'] == 1
    row = tracker.get_job_by_url(LISTING)
    assert row['job_url'] == LISTING
    assert row['apply_url'] == FORM
    assert job_application_url(row) == FORM


@pytest.mark.parametrize('invalid', [
    'https://example.test/fixtureco/jobs/1001',
    'https://job-boards.greenhouse.io/otherco/jobs/1001',
    'https://job-boards.greenhouse.io/fixtureco/jobs/9999',
    'http://job-boards.greenhouse.io/fixtureco/jobs/1001',
])
def test_mismatched_form_route_is_not_imported_or_eligible(invalid, tracker, app_config):
    job = posting(apply_url=invalid)
    result = import_jobs([job], tracker, app_config)
    assert result['errors'] == 1
    assert tracker.get_job_by_url(LISTING) is None
    eligible, reason = _submission_eligibility(job, app_config)
    assert eligible is None and 'same approved Greenhouse' in reason


def test_reimport_never_replaces_existing_form_route_or_history(tracker, app_config):
    import_jobs([posting()], tracker, app_config)
    row = tracker.get_job_by_url(LISTING)
    tracker.update_job(row['id'], 'confirmed_submitted', reason='Existing receipt')
    before = tracker.get_job_by_url(LISTING)
    audit = tracker._con.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
    import_jobs([posting(apply_url=LISTING)], tracker, app_config)
    after = tracker.get_job_by_url(LISTING)
    assert after['apply_url'] == FORM
    assert after['status'] == before['status']
    assert after['applied_at'] == before['applied_at']
    assert tracker._con.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0] == audit


def test_application_route_change_invalidates_approval_before_writes(
        tracker, app_config, make_job, manifest_factory):
    job = make_job(job_url=LISTING, apply_url=FORM)
    manifest = manifest_factory(tracker, [job])
    tracker._con.execute('UPDATE applications SET apply_url=? WHERE id=?', (LISTING, job['id']))
    tracker._con.commit()
    changed = tracker.get_job_by_url(LISTING)
    before = tracker.db_path.read_bytes()
    with pytest.raises(AuthorizationError, match='jobs'):
        validate_authorization(manifest, [job['id']], app_config, [changed], tracker.db_path)
    assert tracker.db_path.read_bytes() == before
