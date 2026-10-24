"""Exact saved answers, integrity binding and personal-data test isolation."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from auto_apply.answer_memory import (
    AnswerMemoryError, application_answers, memory_integrity, preview_memory, read_memory,
)
from auto_apply.authorization import AuthorizationError, validate_authorization
from auto_apply.orchestrator import run_unattended_batch


@pytest.fixture
def qa_file(tmp_path, monkeypatch):
    path = tmp_path / 'qa.yaml'
    monkeypatch.setenv('AUTO_APPLY_ANSWERS', str(path))
    def write(*entries):
        path.write_text(yaml.safe_dump({'schema_version':1, 'questions':list(entries)},sort_keys=False))
        return path
    return write


def entry(**updates):
    return {'id':'Q001','category':'screening','question':'Portfolio explanation',
            'answer':'A truthful synthetic answer','reviewed':True,'reuse':'exact_question',
            'scope':{'countries':['India']}} | updates


def run(tracker, job, manifest):
    run_unattended_batch(db_path=tracker.db_path, job_ids=[job['id']], auth_file=str(manifest))


def no_attempt(tracker, job, fixture_browser):
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'paused'
    assert not [request for request in fixture_browser[1] if request[0]=='POST']
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0] == 0


def test_default_memory_disabled_in_tests(app_config, tmp_path, monkeypatch):
    import auto_apply.answer_memory as module
    monkeypatch.delenv('AUTO_APPLY_ANSWERS', raising=False)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    (tmp_path/'application_qa.yaml').write_text('BROKEN PERSONAL DATA MUST NOT BE READ')
    assert read_memory(app_config) == {'path':None,'sha256':'disabled','questions':[]}


def test_custom_configuration_has_no_implicit_personal_memory(tmp_path, monkeypatch):
    import auto_apply.answer_memory as module
    monkeypatch.delenv('AUTO_APPLY_ANSWERS', raising=False)
    monkeypatch.delenv('AUTO_APPLY_TEST_MODE', raising=False)
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    monkeypatch.setattr(module,'ROOT',tmp_path)
    (tmp_path/'application_qa.yaml').write_text('must not load')
    assert read_memory({})['path'] is None


def test_explicit_production_memory_is_rejected_in_test_mode(app_config, monkeypatch):
    from auto_apply.settings import ROOT
    monkeypatch.setenv('AUTO_APPLY_ANSWERS',str(ROOT/'application_qa.yaml'))
    with pytest.raises(AnswerMemoryError,match='temporary'):
        read_memory(app_config)


def test_explicit_missing_memory_fails_closed(app_config, tmp_path, monkeypatch):
    monkeypatch.setenv('AUTO_APPLY_ANSWERS',str(tmp_path/'missing.yaml'))
    with pytest.raises(AnswerMemoryError,match='missing'):
        read_memory(app_config)


@pytest.mark.parametrize('content', ['[]','null','{broken','schema_version: 2\nquestions: []'])
def test_invalid_file_fails_closed(content, qa_file, app_config):
    path = qa_file()
    path.write_text(content)
    with pytest.raises(AnswerMemoryError):
        read_memory(app_config)


@pytest.mark.parametrize('update', [
    {'reviewed':'true'}, {'id':''}, {'answer':{'invented':'data'}},
    {'scope':{'company':'TestCo'}}, {'scope':{'countries':[]}},
    {'reuse':'fuzzy'}, {'answer':None}, {'answer':'TODO'},
    {'answer':'[Unanswered]'},
    {'answer':float('nan')}, {'exact_labels':[]},
    {'answer_type':'number','answer':-1}, {'answer_type':'number','answer':True},
])
def test_invalid_entry_is_rejected(update, qa_file, app_config):
    qa_file(entry(**update))
    with pytest.raises(AnswerMemoryError):
        read_memory(app_config)


def test_duplicate_ids_rejected(qa_file, app_config):
    qa_file(entry(),entry())
    with pytest.raises(AnswerMemoryError,match='Duplicate'):
        read_memory(app_config)


def test_reviewed_exact_answer_reused_by_real_bot(qa_file, app_config, tracker, make_job, manifest_factory, fixture_browser):
    qa_file(entry())
    fixture_browser[0]['extra'] = '<label for="q">Portfolio explanation *</label><textarea id="q" name="q" required></textarea>'
    job = make_job()
    run(tracker,job,manifest_factory(tracker,[job]))
    assert tracker.get_job_by_url(job['job_url'])['status']=='confirmed_submitted'
    assert 'A truthful synthetic answer' in next(request[2] for request in fixture_browser[1] if request[0]=='POST')


@pytest.mark.parametrize('question', ['Explain authentication versus authorization in an API.', 'How do you handle data residency in a cloud application?'])
def test_technical_knowledge_is_distinct_from_candidate_legal_facts(question, qa_file, tracker, make_job, manifest_factory, fixture_browser):
    qa_file(entry(question=question,answer='Explicit human-reviewed technical explanation'))
    fixture_browser[0]['extra']=f'<label for="q">{question}</label><textarea id="q" name="q" required></textarea>'
    job=make_job()
    run(tracker,job,manifest_factory(tracker,[job]))
    assert tracker.get_job_by_url(job['job_url'])['status']=='confirmed_submitted'
    assert 'Explicit human-reviewed technical explanation' in next(request[2] for request in fixture_browser[1] if request[0]=='POST')


@pytest.mark.parametrize('question',['Describe your work authorization for Germany for this API role.', 'How is your work authorization in the U.S. relevant to this data job?'])
def test_technical_word_in_legal_question_does_not_remove_country_check(question, qa_file, tracker, make_job, manifest_factory, fixture_browser):
    qa_file(entry(question=question,answer='Yes'))
    fixture_browser[0]['extra']=f'<label for="q">{question}</label><textarea id="q" name="q" required></textarea>'
    job=make_job()
    run(tracker,job,manifest_factory(tracker,[job]))
    no_attempt(tracker,job,fixture_browser)


@pytest.mark.parametrize('updates', [{'reviewed':False},{'reuse':'manual_per_application'},{'reuse':'notes_only'}, {'exact_labels':['A different exact question']}])
def test_unreviewed_manual_notes_and_other_wording_pause(updates, qa_file, tracker, make_job, manifest_factory, fixture_browser):
    qa_file(entry(**updates))
    fixture_browser[0]['extra'] = '<label for="q">Portfolio explanation</label><textarea id="q" name="q" required>Unverified default</textarea>'
    job = make_job()
    run(tracker,job,manifest_factory(tracker,[job]))
    no_attempt(tracker,job,fixture_browser)


@pytest.mark.parametrize('scope,job_updates', [
    ({'countries':['India'],'companies':['OtherCo']},{}),
    ({'countries':['India'],'job_urls':['http://127.0.0.1:9876/jobs/9999']},{}),
])
def test_context_mismatch_pauses(scope, job_updates, qa_file, tracker, make_job, manifest_factory, fixture_browser):
    qa_file(entry(scope=scope))
    fixture_browser[0]['extra'] = '<label for="q">Portfolio explanation</label><input id="q" name="q" required>'
    job = make_job(**job_updates)
    run(tracker,job,manifest_factory(tracker,[job]))
    no_attempt(tracker,job,fixture_browser)


def test_country_scope_does_not_match_indiana_or_foreign_country(qa_file, app_config):
    qa_file(entry())
    for job in ({'country':'United States','location':'India'}, {'location':'Indiana'}, {'location':'Remote'}):
        assert application_answers(app_config,job)=={}
    assert 'portfolio explanation' in application_answers(app_config,{'country':'IN'})
    assert 'portfolio explanation' in application_answers(app_config,{'location':'Remote (India)'})


@pytest.mark.parametrize('country',['U.S.','UK','EU','Germany'])
def test_country_fact_from_memory_cannot_answer_foreign_question(country, qa_file, tracker, make_job, manifest_factory, fixture_browser):
    question=f'Are you authorized to work in {country}?'
    qa_file(entry(question=question,answer='Yes',country='India',fact='work_authorization'))
    fixture_browser[0]['extra']=f'<label for="q">{question}</label><select id="q" name="q" required><option value="">Select</option><option>Yes</option></select>'
    job=make_job()
    run(tracker,job,manifest_factory(tracker,[job]))
    no_attempt(tracker,job,fixture_browser)


def test_application_agreement_is_never_activated_from_general_memory(qa_file, tracker, make_job, manifest_factory, fixture_browser):
    question='Please Review the NDA and indicate your agreement by typing your full name below'
    qa_file(entry(question=question,answer='Test Candidate',reuse='exact_question'))
    fixture_browser[0]['extra']=f'<label for="q">{question}</label><input id="q" name="q" required>'
    job=make_job()
    run(tracker,job,manifest_factory(tracker,[job]))
    no_attempt(tracker,job,fixture_browser)


def test_duplicate_education_label_does_not_get_same_answer_twice(qa_file, tracker, make_job, manifest_factory, fixture_browser):
    qa_file(entry(question='University',answer='Synthetic University'))
    fixture_browser[0]['extra']='<label for="one">University</label><input id="one" name="one" required><label for="two">University</label><input id="two" name="two" required>'
    job=make_job()
    run(tracker,job,manifest_factory(tracker,[job]))
    no_attempt(tracker,job,fixture_browser)


def test_reviewed_name_split_is_used_without_changing_full_name(qa_file, app_config, tracker, make_job, manifest_factory, fixture_browser):
    app_config['profile']['name']='Test Middle Candidate'
    qa_file(entry(id='NAME1',question='First Name',answer='Test Middle'),
            entry(id='NAME2',question='Last Name',answer='Candidate'))
    job=make_job()
    run(tracker,job,manifest_factory(tracker,[job]))
    assert tracker.get_job_by_url(job['job_url'])['status']=='confirmed_submitted'
    body=next(request[2] for request in fixture_browser[1] if request[0]=='POST')
    assert 'Test Middle' in body
    assert app_config['profile']['name']=='Test Middle Candidate'


@pytest.mark.parametrize('question,answer',[('Email','other@example.test'),('Phone','999'),('First Name','Invented')])
def test_memory_cannot_overwrite_verified_identity(question, answer, qa_file, tracker, make_job, manifest_factory, fixture_browser):
    qa_file(entry(question=question,answer=answer))
    job=make_job()
    run(tracker,job,manifest_factory(tracker,[job]))
    no_attempt(tracker,job,fixture_browser)


def test_conflicting_answers_fail_closed(qa_file, app_config):
    qa_file(entry(),entry(id='Q002',answer='A different answer'))
    with pytest.raises(AnswerMemoryError,match='Conflicting'):
        application_answers(app_config,{'country':'India'})


def test_configuration_conflict_is_not_silently_overwritten(qa_file, app_config):
    qa_file(entry())
    app_config['application_answers']={'Portfolio explanation':'Different verified answer'}
    with pytest.raises(AnswerMemoryError,match='conflicts'):
        application_answers(app_config,{'country':'India'})


def test_known_profile_fact_conflict_requires_resolution(qa_file, app_config):
    qa_file(entry(question='Total years of experience',answer='3',answer_type='number',profile_ref='screening.years_of_experience'))
    with pytest.raises(AnswerMemoryError,match='verified configuration'):
        application_answers(app_config,{'country':'India'})


def test_memory_change_invalidates_approval_before_database_writes(qa_file, app_config, tracker, make_job, manifest_factory):
    qa_file(entry(reviewed=False))
    job=make_job()
    manifest=manifest_factory(tracker,[job])
    before=tracker.db_path.read_bytes()
    qa_file(entry(reviewed=False,answer='Edited pending answer'))
    with pytest.raises(AuthorizationError,match='answer_memory'):
        validate_authorization(manifest,[job['id']],app_config,[job],tracker.db_path)
    assert tracker.db_path.read_bytes()==before


def test_memory_edit_during_preparation_stops_guard(qa_file, tracker, make_job, manifest_factory, fixture_browser, monkeypatch):
    import auto_apply.adapters.greenhouse as adapter
    qa_file(entry())
    fixture_browser[0]['extra']='<label for="q">Portfolio explanation</label><input id="q" name="q" required>'
    original=adapter.handle_challenge
    calls=0
    def change(page,unattended=False):
        nonlocal calls
        calls+=1
        if calls==2:
            qa_file(entry(answer='New answer after approval'))
        return original(page,unattended=unattended)
    monkeypatch.setattr(adapter,'handle_challenge',change)
    job=make_job()
    run(tracker,job,manifest_factory(tracker,[job]))
    assert not [request for request in fixture_browser[1] if request[0]=='POST']
    assert tracker._con.execute('SELECT COUNT(*) FROM auto_apply_attempts').fetchone()[0]==0
    assert tracker.get_job_by_url(job['job_url'])['status']!='confirmed_submitted'


def test_profile_path_and_all_memory_bytes_are_bound(qa_file, app_config, monkeypatch, tmp_path):
    path=qa_file(entry(reviewed=False))
    original=memory_integrity(app_config)
    other=tmp_path/'other.yaml'
    other.write_bytes(path.read_bytes())
    monkeypatch.setenv('AUTO_APPLY_ANSWERS',str(other))
    assert memory_integrity(app_config)['sha256']==original['sha256']
    assert memory_integrity(app_config)['path']!=original['path']


def test_readonly_cli_preview_and_draft_expose_memory(qa_file, tracker, make_job, tmp_path):
    qa_file(entry())
    before=tracker.db_path.read_bytes()
    cwd=Path(__file__).resolve().parents[1]/'src'
    result=subprocess.run([sys.executable,'-m','auto_apply','--preview-answers'],cwd=cwd,capture_output=True,text=True,env=os.environ.copy())
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(result.stdout)['reviewed']==1
    assert json.loads(result.stdout)['submission_authorized'] is False
    job=make_job()
    before=tracker.db_path.read_bytes()
    output=tmp_path/'draft.json'
    result=subprocess.run([sys.executable,'-m','auto_apply','--prepare-batch','--job-ids',str(job['id']),'--db-path',str(tracker.db_path),'--out',str(output)],cwd=cwd,capture_output=True,text=True,env=os.environ.copy())
    assert result.returncode==0,result.stdout+result.stderr
    payload=json.loads(output.read_text())
    assert payload['human_approval_recorded'] is False
    assert payload['saved_answer_memory']['answers_by_job'][str(job['id'])]['portfolio explanation']['value']=='A truthful synthetic answer'
    assert tracker.db_path.read_bytes()==before


def test_preview_never_turns_answers_into_submission_approval(qa_file, app_config):
    qa_file(entry(),entry(id='Q002',answer=None,reviewed=False))
    summary=preview_memory(app_config)
    assert summary['questions']==2
    assert summary['reviewed']==1
    assert summary['pending_review']==1
    assert summary['submission_authorized'] is False


@pytest.mark.parametrize('control,answer,maximum', [
    ('input', 'ABCDE', 3),
    ('textarea', 'ABCDE', 3),
    ('textarea', '\U0001f680\U0001f680', 3),
])
def test_saved_text_exceeding_native_limit_pauses_without_attempt(
        control, answer, maximum, qa_file, tracker, make_job, manifest_factory, fixture_browser):
    qa_file(entry(answer=answer))
    field = f'<{control} id="q" name="q" maxlength="{maximum}" required>'
    if control == 'textarea':
        field += '</textarea>'
    fixture_browser[0]['extra'] = '<label for="q">Portfolio explanation</label>' + field
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    no_attempt(tracker, job, fixture_browser)


@pytest.mark.parametrize('control,answer,maximum', [
    ('input', 'ABCDE', 5),
    ('textarea', 'ABCDE', 6),
    ('textarea', '\U0001f680\U0001f680', 4),
])
def test_saved_text_within_native_limit_is_preserved(
        control, answer, maximum, qa_file, tracker, make_job, manifest_factory, fixture_browser):
    qa_file(entry(answer=answer))
    field = f'<{control} id="q" name="q" maxlength="{maximum}" required>'
    if control == 'textarea':
        field += '</textarea>'
    fixture_browser[0]['extra'] = (
        '<script>document.getElementById("application_form").acceptCharset = "UTF-8";</script>'
        '<label for="q">Portfolio explanation</label>' + field
    )
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    assert tracker.get_job_by_url(job['job_url'])['status'] == 'confirmed_submitted'
    assert answer in next(request[2] for request in fixture_browser[1] if request[0] == 'POST')


def test_form_rewriting_saved_text_pauses_without_attempt(
        qa_file, tracker, make_job, manifest_factory, fixture_browser):
    qa_file(entry(answer='Approved text'))
    fixture_browser[0]['extra'] = (
        '<label for="q">Portfolio explanation</label>'
        '<textarea id="q" name="q" required '
        'oninput="this.value = this.value.toUpperCase()"></textarea>'
    )
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    no_attempt(tracker, job, fixture_browser)


def test_basic_fact_exceeding_native_limit_pauses_without_attempt(
        qa_file, tracker, make_job, manifest_factory, fixture_browser):
    qa_file(entry())
    fixture_browser[0]['extra'] = (
        '<script>document.getElementById("first_name").maxLength = 2;</script>'
    )
    job = make_job()
    run(tracker, job, manifest_factory(tracker, [job]))
    no_attempt(tracker, job, fixture_browser)


def test_reviewed_month_only_start_date_remains_notes_not_an_exact_date(qa_file, app_config):
    qa_file(entry(question='What is the exact start date of your current employment?',
                  answer='January 2025', reviewed=True, reuse='notes_only'))
    assert application_answers(app_config, {'country': 'India'}) == {}


def test_corrected_prior_tenure_is_preserved_but_not_reused(qa_file, app_config):
    question = 'How many years of professional LangGraph experience do you have?'
    qa_file(entry(question=question, answer=None, reviewed=False,
                  superseded_answers=[{'answer': 1, 'reviewed': True}],
                  notes='User clarified no direct LangGraph implementation; old tenure is not reusable.'))
    recorded = read_memory(app_config)['questions'][0]
    assert recorded['answer'] is None
    assert recorded['superseded_answers'][0]['answer'] == 1
    assert application_answers(app_config, {'country': 'India'}) == {}


def test_review_only_draft_cannot_authorize_even_with_human_flag(
        qa_file, app_config, tracker, make_job, manifest_factory):
    qa_file(entry())
    job = make_job()
    manifest = manifest_factory(tracker, [job], review_only=True)
    before = tracker.db_path.read_bytes()
    with pytest.raises(AuthorizationError, match='review-only'):
        validate_authorization(manifest, [job['id']], app_config, [job], tracker.db_path)
    assert tracker.db_path.read_bytes() == before
