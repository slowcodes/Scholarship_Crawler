from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class University:
    name: str
    website: str
    wikidata_id: str


@dataclass
class ScholarshipRecord:
    country: str
    university: str
    university_website: str
    scholarship_page: str
    title: str
    text_information: Optional[str]
    date_published: Optional[str]
    department: Optional[str]
    faculty: Optional[str]
    deadline: Optional[str]
    discovered_at_utc: str


@dataclass
class SaveStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
