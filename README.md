# Job application workbench

Inspect and import jobs, prepare a concrete review manifest, and run approved
Greenhouse batches. LinkedIn, Naukri and other platform forms are for discovery
and manual review; this CLI does not submit them automatically.

Run commands from the repository directory:

~~~bash
cd /Users/girimanoharv/.gemini/antigravity/scratch/job-auto-apply
~~~

## Review the queue

~~~bash
auto_apply/.venv/bin/python -m auto_apply --preview-batch --db-path tracker.db
auto_apply/.venv/bin/python -m auto_apply --preview-batch --job-ids 1611,1614 --db-path tracker.db
~~~

Preview is read-only. Ineligible or unresolved jobs keep their stored status.
A score alone does not resolve missing requirements or a recorded review reason.

## Import jobs

~~~bash
auto_apply/.venv/bin/python -m auto_apply --import-csv /absolute/path/jobs.csv --dry-run --db-path tracker.db
auto_apply/.venv/bin/python -m auto_apply --import-csv /absolute/path/jobs.csv --db-path tracker.db
auto_apply/.venv/bin/python -m auto_apply --import-url "https://job-boards.greenhouse.io/EMPLOYER/jobs/JOB_ID" --db-path tracker.db
~~~

Replace EMPLOYER and JOB_ID with an actual verified vacancy. The URL above is a
placeholder; a URL-only import remains for review until its metadata is supplied.

CSV headers:

~~~csv
platform,job_url,title,company,location,country,description,experience,application_open
greenhouse,https://job-boards.greenhouse.io/PLACEHOLDER_EMPLOYER/jobs/PLACEHOLDER_JOB_ID,Python Developer,PLACEHOLDER COMPANY,India,India,"PASTE THE ACTUAL JOB DESCRIPTION AND MANDATORY REQUIREMENTS","PASTE THE ACTUAL EXPERIENCE REQUIREMENT",Unknown
~~~

The sample is deliberately not an eligible job. Supported URL headers are
job_url, url and apply_url. A Greenhouse row can supply both `job_url` (the
listing) and `apply_url` (the exact reviewed first-party application form).
They must identify the same Greenhouse board and job. The listing is
canonicalized for deduplication; the application route is preserved and bound
by approval and the submission receipt. Reimport does not replace an existing
application route. A different route needs an explicit review, not a silent
fallback around an access denial or challenge.

Description, experience, location and availability
must come from the actual posting. Do not invent experience requirements to
turn a review item into an eligible item.

Automatic submissions currently require an established India work location.
For a city-only location, supply the verified country column. Remote alone
does not establish country-specific work authorization.

Imports exit without opening a browser. Reimports backfill missing metadata
without resetting application statuses, confirmed timestamps or audit evidence.
An import with bad rows reports errors; valid rows may still be imported.

## Prepare and approve the first pilot

Select at most five eligible jobs. Replace the illustrative IDs below with the
jobs you reviewed. Jobs 1611 and 1614 are not automatically approved by this guide.

~~~bash
auto_apply/.venv/bin/python -m auto_apply --prepare-batch --job-ids 123,124 --out outputs/pilot-review.json --db-path tracker.db
~~~

The draft reads the existing database without migrations and starts with
human_approval_recorded=false. Review its job descriptions, fit decisions,
resume and proposed facts. Only after your explicit decision, change that
field to true yourself.

The manifest binds the database path, actual resolved browser profile path,
exact jobs, metadata, candidate facts,
resume bytes, submission policy and runtime code. It expires after 24 hours.
Changes require a fresh draft and review. These checks record approval and
detect changes; they are not a cryptographic human signature.

Live command, only after the concrete pilot is approved:

~~~bash
auto_apply/.venv/bin/python -m auto_apply --run-batch --job-ids 123,124 --authorize-submission outputs/pilot-review.json --db-path tracker.db
~~~

No jobs are selected implicitly. Unknown answers, unsupported controls, changed
eligibility, upload failures and challenges stop preparation or pause the job.

## Resume a paused job

~~~bash
auto_apply/.venv/bin/python -m auto_apply --resume-job 123 --authorize-submission outputs/pilot-review.json --db-path tracker.db
~~~

Resume revalidates the original complete approval scope, eligibility, attempt
limits and duplicate protection. You resolve challenges or supported fields
in the open browser, then explicitly authorize the completed form. The same
submission guard executes the final action.

