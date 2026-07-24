import difflib
import discord
import json
import os
import re
from discord import app_commands, Embed
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
bot = commands.Bot(command_prefix='!', intents=discord.Intents.default())

# Load new Doraemon database
try:
    with open('database/search_index.json', encoding='utf-8') as f:
        DB = json.load(f)

    SEARCH_ITEMS = DB.get('items', [])

    EPISODES = []

    for item in SEARCH_ITEMS:
        anime = item.get("anime", {})

        if not anime:
            continue

        episode = {
            "title": anime.get("title", "Unknown"),
            "story_a": anime.get("title", "Unknown"),
            "story_b": None,

            "in_season_episode": anime.get(
                "indian_episode_number",
                "N/A"
            ),

            "jp_story_numbers": [],

            "category": (
                "special_episodes"
                if anime.get("special_episode")
                else "classic_doraemon"
                if not anime.get("season")
                else f"season_{anime.get('season')}"
            ),

            "anime_data": anime,
            "manga_matches": item.get("manga_matches", [])
        }

        jp = anime.get("japanese_story_number")

        if jp:
            episode["jp_story_numbers"] = [str(jp)]

        EPISODES.append(episode)


    print(f"✅ Loaded {len(EPISODES)} episodes from new database")
    print(
        f'   Episodes with JP refs: '
        f'{sum(1 for e in EPISODES if e.get("jp_story_numbers"))}'
    )

except FileNotFoundError:
    DB = {}
    SEARCH_ITEMS = []
    EPISODES = []
    print("❌ Database file not found")

# --- ADVANCED SEARCH COMMAND ---
@bot.tree.command(name='search', description='Advanced search by JP story #, IN episode, SPE, or CE')
@app_commands.describe(query='Search term (e.g., 150, s04e35, spe01, ce1, nobita)')
async def search_cmd(interaction, query: str):
    await interaction.response.defer()
    q = query.lower().strip()
    
    results = []
    search_type = None
    
    # Detection logic
    # JP Story Number (just digits or "jp:" prefix)
    if q.startswith('jp:') or (q.isdigit() and len(q) >= 1):
        search_type = 'jp'
        jp_num = q.replace('jp:', '')
        # Search through jp_story_numbers array for each episode
        for ep in EPISODES:
            jp_numbers = ep.get('jp_story_numbers', [])
            if jp_num in [str(n) for n in jp_numbers]:
                results.append(ep)
    
    # IN Season/Episode (S01E01 format)
    elif re.match(r'^s\d{2}e\d{2}$', q):
        search_type = 'in_episode'
        results = [e for e in EPISODES if e.get('in_season_episode', '').lower() == q]
    
    # SPE (Special Episode)
    elif q.startswith('spe'):
        search_type = 'special'
        spe_num = re.sub(r'[^0-9]', '', q.replace('spe', ''))
        results = [e for e in EPISODES if e.get('in_season_episode', '').upper().startswith('SPE') and spe_num in e.get('in_season_episode')]
    
    # CE (Classic Episode)
    elif q.startswith('ce') or q.startswith('classic'):
        search_type = 'classic'
        ce_num = re.sub(r'[^0-9]', '', q.replace('ce', '').replace('classic', ''))
        results = [e for e in EPISODES if e.get('in_season_episode', '').upper().startswith('CE') and ce_num in e.get('in_season_episode')]
    
    # Fallback: Title keyword search (search both story_a and story_b)
    if not results:
        search_type = 'title'
        results = []
        for ep in EPISODES:
            story_a = ep.get('story_a', '').lower()
            story_b = ep.get('story_b', '').lower() if ep.get('story_b') else ''
            if q in story_a or q in story_b:
                results.append(ep)
        # Limit to 5 results for title search
        results = results[:5]
    
    if not results:
        await interaction.followup.send(
            f'❌ No episodes found for "**{query}**"\n\n'
            '**Supported formats:**\n'
            '• JP Story #: `150` or `jp:150`\n'
            '• IN Episode: `s04e35`\n'
            '• Special: `spe01` or `spe1`\n'
            '• Classic: `ce1` or `classic1`\n'
            '• Title: `nobita` or story name'
        )
        return
    
    # Build response embed for first result
    first_result = results[0]
    in_ep = first_result.get('in_season_episode', 'N/A')
    jp_numbers = first_result.get('jp_story_numbers', [])
    jp_display = ' / '.join([str(n) for n in jp_numbers]) if jp_numbers else 'Not indexed'
    title = first_result.get('title', 'Unknown')
    story_a = first_result.get('story_a', 'N/A')
    story_b = first_result.get('story_b')
    category = first_result.get('category', 'unknown').replace('_', ' ').title()
    
    embed = Embed(title=f"🔍 Episode Found", color=0x6d4aff)
    embed.description = f"**Category:** {category}"
    
    # Add fields
    embed.add_field(name='🇮🇳 Indian Episode', value=in_ep, inline=True)
    embed.add_field(name='🇯🇵 Japanese Story #', value=jp_display, inline=True)
    
    embed.add_field(name='📖 Story A', value=story_a, inline=False)
    if story_b:
        embed.add_field(name='📖 Story B', value=story_b, inline=False)
    
    # Set footer with search type
    if search_type == 'jp':
        embed.set_footer(text=f'Searched by: JP Story #{query.replace("jp:", "")}')
    elif search_type == 'in_episode':
        embed.set_footer(text=f'Searched by: Indian Episode {query.upper()}')
    elif search_type == 'special':
        embed.set_footer(text=f'Searched by: Special Episode {query.upper()}')
    elif search_type == 'classic':
        embed.set_footer(text=f'Searched by: Classic Episode {query.upper()}')
    elif search_type == 'title':
        embed.set_footer(text=f'Searched by: Title "{query}"')
    
    # Show additional matches if multiple
    if len(results) > 1:
        additional = []
        for r in results[1:5]:
            ep_num = r.get('in_season_episode', 'N/A')
            ep_title = r.get('story_a', 'Unknown')[:40]
            additional.append(f"{ep_num}: {ep_title}")
        embed.add_field(name=f'➕ Additional Matches ({len(results)-1} more)',
                       value='\n'.join(additional), inline=False)
    
    await interaction.followup.send(embed=embed)

