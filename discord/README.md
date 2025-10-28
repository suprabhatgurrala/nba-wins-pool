# Wins Pool Discord App
A Discord application that enables slash commands to post wins pool standings in your Discord server.

## Adding the Bot to Your Server
1. Select or create a Discord app in the [Discord Developer Portal](https://discord.com/developers/applications)
2. Navigate to the OAuth tab and check the following boxes under **OAuth2 URL Generator**:

    **Scopes**
        - [x] Bot

    **Bot Permissions**
        - [x] Send Messages
        - [x] Use Slash Commands

    **Integration Type** should be left as the default *Guild Install*.
3. Visit the URL that was generated, which should allow you to add the bot to servers that you manage.

## Running the Bot
The bot is intended to be run by Docker Compose as part of the larger project, but it is possible to run it standalone as well.
Running the bot requires your Discord app's token, which can be found under the **Bot** tab in the Developer Portal.

Set the DISCORD_TOKEN and BACKEND_URL environment variables and run:
```bash
uv run discord_bot.py
```

You might need to refresh your Discord to see the new commands. You can do so on desktop with ctrl-R.

## Deleting all Existing commands
If you're repurposing an old app or just want to have a clean slate, there is a helper script in `/scripts` that will clear all registered commands.
```bash
uv run scripts/clear_commands.py
```
