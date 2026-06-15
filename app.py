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

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("CHANNEL_SECRET")
GROUP_ID = os.environ.get("GROUP_ID")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

user_state = {}

# ========== DATABASE ==========
DB_FILE = "data.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"stars": {}, "reports": [], "users": {}}

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def add_star(giver_id, giver_name, receiver_id, receiver_name):
    db = load_db()
    if receiver_id not in db["stars"]:
        db["stars"][receiver_id] = {"name": receiver_name, "count": 0, "history": []}
    db["stars"][receiver_id]["count"] += 1
    db["stars"][receiver_id]["name"] = receiver_name
    db["stars"][receiver_id]["history"].append({
        "from": giver_name,
        "time": datetime.now().strftime("%d/%m/%Y %H:%M")
    })
    db["users"][giver_id] = giver_name
    db["users"][receiver_id] = receiver_name
    save_db(db)
    return db["stars"][receiver_id]["count"]

def add_report(report_type, reporter_name):
    db = load_db()
    db["reports"].append({
        "type": report_type,
        "reporter": reporter_name,
        "time": datetime.now().strftime("%d/%m/%Y %H:%M")
    })
    save_db(db)

def get_leaderboard():
    db = load_db()
    stars = db["stars"]
    sorted_stars = sorted(stars.items(), key=lambda x: x[1]["count"], reverse=True)
    return sorted_stars[:10]

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

def get_group_members():
    try:
        url = f"https://api.line.me/v2/bot/group/{GROUP_ID}/members/ids"
        headers = {"Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"}
        response = requests.get(url, headers=headers)
        data = response.json()
        members = []
        for uid in data.get("memberIds", []):
            name = get_user_profile(uid)
            members.append({"id": uid, "name": name})
        return members
    except:
        return []

def send_quick_reply(reply_token):
    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(
            text="เลือกประเภทที่ต้องการรายงาน:",
            quick_reply=QuickReply(items=[
                QuickReplyItem(action=MessageAction(label="🦺 ไม่ใส่ PPE", text="🦺 ไม่ใส่ PPE")),
                QuickReplyItem(action=MessageAction(label="⚠️ จุดเสี่ยง", text="⚠️ จุดเสี่ยง")),
                QuickReplyItem(action=MessageAction(label="🔥 เหตุฉุกเฉิน", text="🔥 เหตุฉุกเฉิน")),
            ])
        )]
    ))

def send_star_menu(reply_token, giver_id):
    members = get_group_members()
    items = []
    for m in members:
        if m["id"] != giver_id:
            items.append(QuickReplyItem(
                action=MessageAction(
                    label=m["name"][:20],
                    text="STAR:" + m["id"] + ":" + m["name"]
                )
            ))
    if not items:
        api = get_messaging_api()
        api.reply_message(ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text="ไม่พบสมาชิกในกลุ่มครับ")]
        ))
        return
    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(
            text="เลือกคนที่อยากให้ดาว (ใส่ PPE ครบ):",
            quick_reply=QuickReply(items=items[:13])
        )]
    ))

def send_dashboard_to_group():
    db = load_db()
    leaderboard = get_leaderboard()
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    medal = ["🥇", "🥈", "🥉", "4.", "5."]
    total_reports = len(db["reports"])
    total_stars = sum(v["count"] for v in db["stars"].values())

    lb_rows = []
    for i, (uid, data) in enumerate(leaderboard[:5]):
        icon = medal[i] if i < len(medal) else str(i+1) + "."
        lb_rows.append({
            "type": "box",
            "layout": "horizontal",
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
                }
            ]
        },
        {"type": "separator"},
        {"type": "text", "text": "🏆 Top ดาวสูงสุด", "weight": "bold", "size": "md"}
    ]

    if lb_rows:
        body_contents.extend(lb_rows)
    else:
        body_contents.append({"type": "text", "text": "ยังไม่มีข้อมูล", "color": "#888888", "size": "sm"})

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
        messages=[FlexMessage(
            alt_text="📊 Safety Dashboard",
            contents=FlexContainer.from_dict(flex_content)
        )]
    ))

def get_image_content(message_id):
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers)
    return response.content

def upload_to_imgur(image_content):
    try:
        headers = {"Authorization": "Client-ID 546c25a59c58ad7"}
        b64 = base64.b64encode(image_content).decode("utf-8")
        response = requests.post(
            "https://api.imgur.com/3/image",
            headers=headers,
            json={"image": b64, "type": "base64"}
        )
        if response.status_code == 200:
            return response.json()["data"]["link"]
    except:
        pass
    return None

