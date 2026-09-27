"""
Greenhouse's public job board API -- no auth required, but it's scoped to
one company at a time via that company's board token (the slug in their
careers page URL, e.g. boards.greenhouse.io/stripe -> token "stripe").
Docs: https://developers.greenhouse.io/job-board.html
"""
from typing import Optional

import requests

from app.services.job_sources.base import NormalizedJob

TIMEOUT_SECONDS = 15


def fetch_company_jobs(company_token: str) -> tuple[list[NormalizedJob], Optional[str]]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_token}/jobs"
    try:
        response = requests.get(url, params={"content": "true"}, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        return [], f"Greenhouse request failed for '{company_token}': {exc}"

    payload = response.json()
    jobs = []
    for item in payload.get("jobs", []):
        location = (item.get("location") or {}).get("name")
        jobs.append(NormalizedJob(
            source="greenhouse",
            external_id=str(item.get("id")),
            title=(item.get("title") or "").strip(),
            company=company_token,
            location=location,
            work_mode="remote" if location and "remote" in location.lower() else None,
            description=item.get("content"),
            url=item.get("absolute_url"),
        ))
    return jobs, None
