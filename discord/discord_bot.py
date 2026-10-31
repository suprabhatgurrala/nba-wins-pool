import logging
import os

import pandas as pd
import requests
from table2ascii import Alignment, table2ascii

import discord
from discord import app_commands

logger = logging.getLogger("discord")
logger.setLevel(logging.INFO)

TOKEN = os.environ["DISCORD_TOKEN"]
BACKEND_URL = os.environ["BACKEND_URL"]
LINK_URL_TEMPLATE = "https://wins.suprabhatgurrala.com/pools/{slug}/season/{season}"


def get_pool_data():
    """
    Gets all available pools
    """
    pools_response = requests.get(
        f"{BACKEND_URL}/api/pools", params={"include_seasons": True}
    )
    pools_response.raise_for_status()
    return pools_response.json()


def get_leaderboard_data(slug, season):
    """
    Gets the leaderboard data for a given pool, or None before any team is drafted
    """
    live_response = requests.get(
        f"{BACKEND_URL}/api/pools/slug/{slug}/seasons/{season}/live"
    )
    live_response.raise_for_status()
    return live_response.json()["leaderboard"]


def default_pool_url(guild_id):
    return f"{BACKEND_URL}/api/discord/guilds/{guild_id}/default-pool"


def get_default_pool_id(guild_id):
    """
    Gets the server's default pool ID, or None when it has none
    """
    response = requests.get(default_pool_url(guild_id))
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()["pool_id"]


def find_pool(value):
    """
    Finds a pool by ID, or by name or slug when the user typed it instead of picking a suggestion
    """
    pools = get_pool_data()
    for pool in pools:
        if pool["id"] == value:
            return pool
    lowered = value.strip().lower()
    for pool in pools:
        if lowered in (pool["name"].lower(), pool["slug"].lower()):
            return pool
    return None


intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

CLEAR_DEFAULT = "clear"


def pool_choices(current):
    lowered = current.lower()
    return [
        app_commands.Choice(name=pool["name"], value=pool["id"])
        for pool in get_pool_data()
        if lowered in pool["name"].lower()
    ][:25]


async def pool_autocomplete(interaction: discord.Interaction, current: str):
    return pool_choices(current)


async def set_default_autocomplete(interaction: discord.Interaction, current: str):
    clear = app_commands.Choice(name="Clear default", value=CLEAR_DEFAULT)
    return [clear, *pool_choices(current)][:25]


@tree.command(
    name="wins_pool_standings",
    description="Display Wins Pool standings",
)
@app_commands.autocomplete(pool=pool_autocomplete)
async def standings(interaction: discord.Interaction, pool: str | None = None):
    """Display Wins Pool standings

    Parameters:
        pool (str): Which pool to show standings for. Defaults to this server's default pool.
    """
    if pool is None:
        pool_id = (
            get_default_pool_id(interaction.guild_id) if interaction.guild_id else None
        )
        if pool_id is None:
            await interaction.response.send_message(
                "No default pool for this server. Pass `pool:` or ask an admin to run `/wins_pool_set_default`.",
                ephemeral=True,
            )
            return
        pool = pool_id

    pool_info = find_pool(pool)
    if pool_info is None:
        await interaction.response.send_message(
            f"No pool named `{pool}`.", ephemeral=True
        )
        return

    season = pool_info["seasons"][0]["season"]
    pool_name = pool_info["name"]
    leaderboard_data = get_leaderboard_data(pool_info["slug"], season)
    if leaderboard_data is None:
        await interaction.response.send_message(
            f"No teams have been drafted in {pool_name} for {season} yet."
        )
        return

    df = pd.DataFrame(leaderboard_data["roster"])
    df = df[df["name"] != "Undrafted"]
    df["Rank"] = df["rank"].apply(lambda x: f"{x:.0f}" if not pd.isna(x) else "")

    df["Name"] = df.apply(
        lambda row: f"{row['Rank']} {row['name']}" if row["Rank"] else row["name"],
        axis=1,
    )
    df["W-L"] = df.apply(lambda row: f"{row['wins']}-{row['losses']}", axis=1)
    df["Today"] = df.apply(
        lambda row: f"{row['wins_today']:.0f}-{row['losses_today']:.0f}", axis=1
    )
    df["Win%"] = df["win_probability"].apply(
        lambda x: f"{x * 100:5.1f}%" if pd.notna(x) else ""
    )
    df = df[["Name", "W-L", "Today", "Win%"]].fillna("")

    output = table2ascii(
        header=["Name", "W-L", "Today", "Win%"],
        body=df.values.tolist(),
        alignments=[
            Alignment.LEFT,
            Alignment.CENTER,
            Alignment.CENTER,
            Alignment.CENTER,
        ],
        cell_padding=0,
    )
    embed = discord.Embed(
        title=f"{season} Standings",
        description=f"```{output}```",
        url=LINK_URL_TEMPLATE.format(slug=pool_info["slug"], season=season),
        timestamp=interaction.created_at,
    )
    embed.set_author(name=f"{pool_name}")
    await interaction.response.send_message(embed=embed)
    logger.info("Responded with standings for %s %s", pool_name, season)


@tree.command(
    name="wins_pool_set_default",
    description="Set the pool /wins_pool_standings shows in this server",
)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.autocomplete(pool=set_default_autocomplete)
async def set_default(interaction: discord.Interaction, pool: str):
    """Set the pool /wins_pool_standings shows in this server

    Parameters:
        pool (str): The server's default pool, or "Clear default" to remove it.
    """
    url = default_pool_url(interaction.guild_id)
    if pool == CLEAR_DEFAULT:
        requests.delete(url).raise_for_status()
        await interaction.response.send_message(
            f"Default pool cleared by {interaction.user.mention}."
        )
        logger.info("Cleared default pool for guild %s", interaction.guild_id)
        return

    pool_info = find_pool(pool)
    if pool_info is None:
        await interaction.response.send_message(
            f"No pool named `{pool}`.", ephemeral=True
        )
        return

    requests.put(url, json={"pool_id": pool_info["id"]}).raise_for_status()
    await interaction.response.send_message(
        f"Default pool set to **{pool_info['name']}** by {interaction.user.mention}."
    )
    logger.info(
        "Set default pool for guild %s to %s", interaction.guild_id, pool_info["name"]
    )


@client.event
async def on_ready():
    logger.info("We have logged in as %s", client.user)
    await tree.sync()
    logger.info("Discord bot is ready.")


logger.info("Starting discord bot...")
client.run(TOKEN)
