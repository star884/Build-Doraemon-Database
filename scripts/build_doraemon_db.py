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

# Removed #classic - fetch base page that contains ALL data
DORAEMON_SITE_URL = os.getenv("DORAEMON_SITE_URL", "https://doraemon-hindi-1979.netlify.app")
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
    print(f"DEBUG: Fetching {url}")
    r = requests.get(url, headers=UA, timeout=45)
    r.raise_for_status()
    print(f"DEBUG: Got {len(r.text)} bytes")
    return r.text


def parse_markdown_tables(html_content: str) -> List[tuple]:
    """Parse markdown-style pipe tables from HTML text."""
    tables = []
    
    # Look for patterns like: | column1 | column2 | column3 |
    pattern = r'\|\s*[^\|]+\s*\|(?:\s*[^\|]+\s*\|)+'
    matches = re.findall(pattern, html_content, re.MULTILINE)
    
    for match in matches:
        rows = []
        lines = match.strip().split('\n')
        
        for line in lines:
            # Extract cells between pipes
            cells = re.findall(r'\|([^|]+)\|', line)
            cells = [clean_text(c) for c in cells]
            cells = [c for c in cells if c]  # Remove empty
            if cells and len(cells) >= 2:
                rows.append(cells)
        
        if len(rows) >= 2:  # Need header + at least one data row
            tables.append(rows)
    
    return tables


def parse_html_tables(soup: BeautifulSoup) -> List[List[Dict[str, str]]]:
    """Parse traditional HTML tables."""
    all_rows = []
    tables = soup.find_all("table")
    
    print(f"DEBUG: Found {len(tables)} HTML tables")
    
    for table in tables:
        rows = []
        headers = []
        
        # Get header row
        header_row = table.find("tr")
        if header_row:
            th_cells = header_row.find_all(["th", "td"])
            headers = [clean_text(c.get_text(" ", strip=True)) for c in th_cells]
        
        # Get data rows
        for tr in table.find_all("tr")[1:] if headers else table.find_all("tr"):
            td_cells = tr.find_all(["td", "th"])
            values = [clean_text(c.get_text(" ", strip=True)) for c in td_cells]
            
            if headers and len(values) == len(headers):
                row_dict = dict(zip(headers, values))
                if any(row_dict.values()):
                    rows.append(row_dict)
            elif not headers and len(values) >= 2:
                # No headers, just raw values
                row_dict = {f"col_{i}": v for i, v in enumerate(values)}
                rows.append(row_dict)
        
        if rows:
            all_rows.append({"headers": headers, "rows": rows})
    
    return all_rows


def nearest_section_heading(html_text: str, position: int) -> str:
    """Find the closest heading text before a position in HTML."""
    # Look backwards from position for section markers
    before = html_text[max(0, position-500):position]
    
    # Common section indicators
    patterns = [
        r'Season\s*(10|[1-9])',
        r'Classic\s*Doraemon',
        r'Special\s*Episodes?',
        r'Alternate',
        r'Manga',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, before, re.IGNORECASE)
        if match:
            return match.group(0)
    
    return "unknown"


def detect_category_from_headers(headers: List[str], section_hint: str) -> str:
    """Detect category based on headers and section hint."""
    h_section = section_hint.lower()
    hdrs = " ".join(norm_key(h) for h in headers)
    
    if "classic doraemon" in h_section:
        return "classic_doraemon"
    if "special" in h_section or "special episodes" in h_section:
        return "special_episodes"
    
    m = re.search(r"season\s*(10|[1-9])", h_section)
    if m:
        return f"season_{int(m.group(1))}"
    
    # Detect from headers
    if "jp" in hdrs or "story" in hdrs:
        if "season" in hdrs or "in season" in hdrs:
            return "classic"
    
    return "unknown"


def canonicalize_record(raw: Dict[str, str], category: str, heading: str, source: str) -> Dict[str, Any]:
    """Normalize record fields."""
    lowered = {norm_key(k): v for k, v in raw.items()}
    
    jp = lowered.get("jp_story_number") or lowered.get("jp_story_no") or lowered.get("jp") or lowered.get("col_0")
    season_ep = lowered.get("in_season_episode") or lowered.get("in_season_episode_no") or lowered.get("col_1")
    ep_no = lowered.get("in_episode_number") or lowered.get("in_ep_number") or lowered.get("col_2")
    alt_ep = lowered.get("in_alternate_ep_no") or lowered.get("in_alternate_ep_number") or lowered.get("col_2")
    title = lowered.get("title") or lowered.get("titles") or lowered.get("name") or lowered.get("col_3")
    
    # If col-based, try to extract meaningful data
    if not title and len(lowered) >= 4:
        # Assume last column is title
        for i in range(3, -1, -1):
            key = f"col_{i}"
            val = lowered.get(key)
            if val and not re.match(r'^[\d\/\s]+$', val):  # Not just numbers
                title = val
                if ep_no is None and i == 2:
                    ep_no = lowered.get("col_2")
                break
    
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
    
    return record


