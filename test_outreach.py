import asyncio
import sys
import threading
import time

sys.path.insert(0, ".")

from aiosmtpd.controller import Controller  # noqa: E402

from app.services.email_generator import EmailContext, generate_cold_email  # noqa: E402
from app.services.reply_classifier import classify_reply  # noqa: E402

print("== email generator (template mode) ==")
ctx = EmailContext(
    candidate_name="Jordan Lee",
    contact_name="Priya Sharma",
    contact_title="Technical Recruiter",
    company="Acme Corp",
    job_title="Backend Engineer",
    resume_summary="Backend engineer with 5 years of experience building scalable APIs.",
    matched_skills=["Python", "FastAPI", "PostgreSQL", "Kubernetes"],
    portfolio_links=["linkedin.com/in/jordanlee", "github.com/jordanlee"],
)
result = generate_cold_email(ctx)
print("method:", result["method"])
print("subject:", result["subject"])
print("body:\n", result["body"])
assert result["method"] == "template"  # no ANTHROPIC_API_KEY set in this test
assert "Jordan Lee" in result["body"]
assert "Python" in result["body"]
assert "Acme Corp" in result["subject"] or "Acme Corp" in result["body"]
print("OK  template email generated with real candidate data\n")


print("== reply classifier ==")
cases = [
    ("Thanks for reaching out, unfortunately we've decided to move forward with other candidates.", "rejection"),
    ("This looks great -- are you available for a call next Tuesday to discuss next steps?", "interview_opportunity"),
    ("Not interested, please remove me from your list.", "negative"),
    ("Thanks, this sounds good, let's connect!", "positive"),
    ("Can you tell me your notice period?", "action_required"),
    ("", "neutral"),
]
for text, expected in cases:
    result = classify_reply(text)
    status = "OK " if result["category"] == expected else "FAIL"
    print(f"{status} '{text[:50]}...' -> {result}")
    assert result["category"] == expected, f"expected {expected}, got {result}"
print("OK  all classifier cases passed\n")


print("== SMTP sender (against a local test server) ==")

received_messages = []


class PrintHandler:
    async def handle_DATA(self, server, session, envelope):
        received_messages.append({
            "mail_from": envelope.mail_from,
            "rcpt_tos": envelope.rcpt_tos,
            "content": envelope.content.decode("utf8", errors="replace"),
        })
        return "250 Message accepted for delivery"


controller = Controller(PrintHandler(), hostname="127.0.0.1", port=1025)
controller.start()
time.sleep(0.3)

try:
    # point our sender at the local test server (no auth, no TLS)
    from app.config import settings
    settings.smtp_host = "127.0.0.1"
    settings.smtp_port = 1025
    settings.smtp_username = "test"
    settings.smtp_password = "test"
    settings.smtp_use_tls = False
    settings.smtp_from_email = "agent@example.com"
    settings.smtp_from_name = "Job Agent"

    # aiosmtpd's default handler doesn't require auth -- patch smtplib.login to no-op for this local test
    import smtplib
    smtplib.SMTP.login = lambda self, *a, **k: (235, b"OK")

    from app.services.email_sender import send_email
    success, message, message_id = send_email("recruiter@acme.example.com", "Test Subject", "Test body content")
    print("success:", success, "message:", message, "message_id:", message_id)
    assert success, message
    assert message_id is not None
    assert len(received_messages) == 1
    assert "Test Subject" in received_messages[0]["content"]
    assert "recruiter@acme.example.com" in received_messages[0]["rcpt_tos"]
    print("OK  email actually sent through SMTP and received by test server\n")
finally:
    controller.stop()

print("ALL OUTREACH SERVICE-LAYER TESTS PASSED")
