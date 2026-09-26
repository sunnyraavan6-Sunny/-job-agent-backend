"""
Builds a realistic synthetic history (several applications with different
skills/outcomes, several outreach emails with different reply outcomes) and
verifies the learning engine actually surfaces the correct patterns -- not
just that the endpoints return 200.
"""
import sys
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, ".")

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Application,
    ApplicationStatus,
    HRContact,
    JobMatch,
    JobPosting,
    OutreachEmail,
    OutreachStatus,
    User,
    UserPreference,
)
from app.auth import hash_password  # noqa: E402

engine = create_engine("sqlite:///./learning_test.db", connect_args={"check_same_thread": False})
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

# ---- seed a realistic history directly via the ORM (faster than 20 API calls) ----
db = TestingSessionLocal()

user = User(email="learner@example.com", hashed_password=hash_password("supersecret123"), full_name="Learner Test")
db.add(user)
db.commit()
db.refresh(user)
user_id = user.id
db.add(UserPreference(user_id=user.id))
db.commit()

# Python appears in 4 applications, 3 of which got interviews -> should surface as a strong skill.
# COBOL appears in 3 applications, 0 of which converted -> should surface as a weak skill.
scenarios = [
    ("Python", ApplicationStatus.interview),
    ("Python", ApplicationStatus.interview),
    ("Python", ApplicationStatus.interview),
    ("Python", ApplicationStatus.rejected),
    ("COBOL", ApplicationStatus.rejected),
    ("COBOL", ApplicationStatus.rejected),
    ("COBOL", ApplicationStatus.no_response),
]

for i, (skill, status) in enumerate(scenarios):
    posting = JobPosting(
        source="manual", external_id=f"seed-{i}", title=f"Engineer {i}", company=f"Company{i}",
        work_mode="remote",
    )
    db.add(posting)
    db.commit()
    db.refresh(posting)

    match = JobMatch(user_id=user.id, job_posting_id=posting.id, relevance_score=75, matched_skills=[skill])
    db.add(match)
    db.commit()
    db.refresh(match)

    application = Application(user_id=user.id, job_match_id=match.id, status=status)
    db.add(application)

db.commit()

# outreach: 3 emails with "quick question" subject all got positive replies;
# 3 emails with "following up" subject got none.
contact = HRContact(user_id=user.id, name="Test Recruiter", email="recruiter@example.com", company="Acme")
db.add(contact)
db.commit()
db.refresh(contact)

for i in range(3):
    db.add(OutreachEmail(
        user_id=user.id, hr_contact_id=contact.id,
        subject=f"Quick question about the role #{i}", body="...",
        status=OutreachStatus.replied_positive, replied_at=datetime.now(timezone.utc),
    ))
for i in range(3):
    db.add(OutreachEmail(
        user_id=user.id, hr_contact_id=contact.id,
        subject=f"Following up #{i}", body="...",
        status=OutreachStatus.sent,
    ))
db.commit()
db.close()

# ---- log in and hit the actual API endpoints -----------------------------
login_resp = client.post("/auth/login", data={"username": "learner@example.com", "password": "supersecret123"})
assert login_resp.status_code == 200, login_resp.text
token = login_resp.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

print("== GET /learning/insights ==")
resp = client.get("/learning/insights", headers=headers)
assert resp.status_code == 200, resp.text
insights = resp.json()

skill_perf = {row["skill"]: row for row in insights["skill_performance"]}
print("skill_performance:", skill_perf)
assert skill_perf["Python"]["success_rate"] == 0.75, skill_perf["Python"]
assert skill_perf["COBOL"]["success_rate"] == 0.0, skill_perf["COBOL"]
assert insights["skill_performance"][0]["skill"] == "Python", "Python should rank above COBOL"
print("OK  correctly identified Python as strong, COBOL as weak")

email_perf = insights["email_performance"]
print("email_performance:", email_perf)
assert email_perf["reply_rate"] == 0.5
signal_words = {s["word"] for s in email_perf["subject_keyword_signal"]}
assert "quick" in signal_words or "question" in signal_words, signal_words
print("OK  correctly surfaced 'quick'/'question' as a positive subject-line signal")

print("\nrecommendations:")
for rec in insights["recommendations"]:
    print(" -", rec)
assert any("Python" in r for r in insights["recommendations"])

print("\n== resume generation with use_learning picks up Python as a priority skill ==")
# give this user a master resume that includes both Python and COBOL, then
# analyze a Python-only JD -- with use_learning=True, COBOL should NOT be
# pulled in (it's not JD-relevant AND it has a 0% success rate), but if the
# JD were ambiguous, a historically strong skill the candidate has should
# still get a boost. Simpler, directly-testable claim: get_top_performing_skills
# returns Python and not COBOL.
from app.services.learning_engine import get_top_performing_skills  # noqa: E402

db2 = TestingSessionLocal()
top_skills = get_top_performing_skills(user_id, db2)
db2.close()
print("top_performing_skills:", top_skills)
assert "Python" in top_skills
assert "COBOL" not in top_skills
print("OK  get_top_performing_skills correctly excludes the 0%-success skill")

print("\n== POST /learning/sync-answer-bank + /knowledge/answers verify flow ==")
# record answers on one application, then sync
apps_resp = client.get("/applications", headers=headers)
app_id = apps_resp.json()[0]["id"]
client.patch(f"/applications/{app_id}/answers", headers=headers, json={
    "Are you authorized to work in this country?": "Yes",
    "What is your notice period?": "2 weeks",
})
# a second application answering the same question, to make it "recurring"
app_id_2 = apps_resp.json()[1]["id"]
client.patch(f"/applications/{app_id_2}/answers", headers=headers, json={
    "Are you authorized to work in this country?": "Yes",
})

sync_result = client.post("/learning/sync-answer-bank", headers=headers).json()
print("sync_result:", sync_result)
assert sync_result["new_questions_added"] == 2
assert sync_result["unverified_pending_review"] == 2

bank = client.get("/knowledge/answers", headers=headers).json()
assert len(bank) == 2
work_auth_entry = next(a for a in bank if "authorized" in a["question_text"].lower())
assert work_auth_entry["times_used"] == 2  # seen twice, and recurring-questions should reflect that
assert work_auth_entry["verified"] is False
print("OK  new answers land unverified, recurring question correctly counted twice")

verify_resp = client.patch(
    f"/knowledge/answers/{work_auth_entry['id']}", headers=headers, json={"verified": True}
)
assert verify_resp.json()["verified"] is True
print("OK  candidate can verify an answer via /knowledge/answers/{id}")

match_resp = client.get(
    "/knowledge/answers/match", headers=headers,
    params={"question": "Are you authorized to work in this country?"},
).json()
assert match_resp["found"] is True and match_resp["confidence"] == "exact"
print("OK  exact question match found via /knowledge/answers/match")

insights2 = client.get("/learning/insights", headers=headers).json()
recurring = insights2["recurring_questions"]
print("recurring_questions:", recurring)
assert any(q["times_seen"] == 2 and q["has_verified_answer"] for q in recurring)
print("OK  recurring question correctly flagged as now having a verified answer")

print("\nALL LEARNING-LOOP TESTS PASSED")
