"""Isolation regressions using the real eligibility, dispatcher, adapter and guard."""
import pytest

from auto_apply.authorization import AuthorizationError, validate_authorization
from auto_apply.orchestrator import is_eligible, run_unattended_batch, score_job


def run(tracker, job, manifest):
    run_unattended_batch(db_path=tracker.db_path, job_ids=[job['id']], auth_file=str(manifest))


def assert_no_attempt(tracker, requests, job):
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'paused'
    assert not [item for item in requests if item[0] == 'POST']
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 0


@pytest.mark.parametrize('extra,forbidden', [
    ('<fieldset><legend>Gender</legend><label><input name="gender" type="radio" value="male" checked>Male</label><label><input name="gender" type="radio" value="female">Female</label></fieldset>', 'male'),
    ('<label for="q">Desired salary</label><input id="q" name="q" value="99999">', '99999'),
    ('<label for="q">Other information</label><textarea id="q" name="q">Fabricated</textarea>', 'Fabricated'),
    ('<label for="q">Work location</label><select id="q" name="q"><option selected>Germany</option></select>', 'Germany'),
    ('<label><input name="marketing" type="checkbox" value="agree" checked>Marketing consent</label>', 'agree'),
    ('<fieldset><legend>Relocation</legend><label><input name="move" type="radio" value="relocate" checked>Yes</label></fieldset>', 'relocate'),
    ('<fieldset><legend>Gender</legend><label><input name="gender" style="display:none" type="radio" value="male" checked>Male</label></fieldset>', 'male'),
])
def test_optional_unverified_defaults_are_not_sent(extra, forbidden, tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]['extra'] = extra
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    body = next(item[2] for item in fixture_browser[1] if item[0] == 'POST')
    assert forbidden not in body


@pytest.mark.parametrize('extra,expected', [
    ('<label for="gender">Gender</label><select id="gender" name="gender" required><option selected>Male</option><option>Prefer not to answer</option></select>', 'Prefer not to answer'),
    ('<fieldset><legend>Gender *</legend><label><input name="gender" type="radio" checked required>Male</label><label><input name="gender" type="radio">Prefer not to answer</label></fieldset>', 'on'),
    ('<label for="q">What do you identify as?</label><select id="q" name="q" required><option selected>Male</option><option>Female</option><option>Other/Prefer not to disclose</option></select>', 'Other/Prefer not to disclose'),
])
def test_required_nondisclosure_without_value_attributes(extra, expected, tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]['extra'] = extra
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    body = next(item[2] for item in fixture_browser[1] if item[0] == 'POST')
    assert expected in body


def test_required_eeo_reuses_exact_saved_fact_without_nondisclosure(tracker, make_job, manifest_factory, fixture_browser, app_config):
    fixture_browser[0]['extra'] = '<label for="q">Gender</label><select id="q" name="q" required><option>Female</option><option>Male</option></select>'
    app_config['application_answers'] = {'Gender': 'Female'}
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    assert 'Female' in next(item[2] for item in fixture_browser[1] if item[0] == 'POST')


def test_optional_eeo_stays_blank_even_with_saved_fact(tracker, make_job, manifest_factory, fixture_browser, app_config):
    fixture_browser[0]['extra'] = '<label for="q">Gender</label><select id="q" name="q"><option selected>Male</option><option>Female</option></select>'
    app_config['application_answers'] = {'Gender': 'Female'}
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    body = next(item[2] for item in fixture_browser[1] if item[0] == 'POST')
    assert 'name="q"' not in body


def test_required_eeo_without_authorized_choice_pauses(tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]['extra'] = '<fieldset><legend>Gender *</legend><label><input name="gender" type="radio" value="male" required checked>Male</label></fieldset>'
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert_no_attempt(tracker, fixture_browser[1], job)


@pytest.mark.parametrize('missing', ['name', 'email'])
def test_basic_prefill_cannot_replace_missing_profile_fact(missing, tracker, make_job, manifest_factory, fixture_browser, app_config):
    app_config['profile'].pop(missing)
    field = 'first_name' if missing == 'name' else 'email'
    fixture_browser[0]['extra'] = f'<script>document.getElementById("{field}").value="unverified";</script>'
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert_no_attempt(tracker, fixture_browser[1], job)


