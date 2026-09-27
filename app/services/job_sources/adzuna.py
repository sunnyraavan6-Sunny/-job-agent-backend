"""
Adzuna (https://developer.adzuna.com/) -- keyword + location job search
across many countries. Free tier requires registering for an app_id/app_key.
Docs: https://developer.adzuna.com/docs/search
"""
from typing import Optional

import requests

from app.config import settings
from app.services.job_sources.base import NormalizedJob

BASE_URL = "https://api.adzuna.com/v1/api/jobs"
TIMEOUT_SECONDS = 15


def search(titles: list[str], locations: list[str], results_per_page: int = 20) -> tuple[list[NormalizedJob], Optional[str]]:
    if not settings.adzuna_app_id or not settings.adzuna_app_key:
        return [], "Adzuna is not configured: set ADZUNA_APP_ID and ADZUNA_APP_KEY in .env"

    what = titles[0] if titles else ""
    where = locations[0] if locations else ""
    url = f"{BASE_URL}/{settings.adzuna_country}/search/1"
    params = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_app_key,
        "results_per_page": results_per_page,
        "what": what,
        "where": where,
        "content-type": "application/json",
    }

    try:
        response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        return [], f"Adzuna request failed: {exc}"

    payload = response.json()
    jobs = []
    for item in payload.get("results", []):
        company = (item.get("company") or {}).get("display_name", "Unknown")
        location = (item.get("location") or {}).get("display_name")
        jobs.append(NormalizedJob(
            source="adzuna",
            external_id=str(item.get("id")),
            title=(item.get("title") or "").strip(),
            company=company,
            location=location,
            work_mode=None,
            description=item.get("description"),
            url=item.get("redirect_url"),
            salary_min=int(item["salary_min"]) if item.get("salary_min") else None,
            salary_max=int(item["salary_max"]) if item.get("salary_max") else None,
        ))
    return jobs, None
