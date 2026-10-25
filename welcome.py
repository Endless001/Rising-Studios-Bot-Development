from __future__ import annotations

import os
import random
import logging
import discord
from discord.ext import commands

log = logging.getLogger("welcome")


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


# Load configuration variables
config = load_env_file(".env")
if not config:
    config = load_env_file("../.env")

raw_welcome_id = config.get("WELCOME_CHANNEL_ID", "0")
WELCOME_CHANNEL_ID = int(raw_welcome_id) if raw_welcome_id.isdigit() else 0
SERVER_NAME = config.get("SERVER_NAME", "Rising Development")


def build_welcome_view(count: int) -> discord.ui.View:
    view = discord.ui.View()
    view.add_item(
        discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label=f"Member #{count}",
            disabled=True,
            custom_id="welcome_member_number",
        )
    )
    return view


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if WELCOME_CHANNEL_ID == 0:
            log.warning("[%s] Welcome Cog Warning: WELCOME_CHANNEL_ID could not be loaded from your .env file.", SERVER_NAME)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return

        channel = None
        if WELCOME_CHANNEL_ID:
            channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
            if channel is None:
                try:
                    channel = await member.guild.fetch_channel(WELCOME_CHANNEL_ID)
                except discord.HTTPException:
                    log.warning("[%s] Could not fetch WELCOME_CHANNEL_ID: %s", SERVER_NAME, WELCOME_CHANNEL_ID)

        if channel is None:
            channel = member.guild.system_channel

        if channel is None or not isinstance(channel, discord.TextChannel):
            log.warning("[%s] No welcome text channel available for guild %s", SERVER_NAME, member.guild.id)
            return

        count = member.guild.member_count or 0
        try:
            await channel.send(
                content=f"Welcome to {SERVER_NAME}, {member.mention}!",
                view=build_welcome_view(count),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
            log.info("[%s] Automatically welcomed %s as member #%s", SERVER_NAME, member.name, count)
        except discord.Forbidden:
            log.error("[%s] Missing permission to send welcome message in channel ID %s", SERVER_NAME, channel.id)

    @discord.app_commands.command(name="welcomesend", description="Manually trigger a test welcome message.")
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def welcomesend(self, interaction: discord.Interaction) -> None:
        """Manually triggers a test welcome message."""
        if not interaction.guild:
            embed = discord.Embed(
                title="⚠️ System Error",
                description="This command can only be executed within a server context.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        members = [m for m in interaction.guild.members if not m.bot]
        if not members:
            embed = discord.Embed(
                title="⚠️ System Error",
                description="No human members found in server cache to test with.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        member = random.choice(members)
        count = interaction.guild.member_count or 0

        if isinstance(interaction.channel, discord.TextChannel):
            try:
                await interaction.channel.send(
                    content=f"Welcome to {SERVER_NAME}, {member.mention}!",
                    view=build_welcome_view(count),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                await interaction.response.send_message("✅ Test welcome message dispatched successfully.", ephemeral=True)
            except discord.Forbidden:
                embed = discord.Embed(
                    title="⚠️ System Error",
                    description="Bot lacks permission to send messages in this channel.",
                    color=discord.Color.red(),
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = discord.Embed(
                title="⚠️ System Error",
                description="Active execution channel could not be resolved.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @welcomesend.error
    async def welcomesend_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
        if isinstance(error, discord.app_commands.MissingPermissions):
            embed = discord.Embed(
                title="⚠️ System Error",
                description="You need Administrator permissions to execute this command.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            log.exception("Error executing /welcomesend: %s", error)
            embed = discord.Embed(
                title="⚠️ System Error",
                description=f"An unexpected error occurred: {error}",
                color=discord.Color.red(),
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))