# --- JP NUMBER LOOKUP (Convenience Command) ---
@bot.tree.command(name='jp', description='Lookup by Japanese Story Number')
@app_commands.describe(jp_number='Japanese Story Number (e.g., 150)')
async def jp_cmd(interaction, jp_number: str):
    await interaction.response.defer()
    
    # Search through jp_story_numbers array
    results = []
    for ep in EPISODES:
        jp_numbers = ep.get('jp_story_numbers', [])
        if jp_number in [str(n) for n in jp_numbers]:
            results.append(ep)
    
    if not results:
        await interaction.followup.send(f'❌ No episode found for JP Story #{jp_number}')
        return
    
    first = results[0]
    jp_numbers = first.get('jp_story_numbers', [])
    jp_display = ' / '.join([str(n) for n in jp_numbers])
    story_a = first.get('story_a', 'Unknown')
    story_b = first.get('story_b')
    
    embed = Embed(title=f"🇯🇵 JP Story #{jp_number}", color=0x6d4aff)
    embed.add_field(name='🇮🇳 Indian Episode', value=first.get('in_season_episode', 'N/A'), inline=True)
    embed.add_field(name='Category', value=first.get('category', 'unknown').replace('_', ' ').title(), inline=True)
    
    embed.add_field(name='📖 Story A', value=story_a, inline=False)
    if story_b:
        embed.add_field(name='📖 Story B', value=story_b, inline=False)
    
    embed.add_field(name='All JP Stories in Episode', value=jp_display, inline=False)
    embed.set_footer(text=f'Total matches: {len(results)}')
    
    await interaction.followup.send(embed=embed)

