import gspread
import json
import os
from datetime import datetime

# ================= Google Sheets 接続 =================
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
client = gspread.service_account_from_dict(json.loads(GOOGLE_CREDENTIALS_JSON))

# ================= シート取得 =================
def get_sheet(guild_id):
    name = f"面接管理_{guild_id}"
    try:
        return client.open(name).sheet1
    except gspread.SpreadsheetNotFound:
        raise Exception(f"シート {name} が見つかりません。事前に作成して共有してください")

# ================= 予約一覧 =================
def list_interviews(guild_id):
    try:
        sheet = get_sheet(guild_id)
        return sheet.get_all_values()[1:]
    except Exception as e:
        print(f"[ERROR] list_interviews: {e}")
        return []

# ================= 予約保存 =================
def save_interview(guild_id, user_id, user_name, date, time):
    try:
        sheet = get_sheet(guild_id)
        sheet.append_row([user_id, user_name, date, time])
        print(f"✅ 保存: {user_name} {date} {time}")
    except Exception as e:
        print(f"[ERROR] save_interview: {e}")

# ================= キャンセル（完全削除） =================
def cancel_interview(guild_id, user_id):
    try:
        sheet = get_sheet(guild_id)
        data = sheet.get_all_values()

        deleted = False

        # ヘッダー除外
        for i, row in enumerate(data[1:], start=2):
            if row[0] == str(user_id):
                sheet.delete_rows(i)
                print(f"✅ 削除: user_id={user_id} row={i}")
                deleted = True
                break

        if not deleted:
            print(f"[WARN] 見つからない: {user_id}")

        return deleted

    except Exception as e:
        print(f"[ERROR] cancel_interview: {e}")
        return False

# ================= 時間重複確認 =================
def is_time_conflict(guild_id, date, time):
    try:
        for r in list_interviews(guild_id):
            if r[2] == date and r[3] == time:
                return True
        return False
    except Exception as e:
        print(f"[ERROR] is_time_conflict: {e}")
        return False

# ================= 通知チャンネル管理 =================
NOTIFY_MAP_FILE = "notify_map.json"

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
