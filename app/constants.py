from __future__ import annotations

import re

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"

HEADERS = {
    "User-Agent": "UniversityScholarshipCrawler/1.0 (+contact: you@example.com)"
}

SCHOLARSHIP_KEYWORDS = [
    "scholarship",
    "scholarships",
    "funding",
    "studentship",
    "studentships",
    "grant",
    "grants",
    "bursary",
    "bursaries",
    "fellowship",
    "fellowships",
    "tuition waiver",
    "financial support",
    "fee waiver",
    "doctoral funding",
    "phd funding",
    "master scholarship",
    "masters scholarship",
    "postgraduate funding",
]

ACTIVE_HINTS = [
    "open",
    "currently open",
    "applications open",
    "apply now",
    "now accepting applications",
    "deadline",
    "closing date",
]

NEGATIVE_HINTS = [
    "archive",
    "archived",
    "expired",
    "closed",
    "past scholarships",
    "previous scholarships",
    "2021",
    "2022",
    "2023",
]

DATE_PATTERNS = [
    re.compile(r"(published|posted|date published|publication date)\\s*[:\\-]?\\s*([A-Za-z0-9,./\\- ]{6,40})", re.I),
    re.compile(r"(deadline|closing date|application deadline|apply by)\\s*[:\\-]?\\s*([A-Za-z0-9,./\\- ]{6,40})", re.I),
]

DEPARTMENT_PATTERNS = [
    re.compile(r"(department)\\s*[:\\-]?\\s*([A-Za-z0-9,&'()./\\- ]{3,120})", re.I),
]

FACULTY_PATTERNS = [
    re.compile(r"(faculty|school|college)\\s*[:\\-]?\\s*([A-Za-z0-9,&'()./\\- ]{3,120})", re.I),
]

META_DATE_KEYS = [
    "article:published_time",
    "og:published_time",
    "publish-date",
    "pubdate",
    "date",
    "dc.date",
    "dc.date.issued",
    "citation_publication_date",
    "last-modified",
]

MAX_TEXT_SCAN = 15000
MAX_TEXT_INFORMATION = 4000
