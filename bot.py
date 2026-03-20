# bot.py
import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Select, Modal, TextInput
from datetime import datetime, timedelta
import os

from config import ADMIN_ROLE_NAME, REMIND_BEFORE_MINUTES
from sheets import (
    save_interview,
    cancel_interview,
    list_interviews,
    is_time_conflict,
    set_notify_channel,
    get_notify_channel,
)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ================= 通知チャンネル =================
def get_notify_channel_obj(guild):
    cid = get_notify_channel(guild.id)
    if cid:
        ch = guild.get_channel(int(cid))
        if ch:
            return ch
    return guild.system_channel

# ================= 日付入力 =================
class DateInputModal(Modal, title="面接日入力"):
    date_str = TextInput(label="日付 (例: 2026-03-20)")

    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"⏰ 面接時間を選んでください", 
            view=TimeSelectView(self.guild, self.date_str.value),
            ephemeral=True
        )

# ================= 時間選択 =================
class TimeSelect(Select):
    def __init__(self, guild, date_str):
        self.guild = guild
        self.date_str = date_str

        options = []
        for h in range(24):
            for m in range(0, 60, 10):  # 10分刻み
                t = f"{h:02}:{m:02}"
                options.append(discord.SelectOption(label=t, value=t))

        super().__init__(placeholder="面接時間", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "👤 面接者を選んでください", 
            view=MemberSelectView(self.guild, self.date_str, self.values[0]),
            ephemeral=True
        )

class TimeSelectView(View):
    def __init__(self, guild, date_str):
        super().__init__(timeout=180)
        self.add_item(TimeSelect(guild, date_str))

# ================= 面接者選択 =================
class MemberSelect(Select):
    def __init__(self, guild, date_str, time_str):
        self.guild = guild
        self.date_str = date_str
        self.time_str = time_str

        options = [
            discord.SelectOption(label=m.display_name, value=str(m.id))
            for m in guild.members if not m.bot
        ][:25]

        super().__init__(placeholder="面接者選択", options=options)

    async def callback(self, interaction: discord.Interaction):
        uid = int(self.values[0])
        member = interaction.guild.get_member(uid)

        if is_time_conflict(interaction.guild.id, self.date_str, self.time_str):
            await interaction.response.send_message("❌ その時間は予約済みです", ephemeral=True)
            return

        save_interview(interaction.guild.id, str(uid), member.display_name, self.date_str, self.time_str)

        await interaction.response.send_message(
            f"✅ 予約完了\n📅 {self.date_str}\n🕒 {self.time_str}\n👤 {member.mention}",
            ephemeral=True
        )

class MemberSelectView(View):
    def __init__(self, guild, date_str, time_str):
        super().__init__(timeout=180)
        self.add_item(MemberSelect(guild, date_str, time_str))

# ================= キャンセル =================
class CancelSelect(Select):
    def __init__(self, guild):
        self.guild = guild
        self.reserves = list_interviews(guild.id)
        options = []
        for r in self.reserves:
            label = f"{r[1]}｜{r[2]} {r[3]}"
            value = f"{r[0]}|{r[2]}|{r[3]}"
            options.append(discord.SelectOption(label=label, value=value))
        super().__init__(placeholder="キャンセルする予約を選択", options=options)

    async def callback(self, interaction: discord.Interaction):
        uid, date_str, time_str = self.values[0].split("|")
        ok = cancel_interview(interaction.guild.id, uid, date_str, time_str)
        if ok:
            await interaction.response.send_message(f"✅ キャンセル完了: {date_str} {time_str}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ キャンセル失敗", ephemeral=True)

class CancelView(View):
    def __init__(self, guild):
        super().__init__()
        self.add_item(CancelSelect(guild))

# ================= メインパネル =================
class MainPanel(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="予約", style=discord.ButtonStyle.green)
    async def reserve(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DateInputModal(interaction.guild))

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("キャンセルする予約を選択", view=CancelView(interaction.guild), ephemeral=True)

# ================= 通知 =================
notified_reserves = set()

@tasks.loop(minutes=1)
async def reminder_loop():
    now = datetime.now()
    for guild in bot.guilds:
        ch = get_notify_channel_obj(guild)
        if not ch:
            continue
        data = list_interviews(guild.id)
        for r in data:
            reserve_id = f"{guild.id}_{r[0]}_{r[2]}_{r[3]}"
            dt = datetime.strptime(r[2] + " " + r[3], "%Y-%m-%d %H:%M")
            if dt - timedelta(minutes=REMIND_BEFORE_MINUTES) <= now < dt:
                if reserve_id + "_before" not in notified_reserves:
                    await ch.send(f"🔔 面接{REMIND_BEFORE_MINUTES}分前 <@{r[0]}>")
                    notified_reserves.add(reserve_id + "_before")
            if dt <= now < dt + timedelta(minutes=1):
                if reserve_id + "_start" not in notified_reserves:
                    await ch.send(f"⏰ 面接開始 <@{r[0]}>")
                    notified_reserves.add(reserve_id + "_start")

# ================= 起動 =================
@bot.event
async def on_ready():
    print(f"起動完了: {bot.user}")
    await bot.change_presence(activity=discord.Game(name="面接管理中"))
    reminder_loop.start()

# ================= コマンド =================
@bot.command()
@commands.has_role(ADMIN_ROLE_NAME)
async def panel(ctx):
    await ctx.send("面接管理パネル", view=MainPanel())

@bot.command()
@commands.has_role(ADMIN_ROLE_NAME)
async def setnotify(ctx, channel: discord.TextChannel):
    set_notify_channel(ctx.guild.id, str(channel.id))
    await ctx.send(f"✅ 通知チャンネルを {channel.mention} に設定しました")

# ================= 起動 =================
TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)