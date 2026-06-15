import os
import json
import requests
import base64
from datetime import datetime
from flask import Flask, request, abort, render_template_string
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest,
    TextMessage, QuickReply, QuickReplyItem,
    MessageAction, FlexMessage, FlexContainer, ImageMessage
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent, ImageMessageContent
)
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("CHANNEL_SECRET")
GROUP_ID = os.environ.get("GROUP_ID")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
user_state = {}

LOCATIONS = [
    "ห้องนักกาย", "ห้องแต่งปูนคลินิค", "ห้องเครื่องจักรคลินิค",
    "ห้องขึ้นรูปขาเทียมโรงเรียน", "ห้องขึ้นรูปขาเทียมคลินิค", "ห้องช่างรวม",
    "ห้องเครื่องจักรโรงเรียน", "ห้องเครื่องจักรCEPO", "ห้องแต่งปูนCEPO"
]

# ========== GOOGLE SHEETS ==========
def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

def get_users():
    try:
        sh = get_sheet()
        ws = sh.worksheet("Users")
        rows = ws.get_all_records()
        return {r["user_id"]: r["name"] for r in rows if r.get("user_id")}
    except:
        return {}

def save_user(user_id, name):
    try:
        sh = get_sheet()
        ws = sh.worksheet("Users")
        users = get_users()
        if user_id not in users:
            ws.append_row([user_id, name, datetime.now().strftime("%d/%m/%Y %H:%M")])
        else:
            # อัปเดตชื่อถ้าเปลี่ยน
            cell = ws.find(user_id)
            if cell:
                ws.update_cell(cell.row, 2, name)
    except Exception as e:
        print(f"save_user error: {e}")

def add_star(giver_id, giver_name, receiver_id, receiver_name):
    try:
        sh = get_sheet()
        ws = sh.worksheet("Stars")
        ws.append_row([
            giver_id, giver_name, receiver_id, receiver_name,
            datetime.now().strftime("%d/%m/%Y %H:%M")
        ])
        # นับดาวของ receiver
        all_rows = ws.get_all_records()
        count = sum(1 for r in all_rows if r.get("receiver_id") == receiver_id)
        return count
    except Exception as e:
        print(f"add_star error: {e}")
        return 0

def add_report(report_type, location, reporter_name):
    try:
        sh = get_sheet()
        ws = sh.worksheet("Reports")
        ws.append_row([
            datetime.now().strftime("%d/%m/%Y %H:%M"),
            report_type, location, reporter_name
        ])
    except Exception as e:
        print(f"add_report error: {e}")

def get_leaderboard():
    try:
        sh = get_sheet()
        ws = sh.worksheet("Stars")
        rows = ws.get_all_records()
        counts = {}
        for r in rows:
            rid = r.get("receiver_id", "")
            rname = r.get("receiver_name", "")
            if rid:
                counts[rid] = {"name": rname, "count": counts.get(rid, {}).get("count", 0) + 1}
        return sorted(counts.items(), key=lambda x: x[1]["count"], reverse=True)[:10]
    except Exception as e:
        print(f"get_leaderboard error: {e}")
        return []

def get_recent_reports(n=20):
    try:
        sh = get_sheet()
        ws = sh.worksheet("Reports")
        rows = ws.get_all_records()
        return list(reversed(rows[-n:]))
    except:
        return []

def get_stats():
    try:
        sh = get_sheet()
        r_count = len(sh.worksheet("Reports").get_all_records())
        s_rows = sh.worksheet("Stars").get_all_records()
        s_count = len(s_rows)
        u_count = len(sh.worksheet("Users").get_all_records())
        return r_count, s_count, u_count
    except:
        return 0, 0, 0

