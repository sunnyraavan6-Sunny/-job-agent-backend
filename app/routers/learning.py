from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services.learning_engine import generate_insights, sync_answer_bank

router = APIRouter(prefix="/learning", tags=["learning"])


@router.get("/insights")
def get_insights(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    A read-only report over the candidate's own history: which skills, job
    attributes, resume versions, and email approaches correlate with
    interviews/offers vs rejections/silence -- pure descriptive statistics
    over their own data, nothing invented or inferred beyond what actually
    happened. See /knowledge/answers for the reusable answer bank this feeds.
    """
    return generate_insights(current_user.id, db)


@router.post("/sync-answer-bank")
def run_sync_answer_bank(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Scans past applications' recorded Q&A and grows the reusable answer bank
    (managed via /knowledge/answers). New questions land as unverified --
    confirm them with PATCH /knowledge/answers/{id} before they're reused
    automatically on future applications.
    """
    return sync_answer_bank(current_user.id, db)
