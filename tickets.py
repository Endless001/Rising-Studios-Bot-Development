from __future__ import annotations

import asyncio
import os
import logging
import pathlib
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("ticket")

def get_env_id(key: str) -> int:
    val = os.environ.get(key, "0")
    return int(val) if val.isdigit() else 0


# -------------------------------------------------------------------
# Google Sheets Logger Helper
# -------------------------------------------------------------------
async def log_to_google_sheet(action: str, data: dict):
    """
    Appends ticket event data (Created / Closed) to a Google Sheet asynchronously.
    Requires `gspread` installed and `TICKET_SPREADSHEET_ID` + Google Service Account set up.
    """
    spreadsheet_id = os.environ.get("TICKET_SPREADSHEET_ID")
    if not spreadsheet_id:
        return

    def _sync_log():
        try:
            import gspread
            base_dir = pathlib.Path(__file__).parent
            cred_path = base_dir / "credentials.json"
            
            cred_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", str(cred_path))
            gc = gspread.service_account(filename=cred_file)
            
            sh = gc.open_by_key(spreadsheet_id)
            worksheet = sh.sheet1

            if action == "OPEN":
                worksheet.append_row([
                    data.get("timestamp"),
                    "CREATED",
                    str(data.get("channel_id")),
                    data.get("channel_name"),
                    data.get("category"),
                    str(data.get("user")),
                    "OPEN"
                ])
            elif action == "CLOSE":
                worksheet.append_row([
                    data.get("timestamp"),
                    "CLOSED",
                    str(data.get("channel_id")),
                    data.get("channel_name"),
                    data.get("category"),
                    str(data.get("closed_by")),
                    "CLOSED",
                    data.get("reason", "No reason provided")
                ])
        except Exception as e:
            log.warning(f"Failed to log ticket to Google Sheets: {e}")

    await asyncio.to_thread(_sync_log)


# -------------------------------------------------------------------
# Common Ticket Close Handler
# -------------------------------------------------------------------
async def execute_ticket_close(channel: discord.TextChannel, user: discord.User | discord.Member, guild: discord.Guild, reason: str = "No reason provided"):
    messages = [
        message
        async for message in channel.history(limit=500, oldest_first=True)
    ]
    
    category_name = channel.category.name if channel.category else "Unknown Category"
    timestamp_str = discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')

    transcript_content = (
        f"========================================\n"
        f" TICKET TRANSCRIPT\n"
        f" Channel: #{channel.name}\n"
        f" Channel ID: {channel.id}\n"
        f" Category: {category_name}\n"
        f" Closed By: {user}\n"
        f" Reason: {reason}\n"
        f" Date: {timestamp_str}\n"
        f"========================================\n\n"
    )
    for msg in messages:
        transcript_content += f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author}: {msg.clean_content}\n"

    from io import BytesIO
    file_bytes = BytesIO(transcript_content.encode("utf-8"))
    transcript_file = discord.File(
        file_bytes, filename=f"{channel.name}-transcript.txt"
    )

    log_channel_id = get_env_id("TICKET_LOG_CHANNEL_ID")
    if log_channel_id:
        log_channel = guild.get_channel(log_channel_id)
        if log_channel:
            log_embed = discord.Embed(
                title="📝 Ticket Closed & Logged",
                description=(
                    f"**Ticket Channel:** `{channel.name}`\n"
                    f"**Channel ID:** `{channel.id}`\n"
                    f"**Category:** `{category_name}`\n"
                    f"**Closed By:** {user.mention}\n"
                    f"**Reason:** `{reason}`\n"
                    f"**Total Messages:** `{len(messages)}`"
                ),
                color=discord.Color.from_rgb(52, 152, 219),
                timestamp=discord.utils.utcnow()
            )
            file_bytes.seek(0)
            await log_channel.send(embed=log_embed, file=transcript_file)

    asyncio.create_task(log_to_google_sheet("CLOSE", {
        "timestamp": timestamp_str,
        "channel_id": channel.id,
        "channel_name": channel.name,
        "category": category_name,
        "closed_by": str(user),
        "reason": reason
    }))

    embed = discord.Embed(
        title="🔒 Closing Ticket",
        description=f"Ticket closed by {user.mention}.\n**Reason:** {reason}\nChannel deleting in 5 seconds...",
        color=discord.Color.red(),
    )
    await channel.send(embed=embed)
    await asyncio.sleep(5)

    try:
        await channel.delete(reason=f"Ticket closed by {user} - Reason: {reason}")
    except discord.NotFound:
        pass


