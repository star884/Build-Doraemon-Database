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
        all_elements = page.content()
        soup = BeautifulSoup(all_elements, 'html.parser')
        
        # Get all text and parse with improved patterns
        all_text = soup.get_text(separator='\n')
        lines = all_text.split('\n')
        
        current_section = None
        seen_episodes = set()
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            # Detect sections
            if re.match(r'^season\s+\d+$|^specials$|^classic', line, re.I):
                lower_line = line.lower()
                if 'season' in lower_line:
                    num = re.search(r'\d+', lower_line).group(0)
                    current_section = f'season_{num}'
                elif 'special' in lower_line:
                    current_section = 'special_episodes'
                elif 'classic' in lower_line:
                    current_section = 'classic_doraemon'
                print(f"\n📺 Processing: {current_section}")
                i += 1
                continue
            
            # Look for JP story numbers (format: "1694 / 790" or just "765")
            jp_match = re.match(r'^(\d{2,4}(?:\s*/\s*\d{2,4})*)$', line)
            
            if jp_match:
                jp_raw = jp_match.group(1).strip()
                
                # Get the next line which should be the IN episode (S01E01, SPE01, CE01 format)
                in_ep_line = None
                title_line = None
                
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    # Check if next line is an episode number
                    if re.match(r'^S\d{1,2}E\d{2}$|^SPE\d{2}$|^CE\d{2}$', next_line, re.I):
                        in_ep_line = next_line.upper()
                        
                        # Get the title from the line after that
                        if i + 2 < len(lines):
                            title_line = lines[i + 2].strip()
                
                # If we found valid data, create episode entry
                if in_ep_line and title_line and in_ep_line not in seen_episodes:
                    seen_episodes.add(in_ep_line)
                    
                    # Infer section from episode number
                    section = current_section or 'unknown'
                    if 'SPE' in in_ep_line:
                        section = 'special_episodes'
                    elif 'CE' in in_ep_line:
                        section = 'classic_doraemon'
                    
                    # Parse JP story numbers - extract all numbers
                    jp_numbers = re.findall(r'\d+', jp_raw)
                    jp_primary = jp_numbers[0] if jp_numbers else None
                    
                    # Parse story titles (separated by "/")
                    story_parts = [s.strip() for s in title_line.split('/')]
                    story_a = story_parts[0] if len(story_parts) > 0 else title_line
                    story_b = story_parts[1] if len(story_parts) > 1 else None
                    
                    # Build search blob with all JP numbers and both story titles
                    search_terms = [story_a]
                    if story_b:
                        search_terms.append(story_b)
                    search_terms.extend(jp_numbers)
                    search_blob = ' '.join(str(x) for x in search_terms) + f' {section} {in_ep_line} {jp_raw}'
                    
                    episode_entry = {
                        'raw_episode': in_ep_line,
                        'in_season_episode': in_ep_line,
                        'jp_story_numbers': jp_numbers,  # All JP story numbers as array
                        'jp_story_primary': jp_primary,  # First JP story number
                        'jp_story_all': jp_raw,  # All JP numbers as string (e.g., "1694 / 790")
                        'episode_number': re.search(r'\d+', in_ep_line).group(0),
                        'title': title_line[:150],
                        'story_a': story_a,
                        'story_b': story_b,
                        'category': section,
                        'search_blob': search_blob,
                        'has_jp_reference': bool(jp_numbers),
                        'scraped_at': datetime.now().isoformat()
                    }
                    
                    episodes.append(episode_entry)
                    
                    display = f"JP {jp_raw} → {in_ep_line}: {story_a[:40]}"
                    if story_b:
                        display += f" / {story_b[:40]}"
                    print(f"  ✓ {display}")
                    
                    i += 3
                    continue
            
            i += 1
        
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
