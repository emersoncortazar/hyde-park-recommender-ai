"""
SQLite cache for scraped specs.

Every (brand, part_number) result is stored with a timestamp and source.
Re-running the pipeline skips already-cached parts unless --force is passed.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


DB_PATH = Path("data/scrape_cache.db")

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS scrape_results (
    brand                TEXT NOT NULL,
    part_number          TEXT NOT NULL,
    source               TEXT,
    scraped_description  TEXT,
    scraped_specs        TEXT,   -- JSON dict of spec_name -> value
    status               TEXT,   -- 'ok' | 'not_found' | 'error'
    error_msg            TEXT,
    scraped_at           TEXT,
    PRIMARY KEY (brand, part_number)
);
CREATE INDEX IF NOT EXISTS idx_status ON scrape_results(status);
"""


class ScrapeCache:
    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_CREATE_SQL)
        self._conn.commit()

    def get(self, brand: str, part_number: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM scrape_results WHERE brand=? AND part_number=?",
            (brand.lower(), part_number.upper()),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("scraped_specs"):
            result["scraped_specs"] = json.loads(result["scraped_specs"])
        return result

    def set(
        self,
        brand: str,
        part_number: str,
        source: str,
        scraped_description: Optional[str],
        scraped_specs: Optional[dict],
        status: str,
        error_msg: Optional[str] = None,
    ):
        self._conn.execute(
            """
            INSERT OR REPLACE INTO scrape_results
              (brand, part_number, source, scraped_description, scraped_specs,
               status, error_msg, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                brand.lower(),
                part_number.upper(),
                source,
                scraped_description,
                json.dumps(scraped_specs) if scraped_specs else None,
                status,
                error_msg,
                datetime.utcnow().isoformat(),
            ),
        )
        self._conn.commit()

    def pending(self, df, force: bool = False):
        """Return rows from df that haven't been successfully scraped yet."""
        if force:
            return df
        cached_ok = set(
            (r["brand"], r["part_number"])
            for r in self._conn.execute(
                "SELECT brand, part_number FROM scrape_results WHERE status='ok'"
            ).fetchall()
        )
        mask = ~df.apply(
            lambda r: (r["brand_name"].lower(), r["manufacturer_part_number"].upper())
            in cached_ok,
            axis=1,
        )
        return df[mask]

    def stats(self) -> dict:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as n FROM scrape_results GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    def close(self):
        self._conn.close()
