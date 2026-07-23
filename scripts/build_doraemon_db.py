#!/usr/bin/env python3
"""
Doraemon Database Builder v4.0
Robust scraper with flexible selectors and fallback parsing
"""

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
import re
import time

def scrape_with_playwright():
    """Scrape using JavaScript rendering with multiple fallback strategies"""
    url = os.getenv('DORAEMON_SITE_URL', 'https://doraemon-hindi-1979.netlify.app')
    
    print(f"🔍 Launching browser: {url}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print(f"🌐 Navigating to {url}")
        page.goto(url, wait_until='networkidle', timeout=90000)
        time.sleep(5)  # Extended wait for all JS
        
        episodes = []
        
        # Strategy 1: Get full page HTML and parse with BeautifulSoup
        print("  📄 Parsing full page HTML...")
        html = page.content()
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find ALL text containing episode patterns
        all_text = soup.get_text(separator='\n')
        lines = all_text.split('\n')
        
        current_section = None
        seen_titles = set()
        
        for line in lines:
            line = line.strip()
            if not line or len(line) < 3:
                continue
            
            # Detect section headers
            if re.match(r'^season\s+\d+$|specials|classic', line, re.I):
                section_lower = line.lower()
                if 'season' in section_lower:
                    num = re.search(r'\d+', section_lower).group(0)
                    current_section = f'season_{num}'
                elif 'special' in section_lower:
                    current_section = 'special_episodes'
                elif 'classic' in section_lower:
                    current_section = 'classic_doraemon'
                print(f"  📁 Section: {current_section}")
                continue
            
            # Detect episode pattern (S01E01, SPE01, CE01)
            ep_match = re.search(r'(S\d{2}E\d{2}|SPE\d{2}|CE\d{2})', line)
            
            if ep_match:
                ep_raw = ep_match.group(1)
                
                # Extract title (everything after episode number)
                title = re.sub(r'S\d{2}E\d{2}|SPE\d{2}|CE\d{2}\s*', '', line).strip()
                title = title[:100] if title else f"Episode {ep_raw}"
                
                # Avoid duplicates
                title_key = title.lower()[:50]
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)
                
                # Extract JP story number from surrounding text
                jp_match = re.search(r'(JP|Japan|Story)[#:\s]*\s*(\d+)', line, re.I)
                jp_story = jp_match.group(2) if jp_match else None
                
                episodes.append({
                    'raw_episode': ep_raw,
                    'in_season_episode': ep_raw,
                    'jp_story_number': jp_story,
                    'episode_number': re.search(r'\d+', ep_raw).group(0),
                    'title': title,
                    'category': current_section or 'unknown',
                    'search_blob': f"{title} {current_section or ''} {ep_raw} {jp_story or ''}",
                    'has_jp_reference': bool(jp_story),
                    'scraped_at': datetime.now().isoformat()
                })
        
        # Strategy 2: If we got too few episodes, try element-by-element
        if len(episodes) < 100:
            print("  ⚠️ Low episode count, trying element extraction...")
            
            # Find all divs/articles with potential episode data
            potential_cards = soup.find_all(['div', 'article', 'li', 'span'])
            
            for card in potential_cards:
                text = card.get_text(strip=True)
                if not text:
                    continue
                
                # Look for episode pattern
                ep_match = re.search(r'(S\d{2}E\d{2}|SPE\d{2}|CE\d{2})', text)
                
                if ep_match:
                    ep_raw = ep_match.group(1)
                    title = re.sub(r'S\d{2}E\d{2}|SPE\d{2}|CE\d{2}\s*', '', text).strip()
                    title = title[:100] if title else f"Episode {ep_raw}"
                    
                    title_key = title.lower()[:50]
                    if title_key in seen_titles:
                        continue
                    seen_titles.add(title_key)
                    
                    current_sec = 'unknown'
                    # Try to infer section from nearby context
                    parent = card.find_parent(['div', 'section', 'article'])
                    if parent:
                        parent_text = parent.get_text().lower()
                        if 'season' in parent_text:
                            num = re.search(r'season\s+(\d+)', parent_text)
                            if num:
                                current_sec = f'season_{num.group(1)}'
                        elif 'special' in parent_text:
                            current_sec = 'special_episodes'
                        elif 'classic' in parent_text:
                            current_sec = 'classic_doraemon'
                    
                    episodes.append({
                        'raw_episode': ep_raw,
                        'in_season_episode': ep_raw,
                        'jp_story_number': None,  # Try harder in next pass
                        'episode_number': re.search(r'\d+', ep_raw).group(0),
                        'title': title,
                        'category': current_sec,
                        'search_blob': f"{title} {current_sec} {ep_raw}",
                        'has_jp_reference': False,
                        'scraped_at': datetime.now().isoformat()
                    })
        
        browser.close()
        return episodes

def main():
    episodes = scrape_with_playwright()
    
    print(f"\n{'='*50}")
    print(f"✅ SCRAPE COMPLETE: {len(episodes)} total episodes")
    print(f"{'='*50}")
    
    categories = {}
    has_jp_ref = 0
    for ep in episodes:
        cat = ep.get('category', 'unknown')
        categories[cat] = categories.get(cat, 0) + 1
        if ep.get('jp_story_number'):
            has_jp_ref += 1
    
    print("\n📊 Category Distribution:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        marker = ""
        if cat == 'special_episodes' and count != 72:
            marker = " ⚠️ EXPECTED 72"
        elif cat == 'classic_doraemon' and count != 77:
            marker = " ⚠️ EXPECTED 77"
        print(f"  {cat}: {count}{marker}")
    
    print(f"\n🔗 Episodes with JP Story Reference: {has_jp_ref}/{len(episodes)}")
    
    # Save files
    os.makedirs('database', exist_ok=True)
    
    search_index = {
        'items': episodes,
        'metadata': {
            'total': len(episodes),
            'generated_at': datetime.now().isoformat(),
            'source': 'doraemon-hindi-1979.netlify.app',
            'jp_references_available': has_jp_ref
        }
    }
    
    with open('database/search_index.json', 'w', encoding='utf-8') as f:
        json.dump(search_index, f, indent=2, ensure_ascii=False)
    
    with open('database/episodes.json', 'w', encoding='utf-8') as f:
        json.dump({'episodes': episodes, 'metadata': {'total': len(episodes), 'generated_at': datetime.now().isoformat()}}, f, indent=2, ensure_ascii=False)
    
    with open('database/metadata.json', 'w', encoding='utf-8') as f:
        json.dump({'total_episodes': len(episodes), 'categories': list(categories.keys()), 'generated_at': datetime.now().isoformat()}, f, indent=2)
    
    with open('database/summary.json', 'w', encoding='utf-8') as f:
        json.dump({'total_episodes': len(episodes), 'category_breakdown': categories, 'generated_at': datetime.now().isoformat()}, f, indent=2)
    
    with open('database/manga.json', 'w', encoding='utf-8') as f:
        json.dump({'metadata': {'source': 'Google Sheets', 'generated_at': datetime.now().isoformat()}, 'items': [], 'episode_count': len(episodes)}, f, indent=2)
    
    print("\n💾 Saved to database/")
    print("✅ Database build complete!")
    
    if categories.get('special_episodes', 0) != 72 or categories.get('classic_doraemon', 0) != 77:
        print("\n⚠️ WARNING: Special/Classic counts don't match expected!")
        print("  This may indicate the site structure differs from expectations.")
        print("  Suggestion: Inspect the raw HTML to identify correct selectors.")

if __name__ == '__main__':
    main()
