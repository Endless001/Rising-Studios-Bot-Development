from __future__ import annotations

import os
import logging
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

HEADER_IMAGE = os.getenv("HEADER_IMAGE_URL", "")
FOOTER_IMAGE = os.getenv("FOOTER_IMAGE_URL", "")

log = logging.getLogger("event")

# Centralized Error Code Reference
ERROR_CODES = {
    400: "Invalid Request",
    403: "Missing Permissions",
    434: "Channel Missing",
    500: "Internal Bot Error",
}


def get_error_embed(code: int, details: str = "") -> discord.Embed:
    meaning = ERROR_CODES.get(code, "Unknown Error")
    embed = discord.Embed(
        title=f"⚠️ System Error | Code {code}",
        description=f"**Status:** `{meaning}`\n{f'**Details:** {details}' if details else ''}",
        color=discord.Color.red(),
    )
    return embed


def build_event_layout(
    event_title: str,
    event_url: str | None,
    description_text: str,
    ping_role_id: int = 0,
) -> discord.ui.LayoutView:
    """Builds the LayoutView V2 structure with role ping, text components, and instructions."""
    view = discord.ui.LayoutView()
    container = discord.ui.Container()

    # 1. Role Ping
    if ping_role_id != 0:
        container.add_item(discord.ui.TextDisplay(f"|| <@&{ping_role_id}> ||"))
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))

    # 2. Top Header Banner
    if HEADER_IMAGE:
        container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(HEADER_IMAGE)))
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))

    # 3. Main Title & Blockquote Description
    quoted_description = "\n".join(
        [f"> {line}" for line in description_text.splitlines() if line]
    )
    container.add_item(
        discord.ui.TextDisplay(
            f"# Server Event: {event_title}\n\n"
            f"{quoted_description}"
        )
    )
    container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))

    # 4. Event Details & Reaction Instructions
    details_line = (
        f"**Event Details:** [Click here to view scheduled event]({event_url})\n\n"
        if event_url
        else ""
    )

    container.add_item(
        discord.ui.TextDisplay(
            f"{details_line}"
            f"✅ **React with the checkmark below to RSVP!**"
        )
    )

    # 5. Bottom Footer Banner
    if FOOTER_IMAGE:
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))
        container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(FOOTER_IMAGE)))

    view.add_item(container)
    return view


class EventCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def event_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not interaction.guild:
            return []

        events = interaction.guild.scheduled_events
        choices = []
        for event in events:
            if current.lower() in event.name.lower():
                choices.append(
                    app_commands.Choice(name=event.name, value=str(event.id))
                )

        return choices[:25]

    @app_commands.command(
        name="event",
        description="Announce an ERLC event using server scheduled events with a reaction RSVP.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        event_id="Select a scheduled Discord event from this server",
        custom_details="Optional: Override description with custom text",
    )
    @app_commands.autocomplete(event_id=event_autocomplete)
    async def event_command(
        self,
        interaction: discord.Interaction,
        event_id: str,
        custom_details: str | None = None,
    ) -> None:
        issuer = interaction.user
        if not isinstance(issuer, discord.Member):
            embed = get_error_embed(400, "This command can only be executed within a server context.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not interaction.channel:
            embed = get_error_embed(434, "Active execution channel could not be found.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Fetch scheduled event details
        event = None
        if interaction.guild:
            try:
                event = interaction.guild.get_scheduled_event(int(event_id))
                if not event:
                    event = await interaction.guild.fetch_scheduled_event(int(event_id))
            except Exception:
                event = None

        event_title = event.name if event else "Server Event"
        event_url = event.url if event else None
        event_desc = (
            event.description
            if event and event.description
            else "A Server Start Up (SSU) is currently taking place!"
        )

        final_description = custom_details or event_desc

        # Get role ID dynamically from environment
        raw_ping_role = os.getenv("EVENT_PING_ROLE_ID", "0")
        ping_role_id = int(raw_ping_role) if raw_ping_role.isdigit() else 0

        # Build layout view without buttons
        layout_view = build_event_layout(
            event_title, event_url, final_description, ping_role_id
        )

        # Send message and add the checkmark reaction automatically
        message = await interaction.channel.send(
            view=layout_view,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        await message.add_reaction("✅")
        
        # Ephemeral confirmation response to command executor
        await interaction.response.send_message("✅ Event directory published successfully with reaction RSVP.", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Error running /event command: %s", error)
        embed = get_error_embed(500, f"An internal failure occurred while executing command: {error}")

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventCog(bot))