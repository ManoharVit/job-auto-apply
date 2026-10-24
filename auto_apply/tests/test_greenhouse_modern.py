"""Observed renderer structures with synthetic HTTP, candidate data and profiles.

These are isolated integration tests, not live employer submission evidence.
"""
import json
import html
import os
from urllib.parse import urlparse
from unittest.mock import Mock

import pytest

from auto_apply.adapters.greenhouse import _submission_contract
from auto_apply.orchestrator import run_unattended_batch
from auto_apply.requirements import description_text, mandatory_gaps
from auto_apply.settings import greenhouse_identity


def select_field(identifier, label, choices, required=True, default=None):
    selected = f'<span class="select__single-value">{default}</span>' if default else ''
    proxy = default or ''
    return f'''<div class="select__container">
        <label for="{identifier}">{label}{'*' if required else ''}</label>
        <div class="select__control"><div class="select__value-container">{selected}
        <input class="select__input" id="{identifier}" role="combobox" aria-required="{str(required).lower()}"
          data-options='{html.escape(json.dumps(choices), quote=True)}'></div>
        <button type="button" aria-label="Clear selection" onclick="clearChoice('{identifier}')">Clear</button></div>
        <input class="remix-css-test-requiredInput" aria-hidden="true" tabindex="-1"
          {'required' if required else ''} value="{proxy}" style="height:0;opacity:0">
        </div>'''


