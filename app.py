import os
import json
import requests
import base64
from datetime import datetime, timezone, timedelta
from flask import Flask, request, abort, render_template_string
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest,
    TextMessage, QuickReply, QuickReplyItem,
    MessageAction, FlexMessage, FlexContainer
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
    "ห้องนักกาย", "ห้องแต่งปูนคลินิก", "ห้องเครื่องจักรคลินิก",
    "ห้องขึ้นรูปขาเทียมโรงเรียน", "ห้องขึ้นรูปขาเทียมคลินิก", "ห้องช่างรวม",
    "ห้องเครื่องจักรโรงเรียน", "ห้องเครื่องจักรCEPO", "ห้องแต่งปูนCEPO", "บริเวณอื่นๆ"
]

def now_bkk():
    return datetime.now(timezone(timedelta(hours=7)))

# ========== GOOGLE SHEETS ==========
def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

def get_users():
    try:
        ws = get_sheet().worksheet("Users")
        rows = ws.get_all_records()
        return {r["user_id"]: r["name"] for r in rows if r.get("user_id")}
    except Exception as e:
        print(f"get_users error: {e}")
        return {}

def save_user(user_id, name):
    try:
        ws = get_sheet().worksheet("Users")
        users = get_users()
        if user_id not in users:
            ws.append_row([user_id, name, now_bkk().strftime("%d/%m/%Y %H:%M")])
        else:
            rows = ws.get_all_records()
            for i, r in enumerate(rows, 2):
                if r.get("user_id") == user_id and r.get("name") != name:
                    ws.update_cell(i, 2, name)
                    break
    except Exception as e:
        print(f"save_user error: {e}")

def search_users(keyword):
    users = get_users()
    keyword = keyword.strip().lower()
    return [(uid, name) for uid, name in users.items() if keyword in name.lower()]

def add_star(giver_id, giver_name, receiver_id, receiver_name):
    try:
        ws = get_sheet().worksheet("Stars")
        ws.append_row([giver_id, giver_name, receiver_id, receiver_name,
                       now_bkk().strftime("%d/%m/%Y %H:%M")])
        rows = ws.get_all_records()
        return sum(1 for r in rows if r.get("receiver_id") == receiver_id)
    except Exception as e:
        print(f"add_star error: {e}")
        return 0

def add_report(location, reporter_name):
    try:
        ws = get_sheet().worksheet("Reports")
        ws.append_row([now_bkk().strftime("%d/%m/%Y %H:%M"),
                       "🦺 ไม่ใส่ PPE", location, reporter_name])
    except Exception as e:
        print(f"add_report error: {e}")

def get_leaderboard():
    try:
        rows = get_sheet().worksheet("Stars").get_all_records()
        counts = {}
        for r in rows:
            rid, rname = r.get("receiver_id",""), r.get("receiver_name","")
            if rid:
                if rid not in counts:
                    counts[rid] = {"name": rname, "count": 0}
                counts[rid]["count"] += 1
        return sorted(counts.items(), key=lambda x: x[1]["count"], reverse=True)[:10]
    except Exception as e:
        print(f"get_leaderboard error: {e}")
        return []

def get_recent_reports(n=20):
    try:
        rows = get_sheet().worksheet("Reports").get_all_records()
        return list(reversed(rows[-n:]))
    except:
        return []

def get_stats():
    try:
        sh = get_sheet()
        r = len(sh.worksheet("Reports").get_all_records())
        s = len(sh.worksheet("Stars").get_all_records())
        u = len(sh.worksheet("Users").get_all_records())
        return r, s, u
    except:
        return 0, 0, 0

def init_sheets():
    try:
        sh = get_sheet()
        for name, headers in [
            ("Users", ["user_id","name","joined"]),
            ("Stars", ["giver_id","giver_name","receiver_id","receiver_name","time"]),
            ("Reports", ["time","type","location","reporter"])
        ]:
            ws = sh.worksheet(name)
            if not ws.row_values(1):
                ws.append_row(headers)
    except Exception as e:
        print(f"init_sheets error: {e}")

# ========== LINE API ==========
def get_messaging_api():
    return MessagingApi(ApiClient(configuration))

def get_user_profile(user_id):
    try:
        return get_messaging_api().get_profile(user_id).display_name
    except:
        return "ไม่ทราบชื่อ"

