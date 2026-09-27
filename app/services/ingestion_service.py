from sqlalchemy.orm import Session

from app.models import ActivityLog, JobMatch, JobPosting, MasterResume, MatchStatus, User, UserPreference
from app.services.jd_analyzer import analyze_job_match
from app.services.job_sources import adzuna, greenhouse, lever, remoteok
from app.services.job_sources.base import NormalizedJob


def _upsert_posting(db: Session, job: NormalizedJob) -> tuple[JobPosting, bool]:
    existing = (
        db.query(JobPosting)
        .filter(JobPosting.source == job.source, JobPosting.external_id == job.external_id)
        .first()
    )
    if existing:
        return existing, False

    posting = JobPosting(
        source=job.source,
        external_id=job.external_id,
        title=job.title,
        company=job.company,
        location=job.location,
        work_mode=job.work_mode,
        description=job.description,
        url=job.url,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
    )
    db.add(posting)
    db.commit()
    db.refresh(posting)
    return posting, True


def run_ingestion(user: User, db: Session, auto_analyze: bool = True) -> dict:
    prefs = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    if not prefs:
        return {"error": "No preferences set. Call PUT /preferences first."}

    allowed_portals = {p.lower() for p in (prefs.allowed_portals or [])}
    if not allowed_portals:
        return {
            "error": (
                "No portals allowed. Set preferences.allowed_portals to include "
                "any of: adzuna, remoteok, greenhouse, lever."
            )
        }

    titles = prefs.target_titles or []
    locations = prefs.preferred_locations or []
    tracked_companies = prefs.tracked_companies or {}

    all_jobs: list[NormalizedJob] = []
    source_errors: dict[str, list[str]] = {}

    if "adzuna" in allowed_portals:
        jobs, err = adzuna.search(titles, locations)
        all_jobs.extend(jobs)
        if err:
            source_errors.setdefault("adzuna", []).append(err)

    if "remoteok" in allowed_portals:
        jobs, err = remoteok.search(titles)
        all_jobs.extend(jobs)
        if err:
            source_errors.setdefault("remoteok", []).append(err)

    if "greenhouse" in allowed_portals:
        companies = tracked_companies.get("greenhouse", [])
        if not companies:
            source_errors.setdefault("greenhouse", []).append(
                "No companies configured. Set preferences.tracked_companies.greenhouse to a list of board tokens."
            )
        for company in companies:
            jobs, err = greenhouse.fetch_company_jobs(company)
            all_jobs.extend(jobs)
            if err:
                source_errors.setdefault("greenhouse", []).append(err)

    if "lever" in allowed_portals:
        companies = tracked_companies.get("lever", [])
        if not companies:
            source_errors.setdefault("lever", []).append(
                "No companies configured. Set preferences.tracked_companies.lever to a list of company tokens."
            )
        for company in companies:
            jobs, err = lever.fetch_company_jobs(company)
            all_jobs.extend(jobs)
            if err:
                source_errors.setdefault("lever", []).append(err)

    master_resume = (
        db.query(MasterResume)
        .filter(MasterResume.user_id == user.id, MasterResume.is_active == True)  # noqa: E712
        .first()
    )

    new_postings = 0
    matches_created = 0

    for job in all_jobs:
        posting, is_new = _upsert_posting(db, job)
        if is_new:
            new_postings += 1
            db.add(ActivityLog(
                user_id=user.id,
                action_type="job_found",
                description=f"Found '{posting.title}' at {posting.company} via {posting.source}",
                related_entity_type="job_posting",
                related_entity_id=posting.id,
            ))

        if auto_analyze and master_resume and master_resume.parsed_json:
            existing_match = (
                db.query(JobMatch)
                .filter(JobMatch.user_id == user.id, JobMatch.job_posting_id == posting.id)
                .first()
            )
            if not existing_match:
                jd_text = f"{posting.title}\n{posting.description or ''}"
                analysis = analyze_job_match(
                    master_resume.raw_text, master_resume.parsed_json.get("skills", []), jd_text
                )
                status_val = MatchStatus.relevant if analysis["relevance_score"] >= 60 else MatchStatus.new
                db.add(JobMatch(
                    user_id=user.id,
                    job_posting_id=posting.id,
                    relevance_score=analysis["relevance_score"],
                    matched_skills=analysis["matched_skills"],
                    status=status_val,
                ))
                matches_created += 1
                db.add(ActivityLog(
                    user_id=user.id,
                    action_type="job_analyzed",
                    description=(
                        f"Analyzed '{posting.title}' at {posting.company}: "
                        f"{analysis['relevance_score']}% relevance"
                    ),
                    related_entity_type="job_posting",
                    related_entity_id=posting.id,
                ))

    db.commit()

    return {
        "jobs_found": len(all_jobs),
        "new_postings": new_postings,
        "matches_created": matches_created,
        "auto_analyzed": auto_analyze and master_resume is not None and master_resume.parsed_json is not None,
        "source_errors": source_errors,
    }
