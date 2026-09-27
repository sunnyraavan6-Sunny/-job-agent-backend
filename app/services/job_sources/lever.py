"""
Lever's public postings API -- no auth required, scoped to one company at a
time via that company's site slug (e.g. jobs.lever.co/netflix -> "netflix").
Docs: https://github.com/lever/postings-api
"""
from typing import Optional

import requests

from app.services.job_sources.base import NormalizedJob

TIMEOUT_SECONDS = 15


def fetch_company_jobs(company_token: str) -> tuple[list[NormalizedJob], Optional[str]]:
    url = f"https://api.lever.co/v0/postings/{company_token}"
    try:
        response = requests.get(url, params={"mode": "json"}, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        return [], f"Lever request failed for '{company_token}': {exc}"

    payload = response.json()
    jobs = []
    for item in payload:
        categories = item.get("categories", {}) or {}
        location = categories.get("location")
        jobs.append(NormalizedJob(
            source="lever",
            external_id=str(item.get("id")),
            title=(item.get("text") or "").strip(),
            company=company_token,
            location=location,
            work_mode="remote" if location and "remote" in location.lower() else None,
            description=item.get("descriptionPlain") or item.get("description"),
            url=item.get("hostedUrl"),
        ))
    return jobs, None
