from __future__ import annotations

import os
import logging
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Image links configured directly in the code for Rising Development ---
HEADER_IMAGE = "https://cdn.discordapp.com/attachments/1562568568959144077/1563977673368281290/events.jpg?ex=6adf9736&is=6ade45b6&hm=af35e4d53aa42485d028a3b27d896acc86b03393e34e50c65f85b77f4d51ac49&"
FOOTER_IMAGE = "https://cdn.discordapp.com/attachments/1562568568959144077/1562883155025854484/Untitled_Design_2.png?ex=6adf905d&is=6ade3edd&hm=788e3407079b7ba879bb2ef09e5c8d6172c082c4371f0451f035289a5699258d&"

ENTS_POST_URL = os.getenv("ENTS_POST_URL", "")

log = logging.getLogger("rising_development")

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
        title=f"⚠️ Rising Development System Error | Code {code}",
        description=f"**Status:** `{meaning}`\n{f'**Details:** {details}' if details else ''}",
        color=discord.Color.dark_gold(),
    )
    return embed


def build_event_layout(
    event_title: str,
    event_url: str | None,
    description_text: str,
    ping_role_id: int = 0,
) -> discord.ui.LayoutView:
    """Builds the LayoutView V2 structure for Rising Development project updates."""
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
            f"# 🏗️ Rising Development Update: {event_title}\n\n"
            f"{quoted_description}"
        )
    )
    container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.large))

    # 4. Project Details & RSVP Instructions
    details_line = (
        f"**Event Link:** [Click here to view Event]({event_url})\n\n"
        if event_url
        else ""
    )

    container.add_item(
        discord.ui.TextDisplay(
            f"{details_line}"
            f"✅ **React with the checkmark below to confirm participation / RSVP!**"
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

    @commands.Cog.listener()
    async def on_scheduled_event_create(self, event: discord.ScheduledEvent) -> None:
        """Automatically announces and posts an event whenever one is created in Discord."""
        raw_channel_id = os.getenv("EVENT_ANNOUNCE_CHANNEL_ID", "0")
        channel_id = int(raw_channel_id) if raw_channel_id.isdigit() else 0
        if channel_id == 0:
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception:
                return

        if not isinstance(channel, discord.TextChannel):
            return

        event_title = event.name
        event_url = event.url
        event_desc = event.description or "A new development project update or milestone has been scheduled!"

        raw_ping_role = os.getenv("EVENT_PING_ROLE_ID", "0")
        ping_role_id = int(raw_ping_role) if raw_ping_role.isdigit() else 0

        layout_view = build_event_layout(
            event_title, event_url, event_desc, ping_role_id
        )

        try:
            message = await channel.send(
                view=layout_view,
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
            await message.add_reaction("✅")

            if ENTS_POST_URL:
                payload = {
                    "title": event_title,
                    "description": event_desc,
                    "url": event_url,
                    "message_id": str(message.id),
                    "channel_id": str(channel.id),
                    "guild_id": str(event.guild.id) if event.guild else None,
                }
                async with aiohttp.ClientSession() as session:
                    async with session.post(ENTS_POST_URL, json=payload, timeout=10) as resp:
                        if resp.status not in (200, 201, 204):
                            log.warning("Failed to post automated ent to endpoint. Status: %s", resp.status)
        except Exception as e:
            log.error("Exception occurred while auto-announcing scheduled event: %s", e)

    @app_commands.command(
        name="rising-event",
        description="Announce a Rising Development project milestone or event with reaction RSVP.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        event_id="Select a scheduled Discord event from this server",
        custom_details="Optional: Override description with custom project details",
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

        event_title = event.name if event else "Rising Development Milestone"
        event_url = event.url if event else None
        event_desc = (
            event.description
            if event and event.description
            else "A new development project update or milestone is taking place!"
        )

        final_description = custom_details or event_desc

        # Get role ID dynamically from environment
        raw_ping_role = os.getenv("EVENT_PING_ROLE_ID", "0")
        ping_role_id = int(raw_ping_role) if raw_ping_role.isdigit() else 0

        # Build layout view
        layout_view = build_event_layout(
            event_title, event_url, final_description, ping_role_id
        )

        # Send Discord message and add checkmark reaction
        message = await interaction.channel.send(
            view=layout_view,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        await message.add_reaction("✅")

        # Post the Ent / Event payload to the configured ENTS_POST_URL endpoint if set
        if ENTS_POST_URL:
            payload = {
                "title": event_title,
                "description": final_description,
                "url": event_url,
                "message_id": str(message.id),
                "channel_id": str(interaction.channel.id),
                "guild_id": str(interaction.guild.id) if interaction.guild else None,
            }
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(ENTS_POST_URL, json=payload, timeout=10) as resp:
                        if resp.status not in (200, 201, 204):
                            log.warning("Failed to post ent to endpoint. Status: %s", resp.status)
            except Exception as e:
                log.error("Exception occurred while posting ent to ENTS_POST_URL: %s", e)

        # Ephemeral confirmation response to command executor
        await interaction.response.send_message("✅ Rising Development project update published successfully and sent to backend.", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Error running /rising-event command: %s", error)
        embed = get_error_embed(500, f"An internal failure occurred while executing command: {error}")

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventCog(bot))