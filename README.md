# Job Automation Agent — Core Backend + Resume Engine + Job Ingestion + Outreach + Learning Loop (Phases 1-5)

This is the foundation of the autonomous job-search agent described in the spec:
multi-user auth, the full data model (preferences, master resume, job postings,
matches, applications, HR contacts, outreach emails, answer bank, activity log),
and a REST API to drive all of it. MySQL-backed, runs locally via Docker.

**Phase 2 adds the resume customization engine**: parsing a plain-text master
resume into structured sections, scoring a job description against it, and
generating a tailored, ATS-friendly PDF resume — compiled locally with
`pdflatex` (no Overleaf automation; Overleaf has no API for this, so the
Dockerfile installs a real LaTeX toolchain instead).

**Phase 3 adds job ingestion**: pulling real postings from Adzuna, RemoteOK,
Greenhouse, and Lever into the shared job pool, with automatic scoring
against your resume. (LinkedIn/Naukri/Indeed are intentionally excluded —
see the "Job ingestion" section for why.)

**Phase 4 adds the outreach engine**: drafting personalized cold emails to
HR contacts, sending them via SMTP, and tracking/classifying replies.

**Phase 5 adds the learning loop**: mining your own application and outreach
history for what's actually working (which skills correlate with
interviews, which email subject lines get replies, which application
questions keep recurring) and feeding that back into future resume
generation and a reusable, candidate-verified answer bank.

See "What's next" at the bottom for what's still outside this backend
(a frontend and a deployment target).

## Job ingestion: how it works

This module pulls jobs from four sources, normalizes them into the shared
`job_postings` pool, de-duplicates by `(source, external_id)`, and (if a
parsed master resume exists) automatically scores each new posting for the
user who triggered the run.

| Source | Type | Needs |
|---|---|---|
| **Adzuna** | keyword + location search | Free API credentials (`ADZUNA_APP_ID`/`ADZUNA_APP_KEY` in `.env`) |
| **RemoteOK** | keyword search (remote jobs) | Nothing — public API |
| **Greenhouse** | per-company job board | A list of company board tokens in your preferences |
| **Lever** | per-company job board | A list of company tokens in your preferences |

**Deliberately excluded from this phase:** LinkedIn, Naukri, Indeed's web UI,
Glassdoor, and similar portals. Those either have no public search API or
explicitly prohibit automated scraping in their Terms of Service — pulling
from them would mean either violating ToS or maintaining fragile scrapers
that break constantly and can get an account banned. The four sources above
are the ones with a documented, ToS-compliant path to "search jobs
programmatically." If you want a specific portal added later, it needs to be
evaluated case-by-case against that portal's terms.

### Setting it up

1. Set your target titles, locations, and which sources to use:
   `PUT /preferences` with `allowed_portals: ["remoteok", "greenhouse"]`
   (any combination of `adzuna`, `remoteok`, `greenhouse`, `lever`).
2. For Greenhouse/Lever, add the specific companies you want to watch —
   these are per-company boards, not a general search:
   `tracked_companies: {"greenhouse": ["stripe", "airbnb"], "lever": ["netflix"]}`
   (the token is the slug in that company's careers URL, e.g.
   `boards.greenhouse.io/stripe` → `"stripe"`).
3. For Adzuna, register for free credentials at developer.adzuna.com and put
   them in `.env`.
4. `GET /ingestion/sources` to confirm what's configured.
5. `POST /ingestion/run` to pull jobs. Safe to call repeatedly — already-seen
   postings are skipped, so this is what you'd put on a schedule (a cron job
   or a simple loop) once you're happy with the results.

## Outreach engine: how it works

Draft → send → track replies, tied to your existing `hr_contacts`.

