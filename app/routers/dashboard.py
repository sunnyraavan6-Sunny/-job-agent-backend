from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.deps import get_current_user
from app.models import (
    ActivityLog,
    Application,
    ApplicationStatus,
    HRContact,
    JobMatch,
    MatchStatus,
    OutreachEmail,
    OutreachStatus,
    User,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=schemas.DashboardStats)
def get_stats(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    uid = current_user.id

    jobs_discovered = db.query(func.count(JobMatch.id)).filter(JobMatch.user_id == uid).scalar() or 0
    jobs_relevant = (
        db.query(func.count(JobMatch.id))
        .filter(JobMatch.user_id == uid, JobMatch.status == MatchStatus.relevant)
        .scalar()
        or 0
    )
    jobs_applied = (
        db.query(func.count(JobMatch.id))
        .filter(JobMatch.user_id == uid, JobMatch.status == MatchStatus.applied)
        .scalar()
        or 0
    )

    def count_apps(status: ApplicationStatus) -> int:
        return (
            db.query(func.count(Application.id))
            .filter(Application.user_id == uid, Application.status == status)
            .scalar()
            or 0
        )

    applications_submitted = count_apps(ApplicationStatus.submitted)
    applications_in_progress = count_apps(ApplicationStatus.prepared) + count_apps(ApplicationStatus.viewed)
    interviews = count_apps(ApplicationStatus.interview)
    rejections = count_apps(ApplicationStatus.rejected)
    offers = count_apps(ApplicationStatus.offer)

    hr_contacts_discovered = db.query(func.count(HRContact.id)).filter(HRContact.user_id == uid).scalar() or 0
    emails_sent = (
        db.query(func.count(OutreachEmail.id))
        .filter(OutreachEmail.user_id == uid, OutreachEmail.status != OutreachStatus.draft)
        .scalar()
        or 0
    )
    emails_replied = (
        db.query(func.count(OutreachEmail.id))
        .filter(
            OutreachEmail.user_id == uid,
            OutreachEmail.status.in_(
                [OutreachStatus.replied_positive, OutreachStatus.replied_negative, OutreachStatus.replied_neutral]
            ),
        )
        .scalar()
        or 0
    )

    return schemas.DashboardStats(
        jobs_discovered=jobs_discovered,
        jobs_relevant=jobs_relevant,
        jobs_applied=jobs_applied,
        applications_submitted=applications_submitted,
        applications_in_progress=applications_in_progress,
        interviews=interviews,
        rejections=rejections,
        offers=offers,
        hr_contacts_discovered=hr_contacts_discovered,
        emails_sent=emails_sent,
        emails_replied=emails_replied,
    )


@router.get("/activity")
def get_activity_timeline(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entries = (
        db.query(ActivityLog)
        .filter(ActivityLog.user_id == current_user.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": e.id,
            "action_type": e.action_type,
            "description": e.description,
            "related_entity_type": e.related_entity_type,
            "related_entity_id": e.related_entity_id,
            "created_at": e.created_at,
        }
        for e in entries
    ]
