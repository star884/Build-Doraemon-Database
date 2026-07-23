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

# Load database with JP references
try:
    with open('database/search_index.json') as f:
        DB = json.load(f)
    EPISODES = DB.get('items', [])
    print(f'✅ Loaded {len(EPISODES)} episodes from database')
    print(f'   Episodes with JP refs: {sum(1 for e in EPISODES if e.get("jp_story_number"))}')
except FileNotFoundError:
    EPISODES = []
    print('❌ Database file not found')

# --- ADVANCED SEARCH COMMAND ---
@bot.tree.command(name='search', description='Advanced search by JP story #, IN episode, SPE, or CE')
@app_commands.describe(query='Search term (e.g., 150, s01e01, spe01, ce1)')
async def search_cmd(interaction, query: str):
    await interaction.response.defer()
    q = query.lower().strip()
    
    results = []
    
    # Detection logic
    is_jp_search = False
    is_in_search = False
    is_spe_search = False
    is_ce_search = False
    
    # JP Story Number (just digits or "jp:" prefix)
    if q.startswith('jp:') or (q.isdigit() and len(q) >= 2 and len(q) <= 3):
        is_jp_search = True
        jp_num = q.replace('jp:', '')
        results = [e for e in EPISODES if e.get('jp_story_number') == jp_num]
    
    # IN Season/Episode (S01E01 format)
    elif re.match(r'^s\d{2}e\d{2}$', q):
        is_in_search = True
        results = [e for e in EPISODES if e.get('in_season_episode', '').lower() == q]
    
    # SPE (Special Episode)
    elif q.startswith('spe'):
        is_spe_search = True
        spe_num = re.sub(r'[^0-9]', '', q.replace('spe', ''))
        results = [e for e in EPISODES if e.get('in_season_episode', '').startswith('SPE') and spe_num in e.get('in_season_episode')]
    
    # CE (Classic Episode)
    elif q.startswith('ce') or q.startswith('classic'):
        is_ce_search = True
        ce_num = re.sub(r'[^0-9]', '', q.replace('ce', '').replace('classic', ''))
        results = [e for e in EPISODES if e.get('in_season_episode', '').upper().startswith('CE') and ce_num in e.get('in_season_episode')]
    
    # Fallback: Title keyword search
    if not results:
        results = [e for e in EPISODES if q in e.get('title', '').lower() or q in e.get('search_blob', '').lower()][:5]
    
    if not results:
        await interaction.followup.send(
            f'❌ No episodes found for "**{query}**"\n\n'
            '**Supported formats:**\n'
            '• JP Story #: `150` or `jp:150`\n'
            '• IN Episode: `s01e01`\n'
            '• Special: `spe01` or `spe1`\n'
            '• Classic: `ce1` or `classic1`\n'
            '• Title: `nobita`'
        )
        return
    
    # Build response embed
    first_result = results[0]
    in_ep = first_result.get('in_season_episode', 'N/A')
    jp_st = first_result.get('jp_story_number', 'Not indexed')
    title = first_result.get('title', 'Unknown')[:60]
    category = first_result.get('category', 'unknown').replace('_', ' ').title()
    
    embed = Embed(title=f"🔍 Episode Info", color=0x6d4aff)
    embed.description = f"**Title:** {title}\n**Category:** {category}"
    
    if is_jp_search:
        embed.add_field(name='🇮🇳 Indian Episode', value=in_ep, inline=True)
        embed.add_field(name='🇯🇵 Japanese Story #', value=jp_st, inline=True)
        embed.set_footer(text=f'Searched by: JP #{query.replace("jp:", "")}')
    
    elif is_in_search:
        embed.add_field(name='🇮🇳 Indian Episode', value=in_ep, inline=True)
        embed.add_field(name='🇯🇵 Japanese Story #', value=jp_st, inline=True)
        embed.set_footer(text=f'Searched by: IN Episode {query}')
    
    elif is_spe_search:
        embed.add_field(name='🇮🇳 Special Episode', value=in_ep, inline=True)
        embed.add_field(name='🇯🇵 Japanese Story #', value=jp_st, inline=True)
        embed.set_footer(text=f'Searched by: SPE {query}')
    
    elif is_ce_search:
        embed.add_field(name='🇮🇳 Classic Episode', value=in_ep, inline=True)
        embed.add_field(name='🇯🇵 Japanese Story #', value=jp_st, inline=True)
        embed.set_footer(text=f'Searched by: CE {query}')
    
    # Show additional matches if multiple
    if len(results) > 1:
        additional = [r.get('title', 'Unknown')[:50] for r in results[1:5]]
        embed.add_field(name=f'➕ Additional Matches ({len(results)-1} more)',
                       value='\n'.join(additional), inline=False)
    
    await interaction.followup.send(embed=embed)

