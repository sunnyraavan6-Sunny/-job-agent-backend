from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.deps import get_current_user
from app.models import ActivityLog, JobMatch, JobPosting, MatchStatus, User

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/postings", response_model=schemas.JobPostingOut, status_code=201)
def ingest_job_posting(payload: schemas.JobPostingIn, db: Session = Depends(get_db)):
    """
    Manual/ingestion-adapter entry point for a discovered job.
    Real source adapters (Adzuna, Greenhouse, Lever, etc.) will call this
    internally instead of a human calling it directly.
    """
    existing = (
        db.query(JobPosting)
        .filter(JobPosting.source == payload.source, JobPosting.external_id == payload.external_id)
        .first()
    )
    if existing:
        return existing

    posting = JobPosting(**payload.model_dump())
    db.add(posting)
    db.commit()
    db.refresh(posting)
    return posting


@router.get("/postings", response_model=list[schemas.JobPostingOut])
def list_job_postings(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    return db.query(JobPosting).order_by(JobPosting.discovered_at.desc()).offset(skip).limit(limit).all()


@router.post("/matches/{job_posting_id}", response_model=schemas.JobMatchOut, status_code=201)
def create_match_for_current_user(
    job_posting_id: int,
    relevance_score: float = 0.0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    posting = db.query(JobPosting).filter(JobPosting.id == job_posting_id).first()
    if not posting:
        raise HTTPException(status_code=404, detail="Job posting not found")

    existing = (
        db.query(JobMatch)
        .filter(JobMatch.user_id == current_user.id, JobMatch.job_posting_id == job_posting_id)
        .first()
    )
    if existing:
        return existing

    status_val = MatchStatus.relevant if relevance_score >= 60 else MatchStatus.new
    match = JobMatch(
        user_id=current_user.id,
        job_posting_id=job_posting_id,
        relevance_score=relevance_score,
        status=status_val,
    )
    db.add(match)
    db.commit()
    db.refresh(match)

    db.add(ActivityLog(
        user_id=current_user.id,
        action_type="job_analyzed",
        description=f"Analyzed job: {posting.title} at {posting.company} (score {relevance_score})",
        related_entity_type="job_match",
        related_entity_id=match.id,
    ))
    db.commit()

    return match


@router.get("/matches", response_model=list[schemas.JobMatchOut])
def list_my_matches(
    status_filter: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(JobMatch).filter(JobMatch.user_id == current_user.id)
    if status_filter:
        query = query.filter(JobMatch.status == status_filter)
    return query.order_by(JobMatch.relevance_score.desc()).all()
