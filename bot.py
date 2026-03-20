import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select
from datetime import datetime, timedelta
import os
import json

from config import ADMIN_ROLE_NAME, REMIND_BEFORE_MINUTES
from sheets import (
    save_interview,
    cancel_interview,
    list_interviews,
    is_time_conflict,
    get_sheet
)

# ================= BOT設定 =================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= 管理者チェック =================
def is_admin(member):
    return any(role.name == ADMIN_ROLE_NAME for role in member.roles)

# ================= 通知チャンネル管理 =================
def load_notify_map():
    return json.loads(os.getenv("NOTIFY_MAP", "{}"))

def save_notify_map(data):
    os.environ["NOTIFY_MAP"] = json.dumps(data)

notify_map = load_notify_map()

def get_notify_channel(guild):
    cid = notify_map.get(str(guild.id))
    if cid:
        ch = guild.get_channel(cid)
        if ch:
            return ch
    return guild.system_channel

# ================= 日付入力 =================
class DateInputModal(Modal, title="面接日入力"):
    year = TextInput(label="年 (例: 2026)")
    month = TextInput(label="月 (例: 3)")
    day = TextInput(label="日 (例: 21)")

    async def on_submit(self, interaction: discord.Interaction):
        date_str = f"{self.year.value}-{int(self.month.value):02}-{int(self.day.value):02}"
        await interaction.response.send_message(
            f"📅 日付: {date_str}\n午前/午後を選択",
            view=PeriodView(date_str),
            ephemeral=True
        )

