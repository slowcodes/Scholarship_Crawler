from __future__ import annotations

import asyncio

from graphql import graphql

from app.graphql import schema as graphql_schema
from app.repos import scholarship_repo
from app.models.entities import SaveStats


def setup_function() -> None:
    scholarship_repo._STORE.clear()


def test_scholarships_query_returns_data() -> None:
    scholarship_repo._STORE["https://uni.example/s1"] = {
        "country": "Nigeria",
        "university": "Test University",
        "university_website": "https://uni.example",
        "scholarship_page": "https://uni.example/s1",
        "title": "Scholarship 1",
        "text_information": "Info",
        "date_published": "2026-03-01",
        "department": "CS",
        "faculty": "Engineering",
        "deadline": "2099-12-31",
        "discovered_at_utc": "2026-03-11T00:00:00+00:00",
        "updated_at_utc": "2026-03-11T00:00:00+00:00",
        "content_hash": "x",
    }

    query = """
    query {
      scholarships(limit: 10) {
        country
        university
        scholarship_page
        title
      }
    }
    """
    result = asyncio.run(graphql(graphql_schema.schema, query))

    assert result.errors is None
    assert result.data is not None
    assert len(result.data["scholarships"]) == 1
    assert result.data["scholarships"][0]["title"] == "Scholarship 1"


def test_crawl_mutation_uses_service(monkeypatch) -> None:
    async def fake_crawl_and_save(country: str, max_pages_per_site: int, limit_universities: int | None):
        assert country == "Nigeria"
        assert max_pages_per_site == 10
        assert limit_universities == 1
        return 4, SaveStats(inserted=2, updated=1, unchanged=1)

    monkeypatch.setattr(graphql_schema, "crawl_and_save", fake_crawl_and_save)

    mutation = """
    mutation {
      crawl(input: {country: "Nigeria", max_pages_per_site: 10, limit_universities: 1}) {
        processed_records
        inserted
        updated
        unchanged
      }
    }
    """
    result = asyncio.run(graphql(graphql_schema.schema, mutation))

    assert result.errors is None
    assert result.data == {
        "crawl": {
            "processed_records": 4,
            "inserted": 2,
            "updated": 1,
            "unchanged": 1,
        }
    }
