import os

import pandas as pd
import requests
from table2ascii import table2ascii

import discord
from discord import app_commands

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

TOKEN = os.environ["DISCORD_TOKEN"]
BACKEND_URL = os.environ["BACKEND_URL"]
URL = "https://wins.suprabhatgurrala.com/pools/sg/season/2025-26"


@tree.command(
    name="nba_wins_pool_standings",
    description="Display NBA Wins Pool standings",
    # guilds=GUILDS
)
async def standings(interaction: discord.Interaction):
    """Display NBA Wins Pool standings"""
    pool_id = "9d7d9a7f-125c-431d-91de-b26f54129abc"
    season = "2025-26"
    leaderboard_response = requests.get(
        f"{BACKEND_URL}/api/pools/{pool_id}/season/{season}/leaderboard"
    )
    leaderboard_data = leaderboard_response.json()
    leaderboard_response.raise_for_status()

    df = pd.DataFrame(leaderboard_data["roster"])

    df["W-L"] = df.apply(lambda row: f"{row['wins']}-{row['losses']}", axis=1)
    df["Rank"] = df["rank"].apply(lambda x: f"{x:.0f}")
    df["Name"] = df["name"]
    df["Today"] = df.apply(
        lambda row: f"{row['wins_today']:.0f}-{row['losses_today']:.0f}", axis=1
    )
    df["7d"] = df.apply(
        lambda row: f"{row['wins_today']:.0f}-{row['losses_today']:.0f}", axis=1
    )
    df = df[["Rank", "Name", "W-L", "Today", "7d"]].fillna("")

    output = table2ascii(
        header=df.columns.tolist(), body=df.values.tolist(), cell_padding=0
    )
    embed = discord.Embed(
        title="NBA Wins Pool Standings",
        description=f"```{output}```",
        url=URL,
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="configure", description="Prints which server called the command")
async def configure(interaction: discord.Interaction):
    """Prints which server called the command"""
    if interaction.guild:
        print(
            f"Command 'configure' used in server: {interaction.guild.name} ({interaction.guild.id})"
        )
        await interaction.response.send_message(
            f"This server is '{interaction.guild.name}' (ID: {interaction.guild.id})"
        )
    else:
        await interaction.response.send_message(
            "This command can only be used in a server."
        )


@client.event
async def on_ready():
    print(f"We have logged in as {client.user}")
    await tree.sync()
    print("Ready!")


client.run(TOKEN)
