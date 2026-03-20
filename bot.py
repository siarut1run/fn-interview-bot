import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Select
from datetime import datetime, timedelta
import os

from config import ADMIN_ROLE_NAME, REMIND_BEFORE_MINUTES
from sheets import save_interview, cancel_interview, list_interviews, set_notify_channel, get_notify_channel

# ================= BOT設定 =================

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

# ================= 面接予約 =================

class DateInputModal(discord.ui.Modal, title="面接日選択"):
    year = discord.ui.TextInput(label="年 (例: 2026)")
    month = discord.ui.TextInput(label="月 (例: 3)")
    day = discord.ui.TextInput(label="日 (例: 21)")

    def __init__(self, guild):
        super().__init__()
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        date_str = f"{self.year.value}-{int(self.month.value):02}-{int(self.day.value):02}"
        await interaction.response.send_message(
            f"📅 日付: {date_str}\n時間を選択してください",
            view=TimeView(self.guild, date_str),
            ephemeral=True
        )

# ================= 時間選択 =================

class HourSelect(discord.ui.Select):
    def __init__(self, date_str, guild):
        self.date_str = date_str
        self.guild = guild
        options = [discord.SelectOption(label=f"{h:02}", value=f"{h:02}") for h in range(0,24)]
        super().__init__(placeholder="時間", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "分を選択してください", view=MinuteView(self.guild, self.date_str, self.values[0]), ephemeral=True
        )

class MinuteSelect(discord.ui.Select):
    def __init__(self, date_str, hour_str, guild):
        self.date_str = date_str
        self.hour_str = hour_str
        self.guild = guild
        options = [discord.SelectOption(label=f"{m:02}", value=f"{m:02}") for m in range(0, 60, 10)]
        super().__init__(placeholder="分", options=options)

    async def callback(self, interaction: discord.Interaction):
        minute_str = self.values[0]
        time_str = f"{self.hour_str}:{minute_str}"
        members = [m for m in self.guild.members if not m.bot]
        await interaction.response.send_message(
            "面接者を選択してください", view=MemberView(self.guild, self.date_str, time_str, members), ephemeral=True
        )

class TimeView(View):
    def __init__(self, guild, date_str):
        super().__init__(timeout=180)
        self.add_item(HourSelect(date_str, guild))

class MinuteView(View):
    def __init__(self, guild, date_str, hour_str):
        super().__init__(timeout=180)
        self.add_item(MinuteSelect(date_str, hour_str, guild))

# ================= 面接者選択 =================

class MemberSelect(discord.ui.Select):
    def __init__(self, guild, date_str, time_str, members):
        self.guild = guild
        self.date_str = date_str
        self.time_str = time_str
        self.guild = guild
        options = [discord.SelectOption(label=m.display_name, value=str(m.id)) for m in members[:25]]
        super().__init__(placeholder="面接者", options=options)

    async def callback(self, interaction: discord.Interaction):
        uid = int(self.values[0])
        member = interaction.guild.get_member(uid)
        save_interview(interaction.guild.id, str(uid), member.display_name, self.date_str, self.time_str)

        # ✅ 修正: followup ではなく response.send_message を使う
        await interaction.response.send_message(
            f"✅ 予約完了\n📅 {self.date_str}\n🕒 {self.time_str}\n👤 {member.mention}",
            ephemeral=True
        )

class MemberView(View):
    def __init__(self, guild, date_str, time_str, members):
        super().__init__(timeout=180)
        self.add_item(MemberSelect(guild, date_str, time_str, members))

# ================= キャンセル =================

class CancelSelect(discord.ui.Select):
    def __init__(self, guild):
        self.guild = guild
        # 今後の面接のみ取得
        future_reserves = [
            r for r in list_interviews(guild.id)
            if datetime.strptime(r[2] + " " + r[3], "%Y-%m-%d %H:%M") >= datetime.now()
        ]
        # 選択肢を作成、ない場合はダミー選択肢
        if future_reserves:
            options = [
                discord.SelectOption(label=f"{r[1]}｜{r[2]} {r[3]}", value=str(r[0]))
                for r in future_reserves[:25]
            ]
        else:
            options = [discord.SelectOption(label="キャンセル可能な面接なし", value="none", default=True)]
        super().__init__(placeholder="キャンセルする面接者", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("❌ キャンセル可能な面接はありません", ephemeral=True)
            return

        uid = self.values[0]
        cancel_interview(interaction.guild.id, uid)
        await interaction.response.send_message(f"❌ キャンセル完了: <@{uid}>", ephemeral=True)

class CancelView(View):
    def __init__(self, guild):
        super().__init__(timeout=180)
        self.add_item(CancelSelect(guild))

# ================= メインパネル =================

class MainPanel(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="予約", style=discord.ButtonStyle.green)
    async def reserve(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(DateInputModal(interaction.guild))

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button):
        await interaction.response.send_message(
            "誰をキャンセルしますか？", view=CancelView(interaction.guild), ephemeral=True
        )

    @discord.ui.button(label="一覧", style=discord.ButtonStyle.blurple)
    async def show_list(self, interaction: discord.Interaction, button):
        future_reserves = [
            r for r in list_interviews(interaction.guild.id)
            if datetime.strptime(r[2] + " " + r[3], "%Y-%m-%d %H:%M") >= datetime.now()
        ]
        if not future_reserves:
            msg = "予約はありません"
        else:
            msg = "\n".join([f"{r[1]}｜{r[2]} {r[3]}" for r in future_reserves])
        await interaction.response.send_message(msg, ephemeral=True)

# ================= 通知ループ =================

notified_reserves = set()

@tasks.loop(minutes=1)
async def reminder_loop():
    now = datetime.now()
    for guild in bot.guilds:
        ch = get_notify_channel_obj(guild)
        if not ch:
            continue

        for r in list_interviews(guild.id):
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
