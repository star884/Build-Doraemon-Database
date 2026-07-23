#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import pandas as pd
from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "database"
DB_DIR.mkdir(parents=True, exist_ok=True)

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

def detect_category_from_episode_data(rows: List[Dict[str, str]]) -> str:
    """Detect category by analyzing actual episode codes in the data."""
    # Sample first few rows to find patterns
    sample_size = min(5, len(rows))
    
    for row in rows[:sample_size]:
        combined = " ".join(str(v) for v in row.values() if v)
        
        # Check for Special Episodes (SPE30, SPE31, etc.)
        if re.search(r'\bSPE\d+\b', combined.upper()):
            print(f"DEBUG: Detected SPECIAL_EPISODES from codes like SPE")
            return "special_episodes"
        
        # Check for Classic Doraemon (CE38, CE39, etc.)
        if re.search(r'\bCE\d+\b', combined.upper()):
            print(f"DEBUG: Detected CLASSIC_DORAEMON from codes like CE")
            return "classic_doraemon"
        
        # Check for Season/Episode format (S04E25, S10E34, etc.)
        m = re.search(r'\bS(\d{1,2})E(\d{1,2})\b', combined.upper())
        if m:
            season_num = int(m.group(1))
            print(f"DEBUG: Detected SEASON_{season_num} from codes like S04E25")
            return f"season_{season_num}"
        
        # Check for JP story number format (1129 / 1130)
        m = re.search(r'(\d{3,4})\s*/\s*(\d{3,4})', combined)
        if m:
            # This is likely a season table with dual episode numbers
            # Fall back to checking section heading
            pass
    
    return "unknown"

def nearest_section_heading(html_text: str, position: int) -> str:
    """Find the closest heading text before a position in HTML."""
    before = html_text[max(0, position-500):position]
    
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

def canonicalize_record(raw: Dict[str, str], category: str, heading: str, source: str) -> Dict[str, Any]:
    lowered = {norm_key(k): v for k, v in raw.items()}
    
    # Handle both named columns and positional col_N columns
    jp = (lowered.get("jp_story_number") or lowered.get("jp_story_no") or 
          lowered.get("jp") or lowered.get("col_0"))
    season_ep = (lowered.get("in_season_episode") or lowered.get("in_season_episode_no") or 
                 lowered.get("col_1"))
    ep_no = (lowered.get("in_episode_number") or lowered.get("in_ep_number") or 
             lowered.get("col_2"))
    alt_ep = (lowered.get("in_alternate_ep_no") or lowered.get("in_alternate_ep_number") or 
              lowered.get("in_alternate_ep_no.") or lowered.get("col_2"))
    title = (lowered.get("title") or lowered.get("titles") or lowered.get("name") or 
             lowered.get("col_3") or lowered.get("col_4"))
    
    # Try to extract title from any remaining column if col_3/4 empty
    if not title:
        for i in range(5, -1, -1):
            key = f"col_{i}"
            val = lowered.get(key)
            if val and not re.match(r'^[\d/\s\-]+$', val):
                title = val
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

def parse_html_tables(soup: BeautifulSoup, html: str) -> Dict[str, List[Dict[str, Any]]]:
    """Parse HTML tables with proper category detection."""
    grouped: Dict[str, List[Dict[str, Any]]] = {
        "season_1": [], "season_2": [], "season_3": [], "season_4": [], "season_5": [],
        "season_6": [], "season_7": [], "season_8": [], "season_9": [], "season_10": [],
        "special_episodes": [], "classic_doraemon": [], "classic": [], "unknown": [],
    }
    
    tables = soup.find_all("table")
    print(f"DEBUG: Found {len(tables)} HTML tables")
    
    for table_idx, table in enumerate(tables):
        # Parse table rows
        rows = []
        headers = []
        
        # Look for header row
        header_row = None
        for tr in table.find_all("tr")[:3]:  # Check first 3 rows for headers
            th_cells = tr.find_all(["th", "td"])
            if th_cells and any("ep" in str(cell).lower() or "story" in str(cell).lower() 
                               or "number" in str(cell).lower() for cell in th_cells):
                header_row = tr
                headers = [clean_text(cell.get_text(" ", strip=True)) or f"col_{i}" 
                          for i, cell in enumerate(th_cells)]
                break
        
        # If no header found, use generic column names
        if not headers:
            first_tr = table.find("tr")
            if first_tr:
                td_cells = first_tr.find_all(["td", "th"])
                headers = [f"col_{i}" for i in range(len(td_cells))]
        
        # Parse data rows
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            # Skip header row
            if cells == header_row.find_all(["th", "td"]) if header_row else False:
                continue
            
            values = [clean_text(cell.get_text(" ", strip=True)) for cell in cells]
            values = [v for v in values if v]  # Remove empty
            
            if len(values) >= 2:  # Minimum useful row
                row_dict = {headers[i] if i < len(headers) else f"col_{i}": v 
                           for i, v in enumerate(values)}
                rows.append(row_dict)
        
        if not rows:
            continue
        
        print(f"DEBUG: Table {table_idx + 1} has {len(rows)} rows, headers: {headers[:3]}")
        
        # DETECT CATEGORY FROM ACTUAL DATA
        category = detect_category_from_episode_data(rows)
        heading = nearest_section_heading(html, 0)
        
        if category == "unknown":
            # Fallback: try to detect from row data patterns
            first_row = rows[0] if rows else {}
            combined = " ".join(str(v) for v in first_row.values())
            
            if "special" in combined.lower() or "alt" in combined.lower():
                category = "special_episodes"
            elif "classic" in combined.lower():
                category = "classic_doraemon"
        
        print(f"DEBUG: Table assigned to category '{category}'")
        
        # Add records to appropriate groups
        for row_data in rows:
            rec = canonicalize_record(row_data, category, heading, DORAEMON_SITE_URL)
            
            # Only add if we have meaningful title or episode number
            if rec.get("title") or rec.get("india_episode_number"):
                cat_key = category
                
                # Add to season-specific bucket
                if cat_key in grouped:
                    grouped[cat_key].append(rec)
                
                # Add to classic group for all non-special content
                if category not in ("special_episodes", "classic"):
                    grouped["classic"].append(rec)
    
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
    
    html = fetch_html(DORAEMON_SITE_URL)
    soup = BeautifulSoup(html, "html.parser")
    
    groups = parse_html_tables(soup, html)
    manga_rows = parse_manga_sheet(MANGA_SHEET_URL)
    
    print("Episode counts...")
    for cat, items in groups.items():
        print(f"  {cat}: {len(items)}")
    total = sum(len(v) for v in groups.values())
    print(f"DEBUG: Total episodes parsed: {total}")
    
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
