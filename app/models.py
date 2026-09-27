import enum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class OperatingMode(str, enum.Enum):
    fully_autonomous = "fully_autonomous"
    approval = "approval"
    assisted = "assisted"


class MatchStatus(str, enum.Enum):
    new = "new"
    relevant = "relevant"
    not_relevant = "not_relevant"
    applied = "applied"


class ApplicationStatus(str, enum.Enum):
    prepared = "prepared"
    submitted = "submitted"
    viewed = "viewed"
    interview = "interview"
    rejected = "rejected"
    offer = "offer"
    no_response = "no_response"


class OutreachStatus(str, enum.Enum):
    draft = "draft"
    sent = "sent"
    replied_positive = "replied_positive"
    replied_negative = "replied_negative"
    replied_neutral = "replied_neutral"
    bounced = "bounced"
    no_response = "no_response"


# ---------------------------------------------------------------------------
# Core tables
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    preferences = relationship("UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan")
    master_resumes = relationship("MasterResume", back_populates="user", cascade="all, delete-orphan")
    job_matches = relationship("JobMatch", back_populates="user", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="user", cascade="all, delete-orphan")
    hr_contacts = relationship("HRContact", back_populates="user", cascade="all, delete-orphan")
    outreach_emails = relationship("OutreachEmail", back_populates="user", cascade="all, delete-orphan")
    answers = relationship("ApplicationAnswer", back_populates="user", cascade="all, delete-orphan")
    knowledge_base = relationship("KnowledgeBaseEntry", back_populates="user", cascade="all, delete-orphan")
    activity_log = relationship("ActivityLog", back_populates="user", cascade="all, delete-orphan")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    target_titles = Column(JSON, default=list)          # up to 3 job titles
    preferred_locations = Column(JSON, default=list)
    experience_level = Column(String(50), nullable=True)  # e.g. "entry", "mid", "senior"
    salary_min = Column(Integer, nullable=True)
    salary_max = Column(Integer, nullable=True)
    work_preference = Column(String(50), nullable=True)   # remote / hybrid / onsite
    max_applications_per_day = Column(Integer, default=10)
    max_applications_per_portal = Column(Integer, default=5)
    allowed_portals = Column(JSON, default=list)           # portals the agent may use
    tracked_companies = Column(JSON, default=dict)          # e.g. {"greenhouse": ["stripe"], "lever": ["netflix"]}
    operating_mode = Column(Enum(OperatingMode), default=OperatingMode.approval)

    user = relationship("User", back_populates="preferences")


class MasterResume(Base):
    __tablename__ = "master_resumes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    raw_text = Column(Text, nullable=False)
    parsed_json = Column(JSON, nullable=True)   # structured skills/experience/education/projects
    file_path = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="master_resumes")


class JobPosting(Base):
    """
    Shared, de-duplicated pool of jobs discovered from any source.
    Not user-specific -- many users can match against the same posting.
    """
    __tablename__ = "job_postings"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_source_external_id"),)

    id = Column(Integer, primary_key=True)
    source = Column(String(100), nullable=False)         # e.g. "linkedin", "indeed", "greenhouse"
    external_id = Column(String(255), nullable=False)     # id/url-hash from the source
    title = Column(String(255), nullable=False)
    company = Column(String(255), nullable=False)
    location = Column(String(255), nullable=True)
    work_mode = Column(String(50), nullable=True)          # remote / hybrid / onsite
    description = Column(Text, nullable=True)
    url = Column(String(1000), nullable=True)
    salary_min = Column(Integer, nullable=True)
    salary_max = Column(Integer, nullable=True)
    posted_date = Column(DateTime(timezone=True), nullable=True)
    discovered_at = Column(DateTime(timezone=True), server_default=func.now())

    matches = relationship("JobMatch", back_populates="job_posting")


