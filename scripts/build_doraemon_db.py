#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json, os, re
from datetime import datetime

def scrape_with_playwright():
    url = os.getenv('DORAEMON_SITE_URL', 'https://doraemon-hindi-1979.netlify.app')
    
    print(f"🔍 Launching browser: {url}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until='networkidle', timeout=90000)
        
        import time
        time.sleep(5)  # Wait for all JS to load
        
        episodes = []
        section_map = {}
        
        # Find all tab elements and collect their positions
        all_elements = page.content()
        soup = BeautifulSoup(all_elements, 'html.parser')
        
        # Get all text and parse with improved patterns
        all_text = soup.get_text(separator='\n')
        lines = all_text.split('\n')
        
        current_section = None
        seen_titles = set()
        seen_episodes = set()
        
        for line in lines:
            line = line.strip()
            if not line or len(line) < 3:
                continue
            
            # Detect sections
            if re.match(r'^season\s+\d+$|specials|classic', line, re.I):
                lower_line = line.lower()
                if 'season' in lower_line:
                    num = re.search(r'\d+', lower_line).group(0)
                    current_section = f'season_{num}'
                elif 'special' in lower_line:
                    current_section = 'special_episodes'
                elif 'classic' in lower_line:
                    current_section = 'classic_doraemon'
                continue
            
            # Match ANY episode pattern aggressively
            ep_match = re.search(r'(S\d{1,2}E\d{2}|SPE\d{2}|CE\d{2})', line, re.I)
            
            if ep_match:
                ep_raw = ep_match.group(1)
                ep_upper = ep_raw.upper()
                
                if ep_upper in seen_episodes:
                    continue
                seen_episodes.add(ep_upper)
                
                title = re.sub(r'S\d{1,2}E\d{2}|SPE\d{2}|CE\d{2}\s*', '', line, flags=re.I).strip()[:100]
                title = title if title else f"Episode {ep_raw}"
                
                if title.lower()[:60] in seen_titles:
                    continue
                seen_titles.add(title.lower()[:60])
                
                # Infer section from episode number
                if 'SPE' in ep_upper:
                    current_section = 'special_episodes'
                elif 'CE' in ep_upper:
                    current_section = 'classic_doraemon'
                elif not current_section:
                    current_section = 'unknown'
                
                jp_match = re.search(r'(JP|Japan|Story)[#:\s]*(\d+)', line, re.I)
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
        
        browser.close()
        return episodes

def main():
    episodes = scrape_with_playwright()
    
    print(f"\n{'='*50}")
    print(f"✅ SCRAPE COMPLETE: {len(episodes)} episodes")
    
    categories = {}
    for ep in episodes:
        cat = ep.get('category', 'unknown')
        categories[cat] = categories.get(cat, 0) + 1
    
    print("\n📊 Category Distribution:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")
    
    os.makedirs('database', exist_ok=True)
    
    search_index = {
        'items': episodes,
        'metadata': {'total': len(episodes), 'generated_at': datetime.now().isoformat(), 'source': 'doraemon-hindi-1979.netlify.app'}
    }
    
    with open('database/search_index.json', 'w', encoding='utf-8') as f:
        json.dump(search_index, f, indent=2, ensure_ascii=False)
    
    # Save other files similarly...
    print("✅ Database build complete!")

if __name__ == '__main__':
    main()
