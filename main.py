import os
import json
import time
import requests
from fastapi import FastAPI, Request
from pydantic import BaseModel
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Odoo Website Link
WEBSITE_LINK = "https://fragrance-by-kelvin.odoo.com/"

PRODUCTS_CACHE = []
LAST_FETCH_TIME = 0
CACHE_DURATION = 3600

# Order Form စကားပြော အဆင့်များ မှတ်ထားရန် Cache
USER_STATES = {}

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
        data = worksheet.get_all_records()
        PRODUCTS_CACHE = data
        LAST_FETCH_TIME = time.time()
        return PRODUCTS_CACHE
    except Exception as e:
        print(f"Sheet Error: {e}")
        return PRODUCTS_CACHE

def save_order_to_sheet(order_data):
    try:
        sheet = get_google_sheet_data()
        try:
            worksheet = sheet.worksheet("Orders")
        except:
            worksheet = sheet.worksheet("Sheet2")
            
        row = [
            order_data.get("name", ""),
            order_data.get("phone", ""),
            order_data.get("address", ""),
            order_data.get("product", ""),
            order_data.get("payment", ""),
            order_data.get("slip_file_id", ""),
            time.strftime("%Y-%m-%d %H:%M:%S")
        ]
        worksheet.append_row(row)
        return True
    except Exception as e:
        print(f"Error saving order: {e}")
        return False

class TelegramUpdate(BaseModel):
    update_id: int
    message: dict = None

