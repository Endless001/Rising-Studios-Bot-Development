from __future__ import annotations

import os
import logging
import discord
from discord.ext import commands

# Configure Module Logger
log = logging.getLogger("member_count")


def load_env_file(filepath=".env"):
    env_data = {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f.read().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    val = value.split("#")[0].strip()
                    env_data[key.strip()] = val
    except FileNotFoundError:
        pass
    return env_data


# Load configuration by looking up one directory or locally
config = load_env_file("../.env")
if not config:
    config = load_env_file(".env")

# Parse configuration variables
raw_voice_id = config.get("VOICE_CHANNEL_ID", "0")
VOICE_CHANNEL_ID = int(raw_voice_id) if raw_voice_id.isdigit() else 0
SERVER_NAME = config.get("SERVER_NAME", "Rising Development")


class MemberCountCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if VOICE_CHANNEL_ID == 0:
            log.warning("[%s] Member Count Cog Warning: VOICE_CHANNEL_ID is missing or '0' inside .env", SERVER_NAME)

    async def cog_load(self) -> None:
        """Standard discord.py hook that triggers when the cog is successfully loaded."""
        if VOICE_CHANNEL_ID != 0:
            self.bot.loop.create_task(self.initial_sync())

    async def initial_sync(self) -> None:
        await self.bot.wait_until_ready()
        
        # Resolve the channel globally first to prevent cross-guild mismatch errors
        channel = self.bot.get_channel(VOICE_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(VOICE_CHANNEL_ID)
            except discord.HTTPException:
                log.error("[%s] Global fetch failed for VOICE_CHANNEL_ID %s", SERVER_NAME, VOICE_CHANNEL_ID)
                return

        if channel and hasattr(channel, "guild"):
            await self.update_member_count(channel.guild)

    async def update_member_count(self, guild: discord.Guild) -> None:
        """Updates the target voice channel string with current guild tracking totals."""
        if not VOICE_CHANNEL_ID:
            return

        channel = guild.get_channel(VOICE_CHANNEL_ID)
        
        if not channel:
            try:
                channel = await guild.fetch_channel(VOICE_CHANNEL_ID)
            except discord.HTTPException:
                log.error("[%s] Could not locate voice channel ID %s in guild %s", SERVER_NAME, VOICE_CHANNEL_ID, guild.name)
                return

        if channel and isinstance(channel, discord.VoiceChannel):
            member_count = guild.member_count
            new_name = f"〔👥〕Member count: {member_count}"
            
            # Avoid redundant API calls if the channel name is already accurate
            if channel.name == new_name:
                return

            try:
                await channel.edit(name=new_name)
                log.info("[%s] Member count updated -> %s", SERVER_NAME, new_name)
            except discord.Forbidden:
                log.error("[%s] Permission Fault: Bot lacks 'Manage Channels' access", SERVER_NAME)
            except discord.HTTPException as e:
                log.error("[%s] API/Rate-Limit Error updating voice channel: %s", SERVER_NAME, e)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not member.bot:
            await self.update_member_count(member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if not member.bot:
            await self.update_member_count(member.guild)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemberCountCog(bot))