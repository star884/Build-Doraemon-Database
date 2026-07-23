#!/usr/bin/env python3
"""
Doraemon Database Builder v3.0 with JP Story Cross-Reference
Captures Japanese Story Numbers from sidebar for bidirectional search
"""

from playwright.sync_api import sync_playwright
import json
import os
from datetime import datetime
import re
import time

def normalize_category(raw_category):
    """Normalize category names to match Discord bot expectations"""
    cat = raw_category.strip().lower()
    
    mappings = {
        'season 1': 'season_1', 'season 2': 'season_2',
        'season 3': 'season_3', 'season 4': 'season_4',
        'season 5': 'season_5', 'season 6': 'season_6',
        'season 7': 'season_7', 'season 8': 'season_8',
        'season 9': 'season_9', 'season 10': 'season_10',
        'specials': 'special_episodes', 'special': 'special_episodes',
        'classic doraemon': 'classic_doraemon', 'classic': 'classic_doraemon',
    }
    
    return mappings.get(cat, cat.replace(' ', '_'))

def scrape_with_playwright():
    """Scrape using JavaScript rendering with JP story number extraction"""
    url = os.getenv('DORAEMON_SITE_URL', 'https://doraemon-hindi-1979.netlify.app')
    
    print(f"🔍 Launching browser: {url}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print(f"🌐 Navigating to {url}")
        page.goto(url, wait_until='networkidle', timeout=60000)
        page.wait_for_timeout(3000)
        
        episodes = []
        
        tab_names = ['Season 1', 'Season 2', 'Season 3', 'Season 4', 'Season 5',
                     'Season 6', 'Season 7', 'Season 8', 'Season 9', 'Season 10',
                     'Specials', 'Classic Doraemon']
        
        for tab_idx, tab in enumerate(tab_names):
            print(f"  🔄 Clicking tab ({tab_idx+1}/{len(tab_names)}): {tab}")
            
            try:
                # Try to click the tab
                page.click(f'a:has-text("{tab}"), button:has-text("{tab}")', timeout=5000)
                page.wait_for_timeout(1500)  # Wait for content
                
                category = normalize_category(tab)
                
                # Get all visible episode cards
                # Adjust selector based on site structure
                cards = page.query_selector_all('.episode-card, .card, article, [class*="episode"]')
                
                if not cards:
                    # Try alternate selector (table rows)
                    cards = page.query_selector_all('tr')
                
                for idx, card in enumerate(cards[:150]):  # Limit per tab
                    try:
                        text = card.text_content()
                        if not text or len(text) < 10:
                            continue
                        
                        # Extract IN episode number
                        in_match = re.search(r'(S\d{2}E\d{2}|SPE\d{2}|CE\d{2})', text)
                        
                        if not in_match:
                            # Try S01E01 pattern
                            in_match = re.search(r'([S]?(\d{2}[A-Z])?(\d{2}))', text)
                        
                        if in_match:
                            ep_raw = in_match.group(1)
                            
                            # Extract title (usually after episode number)
                            title = re.sub(r'(S\d{2}E\d{2}|SPE\d{2}|CE\d{2})\s*', '', text).strip()
                            title = title[:100] if title else f"Episode {ep_raw}"
                            
                            # Extract JP story number from sidebar/text
                            jp_match = re.search(r'(JP|Japan)[#:.\s]*(\d+)', text, re.I)
                            jp_story = jp_match.group(2) if jp_match else None
                            
                            # If no JP number in card, check for sidebar reference
                            jp_alt_match = re.search(r'Story\s*(\d+)|#\s*(\d+)', text)
                            if not jp_story and jp_alt_match:
                                jp_story = jp_alt_match.group(1) or jp_alt_match.group(2)
                            
                            episodes.append({
                                'raw_episode': ep_raw,
                                'in_season_episode': ep_raw,  # Indian format
                                'jp_story_number': jp_story,  # Japanese format
                                'episode_number': re.search(r'\d+', ep_raw).group(0) if ep_match else '0',
                                'title': title,
                                'category': category,
                                'search_blob': f"{title} {category} {ep_raw} {jp_story}",
                                'has_jp_reference': bool(jp_story),
                                'scraped_at': datetime.now().isoformat()
                            })
                            
                            # Progress indicator
                            if idx % 20 == 0:
                                print(f"    Found {len([e for e in episodes if e['category'] == category])} in {category}")
                    
                    except Exception as e:
                        continue
                
            except Exception as e:
                print(f"    ⚠️ Failed to click {tab}: {e}")
                continue
        
        browser.close()
        return episodes

def main():
    episodes = scrape_with_playwright()
    print(f"\n{'='*50}")
    print(f"✅ SCRAPE COMPLETE: {len(episodes)} total episodes")
    print(f"{'='*50}")
    
    # Calculate category distribution
    categories = {}
    has_jp_ref = 0
    for ep in episodes:
        cat = ep.get('category', 'unknown')
        categories[cat] = categories.get(cat, 0) + 1
        if ep.get('has_jp_reference'):
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
    
    # Save all JSON files (same as before...)
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
    
    # ... save other JSON files same as before
    with open('database/episodes.json', 'w', encoding='utf-8') as f:
        json.dump({'episodes': episodes, 'metadata': {'total': len(episodes), 'generated_at': datetime.now().isoformat()}}, f, indent=2, ensure_ascii=False)
    
    print("✅ Database build complete!")

if __name__ == '__main__':
    main()
