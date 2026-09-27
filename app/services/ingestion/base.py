"""
Every ingestion adapter normalizes whatever shape its source returns into
this one NormalizedJob structure, which maps directly onto JobPostingIn.
Adding a new source means writing one adapter that returns a list of these
-- nothing else in the ingestion pipeline needs to change.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime


def strip_html(html: str | None) -> str:
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@dataclass
class NormalizedJob:
    source: str
    external_id: str
    title: str
    company: str
    location: str | None = None
    work_mode: str | None = None          # "remote" / "hybrid" / "onsite" / None if unknown
    description: str = ""
    url: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    posted_date: datetime | None = None


@dataclass
class AdapterResult:
    source: str
    jobs: list[NormalizedJob] = field(default_factory=list)
    error: str | None = None       # set if the source failed (bad token, network error, etc.)


class JobSourceAdapter:
    """Base interface every source adapter implements."""

    source_name: str = "base"
    #: True if this adapter needs per-company slugs/tokens rather than a free-text query
    requires_company_slug: bool = False
    #: True if this adapter needs API credentials configured
    requires_credentials: bool = False

    def fetch(self, query: str = "", location: str = "", company_slugs: list[str] | None = None,
              limit: int = 25) -> AdapterResult:
        raise NotImplementedError
