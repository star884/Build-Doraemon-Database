import discord
import json
import os
from discord import app_commands, Embed
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
bot = commands.Bot(command_prefix='!', intents=discord.Intents.default())

# Load database
try:
    with open('database/search_index.json') as f:
        DB = json.load(f)
    EPISODES = DB.get('items', [])
    print(f'✅ Loaded {len(EPISODES)} episodes from database')
except FileNotFoundError:
    EPISODES = []
    print('❌ Database file not found')

# --- SEARCH COMMAND ---
@bot.tree.command(name='search', description='Search Doraemon episodes by title or keyword')
@app_commands.describe(query='Episode title or keyword')
async def search_cmd(interaction, query: str):
    q = query.lower()
    results = []
    for item in EPISODES:
        if q in item.get('title', '').lower() or q in item.get('search_blob', ''):
            results.append(item)
    
    if not results:
        await interaction.response.send_message(f'❌ No episodes found for **{query}**')
        return
    
    await show_results(interaction, results, query)

# --- LIST ALL COMMAND (Pagination!) ---
@bot.tree.command(name='list', description='List all Doraemon episodes with pagination')
@app_commands.describe(page='Page number (1-999)')
async def list_cmd(interaction, page: int = 1):
    await interaction.response.defer()
    
    PAGE_SIZE = 10
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    
    if start >= len(EPISODES):
        await interaction.followup.send(f'❌ Page {page} does not exist. Total pages: {(len(EPISODES) // PAGE_SIZE) + 1}')
        return
    
    chunk = EPISODES[start:end]
    
    embed = Embed(title=f'Doraemon Episodes - Page {page}', color=0x6d4aff)
    embed.description = f'Total episodes: **{len(EPISODES)}** | Showing {start + 1}-{min(end, len(EPISODES))}'
    
    for r in chunk:
        title = r.get('title', 'Unknown')[:60]
        cat = r.get('category', 'unknown').replace('_', ' ').title()
        ep = r.get('india_episode_number', 'N/A')
        embed.add_field(name=f'#{ep} {title}', value=cat, inline=False)
    
    total_pages = (len(EPISODES) // PAGE_SIZE) + 1
    embed.set_footer(text=f'Page {page} of {total_pages} | Use /list page: X to navigate')
    
    await interaction.followup.send(embed=embed)

# --- SEASON LIST COMMAND ---
@bot.tree.command(name='season', description='Show all episodes from a specific season')
@app_commands.describe(season='Season number (1-10) or special/classic')
async def season_cmd(interaction, season: str):
    await interaction.response.defer()
    
    season_lower = season.lower()
    filtered = [e for e in EPISODES if season_lower in e.get('category', '').lower()]
    
    if not filtered:
        await interaction.followup.send(f'❌ No episodes found for season **{season}**')
        return
    
    # Paginate large seasons
    PAGE_SIZE = 10
    for p in range(0, min(len(filtered), 50), PAGE_SIZE):
        chunk = filtered[p:p + PAGE_SIZE]
        page_num = (p // PAGE_SIZE) + 1
        
        embed = Embed(title=f'Season {season} - Page {page_num}', color=0x6d4aff)
        embed.description = f'Total episodes: **{len(filtered)}** | Showing {p + 1}-{min(p + PAGE_SIZE, len(filtered))}'
        
        for r in chunk:
            title = r.get('title', 'Unknown')[:60]
            ep = r.get('india_episode_number', 'N/A')
            embed.add_field(name=f'#{ep} {title}', value='', inline=False)
        
        total_pages = (len(filtered) // PAGE_SIZE) + 1
        if total_pages > 1:
            embed.set_footer(text=f'Page {page_num} of {total_pages} | Use /season "{season}" for full list')
        
        if p == 0:
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(embed=embed)

# --- STATISTICS COMMAND ---
@bot.tree.command(name='stats', description='Show database statistics')
async def stats_cmd(interaction):
    counts = {}
    for e in EPISODES:
        cat = e.get('category', 'unknown')
        counts[cat] = counts.get(cat, 0) + 1
    
    embed = Embed(title='Database Statistics', color=0x6d4aff)
    embed.description = f'Total episodes: **{len(EPISODES)}**\n\nBreakdown:'
    
    for cat, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        embed.add_field(name=cat.replace('_', ' ').title(), value=f'**{cnt}** episodes', inline=True)
    
    embed.set_footer(text=f'Database generated at {DB.get("metadata", {}).get("generated_at", "unknown")}')
    
    await interaction.response.send_message(embed=embed)

# --- HELP COMMAND ---
@bot.tree.command(name='help', description='Show available commands')
async def help_cmd(interaction):
    embed = Embed(title='Doraemon Search Bot Help', color=0x6d4aff)
    embed.description = '''
**Available Commands:**
• `/search <query>` - Search episodes by title/keyword
• `/list [page]` - Browse all episodes (paginated, 10 per page)
• `/season <number>` - Show episodes from specific season (1-10, special, classic)
• `/stats` - Show database statistics
• `/help` - Show this message

**Examples:**
• `/search query:nobita` - Find episodes with nobita
• `/list page:1` - Browse first 10 episodes
• `/season 1` - Show Season 1 episodes
• `/season classic` - Show classic doraemon episodes
'''
    embed.set_footer(text='Made with ❤️ by Star884')
    
    await interaction.response.send_message(embed=embed)

# Helper function for search results
async def show_results(interaction, results, query):
    PAGE_SIZE = 5
    chunk = results[:PAGE_SIZE]
    
    embed = Embed(title=f"🔍 Episodes matching '{query}'", color=0x6d4aff)
    for r in chunk:
        title = r.get('title', 'Unknown')[:70]
        cat = r.get('category', 'unknown').replace('_', ' ').title()
        ep = r.get('india_episode_number', 'N/A')
        embed.add_field(name=f'**#{ep} {title}**', value=cat, inline=False)
    
    footer = f'Found {len(results)} result(s)'
    if len(results) > 5:
        footer += ' (showing top 5)'
    embed.set_footer(text=footer)
    
    await interaction.response.send_message(embed=embed)

# --- ON READY ---
@bot.event
async def on_ready():
    print(f'✅ Logged in as {bot.user}')
    synced = await bot.tree.sync()
    print(f'✅ Synced {len(synced)} GLOBAL commands')
    
    if bot.guilds:
        print(f'Bot is in {len(bot.guilds)} guild(s)')
        for guild in bot.guilds:
            print(f'  - {guild.name} (ID: {guild.id})')

bot.run(TOKEN)