@pytest.fixture
def modern_form(fixture_browser):
    scenario = {'extra': '', 'job_id': None, 'board': 'TestCo', 'wrong_confirmation': False,
                'generic_confirmation': False, 'old_confirmation': False, 'reject': False,
                'submit_path': None, 'confirmation_path': None, 'description': None,
                'json_errors': False, 'consume_response': True, 'retry_submission': False,
                'async_upload': False, 'upload_status': 204, 'upload_wrong_bytes': False,
                'upload_no_request': False, 'upload_wrong_name': False,
                'upload_progress': False, 'upload_error': False, 'submit_wrong_resume': False,
                'remove_proxy_on_select': False}

    def handle(route):
        request = route.request
        if '/upload/resume' in request.url:
            route.fulfill(status=scenario['upload_status'], body='')
            return True
        identity = greenhouse_identity(request.url)
        identifier = identity[1] if identity else urlparse(request.url).path.rstrip('/').split('/')[-1]
        if request.method == 'POST':
            status = 422 if scenario['reject'] else 200
            route.fulfill(status=status, content_type='application/json',
                          body=json.dumps({'errors': ['rejected']} if status == 422 or scenario['json_errors'] else {'accepted': True}))
            return True
        if '/confirmation/' in request.url or urlparse(request.url).path.endswith('/confirmation'):
            message = 'Applied' if scenario['generic_confirmation'] else 'Application received'
            route.fulfill(status=200, content_type='text/html', body=(
                f'<div class="confirmation"><div class="confirmation__content" data-job-id="{identifier}">{message}</div></div>'
            ))
            return True
        context = {'jobPostId': scenario['job_id'] or int(identifier), 'urlToken': scenario['board'],
                   'jobPost': {'title': 'Python Developer'},
                   'submitPath': scenario['submit_path'] or (f'/embed/{identity[0]}/jobs/{identifier}' if identity else f'/submit/{identifier}'),
                   'confirmationPath': scenario['confirmation_path'] or (f'/embed/job_app/confirmation?for={identity[0]}&token={identifier}' if identity else f'/confirmation/{identifier}')}
        description = scenario['description'] or 'Python and FastAPI backend development.'
        old = '<div class="confirmation"><div class="confirmation__content">Application received</div></div>' if scenario['old_confirmation'] else ''
        next_id = '9999' if scenario['wrong_confirmation'] else identifier
        next_path = context['confirmationPath'] if identity and not scenario['wrong_confirmation'] else f'/confirmation/{next_id}'
        html = f'''<html><head><meta charset="utf-8"></head><body>
          {'<p>LOCAL SIMULATION. Synthetic candidate. No employer application.</p>' if os.environ.get('AUTO_APPLY_SHOW_LOCAL_FIXTURE') == '1' else ''}
          <h1>Python Developer</h1><div class="job__description">{description}</div>{old}
          <form id="application-form" class="application--form" method="get" action="/jobs/{identifier}">
          <label for="first_name">First Name*</label><input id="first_name" aria-required="true">
          <label for="last_name">Last Name*</label><input id="last_name" aria-required="true">
          <label for="email">Email*</label><input id="email" aria-required="true">
          <label for="phone">Phone*</label><input id="phone" aria-required="true">
          <div class="{'file-upload' if scenario['async_upload'] else ''}" role="group" aria-labelledby="upload-label-resume" aria-required="true">
            <div id="upload-label-resume">Resume/CV*</div><label for="resume">Attach</label>
            <input id="resume" type="file" style="display:none"></div>
          {scenario['extra']}<button type="submit">Submit application</button></form>
          <script>
          window.__remixRouter = {{state:{{loaderData:{{job:{json.dumps(context)}}}}}}};
          window.uploadedResume = {{}};
          if ({json.dumps(scenario['async_upload'])}) {{
            document.getElementById('resume').onchange = event => {{
              const input = event.target, file = input.files[0], group = input.parentElement;
              const data = new FormData();
              data.append('key', 'synthetic/'+file.name);
              data.append('file', {"new File(['different resume'], file.name, {type:'application/pdf'})" if scenario['upload_wrong_bytes'] else 'file'});
              const request = new XMLHttpRequest();
              request.onloadend = () => {{
                group.querySelectorAll('[role=progressbar]').forEach(el=>el.remove());
                const name = document.createElement('div'); name.className = 'file-upload__filename';
                name.textContent = {"'wrong-resume.pdf'" if scenario['upload_wrong_name'] else 'file.name'};
                group.appendChild(name);
                window.uploadedResume = {{resume_url:location.origin+'/upload/resume/synthetic/'+file.name,
                  resume_url_filename:file.name}};
                {"group.insertAdjacentHTML('beforeend', '<div role=progressbar>Pending</div>');" if scenario['upload_progress'] else ''}
                {"group.insertAdjacentHTML('beforeend', '<p class=helper-text--error>Rejected file</p>');" if scenario['upload_error'] else ''}
              }};
              request.open('POST', '/upload/resume');
              {'request.onloadend();' if scenario['upload_no_request'] else 'request.send(data);'}
              input.remove();
            }};
          }}
          function clearChoice(id) {{
            let input=document.getElementById(id), parent=input.closest('.select__container');
            parent.querySelectorAll('.select__single-value').forEach(el=>el.remove());
            parent.querySelector('input[aria-hidden=true]').value=''; input.value='';
          }}
          document.querySelectorAll('.select__input').forEach(input=>{{
            function menu() {{
              document.querySelectorAll('[role=listbox]').forEach(el=>el.remove());
              let list=document.createElement('div'); list.id='react-select-'+input.id+'-listbox';
              list.setAttribute('role','listbox');
              let choices=JSON.parse(input.dataset.options);
              if(input.dataset.searchOptions && input.value)choices=JSON.parse(input.dataset.searchOptions);
              if(!choices.length)list.textContent='No options';
              choices.forEach(label=>{{
                let option=document.createElement('div'); option.setAttribute('role','option'); option.textContent=label;
                option.onclick=()=>{{clearChoice(input.id); let selected=document.createElement('span');
                  selected.className='select__single-value'; selected.textContent=label;
                  input.parentElement.appendChild(selected);
                  const proxy=input.closest('.select__container').querySelector('input[aria-hidden=true]');
                  {'proxy.remove();' if scenario['remove_proxy_on_select'] else 'proxy.value=label;'}
                  list.remove();}}; list.appendChild(option);
              }}); input.closest('.select__container').appendChild(list);
            }}
            input.addEventListener('click',menu);
            input.addEventListener('input',menu);
            input.addEventListener('keydown',event=>{{if(event.key==='Escape')document.querySelectorAll('[role=listbox]').forEach(el=>el.remove());}});
          }});
          document.getElementById('application-form').onsubmit=async event=>{{
            event.preventDefault(); let values={{}};
            ['first_name','last_name','email','phone'].forEach(id=>values[id]=document.getElementById(id).value);
            Object.assign(values, window.uploadedResume);
            {"values.resume_url+='unapproved';" if scenario['submit_wrong_resume'] else ''}
            document.querySelectorAll('.select__input').forEach(input=>{{
              values[input.id]=input.closest('.select__container').querySelector('.select__single-value')?.textContent || '';
            }});
            let response=await fetch(window.__remixRouter.state.loaderData.job.submitPath,
              {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{job_application:values}})}});
            {'await response.text();' if scenario['consume_response'] else ''}
            {"try {await fetch(window.__remixRouter.state.loaderData.job.submitPath, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({job_application:values})});} catch (_) {}" if scenario['retry_submission'] else ''}
            if(response.ok)location.href='{next_path}';
          }};
          </script></body></html>'''
        route.fulfill(status=200, content_type='text/html', body=html)
        return True

    fixture_browser[0]['request_handler'] = handle
    return scenario


