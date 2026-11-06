import os
import json
import time
import requests
from fastapi import FastAPI, Request
from pydantic import BaseModel
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from groq import Groq

app = FastAPI()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "YOUR_GROQ_API_KEY_HERE")

client = Groq(api_key=GROQ_API_KEY)

PRODUCTS_CACHE = []
LAST_FETCH_TIME = 0
CACHE_DURATION = 3600

def get_google_sheet_data():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
    client_gs = gspread.authorize(creds)
    return client_gs.open("Fragrance by Kelvin")

def load_products_cached():
    global PRODUCTS_CACHE, LAST_FETCH_TIME
    if PRODUCTS_CACHE and (time.time() - LAST_FETCH_TIME < CACHE_DURATION):
        return PRODUCTS_CACHE
    try:
        sheet = get_google_sheet_data()
        worksheet = sheet.worksheet("Sheet1")
        PRODUCTS_CACHE = worksheet.get_all_records()
        LAST_FETCH_TIME = time.time()
        return PRODUCTS_CACHE
    except Exception as e:
        print(f"Sheet Error: {e}")
        return PRODUCTS_CACHE

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
        send_telegram_message(chat_id, "မင်္ဂလာပါရှင်! Kelvin Fragrance Bot မှ ကြိုဆိုပါတယ်။")
        return {"status": "ok"}

    try:
        products = load_products_cached()
        system_prompt = f"သင်သည် ရေမွေးအရောင်းစာရေးဖြစ်သည်. စာရင်း: {json.dumps(products, ensure_ascii=False)}"
        
        response = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0.7
        )
        reply_text = response.choices[0].message.content
    except Exception as e:
        # Error တက်ရင် ဘာ Error လဲဆိုတာ Telegram မှာ ပို့ပေးမယ်
        reply_text = f"⚠️ Server Error: {str(e)}"

    send_telegram_message(chat_id, reply_text)
    return {"status": "ok"}

def send_telegram_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

@app.get("/")
async def root():
    return {"status": "Running"}
