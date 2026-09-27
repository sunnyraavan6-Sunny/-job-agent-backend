"""
Mines the candidate's own history (applications, resume versions, outreach
emails, replies) for patterns that predict success, per spec section 3:
"identify which resume formats/skills/email formats/subject lines/cover-letter
structures perform better... without changing factual information."

Everything here is descriptive statistics over the user's own data -- no
external model, nothing invented. Two outputs:
  1. generate_insights() -- a read-only report: which skills/attributes
     correlate with interviews/offers vs rejections/silence.
  2. sync_answer_bank() -- scans past application answers, grows the reusable
     ApplicationAnswer bank, and flags brand-new recurring questions that
     need the candidate's confirmation before being reused (per spec:
     "for uncertain or sensitive questions, request user confirmation
     rather than making up information").
"""
from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from app.models import (
    Application,
    ApplicationAnswer,
    ApplicationStatus,
    JobMatch,
    JobPosting,
    OutreachEmail,
    OutreachStatus,
    ResumeVersion,
)

# Statuses that count as a meaningfully positive outcome for correlation purposes.
_POSITIVE_APP_STATUSES = {ApplicationStatus.interview, ApplicationStatus.offer}
_NEGATIVE_APP_STATUSES = {ApplicationStatus.rejected}
_POSITIVE_OUTREACH_STATUSES = {OutreachStatus.replied_positive}


def _success_rate(hits: int, total: int) -> float:
    return round(hits / total, 3) if total else 0.0


def _skill_performance(applications: list[Application]) -> list[dict]:
    """
    For each skill that appeared in a job match's matched_skills, count how
    many applications involving that skill turned into an interview/offer
    vs a rejection, vs are still pending/no response.
    """
    per_skill_total = Counter()
    per_skill_positive = Counter()
    per_skill_negative = Counter()

    for app in applications:
        job_match = app.job_match
        if not job_match or not job_match.matched_skills:
            continue
        for skill in job_match.matched_skills:
            per_skill_total[skill] += 1
            if app.status in _POSITIVE_APP_STATUSES:
                per_skill_positive[skill] += 1
            elif app.status in _NEGATIVE_APP_STATUSES:
                per_skill_negative[skill] += 1

    results = []
    for skill, total in per_skill_total.items():
        if total < 1:
            continue
        results.append({
            "skill": skill,
            "applications": total,
            "interviews_or_offers": per_skill_positive[skill],
            "rejections": per_skill_negative[skill],
            "success_rate": _success_rate(per_skill_positive[skill], total),
        })

    # Only surface skills with enough data to mean something, most successful first.
    results = [r for r in results if r["applications"] >= 2]
    results.sort(key=lambda r: (-r["success_rate"], -r["applications"]))
    return results


def _job_attribute_performance(applications: list[Application]) -> dict:
    by_work_mode = defaultdict(lambda: {"total": 0, "positive": 0})
    by_company = defaultdict(lambda: {"total": 0, "positive": 0})

    for app in applications:
        posting = app.job_match.job_posting if app.job_match else None
        if not posting:
            continue
        is_positive = app.status in _POSITIVE_APP_STATUSES

        mode_key = posting.work_mode or "unspecified"
        by_work_mode[mode_key]["total"] += 1
        by_work_mode[mode_key]["positive"] += int(is_positive)

        by_company[posting.company]["total"] += 1
        by_company[posting.company]["positive"] += int(is_positive)

    def _finalize(d: dict) -> list[dict]:
        out = [
            {"key": k, "applications": v["total"], "success_rate": _success_rate(v["positive"], v["total"])}
            for k, v in d.items()
        ]
        out.sort(key=lambda r: -r["success_rate"])
        return out

    return {"by_work_mode": _finalize(by_work_mode), "by_company": _finalize(by_company)}


def _resume_version_performance(applications: list[Application]) -> list[dict]:
    results = []
    for app in applications:
        if not app.resume_version_id:
            continue
        version: ResumeVersion | None = (
            next((v for v in (app.job_match.resume_versions if app.job_match else []) if v.id == app.resume_version_id), None)
        )
        emphasized = (version.emphasis_notes or {}).get("skills_prioritized", []) if version else []
        results.append({
            "application_id": app.id,
            "resume_version_id": app.resume_version_id,
            "skills_emphasized": emphasized,
            "outcome": app.status.value,
            "was_positive": app.status in _POSITIVE_APP_STATUSES,
        })
    return results


def _email_performance(outreach_emails: list[OutreachEmail]) -> dict:
    sent = [e for e in outreach_emails if e.status != OutreachStatus.draft]
    if not sent:
        return {"emails_sent": 0, "reply_rate": 0.0, "positive_reply_rate": 0.0, "subject_keyword_signal": []}

    replied = [e for e in sent if e.replied_at is not None]
    positive = [e for e in sent if e.status in _POSITIVE_OUTREACH_STATUSES]

    # crude subject-line keyword signal: words that appear disproportionately
    # often in subjects of emails that got a positive reply vs those that didn't.
    positive_words = Counter()
    other_words = Counter()
    for e in sent:
        words = {w.strip(".,!?").lower() for w in (e.subject or "").split() if len(w) > 3}
        bucket = positive_words if e.status in _POSITIVE_OUTREACH_STATUSES else other_words
        bucket.update(words)

    signal = []
    for word, count in positive_words.items():
        if count >= 2 and count > other_words.get(word, 0):
            signal.append({"word": word, "positive_occurrences": count, "other_occurrences": other_words.get(word, 0)})
    signal.sort(key=lambda x: -x["positive_occurrences"])

    return {
        "emails_sent": len(sent),
        "reply_rate": _success_rate(len(replied), len(sent)),
        "positive_reply_rate": _success_rate(len(positive), len(sent)),
        "subject_keyword_signal": signal[:10],
    }