def execute(tracker, job, manifest_factory):
    manifest = manifest_factory(tracker, [job])
    run_unattended_batch(db_path=tracker.db_path, job_ids=[job['id']], auth_file=str(manifest))


def assert_paused(tracker, job, fixture_browser):
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'paused'
    assert not [item for item in fixture_browser[1] if item[0] == 'POST']
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 0


def test_modern_native_fields_hidden_resume_and_json_confirmation(
        modern_form, app_config, tracker, make_job, manifest_factory, fixture_browser):
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 1


def test_async_resume_upload_unmounts_input_and_binds_exact_bytes_and_payload(
        modern_form, tracker, make_job, manifest_factory, fixture_browser):
    modern_form['async_upload'] = True
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 1
    uploads = [r for r in fixture_browser[1] if r[0] == 'POST' and '/upload/' in r[1]]
    submissions = [r for r in fixture_browser[1] if r[0] == 'POST' and '/submit/' in r[1]]
    assert len(uploads) == len(submissions) == 1
    body = json.loads(submissions[0][2])['job_application']
    assert body['resume_url'] == 'http://127.0.0.1:9876/upload/resume/synthetic/candidate.pdf'
    assert body['resume_url_filename'] == 'candidate.pdf'


@pytest.mark.parametrize('update', [
    {'upload_status': 403}, {'upload_wrong_bytes': True}, {'upload_no_request': True},
    {'upload_wrong_name': True}, {'upload_progress': True}, {'upload_error': True},
])
def test_async_upload_cannot_succeed_from_filename_or_selection_alone(
        update, modern_form, tracker, make_job, manifest_factory, fixture_browser):
    modern_form.update(async_upload=True, **update)
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'failed'
    assert not [r for r in fixture_browser[1] if r[0] == 'POST' and '/submit/' in r[1]]
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 0


def test_completed_resume_removed_before_guard_pauses_without_attempt(
        modern_form, tracker, make_job, manifest_factory, fixture_browser, monkeypatch):
    import auto_apply.adapters.greenhouse as adapter
    modern_form['async_upload'] = True
    original = adapter.handle_challenge
    calls = 0
    def change(page, unattended=False):
        nonlocal calls
        calls += 1
        if calls == 2:
            page.locator('.file-upload__filename').evaluate('el=>el.remove()')
        return original(page, unattended=unattended)
    monkeypatch.setattr(adapter, 'handle_challenge', change)
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'paused'
    assert not [r for r in fixture_browser[1] if r[0] == 'POST' and '/submit/' in r[1]]
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 0


def test_verified_upload_does_not_skip_unknown_required_questions(
        modern_form, tracker, make_job, manifest_factory, fixture_browser):
    modern_form.update(async_upload=True, extra='<label for="unknown">Unknown required fact*</label><input id="unknown" required>')
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'paused'
    assert 'Unknown required fact' in tracker.get_job_by_url(job['job_url'])['error_message']
    assert not [r for r in fixture_browser[1] if r[0] == 'POST' and '/submit/' in r[1]]
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 0


