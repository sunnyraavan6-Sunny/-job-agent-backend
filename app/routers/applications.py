from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.deps import get_current_user
from app.models import ActivityLog, Application, ApplicationStatus, JobMatch, MatchStatus, User

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("/from-match/{job_match_id}", response_model=schemas.ApplicationOut, status_code=201)
def create_application(
    job_match_id: int,
    portal: str | None = None,
    resume_version_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    match = (
        db.query(JobMatch)
        .filter(JobMatch.id == job_match_id, JobMatch.user_id == current_user.id)
        .first()
    )
    if not match:
        raise HTTPException(status_code=404, detail="Job match not found")

    existing = db.query(Application).filter(Application.job_match_id == job_match_id).first()
    if existing:
        return schemas.ApplicationOut.from_application(existing)

    application = Application(
        user_id=current_user.id,
        job_match_id=job_match_id,
        portal=portal,
        resume_version_id=resume_version_id,
        status=ApplicationStatus.prepared,
    )
    db.add(application)
    match.status = MatchStatus.applied
    db.commit()
    db.refresh(application)

    db.add(ActivityLog(
        user_id=current_user.id,
        action_type="application_prepared",
        description="Application prepared and ready for review/submission",
        related_entity_type="application",
        related_entity_id=application.id,
    ))
    db.commit()

    return schemas.ApplicationOut.from_application(application)


@router.patch("/{application_id}/status", response_model=schemas.ApplicationOut)
def update_application_status(
    application_id: int,
    payload: schemas.ApplicationStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == current_user.id)
        .first()
    )
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    try:
        new_status = ApplicationStatus(payload.status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid status value")

    application.status = new_status
    if payload.result_notes:
        application.result_notes = payload.result_notes
    if new_status == ApplicationStatus.submitted and application.applied_at is None:
        application.applied_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(application)

    db.add(ActivityLog(
        user_id=current_user.id,
        action_type="application_status_changed",
        description=f"Application status changed to {new_status.value}",
        related_entity_type="application",
        related_entity_id=application.id,
    ))
    db.commit()

    return schemas.ApplicationOut.from_application(application)


@router.patch("/{application_id}/answers", response_model=schemas.ApplicationOut)
def record_application_answers(
    application_id: int,
    answers: dict[str, str],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Records the question/answer pairs used to complete this application
    (merges into any already recorded). This is what feeds the answer bank
    (POST /learning/sync-answer-bank) and the skill/outcome analysis
    (GET /learning/insights) once the application's outcome is known --
    check GET /knowledge/answers/match first for questions you've likely
    already answered before, so you're not retyping the same answer.
    """
    application = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == current_user.id)
        .first()
    )
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    application.application_data = {**(application.application_data or {}), **answers}
    db.commit()
    db.refresh(application)
    return schemas.ApplicationOut.from_application(application)


@router.get("", response_model=list[schemas.ApplicationOut])
def list_applications(
    status_filter: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Application).filter(Application.user_id == current_user.id)
    if status_filter:
        query = query.filter(Application.status == status_filter)
    apps = query.order_by(Application.created_at.desc()).all()
    return [schemas.ApplicationOut.from_application(a) for a in apps]