1. **Drafting** (`app/services/email_generator.py`) — builds a personalized
   cold email from real data only (candidate name/summary/skills from your
   parsed master resume, the contact's name/company, the matched job).
   Default mode fills one of several varied templates — free, offline, no
   external dependency. If you set `ANTHROPIC_API_KEY` in `.env`, it instead
   asks Claude to phrase the same facts more naturally, and automatically
   falls back to the template if that call fails for any reason. Either way,
   it never invents experience or skills that weren't in your data.
2. **Sending** (`app/services/email_sender.py`) — plain SMTP via `smtplib`,
   works with Gmail app passwords, SendGrid, Postmark, or your own mail
   server. Records the outgoing Message-ID so a later reply can be matched
   back to this exact email.
3. **Reply tracking** — realistically, watching an inbox requires an IMAP
   poller or a provider's inbound-parse webhook (SendGrid Inbound Parse,
   Mailgun Routes, Postmark Inbound are the common options), which is a
   deploy-time integration choice, not something to hardcode. This backend
   exposes `POST /outreach/reply-webhook` in the shape those providers send,
   so wiring one up is a matter of pointing its webhook at that endpoint
   (adjust field names to match if a provider's payload differs slightly).
4. **Classification** (`app/services/reply_classifier.py`) — keyword-based,
   sorts an inbound reply into positive/negative/neutral plus the more
   specific dashboard categories from the spec (interview opportunity,
   rejection, action required). Transparent and easy to extend as you see
   real replies come in, at the cost of missing nuance a real NLP model
   would catch — worth an upgrade path later if reply volume grows.
5. **Follow-ups** — `GET /outreach/pending-followups` lists sent-but-unanswered
   emails older than `FOLLOW_UP_AFTER_DAYS` (default 7); `POST /outreach/follow-up/{id}`
   sends one. This is manual-trigger by design, matching Approval Mode from
   the spec — turning it into a scheduled autonomous job is a small addition
   (a cron entry or Celery beat task calling that endpoint) once you're
   comfortable with how it behaves.

### Outreach endpoints

- `POST /outreach/draft/{hr_contact_id}?job_match_id=...` — generate a draft
- `POST /outreach/send/{outreach_email_id}` — send a draft via SMTP
- `GET /outreach/smtp-status` — check whether SMTP is configured
- `GET /outreach/pending-followups` / `POST /outreach/follow-up/{id}`
- `POST /outreach/reply-webhook` — inbound reply handler for your email provider
- `GET /outreach` — list all outreach emails (filter with `?status_filter=`)

## Learning loop: how it works

Everything here is descriptive statistics over the candidate's *own* history
— no external model, nothing invented, nothing applied until the candidate
has actually seen enough of their own outcomes to matter.

1. **`GET /learning/insights`** (`app/services/learning_engine.py`) —
   correlates each skill that's appeared in a job match with how those
   applications turned out (interview/offer vs rejection vs silence),
   does the same for job attributes (company, work mode), looks at whether
   specific resume versions' emphasized skills led anywhere, and finds
   subject-line words that show up disproportionately in emails that got
   positive replies. Returns a `recommendations` list in plain language,
   plus the raw numbers behind each one.
2. **Resume generation gets smarter over time** — `POST /resume-engine/generate/{job_match_id}`
   now takes a `use_learning` flag (defaults to `true`): when set, it pulls
   in skills that have *historically* led to interviews for this candidate
   — but only ones already in their actual resume, layered on top of (never
   instead of) this specific job's own relevance match.
3. **The answer bank closes the loop on recurring application questions**
   (spec section 3's "maintain a Candidate Knowledge Base... for uncertain
   questions, request user confirmation"):
   - Record answers as you complete an application: `PATCH /applications/{id}/answers`
   - Before answering a new question, check if you've answered something
     close to it before: `GET /knowledge/answers/match?question=...`
   - `POST /learning/sync-answer-bank` scans all your recorded answers and
     grows the bank — **new entries always start unverified**, so nothing
     gets silently reused until you confirm it's accurate:
     `PATCH /knowledge/answers/{id}` with `{"verified": true}`
   - `insights.recurring_questions` tells you which questions keep coming
     up and whether you've verified an answer for them yet.

### Learning + knowledge-base endpoints

- `GET /learning/insights` — the full analytics report described above
- `POST /learning/sync-answer-bank` — scan applications, grow the answer bank
- `GET /knowledge/answers` / `POST /knowledge/answers` — the answer bank (add `?verified_only=true` or `?category=`)
- `GET /knowledge/answers/match?question=...` — find a reusable answer for a new question
- `PATCH /knowledge/answers/{id}` — edit/verify an answer
- `POST /knowledge/facts` / `GET /knowledge/facts` — free-form verified candidate facts (visa status, notice period, etc.)
- `PATCH /applications/{id}/answers` — record the Q&A used on a specific application

### Proven with synthetic data, not just "it returns 200"

`test_learning_loop.py` seeds a candidate with 4 Python applications (3
interviews) and 3 COBOL applications (0 interviews), plus 6 outreach emails
split by subject-line style, and asserts the engine actually surfaces Python
as the strongest skill, COBOL as a dead end, and the winning subject-line
words — not just that the endpoints don't error.

## Resume engine: how it works

1. **Parsing** (`app/services/resume_parser.py`) — rule-based, not ML: splits
   your master resume's raw text into contact info, summary, skills,
   experience, education, projects, and certifications by recognizing common
   section headers and bullet patterns. It's deliberately simple so it has
   zero external model dependency and is easy to audit — and because plain-text
   resumes vary wildly in layout, the parsed result is meant to be reviewed
   and corrected, not trusted blindly.
2. **JD analysis** (`app/services/jd_analyzer.py`) — matches a curated skills
   taxonomy (`app/services/skills_data.py`) against both the resume and the
   job description, and blends that with TF-IDF cosine similarity over the
   full text, into a single 0-100 relevance score plus explicit
   matched/missing skill lists.
3. **Generation** (`app/services/resume_builder.py`) — reorders (never
   invents) your existing skills and bullet points so the ones most relevant
   to this job surface first, renders that into a LaTeX template via Jinja2,
   and compiles it to PDF with `pdflatex`.

### Resume engine endpoints

- `POST /resume-engine/parse-master` — parse your active master resume into structured JSON
- `PUT /resume-engine/master/parsed` — manually correct the parsed structure (recommended after first parse)
- `POST /resume-engine/analyze/{job_posting_id}` — score a job against your resume, creates/updates the `JobMatch`
- `POST /resume-engine/generate/{job_match_id}` — build and compile a tailored resume for that match
- `GET /resume-engine/versions/{job_match_id}` — list generated versions for a match
- `GET /resume-engine/download/{resume_version_id}` — download the compiled PDF

Typical flow: upload master resume → parse it → review/fix the parsed JSON →
ingest a job posting → analyze it → generate → download the PDF.

## Quick start (local)

Requires Docker and Docker Compose.

```bash
cd job_agent
cp .env.example .env
# edit .env and set real values for SECRET_KEY, MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD

docker compose up --build
```

The API will be live at http://localhost:8000
Interactive docs (Swagger UI): http://localhost:8000/docs

On first startup the app creates all MySQL tables automatically from the
SQLAlchemy models (fine for development; switch to Alembic migrations before
production — see below).

## Trying it out

1. **Register a user**
   `POST /auth/register` — body: `{"email": "...", "password": "...", "full_name": "..."}`

2. **Log in** (this is an OAuth2 password-flow form, not JSON)
   `POST /auth/login` — form fields `username` (your email) and `password`.
   Returns a JWT `access_token`. Use it in Swagger UI's "Authorize" button,
   or as `Authorization: Bearer <token>` on every subsequent request.

3. **Set preferences**
   `PUT /preferences` — target titles, locations, salary range, operating
   mode (`fully_autonomous` / `approval` / `assisted`), portal allowlist, etc.

4. **Upload a master resume**
   `POST /resumes` — body: `{"raw_text": "..."}`

5. **Feed in a job** (manual stand-in) or **pull real jobs automatically**
   `POST /jobs/postings` — manual entry, source, external_id, title, company, description, url...
   or set up `preferences.allowed_portals`/`tracked_companies` and call
   `POST /ingestion/run` to pull from Adzuna/RemoteOK/Greenhouse/Lever (see
   the "Job ingestion" section below for setup).

6. **Create a match for yourself against that job**
   `POST /jobs/matches/{job_posting_id}?relevance_score=82`

7. **Turn a match into an application and move it through its lifecycle**
   `POST /applications/from-match/{job_match_id}`
   `PATCH /applications/{application_id}/status` — body: `{"status": "submitted"}`
   `PATCH /applications/{application_id}/answers` — record the Q&A you used

8. **Log an HR contact**
   `POST /contacts`

9. **Draft and send a cold email, then simulate a reply**
   `POST /outreach/draft/{hr_contact_id}?job_match_id=...`
   `POST /outreach/send/{outreach_email_id}` (needs SMTP configured in `.env`)
   `POST /outreach/reply-webhook` — see the "Outreach engine" section above

10. **Check the dashboard**
    `GET /dashboard/stats`
    `GET /dashboard/activity`

11. **See what's working and grow the answer bank**
    `GET /learning/insights`
    `POST /learning/sync-answer-bank`
    `PATCH /knowledge/answers/{id}` — verify a new answer before it's reused

Every write endpoint also appends to `activity_log`, which is what powers the
dashboard timeline.

## Multi-tenancy model

Every table that holds user data carries a `user_id` foreign key, and every
router filters by `current_user.id` resolved from the JWT — no user can see
or modify another user's rows. `job_postings` is the one shared/global table
(the pool of jobs discovered from any source); each user's relevance
assessment against a posting lives in their own `job_matches` row.

## Project layout

```
job_agent/
├── app/
│   ├── main.py            FastAPI app, router wiring, table creation
│   ├── config.py          Settings loaded from .env
│   ├── database.py        SQLAlchemy engine/session
│   ├── models.py          Full ORM schema (11 tables)
│   ├── schemas.py         Pydantic request/response models
│   ├── auth.py            Password hashing + JWT
│   ├── deps.py            get_current_user dependency
│   ├── services/
│   │   ├── resume_parser.py    raw text -> structured resume JSON
│   │   ├── jd_analyzer.py      relevance scoring + skill matching
│   │   ├── resume_builder.py   tailoring + LaTeX render + PDF compile
│   │   ├── skills_data.py      curated skills taxonomy
│   │   ├── ingestion_service.py  orchestrates job-source adapters
│   │   ├── email_generator.py  template + optional Claude-assisted drafting
│   │   ├── email_sender.py     SMTP sending
│   │   ├── reply_classifier.py keyword-based reply classification
│   │   ├── learning_engine.py  insights report + answer-bank sync
│   │   └── job_sources/
│   │       ├── base.py         shared NormalizedJob shape
│   │       ├── adzuna.py       keyword search (needs API key)
│   │       ├── remoteok.py     keyword search (no key needed)
│   │       ├── greenhouse.py   per-company board
│   │       └── lever.py        per-company board
│   ├── templates/
│   │   └── resume_template.tex.jinja
│   └── routers/
│       ├── auth.py        register / login / me
│       ├── preferences.py
│       ├── resumes.py     master resume storage
│       ├── resume_engine.py  parse / analyze / generate / download
│       ├── jobs.py        job postings + per-user matches
│       ├── ingestion.py   list sources / trigger a search run
│       ├── applications.py
│       ├── contacts.py    HR contacts
│       ├── outreach.py    draft / send / follow-up / reply webhook
│       ├── knowledge.py   answer bank + verified candidate facts
│       ├── learning.py    insights report + answer-bank sync
│       └── dashboard.py   stats + activity timeline
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt   extra deps for running the test scripts (aiosmtpd)
└── .env.example
```

Test scripts at the repo root (`test_resume_engine.py`, `test_job_sources.py`,
`test_outreach.py`, `test_learning_loop.py`, plus `smoke_test.py` for the
full auth-through-dashboard flow) aren't part of the shipped app — they're
what was used to verify each phase actually works, and are safe to delete
or keep for regression-checking after you make changes.

## Running without Docker

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# make sure a MySQL server is reachable and .env points to it
uvicorn app.main:app --reload
```

## Before going to production

- Replace `Base.metadata.create_all` with **Alembic migrations**
  (`alembic init alembic`, generate a migration from the current models,
  and run `alembic upgrade head` on deploy instead of auto-creating tables).
- Set a strong random `SECRET_KEY` and real DB credentials — never reuse
  the `.env.example` values.
- Restrict CORS via the `CORS_ORIGINS` env var (comma-separated) to your
  actual frontend domain instead of the `*` default — see `DEPLOYMENT.md`
  step 4.
- Put this behind HTTPS (a reverse proxy like Caddy/nginx, or your PaaS's
  built-in TLS) before exposing it to the internet. Railway provides this
  automatically — see `DEPLOYMENT.md`.
- Add rate limiting on `/auth/login` and `/auth/register`.

See `DEPLOYMENT.md` for a full walkthrough of deploying this to Railway
alongside the frontend and a managed MySQL instance.

## Known limitations of the learning loop

- Needs real volume to say anything useful — the `applications >= 2` /
  `emails_sent >= 5` thresholds in `learning_engine.py` exist so it doesn't
  claim confidence from 1-2 data points, but that also means a brand-new
  account will mostly see "not enough data yet."
- Correlation, not causation: if "Python" applications did better, that
  might be because Python roles are just more available/less competitive
  right now, not because of anything about how you presented it. Treat
  `recommendations` as leads worth noticing, not verdicts.
- The subject-line keyword signal is a simple word-frequency comparison —
  it'll surface *something* even from noise at low volume; the `positive_occurrences >= 2`
  floor helps but doesn't eliminate that.
- `sync_answer_bank` matches questions by exact text after lowercasing/trimming
  — "What's your notice period?" and "What is your notice period?" are
  currently treated as different questions. `GET /knowledge/answers/match`'s
  fuzzy fallback helps at *lookup* time but sync itself doesn't merge near-duplicates.

## Known limitations of the outreach engine

- Reply tracking depends on you wiring an inbound-parse webhook from your
  email provider to `POST /outreach/reply-webhook` — without that connected,
  replies won't show up automatically (you can still call the endpoint
  manually/from a script to log one).
- The reply classifier is keyword-based; it will misclassify ambiguous or
  unusually-worded replies. Treat `reply_category` as a helpful first pass,
  not ground truth, especially early on.
- Follow-ups are manual-trigger only in this phase (`POST /outreach/follow-up/{id}`)
  — no scheduler is included yet to auto-send them after N days.
- The optional Claude-assisted drafting mode calls `api.anthropic.com`
  directly with your `ANTHROPIC_API_KEY`; check current model names at
  docs.claude.com before relying on the default in `.env.example`.

## Known limitations of the job ingestion module

- **Not tested against the live APIs from this build environment** — the
  sandbox that built this has no outbound network access to adzuna.com,
  greenhouse.io, lever.co, or remoteok.com. Each adapter is written to match
  its provider's documented response format exactly, and the normalization
  logic is verified with mocked responses (`test_job_sources.py`), but you
  should do one live `POST /ingestion/run` after deploying to confirm
  connectivity and current API shapes before relying on it.
- RemoteOK's API has no server-side keyword filter, so that adapter downloads
  the full current listing and filters by title client-side — fine at
  RemoteOK's current scale, worth revisiting if that changes.
- Greenhouse/Lever require you to already know which companies to watch —
  there's no cross-company search on either platform.

## Known limitations of the resume engine (be aware before relying on it)

- The parser is heuristic and will mis-segment unusual resume layouts —
  always review `parsed_json` (and fix via `PUT /resume-engine/master/parsed`)
  before generating a resume you'll actually submit somewhere.
- The skills taxonomy is a fixed list (`skills_data.py`); anything outside
  it won't be detected as a "skill" for scoring purposes — add to that list
  for your field as needed.
- Tailoring only reorders existing content; it will never write a bullet
  point, skill, or credential that wasn't already in your master resume.

## What's next

1. **Deployment** — see `DEPLOYMENT.md` in this repo for a full Railway
   walkthrough (backend + managed MySQL + the frontend, all in one project).
2. **Scheduling** — turning `POST /ingestion/run` and follow-up sending into
   scheduled jobs (cron or Celery beat) instead of manually triggered, once
   you're comfortable with how each behaves.
3. **LinkedIn/Naukri/Indeed coverage** — currently skipped since none of
   the three offer a self-serve API (see "Job ingestion" above); revisit
   with a manual/browser-capture tool or a paid third-party data provider
   if this becomes a priority.