def test_empty_optional_upload_is_not_cleared_or_allowed_to_detach_other_fields(
        modern_form, tracker, make_job, manifest_factory, fixture_browser):
    modern_form.update(async_upload=True, extra='''
      <div class="file-upload" role="group" aria-labelledby="upload-label-cover_letter">
      <div id="upload-label-cover_letter">Cover Letter</div><label for="cover_letter">Attach</label>
      <input id="cover_letter" type="file" onchange="this.remove()"></div>
      <label for="nda">Please review this agreement*</label><input id="nda" required>''')
    job = make_job()
    execute(tracker, job, manifest_factory)
    row = tracker.get_job_by_url(job['job_url'])
    assert row['status'] == 'paused'
    assert 'Please review this agreement' in row['error_message']
    assert 'TimeoutError' not in row['error_message']
    assert not [r for r in fixture_browser[1] if r[0] == 'POST' and '/submit/' in r[1]]
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 0


def test_changed_resume_payload_is_blocked_and_reservation_is_not_retried(
        modern_form, tracker, make_job, manifest_factory, fixture_browser):
    modern_form.update(async_upload=True, submit_wrong_resume=True)
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'unconfirmed'
    assert not [r for r in fixture_browser[1] if r[0] == 'POST' and '/submit/' in r[1]]
    assert tracker._con.execute('SELECT outcome FROM auto_apply_attempts').fetchone()[0] == 'ambiguous'


def test_exact_react_select_choice_and_optional_demographic_blank(
        modern_form, app_config, tracker, make_job, manifest_factory, fixture_browser):
    modern_form['extra'] = select_field('citizen', 'Are you an Indian citizen?', ['Yes', 'No']) + select_field(
        'gender', 'Gender', ['Male', 'Female', 'Decline To Self Identify'], required=False, default='Male')
    app_config['application_answers'] = {'Are you an Indian citizen?': {'value': 'Yes', 'country': 'India', 'fact': 'citizenship'}}
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    data = json.loads(next(item[2] for item in fixture_browser[1] if item[0] == 'POST'))['job_application']
    assert data['citizen'] == 'Yes'
    assert data['gender'] == ''


def test_required_react_demographic_uses_offered_nondisclosure(
        modern_form, tracker, make_job, manifest_factory, fixture_browser):
    modern_form['extra'] = select_field('gender', 'Gender', ['Male', 'Female', 'Other/Prefer not to disclose'])
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    assert 'Other/Prefer not to disclose' in next(item[2] for item in fixture_browser[1] if item[0] == 'POST')


def test_generic_identity_question_is_demographic_only_when_options_establish_it(
        modern_form, tracker, make_job, manifest_factory, fixture_browser):
    modern_form['extra'] = select_field('q', 'What do you identify as?', ['Male', 'Female', 'Other/Prefer not to disclose'])
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    assert 'Other/Prefer not to disclose' in next(item[2] for item in fixture_browser[1] if item[0] == 'POST')


def test_search_select_requires_an_actual_exact_option_click(
        modern_form, app_config, tracker, make_job, manifest_factory, fixture_browser):
    field = select_field('city', 'Location (City)', [])
    field = field.replace('data-options=', 'data-search-options=\'["Synthetic City, India"]\' data-options=')
    modern_form['extra'] = field
    app_config['application_answers'] = {'Location (City)': 'Synthetic City, India'}
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    assert 'Synthetic City, India' in next(item[2] for item in fixture_browser[1] if item[0] == 'POST')


def test_selected_option_removing_visible_proxy_does_not_shift_later_controls(
        modern_form, app_config, tracker, make_job, manifest_factory, fixture_browser):
    question = 'Are you currently or have you ever been employed by Rubrik or contracted to provide services to Rubrik?'
    field = select_field('prior_employer', question, ['Yes', 'No'])
    field = field.replace('style="height:0;opacity:0"', 'style="opacity:0;position:absolute;width:100%"')
    modern_form.update(remove_proxy_on_select=True, extra=field + '''
      <label for="employer">What is the name of your current employer?*</label><input id="employer" required>
      <label for="nda">Please review this agreement*</label><input id="nda" required>''')
    app_config['application_answers'] = {question: 'No', 'What is the name of your current employer?': 'Synthetic Employer'}
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert_paused(tracker, job, fixture_browser)
    row = tracker.get_job_by_url(job['job_url'])
    assert 'Please review this agreement' in row['error_message']
    assert 'TimeoutError' not in row['error_message']
    assert 'current employer' not in row['error_message']


