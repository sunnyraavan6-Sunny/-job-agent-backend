"""
Local smoke test: validates the app boots, tables create, and the core
register -> login -> preferences -> resume -> job -> match -> application ->
dashboard flow works end to end. Uses SQLite in place of MySQL purely so this
can run without a MySQL server; the production path (docker-compose) uses
real MySQL via the same SQLAlchemy models.
"""
import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, ".")

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

engine = create_engine("sqlite:///./smoke_test.db", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def check(label, resp, expect=200):
    ok = resp.status_code == expect
    print(f"{'OK ' if ok else 'FAIL'} {label}: {resp.status_code}")
    if not ok:
        print("   ->", resp.text)
        sys.exit(1)
    return resp.json()


print("== health ==")
check("health check", client.get("/health"))

print("== auth ==")
check("register", client.post("/auth/register", json={
    "email": "candidate@example.com", "password": "supersecret123", "full_name": "Test Candidate"
}), expect=201)

login_resp = check("login", client.post("/auth/login", data={
    "username": "candidate@example.com", "password": "supersecret123"
}))
token = login_resp["access_token"]
headers = {"Authorization": f"Bearer {token}"}

check("me", client.get("/auth/me", headers=headers))

print("== preferences ==")
check("update preferences", client.put("/preferences", headers=headers, json={
    "target_titles": ["Backend Engineer", "Python Developer"],
    "preferred_locations": ["Remote", "Hyderabad"],
    "experience_level": "mid",
    "salary_min": 1500000,
    "salary_max": 2500000,
    "work_preference": "remote",
    "max_applications_per_day": 15,
    "max_applications_per_portal": 5,
    "allowed_portals": ["linkedin", "indeed"],
    "operating_mode": "approval",
}))

print("== master resume ==")
check("upload master resume", client.post("/resumes", headers=headers, json={
    "raw_text": "Experienced Python backend engineer with FastAPI, MySQL, AWS..."
}), expect=201)
check("get active resume", client.get("/resumes/active", headers=headers))

print("== job posting + match ==")
posting = check("ingest job posting", client.post("/jobs/postings", json={
    "source": "greenhouse", "external_id": "gh-12345",
    "title": "Backend Engineer", "company": "Acme Corp",
    "location": "Remote", "work_mode": "remote",
    "description": "Looking for a Python/FastAPI engineer...",
    "url": "https://example.com/jobs/12345",
}), expect=201)

match = check("create match", client.post(
    f"/jobs/matches/{posting['id']}?relevance_score=82", headers=headers
), expect=201)

check("list matches", client.get("/jobs/matches", headers=headers))

print("== application lifecycle ==")
application = check("create application", client.post(
    f"/applications/from-match/{match['id']}?portal=greenhouse", headers=headers
), expect=201)

check("mark submitted", client.patch(
    f"/applications/{application['id']}/status", headers=headers,
    json={"status": "submitted"}
))
check("mark interview", client.patch(
    f"/applications/{application['id']}/status", headers=headers,
    json={"status": "interview", "result_notes": "Phone screen scheduled"}
))

print("== resume engine ==")
parsed = check("parse master resume", client.post("/resume-engine/parse-master", headers=headers))
print("   parsed skills:", parsed["parsed_json"].get("skills"))

analysis = check("analyze job posting", client.post(
    f"/resume-engine/analyze/{posting['id']}", headers=headers
))
print("   relevance:", analysis["relevance_score"], "matched:", analysis["matched_skills"])

version = check("generate tailored resume", client.post(
    f"/resume-engine/generate/{analysis['job_match_id']}", headers=headers
), expect=201)
print("   pdf_available:", version["pdf_available"], "log:", version.get("log_message"))

check("list resume versions", client.get(f"/resume-engine/versions/{analysis['job_match_id']}", headers=headers))

if version["pdf_available"]:
    dl = client.get(f"/resume-engine/download/{version['id']}", headers=headers)
    print(f"   OK  download resume PDF: {dl.status_code}, {len(dl.content)} bytes")
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/pdf"
else:
    print("   SKIP download check: PDF was not compiled in this environment")

print("== ingestion (via API, sources mocked) ==")
from unittest.mock import patch as _patch
from app.services.job_sources.base import NormalizedJob as _NJ

# tracked companies + allowed portals
check("set preferences for ingestion", client.put("/preferences", headers=headers, json={
    "target_titles": ["Backend Engineer"],
    "preferred_locations": ["Remote"],
    "experience_level": "mid",
    "allowed_portals": ["remoteok", "greenhouse"],
    "tracked_companies": {"greenhouse": ["acme"]},
    "operating_mode": "approval",
}))

mock_remoteok_jobs = [_NJ(
    source="remoteok", external_id="rok-1", title="Backend Engineer", company="RemoteCo",
    location="Worldwide", work_mode="remote", description="Python, FastAPI, PostgreSQL role",
    url="https://remoteok.com/remote-jobs/rok-1",
)]
mock_greenhouse_jobs = [_NJ(
    source="greenhouse", external_id="gh-1", title="Backend Engineer", company="acme",
    location="Remote", work_mode="remote", description="FastAPI and Kubernetes experience needed",
    url="https://boards.greenhouse.io/acme/jobs/gh-1",
)]

with _patch("app.services.ingestion_service.remoteok.search", return_value=(mock_remoteok_jobs, None)), \
     _patch("app.services.ingestion_service.greenhouse.fetch_company_jobs", return_value=(mock_greenhouse_jobs, None)):
    result = check("run ingestion", client.post("/ingestion/run", headers=headers))
    print("   ", result)
    assert result["jobs_found"] == 2
    assert result["new_postings"] == 2
    assert result["matches_created"] == 2  # active master resume + parsed_json already set earlier
    assert result["source_errors"] == {}

    # run again -- should dedupe to zero new postings/matches
    result2 = check("run ingestion again (dedupe check)", client.post("/ingestion/run", headers=headers))
    print("   ", result2)
    assert result2["new_postings"] == 0
    assert result2["matches_created"] == 0

check("list sources", client.get("/ingestion/sources"))

print("== outreach engine ==")
import smtplib as _smtplib
from aiosmtpd.controller import Controller as _Controller

_received = []


class _Handler:
    async def handle_DATA(self, server, session, envelope):
        _received.append(envelope.content.decode("utf8", errors="replace"))
        return "250 Message accepted for delivery"


_controller = _Controller(_Handler(), hostname="127.0.0.1", port=1026)
_controller.start()
import time as _time
_time.sleep(0.3)
_smtplib.SMTP.login = lambda self, *a, **k: (235, b"OK")

from app.config import settings as _settings
_settings.smtp_host = "127.0.0.1"
_settings.smtp_port = 1026
_settings.smtp_username = "test"
_settings.smtp_password = "test"
_settings.smtp_use_tls = False
_settings.smtp_from_email = "agent@example.com"
_settings.smtp_from_name = "Job Agent"

try:
    check("smtp status", client.get("/outreach/smtp-status"))

    contact = check("add contact for outreach", client.post("/contacts", headers=headers, json={
        "name": "Priya Sharma", "title": "Technical Recruiter", "company": "Acme Corp",
        "email": "priya@acme.example.com", "source": "linkedin",
    }), expect=201)

    draft = check("draft cold email", client.post(
        f"/outreach/draft/{contact['id']}?job_match_id={analysis['job_match_id']}", headers=headers
    ), expect=201)
    print("   subject:", draft["subject"])
    assert draft["status"] == "draft"

    sent = check("send cold email", client.post(f"/outreach/send/{draft['id']}", headers=headers))
    assert sent["status"] == "sent"
    assert len(_received) == 1 and "Acme" in _received[0]
    print("   OK  email actually delivered to test SMTP server")

    followups = check("list pending followups (should be empty, just sent)", client.get(
        "/outreach/pending-followups", headers=headers
    ))
    assert followups == []

    reply_result = check("simulate inbound reply webhook", client.post("/outreach/reply-webhook", json={
        "from_email": "priya@acme.example.com",
        "subject": "Re: interest",
        "text_body": "This looks great, are you available for a call next week to discuss next steps?",
    }))
    print("   classification:", reply_result["classification"])
    assert reply_result["classification"]["category"] == "interview_opportunity"

    updated = check("list outreach emails", client.get("/outreach", headers=headers))
    assert updated[0]["status"] == "replied_positive"
    print("   OK  reply correctly matched and classified end-to-end")
finally:
    _controller.stop()

print("== hr contact ==")
check("add contact", client.post("/contacts", headers=headers, json={
    "name": "Jane Recruiter", "title": "Talent Acquisition", "company": "Acme Corp",
    "email": "jane@acme.example.com", "source": "linkedin",
}), expect=201)

print("== dashboard ==")
stats = check("dashboard stats", client.get("/dashboard/stats", headers=headers))
print("   stats:", stats)
activity = check("activity timeline", client.get("/dashboard/activity", headers=headers))
print(f"   {len(activity)} activity log entries")

print("\nALL CHECKS PASSED")
