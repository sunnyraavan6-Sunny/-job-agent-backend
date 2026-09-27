"""
RemoteOK public API -- no key required. Returns all currently listed remote
jobs; we filter client-side by title keyword since the API has no server-side
search parameter. Docs (informal): https://remoteok.com/api
"""
from typing import Optional

import requests

from app.services.job_sources.base import NormalizedJob

API_URL = "https://remoteok.com/api"
TIMEOUT_SECONDS = 15


def search(titles: list[str], limit: int = 25) -> tuple[list[NormalizedJob], Optional[str]]:
    try:
        response = requests.get(
            API_URL, timeout=TIMEOUT_SECONDS, headers={"User-Agent": "job-automation-agent/0.1"}
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return [], f"RemoteOK request failed: {exc}"

    try:
        payload = response.json()
    except ValueError as exc:
        return [], f"RemoteOK returned non-JSON response: {exc}"

    # RemoteOK's first array element is metadata, not a listing -- skip it.
    listings = [item for item in payload if isinstance(item, dict) and item.get("id")]
    titles_lower = [t.lower() for t in titles if t]

    jobs = []
    for item in listings:
        position = (item.get("position") or item.get("title") or "").strip()
        if titles_lower and not any(t in position.lower() for t in titles_lower):
            continue

        jobs.append(NormalizedJob(
            source="remoteok",
            external_id=str(item.get("id")),
            title=position,
            company=item.get("company", "Unknown"),
            location=item.get("location") or "Remote",
            work_mode="remote",
            description=item.get("description"),
            url=item.get("url") or f"https://remoteok.com/remote-jobs/{item.get('id')}",
            salary_min=item.get("salary_min"),
            salary_max=item.get("salary_max"),
        ))
        if len(jobs) >= limit:
            break

    return jobs, None
