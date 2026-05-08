"""
db_setup.py — MediaVault SQLite schema initializer
Creates C:/AI/Platform\MediaVault\core\mediavault.sqlite
Run once. Safe to re-run (uses CREATE TABLE IF NOT EXISTS).
"""

import sqlite3
import os
import sys

DB_PATH = r"C:\AI\Platform\MediaVault\core\mediavault.sqlite"


def create_schema(conn):
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS artifacts (
            id                      TEXT PRIMARY KEY,
            domain                  TEXT NOT NULL CHECK(domain IN ('hunter_root','genealogy','personal')),
            source_url              TEXT,
            source_platform         TEXT CHECK(source_platform IN (
                                        'instagram','youtube','facebook','bandcamp',
                                        'press','local','other')),
            capture_date            DATE,
            post_date               DATE,
            post_date_confidence    TEXT CHECK(post_date_confidence IN (
                                        'extracted','manual','estimated','unknown')),
            link_status             TEXT CHECK(link_status IN ('live','dead','local-only')),
            local_asset_path        TEXT,
            thumbnail_path          TEXT,
            description_short       TEXT,
            description_long        TEXT,
            extracted_text          TEXT,
            author_name             TEXT,
            media_type_in_post      TEXT CHECK(media_type_in_post IN (
                                        'photo','video','link','text-only','artwork','mixed')),
            tags_year_era           TEXT,
            tags_content_type       TEXT,
            tags_song_reference     TEXT,
            tags_release_stage      TEXT,
            tags_subject            TEXT,
            tags_topic              TEXT,
            tags_rarity             TEXT,
            tags_preservation       TEXT,
            tags_permission         TEXT,
            tags_keywords           TEXT,
            permission_contact      TEXT,
            permission_evidence_path TEXT,
            post_usage_log          TEXT,
            notes                   TEXT,
            ingest_date             DATE NOT NULL,
            ingest_source           TEXT CHECK(ingest_source IN (
                                        'screenshot-pipeline','local-drop',
                                        'url-entry','csv-import','extension-capture')),
            confidence_flags        TEXT
        )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_domain        ON artifacts(domain)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_capture_date  ON artifacts(capture_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_post_date     ON artifacts(post_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_link_status   ON artifacts(link_status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ingest_date   ON artifacts(ingest_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ingest_source ON artifacts(ingest_source)")

    c.execute("""
        CREATE TABLE IF NOT EXISTS id_sequence (
            domain      TEXT NOT NULL,
            date_str    TEXT NOT NULL,
            last_seq    INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (domain, date_str)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS ingest_queue (
            queue_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            domain          TEXT NOT NULL,
            ingest_source   TEXT NOT NULL,
            raw_path        TEXT,
            source_url      TEXT,
            queued_at       TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending'
                                CHECK(status IN ('pending','keep','skip','enriched','approved','failed')),
            enrichment_json TEXT,
            error_message   TEXT
        )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON ingest_queue(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_queue_domain ON ingest_queue(domain)")

    conn.commit()
    print("Schema created successfully.")


def next_id(conn, domain):
    from datetime import date
    prefixes = {"hunter_root": "HR", "genealogy": "GN", "personal": "PE"}
    prefix = prefixes[domain]
    date_str = date.today().strftime("%Y%m%d")
    c = conn.cursor()
    c.execute("""
        INSERT INTO id_sequence (domain, date_str, last_seq)
        VALUES (?, ?, 1)
        ON CONFLICT(domain, date_str) DO UPDATE SET last_seq = last_seq + 1
    """, (domain, date_str))
    conn.commit()
    c.execute("SELECT last_seq FROM id_sequence WHERE domain=? AND date_str=?",
              (domain, date_str))
    seq = c.fetchone()[0]
    return f"MV-{prefix}-{date_str}-{seq:03d}"


if __name__ == "__main__":
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    create_schema(conn)

    for domain in ("hunter_root", "genealogy", "personal"):
        sample_id = next_id(conn, domain)
        print(f"  Sample ID ({domain}): {sample_id}")

    conn.close()
    print(f"\nDatabase at: {DB_PATH}")