@pytest.mark.parametrize('field,value', [('email', 'other@example.test'), ('phone', '123'), ('q', 'changed')])
def test_changed_approved_values_pause_before_reservation(field, value, tracker, make_job, manifest_factory, fixture_browser, monkeypatch):
    import auto_apply.adapters.greenhouse as adapter
    fixture_browser[0]['extra'] = '<label for="q">Optional unknown</label><input id="q" name="q">'
    original = adapter.handle_challenge
    calls = 0
    def change(page, unattended=False):
        nonlocal calls
        calls += 1
        result = original(page, unattended=unattended)
        if calls == 2:
            page.locator(f'#{field}').fill(value)
        return result
    monkeypatch.setattr(adapter, 'handle_challenge', change)
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert_no_attempt(tracker, fixture_browser[1], job)


@pytest.mark.parametrize('country', ['United States', 'U.S.', 'UK', 'EU', 'Germany', 'India or Germany'])
def test_india_scope_cannot_answer_foreign_work_question(country, tracker, make_job, manifest_factory, fixture_browser, app_config):
    question = f'Are you authorized to work in {country}?'
    fixture_browser[0]['extra'] = f'<label for="q">{question}</label><select id="q" name="q" required><option selected>Yes</option><option>No</option></select>'
    app_config['application_answers'] = {question: {'value': 'Yes', 'country': 'India', 'fact': 'work_authorization'}}
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert_no_attempt(tracker, fixture_browser[1], job)


@pytest.mark.parametrize('fact,template', [
    ('citizenship', 'Are you a citizen of {}?'),
    ('permanent_residency', 'Are you a permanent resident of {}?'),
    ('work_authorization', 'Are you authorized to work in {}?'),
    ('visa_sponsorship', 'Will you require visa sponsorship to work in {}?'),
])
@pytest.mark.parametrize('country', ['U.S.', 'UK', 'EU', 'Germany', 'India and Germany', 'Canada', 'Japan'])
def test_each_legal_fact_requires_positive_country_compatibility(fact, template, country):
    from auto_apply.adapters.greenhouse import _scoped_legal_answer
    assert not _scoped_legal_answer(template.format(country), {'value': 'Yes', 'country': 'India', 'fact': fact})


@pytest.mark.parametrize('fact,question', [
    ('citizenship', 'Are you an Indian citizen?'),
    ('permanent_residency', 'Are you a permanent resident of India?'),
    ('work_authorization', 'Are you legally authorized to work in India?'),
    ('visa_sponsorship', 'Will you require visa sponsorship to work in India?'),
])
def test_scoped_india_facts_are_reused(fact, question, tracker, make_job, manifest_factory, fixture_browser, app_config):
    fixture_browser[0]['extra'] = f'<label for="q">{question}</label><select id="q" name="q" required><option value="">Select</option><option>Yes</option><option>No</option></select>'
    app_config['application_answers'] = {question: {'value': 'Yes', 'country': 'India', 'fact': fact}}
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'


def test_authorization_is_not_citizenship():
    from auto_apply.adapters.greenhouse import _scoped_legal_answer
    assert not _scoped_legal_answer('Are you an Indian citizen?', {'value': 'Yes', 'country': 'India', 'fact': 'work_authorization'})


@pytest.mark.parametrize('existing_record', [True, False])
def test_stored_india_authorization_is_reused_without_reasking(existing_record, tracker, make_job, manifest_factory, fixture_browser, app_config):
    question = 'Are you legally authorized to work in India?'
    fixture_browser[0]['extra'] = f'<label for="q">{question}</label><select id="q" name="q" required><option value="">Select</option><option>Yes</option></select>'
    if existing_record:
        app_config['application_answers'] = {question: {'value':'Yes','country':'India'}}
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'


