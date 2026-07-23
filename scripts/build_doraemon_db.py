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
        
        # Get page content
        html_content = page.content()
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find all tables on the page (one per season/section)
        tables = soup.find_all('table')
        
        section_counter = 0
        for table in tables:
            section_counter += 1
            
            # Determine section from context (Season 1, Season 2, etc.)
            # Look for heading or section identifier near the table
            heading = None
            for prev in table.find_all_previous(['h1', 'h2', 'h3']):
                heading = prev.get_text(strip=True).upper()
                break
            
            section = 'unknown'
            if heading:
                if 'SEASON' in heading:
                    season_num = re.search(r'\d+', heading)
                    if season_num:
                        section = f'season_{season_num.group(0)}'
                elif 'SPECIAL' in heading:
                    section = 'special_episodes'
                elif 'CLASSIC' in heading:
                    section = 'classic_doraemon'
            
            print(f"\n📺 Processing Table {section_counter}: {section}")
            
            # Get table rows (skip header)
            rows = table.find_all('tr')[1:]  # Skip header row
            
            for row in rows:
                cells = row.find_all('td')
                
                if len(cells) < 3:
                    continue
                
                jp_raw = cells[0].get_text(strip=True)
                in_ep = cells[1].get_text(strip=True).upper()
                title = cells[2].get_text(strip=True)
                
                # Skip empty rows
                if not jp_raw or not in_ep or not title:
                    continue
                
                # Parse JP story numbers (e.g., "1694 / 790" or "765")
                jp_numbers = re.findall(r'\d+', jp_raw)
                jp_primary = jp_numbers[0] if jp_numbers else None
                
                # Parse story titles (separated by "/")
                story_parts = [s.strip() for s in title.split('/')]
                story_a = story_parts[0] if len(story_parts) > 0 else title
                story_b = story_parts[1] if len(story_parts) > 1 else None
                
                # Update section based on episode number
                if 'SPE' in in_ep:
                    section = 'special_episodes'
                elif 'CE' in in_ep:
                    section = 'classic_doraemon'
                
                # Build search blob with all JP numbers and both story titles
                search_terms = [story_a]
                if story_b:
                    search_terms.append(story_b)
                search_terms.extend(jp_numbers)
                search_blob = ' '.join(str(x) for x in search_terms) + f' {section} {in_ep} {jp_raw}'
                
                episode_entry = {
                    'raw_episode': in_ep,
                    'in_season_episode': in_ep,
                    'jp_story_numbers': jp_numbers,  # All JP story numbers as array
                    'jp_story_primary': jp_primary,  # First JP story number
                    'jp_story_all': jp_raw,  # All JP numbers as string (e.g., "1694 / 790")
                    'episode_number': re.search(r'\d+', in_ep).group(0) if re.search(r'\d+', in_ep) else None,
                    'title': title[:150],
                    'story_a': story_a,
                    'story_b': story_b,
                    'category': section,
                    'search_blob': search_blob,
                    'has_jp_reference': bool(jp_numbers),
                    'scraped_at': datetime.now().isoformat()
                }
                
                episodes.append(episode_entry)
                
                display = f"JP {jp_raw} → {in_ep}: {story_a[:40]}"
                if story_b:
                    display += f" / {story_b[:40]}"
                print(f"  ✓ {display}")
        
        browser.close()
        return episodes

def main():
    episodes = scrape_with_playwright()
    
    print(f"\n{'='*50}")
    print(f"✅ SCRAPE COMPLETE: {len(episodes)} episodes")
    
    categories = {}
    jp_count = 0
    dual_story_count = 0
    
    for ep in episodes:
        cat = ep.get('category', 'unknown')
        categories[cat] = categories.get(cat, 0) + 1
        if ep.get('jp_story_numbers'):
            jp_count += 1
            if len(ep.get('jp_story_numbers', [])) > 1:
                dual_story_count += 1
    
    print("\n📊 Category Distribution:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")
    
    print(f"\n🇯🇵 Episodes with Japanese Story Numbers: {jp_count}")
    print(f"📖 Episodes with Dual Stories (Story A + B): {dual_story_count}")
    
    os.makedirs('database', exist_ok=True)
    
    search_index = {
        'items': episodes,
        'metadata': {
            'total': len(episodes),
            'generated_at': datetime.now().isoformat(),
            'source': 'doraemon-hindi-1979.netlify.app',
            'jp_indexed': jp_count,
            'dual_stories': dual_story_count,
            'note': 'Each Indian episode contains Story A and Story B (original Japanese stories). Search by either JP number to find the episode.'
        }
    }
    
    with open('database/search_index.json', 'w', encoding='utf-8') as f:
        json.dump(search_index, f, indent=2, ensure_ascii=False)
    
    print("✅ Database build complete!")

if __name__ == '__main__':
    main()