# -------------------------------------------------------------------
# Inside Ticket Controls (Close, Claim, Transcript)
# -------------------------------------------------------------------
class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close Ticket",
        style=discord.ButtonStyle.red,
        emoji="🔒",
        custom_id="ticket_close_btn",
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await execute_ticket_close(
            channel=interaction.channel,
            user=interaction.user,
            guild=interaction.guild,
            reason="Closed via Button"
        )

    @discord.ui.button(
        label="Claim",
        style=discord.ButtonStyle.green,
        emoji="🙋‍♂️",
        custom_id="ticket_claim_btn",
    )
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.disabled = True
        button.label = f"Claimed by {interaction.user.display_name}"
        await interaction.response.edit_message(view=self)

        embed = discord.Embed(
            description=f"✅ This ticket is now being handled by {interaction.user.mention}.",
            color=discord.Color.from_rgb(52, 152, 219),
        )
        await interaction.followup.send(embed=embed)

    @discord.ui.button(
        label="Transcript",
        style=discord.ButtonStyle.secondary,
        emoji="📂",
        custom_id="ticket_transcript_btn",
    )
    async def generate_transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        messages = [
            message async for message in interaction.channel.history(limit=500, oldest_first=True)
        ]
        category_name = interaction.channel.category.name if interaction.channel.category else "Unknown Category"
        transcript_content = (
            f"========================================\n"
            f" TICKET TRANSCRIPT (MANUAL EXPORT)\n"
            f" Channel: #{interaction.channel.name}\n"
            f" Channel ID: {interaction.channel.id}\n"
            f" Category: {category_name}\n"
            f" Exported By: {interaction.user}\n"
            f" Date: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"========================================\n\n"
        )
        for msg in messages:
            transcript_content += f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author}: {msg.clean_content}\n"

        from io import BytesIO
        file_bytes = BytesIO(transcript_content.encode("utf-8"))
        discord_file = discord.File(
            file_bytes, filename=f"{interaction.channel.name}-transcript.txt"
        )

        await interaction.followup.send(
            content="📄 Here is the message transcript for this ticket:",
            file=discord_file,
            ephemeral=True,
        )


# -------------------------------------------------------------------
# Dashboard Ticket Category Select Menu & View
# -------------------------------------------------------------------
class TicketCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="General",
                value="general",
                description="Discord questions & in-game support",
                emoji="💬",
            ),
            discord.SelectOption(
                label="Player Report",
                value="player_report",
                description="Report in-game players or Discord users",
                emoji="🛡️",
            ),
            discord.SelectOption(
                label="Partnership Requests",
                value="partnership",
                description="Request a server partnership or affiliation",
                emoji="🤝",
            ),
        ]
        super().__init__(
            placeholder="Select a ticket category...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_category_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        user = interaction.user
        category_choice = self.values[0]

        if category_choice == "general":
            cat_id = get_env_id("GENERAL_TICKET_CATEGORY_ID")
            role_id = get_env_id("GENERAL_ROLE_ID")
            prefix = "general"
            title_name = "General Support"
        elif category_choice == "player_report":
            cat_id = get_env_id("IA_TICKET_CATEGORY_ID")
            role_id = get_env_id("INTERNAL_AFFAIRS_ROLE_ID")
            prefix = "report"
            title_name = "Player Report"
        else:
            cat_id = get_env_id("MANAGEMENT_TICKET_CATEGORY_ID")
            role_id = get_env_id("MANAGEMENT_ROLE_ID")
            prefix = "partner"
            title_name = "Partnership Request"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False, view_channel=False),
            user: discord.PermissionOverwrite(read_messages=True, view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, view_channel=True, send_messages=True),
        }

        staff_role = guild.get_role(role_id) if role_id else None
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                read_messages=True, view_channel=True, send_messages=True
            )

        target_category = guild.get_channel(cat_id) if cat_id else None

        channel_name = f"{prefix}-{user.name}".lower().replace(" ", "-")
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=target_category,
            overwrites=overwrites,
            reason=f"{title_name} Ticket opened by {user}",
        )
        
        embeds = []
        light_blue = discord.Color.from_rgb(52, 152, 219)
        
        info_embed = discord.Embed(
            title=f"🎟️ {title_name}",
            description=(
                f"Welcome {user.mention}! Thank you for contacting **Rising Studios Development**.\n\n"
                "Please describe your issue or inquiry in detail below. Provide any relevant information, usernames, "
                "or proof so our staff team can assist you promptly.\n\n"
                f"**Opened By:** {user.mention}\n"
                f"**Category:** `{title_name}`\n"
                f"**Status:** `Open`"
            ),
            color=light_blue
        )
        embeds.append(info_embed)

        if category_choice == "player_report":
            format_embed = discord.Embed(
                title="🛡️ Player Report Format",
                description=(
                    "Please copy and fill out the following format for your report:\n\n"
                    "**User/Player Being Reported:**\n"
                    "**Reason For Report:**\n"
                    "**Proof / Evidence (Screenshots/Video):**"
                ),
                color=light_blue
            )
            embeds.append(format_embed)
        elif category_choice == "partnership":
            format_embed = discord.Embed(
                title="🤝 Partnership Request Format",
                description=(
                    "Please copy and fill out the following format for your partnership request:\n\n"
                    "**Server Name:**\n"
                    "**Invite Link:**\n"
                    "**Member Count:**\n"
                    "**Server Owner:**\n"
                    "**Why Should We Partner:**"
                ),
                color=light_blue
            )
            embeds.append(format_embed)

        ping_content = f"{user.mention} {staff_role.mention}" if staff_role else user.mention
        
        await ticket_channel.send(
            content=ping_content,
            embeds=embeds,
            view=TicketControlView()
        )

        asyncio.create_task(log_to_google_sheet("OPEN", {
            "timestamp": discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
            "channel_id": ticket_channel.id,
            "channel_name": ticket_channel.name,
            "category": title_name,
            "user": str(user)
        }))

        await interaction.followup.send(
            content=f"✅ Ticket created successfully! Go to {ticket_channel.mention}",
            ephemeral=True,
        )


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect())


