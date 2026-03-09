#!/usr/bin/env python3
"""
scholarship_crawler.py

Crawl public university websites for active scholarships in a chosen country.

Features:
- Fetches public universities + official websites from Wikidata
- Respects robots.txt (best effort)
- Crawls scholarship-related pages only
- Extracts: text information, date published, department, faculty, deadline
- Saves/updates scholarships in SQLite

Usage:
    python scholarship_crawler.py --country "Germany"
    python scholarship_crawler.py --country "France" --max-pages-per-site 120
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import sqlite3
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List, Dict, Set, Tuple
from urllib.parse import urljoin, urlparse, urldefrag

import aiohttp
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from urllib.robotparser import RobotFileParser


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
    re.compile(r"(published|posted|date published|publication date)\s*[:\-]?\s*([A-Za-z0-9,./\- ]{6,40})", re.I),
    re.compile(r"(deadline|closing date|application deadline|apply by)\s*[:\-]?\s*([A-Za-z0-9,./\- ]{6,40})", re.I),
]

DEPARTMENT_PATTERNS = [
    re.compile(r"(department)\s*[:\-]?\s*([A-Za-z0-9,&'()./\- ]{3,120})", re.I),
]

FACULTY_PATTERNS = [
    re.compile(r"(faculty|school|college)\s*[:\-]?\s*([A-Za-z0-9,&'()./\- ]{3,120})", re.I),
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


class RobotsCache:
    def __init__(self) -> None:
        self._cache: Dict[str, RobotFileParser] = {}

    async def allowed(self, session: aiohttp.ClientSession, url: str, user_agent: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = f"{base}/robots.txt"

        if base not in self._cache:
            rp = RobotFileParser()
            try:
                async with session.get(robots_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status >= 400:
                        rp.parse([])
                    else:
                        text = await resp.text(errors="ignore")
                        rp.parse(text.splitlines())
            except Exception:
                rp.parse([])
            self._cache[base] = rp

        return self._cache[base].can_fetch(user_agent, url)


def normalize_url(url: str) -> str:
    url, _frag = urldefrag(url.strip())
    return url.rstrip("/")


def same_domain(seed_url: str, candidate_url: str) -> bool:
    a = urlparse(seed_url).netloc.lower().replace("www.", "")
    b = urlparse(candidate_url).netloc.lower().replace("www.", "")
    return a == b


def looks_html_content_type(content_type: str | None) -> bool:
    if not content_type:
        return True
    return "text/html" in content_type.lower() or "application/xhtml+xml" in content_type.lower()


def text_contains_keywords(text: str, keywords: List[str]) -> bool:
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


def extract_meta_dates(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    found: Dict[str, Optional[str]] = {}
    for meta in soup.find_all("meta"):
        key = (meta.get("property") or meta.get("name") or "").strip().lower()
        value = (meta.get("content") or "").strip()
        if key in META_DATE_KEYS and value:
            found[key] = parse_date_safe(value) or value
    return found


def extract_by_patterns(text: str, patterns: List[re.Pattern]) -> Optional[str]:
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            value = m.group(2).strip(" :-\n\t")
            if value:
                return re.sub(r"\s{2,}", " ", value)
    return None


def extract_dates_from_text(text: str) -> Tuple[Optional[str], Optional[str]]:
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


def extract_fields_from_page(html: str, url: str, country: str, university: University) -> Optional[ScholarshipRecord]:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = extract_title(soup)
    text = soup.get_text("\n", strip=True)
    scan_text = text[:MAX_TEXT_SCAN]
    text_information = scan_text[:MAX_TEXT_INFORMATION] or None

    # Basic relevance filter
    relevance_blob = f"{title}\n{scan_text[:4000]}".lower()
    if not text_contains_keywords(relevance_blob, SCHOLARSHIP_KEYWORDS):
        return None

    if any(n in relevance_blob for n in NEGATIVE_HINTS):
        # Keep only if there are also strong active signals
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

    # Heuristic fallback from headings / labels
    if not department or not faculty:
        headings = []
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "strong", "b"]):
            t = tag.get_text(" ", strip=True)
            if t:
                headings.append(t)
        joined = "\n".join(headings[:80])

        department = department or extract_by_patterns(joined, DEPARTMENT_PATTERNS)
        faculty = faculty or extract_by_patterns(joined, FACULTY_PATTERNS)

    # Consider active only if deadline missing or future / today
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


async def fetch_text(session: aiohttp.ClientSession, url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=25), allow_redirects=True) as resp:
            content_type = resp.headers.get("Content-Type")
            if resp.status >= 400:
                return None, content_type, f"HTTP {resp.status}"
            if not looks_html_content_type(content_type):
                return None, content_type, "Non-HTML"
            text = await resp.text(errors="ignore")
            return text, content_type, None
    except Exception as e:
        return None, None, str(e)


async def get_public_universities(country_name: str) -> List[University]:
    """
    Tries to fetch public universities and official websites from Wikidata.

    Note:
    - public university = wd:Q875538
    - country is matched by English label
    """
    query = f"""
    SELECT DISTINCT ?item ?itemLabel ?website WHERE {{
      ?country rdfs:label "{country_name}"@en .
      ?item wdt:P31/wdt:P279* wd:Q875538 .
      ?item wdt:P17 ?country .
      OPTIONAL {{ ?item wdt:P856 ?website . }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    ORDER BY ?itemLabel
    """

    params = {"format": "json", "query": query}
    headers = {"Accept": "application/sparql-results+json", **HEADERS}

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(WIKIDATA_ENDPOINT, params=params, timeout=aiohttp.ClientTimeout(total=45)) as resp:
            resp.raise_for_status()
            data = await resp.json()

    items: List[University] = []
    seen: Set[str] = set()

    for row in data.get("results", {}).get("bindings", []):
        name = row.get("itemLabel", {}).get("value", "").strip()
        item_uri = row.get("item", {}).get("value", "")
        website = row.get("website", {}).get("value", "").strip()
        wikidata_id = item_uri.rsplit("/", 1)[-1] if item_uri else ""

        if not name or not website:
            continue

        website = normalize_url(website)
        if website in seen:
            continue

        parsed = urlparse(website)
        if not parsed.scheme.startswith("http"):
            continue

        seen.add(website)
        items.append(University(name=name, website=website, wikidata_id=wikidata_id))

    return items


def extract_candidate_links(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: List[str] = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(" ", strip=True)
        combined = f"{href} {text}".lower()

        if any(k in combined for k in SCHOLARSHIP_KEYWORDS):
            full = normalize_url(urljoin(base_url, href))
            if full.startswith("http"):
                candidates.append(full)

    # Deduplicate while preserving order
    result = []
    seen = set()
    for u in candidates:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


async def crawl_university(
    session: aiohttp.ClientSession,
    robots: RobotsCache,
    university: University,
    country: str,
    max_pages_per_site: int = 80,
    concurrency_delay: float = 1.0,
) -> List[ScholarshipRecord]:
    seed = university.website
    queue = deque([seed])
    visited: Set[str] = set()
    results: List[ScholarshipRecord] = []

    while queue and len(visited) < max_pages_per_site:
        url = normalize_url(queue.popleft())
        if url in visited:
            continue
        if not same_domain(seed, url):
            continue

        visited.add(url)

        allowed = await robots.allowed(session, url, HEADERS["User-Agent"])
        if not allowed:
            continue

        html, _ct, err = await fetch_text(session, url)
        if err or not html:
            await asyncio.sleep(concurrency_delay)
            continue

        # If page itself looks like a scholarship page, extract
        record = extract_fields_from_page(html, url, country, university)
        if record:
            results.append(record)

        # Expand only through relevant links
        for link in extract_candidate_links(html, url):
            if same_domain(seed, link) and link not in visited:
                queue.append(link)

        await asyncio.sleep(concurrency_delay)

    # De-duplicate by scholarship_page
    dedup: Dict[str, ScholarshipRecord] = {}
    for r in results:
        dedup[r.scholarship_page] = r

    return list(dedup.values())


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scholarships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country TEXT NOT NULL,
            university TEXT NOT NULL,
            university_website TEXT NOT NULL,
            scholarship_page TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            text_information TEXT,
            date_published TEXT,
            department TEXT,
            faculty TEXT,
            deadline TEXT,
            discovered_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            content_hash TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scholarships_university ON scholarships(university)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scholarships_deadline ON scholarships(deadline)")
    conn.commit()


def save_to_sqlite(path: str, records: List[ScholarshipRecord]) -> SaveStats:
    stats = SaveStats()
    conn = sqlite3.connect(path)
    try:
        init_db(conn)
        now_utc = datetime.now(timezone.utc).isoformat()
        for rec in records:
            row = conn.execute(
                "SELECT content_hash FROM scholarships WHERE scholarship_page = ?",
                (rec.scholarship_page,),
            ).fetchone()

            new_hash = scholarship_content_hash(rec)

            if row is None:
                conn.execute(
                    """
                    INSERT INTO scholarships (
                        country, university, university_website, scholarship_page, title,
                        text_information, date_published, department, faculty, deadline,
                        discovered_at_utc, updated_at_utc, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec.country,
                        rec.university,
                        rec.university_website,
                        rec.scholarship_page,
                        rec.title,
                        rec.text_information,
                        rec.date_published,
                        rec.department,
                        rec.faculty,
                        rec.deadline,
                        rec.discovered_at_utc,
                        now_utc,
                        new_hash,
                    ),
                )
                stats.inserted += 1
                continue

            old_hash = row[0]
            if old_hash == new_hash:
                stats.unchanged += 1
                continue

            conn.execute(
                """
                UPDATE scholarships
                SET country = ?,
                    university = ?,
                    university_website = ?,
                    title = ?,
                    text_information = ?,
                    date_published = ?,
                    department = ?,
                    faculty = ?,
                    deadline = ?,
                    updated_at_utc = ?,
                    content_hash = ?
                WHERE scholarship_page = ?
                """,
                (
                    rec.country,
                    rec.university,
                    rec.university_website,
                    rec.title,
                    rec.text_information,
                    rec.date_published,
                    rec.department,
                    rec.faculty,
                    rec.deadline,
                    now_utc,
                    new_hash,
                    rec.scholarship_page,
                ),
            )
            stats.updated += 1

        conn.commit()
        return stats
    finally:
        conn.close()


async def run(country: str, max_pages_per_site: int, limit_universities: Optional[int], sqlite_path: str) -> None:
    print(f"[INFO] Fetching public universities for: {country}")
    universities = await get_public_universities(country)

    if limit_universities:
        universities = universities[:limit_universities]

    print(f"[INFO] Found {len(universities)} universities with websites")

    connector = aiohttp.TCPConnector(limit=10, ssl=False)
    timeout = aiohttp.ClientTimeout(total=30)
    robots = RobotsCache()

    all_records: List[ScholarshipRecord] = []

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector, timeout=timeout) as session:
        for idx, uni in enumerate(universities, start=1):
            print(f"[{idx}/{len(universities)}] Crawling {uni.name} -> {uni.website}")
            try:
                records = await crawl_university(
                    session=session,
                    robots=robots,
                    university=uni,
                    country=country,
                    max_pages_per_site=max_pages_per_site,
                    concurrency_delay=1.0,
                )
                print(f"    Found {len(records)} scholarship page(s)")
                all_records.extend(records)
            except Exception as e:
                print(f"    ERROR: {e}")

    # De-duplicate by (university, scholarship_page)
    uniq: Dict[Tuple[str, str], ScholarshipRecord] = {}
    for rec in all_records:
        uniq[(rec.university, rec.scholarship_page)] = rec

    final_records = list(uniq.values())
    stats = save_to_sqlite(sqlite_path, final_records)

    print(f"\n[DONE] Saved {len(final_records)} records")
    print(f"SQLite DB : {sqlite_path}")
    print(f"Inserted  : {stats.inserted}")
    print(f"Updated   : {stats.updated}")
    print(f"Unchanged : {stats.unchanged}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl public university scholarship pages by country")
    parser.add_argument("--country", required=True, help='Country name, e.g. "Germany", "France", "Netherlands"')
    parser.add_argument("--max-pages-per-site", type=int, default=80, help="Maximum pages to inspect per university website")
    parser.add_argument("--limit-universities", type=int, default=None, help="Optional limit for testing")
    parser.add_argument("--sqlite-path", default="scholarships.db", help="SQLite database file path")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    asyncio.run(run(
        country=args.country,
        max_pages_per_site=args.max_pages_per_site,
        limit_universities=args.limit_universities,
        sqlite_path=args.sqlite_path,
    ))


if __name__ == "__main__":
    main()