# --- LIST ALL (Pagination) ---
@bot.tree.command(name='list', description='List episodes with pagination')
@app_commands.describe(page='Page number (1-999)', season='Filter by season (1-10) or "special" or "classic"')
async def list_cmd(interaction, page: int = 1, season: str = None):
    await interaction.response.defer()
    
    # Filter by season if specified
    filtered_episodes = EPISODES
    if season:
        season_lower = season.lower()
        if season_lower == 'special':
            filtered_episodes = [e for e in EPISODES if e.get('category') == 'special_episodes']
        elif season_lower == 'classic':
            filtered_episodes = [e for e in EPISODES if e.get('category') == 'classic_doraemon']
        elif season_lower.isdigit():
            season_cat = f'season_{season_lower}'
            filtered_episodes = [e for e in EPISODES if e.get('category') == season_cat]
    
    PAGE_SIZE = 10
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    
    if start >= len(filtered_episodes):
        await interaction.followup.send(f'❌ Page {page} does not exist.')
        return
    
    chunk = filtered_episodes[start:end]
    season_display = season if season else 'All'
    embed = Embed(title=f'Doraemon Episodes - Page {page} ({season_display})', color=0x6d4aff)
    embed.description = f'Total episodes: **{len(filtered_episodes)}** | Showing {start + 1}-{min(end, len(filtered_episodes))}'
    
    for r in chunk:
        in_ep = r.get('in_season_episode', 'N/A')
        jp_numbers = r.get('jp_story_numbers', [])
        jp_st = ' / '.join([str(n) for n in jp_numbers]) if jp_numbers else '-'
        story_a = r.get('story_a', 'Unknown')[:40]
        story_b = r.get('story_b', '')
        
        title_display = story_a
        if story_b:
            title_display += f' / {story_b[:40]}'
        
        embed.add_field(name=f'{in_ep} | JP: {jp_st}', value=title_display, inline=False)
    
    total_pages = (len(filtered_episodes) // PAGE_SIZE) + 1
    embed.set_footer(text=f'Page {page} of {total_pages}')
    await interaction.followup.send(embed=embed)

# --- STATS ---
@bot.tree.command(name='stats', description='Show database statistics')
async def stats_cmd(interaction):
    await interaction.response.defer()
    
    counts = {}
    with_jp_ref = 0
    dual_stories = 0
    
    for e in EPISODES:
        cat = e.get('category', 'unknown')
        counts[cat] = counts.get(cat, 0) + 1
        jp_nums = e.get('jp_story_numbers', [])
        if jp_nums:
            with_jp_ref += 1
            if len(jp_nums) > 1:
                dual_stories += 1
    
    embed = Embed(title='Database Statistics', color=0x6d4aff)
    embed.description = f'**Total Episodes:** {len(EPISODES)}\n**With JP References:** {with_jp_ref}\n**Dual Stories (A+B):** {dual_stories}\n\n**Breakdown by Category:**'
    
    for cat, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        embed.add_field(name=cat.replace('_', ' ').title(), value=f'**{cnt}** episodes', inline=True)
    
    embed.set_footer(text=f'Database: {DB.get("metadata", {}).get("generated_at", "unknown")}')
    await interaction.followup.send(embed=embed)

# --- HELP ---
@bot.tree.command(name='help', description='Show available commands')
async def help_cmd(interaction):
    embed = Embed(title='🤖 Doraemon Search Bot Help', color=0x6d4aff)
    embed.description = '''
**Available Commands:**

• `/search <query>` - Search by JP #, IN episode, SPE, CE, or story title
• `/jp <number>` - Lookup by Japanese Story Number directly
• `/list [page] [season]` - Browse episodes with pagination
• `/stats` - Show database statistics
• `/help` - Show this message

**Search Examples:**
• `/search 150` - Find Japanese Story #150 and its Indian episode
• `/search s04e35` - Find Indian Episode S04E35
• `/search spe01` - Find Special Episode 01
• `/search ce1` - Find Classic Episode 1
• `/search nobita` - Search by story title
• `/jp 1694` - Lookup JP Story #1694

**List Examples:**
• `/list` - Show page 1 of all episodes
• `/list 2` - Show page 2 of all episodes
• `/list 1 season 1` - Show all Season 1 episodes
• `/list season special` - Show all Special episodes
• `/list season classic` - Show all Classic episodes
'''
    embed.set_footer(text='🇯🇵 ↔ 🇮🇳 Bidirectional JP ↔ IN Cross-Reference Search')
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user}')
    synced = await bot.tree.sync()
    print(f'✅ Synced {len(synced)} GLOBAL commands')
    if bot.guilds:
        print(f'Bot is in {len(bot.guilds)} guild(s)')

bot.run(TOKEN)
