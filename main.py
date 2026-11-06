import os
import json
import requests
from fastapi import FastAPI, Request
from pydantic import BaseModel
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from openai import OpenAI

app = FastAPI()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY_HERE")

client = OpenAI(api_key=OPENAI_API_KEY)

# Google Sheets Setup
def get_google_sheet_data():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        
    client_gs = gspread.authorize(creds)
    sheet = client_gs.open("Fragrance by Kelvin")
    return sheet

def load_products_from_sheet():
    try:
        sheet = get_google_sheet_data()
        worksheet = sheet.worksheet("Sheet1")
        data = worksheet.get_all_records()
        return data
    except Exception as e:
        print(f"Error loading sheet: {e}")
        return []

# System Prompt for OpenAI ChatGPT
def get_system_prompt():
    products = load_products_from_sheet()
    return f"""
သင်သည် Kelvin Fragrance Online Shop ၏ အသိဉာဏ်ထက်မြက်သော AI ရေမွေး အရောင်းကျွမ်းကျင်သူ (AI Sales Consultant) ဖြစ်သည်။
ကျွန်ုပ်တို့၏ Google Sheet ထဲတွင် ရှိနေသော လက်ရှိ ရေမွေးစာရင်းများမှာ အောက်ပါအတိုင်း ဖြစ်သည်:
{json.dumps(products, ensure_ascii=False, indent=2)}

စည်းမျဉ်းများ -
1. Customer များက ရေမွေးအကြောင်း မေးမြန်းလျှင်၊ အကြံဉာဏ်တောင်းလျှင် အထက်ပါ Google Sheet စာရင်းထဲမှ သင့်လျော်သော ရေမွေးများကို ဈေးနှုန်းနှင့် ဖော်ပြပေးပါ။
2. စာရင်းထဲတွင် မရှိသော အကြောင်းအရာများ သို့မဟုတ် အထွေထွေ ဗဟုသုတ၊ ရေမွေးသမိုင်းကြောင်းများကို မေးလျှင်လည်း ကိုယ်ပိုင်ဗဟုသုတဖြင့် ချိုသာယဉ်ကျေးစွာ ဖြေကြားပေးပါ။
3. Customer က ဈေးဝယ်လိုကြောင်း (Order တင်လိုကြောင်း) ပြောလာပါက အမည်၊ ဖုန်းနံပါတ်၊ လိပ်စာ နှင့် လိုချင်သည့် ရေမွေးအမျိုးအစား/ပမာဏတို့ကို အဆင့်ဆင့် မေးမြန်းပါ။
4. အမြဲတမ်း မြန်မာဘာသာဖြင့် ဖော်ရွေပျူငှာစွာ ဖြေကြားပါ။
"""

class TelegramUpdate(BaseModel):
    update_id: int
    message: dict = None

@app.post("/")
async def webhook(update: TelegramUpdate):
    if not update.message or "text" not in update.message:
        return {"status": "ok"}
    
    chat_id = update.message["chat"]["id"]
    user_text = update.message["text"]
    
    if user_text == "/start":
        welcome_message = (
            "မင်္ဂလာပါရှင်! 🙏 Kelvin Fragrance Online Shop မှ ကြိုဆိုပါတယ်။\n\n"
            "ကျွန်ုပ်တို့ ဆီမှာ ရရှိနိုင်တဲ့ မွှေးပျံ့တဲ့ ရေမွေးအမျိုးမျိုးကို စိတ်ကြိုက်မေးမြန်းနိုင်ပါတယ်။ "
            "ဘယ်လိုရနံ့မျိုးကို နှစ်သက်လဲ၊ ဘယ်လိုနေရာတွေမှာ သုံးမလဲ ပြောပြပေးပါနော်။"
        )
        send_telegram_message(chat_id, welcome_message)
        return {"status": "ok"}

    try:
        system_prompt = get_system_prompt()
        
        # OpenAI GPT-4o-mini ဖြင့် ဖြေကြားခြင်း
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0.7
        )
        reply_text = response.choices[0].message.content
    except Exception as e:
        reply_text = f"⚠️ Error Details: {str(e)}"

    send_telegram_message(chat_id, reply_text)
    return {"status": "ok"}

def send_telegram_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

@app.get("/")
async def root():
    return {"status": "Telegram Bot with OpenAI is running smoothly!"}
