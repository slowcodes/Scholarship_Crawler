from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from app.models.entities import SaveStats, ScholarshipRecord


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


def open_sqlite_with_recovery(path: str) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA quick_check")
        return conn
    except sqlite3.DatabaseError as e:
        msg = str(e).lower()
        if "malformed" not in msg and "not a database" not in msg:
            raise
        try:
            conn.close()
        except Exception:
            pass
        if os.path.exists(path):
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_path = f"{path}.corrupt_{ts}"
            os.replace(path, backup_path)
        return sqlite3.connect(path)


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


def save_to_sqlite(path: str, records: list[ScholarshipRecord]) -> SaveStats:
    stats = SaveStats()
    conn = open_sqlite_with_recovery(path)
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


def fetch_scholarships(
    sqlite_path: str,
    country: Optional[str],
    university: Optional[str],
    limit: int,
) -> list[dict]:
    conn = open_sqlite_with_recovery(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        query = """
            SELECT
                country, university, university_website, scholarship_page, title,
                text_information, date_published, department, faculty, deadline,
                discovered_at_utc, updated_at_utc
            FROM scholarships
            WHERE (? IS NULL OR country = ?)
              AND (? IS NULL OR university = ?)
            ORDER BY updated_at_utc DESC
            LIMIT ?
        """
        rows = conn.execute(query, (country, country, university, university, limit)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
