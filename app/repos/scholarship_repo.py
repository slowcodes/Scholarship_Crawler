from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

from app.models.entities import SaveStats, ScholarshipRecord

_STORE_LOCK = Lock()
_STORE: dict[str, dict] = {}


def scholarship_content_hash(record: ScholarshipRecord) -> str:
    payload = "||".join([
        record.country or "",
        record.university or "",
        record.university_website or "",
        record.scholarship_page or "",
        record.title or "",
        record.text_information or "",
        record.date_published or "",
        record.department or "",
        record.faculty or "",
        record.deadline or "",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upsert_scholarships(records: list[ScholarshipRecord]) -> SaveStats:
    stats = SaveStats()

    with _STORE_LOCK:
        now_utc = datetime.now(timezone.utc).isoformat()
        for rec in records:
            new_hash = scholarship_content_hash(rec)
            existing = _STORE.get(rec.scholarship_page)

            if existing is None:
                _STORE[rec.scholarship_page] = {
                    "country": rec.country,
                    "university": rec.university,
                    "university_website": rec.university_website,
                    "scholarship_page": rec.scholarship_page,
                    "title": rec.title,
                    "text_information": rec.text_information,
                    "date_published": rec.date_published,
                    "department": rec.department,
                    "faculty": rec.faculty,
                    "deadline": rec.deadline,
                    "discovered_at_utc": rec.discovered_at_utc,
                    "updated_at_utc": now_utc,
                    "content_hash": new_hash,
                }
                stats.inserted += 1
                continue

            if existing.get("content_hash") == new_hash:
                stats.unchanged += 1
                continue

            existing.update(
                {
                    "country": rec.country,
                    "university": rec.university,
                    "university_website": rec.university_website,
                    "title": rec.title,
                    "text_information": rec.text_information,
                    "date_published": rec.date_published,
                    "department": rec.department,
                    "faculty": rec.faculty,
                    "deadline": rec.deadline,
                    "updated_at_utc": now_utc,
                    "content_hash": new_hash,
                }
            )
            stats.updated += 1

    return stats


def fetch_scholarships(
    country: Optional[str],
    university: Optional[str],
    limit: int,
) -> list[dict]:
    with _STORE_LOCK:
        items = list(_STORE.values())

    if country:
        items = [x for x in items if x.get("country") == country]
    if university:
        items = [x for x in items if x.get("university") == university]

    items.sort(key=lambda x: x.get("updated_at_utc") or "", reverse=True)

    # Remove internal hash from GraphQL response
    cleaned: list[dict] = []
    for item in items[:limit]:
        entry = dict(item)
        entry.pop("content_hash", None)
        cleaned.append(entry)
    return cleaned
