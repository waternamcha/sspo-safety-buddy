import os
import json
from datetime import datetime
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest,
    TextMessage, ImageMessage, QuickReply, QuickReplyItem,
    MessageAction, FlexMessage, FlexContainer
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

# เก็บ state ของแต่ละ user ชั่วคราว (ว่ากำลัง report อะไรอยู่)
user_state = {}

def get_messaging_api():
    return MessagingApi(ApiClient(configuration))

def get_user_profile(user_id):
    """ดึงชื่อผู้ใช้จาก LINE"""
    try:
        api = get_messaging_api()
        profile = api.get_profile(user_id)
        return profile.display_name
    except:
        return "ไม่ทราบชื่อ"

def send_quick_reply(reply_token):
    """ส่ง Quick Reply ให้เลือกประเภทการรายงาน"""
    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(
            text="🚨 เลือกประเภทที่ต้องการรายงาน:",
            quick_reply=QuickReply(items=[
                QuickReplyItem(action=MessageAction(label="🦺 ไม่ใส่ PPE", text="🦺 ไม่ใส่ PPE")),
                QuickReplyItem(action=MessageAction(label="⚠️ จุดเสี่ยง", text="⚠️ จุดเสี่ยง")),
                QuickReplyItem(action=MessageAction(label="🔥 เหตุฉุกเฉิน", text="🔥 เหตุฉุกเฉิน")),
            ])
        )]
    ))

def ask_for_image(reply_token):
    """ขอรูปภาพจากผู้ใช้"""
    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(text="📸 กรุณาส่งรูปภาพเหตุการณ์")]
    ))

def send_alert_to_group(image_url, report_type, reporter_name):
    """ส่ง Flex Message แจ้งเตือนเข้ากลุ่ม"""
    now = datetime.now().strftime("%d/%m/%Y %H:%M น.")

    flex_content = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "⚠️ SAFETY ALERT",
                    "weight": "bold",
                    "size": "xl",
                    "color": "#FFFFFF"
                }
            ],
            "backgroundColor": "#FF0000",
            "paddingAll": "15px"
        },
        "hero": {
            "type": "image",
            "url": image_url,
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"พบ {report_type}",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#FF0000",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": "กรุณาแก้ไขด่วน!",
                    "size": "md",
                    "color": "#333333",
                    "margin": "sm"
                },
                {
                    "type": "separator",
                    "margin": "md"
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "md",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "👤 ผู้รายงาน", "size": "sm", "color": "#888888", "flex": 3},
                                {"type": "text", "text": reporter_name, "size": "sm", "color": "#333333", "flex": 5, "wrap": True}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "🕐 เวลา", "size": "sm", "color": "#888888", "flex": 3},
                                {"type": "text", "text": now, "size": "sm", "color": "#333333", "flex": 5}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "📋 ประเภท", "size": "sm", "color": "#888888", "flex": 3},
                                {"type": "text", "text": report_type, "size": "sm", "color": "#FF0000", "flex": 5, "weight": "bold"}
                            ]
                        }
                    ]
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "SSPO Safety Buddy System",
                    "size": "xs",
                    "color": "#888888",
                    "align": "center"
                }
            ]
        }
    }

    api = get_messaging_api()
    api.push_message(PushMessageRequest(
        to=GROUP_ID,
        messages=[FlexMessage(
            alt_text=f"⚠️ Safety Alert! พบ {report_type} กรุณาแก้ไขด่วน!",
            contents=FlexContainer.from_dict(flex_content)
        )]
    ))

def get_image_url(message_id):
    """ดึง URL รูปภาพจาก LINE"""
    return f"https://api-data.line.me/v2/bot/message/{message_id}/content"


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "service": "SSPO Safety Buddy"}, 200


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    # เริ่ม report
    if text.lower() in ["report", "alert", "แจ้ง", "🚨"] or "alert" in text.lower():
        user_state.pop(user_id, None)
        send_quick_reply(event.reply_token)
        return

    # เลือกประเภท
    if text in ["🦺 ไม่ใส่ PPE", "⚠️ จุดเสี่ยง", "🔥 เหตุฉุกเฉิน"]:
        user_state[user_id] = {"report_type": text}
        ask_for_image(event.reply_token)
        return

    # ข้อความทั่วไป
    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=event.reply_token,
        messages=[TextMessage(
            text="สวัสดีครับ! พิมพ์ 'report' หรือกดปุ่ม ALERT เพื่อรายงานเหตุการณ์ 🚨",
        )]
    ))


@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image(event):
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
    image_url = get_image_url(event.message.id)

    # ส่งแจ้งเตือนเข้ากลุ่ม
    send_alert_to_group(image_url, report_type, reporter_name)

    # ยืนยันกับผู้รายงาน
    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=event.reply_token,
        messages=[TextMessage(
            text=f"✅ รายงานสำเร็จ!\nประเภท: {report_type}\nทีม Safety ได้รับแจ้งแล้วครับ 🙏"
        )]
    ))

    # ล้าง state
    user_state.pop(user_id, None)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