def init_sheets():
    """สร้าง header ถ้ายังไม่มี"""
    try:
        sh = get_sheet()
        try:
            ws = sh.worksheet("Users")
            if not ws.row_values(1):
                ws.append_row(["user_id", "name", "joined"])
        except:
            pass
        try:
            ws = sh.worksheet("Stars")
            if not ws.row_values(1):
                ws.append_row(["giver_id", "giver_name", "receiver_id", "receiver_name", "time"])
        except:
            pass
        try:
            ws = sh.worksheet("Reports")
            if not ws.row_values(1):
                ws.append_row(["time", "type", "location", "reporter"])
        except:
            pass
    except Exception as e:
        print(f"init_sheets error: {e}")

# ========== LINE API ==========
def get_messaging_api():
    return MessagingApi(ApiClient(configuration))

def get_user_profile(user_id):
    try:
        api = get_messaging_api()
        profile = api.get_profile(user_id)
        return profile.display_name
    except:
        return "ไม่ทราบชื่อ"

# ========== MESSAGES ==========
def send_main_menu(reply_token):
    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(
            text="🦺 SSPO Safety Buddy\n\nเลือกสิ่งที่ต้องการ:",
            quick_reply=QuickReply(items=[
                QuickReplyItem(action=MessageAction(label="🚨 รายงาน PPE", text="report")),
                QuickReplyItem(action=MessageAction(label="⭐ ให้ดาว", text="ให้ดาว")),
                QuickReplyItem(action=MessageAction(label="📊 Dashboard", text="dashboard")),
            ])
        )]
    ))

def send_location_menu(reply_token):
    items = [QuickReplyItem(action=MessageAction(label=loc[:20], text="📍 " + loc)) for loc in LOCATIONS]
    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(
            text="📍 เลือกบริเวณที่พบ:",
            quick_reply=QuickReply(items=items)
        )]
    ))

def send_star_menu(reply_token, giver_id):
    users = get_users()
    items = []
    for uid, name in users.items():
        if uid != giver_id:
            items.append(QuickReplyItem(
                action=MessageAction(
                    label=name[:20],
                    text="⭐ ให้ดาว:" + uid + ":" + name
                )
            ))
    if not items:
        api = get_messaging_api()
        api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text="ยังไม่มีสมาชิกในระบบครับ\nให้เพื่อนๆ แชทกับบอทก่อนสักครั้งครับ 🙏")]
        ))
        return
    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(
            text="⭐ เลือกคนที่อยากให้ดาว\n(ใส่ PPE ครบ / ทำงานปลอดภัย):",
            quick_reply=QuickReply(items=items[:13])
        )]
    ))

