from dataclasses import dataclass
from typing import Optional


@dataclass
class NormalizedJob:
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