A reserved or ambiguous attempt is not automatically retried. Inspect its
receipt and platform history before any recovery decision.

## Daily batches after pilot review

The first pilot is permanently bound to its selected jobs. Its outcome review
is required before additional batches. The runner prints the pilot ID.

~~~bash
auto_apply/.venv/bin/python -m auto_apply --prepare-batch --phase daily --job-ids 125,126 --out outputs/daily-review.json --db-path tracker.db
~~~

The daily draft includes the prior pilot outcomes and starts with both
human_approval_recorded=false and pilot_review_recorded=false. Record those
decisions yourself after reviewing them. Then run the exact approved IDs with
--run-batch and --authorize-submission.

At most 20 submission attempts are allowed per Asia/Kolkata calendar day.
Failed or ambiguous submissions consume a slot. Preparation and challenges
before submission do not. Each attempt is durably reserved before the external
action. Batch and resume share the same transactional checks across processes.

The new auto_apply_pilot and auto_apply_attempts tables are additive. Historical
tables and legacy unconfirmed records are preserved. confirmed_submitted is
the canonical successful state, and its original applied_at is preserved.

## Browser session

Normal live sessions use sessions/chromium_profile and preserve its cookies
and browser history. Platform session expiry can still require a manual login.

~~~bash
auto_apply/.venv/bin/python -m auto_apply --open-browser
~~~

No password rotation, profile deletion, account switching or CAPTCHA bypass is
performed by these commands. Custom profile paths can be supplied through
AUTO_APPLY_PROFILE_DIR or browser.user_data_dir in configuration.
The environment override takes precedence. Paths are expanded and resolved
using the same function during draft preparation, approval validation and
browser launch. A changed override or symlink target invalidates approval;
generate and review a new draft before changing sessions. Approval binds the
profile path, not a verified account identity or a permanent login. Do not
delete, copy, merge or recreate the production profile to repair authentication.

## Supported forms and confirmation

The adapter supports native Greenhouse forms it can identify unambiguously.
It fills approved basic identity fields, selects the actual resume control,
and validates native/ARIA-required controls, radios, checkboxes and attachments.
Unknown custom widgets and screening questions pause for review.

The newer `application--form` renderer is supported when its job ID, board,
submission path and confirmation path match the approved posting. Its
`.job__description` is compared with the full reviewed description. Recognized
Greenhouse React selects require an exact, unique offered option and a committed
selection state. Typed search text alone is not an answer. Unfamiliar widgets
remain unsupported.
Recognized select validation proxies are excluded from answer-field snapshots.
Uniquely identified controls stay bound by ID when selection removes those
proxies, rather than following a shifted position in the form.
A prefilled required non-demographic select without an approved answer is never
treated as verified. It stays for explicit human review, including controls
that have no Clear button. Batch execution pauses; interactive resume requires
review of the completed form before the same guard can submit it.

The recognized asynchronous resume uploader can remove its file input while
uploading. The bot observes the file passed to native `XMLHttpRequest.send`,
checks its name, size and SHA-256 against the approved resume, and requires a
completed successful upload response and a matching filename in the resume
control. It does not change the upload URL, signed fields or body, or wait for
the hash calculation before sending the native request.
The displayed upload is checked again before reservation. The final application
POST must refer to that verified upload URL and filename, or it is blocked.
A filename alone, a selected file or an incomplete upload cannot pass this check.
Other asynchronous uploaders remain unsupported. Upload requests are preparation,
not application submissions; they do not create a submission attempt.
Already-empty optional file inputs stay untouched. Sending an empty selection
can fire the renderer's upload handler and detach the control during preparation.

For the newer renderer, a bounded observer reads a copy of the native fetch
response before navigation. It does not change request URLs, headers, bodies,
cookies or CAPTCHA behavior. A completed matching POST and a new dedicated,
job-bound confirmation are still required. Unreadable or incomplete JSON stays
unconfirmed. One reserved attempt permits one POST to its submission endpoint;
an automatic renderer retry is blocked rather than silently sent twice.

Active enterprise reCAPTCHA challenges and email-verification screens require
manual resolution. The presence of an inactive script or invisible anchor is
not treated as a solved challenge. No challenge token is created by the bot.

