from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from app.constants import (
    ACTIVE_HINTS,
    DATE_PATTERNS,
    DEPARTMENT_PATTERNS,
    FACULTY_PATTERNS,
    MAX_TEXT_INFORMATION,
    MAX_TEXT_SCAN,
    META_DATE_KEYS,
    NEGATIVE_HINTS,
    SCHOLARSHIP_KEYWORDS,
)
from app.models.entities import ScholarshipRecord, University


def text_contains_keywords(text: str, keywords: list[str]) -> bool:
    low = text.lower()
    return any(k in low for k in keywords)


def parse_date_safe(value: str) -> Optional[str]:
    try:
        dt = dateparser.parse(value, fuzzy=True, dayfirst=False)
        if not dt:
            return None
        return dt.date().isoformat()
    except Exception:
        return None


def extract_meta_dates(soup: BeautifulSoup) -> dict[str, Optional[str]]:
    found: dict[str, Optional[str]] = {}
    for meta in soup.find_all("meta"):
        key = (meta.get("property") or meta.get("name") or "").strip().lower()
        value = (meta.get("content") or "").strip()
        if key in META_DATE_KEYS and value:
            found[key] = parse_date_safe(value) or value
    return found


def extract_by_patterns(text: str, patterns: list[re.Pattern]) -> Optional[str]:
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            value = m.group(2).strip(" :-\n\t")
            if value:
                return re.sub(r"\s{2,}", " ", value)
    return None


def extract_dates_from_text(text: str) -> tuple[Optional[str], Optional[str]]:
    published = None
    deadline = None

    for pattern in DATE_PATTERNS:
        for m in pattern.finditer(text):
            label = m.group(1).lower()
            value = m.group(2).strip()
            parsed = parse_date_safe(value)
            if "publish" in label or "posted" in label:
                published = published or parsed or value
            if "deadline" in label or "closing" in label or "apply by" in label:
                deadline = deadline or parsed or value

    return published, deadline


def extract_title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.text.strip():
        return re.sub(r"\s+", " ", soup.title.text.strip())
    h1 = soup.find("h1")
    if h1:
        return re.sub(r"\s+", " ", h1.get_text(" ", strip=True))
    return "Untitled scholarship page"


def extract_fields_from_page(html: str, url: str, country: str, university: University) -> Optional[ScholarshipRecord]:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = extract_title(soup)
    text = soup.get_text("\n", strip=True)
    scan_text = text[:MAX_TEXT_SCAN]
    text_information = scan_text[:MAX_TEXT_INFORMATION] or None

    relevance_blob = f"{title}\n{scan_text[:4000]}".lower()
    if not text_contains_keywords(relevance_blob, SCHOLARSHIP_KEYWORDS):
        return None

    if any(n in relevance_blob for n in NEGATIVE_HINTS):
        if not any(h in relevance_blob for h in ACTIVE_HINTS):
            return None

    meta_dates = extract_meta_dates(soup)
    published_text, deadline_text = extract_dates_from_text(scan_text)

    published = (
        meta_dates.get("article:published_time")
        or meta_dates.get("og:published_time")
        or meta_dates.get("publish-date")
        or meta_dates.get("pubdate")
        or meta_dates.get("citation_publication_date")
        or published_text
    )

    deadline = deadline_text

    department = extract_by_patterns(scan_text, DEPARTMENT_PATTERNS)
    faculty = extract_by_patterns(scan_text, FACULTY_PATTERNS)

    if not department or not faculty:
        headings: list[str] = []
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "strong", "b"]):
            t = tag.get_text(" ", strip=True)
            if t:
                headings.append(t)
        joined = "\n".join(headings[:80])

        department = department or extract_by_patterns(joined, DEPARTMENT_PATTERNS)
        faculty = faculty or extract_by_patterns(joined, FACULTY_PATTERNS)

    if deadline:
        try:
            dd = dateparser.parse(deadline, fuzzy=True)
            if dd and dd.date() < datetime.now().date():
                return None
        except Exception:
            pass

    return ScholarshipRecord(
        country=country,
        university=university.name,
        university_website=university.website,
        scholarship_page=url,
        title=title,
        text_information=text_information,
        date_published=published,
        department=department,
        faculty=faculty,
        deadline=deadline,
        discovered_at_utc=datetime.now(timezone.utc).isoformat(),
    )
