#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
CACHE = DATABASE / "cache"
MANGA_JSON = DATABASE / "manga.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("manga_scraper")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    DATABASE.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_title(text: str) -> str:
    text = normalize_space(text).lower()
    text = re.sub(r"[\u2018\u2019\u201c\u201d']", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return normalize_space(text)


def split_aliases(text: str) -> List[str]:
    parts = re.split(r"\s*(?:/|\||;|•|·|・|~)\s*", text or "")
    out: List[str] = []
    for p in parts:
        p = normalize_space(p)
        if p and p not in out:
            out.append(p)
    return out


def guess(row: Dict[str, str], names: List[str]) -> str:
    lowered = {k.lower().strip(): v for k, v in row.items()}
    normalized = {re.sub(r"[^a-z0-9]+", "", k): v for k, v in lowered.items()}

    for name in names:
        key = name.lower().strip()
        key_norm = re.sub(r"[^a-z0-9]+", "", key)
        for k, v in lowered.items():
            if k == key:
                return normalize_space(v)
        for k, v in normalized.items():
            if k == key_norm:
                return normalize_space(v)
    return ""


def read_csv_text(text: str) -> List[Dict[str, str]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except Exception:
        dialect = csv.excel
    reader = csv.DictReader(StringIO(text), dialect=dialect)
    return [dict(row) for row in reader]


def parse_row(row: Dict[str, str], source_url: str, index: int) -> Dict[str, Any]:
    title = guess(row, ["title", "chapter title", "english title", "name", "story title"])
    jp_title = guess(row, ["japanese title", "jp title", "original title", "title jp"])
    volume = guess(row, ["volume", "vol", "book"])
    chapter_no = guess(row, ["chapter", "chapter no", "chapter number", "no"])
    story_no = guess(row, ["japanese story number", "jp story number", "story number", "jp no", "jp"])
    indian_ep = guess(row, ["indian episode number", "episode", "ep", "in episode", "anime episode"])
    alt = guess(row, ["alternate title", "alt title", "alt", "aliases", "alias"])
    notes = guess(row, ["notes", "note", "remarks", "comment"])
    link = guess(row, ["link", "url", "source"])

    combined_title = title or jp_title or guess(row, list(row.keys()))[:120]
    variants = []
    for block in [combined_title, jp_title, alt]:
        variants.extend(split_aliases(block))
    variants = list(dict.fromkeys([v for v in variants if v]))

    record = {
        "source": source_url,
        "source_row_index": index,
        "raw_row": row,
        "title": combined_title,
        "jp_title": jp_title or None,
        "title_variants": variants,
        "title_normalized": normalize_title(combined_title),
        "jp_title_normalized": normalize_title(jp_title) if jp_title else None,
        "volume": volume or None,
        "chapter_no": chapter_no or None,
        "japanese_story_number": story_no or None,
        "indian_episode_number": indian_ep or None,
        "alternate_title": alt or None,
        "notes": notes or None,
        "link": link or None,
        "collected_at": now_iso(),
    }

    record["record_hash"] = sha1_text(
        "|".join(
            [
                record["title_normalized"] or "",
                record["jp_title_normalized"] or "",
                record["volume"] or "",
                record["chapter_no"] or "",
                record["japanese_story_number"] or "",
                record["indian_episode_number"] or "",
                record["link"] or "",
            ]
        )
    )
    return record


def download_csv_text(csv_url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; DoraemonDB/1.0; +https://openai.com)",
        "Accept": "text/csv,text/plain,*/*",
    }
    r = requests.get(csv_url, headers=headers, timeout=60)
    r.raise_for_status()
    return r.text


def scrape(csv_url: str) -> Dict[str, Any]:
    ensure_dirs()
    seen_path = CACHE / "manga_seen.json"
    seen = set(read_json(seen_path, []))

    text = download_csv_text(csv_url)
    rows = read_csv_text(text)

    existing = read_json(MANGA_JSON, {})
    existing_items = existing.get("items", []) if isinstance(existing, dict) else []
    existing_hashes = {item.get("record_hash") for item in existing_items if isinstance(item, dict)}
    merged_items = list(existing_items)

    new_count = 0
    raw_added = 0
    for i, row in enumerate(rows):
        parsed = parse_row(row, csv_url, i)
        raw_added += 1
        if parsed["record_hash"] in seen or parsed["record_hash"] in existing_hashes:
            continue
        seen.add(parsed["record_hash"])
        merged_items.append(parsed)
        new_count += 1

    out_obj = {
        "source_url": csv_url,
        "collected_at": now_iso(),
        "row_count": len(rows),
        "item_count": len(merged_items),
        "new_items_this_run": new_count,
        "items": merged_items,
    }

    write_json(MANGA_JSON, out_obj)
    write_json(seen_path, sorted(seen))
    log.info("Saved %d total manga rows (%d new this run)", len(merged_items), new_count)
    return out_obj


def main() -> None:
    parser = argparse.ArgumentParser(description="CSV-based Doraemon manga scraper")
    parser.add_argument("--csv-url", required=True, help="Public CSV export URL from Google Sheets")
    args = parser.parse_args()
    scrape(args.csv_url)


if __name__ == "__main__":
    main()
