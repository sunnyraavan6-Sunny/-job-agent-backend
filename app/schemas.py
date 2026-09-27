from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field


# ---- Auth --------------------------------------------------------------

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---- Preferences ---------------------------------------------------------

class PreferencesIn(BaseModel):
    target_titles: list[str] = Field(default_factory=list, max_length=3)
    preferred_locations: list[str] = Field(default_factory=list)
    experience_level: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    work_preference: Optional[str] = None
    max_applications_per_day: int = 10
    max_applications_per_portal: int = 5
    allowed_portals: list[str] = Field(default_factory=list)
    tracked_companies: dict[str, list[str]] = Field(default_factory=dict)
    operating_mode: str = "approval"


class PreferencesOut(PreferencesIn):
    class Config:
        from_attributes = True


# ---- Master resume -------------------------------------------------------

class MasterResumeIn(BaseModel):
    raw_text: str


class MasterResumeOut(BaseModel):
    id: int
    raw_text: str
    parsed_json: Optional[Any] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ---- Job postings / matches ----------------------------------------------

class JobPostingIn(BaseModel):
    source: str
    external_id: str
    title: str
    company: str
    location: Optional[str] = None
    work_mode: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None


class JobPostingOut(BaseModel):
    id: int
    source: str
    title: str
    company: str
    location: Optional[str] = None
    work_mode: Optional[str] = None
    url: Optional[str] = None
    discovered_at: datetime

    class Config:
        from_attributes = True


class JobMatchOut(BaseModel):
    id: int
    relevance_score: float
    matched_skills: Optional[Any] = None
    status: str
    job_posting: JobPostingOut

    class Config:
        from_attributes = True


# ---- Applications ----------------------------------------------------------

class ApplicationOut(BaseModel):
    id: int
    job_match_id: int
    resume_version_id: Optional[int] = None
    portal: Optional[str] = None
    status: str
    applied_at: Optional[datetime] = None
    created_at: datetime
    job_title: Optional[str] = None
    company: Optional[str] = None

    class Config:
        from_attributes = True

    @staticmethod
    def from_application(app):
        posting = app.job_match.job_posting if app.job_match else None
        return ApplicationOut(
            id=app.id,
            job_match_id=app.job_match_id,
            resume_version_id=app.resume_version_id,
            portal=app.portal,
            status=app.status.value if hasattr(app.status, "value") else app.status,
            applied_at=app.applied_at,
            created_at=app.created_at,
            job_title=posting.title if posting else None,
            company=posting.company if posting else None,
        )


class ApplicationStatusUpdate(BaseModel):
    status: str
    result_notes: Optional[str] = None


# ---- HR contacts / outreach -------------------------------------------------

class HRContactIn(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    source: Optional[str] = None


class HRContactOut(HRContactIn):
    id: int
    discovered_at: datetime

    class Config:
        from_attributes = True


# ---- Dashboard --------------------------------------------------------------

class DashboardStats(BaseModel):
    jobs_discovered: int
    jobs_relevant: int
    jobs_applied: int
    applications_submitted: int
    applications_in_progress: int
    interviews: int
    rejections: int
    offers: int
    hr_contacts_discovered: int
    emails_sent: int
    emails_replied: int
