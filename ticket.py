from __future__ import annotations

import asyncio
import os
import logging
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("ticket")

def get_env_id(key: str) -> int:
    val = os.environ.get(key, "0")
    return int(val) if val.isdigit() else 0


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

        messages = [
            message
            async for message in interaction.channel.history(limit=500, oldest_first=True)
        ]
        transcript_content = f"--- Transcript for {interaction.channel.name} ---\n\n"
        for msg in messages:
            transcript_content += f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author}: {msg.clean_content}\n"

        from io import BytesIO
        file_bytes = BytesIO(transcript_content.encode("utf-8"))
        transcript_file = discord.File(
            file_bytes, filename=f"{interaction.channel.name}-transcript.txt"
        )

        log_channel_id = get_env_id("TICKET_LOG_CHANNEL_ID")
        if log_channel_id:
            log_channel = interaction.guild.get_channel(log_channel_id)
            if log_channel:
                log_embed = discord.Embed(
                    title="📝 Ticket Closed & Logged",
                    description=(
                        f"**Ticket Channel:** `{interaction.channel.name}`\n"
                        f"**Closed By:** {interaction.user.mention}\n"
                    ),
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                file_bytes.seek(0)
                await log_channel.send(embed=log_embed, file=transcript_file)

        embed = discord.Embed(
            title="🔒 Closing Ticket",
            description=f"Ticket closed by {interaction.user.mention}.\nChannel deleting in 5 seconds...",
            color=discord.Color.red(),
        )
        await interaction.followup.send(embed=embed)
        await asyncio.sleep(5)

        try:
            await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
        except discord.NotFound:
            pass

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
            color=discord.Color.green(),
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
        transcript_content = f"--- Transcript for {interaction.channel.name} ---\n\n"
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
# Dashboard Ticket Category Select Menu & View (Standard View for Dropdown)
# -------------------------------------------------------------------
class TicketCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="General Ticket",
                value="general",
                description="Questions, Department Inquiries, Basic Partnerships",
                emoji="💬",
            ),
            discord.SelectOption(
                label="Internal Affairs Ticket",
                value="ia",
                description="Reporting LR Staff or Players in-game",
                emoji="🛡️",
            ),
            discord.SelectOption(
                label="Management Ticket",
                value="management",
                description="HR Staff Report, Violations of ToS, Staff Partnerships",
                emoji="👑",
            ),
        ]
        super().__init__(
            placeholder="Select a category to open a ticket...",
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
        elif category_choice == "ia":
            cat_id = get_env_id("IA_TICKET_CATEGORY_ID")
            role_id = get_env_id("INTERNAL_AFFAIRS_ROLE_ID")
            prefix = "ia"
            title_name = "Internal Affairs"
        else:
            cat_id = get_env_id("MANAGEMENT_TICKET_CATEGORY_ID")
            role_id = get_env_id("MANAGEMENT_ROLE_ID")
            prefix = "mgmt"
            title_name = "Management Support"

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
        info_embed = discord.Embed(
            title=f"🎟️ {title_name}",
            description=(
                f"Welcome {user.mention}! Thank you for contacting the **South Dakota Support Team**.\n\n"
                "Please describe your issue or inquiry in detail below. Provide any relevant usernames, screenshots, "
                "or proof so staff can assist you promptly.\n\n"
                f"**Opened By:** {user.mention}\n"
                f"**Category:** `{title_name}`\n"
                f"**Status:** `Open`"
            ),
            color=0x1C5D86
        )
        embeds.append(info_embed)

        if category_choice == "general":
            format_embed = discord.Embed(
                title="🤝 Partnership & General Inquiry Format",
                description=(
                    "Please copy and fill out the following format for your partnership or inquiry:\n\n"
                    "**Member Count:**\n"
                    "**Server Name:**\n"
                    "**Server Owner:**\n"
                    "**Why Should We Partner/Affiliate:**"
                ),
                color=discord.Color.blue()
            )
            embeds.append(format_embed)
        elif category_choice == "ia":
            format_embed = discord.Embed(
                title="🛡️ Internal Affairs Report Format",
                description=(
                    "Please copy and fill out the following format for your report:\n\n"
                    "**HR Member:**\n"
                    "**Reason For Report:**\n"
                    "**Proof:**"
                ),
                color=discord.Color.orange()
            )
            embeds.append(format_embed)

        ping_content = f"{user.mention} {staff_role.mention}" if staff_role else user.mention
        
        await ticket_channel.send(
            content=ping_content,
            embeds=embeds,
            view=TicketControlView()
        )

        await interaction.followup.send(
            content=f"✅ Ticket created successfully! Go to {ticket_channel.mention}",
            ephemeral=True,
        )


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect())