def generate_aliases(title: Optional[str], category: str, jp: Optional[str], ep_no: Optional[str]) -> List[str]:
    aliases = set()
    if title:
        words = [w for w in norm_key(title).split() if len(w) > 2]
        for w in words:
            aliases.add(w)
        for i in range(len(words) - 1):
            aliases.add(f"{words[i]} {words[i+1]}")
    if category:
        aliases.add(category.replace("_", " "))
    
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
    print("DEBUG: Starting parse_doraemon_site...")
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    
    grouped: Dict[str, List[Dict[str, Any]]] = {
        "season_1": [], "season_2": [], "season_3": [], "season_4": [], "season_5": [],
        "season_6": [], "season_7": [], "season_8": [], "season_9": [], "season_10": [],
        "special_episodes": [], "classic_doraemon": [], "classic": [], "unknown": [],
    }
    
    # Try HTML tables first
    html_parsed = parse_html_tables(soup)
    
    print(f"DEBUG: HTML parser found {len(html_parsed)} parsed tables")
    
    for parsed_table in html_parsed:
        rows = parsed_table["rows"]
        headers = parsed_table.get("headers", [])
        
        if not rows:
            continue
        
        # Create normalized records
        for row_data in rows:
            # Convert list tuples to dict if needed
            if isinstance(row_data, tuple):
                row_dict = {headers[i] if i < len(headers) else f"col_{i}": v for i, v in enumerate(row_data)}
            else:
                row_dict = row_data
            
            heading = nearest_section_heading(html, 0)  # Simplified
            category = detect_category_from_headers(list(row_dict.keys()), heading)
            
            rec = canonicalize_record(row_dict, category, heading, url)
            
            cat_key = category if category.startswith("season_") else category
            if cat_key in grouped:
                grouped[cat_key].append(rec)
                if category != "classic":
                    grouped["classic"].append(rec)
    
    # Fallback: Try markdown-style pipe tables
    if sum(len(v) for v in grouped.values()) < 10:
        print("DEBUG: HTML parsing returned too few results, trying markdown tables...")
        md_tables = parse_markdown_tables(html)
        print(f"DEBUG: Markdown parser found {len(md_tables)} table blocks")
        
        current_category = "unknown"
        current_heading = "unknown"
        
        for table_rows in md_tables:
            if len(table_rows) < 3:
                continue
            
            # First row is headers
            headers = [f"col_{i}" for i in range(len(table_rows[0]))]
            
            # Try to detect category from first data row
            first_data = table_rows[1] if len(table_rows) > 1 else []
            combined = " ".join(first_data)
            
            if "special" in combined.lower() or "spe" in combined.lower():
                current_category = "special_episodes"
                current_heading = "Special Episodes"
            elif re.search(r"s\d+\s*e\d+", combined.lower()):
                # Season/episode format like S04E25
                m = re.search(r's(\d+)\s*e', combined.lower())
                if m:
                    season_num = min(int(m.group(1)), 10)
                    current_category = f"season_{season_num}"
                    current_heading = f"Season {season_num}"
            elif "ce" in combined.lower() or "classic" in combined.lower():
                current_category = "classic_doraemon"
                current_heading = "Classic Doraemon"
            
            # Process data rows (skip header)
            for row_values in table_rows[1:]:
                row_dict = {headers[i]: v for i, v in enumerate(row_values)}
                rec = canonicalize_record(row_dict, current_category, current_heading, url)
                
                if rec.get("title"):  # Only add if we got meaningful data
                    cat_key = current_category if current_category.startswith("season_") else current_category
                    if cat_key in grouped:
                        grouped[cat_key].append(rec)
                        if current_category != "classic":
                            grouped["classic"].append(rec)
    
    # Print counts for debugging
    print(f"DEBUG: Episode counts by category:")
    for cat, items in grouped.items():
        print(f"  {cat}: {len(items)}")
    
    total = sum(len(v) for v in grouped.values())
    print(f"DEBUG: Total episodes parsed: {total}")
    
    return grouped


def parse_manga_sheet(url: str) -> List[Dict[str, Any]]:
    if not url:
        return []

    try:
        tables = pd.read_html(url)
    except Exception as e:
        print(f"DEBUG: Manga sheet parse failed: {e}")
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
    
    print(f"DEBUG: Parsed {len(manga_rows)} manga rows")
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
        "counts": {k: len(v) for k, v in all_groups.items()},
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
    print(f"DEBUG: Wrote {path.name} ({len(json.dumps(data))} bytes)")


def main() -> None:
    print("Starting...")
    print("Website...")
    
    groups = parse_doraemon_site(DORAEMON_SITE_URL)
    manga_rows = parse_manga_sheet(MANGA_SHEET_URL)
    
    print("Episode counts...")
    db = make_index(groups, manga_rows)

    print("Writing files...")
    write_json(DB_DIR / "episodes.json", db["groups"])
    write_json(DB_DIR / "manga.json", db["manga"])
    write_json(DB_DIR / "search_index.json", {"metadata": db["metadata"], "items": db["items"]})
    write_json(DB_DIR / "metadata.json", db["metadata"])

    summary = {
        "generated_at": db["metadata"]["generated_at"],
        "counts": db["metadata"]["counts"],
        "index_items": db["metadata"]["index_items"],
    }
    write_json(DB_DIR / "summary.json", summary)
    
    print("Done.")
    print(f"Total items in index: {db['metadata']['index_items']}")


if __name__ == "__main__":
    main()