def send_dashboard_to_group():
    leaderboard = get_leaderboard()
    total_reports, total_stars, total_users = get_stats()
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    lb_rows = []
    for i, (uid, data) in enumerate(leaderboard[:5]):
        icon = medal[i] if i < len(medal) else str(i+1) + "."
        lb_rows.append({
            "type": "box", "layout": "horizontal",
            "contents": [
                {"type": "text", "text": icon + " " + data["name"], "size": "sm", "flex": 4, "wrap": True},
                {"type": "text", "text": "⭐ " + str(data["count"]), "size": "sm", "flex": 2, "align": "end", "color": "#FF8C00", "weight": "bold"}
            ]
        })

    body_contents = [
        {
            "type": "box", "layout": "horizontal", "spacing": "md",
            "contents": [
                {
                    "type": "box", "layout": "vertical", "flex": 1,
                    "backgroundColor": "#FFF3E0", "cornerRadius": "8px", "paddingAll": "10px",
                    "contents": [
                        {"type": "text", "text": "🚨", "align": "center", "size": "xl"},
                        {"type": "text", "text": str(total_reports), "align": "center", "size": "xxl", "weight": "bold", "color": "#FF0000"},
                        {"type": "text", "text": "รายงาน", "align": "center", "size": "xs", "color": "#888888"}
                    ]
                },
                {
                    "type": "box", "layout": "vertical", "flex": 1,
                    "backgroundColor": "#FFF8E1", "cornerRadius": "8px", "paddingAll": "10px",
                    "contents": [
                        {"type": "text", "text": "⭐", "align": "center", "size": "xl"},
                        {"type": "text", "text": str(total_stars), "align": "center", "size": "xxl", "weight": "bold", "color": "#FF8C00"},
                        {"type": "text", "text": "ดาวรวม", "align": "center", "size": "xs", "color": "#888888"}
                    ]
                },
                {
                    "type": "box", "layout": "vertical", "flex": 1,
                    "backgroundColor": "#E8F5E9", "cornerRadius": "8px", "paddingAll": "10px",
                    "contents": [
                        {"type": "text", "text": "👷", "align": "center", "size": "xl"},
                        {"type": "text", "text": str(total_users), "align": "center", "size": "xxl", "weight": "bold", "color": "#00897B"},
                        {"type": "text", "text": "ผู้ใช้", "align": "center", "size": "xs", "color": "#888888"}
                    ]
                }
            ]
        },
        {"type": "separator"}
    ]

    if lb_rows:
        body_contents.append({"type": "text", "text": "🏆 Top ดาวสูงสุด", "weight": "bold", "size": "md"})
        body_contents.extend(lb_rows)
    else:
        body_contents.append({"type": "text", "text": "ยังไม่มีข้อมูลดาว", "color": "#888888", "size": "sm"})

    flex_content = {
        "type": "bubble", "size": "mega",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": "#00897B", "paddingAll": "15px",
            "contents": [
                {"type": "text", "text": "📊 Safety Dashboard", "weight": "bold", "size": "xl", "color": "#FFFFFF"},
                {"type": "text", "text": now, "size": "xs", "color": "#CCEEEC"}
            ]
        },
        "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": body_contents},
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [{"type": "text", "text": "SSPO Safety Buddy System", "size": "xs", "color": "#888888", "align": "center"}]
        }
    }

    api = get_messaging_api()
    api.push_message(PushMessageRequest(
        to=GROUP_ID,
        messages=[FlexMessage(alt_text="📊 Safety Dashboard", contents=FlexContainer.from_dict(flex_content))]
    ))

def get_image_content(message_id):
    url = "https://api-data.line.me/v2/bot/message/" + message_id + "/content"
    headers = {"Authorization": "Bearer " + CHANNEL_ACCESS_TOKEN}
    return requests.get(url, headers=headers).content

def upload_to_imgur(image_content):
    try:
        headers = {"Authorization": "Client-ID 546c25a59c58ad7"}
        b64 = base64.b64encode(image_content).decode("utf-8")
        r = requests.post("https://api.imgur.com/3/image", headers=headers, json={"image": b64, "type": "base64"})
        if r.status_code == 200:
            return r.json()["data"]["link"]
    except:
        pass
    return None

def send_alert_to_group(message_id, location, reporter_name):
    now = datetime.now().strftime("%d/%m/%Y %H:%M น.")
    add_report("🦺 ไม่ใส่ PPE", location, reporter_name)
    image_content = get_image_content(message_id)
    public_image_url = upload_to_imgur(image_content)

    api = get_messaging_api()
    if public_image_url:
        flex_content = {
            "type": "bubble", "size": "mega",
            "header": {
                "type": "box", "layout": "vertical",
                "backgroundColor": "#FF0000", "paddingAll": "15px",
                "contents": [{"type": "text", "text": "⚠️ SAFETY ALERT", "weight": "bold", "size": "xl", "color": "#FFFFFF"}]
            },
            "hero": {"type": "image", "url": public_image_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
            "body": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "พบ 🦺 ไม่ใส่ PPE", "weight": "bold", "size": "lg", "color": "#FF0000", "wrap": True},
                    {"type": "text", "text": "กรุณาแก้ไขด่วน!", "size": "md", "color": "#333333", "margin": "sm"},
                    {"type": "separator", "margin": "md"},
                    {
                        "type": "box", "layout": "vertical", "margin": "md", "spacing": "sm",
                        "contents": [
                            {"type": "box", "layout": "horizontal", "contents": [
                                {"type": "text", "text": "📍 บริเวณ", "size": "sm", "color": "#888888", "flex": 3},
                                {"type": "text", "text": location, "size": "sm", "color": "#333333", "flex": 5, "wrap": True}
                            ]},
                            {"type": "box", "layout": "horizontal", "contents": [
                                {"type": "text", "text": "🕐 เวลา", "size": "sm", "color": "#888888", "flex": 3},
                                {"type": "text", "text": now, "size": "sm", "color": "#333333", "flex": 5}
                            ]}
                        ]
                    }
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical",
                "contents": [{"type": "text", "text": "SSPO Safety Buddy System", "size": "xs", "color": "#888888", "align": "center"}]
            }
        }
        api.push_message(PushMessageRequest(
            to=GROUP_ID,
            messages=[FlexMessage(alt_text="⚠️ พบไม่ใส่ PPE บริเวณ " + location, contents=FlexContainer.from_dict(flex_content))]
        ))
    else:
        api.push_message(PushMessageRequest(
            to=GROUP_ID,
            messages=[TextMessage(text="⚠️ SAFETY ALERT\nพบไม่ใส่ PPE\n📍 " + location + "\n🕐 " + now)]
        ))

