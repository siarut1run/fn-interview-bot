import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# ================= Google Sheets 認証 =================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# Railway環境変数でJSONを読み込む場合
import os, json
creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
creds_dict = json.loads(creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# ================= サーバーID → シートID マップ =================
sheet_map = {}

def get_sheet(guild_id):
    """サーバーIDからシートオブジェクトを返す"""
    gid = str(guild_id)
    if gid not in sheet_map:
        # サーバー登録時に新規シート作成
        sheet = client.create(f"面接管理_{gid}")
        worksheet = sheet.sheet1
        # ヘッダー設定
        worksheet.append_row(["UserID", "Name", "Date", "Time"])
        sheet_map[gid] = sheet.id
    sheet = client.open_by_key(sheet_map[gid])
    return sheet.sheet1

# ================= 予約 =================
def save_interview(guild_id, user_id, name, date, time):
    ws = get_sheet(guild_id)
    ws.append_row([user_id, name, date, time])

# ================= キャンセル =================
def cancel_interview(guild_id, user_id, date=None, time=None):
    ws = get_sheet(guild_id)
    records = ws.get_all_values()
    for i, row in enumerate(records, start=1):
        if row[0] == str(user_id):
            if date and time:
                if row[2] == date and row[3] == time:
                    ws.delete_row(i)
                    return True
            else:
                ws.delete_row(i)
                return True
    return False

# ================= 一覧取得 =================
def list_interviews(guild_id):
    ws = get_sheet(guild_id)
    data = ws.get_all_values()
    return data[1:]  # ヘッダー除外

# ================= バッティングチェック =================
def is_time_conflict(guild_id, date, time):
    interviews = list_interviews(guild_id)
    for row in interviews:
        if row[2] == date and row[3] == time:
            return True
    return False

# ================= サーバー登録 =================
def register_guild(guild_id):
    """新しいサーバーが追加されたときに呼ぶ"""
    get_sheet(guild_id)  # get_sheet が自動で作成