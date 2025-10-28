# Script to clear all existing commands for a bot
# https://github.com/Rapptz/discord.py/discussions/9064
import os

import discord

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)


@client.event
async def on_ready():
    print(f"We have logged in as {client.user}")
    guilds = client.guilds
    print(f"The {client.user.name} bot is in {len(guilds)} Guilds.")

    for guild in client.guilds:
        tree.clear_commands(guild=guild, type=None)
        await tree.sync(guild=guild)
        print(f"Deleted commands from {guild.name}")

    tree.clear_commands(guild=None, type=None)
    await tree.sync(guild=None)
    print("Deleted global commands")


client.run(os.environ["DISCORD_TOKEN"])
