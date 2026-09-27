from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import ApplicationAnswer, KnowledgeBaseEntry, User

router = APIRouter(prefix="/knowledge", tags=["knowledge-base"])


# ---- schemas -----------------------------------------------------------

class AnswerIn(BaseModel):
    question_text: str
    answer_text: str
    category: Optional[str] = None
    verified: bool = False


class AnswerUpdate(BaseModel):
    answer_text: Optional[str] = None
    category: Optional[str] = None
    verified: Optional[bool] = None


class AnswerOut(BaseModel):
    id: int
    question_text: str
    answer_text: str
    category: Optional[str] = None
    verified: bool
    times_used: int
    created_at: datetime

    class Config:
        from_attributes = True


class FactIn(BaseModel):
    key: str
    value: str
    verified: bool = False


class FactOut(FactIn):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class AnswerMatch(BaseModel):
    found: bool
    answer: Optional[AnswerOut] = None
    confidence: str  # "exact" | "fuzzy" | "none"


# ---- application answers ---------------------------------------------------

@router.post("/answers", response_model=AnswerOut, status_code=201)
def add_answer(
    payload: AnswerIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Add a reusable answer to the bank. Set verified=true once the candidate
    has actually confirmed this answer is accurate and safe to reuse
    automatically; leave it false for something recorded but not yet
    confirmed (per the spec: uncertain/sensitive questions should prompt for
    confirmation rather than being auto-reused).
    """
    answer = ApplicationAnswer(user_id=current_user.id, **payload.model_dump())
    db.add(answer)
    db.commit()
    db.refresh(answer)
    return answer


@router.get("/answers", response_model=list[AnswerOut])
def list_answers(
    category: Optional[str] = None,
    verified_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(ApplicationAnswer).filter(ApplicationAnswer.user_id == current_user.id)
    if category:
        query = query.filter(ApplicationAnswer.category == category)
    if verified_only:
        query = query.filter(ApplicationAnswer.verified == True)  # noqa: E712
    return query.order_by(ApplicationAnswer.times_used.desc()).all()


@router.patch("/answers/{answer_id}", response_model=AnswerOut)
def update_answer(
    answer_id: int,
    payload: AnswerUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    answer = (
        db.query(ApplicationAnswer)
        .filter(ApplicationAnswer.id == answer_id, ApplicationAnswer.user_id == current_user.id)
        .first()
    )
    if not answer:
        raise HTTPException(status_code=404, detail="Answer not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(answer, field, value)
    db.commit()
    db.refresh(answer)
    return answer


@router.get("/answers/match", response_model=AnswerMatch)
def find_matching_answer(
    question: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Looks for a reusable answer to a new application question. Returns an
    exact match if the question text matches something already in the bank,
    a fuzzy match (simple substring/keyword overlap) otherwise, or found=false
    if nothing matches -- in which case the caller should ask the candidate
    rather than guessing, per the spec's "request confirmation" requirement.
    """
    normalized = question.strip().lower()
    answers = db.query(ApplicationAnswer).filter(ApplicationAnswer.user_id == current_user.id).all()

    for answer in answers:
        if answer.question_text.strip().lower() == normalized:
            answer.times_used += 1
            db.commit()
            db.refresh(answer)
            return AnswerMatch(found=True, answer=answer, confidence="exact")

    question_words = set(normalized.split())
    best_answer, best_overlap = None, 0
    for answer in answers:
        answer_words = set(answer.question_text.strip().lower().split())
        overlap = len(question_words & answer_words)
        if overlap > best_overlap:
            best_overlap, best_answer = overlap, answer

    if best_answer and best_overlap >= 3:
        best_answer.times_used += 1
        db.commit()
        db.refresh(best_answer)
        return AnswerMatch(found=True, answer=best_answer, confidence="fuzzy")

    return AnswerMatch(found=False, answer=None, confidence="none")


# ---- knowledge base facts -------------------------------------------------

@router.post("/facts", response_model=FactOut, status_code=201)
def add_fact(
    payload: FactIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fact = KnowledgeBaseEntry(user_id=current_user.id, **payload.model_dump())
    db.add(fact)
    db.commit()
    db.refresh(fact)
    return fact


@router.get("/facts", response_model=list[FactOut])
def list_facts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(KnowledgeBaseEntry).filter(KnowledgeBaseEntry.user_id == current_user.id).all()
