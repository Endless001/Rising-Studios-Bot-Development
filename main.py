from __future__ import annotations

import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

class TicketBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
        )

    async def setup_hook(self):
        # Load the tickets extension from tickets.py
        await self.load_extension("tickets")
        await self.load_extension("events")
        await self.load_extension("welcome")
        await self.load_extension("dev_panel")
        await self.load_extension("member_count")



        
        # Sync slash commands globally or to a test guild
        try:
            synced = await self.tree.sync()
            print(f"Successfully synced {len(synced)} command(s).")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("Bot is ready and online!")

bot = TicketBot()

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN is missing from environment variables or .env file.")
    bot.run(token)