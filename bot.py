import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput
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

# ================= 日付入力 =================
class DateInputModal(Modal, title="日付入力"):
    year = TextInput(label="年 (例: 2026)")
    month = TextInput(label="月 (例: 3)")
    day = TextInput(label="日 (例: 21)")

    async def on_submit(self, interaction: discord.Interaction):
        date_str = f"{self.year.value}-{int(self.month.value):02}-{int(self.day.value):02}"
        await interaction.response.send_message(
            f"📅 日付: {date_str}\n時間を入力してください (例: 14:30)",
            view=TimeInputView(interaction.guild, date_str),
            ephemeral=True
        )

# ================= 時間入力 =================
class TimeInputView(View):
    def __init__(self, guild, date_str):
        super().__init__(timeout=180)
        self.guild = guild
        self.date_str = date_str
        self.time_input = TextInput(label="時間 (HH:MM)", placeholder="例: 14:30", max_length=5)
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction):
        time_str = self.time_input.value
        await interaction.response.send_message(
            "👤 面接者を選択してください",
            view=MemberView(self.guild, self.date_str, time_str),
            ephemeral=True
        )

# ================= 面接者選択 =================
class MemberSelect(discord.ui.Select):
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
        member = interaction.guild.get_member(int(uid))

        if is_time_conflict(interaction.guild.id, self.date_str, self.time_str):
            await interaction.followup.send("❌ その時間は予約済み", ephemeral=True)
            return

        save_interview(
            interaction.guild.id,
            uid,
            member.display_name,
            self.date_str,
            self.time_str
        )

        notify_ch = get_notify_channel_obj(interaction.guild)
        if notify_ch:
            await notify_ch.send(
                f"✅ 予約完了\n📅 {self.date_str}\n🕒 {self.time_str}\n👤 {member.mention}"
            )

        await interaction.followup.send("予約完了しました", ephemeral=True)

class MemberView(View):
    def __init__(self, guild, date_str, time_str):
        super().__init__(timeout=180)
        self.add_item(MemberSelect(guild, date_str, time_str))

# ================= キャンセル =================
class CancelModal(Modal, title="面接キャンセル"):
    user_id = TextInput(label="面接者Discord ID")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        ok = cancel_interview(interaction.guild.id, str(self.user_id.value))
        if ok:
            await interaction.followup.send("✅ キャンセル完了", ephemeral=True)
        else:
            await interaction.followup.send("❌ 予約が見つかりません", ephemeral=True)

# ================= メインパネル =================
class MainPanel(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="予約", style=discord.ButtonStyle.green)
    async def reserve(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DateInputModal())

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(CancelModal())

    @discord.ui.button(label="一覧", style=discord.ButtonStyle.blurple)
    async def show_list(self, interaction: discord.Interaction, button: Button):
        try:
            data = list_interviews(interaction.guild.id)
        except Exception as e:
            await interaction.response.send_message(f"[ERROR] {e}", ephemeral=True)
            return

        if not data:
            msg = "予約はありません"
        else:
            msg = "\n".join([f"{r[1]}｜{r[2]} {r[3]}" for r in data])
        await interaction.response.send_message(msg, ephemeral=True)

# ================= 通知 =================
notified_reserves = set()

@tasks.loop(minutes=1)
async def reminder_loop():
    now = datetime.now()
    for guild in bot.guilds:
        ch = get_notify_channel_obj(guild)
        if not ch:
            continue
        try:
            data = list_interviews(guild.id)
        except Exception as e:
            print(f"[ERROR] reminder_loop: {e}")
            continue

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
    reminder_loop.start()  # 🔥 これでリマインダー開始

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