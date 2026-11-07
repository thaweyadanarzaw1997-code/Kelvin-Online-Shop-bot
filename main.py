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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Website Link
WEBSITE_LINK = "https://fragrance-by-kelvin.odoo.com/"

PRODUCTS_CACHE = []
LAST_FETCH_TIME = 0
CACHE_DURATION = 3600

# User ၏ စကားပြော State များကို မှတ်ထားရန် Cache (Order Form အဆင့်များအတွက်)
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
    
    # ဓာတ်ပုံ (Payment Slip) ပို့လာသည့်အခါ စစ်ဆေးခြင်း
    if "photo" in update.message:
        if state.get("step") == "WAITING_SLIP":
            photo = update.message["photo"][-1]
            file_id = photo["file_id"]
            state["slip_file_id"] = file_id
            
            # Sheet ထဲသို့ Order စာရင်းသိမ်းခြင်း
            success = save_order_to_sheet(state)
            if success:
                reply_msg = (
                    "🎉 **Order အောင်မြင်စွာ တင်ပြီးပါပြီရှင့်!**\n\n"
                    f"👤 အမည်: {state.get('name')}\n"
                    f"📞 ဖုန်း: {state.get('phone')}\n"
                    f"📍 လိပ်စာ: {state.get('address')}\n"
                    f"🌸 ရေမွေး: {state.get('product')}\n"
                    f"💳 Payment: {state.get('payment')}\n\n"
                    "ကျေးဇူးအထူးတင်ရှိပါတယ်။ Kelvin Fragrance မှ မကြာမီ စာပို့၍ အကြောင်းပြန်ပေးပါမည်ရှင့်။"
                )
            else:
                reply_msg = "⚠️ Order သိမ်းဆည်းရာတွင် အမှားအယွင်းရှိခဲ့ပါသည်။ လူကြီးမင်း၏ Order ကို Admin သို့ တိုက်ရိုက် ပေးပို့ပေးပါမည်။"
                
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
            f"မင်္ဂလာပါရှင်! 🙏 **Kelvin Fragrance Online Shop** မှ ကြိုဆိုပါတယ်။\n\n"
            f"စိတ်ကြိုက် ရေမွေးနံ့များကို မေးမြန်းနိုင်သလို ရေမွေးအကုန်လုံးကို ကြည့်ရှုလိုပါက အောက်ပါ လင့်ခ်မှာ ကြည့်ရှုနိုင်ပါတယ်ရှင့် -\n"
            f"🔗 {WEBSITE_LINK}"
        )
        return {"status": "ok"}

    # Order တင်သည့် Process လမ်းကြောင်း (Interactive Order Form Flow)
    current_step = state.get("step")

    if user_text.lower() in ["order", "မှာမည်", "ဝယ်မည်", "order တင်မည်"] and not current_step:
        USER_STATES[chat_id] = {"step": "WAITING_PRODUCT"}
        send_telegram_message(chat_id, "🛒 **Order တင်ရန်**\n\nလိုချင်သည့် ရေမွေးအမည်နှင့် ပမာဏ (ဥပမာ- Sauvage 10ml) ကို ရေးပေးပါနော်။")
        return {"status": "ok"}

    if current_step == "WAITING_PRODUCT":
        USER_STATES[chat_id] = {"step": "WAITING_NAME", "product": user_text}
        send_telegram_message(chat_id, "📝 မှာယူသူ၏ **အမည်** ကို ရေးပေးပါနော်။")
        return {"status": "ok"}

    elif current_step == "WAITING_NAME":
        state["name"] = user_text
        state["step"] = "WAITING_PHONE"
        USER_STATES[chat_id] = state
        send_telegram_message(chat_id, "📞 ဆက်သွယ်ရန် **ဖုန်းနံပါတ်** လေး ပေးပို့ပေးပါနော်။")
        return {"status": "ok"}

    elif current_step == "WAITING_PHONE":
        state["phone"] = user_text
        state["step"] = "WAITING_ADDRESS"
        USER_STATES[chat_id] = state
        send_telegram_message(chat_id, "📍 ပို့ဆောင်ပေးရမည့် **နေရပ်လိပ်စာ** ကို ပို့ပေးပါနော်။")
        return {"status": "ok"}

    elif current_step == "WAITING_ADDRESS":
        state["address"] = user_text
        state["step"] = "WAITING_PAYMENT"
        USER_STATES[chat_id] = state
        
        reply_payment = (
            "💳 **Payment Type ရွေးချယ်ပါ**\n\n"
            "1️⃣ KBZ Pay\n"
            "2️⃣ Wave Pay\n\n"
            "ငွေလွှဲလိုသည့် အမျိုးအစားကို ရိုက်ပို့ပေးပါနော်။"
        )
        send_telegram_message(chat_id, reply_payment)
        return {"status": "ok"}

    elif current_step == "WAITING_PAYMENT":
        state["payment"] = user_text
        state["step"] = "WAITING_SLIP"
        USER_STATES[chat_id] = state
        send_telegram_message(chat_id, "📸 ငွေလွှဲပြီးပါက **ငွေလွှဲ Screenshot (Payment Slip)** ကို ဓာတ်ပုံ ပို့ပေးပါနော်။")
        return {"status": "ok"}

    # AI စကားပြောခြင်း (Customer မေးသည့် ရေမွေးကိုသာ သီးသန့် ရှာဖွေပြသမည်)
    try:
        products = load_products_cached()
        
        system_content = (
            "သင်သည် Kelvin Fragrance Online Shop ၏ ဖော်ရွေသော AI ရေမွေး အရောင်းကျွမ်းကျင်သူ ဖြစ်သည်။ "
            "စည်းမျဉ်းများ -\n"
            "1. Customer မေးမြန်းသည့် သို့မဟုတ် နှစ်သက်သည့် ရနံ့/ရေမွေး အမျိုးအစားကိုသာ စာရင်းထဲမှ ရွေးထုတ်၍ ဈေးနှုန်းနှင့်အတူ မြန်မာဘာသာဖြင့် ဖော်ရွေစွာ ညွှန်းဆိုပါ။ စာရင်းတစ်ခုလုံးကို အကုန် မပြပါနှင့်။\n"
            f"2. ရေမွေးအကုန်လုံးကို ကြည့်ချင်ပါက {WEBSITE_LINK} တွင် ဝင်ရောက်ကြည့်ရှုနိုင်ကြောင်း အသိပေးပါ။\n"
            "3. Customer က ဝယ်ယူလိုကြောင်း ပြောပါက 'Order တင်မည်' ဟု ရိုက်ပို့ခိုင်းပါ။\n"
            "ရေမွေးစာရင်း: " + json.dumps(products[:40], ensure_ascii=False)
        )
        
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com",
            "X-Title": "Kelvin Perfume Bot"
        }
        
        payload = {
            "model": "google/gemma-2-9b-it:free",
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_text}
            ],
            "temperature": 0.5,
            "max_tokens": 512
        }
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=15
        )
        
        res_data = response.json()
        if response.status_code == 200 and "choices" in res_data:
            reply_text = res_data["choices"][0]["message"]["content"]
        else:
            reply_text = f"⚠️ OpenRouter Error ({response.status_code}): {str(res_data)}"
            
    except Exception as e:
        reply_text = f"⚠️ Server Error: {str(e)}"

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
    return {"status": "Telegram Bot is running smoothly!"}
