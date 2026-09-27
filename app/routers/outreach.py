from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import (
    ActivityLog,
    HRContact,
    JobMatch,
    MasterResume,
    OutreachEmail,
    OutreachStatus,
    User,
)
from app.services.email_generator import EmailContext, generate_cold_email
from app.services.email_sender import is_smtp_configured, send_email
from app.services.reply_classifier import classify_reply

router = APIRouter(prefix="/outreach", tags=["outreach"])


# ---- schemas -----------------------------------------------------------

class OutreachEmailOut(BaseModel):
    id: int
    hr_contact_id: int
    job_match_id: Optional[int] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    status: str
    follow_up_count: int
    reply_category: Optional[str] = None
    sent_at: Optional[datetime] = None
    replied_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ReplyWebhookPayload(BaseModel):
    """
    Shape modeled on common inbound-parse webhooks (SendGrid/Mailgun/Postmark
    all provide these fields in some form). Point your provider's inbound
    webhook at whatever endpoint wraps this, mapped to this shape.
    """
    in_reply_to: Optional[str] = None   # the Message-ID header this is replying to
    from_email: str
    subject: Optional[str] = None
    text_body: str


# ---- helpers -------------------------------------------------------------

def _get_contact_or_404(contact_id: int, user: User, db: Session) -> HRContact:
    contact = db.query(HRContact).filter(HRContact.id == contact_id, HRContact.user_id == user.id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="HR contact not found")
    return contact


# ---- drafting -----------------------------------------------------------

