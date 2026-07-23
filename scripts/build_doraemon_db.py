#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import pandas as pd
from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "database"
DB_DIR.mkdir(parents=True, exist_ok=True)

DORAEMON_SITE_URL = os.getenv("DORAEMON_SITE_URL", "https://doraemon-hindi-1979.netlify.app/#classic")
MANGA_SHEET_URL = os.getenv("MANGA_SHEET_URL", "")

UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\xa0", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return None
    if re.fullmatch(r"[—–-]{3,}", text):
        return None
    return text


def norm_key(value: Any) -> str:
    text = clean_text(value) or ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_html(url: str) -> str:
    r = requests.get(url, headers=UA, timeout=45)
    r.raise_for_status()
    return r.text


def nearest_heading(table: Tag) -> str:
    # Walk backwards to find the closest heading-like text.
    node = table
    for _ in range(30):
        node = node.find_previous()
        if node is None:
            break
        if getattr(node, "name", None) in {"h1", "h2", "h3", "h4", "h5", "h6", "summary"}:
            txt = clean_text(node.get_text(" ", strip=True))
            if txt:
                return txt
        if getattr(node, "name", None) == "p":
            txt = clean_text(node.get_text(" ", strip=True))
            if txt and len(txt) < 120:
                return txt
    return ""


def row_dict_from_table(table: Tag) -> List[Dict[str, str]]:
    rows = []
    headers = []
    # Prefer the first row with th cells as header row
    header_row = None
    for tr in table.find_all("tr"):
        ths = tr.find_all("th")
        if ths:
            header_row = tr
            headers = [clean_text(th.get_text(" ", strip=True)) or "" for th in ths]
            break

    if not headers:
        return rows

    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        values = [clean_text(td.get_text(" ", strip=True)) for td in tds]
        if len(values) != len(headers):
            # Keep partial rows but align to shortest useful mapping.
            count = min(len(values), len(headers))
            values = values[:count]
            heads = headers[:count]
        else:
            heads = headers
        item = {}
        for h, v in zip(heads, values):
            if h:
                item[h] = v
        if item:
            rows.append(item)
    return rows


def detect_category(heading: str, headers: List[str]) -> str:
    h = norm_key(heading)
    hdrs = " ".join(norm_key(x) for x in headers)

    if "classic doraemon" in h:
        return "classic_doraemon"
    if "special" in h or "special episodes" in h or "alternate ep no" in hdrs:
        return "special_episodes"

    m = re.search(r"season\s*(10|[1-9])", h)
    if m:
        return f"season_{int(m.group(1))}"

    if "in season episode" in hdrs or "in season episode" in h:
        # Likely the normal season tables.
        return "classic"

    return "unknown"


def canonicalize_record(raw: Dict[str, str], category: str, heading: str, source: str) -> Dict[str, Any]:
    lowered = {norm_key(k): v for k, v in raw.items()}

    jp = lowered.get("jp story number") or lowered.get("jp story no") or lowered.get("jp")
    season_ep = lowered.get("in season episode") or lowered.get("in season episode no")
    ep_no = lowered.get("in episode number") or lowered.get("in ep number")
    alt_ep = lowered.get("in alternate ep no") or lowered.get("in alternate ep number") or lowered.get("in alternate ep no.")
    title = lowered.get("title") or lowered.get("titles") or lowered.get("name")

    record = {
        "category": category,
        "section_heading": heading,
        "source": source,
        "jp_story_number": jp,
        "india_season_episode": season_ep,
        "india_episode_number": ep_no,
        "india_alternate_episode_number": alt_ep,
        "title": title,
        "raw": raw,
    }

    # Preserve explicit missingness.
    for k in ("jp_story_number", "india_season_episode", "india_episode_number", "india_alternate_episode_number", "title"):
        if record[k] is None:
            record[k] = None

    return record


def generate_aliases(title: Optional[str], category: str, jp: Optional[str], ep_no: Optional[str]) -> List[str]:
    aliases = set()
    parts = [title or "", category.replace("_", " "), jp or "", ep_no or ""]
    combined = norm_key(" ".join(parts))
    if combined:
        aliases.add(combined)

    if title:
        words = [w for w in norm_key(title).split() if len(w) > 2]
        for w in words:
            aliases.add(w)
        # compact 2-word phrases
        for i in range(len(words) - 1):
            aliases.add(f"{words[i]} {words[i+1]}")

    return sorted(a for a in aliases if a)


