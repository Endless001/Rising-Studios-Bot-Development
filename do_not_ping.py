from __future__ import annotations

import os
import logging
import discord
from discord.ext import commands

# Configure Module Logger
log = logging.getLogger("do_not_ping")

# Centralized Error Code Reference
ERROR_CODES = {
    400: "Invalid Request",
    401: "Invalid Bot Token",
    403: "Missing Permissions",
    404: "Cog Offline / Not Loaded",
    405: "Command Disabled",
    408: "Timeout",
    409: "Conflict",
    420: "API Rate Limited",
    429: "Too Many Requests",
    430: "Webhook Failed",
    434: "Channel Missing",
    435: "Role Missing",
    436: "Server Missing",
    437: "User Not Found",
    450: "Logging Error",
    500: "Internal Bot Error",
    501: "Feature Not Available",
    502: "Service Offline",
    503: "Bot Maintenance",
    506: "Startup Failed",
    509: "Bot Crash",
    510: "Unknown Error",
}


def get_error_embed(code: int, details: str = "") -> discord.Embed:
    meaning = ERROR_CODES.get(code, "Unknown Error")
    embed = discord.Embed(
        title=f"⚠️ System Error | Code {code}",
        description=f"**Status:** `{meaning}`\n{f'**Details:** {details}' if details else ''}",
        color=discord.Color.red()
    )
    return embed


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
                    # Strip out inline comments safely
                    val = value.split("#")[0].strip()
                    env_data[key.strip()] = val
    except FileNotFoundError:
        pass
    return env_data


# Load configuration by looking up one directory or locally
config = load_env_file("../.env")
if not config:
    config = load_env_file(".env")

SERVER_NAME = config.get("SERVER_NAME", "South Dakota State Roleplay")

# Parse protected role IDs
raw_role_ids = config.get("DO_NOT_PING_ROLE_IDS", "")
PROTECTED_ROLE_IDS = set()
if raw_role_ids:
    for item in raw_role_ids.split(","):
        item = item.strip()
        if item.isdigit():
            PROTECTED_ROLE_IDS.add(int(item))

# Parse bypass role IDs
raw_bypass_ids = config.get("PING_BYPASS_ROLE_IDS", "")
BYPASS_ROLE_IDS = set()
if raw_bypass_ids:
    for item in raw_bypass_ids.split(","):
        item = item.strip()
        if item.isdigit():
            BYPASS_ROLE_IDS.add(int(item))


class DoNotPingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if not PROTECTED_ROLE_IDS:
            log.warning(
                "[%s] Do Not Ping Cog Warning: DO_NOT_PING_ROLE_IDS is missing or empty inside .env (Code 435)",
                SERVER_NAME
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Ignore messages sent by bots or outside of guilds
        if message.author.bot or not message.guild:
            return

        # Check if the sender has Administrator privileges
        if isinstance(message.author, discord.Member):
            if message.author.guild_permissions.administrator:
                return

            # Check if sender has any bypass roles
            author_role_ids = {role.id for role in message.author.roles}
            if BYPASS_ROLE_IDS.intersection(author_role_ids):
                return

        # Check if the message has any user mentions and we have roles configured
        if message.mentions and PROTECTED_ROLE_IDS:
            for mentioned_user in message.mentions:
                # Exclude self-pings
                if mentioned_user.id == message.author.id:
                    continue

                # Fetch the member from the guild cache or API to check their roles
                member = message.guild.get_member(mentioned_user.id)
                if not member:
                    try:
                        member = await message.guild.fetch_member(mentioned_user.id)
                    except discord.HTTPException:
                        log.debug("Could not resolve member %s in guild (Code 437)", mentioned_user.id)
                        continue

                if member:
                    # Optimized intersecting set lookup to find a matching protected role
                    member_role_ids = {role.id for role in member.roles}
                    matching_ids = PROTECTED_ROLE_IDS.intersection(member_role_ids)

                    if matching_ids:
                        # Grab the first matched role object to pull its name
                        matched_id = next(iter(matching_ids))
                        matching_role = message.guild.get_role(matched_id)
                        role_name = matching_role.name if matching_role else "Protected Staff"

                        # Structural warning embed matching system standards
                        embed = discord.Embed(
                            title=f"⚠️ {SERVER_NAME} — Security Notice",
                            description=(
                                f"Please refrain from pinging members holding the **{role_name}** position "
                                "unless it is an absolute emergency or explicitly requested."
                            ),
                            color=discord.Color.orange()
                        )
                        embed.set_footer(text="Notice: This system alert auto-deletes in 5 seconds.")

                        # Reply directly and set it to auto-delete after 5 seconds
                        try:
                            await message.reply(embed=embed, delete_after=5)
                            log.info("[%s] Ping intercepted. Warning dispatched for mention targeting %s.", SERVER_NAME, member)
                        except discord.Forbidden:
                            log.error("[%s] Permission failure sending ping warning embed (Code 403).", SERVER_NAME)
                        except discord.HTTPException as e:
                            log.error("[%s] Network interface error sending protection embed (Code %s): %s", SERVER_NAME, e.status, e)

                        # Break early to avoid sending duplicate warnings for one message
                        break


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DoNotPingCog(bot))