# ========== MESSAGES ==========
def send_main_menu(reply_token):
    get_messaging_api().reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(
            text="🦺 SSPO Safety Buddy 🦺\nกรุณาเลือกสิ่งที่ต้องการ:",
            quick_reply=QuickReply(items=[
                QuickReplyItem(action=MessageAction(label="🚨 รายงาน PPE", text="report")),
                QuickReplyItem(action=MessageAction(label="⭐ ให้ดาว", text="ให้ดาว")),
                QuickReplyItem(action=MessageAction(label="📊 Dashboard", text="dashboard")),
            ])
        )]
    ))

def send_location_menu(reply_token):
    items = [QuickReplyItem(action=MessageAction(label=loc[:20], text="📍"+loc)) for loc in LOCATIONS]
    get_messaging_api().reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(text="📍 เลือกบริเวณที่พบ:", quick_reply=QuickReply(items=items))]
    ))

def send_alert_to_group(message_id, location, reporter_name):
    add_report(location, reporter_name)
    now = now_bkk().strftime("%d/%m/%Y %H:%M น.")

    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"}
    image_content = requests.get(url, headers=headers).content

    public_url = None
    try:
        b64 = base64.b64encode(image_content).decode("utf-8")
        r = requests.post("https://api.imgur.com/3/image",
                          headers={"Authorization": "Client-ID 546c25a59c58ad7"},
                          json={"image": b64, "type": "base64"})
        if r.status_code == 200:
            public_url = r.json()["data"]["link"]
    except:
        pass

    api = get_messaging_api()
    if public_url:
        flex = {
            "type": "bubble", "size": "mega",
            "header": {
                "type": "box", "layout": "vertical",
                "backgroundColor": "#C62828", "paddingAll": "16px",
                "contents": [
                    {"type": "text", "text": "⚠️ SAFETY ALERT ⚠️", "weight": "bold", "size": "xl", "color": "#FFFFFF"},
                    {"type": "text", "text": "พบการไม่ใส่ PPE", "size": "sm", "color": "#FFCDD2"}
                ]
            },
            "hero": {"type": "image", "url": public_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
            "body": {
                "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "16px",
                "contents": [
                    {"type": "box", "layout": "horizontal", "contents": [
                        {"type": "text", "text": "📍", "size": "sm", "flex": 1},
                        {"type": "text", "text": location, "size": "sm", "flex": 5, "weight": "bold", "wrap": True}
                    ]},
                    {"type": "box", "layout": "horizontal", "contents": [
                        {"type": "text", "text": "🕐", "size": "sm", "flex": 1},
                        {"type": "text", "text": now, "size": "sm", "flex": 5, "color": "#666666"}
                    ]},
                    {"type": "separator", "margin": "md"},
                    {"type": "text", "text": "กรุณาแก้ไขโดยด่วน", "size": "sm", "color": "#C62828", "margin": "md", "weight": "bold"}
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical", "backgroundColor": "#F5F5F5",
                "contents": [{"type": "text", "text": "SSPO Safety Buddy System", "size": "xs", "color": "#999999", "align": "center"}]
            }
        }
        api.push_message(PushMessageRequest(to=GROUP_ID, messages=[
            FlexMessage(alt_text=f"⚠️ พบไม่ใส่ PPE บริเวณ {location}", contents=FlexContainer.from_dict(flex))
        ]))
    else:
        api.push_message(PushMessageRequest(to=GROUP_ID, messages=[
            TextMessage(text=f"⚠️ SAFETY ALERT ⚠️\nพบไม่ใส่ PPE\n📍 {location}\n🕐 {now}")
        ]))

def send_dashboard_to_group():
    lb = get_leaderboard()
    total_r, total_s, total_u = get_stats()
    now = now_bkk().strftime("%d/%m/%Y %H:%M")
    medal = ["🥇","🥈","🥉","4️⃣","5️⃣"]
    lb_rows = []
    for i, (uid, d) in enumerate(lb[:5]):
        lb_rows.append({"type":"box","layout":"horizontal","contents":[
            {"type":"text","text":f"{medal[i] if i<5 else str(i+1)+'.'} {d['name']}","size":"sm","flex":4,"wrap":True},
            {"type":"text","text":f"⭐ {d['count']}","size":"sm","flex":2,"align":"end","color":"#E65100","weight":"bold"}
        ]})
    body = [
        {"type":"box","layout":"horizontal","spacing":"md","contents":[
            {"type":"box","layout":"vertical","flex":1,"backgroundColor":"#FFF3E0","cornerRadius":"8px","paddingAll":"10px","contents":[
                {"type":"text","text":"🚨","align":"center","size":"lg"},
                {"type":"text","text":str(total_r),"align":"center","size":"xxl","weight":"bold","color":"#C62828"},
                {"type":"text","text":"รายงาน","align":"center","size":"xs","color":"#999"}
            ]},
            {"type":"box","layout":"vertical","flex":1,"backgroundColor":"#FFF8E1","cornerRadius":"8px","paddingAll":"10px","contents":[
                {"type":"text","text":"⭐","align":"center","size":"lg"},
                {"type":"text","text":str(total_s),"align":"center","size":"xxl","weight":"bold","color":"#E65100"},
                {"type":"text","text":"ดาวรวม","align":"center","size":"xs","color":"#999"}
            ]},
            {"type":"box","layout":"vertical","flex":1,"backgroundColor":"#E8F5E9","cornerRadius":"8px","paddingAll":"10px","contents":[
                {"type":"text","text":"👷","align":"center","size":"lg"},
                {"type":"text","text":str(total_u),"align":"center","size":"xxl","weight":"bold","color":"#2E7D32"},
                {"type":"text","text":"ผู้ใช้","align":"center","size":"xs","color":"#999"}
            ]}
        ]},
        {"type":"separator"},
        {"type":"text","text":"🏆 Top ดาวสูงสุด","weight":"bold","size":"md","margin":"md"},
        *(lb_rows if lb_rows else [{"type":"text","text":"ยังไม่มีข้อมูล","color":"#999","size":"sm"}])
    ]
    flex = {
        "type":"bubble","size":"mega",
        "header":{"type":"box","layout":"vertical","backgroundColor":"#1B5E20","paddingAll":"16px","contents":[
            {"type":"text","text":"📊 Safety Dashboard","weight":"bold","size":"xl","color":"#FFFFFF"},
            {"type":"text","text":now,"size":"xs","color":"#A5D6A7"}
        ]},
        "body":{"type":"box","layout":"vertical","spacing":"md","contents":body},
        "footer":{"type":"box","layout":"vertical","backgroundColor":"#F5F5F5","contents":[
            {"type":"text","text":"SSPO Safety Buddy System","size":"xs","color":"#999","align":"center"}
        ]}
    }
    get_messaging_api().push_message(PushMessageRequest(to=GROUP_ID, messages=[
        FlexMessage(alt_text="📊 Safety Dashboard", contents=FlexContainer.from_dict(flex))
    ]))

# ========== DASHBOARD WEB ==========
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SSPO Safety Dashboard</title>
<style>
  :root {
    --green: #1B5E20; --green-light: #43A047; --red: #C62828;
    --orange: #E65100; --gray: #F8F9FA; --card-shadow: 0 2px 12px rgba(0,0,0,0.08);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #F0F4F0; color: #1a1a1a; }
  header { background: var(--green); color: white; padding: 20px 24px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 20px; font-weight: 700; }
  header p { font-size: 12px; opacity: 0.7; margin-top: 2px; }
  .container { max-width: 900px; margin: 0 auto; padding: 24px 16px; }
  .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 24px; }
  .stat-card { background: white; border-radius: 16px; padding: 20px; text-align: center; box-shadow: var(--card-shadow); }
  .stat-card .icon { font-size: 28px; margin-bottom: 8px; }
  .stat-card .num { font-size: 40px; font-weight: 800; line-height: 1; }
  .stat-card .label { font-size: 12px; color: #666; margin-top: 6px; font-weight: 500; }
  .card { background: white; border-radius: 16px; box-shadow: var(--card-shadow); overflow: hidden; margin-bottom: 20px; }
  .card-header { padding: 16px 20px; border-bottom: 1px solid #F0F0F0; display: flex; align-items: center; gap: 8px; }
  .card-header h2 { font-size: 15px; font-weight: 700; color: #1a1a1a; }
  table { width: 100%; border-collapse: collapse; }
  th { background: #FAFAFA; padding: 10px 16px; text-align: left; font-size: 12px; font-weight: 600; color: #666; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #F0F0F0; }
  td { padding: 12px 16px; font-size: 13px; border-bottom: 1px solid #F8F8F8; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #FAFAFA; }
  .rank { font-size: 18px; }
  .star-count { color: var(--orange); font-weight: 700; }
  .badge { display: inline-flex; align-items: center; gap: 4px; background: #FFF3E0; color: var(--orange); padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
  .badge-red { background: #FFEBEE; color: var(--red); }
  .location { color: #444; font-weight: 500; }
  .time { color: #999; font-size: 12px; }
  .empty { text-align: center; padding: 32px; color: #bbb; font-size: 14px; }
  footer { text-align: center; color: #bbb; font-size: 11px; padding: 24px; }
  @media (max-width: 480px) {
    .stats { grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .stat-card { padding: 14px 8px; }
    .stat-card .num { font-size: 28px; }
  }
</style>
</head>
<body>
<header>
  <div style="background:rgba(255,255,255,0.15);border-radius:12px;padding:10px;font-size:24px">🦺</div>
  <div>
    <h1>SSPO Safety Dashboard</h1>
    <p>ระบบติดตามความปลอดภัย • อัปเดต {{ now }}</p>
  </div>
</header>

<div class="container">
  <div class="stats">
    <div class="stat-card">
      <div class="icon">🚨</div>
      <div class="num" style="color:var(--red)">{{ total_reports }}</div>
      <div class="label">รายงานทั้งหมด</div>
    </div>
    <div class="stat-card">
      <div class="icon">⭐</div>
      <div class="num" style="color:var(--orange)">{{ total_stars }}</div>
      <div class="label">ดาวที่มอบ</div>
    </div>
    <div class="stat-card">
      <div class="icon">👷</div>
      <div class="num" style="color:var(--green-light)">{{ total_users }}</div>
      <div class="label">ผู้ใช้งาน</div>
    </div>
  </div>

  <div class="card">
    <div class="card-header">
      <span style="font-size:18px">🏆</span>
      <h2>อันดับดาวความปลอดภัย</h2>
    </div>
    <table>
      <tr><th>อันดับ</th><th>ชื่อ</th><th>ดาว</th></tr>
      {% for i, uid, data in leaderboard %}
      <tr>
        <td class="rank">{% if i==0 %}🥇{% elif i==1 %}🥈{% elif i==2 %}🥉{% else %}<span style="color:#999;font-size:14px">{{ i+1 }}</span>{% endif %}</td>
        <td style="font-weight:600">{{ data.name }}</td>
        <td><span class="badge">⭐ {{ data.count }}</span></td>
      </tr>
      {% endfor %}
      {% if not leaderboard %}<tr><td colspan="3" class="empty">ยังไม่มีข้อมูล</td></tr>{% endif %}
    </table>
  </div>

  <div class="card">
    <div class="card-header">
      <span style="font-size:18px">📋</span>
      <h2>รายงานล่าสุด</h2>
    </div>
    <table>
      <tr><th>เวลา</th><th>บริเวณ</th></tr>
      {% for r in reports %}
      <tr>
        <td class="time">{{ r.time }}</td>
        <td><span class="badge badge-red">{{ r.location }}</span></td>
      </tr>
      {% endfor %}
      {% if not reports %}<tr><td colspan="2" class="empty">ยังไม่มีรายงาน</td></tr>{% endif %}
    </table>
  </div>
</div>
<footer>SSPO Safety Buddy System — ข้อมูลจาก Google Sheets</footer>
</body>
</html>"""

@app.route("/dashboard")
def dashboard():
    lb = [(i, uid, data) for i, (uid, data) in enumerate(get_leaderboard())]
    reports = get_recent_reports(20)
    tr, ts, tu = get_stats()
    now = now_bkk().strftime("%d/%m/%Y %H:%M น.")
    return render_template_string(DASHBOARD_HTML,
        leaderboard=lb, reports=reports,
        total_reports=tr, total_stars=ts, total_users=tu, now=now)

@app.route("/health")
def health():
    return {"status": "ok"}, 200

@app.route("/callback", methods=["POST"])
def callback():
    sig = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, sig)
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
    api = get_messaging_api()

    # ---- ให้ดาว: กดเลือกจาก quick reply ----
    if text.startswith("⭐give:"):
        parts = text.split(":")
        if len(parts) >= 3:
            receiver_id, receiver_name = parts[1], parts[2]
            total = add_star(user_id, name, receiver_id, receiver_name)
            api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[
                TextMessage(text=f"✅ ให้ดาว {receiver_name} สำเร็จ!\n{receiver_name} มีดาวทั้งหมด ⭐ {total} ดาว")
            ]))
            api.push_message(PushMessageRequest(to=GROUP_ID, messages=[
                TextMessage(text=f"⭐ {name} ให้ดาวแก่ {receiver_name} เพราะใส่ PPE ครบ!\n{receiver_name} มี {total} ดาว 🎉")
            ]))
        user_state.pop(user_id, None)
        return

    # ---- ให้ดาว: ค้นหาชื่อ ----
    if user_state.get(user_id, {}).get("waiting") == "star_search":
        keyword = text
        results = search_users(keyword)
        results = [(uid, n) for uid, n in results if uid != user_id]
        if not results:
            api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[
                TextMessage(
                    text=f'ไม่พบชื่อ "{keyword}" ในระบบ\nลองพิมพ์ชื่อใหม่ หรือกด "ยกเลิก"',
                    quick_reply=QuickReply(items=[
                        QuickReplyItem(action=MessageAction(label="❌ ยกเลิก", text="ยกเลิก"))
                    ])
                )
            ]))
        elif len(results) == 1:
            uid, n = results[0]
            total = add_star(user_id, name, uid, n)
            api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[
                TextMessage(text=f"✅ ให้ดาว {n} สำเร็จ!\n{n} มีดาวทั้งหมด ⭐ {total} ดาว")
            ]))
            api.push_message(PushMessageRequest(to=GROUP_ID, messages=[
                TextMessage(text=f"⭐ {name} ให้ดาวแก่ {n} เพราะใส่ PPE ครบ!\n{n} มี {total} ดาว 🎉")
            ]))
            user_state.pop(user_id, None)
        else:
            # แสดงตัวเลือกจากผลค้นหา (สูงสุด 13)
            items = [
                QuickReplyItem(action=MessageAction(label=n[:20], text=f"⭐give:{uid}:{n}"))
                for uid, n in results[:13]
            ]
            items.append(QuickReplyItem(action=MessageAction(label="❌ ยกเลิก", text="ยกเลิก")))
            api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[
                TextMessage(
                    text=f'พบ {len(results)} คนที่มีชื่อ "{keyword}"\nเลือกคนที่ต้องการให้ดาว:',
                    quick_reply=QuickReply(items=items)
                )
            ]))
        return

    # ---- เลือกบริเวณ ----
    if text.startswith("📍") and user_state.get(user_id, {}).get("waiting") == "location":
        location = text[1:].strip() if text.startswith("📍") else text
        user_state[user_id] = {"waiting": "image", "location": location}
        api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[
            TextMessage(text=f"📸 กรุณาส่งรูปภาพเหตุการณ์\nบริเวณ: {location}")
        ]))
        return

    # ---- ยกเลิก ----
    if text == "ยกเลิก":
        user_state.pop(user_id, None)
        send_main_menu(event.reply_token)
        return

    # ---- เมนูหลัก ----
    if text.lower() in ["report", "แจ้ง", "🚨"]:
        user_state[user_id] = {"waiting": "location"}
        send_location_menu(event.reply_token)
        return

    if text in ["ให้ดาว", "⭐ ให้ดาว", "star", "rewards"]:
        users = get_users()
        count = len([u for u in users if u != user_id])
        if count == 0:
            api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[
                TextMessage(text="ยังไม่มีสมาชิกในระบบครับ\nให้เพื่อนๆ แชทกับบอทก่อนสักครั้งครับ 🙏")
            ]))
            return
        user_state[user_id] = {"waiting": "star_search"}
        api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[
            TextMessage(text=f"⭐ ให้ดาวเพื่อนที่ใส่ PPE ครบ\n\nมีสมาชิกในระบบ {count} คน\nพิมพ์ชื่อ (หรือบางส่วนของชื่อ) เพื่อค้นหา:")
        ]))
        return

    if text.lower() in ["dashboard", "/dashboard", "สรุป"]:
        url = os.environ.get("RENDER_EXTERNAL_URL", "https://sspo-safety-buddy.onrender.com")
        api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[
            TextMessage(text=f"📊 ดู Dashboard ได้ที่:\n{url}/dashboard")
        ]))
        return

    send_main_menu(event.reply_token)


@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    if event.source.type == "group":
        return
    user_id = event.source.user_id
    name = get_user_profile(user_id)
    state = user_state.get(user_id, {})

    if state.get("waiting") != "image":
        get_messaging_api().reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text="กรุณาพิมพ์ 'report' ก่อนส่งรูปครับ 🙏")]
        ))
        return

    location = state.get("location", "ไม่ระบุ")
    send_alert_to_group(event.message.id, location, name)
    get_messaging_api().reply_message(ReplyMessageRequest(
        reply_token=event.reply_token,
        messages=[TextMessage(text=f"✅ รายงานสำเร็จ!\n📍 {location}\nทีม Safety ได้รับแจ้งแล้วครับ 🙏")]
    ))
    user_state.pop(user_id, None)


with app.app_context():
    try:
        init_sheets()
    except Exception as e:
        print(f"init error: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