def build_search_blob(rec: Dict[str, Any]) -> str:
    bits = [
        rec.get("category") or "",
        rec.get("section_heading") or "",
        rec.get("jp_story_number") or "",
        rec.get("india_season_episode") or "",
        rec.get("india_episode_number") or "",
        rec.get("india_alternate_episode_number") or "",
        rec.get("title") or "",
    ]
    aliases = generate_aliases(
        rec.get("title"),
        rec.get("category", ""),
        rec.get("jp_story_number"),
        rec.get("india_episode_number"),
    )
    bits.extend(aliases)
    return norm_key(" ".join(bits))


def parse_doraemon_site(url: str) -> Dict[str, List[Dict[str, Any]]]:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    grouped: Dict[str, List[Dict[str, Any]]] = {
        "season_1": [],
        "season_2": [],
        "season_3": [],
        "season_4": [],
        "season_5": [],
        "season_6": [],
        "season_7": [],
        "season_8": [],
        "season_9": [],
        "season_10": [],
        "special_episodes": [],
        "classic_doraemon": [],
        "classic": [],
        "unknown": [],
    }

    for table in tables:
        heading = nearest_heading(table)
        rows = row_dict_from_table(table)
        if not rows:
            continue

        headers = list(rows[0].keys())
        category = detect_category(heading, headers)

        for raw in rows:
            rec = canonicalize_record(raw, category, heading, url)
            if category.startswith("season_"):
                grouped[category].append(rec)
                grouped["classic"].append(rec)
            elif category in ("special_episodes", "classic_doraemon", "classic"):
                grouped[category].append(rec)
                if category != "classic":
                    grouped["classic"].append(rec)
            else:
                grouped["unknown"].append(rec)

    return grouped


def parse_manga_sheet(url: str) -> List[Dict[str, Any]]:
    if not url:
        return []

    try:
        # Public Google Sheet HTML view often exposes readable tables.
        tables = pd.read_html(url)
    except Exception:
        return []

    manga_rows: List[Dict[str, Any]] = []
    for idx, df in enumerate(tables):
        df.columns = [clean_text(c) or f"column_{i}" for i, c in enumerate(df.columns)]
        for _, row in df.iterrows():
            item = {str(k): clean_text(v) for k, v in row.to_dict().items()}
            if any(v for v in item.values()):
                manga_rows.append({
                    "source_table": idx,
                    "raw": item,
                    "search_blob": norm_key(" ".join(v or "" for v in item.values())),
                })
    return manga_rows


def make_index(all_groups: Dict[str, List[Dict[str, Any]]], manga_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []

    def push(rec: Dict[str, Any], origin: str):
        item = {
            "origin": origin,
            "category": rec.get("category", "unknown"),
            "section_heading": rec.get("section_heading", ""),
            "jp_story_number": rec.get("jp_story_number") or "",
            "india_season_episode": rec.get("india_season_episode") or "",
            "india_episode_number": rec.get("india_episode_number") or "",
            "india_alternate_episode_number": rec.get("india_alternate_episode_number") or "",
            "title": rec.get("title") or "",
            "search_blob": build_search_blob(rec),
        }
        items.append(item)

    for cat in ["season_1", "season_2", "season_3", "season_4", "season_5", "season_6", "season_7", "season_8", "season_9", "season_10", "special_episodes", "classic_doraemon", "classic", "unknown"]:
        for rec in all_groups.get(cat, []):
            push(rec, cat)

    # Optional manga items
    for row in manga_rows:
        items.append({
            "origin": "manga",
            "category": "manga",
            "section_heading": "",
            "jp_story_number": "",
            "india_season_episode": "",
            "india_episode_number": "",
            "india_alternate_episode_number": "",
            "title": "",
            "search_blob": row.get("search_blob", ""),
            "raw": row.get("raw", {}),
        })

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_urls": {
            "doraemon_site": DORAEMON_SITE_URL,
            "manga_sheet": MANGA_SHEET_URL,
        },
        "counts": {
            k: len(v) for k, v in all_groups.items()
        },
        "index_items": len(items),
    }

    return {
        "metadata": metadata,
        "groups": all_groups,
        "manga": manga_rows,
        "items": items,
    }


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    groups = parse_doraemon_site(DORAEMON_SITE_URL)
    manga_rows = parse_manga_sheet(MANGA_SHEET_URL)
    db = make_index(groups, manga_rows)

    write_json(DB_DIR / "episodes.json", db["groups"])
    write_json(DB_DIR / "manga.json", db["manga"])
    write_json(DB_DIR / "search_index.json", {"metadata": db["metadata"], "items": db["items"]})
    write_json(DB_DIR / "metadata.json", db["metadata"])

    # Helpful local summary for commits and debugging
    summary = {
        "generated_at": db["metadata"]["generated_at"],
        "counts": db["metadata"]["counts"],
        "index_items": db["metadata"]["index_items"],
    }
    write_json(DB_DIR / "summary.json", summary)


if __name__ == "__main__":
    main()
