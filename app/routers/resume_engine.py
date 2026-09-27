from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import (
    ActivityLog,
    JobMatch,
    JobPosting,
    MasterResume,
    MatchStatus,
    ResumeVersion,
    User,
)
from app.services.jd_analyzer import analyze_job_match
from app.services.learning_engine import get_top_performing_skills
from app.services.resume_builder import build_tailored_resume
from app.services.resume_parser import parse_master_resume

router = APIRouter(prefix="/resume-engine", tags=["resume-engine"])


def _get_active_master_resume(user: User, db: Session) -> MasterResume:
    resume = (
        db.query(MasterResume)
        .filter(MasterResume.user_id == user.id, MasterResume.is_active == True)  # noqa: E712
        .first()
    )
    if not resume:
        raise HTTPException(status_code=404, detail="No active master resume set. POST /resumes first.")
    return resume


# ---- Parsing --------------------------------------------------------------

class ParsedResumeOut(BaseModel):
    id: int
    parsed_json: Any

    class Config:
        from_attributes = True


@router.post("/parse-master", response_model=ParsedResumeOut)
def parse_master_resume_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resume = _get_active_master_resume(current_user, db)
    parsed = parse_master_resume(resume.raw_text)
    resume.parsed_json = parsed
    db.commit()
    db.refresh(resume)
    return resume


class ParsedResumeUpdate(BaseModel):
    parsed_json: dict


@router.put("/master/parsed", response_model=ParsedResumeOut)
def update_parsed_master_resume(
    payload: ParsedResumeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lets the candidate correct anything the heuristic parser got wrong before
    it's ever used to generate a tailored resume -- parsing plain text is
    best-effort, this is the safety valve.
    """
    resume = _get_active_master_resume(current_user, db)
    resume.parsed_json = payload.parsed_json
    db.commit()
    db.refresh(resume)
    return resume


# ---- Analysis ---------------------------------------------------------------

class AnalysisOut(BaseModel):
    job_match_id: int
    relevance_score: float
    matched_skills: list[str]
    missing_skills: list[str]
    topical_similarity: float
    skill_overlap_ratio: float


@router.post("/analyze/{job_posting_id}", response_model=AnalysisOut)
def analyze_job_posting(
    job_posting_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    posting = db.query(JobPosting).filter(JobPosting.id == job_posting_id).first()
    if not posting:
        raise HTTPException(status_code=404, detail="Job posting not found")

    resume = _get_active_master_resume(current_user, db)
    if not resume.parsed_json:
        raise HTTPException(
            status_code=400,
            detail="Master resume hasn't been parsed yet. Call POST /resume-engine/parse-master first.",
        )

    jd_text = f"{posting.title}\n{posting.description or ''}"
    analysis = analyze_job_match(resume.raw_text, resume.parsed_json.get("skills", []), jd_text)

    match = (
        db.query(JobMatch)
        .filter(JobMatch.user_id == current_user.id, JobMatch.job_posting_id == job_posting_id)
        .first()
    )
    if not match:
        match = JobMatch(user_id=current_user.id, job_posting_id=job_posting_id)
        db.add(match)

    match.relevance_score = analysis["relevance_score"]
    match.matched_skills = analysis["matched_skills"]
    if match.status == MatchStatus.new and analysis["relevance_score"] >= 60:
        match.status = MatchStatus.relevant
    db.commit()
    db.refresh(match)

    db.add(ActivityLog(
        user_id=current_user.id,
        action_type="job_analyzed",
        description=(
            f"Analyzed '{posting.title}' at {posting.company}: "
            f"{analysis['relevance_score']}% relevance, {len(analysis['matched_skills'])} skills matched"
        ),
        related_entity_type="job_match",
        related_entity_id=match.id,
    ))
    db.commit()

    return AnalysisOut(job_match_id=match.id, **analysis)


# ---- Generation ---------------------------------------------------------------

class ResumeVersionOut(BaseModel):
    id: int
    job_match_id: int
    pdf_available: bool
    emphasis_notes: Any
    log_message: str | None = None


@router.post("/generate/{job_match_id}", response_model=ResumeVersionOut, status_code=201)
def generate_tailored_resume(
    job_match_id: int,
    use_learning: bool = True,
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

    resume = _get_active_master_resume(current_user, db)
    if not resume.parsed_json:
        raise HTTPException(
            status_code=400,
            detail="Master resume hasn't been parsed yet. Call POST /resume-engine/parse-master first.",
        )

    priority_skills = list(match.matched_skills or [])
    if use_learning:
        # Boost in skills that have historically led to interviews/offers for
        # this candidate -- but only ones they actually have (never invented),
        # and only as a re-ranking signal on top of this job's own JD match.
        candidate_skills_lower = {s.lower() for s in resume.parsed_json.get("skills", [])}
        top_performing = get_top_performing_skills(current_user.id, db)
        for skill in top_performing:
            if skill.lower() in candidate_skills_lower and skill not in priority_skills:
                priority_skills.append(skill)

    output_basename = f"user{current_user.id}_match{match.id}_v{len(match.resume_versions) + 1}"
    build_result = build_tailored_resume(
        parsed_resume=resume.parsed_json,
        matched_skills=priority_skills,
        output_basename=output_basename,
    )

    version = ResumeVersion(
        user_id=current_user.id,
        job_match_id=match.id,
        tex_content=build_result["tex_content"],
        pdf_path=build_result["pdf_path"],
        emphasis_notes=build_result["emphasis_notes"],
    )
    db.add(version)
    db.commit()
    db.refresh(version)

    db.add(ActivityLog(
        user_id=current_user.id,
        action_type="resume_customized",
        description=f"Generated tailored resume for job match #{match.id} ({build_result['log_message']})",
        related_entity_type="resume_version",
        related_entity_id=version.id,
    ))
    db.commit()

    return ResumeVersionOut(
        id=version.id,
        job_match_id=version.job_match_id,
        pdf_available=version.pdf_path is not None,
        emphasis_notes=version.emphasis_notes,
        log_message=build_result["log_message"],
    )


@router.get("/versions/{job_match_id}", response_model=list[ResumeVersionOut])
def list_resume_versions(
    job_match_id: int,
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

    return [
        ResumeVersionOut(
            id=v.id,
            job_match_id=v.job_match_id,
            pdf_available=v.pdf_path is not None,
            emphasis_notes=v.emphasis_notes,
        )
        for v in match.resume_versions
    ]


@router.get("/download/{resume_version_id}")
def download_resume_pdf(
    resume_version_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    version = (
        db.query(ResumeVersion)
        .filter(ResumeVersion.id == resume_version_id, ResumeVersion.user_id == current_user.id)
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Resume version not found")
    if not version.pdf_path:
        raise HTTPException(status_code=404, detail="PDF was not compiled for this version; only .tex is available")

    return FileResponse(version.pdf_path, media_type="application/pdf", filename=f"resume_v{version.id}.pdf")