# -------------------------------------------------------------------
# Custom Dashboard Layout View
# -------------------------------------------------------------------
class CustomDashboardLayoutView(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        
        component = discord.ui.Container(
            discord.ui.MediaGallery(
                discord.MediaGalleryItem(
                    "https://media.discordapp.net/attachments/1562568568959144077/1562568710755979324/Support_Header.png?ex=6ada7703&is=6ad92583&hm=be11b9d9302c8bda42d1a2586be76c2ce467a22a3793dc4cc77c9db848977a73&=&format=webp&quality=lossless",
                ),
                id=2,
            ),
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.large,
                id=3,
            ),
            discord.ui.TextDisplay(
                "## 🆘 Rising Studios Development Support Dashboard\n\n***Please select the correct ticket category below. Make sure not to ping staff members directly upon opening a ticket, and provide all requested information or formats clearly.***",
                id=4,
            ),
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.large,
                id=5,
            ),
            discord.ui.TextDisplay(
                "**💬 General**\n`-` Discord Questions\n`-` Support about in-game\n\n**🛡️ Player Report**\n`-` In-game Player report\n`-` Discord User Report\n\n**🤝 Partnership Requests**\n`-` Request a partnership/affiliation",
                id=6,
            ),
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.large,
                id=9,
            ),
            discord.ui.TextDisplay(
                "**Discord Bot Issues**\n> If you're experiencing any issues with the Discord bot, please report them using the form below.\n> 📨 [Issue Report Form](https://forms.gle/oWWQvkaLqoUAz4Rk8)",
                id=10,
            ),
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.large,
                id=7,
            ),
            discord.ui.TextDisplay(
                "**📝 Note: Pinging staff members inside tickets without reason may result in your ticket being closed.**",
                id=8,
            ),
            discord.ui.MediaGallery(
                discord.MediaGalleryItem(
                    "https://media.discordapp.net/attachments/1562568568959144077/1562883155025854484/Untitled_Design_2.png?ex=6adb9bdd&is=6ada4a5d&hm=cb8b6f5923013403164cb1669c1f48985fbceb4033e3b571dffbd3a5fba9de6b&=&format=webp&quality=lossless" 
                ),
                id=11
            ),
            accent_color=3447003,
            id=1,
        )
        
        self.add_item(component)