# --- JP NUMBER LOOKUP (Convenience Command) ---
@bot.tree.command(name='jp', description='Lookup by Japanese Story Number')
@app_commands.describe(jp_number='Japanese Story Number (e.g., 150)')
async def jp_cmd(interaction, jp_number: str):
    await interaction.response.defer()
    
    results = [e for e in EPISODES if e.get('jp_story_number') == jp_number]
    
    if not results:
        await interaction.followup.send(f'❌ No episode found for JP Story #{jp_number}')
        return
    
    first = results[0]
    embed = Embed(title=f"🇯🇵 JP Story #{jp_number}", color=0x6d4aff)
    embed.add_field(name='Title', value=first.get('title', 'Unknown'), inline=False)
    embed.add_field(name='Indian Episode', value=first.get('in_season_episode', 'N/A'), inline=True)
    embed.add_field(name='Category', value=first.get('category', 'unknown').replace('_', ' ').title(), inline=True)
    embed.set_footer(text=f'Total matches: {len(results)}')
    
    await interaction.followup.send(embed=embed)

# --- LIST ALL (Pagination) ---
@bot.tree.command(name='list', description='List episodes with pagination')
@app_commands.describe(page='Page number (1-999)')
async def list_cmd(interaction, page: int = 1):
    await interaction.response.defer()
    
    PAGE_SIZE = 10
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    
    if start >= len(EPISODES):
        await interaction.followup.send(f'❌ Page {page} does not exist.')
        return
    
    chunk = EPISODES[start:end]
    embed = Embed(title=f'Doraemon Episodes - Page {page}', color=0x6d4aff)
    embed.description = f'Total episodes: **{len(EPISODES)}** | Showing {start + 1}-{min(end, len(EPISODES))}'
    
    for r in chunk:
        in_ep = r.get('in_season_episode', 'N/A')
        jp_st = r.get('jp_story_number', '-')
        title = r.get('title', 'Unknown')[:50]
        embed.add_field(name=f'{in_ep}: {title}', value=f'JP: #{jp_st}', inline=False)
    
    total_pages = (len(EPISODES) // PAGE_SIZE) + 1
    embed.set_footer(text=f'Page {page} of {total_pages}')
    await interaction.followup.send(embed=embed)

# --- STATS ---
@bot.tree.command(name='stats', description='Show database statistics')
async def stats_cmd(interaction):
    await interaction.response.defer()
    
    counts = {}
    with_jp_ref = 0
    for e in EPISODES:
        cat = e.get('category', 'unknown')
        counts[cat] = counts.get(cat, 0) + 1
        if e.get('jp_story_number'):
            with_jp_ref += 1
    
    embed = Embed(title='Database Statistics', color=0x6d4aff)
    embed.description = f'Total episodes: **{len(EPISODES)}**\nEpisodes with JP refs: **{with_jp_ref}**\n\nBreakdown:'
    
    for cat, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        embed.add_field(name=cat.replace('_', ' ').title(), value=f'**{cnt}** episodes', inline=True)
    
    embed.set_footer(text=f'Database: {DB.get("metadata", {}).get("generated_at", "unknown")}')
    await interaction.followup.send(embed=embed)

# --- HELP ---
@bot.tree.command(name='help', description='Show available commands')
async def help_cmd(interaction):
    embed = Embed(title='Doraemon Search Bot Help', color=0x6d4aff)
    embed.description = '''
**Available Commands:**
• `/search <query>` - Advanced search (JP#, IN#, SPE, CE, or title)
• `/jp <number>` - Lookup by Japanese Story Number
• `/list [page]` - Browse all episodes (paginated)
• `/stats` - Show database statistics
• `/help` - Show this message

**Search Examples:**
• `/search 150` - Find JP Story #150
• `/search s01e01` - Find IN Episode S01E01
• `/search spe01` - Find Special Episode #1
• `/search ce1` - Find Classic Episode #1
• `/search nobita` - Search by title
• `/jp 150` - Lookup JP Story #150 directly
'''
    embed.set_footer(text='Bidirectional JP ↔ IN Cross-Reference Search')
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user}')
    synced = await bot.tree.sync()
    print(f'✅ Synced {len(synced)} GLOBAL commands')
    if bot.guilds:
        print(f'Bot is in {len(bot.guilds)} guild(s)')

bot.run(TOKEN)