def test_stored_work_authorization_cannot_supply_citizenship(tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]['extra'] = '<label for="q">Are you an Indian citizen?</label><select id="q" name="q" required><option value="">Select</option><option>Yes</option></select>'
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert_no_attempt(tracker, fixture_browser[1], job)


def test_profile_override_change_invalidates_approval(tracker, make_job, manifest_factory, app_config, monkeypatch, tmp_path):
    job = make_job()
    manifest = manifest_factory(tracker, [job])
    monkeypatch.setenv('AUTO_APPLY_PROFILE_DIR', str(tmp_path / 'different-profile'))
    with pytest.raises(AuthorizationError, match='browser_profile'):
        validate_authorization(manifest, [job['id']], app_config, [job], tracker.db_path)


def test_resolved_profile_alias_retains_binding(tracker, make_job, manifest_factory, app_config, monkeypatch, tmp_path):
    selected = tmp_path / 'profile'
    selected.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(selected, target_is_directory=True)
    job = make_job()
    manifest = manifest_factory(tracker, [job])
    monkeypatch.setenv('AUTO_APPLY_PROFILE_DIR', str(alias))
    assert validate_authorization(manifest, [job['id']], app_config, [job], tracker.db_path)


def test_profile_change_before_dispatch_does_not_launch_browser(tracker, make_job, manifest_factory, app_config, monkeypatch, tmp_path):
    import auto_apply.orchestrator as orchestrator
    original = orchestrator.execute_application_automated
    def changed(*args, **kwargs):
        monkeypatch.setenv('AUTO_APPLY_PROFILE_DIR', str(tmp_path / 'other'))
        return original(*args, **kwargs)
    monkeypatch.setattr(orchestrator, 'execute_application_automated', changed)
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert not (tmp_path / 'other').exists()
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 0


def test_manual_resume_accepts_explicit_new_required_answer(tracker, make_job, manifest_factory, fixture_browser, monkeypatch):
    from auto_apply.orchestrator import run_resume_job
    import auto_apply.adapters.greenhouse as adapter
    fixture_browser[0]['extra'] = '<label for="q">Required portfolio explanation</label><input id="q" name="q" required>'
    job = make_job()
    manifest = manifest_factory(tracker, [job])
    run(tracker, job, manifest)
    assert_no_attempt(tracker, fixture_browser[1], job)
    original = adapter.handle_challenge
    active = []
    def capture(page, unattended=False):
        active[:] = [page]
        return original(page, unattended=unattended)
    def answer(prompt):
        if 'Press Enter' in prompt:
            active[0].locator('#q').fill('Explicit human answer in isolated fixture')
            return ''
        return 'submit'
    monkeypatch.setattr(adapter, 'handle_challenge', capture)
    monkeypatch.setattr('builtins.input', answer)
    run_resume_job(job['id'], auth_file=str(manifest), db_path=tracker.db_path)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 1


def test_new_optional_answer_after_preparation_is_unverified(tracker, make_job, manifest_factory, fixture_browser, monkeypatch):
    import auto_apply.adapters.greenhouse as adapter
    original = adapter.handle_challenge
    calls = 0
    def change(page, unattended=False):
        nonlocal calls
        calls += 1
        if calls == 2:
            page.locator('form').evaluate('el => { const input=document.createElement("input"); input.name="new_answer"; input.value="unverified"; el.append(input); }')
        return original(page, unattended=unattended)
    monkeypatch.setattr(adapter, 'handle_challenge', change)
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert_no_attempt(tracker, fixture_browser[1], job)


def test_optional_custom_default_pauses(tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]['extra'] = '<div role="combobox" aria-label="Unknown optional selection" aria-valuetext="Unverified default">Default</div>'
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert_no_attempt(tracker, fixture_browser[1], job)


def test_native_aria_radio_group_uses_saved_question(tracker, make_job, manifest_factory, fixture_browser, app_config):
    fixture_browser[0]['extra'] = '<div role="radiogroup" aria-label="Are you legally authorized to work in India?" aria-required="true"><label><input name="auth" type="radio" value="yes" required>Yes</label><label><input name="auth" type="radio" value="no">No</label></div>'
    question = 'Are you legally authorized to work in India?'
    app_config['application_answers'] = {question: {'value':'Yes', 'country':'India', 'fact':'work_authorization'}}
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'