@app.post("/")
async def webhook(update: TelegramUpdate):
    if not update.message:
        return {"status": "ok"}
    
    chat_id = update.message["chat"]["id"]
    state = USER_STATES.get(chat_id, {})
    
    # ဓာတ်ပုံ (Payment Slip Screenshot) ပို့လာပါက အလိုအလျောက် Sheet ထဲ သိမ်းမည်
    if "photo" in update.message:
        if state.get("step") == "WAITING_SLIP":
            photo = update.message["photo"][-1]
            file_id = photo["file_id"]
            state["slip_file_id"] = file_id
            
            success = save_order_to_sheet(state)
            if success:
                reply_msg = (
                    "Order အောင်မြင်စွာ တင်ပြီးပါပြီရှင့်!\n\n"
                    f"အမည်: {state.get('name')}\n"
                    f"ဖုန်း: {state.get('phone')}\n"
                    f"လိပ်စာ: {state.get('address')}\n"
                    f"ရေမွေး: {state.get('product')}\n"
                    f"Payment: {state.get('payment')}\n\n"
                    "ကျေးဇူးအထူးတင်ရှိပါတယ်။ Kelvin Fragrance မှ မကြာမီ ဆက်သွယ်ပေးပါမည်ရှင့်။"
                )
            else:
                reply_msg = "Order သိမ်းဆည်းရာတွင် အမှားအယွင်းရှိခဲ့ပါသည်။ Admin ထံ တိုက်ရိုက် အကြောင်းကြားပေးပါမည်။"
                
            USER_STATES[chat_id] = {}
            send_telegram_message(chat_id, reply_msg)
            return {"status": "ok"}

    user_text = update.message.get("text", "").strip()
    if not user_text:
        return {"status": "ok"}

    # Start Command
    if user_text == "/start":
        USER_STATES[chat_id] = {}
        send_telegram_message(
            chat_id, 
            f"မင်္ဂလာပါရှင်! Kelvin Fragrance Online Shop မှ ကြိုဆိုပါတယ်။\n\n"
            f"လိုချင်သော ရေမွေးအမည်ကို ရိုက်ထည့်ပြီး ရှာဖွေနိုင်ပါတယ်ရှင့်။\n"
            f"ရေမွေးအကုန်လုံးကို ကြည့်ရှုလိုပါက အောက်ပါ Website တွင် ဝင်ရောက်ကြည့်ရှုနိုင်ပါတယ်ရှင့် -\n"
            f"{WEBSITE_LINK}\n\n"
            f"Order တင်လိုပါက 'Order တင်မည်' ဟု ရိုက်ပို့ပေးပါနော်။"
        )
        return {"status": "ok"}

    current_step = state.get("step")

    # Order တင်သည့် Flow စတင်ခြင်း
    if user_text.lower() in ["order", "မှာမည်", "ဝယ်မည်", "order တင်မည်"] and not current_step:
        USER_STATES[chat_id] = {"step": "WAITING_PRODUCT"}
        send_telegram_message(chat_id, "Order တင်ရန်\n\nမှာယူလိုသည့် ရေမွေးအမည်နှင့် ပမာဏ (ဥပမာ- Sauvage 10ml) ကို ရေးပေးပါနော်။")
        return {"status": "ok"}

    if current_step == "WAITING_PRODUCT":
        USER_STATES[chat_id] = {"step": "WAITING_NAME", "product": user_text}
        send_telegram_message(chat_id, "မှာယူသူ၏ အမည် ကို ရေးပေးပါနော်။")
        return {"status": "ok"}

    elif current_step == "WAITING_NAME":
        state["name"] = user_text
        state["step"] = "WAITING_PHONE"
        USER_STATES[chat_id] = state
        send_telegram_message(chat_id, "ဆက်သွယ်ရန် ဖုန်းနံပါတ် ကို ရေးပေးပါနော်။")
        return {"status": "ok"}

    elif current_step == "WAITING_PHONE":
        state["phone"] = user_text
        state["step"] = "WAITING_ADDRESS"
        USER_STATES[chat_id] = state
        send_telegram_message(chat_id, "ပို့ဆောင်ပေးရမည့် နေရပ်လိပ်စာ ကို ရေးပေးပါနော်။")
        return {"status": "ok"}

    elif current_step == "WAITING_ADDRESS":
        state["address"] = user_text
        state["step"] = "WAITING_PAYMENT"
        USER_STATES[chat_id] = state
        
        reply_payment = (
            "Payment Type ရွေးချယ်ပါ\n\n"
            "1. KBZ Pay\n"
            "2. Wave Pay\n\n"
            "ငွေလွှဲမည့် Payment အမျိုးအစားကို ရိုက်ပို့ပေးပါနော်။"
        )
        send_telegram_message(chat_id, reply_payment)
        return {"status": "ok"}

    elif current_step == "WAITING_PAYMENT":
        state["payment"] = user_text
        state["step"] = "WAITING_SLIP"
        USER_STATES[chat_id] = state
        send_telegram_message(chat_id, "ငွေလွှဲပြီးပါက ငွေလွှဲ Screenshot (Slip) ဓာတ်ပုံကို ပို့ပေးပါနော်။")
        return {"status": "ok"}

    # ၁။ ပထမဦးစွာ Google Sheet ထဲတွင် ရေမွေးအမည် တိုက်ဆိုင်မှု ရှိမရှိ စစ်ဆေးမည်
    try:
        products = load_products_cached()
        query = user_text.lower()
        
        matched_products = []
        for p in products:
            prod_name = str(p.get("Product Name") or p.get("Name") or p.get("product") or "").lower()
            if prod_name and (query in prod_name or prod_name in query):
                matched_products.append(p)
                
        if matched_products:
            reply_text = "ရှာတွေ့သော ရေမွေးများ:\n\n"
            for p in matched_products[:5]:
                name = p.get("Product Name") or p.get("Name") or p.get("product") or "Unknown"
                price_5 = p.get("5ml Price") or p.get("5ml") or "-"
                price_10 = p.get("10ml Price") or p.get("10ml") or "-"
                reply_text += f"🌸 {name}\n   - 5ml: {price_5}\n   - 10ml: {price_10}\n\n"
            reply_text += f"မှာယူလိုပါက 'Order တင်မည်' ဟု ရိုက်ပို့ပါ။\nရေမွေးအစုံကြည့်ရန် 👉 {WEBSITE_LINK}"
            
            send_telegram_message(chat_id, reply_text)
            return {"status": "ok"}
            
    except Exception as e:
        print(f"Sheet Search Error: {e}")

    # ၂။ ရေမွေးစာရင်းထဲ မတွေ့ပါက (သို့မဟုတ် အထွေထွေစကားပြောဆိုမှု ဖြစ်ပါက) Gemini AI သို့ ပို့၍ ဖော်ရွေစွာ ဖြေခိုင်းမည်
    try:
        ai_prompt = (
            "သင်သည် Kelvin Fragrance Online Shop ၏ ဖော်ရွေသော ရေမွေးဆိုင် ကိုယ်စားလှယ် ဖြစ်သည်။ "
            "Customer က အထွေထွေ မေးခွန်းမေးခြင်း (သို့မဟုတ်) နှုတ်ဆက်ခြင်း ဖြစ်သည်။ "
            "ဖော်ရွေစွာ မြန်မာဘာသာဖြင့် တုံ့ပြန်ပါ။ ရေမွေးအကုန်ကြည့်ချင်ပါက "
            f"{WEBSITE_LINK} တွင် ကြည့်နိုင်ကြောင်း ထည့်ပြောပါ။ Markdown ကို အသုံးမပြုပါနဲ့။\n\n"
            f"Customer ပြောသည်မှာ: {user_text}"
        )
        
        gemini_url = f"https://generativelanguage.googleapis.com/v1/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [
                {
                    "parts": [{"text": ai_prompt}]
                }
            ]
        }
        
        response = requests.post(gemini_url, json=payload, timeout=20)
        res_data = response.json()
        
        if response.status_code == 200 and "candidates" in res_data:
            reply_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            reply_text = (
                f"မင်္ဂလာပါရှင့်! 🙏 Kelvin Fragrance Online Shop မှ ကြိုဆိုပါတယ်။\n"
                f"ရေမွေးအစုံကို ကြည့်ရှုလိုပါက 👉 {WEBSITE_LINK} တွင် ဝင်ရောက်ကြည့်ရှုနိုင်ပါတယ်ရှင့်။"
            )
    except Exception as e:
        reply_text = (
            f"မင်္ဂလာပါရှင့်! 🙏 Kelvin Fragrance Online Shop မှ ကြိုဆိုပါတယ်။\n"
            f"ရေမွေးအစုံကို ကြည့်ရှုလိုပါက 👉 {WEBSITE_LINK} တွင် ဝင်ရောက်ကြည့်ရှုနိုင်ပါတယ်ရှင့်။"
        )

    send_telegram_message(chat_id, reply_text)
    return {"status": "ok"}

def send_telegram_message(chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    requests.post(url, json=payload)

@app.get("/")
async def root():
    return {"status": "Telegram Bot is running smoothly!"}
