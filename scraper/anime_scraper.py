#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
CACHE = DATABASE / "cache"
EPISODES_JSON = DATABASE / "episodes.json"

DEFAULT_URL = "https://doraemon-hindi-1979.netlify.app/#classic"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("anime_scraper")


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


def write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_ascii(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return normalize_space(text)


def normalize_title(text: str) -> str:
    text = normalize_ascii(text).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[\u2018\u2019\u201c\u201d']", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return normalize_space(text)


def split_aliases(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"\s*(?:/|\||;|•|·|・|~)\s*", text)
    out: List[str] = []
    for p in parts:
        p = normalize_space(p)
        if p and p not in out:
            out.append(p)
    return out


def parse_date(text: str) -> Optional[str]:
    raw = normalize_space(text)
    if not raw:
        return None

    # Common formats first
    fmts = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b, %Y",
        "%d %B, %Y",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass

    # Fallback: extract a likely date-like chunk and preserve it if parse fails.
    m = re.search(
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
        r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
        raw,
    )
    return m.group(1) if m else None


def extract_title_variants(text: str) -> List[str]:
    variants = []
    for part in split_aliases(text):
        clean = normalize_space(part)
        if clean and clean not in variants:
            variants.append(clean)
    return variants


def parse_episode_block(text: str, href: Optional[str], source_url: str) -> Optional[Dict[str, Any]]:
    raw = normalize_space(text)
    if len(raw) < 8:
        return None

    low = raw.lower()

    # Heuristic filters: keep blocks that look episode-ish.
    if not any(k in low for k in ["episode", "ep ", "ep.", "season", "special", "story", "air", "indian", "japanese", "jp"]):
        # Still allow blocks with strong numbering + a title-like shape.
        if not re.search(r"\b\d{1,4}\b", raw):
            return None

    # Patterns for likely fields.
    indian_episode_number = None
    season = None
    japanese_story_number = None
    air_date = None
    special_marker = None

    patterns = [
        (r"(?:indian\s*(?:episode|ep(?:isode)?)|in(?:dian)?\s*ep(?:isode)?|episode|ep)\s*[:#-]?\s*(\d{1,5})", "indian"),
        (r"(?:season|s)\s*[:#-]?\s*(\d{1,3})", "season"),
        (r"(?:japanese\s*(?:story|episode)|jp\s*(?:story|episode)|story\s*(?:no\.?|number)|jp\s*no\.?)\s*[:#-]?\s*([A-Za-z0-9.\-]+)", "jp"),
    ]
    for pat, kind in patterns:
        m = re.search(pat, low, re.IGNORECASE)
        if m:
            if kind == "indian" and indian_episode_number is None:
                indian_episode_number = m.group(1)
            elif kind == "season" and season is None:
                season = m.group(1)
            elif kind == "jp" and japanese_story_number is None:
                japanese_story_number = m.group(1)

    date_match = re.search(
        r"(\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
        r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
        raw,
    )
    if date_match:
        air_date = parse_date(date_match.group(1))

    if any(k in low for k in ["special episode", "special", "ova", "movie", "feature"]):
        special_marker = "special"

    # Title extraction:
    # Prefer text after a separator, otherwise the whole block.
    title_guess = raw
    split_candidates = [
        " - ",
        " | ",
        " : ",
        " — ",
        " – ",
        "\n",
    ]
    for sep in split_candidates:
        if sep in raw:
            parts = [normalize_space(p) for p in raw.split(sep) if normalize_space(p)]
            if parts:
                # Choose the longest non-numeric fragment that is not a label.
                title_guess = max(parts, key=len)
    title_guess = normalize_space(title_guess)

    # Remove obvious labels from title guess.
    title_guess = re.sub(
        r"(?i)\b(?:indian\s*episode|episode|ep|season|japanese\s*story|jp\s*story|story\s*no\.?|air\s*date|special episode|special)\b[:#-]?",
        "",
        title_guess,
    )
    title_guess = normalize_space(title_guess)

    title_variants = extract_title_variants(title_guess)
    title = title_variants[0] if title_variants else title_guess

    record = {
        "source": source_url,
        "href": href,
        "raw_text": raw,
        "title": title,
        "title_variants": title_variants,
        "title_normalized": normalize_title(title),
        "japanese_story_number": japanese_story_number,
        "indian_episode_number": indian_episode_number,
        "season": season,
        "air_date": air_date,
        "special_marker": special_marker,
        "special_episode": bool(special_marker),
        "collected_at": now_iso(),
    }

    # Drop empty shells.
    if not record["title"] and not record["indian_episode_number"] and not record["japanese_story_number"]:
        return None
    return record


async def extract_blocks(page) -> List[Dict[str, Any]]:
    # Grab multiple sources of text to survive different layouts.
    js = """
    () => {
      const visible = (el) => {
        const s = window.getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s && s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0;
      };

      const pickHref = (el) => {
        if (el.tagName === 'A' && el.href) return el.href;
        const a = el.querySelector && el.querySelector('a[href]');
        return a ? a.href : null;
      };

      const nodes = Array.from(document.querySelectorAll('article, section, li, tr, a, button, div, p, span'));
      const out = [];
      for (const el of nodes) {
        try {
          if (!visible(el)) continue;
          const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
          if (!text || text.length < 6 || text.length > 700) continue;
          const href = pickHref(el);
          out.push({
            tag: el.tagName.toLowerCase(),
            text,
            href,
            cls: el.className ? String(el.className).slice(0, 180) : null,
            id: el.id ? String(el.id).slice(0, 120) : null
          });
        } catch (_) {}
      }
      return out;
    }
    """
    candidates = await page.evaluate(js)
    return candidates or []


async def scrape(url: str, wait_ms: int, headed: bool) -> Dict[str, Any]:
    ensure_dirs()
    seen_path = CACHE / "anime_seen.json"
    raw_path = CACHE / "anime_raw.jsonl"

    seen = set(read_json(seen_path, []))
    records: List[Dict[str, Any]] = []
    raw_rows: List[Dict[str, Any]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        page = await browser.new_page(viewport={"width": 1600, "height": 1400})
        page.set_default_timeout(30000)

        log.info("Opening %s", url)
        await page.goto(url, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        await page.wait_for_timeout(wait_ms)

        candidates = await extract_blocks(page)
        body_text = await page.locator("body").inner_text(timeout=30000)

        # Combine DOM blocks plus large text lines.
        merged_inputs = []
        for c in candidates:
            merged_inputs.append((c.get("text", ""), c.get("href")))
        for line in body_text.splitlines():
            line = normalize_space(line)
            if line:
                merged_inputs.append((line, None))

        # Deduplicate by content hash before parsing.
        deduped_inputs: List[tuple[str, Optional[str]]] = []
        input_seen = set()
        for text, href in merged_inputs:
            key = sha1_text(f"{text}|{href or ''}")
            if key in input_seen:
                continue
            input_seen.add(key)
            deduped_inputs.append((text, href))

        new_count = 0
        for text, href in deduped_inputs:
            parsed = parse_episode_block(text, href, url)
            if not parsed:
                continue

            record_hash = sha1_text(
                "|".join(
                    [
                        parsed.get("title_normalized") or "",
                        parsed.get("indian_episode_number") or "",
                        parsed.get("japanese_story_number") or "",
                        parsed.get("air_date") or "",
                        parsed.get("href") or "",
                    ]
                )
            )
            parsed["record_hash"] = record_hash
            parsed["source_type"] = "anime_website"

            if record_hash in seen:
                continue

            seen.add(record_hash)
            records.append(parsed)
            raw_rows.append(
                {
                    "record_hash": record_hash,
                    "source": url,
                    "href": href,
                    "raw_text": text,
                    "parsed": parsed,
                    "collected_at": now_iso(),
                }
            )
            new_count += 1

        await browser.close()

    # If the cache already had prior records, keep them.
    existing = read_json(EPISODES_JSON, {})
    existing_items = existing.get("items", []) if isinstance(existing, dict) else []
    existing_hashes = {item.get("record_hash") for item in existing_items if isinstance(item, dict)}
    merged_items = list(existing_items)

    for item in records:
        if item["record_hash"] not in existing_hashes:
            merged_items.append(item)

    out_obj = {
        "source_url": url,
        "collected_at": now_iso(),
        "item_count": len(merged_items),
        "new_items_this_run": new_count,
        "items": merged_items,
    }

    write_json(EPISODES_JSON, out_obj)
    write_json(seen_path, sorted(seen))
    if raw_rows:
        write_jsonl(raw_path, raw_rows)

    log.info("Saved %d total episodes (%d new this run)", len(merged_items), new_count)
    return out_obj


def main() -> None:
    parser = argparse.ArgumentParser(description="Playwright-based Doraemon anime scraper")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--wait-ms", type=int, default=4000)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    asyncio.run(scrape(args.url, args.wait_ms, args.headed))


if __name__ == "__main__":
    main()
