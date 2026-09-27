from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.services.ingestion_service import run_ingestion

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

_SOURCE_DESCRIPTIONS = [
    {
        "name": "adzuna",
        "type": "keyword_search",
        "config_needed": "ADZUNA_APP_ID / ADZUNA_APP_KEY in .env (free signup at developer.adzuna.com)",
    },
    {
        "name": "remoteok",
        "type": "keyword_search",
        "config_needed": None,
    },
    {
        "name": "greenhouse",
        "type": "company_board",
        "config_needed": "preferences.tracked_companies.greenhouse = [board tokens, e.g. 'stripe']",
    },
    {
        "name": "lever",
        "type": "company_board",
        "config_needed": "preferences.tracked_companies.lever = [company tokens, e.g. 'netflix']",
    },
]


@router.get("/sources")
def list_sources():
    """
    Shows which job sources this backend can pull from, and what each one
    needs configured (an API key for Adzuna, or a list of company tokens for
    the two ATS-board sources) before it will return anything.
    """
    sources = []
    for src in _SOURCE_DESCRIPTIONS:
        entry = dict(src)
        if src["name"] == "adzuna":
            entry["configured"] = bool(settings.adzuna_app_id and settings.adzuna_app_key)
        else:
            entry["configured"] = True  # no global config required; per-user prefs handle the rest
        sources.append(entry)
    return sources


@router.post("/run")
def trigger_ingestion(
    auto_analyze: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Pulls fresh jobs from every source in the user's preferences.allowed_portals,
    de-duplicates against the existing job pool, and (if auto_analyze) scores
    each new posting against the user's active master resume.
    """
    return run_ingestion(current_user, db, auto_analyze=auto_analyze)