Optional demographic fields stay blank, including preselected radios and
selects. Required native demographic selects and radio groups use an offered
nondisclosure option first, including options with no explicit HTML value.
If none exists, only an exact saved answer may be used; otherwise preparation
pauses. Other unverified native defaults are cleared, including optional
answers and basic fields whose corresponding profile fact is missing.
Unknown required facts remain unanswered.
Approved values, including intentionally blank optional answers, radio and
checkbox states and values, and the selected resume's actual bytes, are checked
again before the submission guard reserves an attempt. On manual resume,
new required answers are recorded from the explicitly reviewed completed form
and checked again before reservation. Known approved values remain protected.

## Exact question answers

### Personal QA memory

`APPLICATION_QUESTIONS.md` is the readable questionnaire; `application_qa.yaml`
is the bot's authoritative answer memory. The initial bank contains 337
questions, including screening, technical knowledge, separate professional
and project experience, education and exact saved employer-form questions.
It is a starting bank, not an exhaustive list of every possible question.

Reply with question IDs in chat, or edit the YAML. Known facts are prefilled
for review; unknown answers are `null`. Every new entry starts with
`reviewed: false`. Only explicitly confirmed answers marked `reviewed: true`
and `reuse: exact_question` can be reused, subject to exact labels and scope.
Questionnaire completion does not authorize an application submission.

~~~yaml
# Synthetic example, not this candidate's answer:
schema_version: 1
questions:
  - id: SAMPLE001
    category: screening
    question: What is your notice period?
    exact_labels:
      - What is your notice period?
    answer: null
    reviewed: false
    reuse: exact_question
    scope:
      countries: [India]
~~~

Valid reuse modes are `exact_question`, `manual_per_application` and
`notes_only`. Employer-specific records use `scope.companies`; individual
vacancies can use `scope.job_urls`. Scopes contain nonempty lists and match
exactly, apart from known Greenhouse URL tracking variants. Legal records
need distinct `fact` and explicit `country` metadata as described below.
No semantic/fuzzy matching or answer generation takes place.

Terms/NDA/privacy acknowledgements and certifications require review for the
current application. General QA memory cannot provide their acceptance.
Optional EEO stays blank even when an answer is saved. Identical ambiguous
labels, such as two University fields, remain for review. A reviewed first/last
name split must agree with the verified full name. Existing explicit profile
facts cannot be silently overwritten by QA answers.

Saved text must fit the form's native character limit and remain unchanged
after filling, apart from equivalent newline encodings. Oversized or rewritten
answers pause before any submission reservation; the bot does not silently
truncate, summarize, or switch to an unreviewed shorter version. Custom counters
without native limits may still need manual review.

Professional tenure is not inferred from technical knowledge or project
answers. QA memory does not update eligibility skills, experience or filters.
Conflicts with referenced profile facts or other saved answers pause execution.
The entire memory file and its resolved path are included in approval integrity
checks. Any edit, including pending answers, requires a fresh batch draft and
review. The draft shows the exact saved answers applicable to each job.

Normal repository configuration loads `application_qa.yaml` automatically.
Use `AUTO_APPLY_ANSWERS` or `paths.answer_memory_path` for an explicit custom
path. Synthetic/test configuration has no implicit personal-memory fallback;
tests require explicitly selected temporary files outside the repository.
The personal YAML and worksheet are git-ignored. Do not put credentials,
government-ID numbers or financial-account details in this bank.

Read-only readiness summary, without opening a browser or database:

~~~bash
auto_apply/.venv/bin/python -m auto_apply --preview-answers
~~~

The YAML is authoritative. Markdown edits alone do not change what the bot
uses. A synthetic schema example is in
`auto_apply/examples/application_qa.example.yaml`.

### Direct configured answers

`application_answers` is a YAML mapping from the complete visible question
to its explicitly verified answer. Matching ignores case, surrounding spaces
and a trailing required-field asterisk; it does not use fuzzy matching.
Do not add answers merely because a test fixture or default provides a value.

~~~yaml
# Synthetic examples, not this candidate's answers:
application_answers:
  "Total years of experience": "2"
  "Consent to the stated recruitment data policy": true
  "Are you legally authorized to work in India?":
    value: "Yes"
    country: India
    fact: work_authorization
~~~

Text inputs and textareas accept a scalar or `{value: ...}` record. Native
selects use the exact option label; checkboxes require a YAML boolean. Native
radio groups require a fieldset legend or ARIA group label identifying the
question and an exact, unique option label. Unrecognized custom widgets pause.
Hidden platform tokens are not candidate answers.