@router.post("/draft/{hr_contact_id}", response_model=OutreachEmailOut, status_code=201)
def draft_cold_email(
    hr_contact_id: int,
    job_match_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = _get_contact_or_404(hr_contact_id, current_user, db)

    job_match = None
    if job_match_id is not None:
        job_match = (
            db.query(JobMatch)
            .filter(JobMatch.id == job_match_id, JobMatch.user_id == current_user.id)
            .first()
        )
        if not job_match:
            raise HTTPException(status_code=404, detail="Job match not found")

    master_resume = (
        db.query(MasterResume)
        .filter(MasterResume.user_id == current_user.id, MasterResume.is_active == True)  # noqa: E712
        .first()
    )
    parsed = master_resume.parsed_json if master_resume else None

    portfolio_links = []
    if parsed:
        contact_info = parsed.get("contact", {})
        for key in ("linkedin", "github"):
            if contact_info.get(key):
                portfolio_links.append(contact_info[key])

    ctx = EmailContext(
        candidate_name=current_user.full_name or current_user.email,
        contact_name=contact.name,
        contact_title=contact.title,
        company=contact.company or (job_match.job_posting.company if job_match else "your company"),
        job_title=job_match.job_posting.title if job_match else None,
        resume_summary=parsed.get("summary") if parsed else None,
        matched_skills=job_match.matched_skills if job_match else [],
        portfolio_links=portfolio_links,
    )
    generated = generate_cold_email(ctx)

    email = OutreachEmail(
        user_id=current_user.id,
        hr_contact_id=contact.id,
        job_match_id=job_match.id if job_match else None,
        subject=generated["subject"],
        body=generated["body"],
        status=OutreachStatus.draft,
        generation_method=generated["method"],
    )
    db.add(email)
    db.commit()
    db.refresh(email)

    db.add(ActivityLog(
        user_id=current_user.id,
        action_type="cold_email_drafted",
        description=f"Drafted outreach email to {contact.name or contact.email} ({generated['method']})",
        related_entity_type="outreach_email",
        related_entity_id=email.id,
    ))
    db.commit()

    return email


# ---- sending -----------------------------------------------------------

@router.post("/send/{outreach_email_id}", response_model=OutreachEmailOut)
def send_outreach_email(
    outreach_email_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    email = (
        db.query(OutreachEmail)
        .filter(OutreachEmail.id == outreach_email_id, OutreachEmail.user_id == current_user.id)
        .first()
    )
    if not email:
        raise HTTPException(status_code=404, detail="Outreach email not found")
    if email.status != OutreachStatus.draft:
        raise HTTPException(status_code=400, detail=f"Email already in status '{email.status.value}', not draft")

    contact = db.query(HRContact).filter(HRContact.id == email.hr_contact_id).first()
    if not contact or not contact.email:
        raise HTTPException(status_code=400, detail="This HR contact has no email address on file")

    success, message, message_id = send_email(contact.email, email.subject, email.body)
    if not success:
        raise HTTPException(status_code=502, detail=message)

    email.status = OutreachStatus.sent
    email.sent_at = datetime.now(timezone.utc)
    email.message_id = message_id
    db.commit()
    db.refresh(email)

    db.add(ActivityLog(
        user_id=current_user.id,
        action_type="cold_email_sent",
        description=f"Sent outreach email to {contact.email}",
        related_entity_type="outreach_email",
        related_entity_id=email.id,
    ))
    db.commit()

    return email


@router.get("/smtp-status")
def smtp_status():
    return {"configured": is_smtp_configured()}


# ---- follow-ups -----------------------------------------------------------

@router.get("/pending-followups", response_model=list[OutreachEmailOut])
def list_pending_followups(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.follow_up_after_days)
    return (
        db.query(OutreachEmail)
        .filter(
            OutreachEmail.user_id == current_user.id,
            OutreachEmail.status == OutreachStatus.sent,
            OutreachEmail.sent_at <= cutoff,
        )
        .all()
    )


@router.post("/follow-up/{outreach_email_id}", response_model=OutreachEmailOut)
def send_follow_up(
    outreach_email_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    email = (
        db.query(OutreachEmail)
        .filter(OutreachEmail.id == outreach_email_id, OutreachEmail.user_id == current_user.id)
        .first()
    )
    if not email:
        raise HTTPException(status_code=404, detail="Outreach email not found")
    if email.status != OutreachStatus.sent:
        raise HTTPException(status_code=400, detail="Can only follow up on emails with status 'sent' (no reply yet)")

    contact = db.query(HRContact).filter(HRContact.id == email.hr_contact_id).first()
    follow_up_body = (
        f"Hi{' ' + contact.name if contact and contact.name else ''},\n\n"
        f"Just wanted to bump this to the top of your inbox in case it got buried -- "
        f"still very interested and happy to answer any questions.\n\n"
        f"Best,\n{current_user.full_name or current_user.email}"
    )
    follow_up_subject = f"Re: {email.subject}"

    success, message, _ = send_email(contact.email, follow_up_subject, follow_up_body)
    if not success:
        raise HTTPException(status_code=502, detail=message)

    email.follow_up_count += 1
    db.commit()
    db.refresh(email)

    db.add(ActivityLog(
        user_id=current_user.id,
        action_type="follow_up_sent",
        description=f"Sent follow-up #{email.follow_up_count} to {contact.email if contact else 'contact'}",
        related_entity_type="outreach_email",
        related_entity_id=email.id,
    ))
    db.commit()

    return email


# ---- inbound reply handling -----------------------------------------------

@router.post("/reply-webhook")
def handle_reply_webhook(payload: ReplyWebhookPayload, db: Session = Depends(get_db)):
    """
    Point your email provider's inbound-parse webhook here (adapt the payload
    shape per-provider upstream if needed). Matches the reply to a sent
    OutreachEmail by Message-ID first, falling back to the contact's email
    address if no thread header is available.
    """
    email = None
    if payload.in_reply_to:
        email = db.query(OutreachEmail).filter(OutreachEmail.message_id == payload.in_reply_to).first()

    if not email:
        contact = db.query(HRContact).filter(HRContact.email == payload.from_email).first()
        if contact:
            email = (
                db.query(OutreachEmail)
                .filter(OutreachEmail.hr_contact_id == contact.id, OutreachEmail.status == OutreachStatus.sent)
                .order_by(OutreachEmail.sent_at.desc())
                .first()
            )

    if not email:
        raise HTTPException(status_code=404, detail="Could not match this reply to a sent outreach email")

    classification = classify_reply(payload.text_body)
    email.status = OutreachStatus(classification["outreach_status"])
    email.reply_category = classification["category"]
    email.reply_excerpt = payload.text_body[:1000]
    email.replied_at = datetime.now(timezone.utc)
    db.commit()

    db.add(ActivityLog(
        user_id=email.user_id,
        action_type="recruiter_response_received",
        description=f"Reply received, classified as '{classification['category']}'",
        related_entity_type="outreach_email",
        related_entity_id=email.id,
    ))
    db.commit()

    return {"matched_outreach_email_id": email.id, "classification": classification}


# ---- listing -----------------------------------------------------------

@router.get("", response_model=list[OutreachEmailOut])
def list_outreach_emails(
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(OutreachEmail).filter(OutreachEmail.user_id == current_user.id)
    if status_filter:
        query = query.filter(OutreachEmail.status == status_filter)
    return query.order_by(OutreachEmail.created_at.desc()).all()
