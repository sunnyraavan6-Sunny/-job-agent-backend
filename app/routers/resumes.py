from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.deps import get_current_user
from app.models import ActivityLog, MasterResume, User

router = APIRouter(prefix="/resumes", tags=["master-resume"])


@router.post("", response_model=schemas.MasterResumeOut, status_code=201)
def create_master_resume(
    payload: schemas.MasterResumeIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # deactivate previous master resumes -- one active master resume per user
    db.query(MasterResume).filter(
        MasterResume.user_id == current_user.id, MasterResume.is_active == True  # noqa: E712
    ).update({"is_active": False})

    resume = MasterResume(user_id=current_user.id, raw_text=payload.raw_text, is_active=True)
    db.add(resume)
    db.commit()
    db.refresh(resume)

    db.add(ActivityLog(
        user_id=current_user.id,
        action_type="master_resume_uploaded",
        description="Master resume uploaded / updated",
        related_entity_type="master_resume",
        related_entity_id=resume.id,
    ))
    db.commit()

    return resume


@router.get("", response_model=list[schemas.MasterResumeOut])
def list_master_resumes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(MasterResume)
        .filter(MasterResume.user_id == current_user.id)
        .order_by(MasterResume.created_at.desc())
        .all()
    )


@router.get("/active", response_model=schemas.MasterResumeOut)
def get_active_master_resume(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    resume = (
        db.query(MasterResume)
        .filter(MasterResume.user_id == current_user.id, MasterResume.is_active == True)  # noqa: E712
        .first()
    )
    if not resume:
        raise HTTPException(status_code=404, detail="No active master resume set")
    return resume
