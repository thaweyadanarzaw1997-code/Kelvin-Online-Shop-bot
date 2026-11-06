import os
import json
import requests
from fastapi import FastAPI, Request
from pydantic import BaseModel
import google.generativeai as genai
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")

genai.configure(api_key=GEMINI_API_KEY)

# Google Sheets Setup
def get_google_sheet_data():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # Vercel Environment Variable မှ Service Account JSON ကို ဖတ်ခြင်း (သို့မဟုတ် Local အတွက် ဖိုင်လမ်းကြောင်းထည့်ရန်)
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        # Local စမ်းသုံးရန် (Service Account JSON ဖိုင်နာမည်ကို ထည့်ပါ)
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        
    client = gspread.authorize(creds)
    
    # သင့် Google Sheet အမည်ကို ထည့်ပါ (ဥပမာ: "Fragrance by Kelvin")
    sheet = client.open("Fragrance by Kelvin")
    return sheet

def load_products_from_sheet():
    try:
        sheet = get_google_sheet_data()
        worksheet = sheet.worksheet("Sheet1") # ရေမွေးစာရင်းရှိသော Sheet
        data = worksheet.get_all_records()
        return data
    except Exception as e:
        print(f"Error loading products: {e}")
        return []

def save_order_to_sheet(order_details):
    try:
        sheet = get_google_sheet_data()
        worksheet = sheet.worksheet("Sheet2") # Order စာရင်းရှိသော Sheet
        # အချက်အလက်များထည့်ခြင်း: [Date, Customer, Phone, Address, ItemName, Price, Status, ...]
        worksheet.append_row([
            order_details.get("date"),
            order_details.get("customer"),
            order_details.get("phone"),
            "", # Viber
            order_details.get("address"),
            order_details.get("item_name"),
            order_details.get("price"),
            "Pending",
            "",
            order_details.get("payment_method", "Cash on Delivery"),
            "",
            "",
            "Pending"
        ])
        return True
    except Exception as e:
        print(f"Error saving order: {e}")
        return False

# System Prompt for Gemini AI
def get_system_prompt():
    products = load_products_from_sheet()
    return f"""
သင်သည် Kelvin Fragrance Online Shop ၏ အသိဉာဏ်ထက်မြက်သော AI ရေမွေး အရောင်းကျွမ်းကျင်သူ (AI Sales Consultant) ဖြစ်သည်။
ကျွန်ုပ်တို့၏ Google Sheet ထဲတွင် ရှိနေသော လက်ရှိ ရေမွေးစာရင်းများမှာ အောက်ပါအတိုင်း ဖြစ်သည်:
{json.dumps(products, ensure_ascii=False, indent=2)}

စည်းမျဉ်းများ -
1. Customer များက ရေမွေးအကြောင်း မေးမြန်းလျှင်၊ အကြံဉာဏ်တောင်းလျှင် အထက်ပါ Google Sheet စာရင်းထဲမှ သင့်လျော်သော ရေမွေးများကို ဈေးနှုန်းနှင့် ဖော်ပြပေးပါ။
2. စာရင်းထဲတွင် မရှိသော အကြောင်းအရာများ သို့မဟုတ် အထွေထွေ ဗဟုသုတ၊ ရေမွေးသမိုင်းကြောင်းများကို မေးလျှင်လည်း ကိုယ်ပိုင်ဗဟုသုတဖြင့် ချိုသာယဉ်ကျေးစွာ ဖြေကြားပေးပါ။
3. Customer က ဈေးဝယ်လိုကြောင်း (Order တင်လိုကြောင်း) ပြောလာပါက အမည်၊ ဖုန်းနံပါတ်၊ လိပ်စာ နှင့် လိုချင်သည့် ရေမွေးအမျိုးအစား/ပမာဏတို့ကို အဆင့်ဆင့် မေးမြန်းပါ။ အချက်အလက် အစုံအလင်ရပါက Order တင်ပေးမည်ဖြစ်ကြောင်း အတည်ပြုပါ။
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
        # Dynamic System Prompt ဖြင့် Gemini Model ကို ဖန်တီးခြင်း (Sheet ထဲက Data အသစ်တွေကို အမြဲဖတ်မည်)
        current_system_prompt = get_system_prompt()
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=current_system_prompt
        )
        
        chat_session = model.start_chat(history=[])
        response = chat_session.send_message(user_text)
        reply_text = response.text
    except Exception as e:
        reply_text = "ဝမ်းနည်းပါတယ်၊ လက်တလော စနစ် အလုပ်လုပ်ရာတွင် အနည်းငယ် အခက်အခဲရှိနေပါသည်။ ကျေးဇူးပြု၍ ခဏနေမှ ထပ်မံကြိုးစားပေးပါရှင့်။"

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
    return {"status": "Telegram Bot with Live Google Sheets is running smoothly!"}
