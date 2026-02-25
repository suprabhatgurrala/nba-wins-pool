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


def get_leaderboard_data(pool_id, season):
    """
    Gets the leaderboard data for a given pool
    """
    leaderboard_response = requests.get(
        f"{BACKEND_URL}/api/pools/{pool_id}/season/{season}/leaderboard"
    )
    leaderboard_response.raise_for_status()
    leaderboard_data = leaderboard_response.json()
    return leaderboard_data


intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


pool_data = get_pool_data()

pool_choices = []
pool_data_by_id = {}
for pool in pool_data:
    pool_choices.append(app_commands.Choice(name=pool["name"], value=pool["id"]))
    pool_data_by_id[pool["id"]] = pool


@tree.command(
    name="wins_pool_standings",
    description="Display Wins Pool standings",
)
@app_commands.choices(pool=pool_choices)
async def standings(interaction: discord.Interaction, pool: str):
    """Display Wins Pool standings

    Parameters:
        pool (str): Which pool to show standings for.
    """
    pool_id = pool
    season = pool_data_by_id[pool_id]["seasons"][0]["season"]
    pool_name = pool_data_by_id[pool_id]["name"]
    leaderboard_data = get_leaderboard_data(pool_id, season)

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
    df["Exp."] = df.apply(lambda row: f"{row['expected_wins']:.1f}", axis=1)
    df = df[["Name", "W-L", "Today", "Exp."]].fillna("")

    output = table2ascii(
        header=["Name", "W-L", "Today", "Exp."],
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
        url=LINK_URL_TEMPLATE.format(
            slug=pool_data_by_id[pool_id]["slug"], season=season
        ),
        timestamp=interaction.created_at,
    )
    embed.set_author(name=f"{pool_name}")
    await interaction.response.send_message(embed=embed)
    logger.info("Responded with standings for %s %s", pool_name, season)


@client.event
async def on_ready():
    logger.info("We have logged in as %s", client.user)
    await tree.sync()
    logger.info("Discord bot is ready.")


logger.info("Starting discord bot...")
client.run(TOKEN)
