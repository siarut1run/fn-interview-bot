# bot.py
import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select
from datetime import datetime, timedelta
import os
from config import ADMIN_ROLE_NAME, REMIND_BEFORE_MINUTES
from sheets import save_interview, cancel_interview, list_interviews, is_time_conflict, set_notify_channel, get_notify_channel

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ===== 通知チャンネル取得 =====
def get_notify_channel_obj(guild):
    cid = get_notify_channel(guild.id)
    if cid:
        ch = guild.get_channel(int(cid))
        if ch:
            return ch
    return guild.system_channel

# ===== 日付入力モーダル =====
class DateInputModal(Modal):
    def __init__(self, guild):
        super().__init__(title="日付入力")
        self.guild = guild

        self.year = TextInput(label="年 (例: 2026)")
        self.month = TextInput(label="月 (例: 3)")
        self.day = TextInput(label="日 (例: 21)")

        self.add_item(self.year)
        self.add_item(self.month)
        self.add_item(self.day)

    async def on_submit(self, interaction: discord.Interaction):
        date_str = f"{self.year.value}-{int(self.month.value):02}-{int(self.day.value):02}"
        await interaction.response.send_modal(TimeInputModal(self.guild, date_str))

# ===== 時間入力モーダル =====
class TimeInputModal(Modal):
    def __init__(self, guild, date_str):
        super().__init__(title="時間入力")
        self.guild = guild
        self.date_str = date_str

        self.time = TextInput(label="時間 (HH:MM)", placeholder="例: 14:30", max_length=5)
        self.add_item(self.time)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "👤 面接者を選択してください",
            view=MemberView(self.guild, self.date_str, self.time.value),
            ephemeral=True
        )

# ===== 面接者選択 =====
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
        await interaction.response.defer(ephemeral=True)
        uid = self.values[0]
        member = self.guild.get_member(int(uid))

        if is_time_conflict(self.guild.id, self.date_str, self.time_str):
            await interaction.followup.send("❌ その時間は予約済み", ephemeral=True)
            return

        save_interview(self.guild.id, uid, member.display_name, self.date_str, self.time_str)

        notify_ch = get_notify_channel_obj(self.guild)
        if notify_ch:
            await notify_ch.send(f"✅ 予約完了\n📅 {self.date_str}\n🕒 {self.time_str}\n👤 {member.mention}")

        await interaction.followup.send("予約を完了しました ✅", ephemeral=True)

class MemberView(View):
    def __init__(self, guild, date_str, time_str):
        super().__init__(timeout=180)
        self.add_item(MemberSelect(guild, date_str, time_str))

# ===== キャンセル =====
class CancelModal(Modal, title="面接キャンセル"):
    user_id = TextInput(label="面接者Discord ID")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ok = cancel_interview(interaction.guild.id, str(self.user_id.value))
        if ok:
            await interaction.followup.send("✅ キャンセル完了", ephemeral=True)
        else:
            await interaction.followup.send("❌ 予約が見つかりません", ephemeral=True)

# ===== メインパネル =====
class MainPanel(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="予約", style=discord.ButtonStyle.green)
    async def reserve(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DateInputModal(interaction.guild))

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(CancelModal())

    @discord.ui.button(label="一覧", style=discord.ButtonStyle.blurple)
    async def show_list(self, interaction: discord.Interaction, button: Button):
        data = list_interviews(interaction.guild.id)
        if not data:
            msg = "予約はありません"
        else:
            msg = "\n".join([f"{r[1]}｜{r[2]} {r[3]}" for r in data])
        await interaction.response.send_message(msg, ephemeral=True)

# ===== リマインダー =====
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

# ===== 起動 =====
@bot.event
async def on_ready():
    print(f"起動完了: {bot.user}")
    await bot.change_presence(activity=discord.Game(name="面接管理中"))
    reminder_loop.start()

# ===== コマンド =====
@bot.command()
@commands.has_role(ADMIN_ROLE_NAME)
async def panel(ctx):
    await ctx.send("面接管理パネル", view=MainPanel())

@bot.command()
@commands.has_role(ADMIN_ROLE_NAME)
async def setnotify(ctx, channel: discord.TextChannel):
    set_notify_channel(ctx.guild.id, str(channel.id))
    await ctx.send(f"✅ 通知チャンネルを {channel.mention} に設定しました")

# ===== 起動 =====
TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)