def test_required_proxy_removed_at_end_of_form_does_not_stall_submission(
        modern_form, app_config, tracker, make_job, manifest_factory, fixture_browser):
    question = 'Known screening question'
    field = select_field('known', question, ['Yes', 'No'])
    modern_form.update(remove_proxy_on_select=True, extra=field.replace(
        'style="height:0;opacity:0"', 'style="opacity:0;position:absolute;width:100%"'))
    app_config['application_answers'] = {question: 'No'}
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 1
    payload = json.loads(next(r[2] for r in fixture_browser[1] if r[0] == 'POST'))
    assert payload['job_application']['known'] == 'No'


@pytest.mark.parametrize('question', ['Unknown required answer', 'Are you authorized to work in the UK?'])
def test_unknown_or_foreign_prefilled_react_select_does_not_supply_provenance(
        question, modern_form, app_config, tracker, make_job, manifest_factory, fixture_browser):
    modern_form['extra'] = select_field('q', question, ['Yes', 'No'], default='Yes')
    if question.startswith('Are you'):
        app_config['application_answers'] = {question: {'value': 'Yes', 'country': 'India', 'fact': 'work_authorization'}}
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert_paused(tracker, job, fixture_browser)


@pytest.mark.parametrize('question,default', [('Country', '+91'), ('Are you authorized to work in the UK?', 'Yes')])
def test_required_unclearable_prefill_reaches_review_without_becoming_approved(
        question, default, modern_form, app_config, tracker, make_job, manifest_factory, fixture_browser):
    field = select_field('q', question, [default, 'Other'], default=default)
    field = field.replace('<button type="button" aria-label="Clear selection" onclick="clearChoice(\'q\')">Clear</button>', '')
    modern_form['extra'] = field
    if question != 'Country':
        app_config['application_answers'] = {question: {'value': 'Yes', 'country': 'India', 'fact': 'work_authorization'}}
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert_paused(tracker, job, fixture_browser)
    assert 'answer is not verified' in tracker.get_job_by_url(job['job_url'])['error_message']


def test_unclearable_required_prefill_can_only_submit_after_explicit_manual_review(
        modern_form, tracker, make_job, manifest_factory, fixture_browser, monkeypatch):
    from auto_apply.orchestrator import run_resume_job
    field = select_field('q', 'Country', ['+91', 'Other'], default='+91')
    modern_form['extra'] = field.replace('<button type="button" aria-label="Clear selection" onclick="clearChoice(\'q\')">Clear</button>', '')
    job = make_job()
    manifest = manifest_factory(tracker, [job])
    run_unattended_batch(db_path=tracker.db_path, job_ids=[job['id']], auth_file=str(manifest))
    assert_paused(tracker, job, fixture_browser)
    decisions = iter(['', 'submit'])
    monkeypatch.setattr('builtins.input', lambda _: next(decisions))
    run_resume_job(job['id'], auth_file=str(manifest), db_path=tracker.db_path)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 1


def test_duplicate_react_labels_remain_ambiguous(
        modern_form, app_config, tracker, make_job, manifest_factory, fixture_browser):
    modern_form['extra'] = select_field('q1', 'University', ['Synthetic School']) + select_field('q2', 'University', ['Synthetic School'])
    app_config['application_answers'] = {'University': 'Synthetic School'}
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert_paused(tracker, job, fixture_browser)


@pytest.mark.parametrize('update', [
    {'job_id': 9999}, {'submit_path': '/submit/9999'},
    {'submit_path': 'https://example.test/submit/1001'},
    {'confirmation_path': '/confirmation/9999'}, {'old_confirmation': True},
])
def test_wrong_renderer_context_paths_or_old_confirmation_pause_before_attempt(
        update, modern_form, tracker, make_job, manifest_factory, fixture_browser):
    modern_form.update(update)
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert_paused(tracker, job, fixture_browser)


@pytest.mark.parametrize('setting', ['wrong_confirmation', 'generic_confirmation'])
def test_modern_post_without_bound_dedicated_confirmation_remains_unconfirmed(
        setting, modern_form, tracker, make_job, manifest_factory):
    modern_form[setting] = True
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'unconfirmed'
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 1


