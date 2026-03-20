import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Select, Modal, TextInput
from datetime import datetime, timedelta
import asyncio
import gspread
import json

# --- Config ---
TOKEN = "YOUR_DISCORD_BOT_TOKEN"
SERVICE_ACCOUNT_FILE = "service_account.json"
NOTIFY_MAP = {
    # guild_id: channel_id
}

intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- Google Sheets setup ---
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
client = gspread.authorize(creds)

with open("sheet_map.json", "r") as f:
    SHEET_MAP = json.load(f)

def get_sheet(guild_id):
    gid = str(guild_id)
    if gid in SHEET_MAP:
        return client.open_by_key(SHEET_MAP[gid])
    else:
        # ここで新規作成も可能
        sheet = client.create(f"面接管理_{gid}")
        SHEET_MAP[gid] = sheet.id
        with open("sheet_map.json", "w") as f:
            json.dump(SHEET_MAP, f)
        return sheet

def list_interviews(guild_id):
    sheet = get_sheet(guild_id).sheet1
    all_data = sheet.get_all_records()
    future_data = [d for d in all_data if datetime.strptime(d['date'] + ' ' + d['time'], "%Y-%m-%d %H:%M") > datetime.now()]
    return future_data

def add_interview(guild_id, date, time, member_name, member_id):
    sheet = get_sheet(guild_id).sheet1
    sheet.append_row([date, time, member_name, member_id])

def remove_interview(guild_id, member_id, date_str, time_str):
    sheet = get_sheet(guild_id).sheet1
    all_data = sheet.get_all_records()
    for i, row in enumerate(all_data, start=2):
        if row['member_id'] == member_id and row['date'] == date_str and row['time'] == time_str:
            sheet.delete_rows(i)
            return True
    return False

# --- Modal for date input ---
class DateInputModal(Modal):
    def __init__(self):
        super().__init__(title="予約日入力")
        self.date_input = TextInput(label="予約日 (YYYY-MM-DD)", placeholder="2026-03-21")
        self.add_item(self.date_input)

    async def on_submit(self, interaction: discord.Interaction):
        date_str = self.date_input.value
        await interaction.response.send_modal(TimeInputModal(interaction.guild, date_str))

# --- Modal for time input ---
class TimeInputModal(Modal):
    def __init__(self, guild, date_str):
        super().__init__(title="時間選択")
        self.guild = guild
        self.date_str = date_str

        # 午前/午後選択
        self.period = Select(
            placeholder="午前/午後",
            options=[discord.SelectOption(label="午前", value="AM"), discord.SelectOption(label="午後", value="PM")]
        )
        self.add_item(self.period)

        # 時選択
        hour_options = []
        for h in range(1, 13):
            hour_options.append(discord.SelectOption(label=str(h), value=str(h)))
        self.hour = Select(placeholder="時", options=hour_options)
        self.add_item(self.hour)

        # 分選択 10分刻み
        minute_options = []
        for m in range(0, 60, 10):
            minute_options.append(discord.SelectOption(label=f"{m:02}", value=f"{m:02}"))
        self.minute = Select(placeholder="分", options=minute_options)
        self.add_item(self.minute)

    async def on_submit(self, interaction: discord.Interaction):
        # 24時間表記に変換
        hour = int(self.hour.values[0])
        minute = int(self.minute.values[0])
        period = self.period.values[0]
        if period == "PM" and hour != 12:
            hour += 12
        elif period == "AM" and hour == 12:
            hour = 0
        time_str = f"{hour:02}:{minute:02}"

        # メンバー選択へ
        await interaction.response.send_message(
            "面接者を選択してください", view=MemberSelectView(self.guild, self.date_str, time_str), ephemeral=True
        )

# --- Member select view ---
class MemberSelectView(View):
    def __init__(self, guild, date_str, time_str):
        super().__init__(timeout=180)
        self.guild = guild
        self.date_str = date_str
        self.time_str = time_str
        options = []
        for m in guild.members:
            if not m.bot:
                options.append(discord.SelectOption(label=m.display_name, value=str(m.id)))
        self.member_select = Select(placeholder="面接者", options=options)
        self.member_select.callback = self.callback
        self.add_item(self.member_select)

    async def callback(self, interaction: discord.Interaction):
        member_id = int(self.member_select.values[0])
        member = self.guild.get_member(member_id)
        add_interview(self.guild.id, self.date_str, self.time_str, member.display_name, member.id)
        await interaction.followup.send(
            f"✅ 予約完了\n📅 {self.date_str}\n🕒 {self.time_str}\n👤 {member.mention}"
        )
        # 通知チャンネル
        notify_id = NOTIFY_MAP.get(str(self.guild.id))
        if notify_id:
            channel = self.guild.get_channel(notify_id)
            if channel:
                await channel.send(f"📌 新しい予約\n📅 {self.date_str}\n🕒 {self.time_str}\n👤 {member.mention}")

# --- Cancel view ---
class CancelView(View):
    def __init__(self, guild):
        super().__init__(timeout=180)
        future_reservations = list_interviews(guild.id)
        options = []
        used_values = set()
        for r in future_reservations:
            val = f"{r['member_id']}_{r['date']}_{r['time']}"
            if val not in used_values:
                used_values.add(val)
                label = f"{r['member_name']} {r['date']} {r['time']}"
                options.append(discord.SelectOption(label=label, value=val))
        if not options:
            options.append(discord.SelectOption(label="予約なし", value="none"))

        self.cancel_select = Select(placeholder="誰をキャンセルしますか？", options=options)
        self.cancel_select.callback = self.cancel_callback
        self.add_item(self.cancel_select)

    async def cancel_callback(self, interaction: discord.Interaction):
        if self.cancel_select.values[0] == "none":
            await interaction.response.send_message("キャンセルできる予約はありません", ephemeral=True)
            return
        member_id, date_str, time_str = self.cancel_select.values[0].split("_")
        remove_interview(self.cancel_select.guild.id, int(member_id), date_str, time_str)
        await interaction.response.send_message(f"キャンセル完了: {date_str} {time_str}", ephemeral=True)

# --- Main panel ---
class MainPanel(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(Button(label="予約", style=discord.ButtonStyle.success, callback=self.reserve))
        self.add_item(Button(label="キャンセル", style=discord.ButtonStyle.danger, callback=self.cancel))

    async def reserve(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DateInputModal())

    async def cancel(self, interaction: discord.Interaction):
        await interaction.response.send_message("キャンセルする予約を選んでください", view=CancelView(interaction.guild), ephemeral=True)

# --- Bot command ---
@bot.command()
async def panel(ctx):
    await ctx.send("面接管理パネル", view=MainPanel())

bot.run(TOKEN)