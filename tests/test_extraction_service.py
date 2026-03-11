from __future__ import annotations

from app.models.entities import University
from app.services.extraction_service import extract_fields_from_page


def test_extract_fields_from_page_success() -> None:
    html = """
    <html>
      <head>
        <title>International Scholarship 2026</title>
        <meta property="article:published_time" content="2026-02-20" />
      </head>
      <body>
        <h1>International Scholarship</h1>
        <p>Applications open for postgraduate funding.</p>
        <p>Department: Computer Science</p>
        <p>Faculty: Engineering</p>
        <p>Deadline: 31 December 2099</p>
      </body>
    </html>
    """
    university = University(name="Test U", website="https://uni.example", wikidata_id="Q1")

    rec = extract_fields_from_page(html, "https://uni.example/sch", "Nigeria", university)

    assert rec is not None
    assert rec.title == "International Scholarship 2026"
    assert rec.date_published == "2026-02-20"
    assert rec.department is not None and "Computer Science" in rec.department
    assert rec.faculty is not None and "Engineering" in rec.faculty
    assert rec.deadline is not None
    assert rec.text_information is not None


def test_extract_fields_from_page_rejects_irrelevant_page() -> None:
    html = "<html><head><title>Admissions News</title></head><body>General campus update only</body></html>"
    university = University(name="Test U", website="https://uni.example", wikidata_id="Q1")

    rec = extract_fields_from_page(html, "https://uni.example/news", "Nigeria", university)

    assert rec is None