Citizenship, permanent residency, work authorization and sponsorship require
a record with `value` and `country: India` (or `IN`). A distinct `fact` is
recommended:
`citizenship`, `permanent_residency`, `work_authorization`, or `visa_sponsorship`.
The question must positively match an implemented India-only template, such
as "Are you an Indian citizen?", "Are you a permanent resident of India?",
"Are you legally authorized to work in India?", or "Will you require visa
sponsorship to work in India?". Wording variants accepted by the adapter are
limited; unfamiliar wording pauses for review. An India record cannot answer
a foreign-country, mixed-country or country-unspecified legal question.
An authorization answer is never citizenship or residency evidence.
For an already saved record without `fact`, the complete supported question
identifies the fact; an explicitly supplied `fact` must agree with it. The
existing `screening.work_authorization_india` Yes/No or boolean is also reused
only for a positively matched India work-authorization question. It cannot
answer citizenship, residency, sponsorship or foreign-country questions.

## Qualification limits

Qualification checks are conservative heuristics. Mandatory and preferred
clauses are assessed separately, including clauses on one line. Explicit
skill alternatives may satisfy their own group; a preferred clause does not
erase an earlier mandatory gap. Unknown experience remains for review.

`screening.years_of_experience` represents the declared total. It does not
prove professional tenure in Python, LLMs or every configured skill. Numeric
tool-specific experience requirements require separately verified
`screening.professional_experience_years` entries keyed by the exact tool name.
Project use and keyword matches do not establish that professional tenure.
This optional map is not automatically populated from dates or resume skills.

The parser covers a finite skill vocabulary and common numeric experience
phrases. It can miss domain, degree, ambiguous prose and unusual alternatives,
and can conservatively flag uncertain clauses. Keyword matching cannot prove
every mandatory qualification. Review full authoritative descriptions,
application questions, location, freshness, salary and employment preferences
before selecting a pilot. The eligibility score does not establish publication
age or unpublished compensation. Public listing availability is not a live
adapter acceptance test; unsupported rendered forms remain for manual review.

Resume selection is verified separately from platform acceptance. A populated
file input is not reported as a successful application. Confirmation requires
a matching accepted POST response, a newly observed dedicated confirmation
state, the approved job identity and the reserved attempt ID. Ambiguous
outcomes remain unconfirmed.

This implementation uses the documented
[Playwright form actions](https://playwright.dev/python/docs/input) and
[response events](https://playwright.dev/python/docs/api/class-page#page-event-response).
It does not assume public job-listing access grants an employer application API
key; the [Greenhouse API documentation](https://docs.greenhouse.io/job-board.html)
describes the separate API authorization requirements.

## Isolated verification

Tests must use synthetic configuration, temporary databases and a separate
Chromium profile. AUTO_APPLY_TEST_MODE blocks external browser requests.
The suite's fixtures set these protections for each test and subprocess.

~~~bash
cd auto_apply
.venv/bin/python -m pytest tests -q -p no:cacheprovider
~~~

Tests with no isolated profile are blocked before browser launch. Local fixture
responses establish local behavior; they are not proof of acceptance by a live
employer.

To watch one local fixture run in visible Chromium:

~~~bash
cd auto_apply
AUTO_APPLY_SHOW_LOCAL_FIXTURE=1 .venv/bin/python -B -m pytest tests/test_greenhouse_modern.py::test_exact_react_select_choice_and_optional_demographic_blank -q -s -p no:cacheprovider
~~~

The visible page is marked as a simulation. It uses synthetic candidate data,
a temporary database and profile, and intercepted localhost responses. It does
not import production jobs, open the real browser profile or apply to an employer.

Discovery review packages may contain a `review_only: true` staging manifest.
The runner rejects it even if its human-approval flag is changed. Review the
specific postings, missing answers and materials, then approve the proposed
production import separately. Generate a fresh production-bound draft using
the actual imported IDs before recording submission approval. Staging IDs are
not production IDs.

## Read-only recovery inspection

This exports selected rows from the explicitly named backup, not the current
database by default, and never restores records:

~~~bash
auto_apply/.venv/bin/python export_recoverable.py --source /absolute/path/backup.db --job-ids 1597,1598,1599 --out outputs/backup-records.csv
~~~

The CSV's .source.json companion identifies its source, found IDs and missing
IDs. Missing records and destroyed attempt history remain unknown.

Old scripts and legacy automation are retained for reference. Do not use the
old run_daily or auto-apply instructions as the entry point for this workflow.
