# 🦺 SSPO Safety Buddy Bot

LINE Chatbot สำหรับรายงานเหตุการณ์ความปลอดภัย

## ไฟล์ในโปรเจค
```
safety-buddy/
├── app.py              # โค้ดหลักของบอท
├── requirements.txt    # library ที่ใช้
├── Procfile           # สำหรับ Render.com
├── .env.example       # ตัวอย่าง environment variables
└── .gitignore
```

## วิธี Deploy บน Render.com

1. Push โค้ดขึ้น GitHub
2. ไปที่ render.com → New → Web Service
3. เชื่อม GitHub repo นี้
4. ตั้งค่า Environment Variables:
   - CHANNEL_ACCESS_TOKEN = (จาก LINE Developers Console)
   - CHANNEL_SECRET = (จาก LINE Developers Console)
   - GROUP_ID = (ID ของกลุ่ม LINE ที่ต้องการแจ้งเตือน)
5. Deploy → ได้ URL เช่น https://sspo-safety-buddy.onrender.com

## วิธีหา GROUP_ID

1. เพิ่มบอทเข้ากลุ่ม LINE
2. ดู Log ใน Render → จะเห็น "GROUP ID: Cxxxxxxx"
3. Copy มาใส่ใน Environment Variables

## Webhook URL
```
https://YOUR-APP.onrender.com/callback
```
นำไปใส่ใน LINE Developers Console → Messaging API → Webhook URL