def test_renderer_path_change_before_guard_pauses_without_attempt(
        modern_form, tracker, make_job, manifest_factory, fixture_browser, monkeypatch):
    import auto_apply.adapters.greenhouse as adapter
    original = adapter.handle_challenge
    calls = 0
    def change(page, unattended=False):
        nonlocal calls
        calls += 1
        if calls == 2:
            page.evaluate("window.__remixRouter.state.loaderData.job.submitPath='/submit/9999'")
        return original(page, unattended=unattended)
    monkeypatch.setattr(adapter, 'handle_challenge', change)
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert_paused(tracker, job, fixture_browser)


def test_json_errors_with_a_new_confirmation_are_not_confirmed(
        modern_form, tracker, make_job, manifest_factory):
    modern_form['json_errors'] = True
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'failed'
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 1


def test_navigation_without_consuming_json_body_finishes_without_hanging(
        modern_form, tracker, make_job, manifest_factory):
    import time
    modern_form['consume_response'] = False
    job = make_job()
    started = time.monotonic()
    execute(tracker, job, manifest_factory)
    assert time.monotonic() - started < 15
    # Browser versions can complete the response before navigation or cancel it.
    assert tracker.get_job_by_url(job['job_url'])['status'] in ('confirmed_submitted', 'unconfirmed')
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 1


def test_renderer_retry_cannot_send_a_second_submission_for_one_reservation(
        modern_form, tracker, make_job, manifest_factory, fixture_browser):
    modern_form['retry_submission'] = True
    job = make_job()
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    assert len([item for item in fixture_browser[1] if item[0] == 'POST']) == 1
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 1


def test_production_renderer_contract_accepts_only_the_same_board_job():
    url = 'https://job-boards.greenhouse.io/embed/job_app?for=fixtureco&token=1001'
    page = Mock(url=url)
    page.evaluate.return_value = [{'jobPostId': 1001, 'board': 'fixtureco', 'title': 'Python Developer',
        'submitPath': 'https://boards.greenhouse.io/embed/fixtureco/jobs/1001',
        'confirmationPath': '/embed/job_app/confirmation?for=fixtureco&token=1001'}]
    form = Mock()
    form.get_attribute.return_value = 'application--form'
    job = {'job_url': url, 'title': 'Python Developer'}
    result = _submission_contract(page, job, form, fixture=False)
    assert result['submit_url'].endswith('/1001')
    page.evaluate.return_value[0]['board'] = 'another'
    with pytest.raises(ValueError, match='board'):
        _submission_contract(page, job, form, fixture=False)


def test_explicit_same_job_provider_route_runs_through_dispatcher_adapter_and_guard(
        modern_form, tracker, make_job, manifest_factory, fixture_browser):
    fixture_browser[0]['intercept_greenhouse'] = True
    modern_form['board'] = 'fixtureco'
    listing = 'https://job-boards.greenhouse.io/fixtureco/jobs/1001'
    application = 'https://job-boards.greenhouse.io/embed/job_app?for=fixtureco&token=1001'
    job = make_job(job_url=listing, apply_url=application)
    execute(tracker, job, manifest_factory)
    assert tracker.get_job_by_url(listing)['status'] == 'confirmed_submitted'
    assert fixture_browser[1][0][1] == application
    assert all('greenhouse.io' in request[1] for request in fixture_browser[1])
    evidence = json.loads(tracker._con.execute('SELECT evidence FROM auto_apply_attempts').fetchone()[0])
    assert evidence['job_url'] == listing
    assert evidence['application_url'] == application


def test_encoded_api_description_preserves_entities_and_preferred_heading():
    text = description_text('&lt;p&gt;Python&amp;nbsp;required&lt;/p&gt;&lt;h3&gt;Nice-to-haves&lt;/h3&gt;&lt;p&gt;TypeScript&lt;/p&gt;')
    assert 'Python\xa0required' in text
    assert mandatory_gaps({'description': text}, ['Python']) == []
    assert mandatory_gaps({'description': text + '\nRust required'}, ['Python']) == ['Rust']
