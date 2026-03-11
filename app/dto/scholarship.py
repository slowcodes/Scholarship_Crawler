from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CrawlRequest(BaseModel):
    country: str = Field(..., description='Country name, e.g. "Germany"')
    max_pages_per_site: int = Field(default=80, ge=1, le=500)
    limit_universities: Optional[int] = Field(default=None, ge=1)
    sqlite_path: str = Field(default="scholarships.db")


class CrawlResponse(BaseModel):
    processed_records: int
    inserted: int
    updated: int
    unchanged: int
    sqlite_path: str


class ScholarshipListResponse(BaseModel):
    count: int
    items: list[dict]
