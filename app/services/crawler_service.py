from __future__ import annotations

import asyncio
from collections import deque
from typing import Optional
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import aiohttp
from bs4 import BeautifulSoup

from app.constants import HEADERS, SCHOLARSHIP_KEYWORDS, WIKIDATA_ENDPOINT
from app.models.entities import SaveStats, ScholarshipRecord, University
from app.repos.scholarship_repo import save_to_sqlite
from app.services.extraction_service import extract_fields_from_page


class RobotsCache:
    def __init__(self) -> None:
        self._cache: dict[str, RobotFileParser] = {}

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
    cleaned, _frag = urldefrag(url.strip())
    return cleaned.rstrip("/")


def same_domain(seed_url: str, candidate_url: str) -> bool:
    a = urlparse(seed_url).netloc.lower().replace("www.", "")
    b = urlparse(candidate_url).netloc.lower().replace("www.", "")
    return a == b


def looks_html_content_type(content_type: str | None) -> bool:
    if not content_type:
        return True
    lowered = content_type.lower()
    return "text/html" in lowered or "application/xhtml+xml" in lowered


async def fetch_text(session: aiohttp.ClientSession, url: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
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


async def get_public_universities(country_name: str) -> list[University]:
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

    items: list[University] = []
    seen: set[str] = set()

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


def extract_candidate_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(" ", strip=True)
        combined = f"{href} {text}".lower()

        if any(k in combined for k in SCHOLARSHIP_KEYWORDS):
            full = normalize_url(urljoin(base_url, href))
            if full.startswith("http"):
                candidates.append(full)

    result: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


async def crawl_university(
    session: aiohttp.ClientSession,
    robots: RobotsCache,
    university: University,
    country: str,
    max_pages_per_site: int = 80,
    concurrency_delay: float = 1.0,
) -> list[ScholarshipRecord]:
    seed = university.website
    queue = deque([seed])
    visited: set[str] = set()
    results: list[ScholarshipRecord] = []

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

        record = extract_fields_from_page(html, url, country, university)
        if record:
            results.append(record)

        for link in extract_candidate_links(html, url):
            if same_domain(seed, link) and link not in visited:
                queue.append(link)

        await asyncio.sleep(concurrency_delay)

    dedup: dict[str, ScholarshipRecord] = {}
    for record in results:
        dedup[record.scholarship_page] = record

    return list(dedup.values())


async def crawl_and_save(
    country: str,
    max_pages_per_site: int,
    limit_universities: Optional[int],
    sqlite_path: str,
) -> tuple[int, SaveStats]:
    universities = await get_public_universities(country)

    if limit_universities:
        universities = universities[:limit_universities]

    connector = aiohttp.TCPConnector(limit=10, ssl=False)
    timeout = aiohttp.ClientTimeout(total=30)
    robots = RobotsCache()

    all_records: list[ScholarshipRecord] = []

    async with aiohttp.ClientSession(headers=HEADERS, connector=connector, timeout=timeout) as session:
        for university in universities:
            try:
                records = await crawl_university(
                    session=session,
                    robots=robots,
                    university=university,
                    country=country,
                    max_pages_per_site=max_pages_per_site,
                    concurrency_delay=1.0,
                )
                all_records.extend(records)
            except Exception:
                continue

    uniq: dict[tuple[str, str], ScholarshipRecord] = {}
    for record in all_records:
        uniq[(record.university, record.scholarship_page)] = record

    final_records = list(uniq.values())
    stats = save_to_sqlite(sqlite_path, final_records)
    return len(final_records), stats