class JobMatch(Base):
    """A specific user's relevance assessment against a job posting."""
    __tablename__ = "job_matches"
    __table_args__ = (UniqueConstraint("user_id", "job_posting_id", name="uq_user_job"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    job_posting_id = Column(Integer, ForeignKey("job_postings.id"), nullable=False)
    relevance_score = Column(Float, default=0.0)          # 0-100
    matched_skills = Column(JSON, default=list)
    status = Column(Enum(MatchStatus), default=MatchStatus.new)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="job_matches")
    job_posting = relationship("JobPosting", back_populates="matches")
    resume_versions = relationship("ResumeVersion", back_populates="job_match", cascade="all, delete-orphan")
    application = relationship("Application", back_populates="job_match", uselist=False)


class ResumeVersion(Base):
    """A job-specific customized resume generated for a given match."""
    __tablename__ = "resume_versions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    job_match_id = Column(Integer, ForeignKey("job_matches.id"), nullable=False)
    tex_content = Column(Text, nullable=True)
    pdf_path = Column(String(500), nullable=True)
    emphasis_notes = Column(JSON, nullable=True)   # which skills/keywords were emphasized and why
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job_match = relationship("JobMatch", back_populates="resume_versions")


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    job_match_id = Column(Integer, ForeignKey("job_matches.id"), unique=True, nullable=False)
    resume_version_id = Column(Integer, ForeignKey("resume_versions.id"), nullable=True)
    portal = Column(String(100), nullable=True)
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.prepared)
    application_data = Column(JSON, nullable=True)   # Q&A pairs answered during application
    result_notes = Column(Text, nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="applications")
    job_match = relationship("JobMatch", back_populates="application")


class HRContact(Base):
    __tablename__ = "hr_contacts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=True)
    title = Column(String(255), nullable=True)
    company = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    linkedin_url = Column(String(500), nullable=True)
    source = Column(String(100), nullable=True)
    discovered_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="hr_contacts")
    outreach_emails = relationship("OutreachEmail", back_populates="hr_contact", cascade="all, delete-orphan")


class OutreachEmail(Base):
    __tablename__ = "outreach_emails"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    hr_contact_id = Column(Integer, ForeignKey("hr_contacts.id"), nullable=False)
    job_match_id = Column(Integer, ForeignKey("job_matches.id"), nullable=True)
    subject = Column(String(500), nullable=True)
    body = Column(Text, nullable=True)
    status = Column(Enum(OutreachStatus), default=OutreachStatus.draft)
    follow_up_count = Column(Integer, default=0)
    message_id = Column(String(255), nullable=True, unique=True)   # RFC 5322 Message-ID, for reply threading
    generation_method = Column(String(20), nullable=True)           # "template" or "llm" -- feeds the learning loop
    reply_category = Column(String(50), nullable=True)              # granular: interview / rejection / follow_up_required / action_required / other
    reply_excerpt = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    replied_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="outreach_emails")
    hr_contact = relationship("HRContact", back_populates="outreach_emails")


class ApplicationAnswer(Base):
    """Reusable Q&A pairs -- the 'answer bank' built up over time."""
    __tablename__ = "application_answers"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    question_text = Column(Text, nullable=False)
    answer_text = Column(Text, nullable=False)
    category = Column(String(100), nullable=True)   # e.g. "salary", "authorization", "notice_period"
    verified = Column(Boolean, default=False)         # confirmed by the candidate, safe to reuse
    times_used = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="answers")


class KnowledgeBaseEntry(Base):
    """Free-form verified facts about the candidate (visa status, notice period, etc.)."""
    __tablename__ = "knowledge_base"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    key = Column(String(255), nullable=False)
    value = Column(Text, nullable=False)
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="knowledge_base")


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action_type = Column(String(100), nullable=False)   # e.g. "job_found", "resume_customized", "email_sent"
    description = Column(String(1000), nullable=True)
    related_entity_type = Column(String(100), nullable=True)
    related_entity_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="activity_log")
