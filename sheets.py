import gspread
import json
import os
from datetime import datetime

# ================= Google Sheets 接続 =================
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
client = gspread.service_account_from_dict(json.loads(GOOGLE_CREDENTIALS_JSON))

# ================= シート取得 =================
def get_sheet(guild_id):
    """
    サーバーごとのシートを取得
    """
    name = f"面接管理_{guild_id}"
    try:
        sheet = client.open(name).sheet1
        return sheet
    except gspread.SpreadsheetNotFound:
        raise Exception(f"シート {name} が見つかりません。事前に作成してサービスアカウントと共有してください")

# ================= 予約一覧 =================
def list_interviews(guild_id):
    """
    予約一覧を取得（ヘッダー除く）
    """
    try:
        sheet = get_sheet(guild_id)
        data = sheet.get_all_values()[1:]  # ヘッダーを除く
        return data
    except Exception as e:
        print(f"[ERROR] list_interviews: {e}")
        return []

# ================= 予約保存 =================
def save_interview(guild_id, user_id, user_name, date, time):
    """
    面接を保存
    """
    try:
        sheet = get_sheet(guild_id)
        sheet.append_row([user_id, user_name, date, time])
        print(f"✅ 面接予約保存: {user_id}, {user_name}, {date} {time}")
    except Exception as e:
        print(f"[ERROR] save_interview: {e}")

# ================= キャンセル =================

class CancelSelect(discord.ui.Select):
    def __init__(self, guild):
        self.guild = guild
        future_reserves = get_future_reservations(guild.id)

        options = []
        if future_reserves:
            for idx, r in enumerate(future_reserves[:25]):
                value = f"{r[0]}_{r[2]}_{r[3]}_{idx}"  # 一意化
                label = f"{r[1]}｜{r[2]} {r[3]}"
                options.append(discord.SelectOption(label=label, value=value))
        else:
            options = [discord.SelectOption(label="キャンセル可能な面接なし", value="none", default=True)]

        super().__init__(placeholder="キャンセルする面接者", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("❌ キャンセル可能な面接はありません", ephemeral=True)
            return

        uid = int(self.values[0].split("_")[0])

        # ================= 削除実行 =================
        result = cancel_interview(interaction.guild.id, uid)

        if not result:
            await interaction.response.send_message("⚠️ 削除に失敗しました", ephemeral=True)
            return

        # ================= 最新データで再生成 =================
        new_view = CancelView(interaction.guild)

        await interaction.response.send_message(
            f"❌ キャンセル完了: <@{uid}>\n\n👇 更新された一覧",
            view=new_view,
            ephemeral=True
        )


class CancelView(View):
    def __init__(self, guild):
        super().__init__(timeout=180)
        self.add_item(CancelSelect(guild))

# ================= 時間重複確認 =================
def is_time_conflict(guild_id, date, time):
    """
    同じ日時に面接が重複していないかチェック
    """
    try:
        data = list_interviews(guild_id)
        for r in data:
            if r[2] == date and r[3] == time:
                return True
        return False
    except Exception as e:
        print(f"[ERROR] is_time_conflict: {e}")
        return False

# ================= 通知チャンネル管理 =================
NOTIFY_MAP_FILE = "notify_map.json"

# ファイルがなければ作成
if not os.path.exists(NOTIFY_MAP_FILE):
    with open(NOTIFY_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f)

def set_notify_channel(guild_id, channel_id):
    try:
        with open(NOTIFY_MAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data[str(guild_id)] = str(channel_id)
        with open(NOTIFY_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
        print(f"✅ 通知チャンネル設定: guild_id={guild_id}, channel_id={channel_id}")
    except Exception as e:
        print(f"[ERROR] set_notify_channel: {e}")

def get_notify_channel(guild_id):
    try:
        with open(NOTIFY_MAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(str(guild_id))
    except Exception as e:
        print(f"[ERROR] get_notify_channel: {e}")
        return None
