from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.config import settings
from app.routers import applications, auth, contacts, dashboard, ingestion, jobs, knowledge, learning, outreach, preferences, resume_engine, resumes

app = FastAPI(
    title="Autonomous Job Automation Agent API",
    description=(
        "Multi-user backend for the job-search automation agent: auth, preferences, "
        "master resume storage, job matching, applications, HR outreach, and dashboard analytics. "
        "Job-board ingestion, LaTeX resume generation, and cold-email sending are separate "
        "modules that call into this API's data model."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    # MVP: create tables directly from models.
    # Once the schema stabilizes, switch to Alembic migrations (see alembic/ in this repo).
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health_check():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(preferences.router)
app.include_router(resumes.router)
app.include_router(resume_engine.router)
app.include_router(jobs.router)
app.include_router(ingestion.router)
app.include_router(applications.router)
app.include_router(contacts.router)
app.include_router(outreach.router)
app.include_router(knowledge.router)
app.include_router(learning.router)
app.include_router(dashboard.router)
