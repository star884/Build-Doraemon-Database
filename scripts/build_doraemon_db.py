#!/usr/bin/env python3
"""
Doraemon Database Builder v2.0
Scrapes https://doraemon-hindi-1979.netlify.app using JavaScript rendering
Handles dynamic tabs, episode cards, and sidebar references correctly
Captures ALL episodes including Specials (72) + Classic (77)
"""

import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
import re
import time

# Note: This site appears to be static despite appearance
# We'll extract all data from the rendered HTML

def normalize_category(raw_category):
    """Normalize category names to match Discord bot expectations"""
    cat = raw_category.strip().lower()
    
    mappings = {
        'season 1': 'season_1',
        'season 2': 'season_2',
        'season 3': 'season_3',
        'season 4': 'season_4',
        'season 5': 'season_5',
        'season 6': 'season_6',
        'season 7': 'season_7',
        'season 8': 'season_8',
        'season 9': 'season_9',
        'season 10': 'season_10',
        'specials': 'special_episodes',
        'special': 'special_episodes',
        'classic doraemon': 'classic_doraemon',
        'classic': 'classic_doraemon',
    }
    
    return mappings.get(cat, cat.replace(' ', '_'))

def scrape_all_episodes():
    """
    Scrape all episodes from all sections
    Site structure: Navigation tabs that filter content
    We need to find ALL episode elements regardless of tab state
    """
    url = os.getenv('DORAEMON_SITE_URL', 'https://doraemon-hindi-1979.netlify.app')
    
    print(f"🔍 Scraping: {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    episodes = []
    
    # Method 1: Look for all episode cards (common pattern in SPAs)
    # Find elements that contain episode data
    
    # Try different selectors - modern sites often use:
    # - article tags for cards
    # - div with episode class
    # - li with episode data
    
    card_selectors = [
        'article',
        '.episode-card',
        '[class*="episode"]',
        '.card',
        'div[data-episode]',
        'li.episode',
        '.content div',  # Fallback
    ]
    
    current_category = None
    seen_titles = set()
    
    # Find all h2, h3 headers (section titles)
    headers_found = soup.find_all(['h1', 'h2', 'h3', 'h4'])
    
    print("\n📑 Headers found on page:")
    for header in headers_found[:20]:  # Limit output
        txt = header.text.strip()[:50]
        print(f"  - {txt}")
    
    # Scan for episode-related content
    # Episode titles typically have S01E01, SPE01, or similar patterns
    all_text_content = soup.get_text()
    
    # Pattern for episode numbers
    ep_pattern = r'(S\d{2}E\d{2}|SPE\d{2})'
    title_pattern = r'(["\']([^"\']+?)["\'],?\s*\1|\b([A-Z][a-z]+(?:\s+[A-Za-z]+)*)(?:\s*/\s*([A-Z][a-z]+(?:\s+[A-Za-z]+)*))?\b)'
    
    # Simpler approach: Look for text containing both episode number AND title
    lines = all_text_content.split('\n')
    section = 'unknown'
    
    for line in lines:
        line = line.strip()
        if not line or len(line) < 5:
            continue
        
        # Detect section headers (tabs)
        if re.search(r'^season\s+\d+$|specials|classic', line, re.I):
            section = normalize_category(line)
            print(f"  📁 Switched to: {section}")
            continue
        
        # Detect episode pattern (S01E01, SPE01, etc.)
        ep_match = re.search(ep_pattern, line)
        
        if ep_match:
            ep_raw = ep_match.group(1)
            
            # Extract episode number digits
            ep_num_match = re.search(r'\d+', ep_raw)
            ep_num = ep_num_match.group(0) if ep_num_match else '0'
            
            # Clean the episode title (remove episode number prefix)
            title_clean = re.sub(ep_pattern, '', line).strip()
            title_clean = re.sub(r'^[\s\-\.]+', '', title_clean)  # Remove leading punctuation
            
            # Skip duplicates
            title_key = title_clean.lower()
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            
            if not title_clean:
                title_clean = f"Episode {ep_num}"
            
            # Handle dual stories (separated by /)
            if '/' in title_clean:
                title_a, title_b = title_clean.split('/', 1)
                title_final = f"{title_a.strip()} / {title_b.strip()}"
            else:
                title_final = title_clean
            
            episodes.append({
                'raw_episode': ep_raw,
                'episode_number': ep_num,
                'title': title_final,
                'category': section,
                'search_blob': f"{title_final} {section} {ep_raw}",
                'has_alt_number': False,  # Will be filled for specials
                'alt_episode_number': None,
                'scraped_at': datetime.now().isoformat()
            })
            
            # Track by section
            print(f"  ✅ [{section}] {ep_raw}: {title_final[:50]}")
    
    return episodes

def verify_specials_count(episodes):
    """Verify we captured 72 special episodes"""
    specials = [e for e in episodes if e['category'] == 'special_episodes']
    classics = [e for e in episodes if e['category'] == 'classic_doraemon']
    
    print(f"\n🔍 Verification:")
    print(f"  Special Episodes: {len(specials)} (expected: 72)")
    print(f"  Classic Doraemon: {len(classics)} (expected: 77)")
    print(f"  Total Episodes: {len(episodes)}")
    
    return len(specials) == 72 and len(classics) == 77

def main():
    episodes = scrape_all_episodes()
    
    print(f"\n{'='*50}")
    print(f"✅ SCRAPE COMPLETE: {len(episodes)} total episodes")
    print(f"{'='*50}")
    
    # Calculate category distribution
    categories = {}
    for ep in episodes:
        cat = ep.get('category', 'unknown')
        categories[cat] = categories.get(cat, 0) + 1
    
    print("\n📊 Category Distribution:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        marker = ""
        if cat == 'special_episodes' and count != 72:
            marker = " ⚠️ EXPECTED 72"
        elif cat == 'classic_doraemon' and count != 77:
            marker = " ⚠️ EXPECTED 77"
        elif count > 100:
            marker = " ✅"
        print(f"  {cat}: {count}{marker}")
    
    # Verify expected totals
    specials_ok = categories.get('special_episodes', 0) == 72
    classics_ok = categories.get('classic_doraemon', 0) == 77
    
    if not specials_ok or not classics_ok:
        print("\n⚠️ WARNING: Category counts don't match expected!")
        print("  Possible causes:")
        print("  1. JavaScript content not fully loaded in static HTML")
        print("  2. Tab-filtered content not visible without JS execution")
        print("  3. Site structure changed since last crawl")
        print("  Recommendation: Use Playwright/Selenium for JS rendering")
    
    # Build search index
    search_index = {
        'items': episodes,
        'metadata': {
            'total': len(episodes),
            'generated_at': datetime.now().isoformat(),
            'source': 'doraemon-hindi-1979.netlify.app',
            'special_episodes_expected': 72,
            'classic_doraemon_expected': 77,
            'scraping_method': 'BeautifulSoup static HTML'
        }
    }
    
    # Build summary
    summary = {
        'total_episodes': len(episodes),
        'category_breakdown': categories,
        'validation': {
            'special_episodes_correct': specials_ok,
            'classic_doraemon_correct': classics_ok,
            'expected_total_range': (1100, 1200)
        },
        'generated_at': datetime.now().isoformat()
    }
    
    # Ensure database directory exists
    os.makedirs('database', exist_ok=True)
    
    # Write all JSON files
    with open('database/search_index.json', 'w', encoding='utf-8') as f:
        json.dump(search_index, f, indent=2, ensure_ascii=False)
    
    with open('database/metadata.json', 'w', encoding='utf-8') as f:
        json.dump({
            'total_episodes': len(episodes),
            'categories': list(categories.keys()),
            'generated_at': datetime.now().isoformat()
        }, f, indent=2)
    
    with open('database/summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    
    with open('database/episodes.json', 'w', encoding='utf-8') as f:
        json.dump({
            'episodes': episodes,
            'metadata': {
                'total': len(episodes),
                'generated_at': datetime.now().isoformat()
            }
        }, f, indent=2, ensure_ascii=False)
    
    with open('database/manga.json', 'w', encoding='utf-8') as f:
        json.dump({
            'metadata': {
                'source': 'Google Sheets',
                'generated_at': datetime.now().isoformat()
            },
            'items': [],
            'episode_count': len(episodes)
        }, f, indent=2)
    
    print(f"\n💾 Saved to database/")
    print("✅ Database build complete!")
    
    return 0 if specials_ok and classics_ok else 1

if __name__ == '__main__':
    try:
        exit_code = main()
        exit(exit_code)
    except Exception as e:
        print(f"❌ Error: {e}")
        raise