def send_alert_to_group(message_id, report_type, reporter_name):
    now = datetime.now().strftime("%d/%m/%Y %H:%M น.")
    image_content = get_image_content(message_id)
    public_image_url = upload_to_imgur(image_content)
    add_report(report_type, reporter_name)

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
                    {"type": "text", "text": "พบ " + report_type, "weight": "bold", "size": "lg", "color": "#FF0000", "wrap": True},
                    {"type": "text", "text": "กรุณาแก้ไขด่วน!", "size": "md", "color": "#333333", "margin": "sm"},
                    {"type": "separator", "margin": "md"},
                    {
                        "type": "box", "layout": "vertical", "margin": "md", "spacing": "sm",
                        "contents": [
                            {"type": "box", "layout": "horizontal", "contents": [
                                {"type": "text", "text": "🕐 เวลา", "size": "sm", "color": "#888888", "flex": 3},
                                {"type": "text", "text": now, "size": "sm", "color": "#333333", "flex": 5}
                            ]},
                            {"type": "box", "layout": "horizontal", "contents": [
                                {"type": "text", "text": "📋 ประเภท", "size": "sm", "color": "#888888", "flex": 3},
                                {"type": "text", "text": report_type, "size": "sm", "color": "#FF0000", "flex": 5, "weight": "bold"}
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
            messages=[FlexMessage(
                alt_text="⚠️ Safety Alert! พบ " + report_type,
                contents=FlexContainer.from_dict(flex_content)
            )]
        ))
    else:
        api.push_message(PushMessageRequest(
            to=GROUP_ID,
            messages=[TextMessage(text="⚠️ SAFETY ALERT\nพบ " + report_type + "\nกรุณาแก้ไขด่วน!\n🕐 " + now)]
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
  body { font-family: sans-serif; background: #f0f4f8; margin: 0; padding: 20px; }
  h1 { color: #00897B; text-align: center; }
  .cards { display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; margin: 20px 0; }
  .card { background: white; border-radius: 12px; padding: 24px; text-align: center; min-width: 140px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
  .num { font-size: 48px; font-weight: bold; }
  .label { color: #888; font-size: 14px; }
  table { width: 100%; max-width: 600px; margin: 0 auto 24px; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); border-collapse: collapse; }
  th { background: #00897B; color: white; padding: 12px 16px; text-align: left; }
  td { padding: 12px 16px; border-bottom: 1px solid #f0f0f0; }
  h2 { text-align: center; color: #333; margin-top: 32px; }
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
  {% if not leaderboard %}<tr><td colspan="3" style="text-align:center;color:#888">ยังไม่มีข้อมูล</td></tr>{% endif %}
</table>

<h2>📋 รายงานล่าสุด</h2>
<table>
  <tr><th>เวลา</th><th>ประเภท</th></tr>
  {% for r in reports %}
  <tr>
    <td style="color:#888;font-size:13px">{{ r.time }}</td>
    <td style="color:#FF0000">{{ r.type }}</td>
  </tr>
  {% endfor %}
  {% if not reports %}<tr><td colspan="2" style="text-align:center;color:#888">ยังไม่มีข้อมูล</td></tr>{% endif %}
</table>
<p style="text-align:center;color:#aaa;font-size:12px">อัปเดต {{ now }}</p>
</body>
</html>
"""

@app.route("/dashboard")
def dashboard():
    db = load_db()
    leaderboard = [(i, uid, data) for i, (uid, data) in enumerate(get_leaderboard())]
    reports = list(reversed(db["reports"][-20:]))
    return render_template_string(DASHBOARD_HTML,
        leaderboard=leaderboard,
        reports=reports,
        total_reports=len(db["reports"]),
        total_stars=sum(v["count"] for v in db["stars"].values()),
        total_users=len(db["users"]),
        now=datetime.now().strftime("%d/%m/%Y %H:%M น.")
    )

@app.route("/health", methods=["GET"])
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
        return  # ไม่ตอบในกลุ่ม

    user_id = event.source.user_id
    text = event.message.text.strip()

    # ให้ดาว
    if text.startswith("STAR:"):
        parts = text.split(":")
        if len(parts) >= 3:
            receiver_id = parts[1]
            receiver_name = parts[2]
            giver_name = get_user_profile(user_id)
            total = add_star(user_id, giver_name, receiver_id, receiver_name)
            api = get_messaging_api()
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="✅ ให้ดาว " + receiver_name + " สำเร็จ!\nรวมทั้งหมด ⭐ " + str(total) + " ดาว")]
            ))
            api.push_message(PushMessageRequest(
                to=GROUP_ID,
                messages=[TextMessage(text="⭐ " + giver_name + " ให้ดาวแก่ " + receiver_name + " เพราะใส่ PPE ครบ!\nรวม " + str(total) + " ดาว 🎉")]
            ))
        return

    if text.lower() in ["report", "alert", "แจ้ง"]:
        user_state.pop(user_id, None)
        send_quick_reply(event.reply_token)
        return

    if text in ["⭐ ให้ดาว", "ให้ดาว", "star"]:
        send_star_menu(event.reply_token, user_id)
        return

    if text.lower() in ["dashboard", "/dashboard", "สรุป"]:
        url = "https://sspo-safety-buddy.onrender.com/dashboard"
        api = get_messaging_api()
        api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text="📊 ดู Dashboard ได้ที่:\n" + url)]
        ))
        return

    if text in ["🦺 ไม่ใส่ PPE", "⚠️ จุดเสี่ยง", "🔥 เหตุฉุกเฉิน"]:
        user_state[user_id] = {"report_type": text}
        api = get_messaging_api()
        api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text="📸 กรุณาส่งรูปภาพเหตุการณ์")]
        ))
        return

    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=event.reply_token,
        messages=[TextMessage(
            text="🦺 SSPO Safety Buddy\n\nเลือกสิ่งที่ต้องการ:",
            quick_reply=QuickReply(items=[
                QuickReplyItem(action=MessageAction(label="🚨 รายงาน", text="report")),
                QuickReplyItem(action=MessageAction(label="⭐ ให้ดาว", text="⭐ ให้ดาว")),
                QuickReplyItem(action=MessageAction(label="📊 Dashboard", text="dashboard")),
            ])
        )]
    ))


@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
    if event.source.type == "group":
        return
    user_id = event.source.user_id
    if user_id not in user_state:
        api = get_messaging_api()
        api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text="กรุณาพิมพ์ 'report' ก่อนส่งรูปครับ 🙏")]
        ))
        return
    report_type = user_state[user_id].get("report_type", "ไม่ระบุ")
    reporter_name = get_user_profile(user_id)
    send_alert_to_group(event.message.id, report_type, reporter_name)
    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=event.reply_token,
        messages=[TextMessage(text="✅ รายงานสำเร็จ!\nประเภท: " + report_type + "\nทีม Safety ได้รับแจ้งแล้วครับ 🙏")]
    ))
    user_state.pop(user_id, None)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
