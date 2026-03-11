from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.dto.scholarship import CrawlRequest, CrawlResponse, ScholarshipListResponse
from app.repos.scholarship_repo import fetch_scholarships
from app.services.crawler_service import crawl_and_save

router = APIRouter(tags=["scholarships"])


@router.post("/crawl", response_model=CrawlResponse)
async def crawl(payload: CrawlRequest) -> CrawlResponse:
    try:
        processed_records, stats = await crawl_and_save(
            country=payload.country,
            max_pages_per_site=payload.max_pages_per_site,
            limit_universities=payload.limit_universities,
            sqlite_path=payload.sqlite_path,
        )
        return CrawlResponse(
            processed_records=processed_records,
            inserted=stats.inserted,
            updated=stats.updated,
            unchanged=stats.unchanged,
            sqlite_path=payload.sqlite_path,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Crawl failed: {e}") from e


@router.get("/scholarships", response_model=ScholarshipListResponse)
async def scholarships(
    sqlite_path: str = Query(default="scholarships.db"),
    country: Optional[str] = Query(default=None),
    university: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> ScholarshipListResponse:
    try:
        data = fetch_scholarships(sqlite_path, country, university, limit)
        return ScholarshipListResponse(count=len(data), items=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {e}") from e
