from __future__ import annotations

from app.models.entities import ScholarshipRecord
from app.repos import scholarship_repo


def _record(*, title: str = "Scholarship A", country: str = "Nigeria") -> ScholarshipRecord:
    return ScholarshipRecord(
        country=country,
        university="Test University",
        university_website="https://uni.example",
        scholarship_page="https://uni.example/scholarship-a",
        title=title,
        text_information="Some details",
        date_published="2026-03-01",
        department="Computer Science",
        faculty="Engineering",
        deadline="2026-12-31",
        discovered_at_utc="2026-03-11T00:00:00+00:00",
    )


def setup_function() -> None:
    scholarship_repo._STORE.clear()


def test_upsert_insert_then_unchanged_then_update() -> None:
    rec = _record()

    first = scholarship_repo.upsert_scholarships([rec])
    assert first.inserted == 1
    assert first.updated == 0
    assert first.unchanged == 0

    second = scholarship_repo.upsert_scholarships([rec])
    assert second.inserted == 0
    assert second.updated == 0
    assert second.unchanged == 1

    changed = _record(title="Scholarship A (Updated)")
    third = scholarship_repo.upsert_scholarships([changed])
    assert third.inserted == 0
    assert third.updated == 1
    assert third.unchanged == 0

    results = scholarship_repo.fetch_scholarships(country="Nigeria", university=None, limit=10)
    assert len(results) == 1
    assert results[0]["title"] == "Scholarship A (Updated)"
    assert "content_hash" not in results[0]


def test_fetch_filters_and_limit() -> None:
    rec_a = _record(title="A", country="Nigeria")
    rec_b = ScholarshipRecord(
        country="Ghana",
        university="Other University",
        university_website="https://other.example",
        scholarship_page="https://other.example/scholarship-b",
        title="B",
        text_information="Info",
        date_published="2026-03-02",
        department="Math",
        faculty="Science",
        deadline="2026-10-01",
        discovered_at_utc="2026-03-11T00:00:00+00:00",
    )

    scholarship_repo.upsert_scholarships([rec_a, rec_b])

    nigeria_only = scholarship_repo.fetch_scholarships(country="Nigeria", university=None, limit=10)
    assert len(nigeria_only) == 1
    assert nigeria_only[0]["country"] == "Nigeria"

    limited = scholarship_repo.fetch_scholarships(country=None, university=None, limit=1)
    assert len(limited) == 1