# ================= 午前午後 =================
class PeriodView(View):
    def __init__(self, date_str):
        super().__init__(timeout=180)
        self.date_str = date_str

    @discord.ui.button(label="🌅 午前", style=discord.ButtonStyle.primary)
    async def am(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(
            "時間を入力してください (HH:MM)",
            view=TimeInputView(self.date_str),
            ephemeral=True
        )

    @discord.ui.button(label="🌇 午後", style=discord.ButtonStyle.success)
    async def pm(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(
            "時間を入力してください (HH:MM)",
            view=TimeInputView(self.date_str),
            ephemeral=True
        )

# ================= 時間入力 =================
class TimeInputModal(Modal, title="面接時間入力"):
    time = TextInput(label="時間 (HH:MM)")

    def __init__(self, date_str):
        super().__init__()
        self.date_str = date_str

    async def on_submit(self, interaction: discord.Interaction):
        time_str = self.time.value
        try:
            datetime.strptime(f"{self.date_str} {time_str}", "%Y-%m-%d %H:%M")
        except:
            await interaction.response.send_message("❌ 時間形式が不正です", ephemeral=True)
            return

        if is_time_conflict(interaction.guild.id, self.date_str, time_str):
            await interaction.response.send_message("❌ その時間は予約済み", ephemeral=True)
            return

        await interaction.response.send_message(
            "面接者を選択してください",
            view=MemberView(interaction.guild, self.date_str, time_str),
            ephemeral=True
        )

class TimeInputView(View):
    def __init__(self, date_str):
        super().__init__(timeout=180)
        self.date_str = date_str

    @discord.ui.button(label="入力", style=discord.ButtonStyle.primary)
    async def input_time(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(TimeInputModal(self.date_str))

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
        super().__init__(placeholder="面接者を選択", options=options)

    async def callback(self, interaction: discord.Interaction):
        uid = self.values[0]
        member = self.guild.get_member(int(uid))
        name = member.display_name if member else "Unknown"

        save_interview(self.guild.id, uid, name, self.date_str, self.time_str)

        # DM通知
        try:
            user = await bot.fetch_user(int(uid))
            await user.send(f"📅 面接予約されました\n日付: {self.date_str}\n時間: {self.time_str}")
        except: pass

        # 通知チャンネル通知
        ch = get_notify_channel(interaction.guild)
        if ch:
            await ch.send(f"✅ 新規予約 <@{uid}> {self.date_str} {self.time_str}")

        await interaction.response.send_message(
            f"✅ 予約完了\n📅 {self.date_str}\n🕒 {self.time_str}\n👤 <@{uid}>",
            ephemeral=True
        )

class MemberView(View):
    def __init__(self, guild, date_str, time_str):
        super().__init__(timeout=180)
        self.add_item(MemberSelect(guild, date_str, time_str))

# ================= キャンセル =================
class CancelButton(Button):
    def __init__(self, guild_id, user_id, date, time):
        super().__init__(label="❌", style=discord.ButtonStyle.red)
        self.guild_id = guild_id
        self.user_id = user_id
        self.date = date
        self.time = time

    async def callback(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 権限なし", ephemeral=True)
            return

        ok = cancel_interview(self.guild_id, self.user_id, self.date, self.time)
        if ok:
            await interaction.response.send_message("✅ キャンセル完了", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 失敗", ephemeral=True)

class ListView(View):
    def __init__(self, guild_id, data):
        super().__init__(timeout=180)
        for r in data[:10]:
            self.add_item(CancelButton(guild_id, r[0], r[2], r[3]))

# ================= メインパネル =================
class MainPanel(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="予約", style=discord.ButtonStyle.green)
    async def reserve(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 権限なし", ephemeral=True)
            return
        await interaction.response.send_modal(DateInputModal())

    @discord.ui.button(label="一覧", style=discord.ButtonStyle.blurple)
    async def show_list(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 権限なし", ephemeral=True)
            return
        data = list_interviews(interaction.guild.id)
        if not data:
            await interaction.response.send_message("予約なし", ephemeral=True)
            return
        msg = "\n".join([f"{i+1}. {r[1]}｜{r[2]} {r[3]}" for i, r in enumerate(data[:10])])
        await interaction.response.send_message(
            msg,
            view=ListView(interaction.guild.id, data),
            ephemeral=True
        )

# ================= 通知ループ =================
notified = set()

@tasks.loop(minutes=1)
async def reminder_loop():
    now = datetime.now()
    for guild in bot.guilds:
        ch = get_notify_channel(guild)
        if not ch:
            continue
        data = list_interviews(guild.id)
        for r in data:
            dt = datetime.strptime(r[2] + " " + r[3], "%Y-%m-%d %H:%M")
            key = f"{guild.id}_{r[0]}_{r[2]}_{r[3]}"
            if dt - timedelta(minutes=REMIND_BEFORE_MINUTES) <= now < dt:
                if key + "_before" not in notified:
                    await ch.send(f"🔔 {REMIND_BEFORE_MINUTES}分前 <@{r[0]}>")
                    try:
                        user = await bot.fetch_user(int(r[0]))
                        await user.send(f"🔔 面接まで{REMIND_BEFORE_MINUTES}分です {r[2]} {r[3]}")
                    except: pass
                    notified.add(key + "_before")
            if dt <= now < dt + timedelta(minutes=1):
                if key + "_start" not in notified:
                    await ch.send(f"⏰ 面接開始 <@{r[0]}>")
                    try:
                        user = await bot.fetch_user(int(r[0]))
                        await user.send(f"⏰ 面接開始です {r[2]} {r[3]}")
                    except: pass
                    notified.add(key + "_start")

# ================= コマンド =================
@bot.command()
@commands.has_role(ADMIN_ROLE_NAME)
async def panel(ctx):
    await ctx.send("📋 面接管理パネル", view=MainPanel())

@bot.command()
@commands.has_role(ADMIN_ROLE_NAME)
async def setnotify(ctx, channel: discord.TextChannel):
    notify_map[str(ctx.guild.id)] = channel.id
    await ctx.send(f"✅ 通知チャンネル設定: {channel.mention}")

# ================= 起動 =================
@bot.event
async def on_ready():
    print(f"起動完了: {bot.user}")
    reminder_loop.start()

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)