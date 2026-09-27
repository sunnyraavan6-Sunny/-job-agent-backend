from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.deps import get_current_user
from app.models import ActivityLog, HRContact, User

router = APIRouter(prefix="/contacts", tags=["hr-contacts"])


@router.post("", response_model=schemas.HRContactOut, status_code=201)
def add_contact(
    payload: schemas.HRContactIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = HRContact(user_id=current_user.id, **payload.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)

    db.add(ActivityLog(
        user_id=current_user.id,
        action_type="hr_contact_found",
        description=f"HR contact discovered: {contact.name or 'unknown'} at {contact.company or 'unknown'}",
        related_entity_type="hr_contact",
        related_entity_id=contact.id,
    ))
    db.commit()

    return contact


@router.get("", response_model=list[schemas.HRContactOut])
def list_contacts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(HRContact)
        .filter(HRContact.user_id == current_user.id)
        .order_by(HRContact.discovered_at.desc())
        .all()
    )