# -------------------------------------------------------------------
# Cog Definition
# -------------------------------------------------------------------
class AdvancedTicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def is_ticket_channel(self, channel: discord.abc.GuildChannel) -> bool:
        if not isinstance(channel, discord.TextChannel):
            return False
            
        gen_cat_id = get_env_id("GENERAL_TICKET_CATEGORY_ID")
        ia_cat_id = get_env_id("IA_TICKET_CATEGORY_ID")
        mgmt_cat_id = get_env_id("MANAGEMENT_TICKET_CATEGORY_ID")
        
        allowed_cat_ids = [c for c in [gen_cat_id, ia_cat_id, mgmt_cat_id] if c != 0]
        
        if not allowed_cat_ids:
            return channel.name.startswith(("general-", "report-", "partner-"))
            
        return channel.category_id in allowed_cat_ids

    @app_commands.command(
        name="ticketpanel",
        description="Posts the support ticket dashboard panel.",
    )
    @app_commands.default_permissions(administrator=True)
    async def ticketpanel(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Publishing support panel...", ephemeral=True)
        await interaction.channel.send(view=CustomDashboardLayoutView())
        await interaction.channel.send(view=PanelView())

    # -------------------------------------------------------------------
    # Slash Commands
    # -------------------------------------------------------------------
    @app_commands.command(
        name="close",
        description="Closes the active ticket channel.",
    )
    @app_commands.describe(reason="Reason for closing the ticket")
    @app_commands.default_permissions(manage_channels=True)
    async def close_slash(self, interaction: discord.Interaction, reason: str = "No reason provided"):
        if not self.is_ticket_channel(interaction.channel):
            await interaction.response.send_message(
                "❌ This command can only be used inside an active ticket channel!",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await execute_ticket_close(
            channel=interaction.channel,
            user=interaction.user,
            guild=interaction.guild,
            reason=reason
        )

    @app_commands.command(
        name="claim",
        description="Claims the active ticket for yourself.",
    )
    @app_commands.default_permissions(manage_channels=True)
    async def claim(self, interaction: discord.Interaction):
        if not self.is_ticket_channel(interaction.channel):
            await interaction.response.send_message(
                "❌ This command can only be used inside an active ticket channel!",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            description=f"🙋‍♂️ This ticket has been claimed by {interaction.user.mention}.",
            color=discord.Color.from_rgb(52, 152, 219),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="unclaim",
        description="Unclaims the active ticket so another staff member can handle it.",
    )
    @app_commands.default_permissions(manage_channels=True)
    async def unclaim(self, interaction: discord.Interaction):
        if not self.is_ticket_channel(interaction.channel):
            await interaction.response.send_message(
                "❌ This command can only be used inside an active ticket channel!",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            description=f"🔓 This ticket is no longer claimed and is open for other staff members.",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="add",
        description="Adds a user to the current ticket channel.",
    )
    @app_commands.describe(user="The member to add to this ticket")
    @app_commands.default_permissions(manage_channels=True)
    async def add_user(self, interaction: discord.Interaction, user: discord.Member):
        if not self.is_ticket_channel(interaction.channel):
            await interaction.response.send_message(
                "❌ This command can only be used inside an active ticket channel!",
                ephemeral=True,
            )
            return

        await interaction.channel.set_permissions(
            user, read_messages=True, view_channel=True, send_messages=True
        )

        embed = discord.Embed(
            description=f"✅ Added {user.mention} to this ticket.",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="rename",
        description="Renames the current ticket channel.",
    )
    @app_commands.describe(new_name="The new name for this ticket channel")
    @app_commands.default_permissions(manage_channels=True)
    async def rename(self, interaction: discord.Interaction, new_name: str):
        if not self.is_ticket_channel(interaction.channel):
            await interaction.response.send_message(
                "❌ This command can only be used inside an active ticket channel!",
                ephemeral=True,
            )
            return

        clean_name = new_name.lower().replace(" ", "-")
        await interaction.channel.edit(name=clean_name, reason=f"Renamed by {interaction.user}")

        embed = discord.Embed(
            description=f"✏️ Ticket channel renamed to `{clean_name}`.",
            color=discord.Color.from_rgb(52, 152, 219),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="notes",
        description="Opens a private staff notes thread for this ticket.",
    )
    @app_commands.default_permissions(manage_channels=True)
    async def ticket_notes(self, interaction: discord.Interaction):
        if not self.is_ticket_channel(interaction.channel):
            await interaction.response.send_message(
                "❌ This command can only be used inside an active ticket channel!",
                ephemeral=True,
            )
            return

        thread_name = f"notes-{interaction.channel.name}"

        for thread in interaction.channel.threads:
            if thread.name == thread_name:
                await interaction.response.send_message(
                    f"⚠️ Staff notes thread already exists: {thread.mention}",
                    ephemeral=True,
                )
                return

        thread = await interaction.channel.create_thread(
            name=thread_name,
            auto_archive_duration=1440,
            type=discord.ChannelType.private_thread,
            reason=f"Staff notes thread created by {interaction.user}",
        )

        await thread.send(
            f"📌 **Staff Notes Thread** created by {interaction.user.mention}.\n"
            "Use this thread for internal staff notes regarding this ticket."
        )

        await interaction.response.send_message(
            f"✅ Created staff notes thread: {thread.mention}",
            ephemeral=True,
        )

    # -------------------------------------------------------------------
    # Escalate Command
    # -------------------------------------------------------------------
    async def escalate_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        category_map = {
            "General Support": get_env_id("GENERAL_TICKET_CATEGORY_ID"),
            "Player Report": get_env_id("IA_TICKET_CATEGORY_ID"),
            "Partnership Requests": get_env_id("MANAGEMENT_TICKET_CATEGORY_ID"),
        }

        choices = []
        for name, cat_id in category_map.items():
            if cat_id:
                cat_obj = interaction.guild.get_channel(cat_id)
                if cat_obj and current.lower() in cat_obj.name.lower():
                    choices.append(app_commands.Choice(name=cat_obj.name, value=str(cat_obj.id)))

        return choices

    @app_commands.command(
        name="escalate",
        description="Escalates the current ticket to a different category.",
    )
    @app_commands.describe(category="Select the ticket category you want to escalate this ticket into")
    @app_commands.autocomplete(category=escalate_autocomplete)
    @app_commands.default_permissions(manage_channels=True)
    async def escalate(
        self, 
        interaction: discord.Interaction, 
        category: str
    ):
        await interaction.response.defer(ephemeral=True)

        if not self.is_ticket_channel(interaction.channel):
            await interaction.followup.send(
                "❌ This command can only be used inside an active ticket channel!", 
                ephemeral=True
            )
            return

        category_id = int(category) if category.isdigit() else 0
        target_category = interaction.guild.get_channel(category_id)

        gen_cat_id = get_env_id("GENERAL_TICKET_CATEGORY_ID")
        ia_cat_id = get_env_id("IA_TICKET_CATEGORY_ID")
        mgmt_cat_id = get_env_id("MANAGEMENT_TICKET_CATEGORY_ID")

        gen_role_id = get_env_id("GENERAL_ROLE_ID")
        ia_role_id = get_env_id("INTERNAL_AFFAIRS_ROLE_ID")
        mgmt_role_id = get_env_id("MANAGEMENT_ROLE_ID")

        allowed_cat_ids = [gen_cat_id, ia_cat_id, mgmt_cat_id]

        if not target_category or target_category.id not in allowed_cat_ids:
            await interaction.followup.send(
                "❌ Invalid category selected. Please select a valid ticket category.",
                ephemeral=True
            )
            return

        try:
            await interaction.channel.edit(
                category=target_category, 
                reason=f"Ticket escalated to {target_category.name} by {interaction.user}"
            )
            await interaction.channel.edit(sync_permissions=True)

            gen_role = interaction.guild.get_role(gen_role_id) if gen_role_id else None
            ia_role = interaction.guild.get_role(ia_role_id) if ia_role_id else None
            mgmt_role = interaction.guild.get_role(mgmt_role_id) if mgmt_role_id else None

            if target_category.id == gen_cat_id:
                if gen_role:
                    await interaction.channel.set_permissions(gen_role, read_messages=True, view_channel=True, send_messages=True)
                if ia_role:
                    await interaction.channel.set_permissions(ia_role, overwrite=None)
                if mgmt_role:
                    await interaction.channel.set_permissions(mgmt_role, overwrite=None)

            elif target_category.id == ia_cat_id:
                if ia_role:
                    await interaction.channel.set_permissions(ia_role, read_messages=True, view_channel=True, send_messages=True)
                if gen_role:
                    await interaction.channel.set_permissions(gen_role, read_messages=False, view_channel=False)
                if mgmt_role:
                    await interaction.channel.set_permissions(mgmt_role, read_messages=False, view_channel=False)

            elif target_category.id == mgmt_cat_id:
                if mgmt_role:
                    await interaction.channel.set_permissions(mgmt_role, read_messages=True, view_channel=True, send_messages=True)
                if gen_role:
                    await interaction.channel.set_permissions(gen_role, read_messages=False, view_channel=False)
                if ia_role:
                    await interaction.channel.set_permissions(ia_role, read_messages=False, view_channel=False)

            light_blue = discord.Color.from_rgb(52, 152, 219)
            embed = discord.Embed(
                title="⚠️ Ticket Escalated",
                description=(
                    f"This ticket has been escalated to **{target_category.name}** "
                    f"by {interaction.user.mention}.\nPermissions have been updated."
                ),
                color=light_blue,
                timestamp=discord.utils.utcnow()
            )
            await interaction.channel.send(embed=embed)

            await interaction.followup.send(
                f"✅ Successfully moved this ticket to **{target_category.name}** and updated role permissions.",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I do not have permission to edit channel permissions or move channels.", 
                ephemeral=True
            )
        except discord.HTTPException:
            await interaction.followup.send(
                "❌ An error occurred while trying to move the channel.", 
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(AdvancedTicketCog(bot))