import json
import os
from discord import app_commands, Embed, Object
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_ID = os.getenv("SERVER_ID")

bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        guild = Object(id=int(SERVER_ID))
        synced = await bot.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} commands")
    except Exception as e:
        print(f"⚠️ Sync failed (normal): {e}")

@bot.tree.command(name="search", description="Search Doraemon episodes")
@app_commands.describe(query="Episode title or keyword")
async def search_command(interaction, query: str):
    try:
        with open("database/search_index.json") as f:
            db = json.load(f)
        
        items = db.get("items", [])
        q = query.lower()
        results = []
        
        for item in items:
            if q in item.get("title", "").lower() or q in item.get("search_blob", ""):
                results.append(item)
            if len(results) >= 10:
                break
        
        if not results:
            await interaction.response.send_message(f"❌ No episodes found for **{query}**")
            return
        
        embed = Embed(title=f"🔍 Episodes matching '{query}'", color=0x6d4aff)
        for r in results[:5]:
            title = r.get("title", "Unknown")
            cat = r.get("category", "unknown").replace("_", " ").title()
            ep = r.get("india_episode_number", "N/A")
            embed.add_field(name=f"**#{ep} {title[:70]}**", value=cat, inline=False)
        
        footer = f"Found {len(results)} result(s)"
        if len(results) > 5:
            footer += f" (showing top 5)"
        embed.set_footer(text=footer)
        
        await interaction.response.send_message(embed=embed)
    except FileNotFoundError:
        await interaction.response.send_message("❌ Database file not found.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {str(e)[:100]}")

bot.run(TOKEN)
