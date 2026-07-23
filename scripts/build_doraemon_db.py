#!/usr/bin/env python3
"""
Doraemon Database Builder with Playwright
Fully captures JavaScript-rendered content including filtered tabs
"""

from playwright.sync_api import sync_playwright
import json
import os
from datetime import datetime
import re

def scrape_with_playwright():
    """Scrape using JavaScript rendering"""
    url = os.getenv('DORAEMON_SITE_URL', 'https://doraemon-hindi-1979.netlify.app')
    
    print(f"🔍 Launching browser: {url}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print(f"🌐 Navigating to {url}")
        page.goto(url, wait_until='networkidle', timeout=60000)
        
        # Wait for content to load
        page.wait_for_timeout(3000)
        
        episodes = []
        
        # Click each tab to load all content
        tab_names = ['Season 1', 'Season 2', 'Season 3', 'Season 4', 'Season 5',
                     'Season 6', 'Season 7', 'Season 8', 'Season 9', 'Season 10',
                     'Specials', 'Classic Doraemon']
        
        for tab in tab_names:
            print(f"  🔄 Clicking tab: {tab}")
            try:
                # Try to click the tab
                page.click(f'a:has-text("{tab}"), button:has-text("{tab}")')
                page.wait_for_timeout(1000)  # Wait for content
                
                # Extract visible episodes
                content = page.content()
                
                # Parse with BeautifulSoup
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(content, 'html.parser')
                
                # Find episode cards/rows in current view
                category = tab.lower().replace(' ', '_')
                if category == 'specials':
                    category = 'special_episodes'
                elif category == 'classic_doraemon':
                    category = 'classic_doraemon'
                
                # Find episode entries
                for item in soup.find_all(['article', 'div', 'li'], class_=True):
                    text = item.get_text()
                    
                    # Look for episode pattern
                    ep_match = re.search(r'(S\d{2}E\d{2}|SPE\d{2})', text)
                    if ep_match:
                        ep_raw = ep_match.group(1)
                        ep_num = re.search(r'\d+', ep_raw).group(0)
                        
                        title = re.sub(r'(S\d{2}E\d{2}|SPE\d{2})\s*', '', text).strip()
                        title = title[:100] if title else f"Episode {ep_num}"
                        
                        if title not in [e['title'] for e in episodes]:
                            episodes.append({
                                'raw_episode': ep_raw,
                                'episode_number': ep_num,
                                'title': title,
                                'category': category,
                                'search_blob': f"{title} {category}",
                                'scraped_at': datetime.now().isoformat()
                            })
                
                print(f"    Found {len([e for e in episodes if e['category'] == category])} episodes in {category}")
                
            except Exception as e:
                print(f"    ⚠️ Failed to click {tab}: {e}")
                continue
        
        browser.close()
        return episodes

def main():
    episodes = scrape_with_playwright()
    print(f"\n✅ Scraped {len(episodes)} episodes")
    
    # ... (rest same as static scraper - save JSON files)
    
    categories = {}
    for ep in episodes:
        cat = ep.get('category', 'unknown')
        categories[cat] = categories.get(cat, 0) + 1
    
    print("\n📊 Category Distribution:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")
    
    os.makedirs('database', exist_ok=True)
    
    with open('database/search_index.json', 'w', encoding='utf-8') as f:
        json.dump({'items': episodes, 'metadata': {'total': len(episodes), 'generated_at': datetime.now().isoformat()}}, f, indent=2, ensure_ascii=False)
    
    # ... (save other JSON files same as before)
    
    print("✅ Database build complete!")

if __name__ == '__main__':
    main()
