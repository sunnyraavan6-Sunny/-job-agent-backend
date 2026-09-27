"""
Generates a personalized cold outreach email from real candidate/job/contact
data -- either via a set of varied templates (default, free, offline) or,
if ANTHROPIC_API_KEY is configured, via the Claude API for more natural
phrasing (falls back to the template on any error).

Either way, this only ever asks the model to *phrase* facts you already
provided (name, company, matched skills, resume summary) -- it's not
generating claims about the candidate that didn't come from their data.
"""
import random
from dataclasses import dataclass
from typing import Optional

import requests

from app.config import settings


@dataclass
class EmailContext:
    candidate_name: str
    contact_name: Optional[str]
    contact_title: Optional[str]
    company: str
    job_title: Optional[str]
    resume_summary: Optional[str]
    matched_skills: list[str]
    portfolio_links: list[str]


_OPENERS = [
    "I came across the {job_title} opening at {company} and wanted to reach out directly.",
    "I've been following {company}'s work and noticed you're hiring for a {job_title} role.",
    "Your {job_title} posting caught my eye, and I wanted to introduce myself.",
]

_CLOSERS = [
    "Would you be open to a short call this week to discuss the role?",
    "I'd welcome the chance to talk more about how I could contribute to the team.",
    "Happy to share more detail whenever works for you -- let me know if a quick call makes sense.",
]


def _template_email(ctx: EmailContext) -> tuple[str, str]:
    greeting = f"Hi {ctx.contact_name}," if ctx.contact_name else "Hi,"
    job_title = ctx.job_title or "open role"
    opener = random.choice(_OPENERS).format(job_title=job_title, company=ctx.company)
    closer = random.choice(_CLOSERS)

    skill_line = ""
    if ctx.matched_skills:
        top_skills = ", ".join(ctx.matched_skills[:5])
        skill_line = f" My background includes hands-on experience with {top_skills}."

    summary_line = f" {ctx.resume_summary.strip()}" if ctx.resume_summary else ""

    links_line = ""
    if ctx.portfolio_links:
        links_line = "\n\n" + "\n".join(ctx.portfolio_links)

    body = (
        f"{greeting}\n\n"
        f"{opener}{summary_line}{skill_line}\n\n"
        f"{closer}\n\n"
        f"Best,\n{ctx.candidate_name}"
        f"{links_line}"
    )
    subject = f"{ctx.candidate_name} -- Interest in {job_title} at {ctx.company}"
    return subject, body


def _llm_email(ctx: EmailContext) -> Optional[tuple[str, str]]:
    if not settings.anthropic_api_key:
        return None

    prompt = f"""Write a short, natural, human-sounding cold outreach email from a job candidate to a recruiter.
Use ONLY the facts given below -- do not invent experience, employers, or skills not listed.

Candidate name: {ctx.candidate_name}
Recruiter name: {ctx.contact_name or "unknown, use a generic greeting"}
Recruiter title: {ctx.contact_title or "unknown"}
Company: {ctx.company}
Job title: {ctx.job_title or "an open role"}
Candidate summary: {ctx.resume_summary or "not provided"}
Relevant matched skills: {", ".join(ctx.matched_skills) if ctx.matched_skills else "not provided"}
Portfolio/profile links to include verbatim at the end: {", ".join(ctx.portfolio_links) if ctx.portfolio_links else "none"}

Keep it under 130 words, concise and specific, not generic or template-sounding.
Respond with exactly two lines:
SUBJECT: <subject line>
BODY: <email body, with \\n for line breaks>"""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.anthropic_model,
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")

        subject_line = next((l for l in text.splitlines() if l.upper().startswith("SUBJECT:")), None)
        body_line = next((l for l in text.splitlines() if l.upper().startswith("BODY:")), None)
        if not subject_line or not body_line:
            return None

        subject = subject_line.split(":", 1)[1].strip()
        body = body_line.split(":", 1)[1].strip().replace("\\n", "\n")
        return subject, body
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def generate_cold_email(ctx: EmailContext) -> dict:
    llm_result = _llm_email(ctx)
    if llm_result:
        subject, body = llm_result
        return {"subject": subject, "body": body, "method": "llm"}

    subject, body = _template_email(ctx)
    return {"subject": subject, "body": body, "method": "template"}