# -------------------------------------------------------------------
# YOUR CUSTOM DASHBOARD PANEL VIEW (V2 Layout Container Only)
# -------------------------------------------------------------------
class CustomDashboardLayoutView(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        
        component = discord.ui.Container(
            discord.ui.MediaGallery(
                discord.MediaGalleryItem(
                    "https://cdn.discordapp.com/attachments/1330603976097267762/1532071333247062226/Copy_of_Copy_of_DASHBOARD_12.png?ex=6a6b841e&is=6a6a329e&hm=966c18dd79c0a50aca7d540a9ad861798317ae137bf2c88db996422070a3d122&",
                ),
                id=2,
            ),
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.large,
                id=3,
            ),
            discord.ui.TextDisplay(
                "## 🆘 South Dakota Support Dashboard\n\n***Please note that when opening a ticket, you ensure that it is the correct ticket type, you do not ping any staff, if you are doing a partnership your server meet the requirements in https://discord.com/channels/1283441788153102358/1528083022094532618 and you fill out any relevant information or formats provided.***",
                id=4,
            ),
            discord.ui.Separator(
                visible=True,
                spacing=discord.SeparatorSpacing.large,
                id=5,
            ),
            discord.ui.TextDisplay(
                "**General ticket**\n`-` Questions\n`-` Department Inquires\n`-` Basic Partnerships\n\n**Internal Affairs Ticket**\n`-` Reporting LR Staff\n`-` Reporting players in-game\n\n**Management Ticket**\n`-` HR Staff Report\n`-` Violations of ToS\n`-` Staff Partnership Inquires",
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
                "**📝 Please note that we do not merge into server, you may merge into us but we wont merge into you. Also, if you ping any staff when you have opened your ticket, it will be closed.**",
                id=8,
            ),
            discord.ui.MediaGallery(
                discord.MediaGalleryItem(
                    "https://cdn.discordapp.com/attachments/1330603976097267762/1531890992440020992/Untitled_design_39.png" 
                ),
                id=11
            ),
            accent_color=1858598,
            id=1,
        )
        
        self.add_item(component)


# -------------------------------------------------------------------
# Cog Definition
# -------------------------------------------------------------------
class AdvancedTicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="ticketpanel",
        description="Posts the support ticket dashboard panel.",
    )
    @app_commands.default_permissions(administrator=True)
    async def ticketpanel(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Publishing support panel...", ephemeral=True)
        await interaction.channel.send(view=CustomDashboardLayoutView())
        await interaction.channel.send(view=PanelView())

    # Autocomplete function to dynamic restrict to configured ticket categories only
    async def escalate_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        category_map = {
            "General Support": get_env_id("GENERAL_TICKET_CATEGORY_ID"),
            "Internal Affairs": get_env_id("IA_TICKET_CATEGORY_ID"),
            "Management Support": get_env_id("MANAGEMENT_TICKET_CATEGORY_ID"),
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

        # Validates that the channel starts with your active prefixes
        valid_prefixes = ("general-", "ia-", "mgmt-")
        if not interaction.channel.name.startswith(valid_prefixes):
            await interaction.followup.send(
                "❌ This command can only be used inside an active ticket channel!", 
                ephemeral=True
            )
            return

        category_id = int(category) if category.isdigit() else 0
        target_category = interaction.guild.get_channel(category_id)

        # Retrieve Environment IDs for Categories and Roles
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
            old_category = interaction.channel.category

            # 1. Move channel to the target category
            await interaction.channel.edit(
                category=target_category, 
                reason=f"Ticket escalated to {target_category.name} by {interaction.user}"
            )

            # 2. Sync permissions with the new category first
            await interaction.channel.edit(sync_permissions=True)

            # 3. Update permissions so only the designated role (and ticket opener) can view
            gen_role = interaction.guild.get_role(gen_role_id) if gen_role_id else None
            ia_role = interaction.guild.get_role(ia_role_id) if ia_role_id else None
            mgmt_role = interaction.guild.get_role(mgmt_role_id) if mgmt_role_id else None

            # Remove access for staff roles not meant to see this category
            if target_category.id == gen_cat_id:
                # General Category: Allow General Staff Role
                if gen_role:
                    await interaction.channel.set_permissions(gen_role, read_messages=True, view_channel=True, send_messages=True)
                if ia_role:
                    await interaction.channel.set_permissions(ia_role, overwrite=None)
                if mgmt_role:
                    await interaction.channel.set_permissions(mgmt_role, overwrite=None)

            elif target_category.id == ia_cat_id:
                # Internal Affairs Category: Only IA Role
                if ia_role:
                    await interaction.channel.set_permissions(ia_role, read_messages=True, view_channel=True, send_messages=True)
                if gen_role:
                    await interaction.channel.set_permissions(gen_role, read_messages=False, view_channel=False)
                if mgmt_role:
                    await interaction.channel.set_permissions(mgmt_role, read_messages=False, view_channel=False)

            elif target_category.id == mgmt_cat_id:
                # Management Category: Only Management Role
                if mgmt_role:
                    await interaction.channel.set_permissions(mgmt_role, read_messages=True, view_channel=True, send_messages=True)
                if gen_role:
                    await interaction.channel.set_permissions(gen_role, read_messages=False, view_channel=False)
                if ia_role:
                    await interaction.channel.set_permissions(ia_role, read_messages=False, view_channel=False)

            embed = discord.Embed(
                title="⚠️ Ticket Escalated",
                description=(
                    f"This ticket has been escalated to **{target_category.name}** "
                    f"by {interaction.user.mention}.\nPermissions have been updated."
                ),
                color=discord.Color.gold(),
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