def test_mixed_qualification_gap_stops_real_dispatch(tracker, make_job, manifest_factory, fixture_browser):
    description = 'Required: Django and Python; AWS preferred.'
    fixture_browser[0]['description'] = description
    job = make_job(description=description)
    before = tracker.db_path.read_bytes()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'pending'
    assert fixture_browser[1] == []
    assert tracker.db_path.read_bytes() == before


@pytest.mark.parametrize('mutation', ['selection', 'value', 'resume'])
def test_changed_radio_or_resume_is_detected(tracker, make_job, manifest_factory, fixture_browser, monkeypatch, mutation):
    import auto_apply.adapters.greenhouse as adapter
    fixture_browser[0]['extra'] = '<fieldset><legend>Gender *</legend><label><input name="gender" type="radio" value="male" required>Male</label><label><input id="decline" name="gender" type="radio" value="decline">Prefer not to answer</label><label><input id="female" name="gender" type="radio" value="female">Female</label></fieldset>'
    original = adapter.handle_challenge
    calls = 0
    def change(page, unattended=False):
        nonlocal calls
        calls += 1
        if calls == 2:
            if mutation == 'selection':
                page.locator('#female').set_checked(True)
            elif mutation == 'value':
                page.locator('#decline').evaluate('el => el.value="male"')
            else:
                page.locator('#resume').evaluate('el => { const data=new DataTransfer(); data.items.add(new File(["wrong bytes"], "candidate.pdf")); el.files=data.files; }')
        return original(page, unattended=unattended)
    monkeypatch.setattr(adapter, 'handle_challenge', change)
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert_no_attempt(tracker, fixture_browser[1], job)


@pytest.mark.parametrize('description', [
    'Mandatory: Python and Django; AWS preferred.',
    'Preferred: AWS; required: Django and Python.',
    'Required: Python, Django. Preferred: AWS.',
    'Django required, Python preferred.',
    'Required: Python and mandatory Django and preferred AWS.',
    'Django required and Python preferred.',
])
def test_preferred_clause_cannot_hide_mandatory_gap(description, app_config):
    job = {'title': 'Python Developer', 'location': 'India', 'description': description,
           'experience': '1-2 years', 'application_open': 'Open'}
    eligible, reason = is_eligible(job, app_config, score_job(job, app_config))
    assert eligible is None
    assert 'Django' in reason


def test_preferred_clause_cannot_hide_mandatory_experience(app_config):
    job = {'title': 'Python Developer', 'location': 'India',
           'description': 'Requires 5 years of backend experience; AWS preferred.',
           'experience': '1-2 years', 'application_open': 'Open'}
    assert is_eligible(job, app_config, score_job(job, app_config))[0] is False


def test_total_experience_does_not_establish_professional_tool_tenure(app_config):
    job = {'title': 'Python Developer', 'location': 'India',
           'description': 'Required: 2 years of professional Python experience.',
           'experience': '1-2 years', 'application_open': 'Open'}
    eligible, reason = is_eligible(job, app_config, score_job(job, app_config))
    assert eligible is None
    assert 'tool-specific tenure' in reason
    app_config['screening']['professional_experience_years'] = {'Python': 2}
    assert is_eligible(job, app_config, score_job(job, app_config))[0] is True


@pytest.mark.parametrize('requirement', ['Required: Python (2 years).', 'Required: 2 years of Python development.', "Required: 2 years' professional Python experience."])
def test_tool_tenure_phrases_cannot_use_total_experience(requirement, app_config):
    job = {'title': 'Python Developer', 'location': 'India', 'description': requirement,
           'experience': '1-2 years', 'application_open': 'Open'}
    eligible, reason = is_eligible(job, app_config, score_job(job, app_config))
    assert eligible is None
    assert 'tool-specific tenure' in reason
