import os
import requests
from datetime import datetime
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest,
    TextMessage, QuickReply, QuickReplyItem,
    MessageAction, FlexMessage, FlexContainer,
    ImageMessage
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

def get_messaging_api():
    return MessagingApi(ApiClient(configuration))

def send_quick_reply(reply_token):
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
    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=reply_token,
        messages=[TextMessage(text="📸 กรุณาส่งรูปภาพเหตุการณ์")]
    ))

def get_image_content(message_id):
    """ดาวน์โหลดรูปจาก LINE และ upload ไปที่ LINE ใหม่ผ่าน imgur"""
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {"Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers)
    return response.content, response.headers.get("Content-Type", "image/jpeg")

def upload_to_imgur(image_content):
    """Upload รูปไปที่ imgur เพื่อได้ public URL"""
    try:
        headers = {"Authorization": "Client-ID 546c25a59c58ad7"}
        response = requests.post(
            "https://api.imgur.com/3/image",
            headers=headers,
            data={"image": image_content.hex()}
        )
        # ใช้ base64 แทน
        import base64
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

def send_alert_to_group(message_id, report_type):
    """ส่ง Flex Message + รูปภาพเข้ากลุ่ม"""
    now = datetime.now().strftime("%d/%m/%Y %H:%M น.")

    # ดาวน์โหลดรูปจาก LINE
    image_content, content_type = get_image_content(message_id)
    
    # Upload ไป imgur
    public_image_url = upload_to_imgur(image_content)

    api = get_messaging_api()

    messages = []

    # ถ้าได้ public URL → ส่ง Flex Message พร้อมรูป
    if public_image_url:
        flex_content = {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [{"type": "text", "text": "⚠️ SAFETY ALERT", "weight": "bold", "size": "xl", "color": "#FFFFFF"}],
                "backgroundColor": "#FF0000",
                "paddingAll": "15px"
            },
            "hero": {
                "type": "image",
                "url": public_image_url,
                "size": "full",
                "aspectRatio": "20:13",
                "aspectMode": "cover"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"พบ {report_type}", "weight": "bold", "size": "lg", "color": "#FF0000", "wrap": True},
                    {"type": "text", "text": "กรุณาแก้ไขด่วน!", "size": "md", "color": "#333333", "margin": "sm"},
                    {"type": "separator", "margin": "md"},
                    {
                        "type": "box", "layout": "vertical", "margin": "md", "spacing": "sm",
                        "contents": [
                            {
                                "type": "box", "layout": "horizontal",
                                "contents": [
                                    {"type": "text", "text": "🕐 เวลา", "size": "sm", "color": "#888888", "flex": 3},
                                    {"type": "text", "text": now, "size": "sm", "color": "#333333", "flex": 5}
                                ]
                            },
                            {
                                "type": "box", "layout": "horizontal",
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
                "type": "box", "layout": "vertical",
                "contents": [{"type": "text", "text": "SSPO Safety Buddy System", "size": "xs", "color": "#888888", "align": "center"}]
            }
        }
        messages.append(FlexMessage(
            alt_text=f"⚠️ Safety Alert! พบ {report_type} กรุณาแก้ไขด่วน!",
            contents=FlexContainer.from_dict(flex_content)
        ))
    else:
        # ถ้าไม่ได้ public URL → ส่งข้อความ + รูปแยก
        messages.append(TextMessage(
            text=f"⚠️ SAFETY ALERT\nพบ {report_type}\nกรุณาแก้ไขด่วน!\n🕐 {now}"
        ))
        # forward รูปเข้ากลุ่มโดยตรง
        messages.append(ImageMessage(
            original_content_url=f"https://api-data.line.me/v2/bot/message/{message_id}/content",
            preview_image_url=f"https://api-data.line.me/v2/bot/message/{message_id}/content"
        ))

    api.push_message(PushMessageRequest(to=GROUP_ID, messages=messages))


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
    if event.source.type == 'group':
        print(f"GROUP ID: {event.source.group_id}")

    if text.lower() in ["report", "alert", "แจ้ง", "🚨"] or "alert" in text.lower():
        user_state.pop(user_id, None)
        send_quick_reply(event.reply_token)
        return

    if text in ["🦺 ไม่ใส่ PPE", "⚠️ จุดเสี่ยง", "🔥 เหตุฉุกเฉิน"]:
        user_state[user_id] = {"report_type": text}
        ask_for_image(event.reply_token)
        return

    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=event.reply_token,
        messages=[TextMessage(text="สวัสดีครับ! พิมพ์ 'report' หรือกดปุ่ม ALERT เพื่อรายงานเหตุการณ์ 🚨")]
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
    message_id = event.message.id

    send_alert_to_group(message_id, report_type)

    api = get_messaging_api()
    api.reply_message(ReplyMessageRequest(
        reply_token=event.reply_token,
        messages=[TextMessage(text=f"✅ รายงานสำเร็จ!\nประเภท: {report_type}\nทีม Safety ได้รับแจ้งแล้วครับ 🙏")]
    ))

    user_state.pop(user_id, None)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
