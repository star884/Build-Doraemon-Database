#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
CACHE = DATABASE / "cache"

EPISODES_JSON = DATABASE / "episodes.json"
MANGA_JSON = DATABASE / "manga.json"
SEARCH_INDEX_JSON = DATABASE / "search_index.json"
METADATA_JSON = DATABASE / "metadata.json"
SUMMARY_JSON = DATABASE / "summary.json"
MAPPINGS_JSON = CACHE / "mappings.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("merge_database")


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


def title_variants(item: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for key in ["title", "jp_title", "alternate_title", "notes"]:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            for part in re.split(r"\s*(?:/|\||;|•|·|・|~)\s*", value):
                part = normalize_space(part)
                if part and part not in out:
                    out.append(part)
    for v in item.get("title_variants") or []:
        if isinstance(v, str):
            v = normalize_space(v)
            if v and v not in out:
                out.append(v)
    return out


def sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def story_token(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = normalize_space(str(value))
    if not v:
        return None
    return re.sub(r"[^a-z0-9]+", "", v.lower())


def record_key(prefix: str, item: Dict[str, Any]) -> str:
    parts = [
        item.get("indian_episode_number") or item.get("chapter_no") or "",
        item.get("japanese_story_number") or "",
        item.get("title_normalized") or "",
    ]
    parts = [re.sub(r"[^a-z0-9]+", "-", str(p).lower()).strip("-") for p in parts if str(p).strip()]
    tail = "-".join(parts[:3]) if parts else "unknown"
    return f"{prefix}:{tail}"


def load_table(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".json":
        obj = read_json(path, [])
        if isinstance(obj, dict) and isinstance(obj.get("items"), list):
            return obj["items"]
        if isinstance(obj, list):
            return obj
        return []
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(r) for r in reader]
    return []


def load_chapter_metadata() -> List[Dict[str, Any]]:
    candidates = [
        DATABASE / "Doraemon Chapter Index.csv",
        DATABASE / "Doraemon Chapter Index.json",
        ROOT / "Doraemon Chapter Index.csv",
        ROOT / "Doraemon Chapter Index.json",
    ]
    for p in candidates:
        if p.exists():
            rows = load_table(p)
            out = []
            for i, row in enumerate(rows):
                title = row.get("title") or row.get("Title") or row.get("chapter") or row.get("Chapter") or ""
                volume = row.get("volume") or row.get("Volume") or row.get("vol") or row.get("Vol") or ""
                jp = row.get("japanese") or row.get("Japanese") or row.get("jp_title") or row.get("JP Title") or ""
                out.append(
                    {
                        "source_file": str(p),
                        "source_row_index": i,
                        "raw_row": row,
                        "title": title or None,
                        "jp_title": jp or None,
                        "volume": volume or None,
                        "title_normalized": normalize_title(title) if title else None,
                        "jp_title_normalized": normalize_title(jp) if jp else None,
                    }
                )
            return out
    return []


def load_manual_links() -> List[Dict[str, Any]]:
    data = read_json(MAPPINGS_JSON, {})
    links = data.get("links") if isinstance(data, dict) else None
    return links if isinstance(links, list) else []


def exact_match_candidates(anime: Dict[str, Any], manga_items: List[Dict[str, Any]]) -> List[Tuple[float, Dict[str, Any], str]]:
    candidates: List[Tuple[float, Dict[str, Any], str]] = []
    anime_title = normalize_title(anime.get("title") or "")
    anime_jp = normalize_title(anime.get("japanese_title") or anime.get("jp_title") or "")
    anime_story = story_token(anime.get("japanese_story_number"))

    anime_variants = [normalize_title(v) for v in title_variants(anime) if normalize_title(v)]
    anime_variants = list(dict.fromkeys([v for v in anime_variants if v]))

    for m in manga_items:
        m_title = normalize_title(m.get("title") or "")
        m_jp = normalize_title(m.get("jp_title") or "")
        m_variants = [normalize_title(v) for v in title_variants(m) if normalize_title(v)]
        m_story = story_token(m.get("japanese_story_number"))

        # Strong exact story match first.
        if anime_story and m_story and anime_story == m_story:
            candidates.append((1.0, m, "story_number"))
            continue

        # Exact normalized title/alias matches.
        if anime_title and (anime_title == m_title or anime_title == m_jp or anime_title in m_variants):
            candidates.append((0.98, m, "exact_title"))
            continue
        if anime_jp and (anime_jp == m_title or anime_jp == m_jp or anime_jp in m_variants):
            candidates.append((0.98, m, "exact_jp_title"))
            continue

        # Fuzzy fallback.
        best = 0.0
        method = "fuzzy_title"
        for av in ([anime_title, anime_jp] + anime_variants):
            if not av:
                continue
            for mv in ([m_title, m_jp] + m_variants):
                if not mv:
                    continue
                score = sim(av, mv)
                if score > best:
                    best = score
                    method = "fuzzy_title"
        if best >= 0.72:
            candidates.append((best, m, method))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[:8]


def build_search_index(episodes: List[Dict[str, Any]], manga: List[Dict[str, Any]]) -> Dict[str, Any]:
    chapter_meta = load_chapter_metadata()
    manual_links = load_manual_links()

    manga_by_key = {}
    for m in manga:
        key = record_key("manga", m)
        manga_by_key[key] = m
        m["_key"] = key

    anime_by_key = {}
    for a in episodes:
        key = record_key("anime", a)
        anime_by_key[key] = a
        a["_key"] = key

    manual_map = {}
    for link in manual_links:
        ak = link.get("anime_key")
        mk = link.get("manga_key")
        if isinstance(ak, str) and isinstance(mk, str):
            manual_map.setdefault(ak, []).append(mk)

    items = []
    anime_lookup: Dict[str, List[str]] = {}
    manga_lookup: Dict[str, List[str]] = {}
    unmatched_anime = 0
    unmatched_manga = 0

    matched_manga_keys = set()

    for a_key, a in anime_by_key.items():
        candidates = exact_match_candidates(a, manga)
        matches = []
        if a_key in manual_map:
            for mk in manual_map[a_key]:
                if mk in manga_by_key:
                    matched_manga_keys.add(mk)
                    matches.append(
                        {
                            "method": "manual",
                            "score": 1.0,
                            "manga_key": mk,
                            "manga": manga_by_key[mk],
                        }
                    )

        # Add automatic candidates, avoiding duplicates.
        seen_mk = {m["manga_key"] for m in matches if "manga_key" in m}
        for score, m, method in candidates:
            mk = m["_key"]
            if mk in seen_mk:
                continue
            seen_mk.add(mk)
            matched_manga_keys.add(mk)
            matches.append(
                {
                    "method": method,
                    "score": round(float(score), 4),
                    "manga_key": mk,
                    "manga": m,
                }
            )

        if not matches:
            unmatched_anime += 1

        # Build reverse lookup keys.
        ak_lookup_keys = [
            a_key,
            f"anime_ep_{a.get('indian_episode_number')}" if a.get("indian_episode_number") else None,
            f"anime_jp_{a.get('japanese_story_number')}" if a.get("japanese_story_number") else None,
        ]
        for lk in [x for x in ak_lookup_keys if x]:
            anime_lookup.setdefault(lk, []).append(a_key)

        items.append(
            {
                "key": a_key,
                "anime": a,
                "manga_matches": matches,
                "chapter_metadata": chapter_meta,
            }
        )

    for m_key, m in manga_by_key.items():
        mk_lookup_keys = [
            m_key,
            f"manga_vol_{m.get('volume')}" if m.get("volume") else None,
            f"manga_ch_{m.get('chapter_no')}" if m.get("chapter_no") else None,
            f"manga_jp_{m.get('japanese_story_number')}" if m.get("japanese_story_number") else None,
        ]
        for lk in [x for x in mk_lookup_keys if x]:
            manga_lookup.setdefault(lk, []).append(m_key)
        if m_key not in matched_manga_keys:
            unmatched_manga += 1

    search_index = {
        "generated_at": now_iso(),
        "source_files": {
            "episodes": str(EPISODES_JSON),
            "manga": str(MANGA_JSON),
            "chapter_metadata": "auto-discovered from Chapter Index file if present",
        },
        "counts": {
            "anime_items": len(episodes),
            "manga_items": len(manga),
            "matched_manga_items": len(matched_manga_keys),
            "unmatched_anime_items": unmatched_anime,
            "unmatched_manga_items": unmatched_manga,
        },
        "items": items,
        "anime_lookup": anime_lookup,
        "manga_lookup": manga_lookup,
    }
    return search_index


def main() -> None:
    ensure_dirs()
    episodes_obj = read_json(EPISODES_JSON, {})
    manga_obj = read_json(MANGA_JSON, {})

    episodes = episodes_obj.get("items", []) if isinstance(episodes_obj, dict) else []
    manga = manga_obj.get("items", []) if isinstance(manga_obj, dict) else []

    log.info("Merging %d anime records and %d manga records", len(episodes), len(manga))

    search_index = build_search_index(episodes, manga)

    metadata = {
        "generated_at": now_iso(),
        "sources": {
            "anime_source": episodes_obj.get("source_url") if isinstance(episodes_obj, dict) else None,
            "manga_source": manga_obj.get("source_url") if isinstance(manga_obj, dict) else None,
        },
        "counts": search_index["counts"],
        "files": {
            "episodes": str(EPISODES_JSON),
            "manga": str(MANGA_JSON),
            "search_index": str(SEARCH_INDEX_JSON),
            "summary": str(SUMMARY_JSON),
        },
    }

    summary = {
        "generated_at": now_iso(),
        "anime_count": len(episodes),
        "manga_count": len(manga),
        "matched_manga_items": search_index["counts"]["matched_manga_items"],
        "unmatched_anime_items": search_index["counts"]["unmatched_anime_items"],
        "unmatched_manga_items": search_index["counts"]["unmatched_manga_items"],
    }

    write_json(SEARCH_INDEX_JSON, search_index)
    write_json(METADATA_JSON, metadata)
    write_json(SUMMARY_JSON, summary)

    log.info("Wrote %s", SEARCH_INDEX_JSON)
    log.info("Wrote %s", METADATA_JSON)
    log.info("Wrote %s", SUMMARY_JSON)


if __name__ == "__main__":
    main()
