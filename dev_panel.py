from __future__ import annotations

import os
import random
import asyncio
import time
import logging
import json
import io
import discord
from discord import app_commands
from discord.ext import commands

# Note: For VC Text-to-Speech functionality, install gTTS via terminal: pip install gTTS
try:
    from gtts import gTTS
    HAS_GTTS = True
except ImportError:
    HAS_GTTS = False

log = logging.getLogger("dev_panel")

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

config = load_env_file(".env")
if not config:
    config = load_env_file("../.env")

SERVER_NAME = config.get("SERVER_NAME", "Rising Development")
raw_owner_id = config.get("ROLEADD_AUTHORIZED_USER_ID", "959223334137126922")
OWNER_ID = int(raw_owner_id) if raw_owner_id.isdigit() else 959223334137126922
STATUS_CHANNEL_ID = int(config.get("STATUS_CHANNEL_ID", "0"))

# File to persist authorized users who can view/use the dev panel
AUTH_FILE = "authorized_devs.json"

def load_authorized_users() -> set[int]:
    users = {OWNER_ID}
    if os.path.exists(AUTH_FILE):
        try:
            with open(AUTH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for uid in data:
                        if isinstance(uid, int) or (isinstance(uid, str) and uid.isdigit()):
                            users.add(int(uid))
        except Exception as e:
            log.error(f"Failed to load authorized users: {e}")
    return users

def save_authorized_users(users: set[int]):
    try:
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(list(users), f)
    except Exception as e:
        log.error(f"Failed to save authorized users: {e}")

AUTHORIZED_USERS = load_authorized_users()

def is_endless(user_id: int) -> bool:
    return user_id == OWNER_ID

def can_view_panel(user_id: int) -> bool:
    return user_id in AUTHORIZED_USERS


class StatusTextModal(discord.ui.Modal, title="Update Custom Status Text"):
    status_input = discord.ui.TextInput(
        label="Activity Text Status",
        placeholder="e.g., Rising Development | Active",
        required=True,
        max_length=128
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not can_view_panel(interaction.user.id):
            await interaction.response.send_message("❌ Security Fault: Clearance denied.", ephemeral=True)
            return

        current_status = getattr(interaction.client, "_forced_status", discord.Status.online)
        new_activity = discord.CustomActivity(name=self.status_input.value)
        
        await interaction.client.change_presence(status=current_status, activity=new_activity)
        
        embed = discord.Embed(
            title="⚡ Dev Panel — System Verified",
            description=f"Bot custom activity text status successfully adjusted to:\n`🟢 {self.status_input.value}`",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class TTSDispatchModal(discord.ui.Modal, title="Broadcast TTS Message"):
    tts_text = discord.ui.TextInput(
        label="Message Content",
        style=discord.TextStyle.paragraph,
        placeholder="Enter text to speak...",
        required=True,
        max_length=500
    )
    
    target_mode = discord.ui.TextInput(
        label="Target Engine (Type 'vc' or 'chat')",
        placeholder="vc = Voice Channel | chat = Normal Text Channel",
        default="vc",
        required=True,
        max_length=4
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not can_view_panel(interaction.user.id):
            await interaction.response.send_message("❌ Security Fault: Clearance denied.", ephemeral=True)
            return

        mode = self.target_mode.value.strip().lower()
        content = self.tts_text.value.strip()

        if mode == "chat":
            await interaction.channel.send(content, tts=True)
            await interaction.response.send_message("🗣️ Standard Text Channel TTS sent successfully.", ephemeral=True)
            
        elif mode == "vc":
            if not interaction.guild or not interaction.guild.voice_client:
                await interaction.response.send_message("❌ Bot must be connected to a Voice Channel first!", ephemeral=True)
                return

            if not HAS_GTTS:
                await interaction.response.send_message("❌ `gTTS` package is missing. Run `pip install gTTS` in your terminal to enable VC audio synthesis.", ephemeral=True)
                return

            vc = interaction.guild.voice_client
            if vc.is_playing():
                await interaction.response.send_message("⚠️ Bot is currently playing another audio stream.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)
            
            try:
                fp = io.BytesIO()
                tts = gTTS(text=content, lang='en')
                tts.write_to_fp(fp)
                fp.seek(0)

                source = discord.FFmpegPCMAudio(fp, pipe=True)
                vc.play(source)
                await interaction.followup.send(f"🗣️ Transmitting voice synthesis into {vc.channel.mention}:\n> *\"{content}\"*", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"❌ Failed to stream TTS to voice: `{e}`", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Invalid target mode. Use `vc` or `chat`.", ephemeral=True)


class DevPanelInterface(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.update_cycle_button()

    def update_cycle_button(self):
        button_list = [item for item in self.children if getattr(item, 'custom_id', None) == "dev_panel_cycle_btn"]
        if button_list:
            button = button_list[0]
            if self.cog.cycle_active:
                button.label = "🔄 Cycle: ON"
                button.style = discord.ButtonStyle.success
            else:
                button.label = "🔄 Cycle: OFF"
                button.style = discord.ButtonStyle.danger

    @discord.ui.select(
        placeholder="🟢 Choose Online Presence State...",
        options=[
            discord.SelectOption(label="Online / Active", value="online", emoji="🟢"),
            discord.SelectOption(label="Idle / Away", value="idle", emoji="🌙"),
            discord.SelectOption(label="Do Not Disturb / Quiet", value="dnd", emoji="⛔")
        ],
        custom_id="dev_panel_status_select",
        row=0
    )
    async def status_select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        if not can_view_panel(interaction.user.id):
            await interaction.response.send_message("❌ Security Fault: Clearance denied.", ephemeral=True)
            return

        status_map = {
            "online": discord.Status.online,
            "idle": discord.Status.idle,
            "dnd": discord.Status.dnd
        }
        
        target_status = status_map.get(select.values[0], discord.Status.online)
        interaction.client._forced_status = target_status
        current_activity = interaction.guild.me.activity if interaction.guild and interaction.guild.me else None
        
        await interaction.client.change_presence(status=target_status, activity=current_activity)
        await interaction.response.send_message(f"✅ Presence updated to **{select.values[0].upper()}**.", ephemeral=True)

    @discord.ui.button(label="Status Text", style=discord.ButtonStyle.primary, custom_id="dev_panel_text_btn", row=1)
    async def text_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_view_panel(interaction.user.id):
            await interaction.response.send_message("❌ Security Fault: Clearance denied.", ephemeral=True)
            return
        await interaction.response.send_modal(StatusTextModal())

    @discord.ui.button(label="🔄 Cycle: ON", style=discord.ButtonStyle.danger, custom_id="dev_panel_cycle_btn", row=1)
    async def cycle_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_view_panel(interaction.user.id):
            await interaction.response.send_message("❌ Security Fault: Clearance denied.", ephemeral=True)
            return

        if self.cog.cycle_active:
            self.cog.cycle_active = False
            self.cog.next_switch_timestamp = None
        else:
            self.cog.cycle_active = True
            self.cog.bot.loop.create_task(self.cog.run_status_rotation())

        self.update_cycle_button()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="📋 Server Roles", style=discord.ButtonStyle.secondary, custom_id="dev_panel_roles_btn", row=1)
    async def roles_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_view_panel(interaction.user.id):
            await interaction.response.send_message("❌ Security Fault: Clearance denied.", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("❌ Must be executed inside a server.", ephemeral=True)
            return

        roles = sorted(interaction.guild.roles, key=lambda r: r.position, reverse=True)
        role_lines = [f"`{role.id}` — {role.mention}" for role in roles if not role.is_default()]

        chunk = "\n".join(role_lines[:30])
        embed = discord.Embed(
            title=f"📋 Server Role Registry ({len(roles)-1} Roles)",
            description=chunk or "No custom roles detected.",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="📡 Status View", style=discord.ButtonStyle.secondary, custom_id="dev_panel_send_status_btn", row=2)
    async def send_status_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_view_panel(interaction.user.id):
            await interaction.response.send_message("❌ Security Fault: Clearance denied.", ephemeral=True)
            return

        status_cog = self.cog.bot.get_cog("BotStatusCog")
        if not status_cog:
            await interaction.response.send_message("⚠️ Error: `BotStatusCog` is not currently loaded.", ephemeral=True)
            return

        target_channel_id = STATUS_CHANNEL_ID or int(os.getenv("STATUS_CHANNEL_ID", "0"))
        if not target_channel_id:
            await interaction.response.send_message("⚠️ Error: `STATUS_CHANNEL_ID` is missing.", ephemeral=True)
            return

        channel = self.cog.bot.get_channel(target_channel_id) or await self.cog.bot.fetch_channel(target_channel_id)
        
        await interaction.response.defer(ephemeral=True)
        try:
            status_view = status_cog.build_status_view(is_online=True)
            await channel.purge(limit=20)
            new_msg = await channel.send(view=status_view)
            status_cog.status_message = new_msg
            await interaction.followup.send(f"✅ Deployed to <#{target_channel_id}>!", ephemeral=True)
        except Exception as err:
            await interaction.followup.send(f"❌ Dispatch Error: `{err}`", ephemeral=True)

    @discord.ui.button(label="Join VC", style=discord.ButtonStyle.success, emoji="🔊", custom_id="dev_panel_join_vc", row=2)
    async def join_vc_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_view_panel(interaction.user.id):
            await interaction.response.send_message("❌ Security Fault: Clearance denied.", ephemeral=True)
            return

        member = interaction.user
        if not isinstance(member, discord.Member) or not member.voice or not member.voice.channel:
            await interaction.response.send_message("❌ Connect to a voice channel first!", ephemeral=True)
            return

        target_channel = member.voice.channel
        try:
            voice_client = interaction.guild.voice_client
            if voice_client:
                await voice_client.move_to(target_channel)
            else:
                await target_channel.connect()
            await interaction.response.send_message(f"🔊 Connected to {target_channel.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ VC Join Failed: `{e}`", ephemeral=True)

    @discord.ui.button(label="Mute/Deafen", style=discord.ButtonStyle.secondary, emoji="🎙️", custom_id="dev_panel_audio_state", row=2)
    async def audio_state_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_view_panel(interaction.user.id):
            await interaction.response.send_message("❌ Security Fault: Clearance denied.", ephemeral=True)
            return

        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_connected():
            await interaction.response.send_message("❌ Bot is not connected to a Voice Channel.", ephemeral=True)
            return

        guild_me = interaction.guild.me
        new_state = not guild_me.voice.self_mute if guild_me.voice else True
        
        try:
            await interaction.guild.change_voice_state(channel=voice_client.channel, self_mute=new_state, self_deaf=new_state)
            state_text = "Muted & Deafened" if new_state else "Unmuted & Undeafened"
            await interaction.response.send_message(f"🎙️ Bot voice state toggled: **{state_text}**.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed adjusting audio states: `{e}`", ephemeral=True)

    @discord.ui.button(label="Leave VC", style=discord.ButtonStyle.danger, emoji="🔇", custom_id="dev_panel_leave_vc", row=2)
    async def leave_vc_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_view_panel(interaction.user.id):
            await interaction.response.send_message("❌ Security Fault: Clearance denied.", ephemeral=True)
            return

        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            vc_name = voice_client.channel.mention
            await voice_client.disconnect()
            await interaction.response.send_message(f"🔇 Disconnected from {vc_name}.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Voice client is not connected.", ephemeral=True)

    @discord.ui.button(label="TTS Engine", style=discord.ButtonStyle.primary, emoji="🗣️", custom_id="dev_panel_tts_btn", row=3)
    async def tts_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_view_panel(interaction.user.id):
            await interaction.response.send_message("❌ Security Fault: Clearance denied.", ephemeral=True)
            return
        await interaction.response.send_modal(TTSDispatchModal())


class DevPanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cycle_active = True
        self._loop_running = False
        self.next_switch_timestamp: int | None = None
        
        self.status_pool = [
            "Welcome To Rising Development",
            "Launch Day: Oct 31st!",
            "Fear",
            "Mangled: Oct 31st!"
        ]
        
        if not hasattr(bot, "_forced_status"):
            bot._forced_status = discord.Status.online

    @commands.Cog.listener()
    async def on_ready(self):
        if not self._loop_running and self.cycle_active:
            self.bot.loop.create_task(self.run_status_rotation())

    async def run_status_rotation(self) -> None:
        if self._loop_running:
            return
        
        self._loop_running = True
        await self.bot.wait_until_ready()

        while self.cycle_active:
            new_text = random.choice(self.status_pool)
            current_status = getattr(self.bot, "_forced_status", discord.Status.online)
            
            try:
                await self.bot.change_presence(
                    status=current_status,
                    activity=discord.CustomActivity(name=new_text)
                )
                
                next_delay = random.randint(15, 420)
                self.next_switch_timestamp = int(time.time()) + next_delay
                
                for _ in range(next_delay):
                    if not self.cycle_active:
                        break
                    await asyncio.sleep(1)

            except Exception as e:
                print(f"⚠️ [Dev Cycle Exception] Presence update failed: {e}")
                self.next_switch_timestamp = None
                await asyncio.sleep(10)
                
        self._loop_running = False
        self.next_switch_timestamp = None

    @app_commands.command(name="devpanel", description="Opens the secure server root infrastructure control system.")
    async def devpanel(self, interaction: discord.Interaction):
        if not can_view_panel(interaction.user.id):
            await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🛠️ {SERVER_NAME} — Root Console",
            description=(
                "Welcome to the central developer core array.\n\n"
                "Use the panel features below to alter internal status states, read guild role IDs, toggle VC muting, or trigger Voice/Text TTS synthesis."
            ),
            color=discord.Color.dark_grey()
        )
        embed.add_field(name="🛰️ Latency", value=f"`{round(self.bot.latency * 1000)}ms`", inline=True)
        embed.add_field(name="🔐 Clearance", value=f"Root (`{interaction.user.name}`)", inline=True)

        await interaction.response.send_message(embed=embed, view=DevPanelInterface(self), ephemeral=True)

    # Slash group to let Endless add/remove users who can view/use the dev panel
    devauth = app_commands.Group(name="devauth", description="Manage who can access the developer panel.")

    @devauth.command(name="add", description="Authorize a user to access the dev panel.")
    @app_commands.describe(user="The user to grant dev panel access to")
    async def devauth_add(self, interaction: discord.Interaction, user: discord.User):
        if not is_endless(interaction.user.id):
            await interaction.response.send_message("❌ Access Denied: Only Developers can manage dev panel access.", ephemeral=True)
            return

        AUTHORIZED_USERS.add(user.id)
        save_authorized_users(AUTHORIZED_USERS)
        await interaction.response.send_message(f"✅ Successfully granted dev panel access to {user.mention}.", ephemeral=True)

    @devauth.command(name="remove", description="Revoke a user's access to the dev panel.")
    @app_commands.describe(user="The user to revoke dev panel access from")
    async def devauth_remove(self, interaction: discord.Interaction, user: discord.User):
        if not is_endless(interaction.user.id):
            await interaction.response.send_message("❌ Access Denied: Only Developers can manage dev panel access.", ephemeral=True)
            return

        if user.id == OWNER_ID:
            await interaction.response.send_message("❌ Cannot remove Endless from authorized users.", ephemeral=True)
            return

        if user.id in AUTHORIZED_USERS:
            AUTHORIZED_USERS.remove(user.id)
            save_authorized_users(AUTHORIZED_USERS)
            await interaction.response.send_message(f"✅ Successfully revoked dev panel access from {user.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ {user.mention} was not in the authorized users list.", ephemeral=True)

    @devauth.command(name="list", description="List all users authorized to access the dev panel.")
    async def devauth_list(self, interaction: discord.Interaction):
        if not can_view_panel(interaction.user.id):
            await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
            return

        mentions = [f"<@{uid}>" for uid in AUTHORIZED_USERS]
        embed = discord.Embed(
            title="🛡️ Authorized Dev Panel Users",
            description="\n".join(mentions) or "No authorized users.",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name="load")
    async def load_cog(self, ctx: commands.Context, *, cog_name: str):
        if not is_endless(ctx.author.id):
            await ctx.send("❌ Access Denied.")
            return
        try:
            await self.bot.load_extension(cog_name)
            await ctx.send(f"✅ Loaded `{cog_name}` successfully.")
        except Exception as e:
            await ctx.send(f"❌ Failed to load: `{e}`")

    @commands.command(name="restart")
    async def restart_cog(self, ctx: commands.Context, *, cog_name: str):
        if not is_endless(ctx.author.id):
            await ctx.send("❌ Access Denied.")
            return

        cog_query = cog_name.strip()
        extensions_to_reload = []
        for ext in list(self.bot.extensions.keys()):
            if cog_query.lower() in ext.lower():
                extensions_to_reload.append(ext)

        if not extensions_to_reload:
            await ctx.send(f"❌ No loaded extension matching `{cog_query}` found.")
            return

        results = []
        for ext in extensions_to_reload:
            try:
                await self.bot.reload_extension(ext)
                results.append(f"✅ Reloaded `{ext}`")
            except Exception as e:
                results.append(f"❌ Failed reloading `{ext}`: `{e}`")

        await ctx.send("\n".join(results))


async def setup(bot: commands.Bot):
    await bot.add_cog(DevPanelCog(bot))