def _recurring_questions(applications: list[Application], answer_bank: list[ApplicationAnswer]) -> list[dict]:
    question_counts = Counter()
    for app in applications:
        if not app.application_data:
            continue
        for question in app.application_data.keys():
            question_counts[question] += 1

    verified_questions = {a.question_text.strip().lower() for a in answer_bank if a.verified}

    recurring = []
    for question, count in question_counts.items():
        if count < 2:
            continue
        recurring.append({
            "question": question,
            "times_seen": count,
            "has_verified_answer": question.strip().lower() in verified_questions,
        })
    recurring.sort(key=lambda r: -r["times_seen"])
    return recurring


def _build_recommendations(skill_perf: list[dict], email_perf: dict, job_attr_perf: dict) -> list[str]:
    recs = []
    if skill_perf:
        top = skill_perf[0]
        recs.append(
            f"'{top['skill']}' has your highest interview/offer rate so far "
            f"({top['success_rate']*100:.0f}% across {top['applications']} applications) -- "
            f"keep it prominent in your resume and outreach when relevant."
        )
        weak = [s for s in skill_perf if s["success_rate"] == 0 and s["applications"] >= 3]
        if weak:
            recs.append(
                f"Applications emphasizing {', '.join(s['skill'] for s in weak[:3])} haven't converted yet "
                f"({weak[0]['applications']}+ tries each) -- worth deprioritizing these or pairing them with "
                f"stronger skills in future tailoring."
            )
    if email_perf.get("emails_sent", 0) >= 5:
        recs.append(
            f"Outreach reply rate is currently {email_perf['reply_rate']*100:.0f}% "
            f"({email_perf['positive_reply_rate']*100:.0f}% positive)."
        )
        if email_perf.get("subject_keyword_signal"):
            words = ", ".join(s["word"] for s in email_perf["subject_keyword_signal"][:3])
            recs.append(f"Subject lines containing '{words}' have gotten more positive replies than others.")
    for group_name, rows in job_attr_perf.items():
        if rows and rows[0]["applications"] >= 3:
            recs.append(
                f"Best-performing {group_name.replace('by_', '')}: '{rows[0]['key']}' "
                f"({rows[0]['success_rate']*100:.0f}% success over {rows[0]['applications']} applications)."
            )
    if not recs:
        recs.append("Not enough historical data yet for reliable patterns -- check back after a few more applications.")
    return recs


def generate_insights(user_id: int, db: Session) -> dict:
    applications = (
        db.query(Application)
        .filter(Application.user_id == user_id)
        .all()
    )
    outreach_emails = db.query(OutreachEmail).filter(OutreachEmail.user_id == user_id).all()
    answer_bank = db.query(ApplicationAnswer).filter(ApplicationAnswer.user_id == user_id).all()

    skill_perf = _skill_performance(applications)
    job_attr_perf = _job_attribute_performance(applications)
    resume_perf = _resume_version_performance(applications)
    email_perf = _email_performance(outreach_emails)
    recurring_questions = _recurring_questions(applications, answer_bank)

    return {
        "sample_size": {
            "applications": len(applications),
            "outreach_emails": len([e for e in outreach_emails if e.status != OutreachStatus.draft]),
        },
        "skill_performance": skill_perf,
        "job_attribute_performance": job_attr_perf,
        "resume_version_performance": resume_perf,
        "email_performance": email_perf,
        "recurring_questions": recurring_questions,
        "recommendations": _build_recommendations(skill_perf, email_perf, job_attr_perf),
    }


def get_top_performing_skills(user_id: int, db: Session, limit: int = 10) -> list[str]:
    """Convenience used by the resume/email generators to weight toward what's actually worked."""
    applications = db.query(Application).filter(Application.user_id == user_id).all()
    ranked = _skill_performance(applications)
    return [r["skill"] for r in ranked if r["success_rate"] > 0][:limit]


def sync_answer_bank(user_id: int, db: Session) -> dict:
    """
    Scans every application's recorded Q&A and upserts into the reusable
    ApplicationAnswer bank. New questions are added as UNVERIFIED -- they
    won't be silently reused until the candidate confirms them via
    PATCH /learning/answer-bank/{id}/verify.
    """
    applications = db.query(Application).filter(Application.user_id == user_id).all()
    existing = {
        a.question_text.strip().lower(): a
        for a in db.query(ApplicationAnswer).filter(ApplicationAnswer.user_id == user_id).all()
    }

    new_count = 0
    updated_count = 0

    for app in applications:
        if not app.application_data:
            continue
        for question, answer in app.application_data.items():
            if not question or not answer:
                continue
            key = question.strip().lower()
            if key in existing:
                existing[key].times_used += 1
                updated_count += 1
            else:
                entry = ApplicationAnswer(
                    user_id=user_id,
                    question_text=question.strip(),
                    answer_text=str(answer).strip(),
                    verified=False,
                    times_used=1,
                )
                db.add(entry)
                existing[key] = entry
                new_count += 1

    db.commit()
    return {
        "new_questions_added": new_count,
        "existing_questions_updated": updated_count,
        "unverified_pending_review": sum(1 for a in existing.values() if not a.verified),
    }
