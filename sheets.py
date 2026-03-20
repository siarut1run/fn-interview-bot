import gspread
import json
import os
from datetime import datetime

# 環境変数からサービスアカウントJSON読み込み
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
client = gspread.service_account_from_dict(json.loads(GOOGLE_CREDENTIALS_JSON))

# サーバーごとのシート名
def get_sheet(guild_id):
    name = f"面接管理_{guild_id}"
    try:
        # 既存シートを開く
        sheet = client.open(name).sheet1
    except gspread.SpreadsheetNotFound:
        # 新規作成をやめて例外にする
        raise Exception(f"シート {name} が見つかりません。事前に作成してサービスアカウントと共有してください")
    return sheet

# 予約一覧取得
def list_interviews(guild_id):
    try:
        sheet = get_sheet(guild_id)
        data = sheet.get_all_values()[1:]  # ヘッダー除く
        return data
    except Exception as e:
        print(f"[ERROR] list_interviews: {e}")
        return []

# 予約保存
def save_interview(guild_id, user_id, user_name, date, time):
    sheet = get_sheet(guild_id)
    sheet.append_row([user_id, user_name, date, time])

# キャンセル
def cancel_interview(guild_id, user_id):
    sheet = get_guild_sheet(guild_id)  # 既存コード
    data = sheet.get_all_values()
    
    for i, row in enumerate(data, start=1):
        if row[0] == str(user_id):
            sheet.delete_rows(i)  # ← delete_row → delete_rows に変更
            break
    return False

# 時間重複確認
def is_time_conflict(guild_id, date, time):
    data = list_interviews(guild_id)
    for r in data:
        if r[2] == date and r[3] == time:
            return True
    return False

# 通知チャンネル管理（JSONで保持）
NOTIFY_MAP_FILE = "notify_map.json"
if not os.path.exists(NOTIFY_MAP_FILE):
    with open(NOTIFY_MAP_FILE, "w", encoding="utf-8") as f:
        f.write("{}")

def set_notify_channel(guild_id, channel_id):
    import json
    with open(NOTIFY_MAP_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data[str(guild_id)] = channel_id
    with open(NOTIFY_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)

def get_notify_channel(guild_id):
    import json
    with open(NOTIFY_MAP_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get(str(guild_id))