# ========== DASHBOARD WEB ==========
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SSPO Safety Dashboard</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: 'Segoe UI', sans-serif; background: #f0f4f8; margin: 0; padding: 16px; }
  h1 { color: #00897B; text-align: center; font-size: 22px; margin-bottom: 16px; }
  .cards { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; margin-bottom: 20px; }
  .card { background: white; border-radius: 12px; padding: 16px 20px; text-align: center; min-width: 100px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
  .card .num { font-size: 36px; font-weight: bold; }
  .card .label { color: #888; font-size: 12px; margin-top: 4px; }
  table { width: 100%; max-width: 640px; margin: 0 auto 24px; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08); border-collapse: collapse; }
  th { background: #00897B; color: white; padding: 10px 14px; text-align: left; font-size: 14px; }
  td { padding: 10px 14px; border-bottom: 1px solid #f0f0f0; font-size: 13px; }
  tr:last-child td { border-bottom: none; }
  h2 { text-align: center; color: #333; margin: 20px 0 10px; font-size: 16px; }
  .empty { text-align: center; color: #aaa; padding: 20px; }
  footer { text-align: center; color: #bbb; font-size: 11px; margin-top: 24px; }
</style>
</head>
<body>
<h1>🦺 SSPO Safety Dashboard</h1>
<div class="cards">
  <div class="card"><div class="num" style="color:#FF0000">{{ total_reports }}</div><div class="label">🚨 รายงาน</div></div>
  <div class="card"><div class="num" style="color:#FF8C00">{{ total_stars }}</div><div class="label">⭐ ดาวรวม</div></div>
  <div class="card"><div class="num" style="color:#00897B">{{ total_users }}</div><div class="label">👷 ผู้ใช้</div></div>
</div>

<h2>🏆 อันดับดาว</h2>
<table>
  <tr><th>อันดับ</th><th>ชื่อ</th><th>ดาว</th></tr>
  {% for i, uid, data in leaderboard %}
  <tr>
    <td>{% if i==0 %}🥇{% elif i==1 %}🥈{% elif i==2 %}🥉{% else %}{{ i+1 }}{% endif %}</td>
    <td>{{ data.name }}</td>
    <td style="color:#FF8C00;font-weight:bold">⭐ {{ data.count }}</td>
  </tr>
  {% endfor %}
  {% if not leaderboard %}<tr><td colspan="3" class="empty">ยังไม่มีข้อมูล</td></tr>{% endif %}
</table>

<h2>📋 รายงานล่าสุด</h2>
<table>
  <tr><th>เวลา</th><th>บริเวณ</th></tr>
  {% for r in reports %}
  <tr>
    <td style="color:#888">{{ r.time }}</td>
    <td style="color:#FF0000">{{ r.location }}</td>
  </tr>
  {% endfor %}
  {% if not reports %}<tr><td colspan="2" class="empty">ยังไม่มีข้อมูล</td></tr>{% endif %}
</table>
<footer>SSPO Safety Buddy • อัปเดต {{ now }}</footer>
</body>
</html>
"""

@app.route("/dashboard")
def dashboard():
    leaderboard = [(i, uid, data) for i, (uid, data) in enumerate(get_leaderboard())]
    reports = get_recent_reports(20)
    total_reports, total_stars, total_users = get_stats()
    now = datetime.now().strftime("%d/%m/%Y %H:%M น.")
    return render_template_string(DASHBOARD_HTML,
        leaderboard=leaderboard, reports=reports,
        total_reports=total_reports, total_stars=total_stars,
        total_users=total_users, now=now)

@app.route("/health")
def health():
    return {"status": "ok"}, 200

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# ========== HANDLERS ==========
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    if event.source.type == "group":
        if event.message.text.strip().lower() == "/dashboard":
            send_dashboard_to_group()
        return

    user_id = event.source.user_id
    text = event.message.text.strip()
    name = get_user_profile(user_id)
    save_user(user_id, name)

    # ให้ดาว
    if text.startswith("⭐ ให้ดาว:"):
        parts = text.split(":")
        if len(parts) >= 3:
            receiver_id = parts[1]
            receiver_name = parts[2]
            total = add_star(user_id, name, receiver_id, receiver_name)
            api = get_messaging_api()
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="✅ ให้ดาว " + receiver_name + " สำเร็จ!\n" + receiver_name + " มีดาวทั้งหมด ⭐ " + str(total) + " ดาว")]
            ))
            api.push_message(PushMessageRequest(
                to=GROUP_ID,
                messages=[TextMessage(text="⭐ " + name + " ให้ดาวแก่ " + receiver_name + "\nเพราะใส่ PPE ครบ! " + receiver_name + " มี " + str(total) + " ดาว 🎉")]
            ))
        return

    # เลือกบริเวณ
    if text.startswith("📍 "):
        location = text[3:]
        if user_id in user_state and user_state[user_id].get("waiting") == "location":
            user_state[user_id] = {"waiting": "image", "location": location}
            api = get_messaging_api()
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="📸 กรุณาส่งรูปภาพเหตุการณ์ที่บริเวณ " + location)]
            ))
        return

    if text.lower() in ["report", "แจ้ง", "🚨"]:
        user_state[user_id] = {"waiting": "location"}
        send_location_menu(event.reply_token)
        return

    if text in ["ให้ดาว", "⭐ ให้ดาว", "star", "rewards"]:
        send_star_menu(event.reply_token, user_id)
        return

    if text.lower() in ["dashboard", "/dashboard", "สรุป"]:
        url = os.environ.get("RENDER_EXTERNAL_URL", "https://sspo-safety-buddy.onrender.com")
        api = get_messaging_api()
        api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text="📊 ดู Dashboard ได้ที่:\n" + url + "/dashboard")]
        ))
        return

    send_main_menu(event.reply_token)


@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    if event.source.type == "group":
        return

    user_id = event.source.user_id
    name = get_user_profile(user_id)

    if user_id not in user_state or user_state[user_id].get("waiting") != "image":
        api = get_messaging_api()
        api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text="กรุณาพิมพ์ 'report' ก่อนส่งรูปครับ 🙏")]
        ))
        return

    location = user_state[user_id].get("location", "ไม่ระบุ")
    send_alert_to_group(event.message.id, location, name)

    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=event.reply_token,
        messages=[TextMessage(text="✅ รายงานสำเร็จ!\n📍 บริเวณ: " + location + "\nทีม Safety ได้รับแจ้งแล้วครับ 🙏")]
    ))
    user_state.pop(user_id, None)


# Init sheets on startup
with app.app_context():
    try:
        init_sheets()
    except Exception as e:
        print(f"init error: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
