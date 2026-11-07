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
ADMIN_CHANNEL_ID = os.getenv("ADMIN_CHANNEL_ID", "")  # Order ဝင်မည့် Admin Channel/Group ID

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
            worksheet = sheet.worksheet("Sheet4")
        except:
            worksheet = sheet.add_worksheet(title="Sheet4", rows="100", cols="10")
            
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
    
    # ဓာတ်ပုံ (Payment Slip Screenshot) ပို့လာပါက အလိုအလျောက် Sheet4 ထဲသိမ်းမည် + Admin Channel သို့ ပို့မည်
    if "photo" in update.message:
        if state.get("step") == "WAITING_SLIP":
            photo = update.message["photo"][-1]
            file_id = photo["file_id"]
            state["slip_file_id"] = file_id
            
            success = save_order_to_sheet(state)
            if success:
                reply_msg = (
                    "🎉 Order အောင်မြင်စွာ တင်ပြီးပါပြီရှင့်!\n\n"
                    f"👤 အမည်: {state.get('name')}\n"
                    f"📞 ဖုန်း: {state.get('phone')}\n"
                    f"📍 လိပ်စာ: {state.get('address')}\n"
                    f"🌸 ရေမွေး: {state.get('product')}\n"
                    f"💳 Payment: {state.get('payment')}\n\n"
                    "ကျေးဇူးအထူးတင်ရှိပါတယ်။ Kelvin Fragrance မှ မကြာမီ ဆက်သွယ်ပေးပါမည်ရှင့်။"
                )
                
                # Admin Channel သို့ Order အချက်အလက်နှင့် ဓာတ်ပုံ ပို့ခြင်း
                if ADMIN_CHANNEL_ID:
                    admin_caption = (
                        "🚨 **New Order Received! (Sheet4)**\n\n"
                        f"👤 အမည်: {state.get('name')}\n"
                        f"📞 ဖုန်း: {state.get('phone')}\n"
                        f"📍 လိပ်စာ: {state.get('address')}\n"
                        f"🌸 ရေမွေး: {state.get('product')}\n"
                        f"💳 Payment: {state.get('payment')}\n"
                        f"💬 Telegram Chat ID: {chat_id}"
                    )
                    send_telegram_photo(ADMIN_CHANNEL_ID, file_id, admin_caption)
            else:
                reply_msg = "⚠️ Order သိမ်းဆည်းရာတွင် အမှားအယွင်းရှိခဲ့ပါသည်။ Admin ထံ တိုက်ရိုက် အကြောင်းကြားပေးပါမည်။"
                
            USER_STATES[chat_id] = {}
            send_telegram_message(chat_id, reply_msg)
            return {"status": "ok"}
        else:
            send_telegram_message(chat_id, "📸 ကျေးဇူးပြု၍ Order တင်စဉ် ငွေလွှဲစလစ် (Slip) ပုံကိုသာ ပို့ပေးပါနော်။")
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
            f"🔍 လိုချင်သော ရေမွေးအမည် သို့မဟုတ် အနံ့အသက်ကို မေးမြန်းနိုင်ပါတယ်။\n"
            f"🌐 ရေမွေးအကုန်လုံးကို ကြည့်ရှုလိုပါက အောက်ပါ Website တွင် ဝင်ရောက်ကြည့်ရှုနိုင်ပါတယ်ရှင့် -\n"
            f"{WEBSITE_LINK}\n\n"
            f"🛒 Order တင်လိုပါက **'Order တင်မည်'** ဟု ရိုက်ပို့ပေးပါနော်။"
        )
        return {"status": "ok"}

    current_step = state.get("step")

    # Order တင်သည့် Flow စတင်ခြင်း
    if user_text.lower() in ["order", "မှာမည်", "ဝယ်မည်", "order တင်မည်", "ဝယ်ချင်တယ်", "မှာချင်တယ်"] and not current_step:
        USER_STATES[chat_id] = {"step": "WAITING_PRODUCT"}
        send_telegram_message(chat_id, "🛒 **Order တင်ရန်**\n\nမှာယူလိုသည့် ရေမွေးအမည်နှင့် ပမာဏ (ဥပမာ- Sauvage 10ml) ကို ရေးပေးပါနော်။")
        return {"status": "ok"}

    if current_step == "WAITING_PRODUCT":
        USER_STATES[chat_id] = {"step": "WAITING_NAME", "product": user_text}
        send_telegram_message(chat_id, "📝 မှာယူသူ၏ **အမည်** ကို ရေးပေးပါနော်။")
        return {"status": "ok"}

    elif current_step == "WAITING_NAME":
        state["name"] = user_text
        state["step"] = "WAITING_PHONE"
        USER_STATES[chat_id] = state
        send_telegram_message(chat_id, "📞 ဆက်သွယ်ရန် **ဖုန်းနံပါတ်** ကို ရေးပေးပါနော်။")
        return {"status": "ok"}

    elif current_step == "WAITING_PHONE":
        state["phone"] = user_text
        state["step"] = "WAITING_ADDRESS"
        USER_STATES[chat_id] = state
        send_telegram_message(chat_id, "📍 ပို့ဆောင်ပေးရမည့် နေရပ်လိပ်စာ ကို ရေးပေးပါနော်။")
        return {"status": "ok"}

    elif current_step == "WAITING_ADDRESS":
        state["address"] = user_text
        state["step"] = "WAITING_PAYMENT"
        USER_STATES[chat_id] = state
        
        reply_payment = (
            "💳 **Payment Type ရွေးချယ်ပါ**\n\n"
            "1️⃣ KBZ Pay\n"
            "2️⃣ Wave Pay\n\n"
            "ငွေလွှဲမည့် Payment အမျိုးအစားကို ရိုက်ပို့ပေးပါနော်။"
        )
        send_telegram_message(chat_id, reply_payment)
        return {"status": "ok"}

    elif current_step == "WAITING_PAYMENT":
        state["payment"] = user_text
        state["step"] = "WAITING_SLIP"
        USER_STATES[chat_id] = state
        send_telegram_message(chat_id, "📸 ငွေလွှဲပြီးပါက ငွေလွှဲ **Screenshot (Slip)** ဓာတ်ပုံကို ပို့ပေးပါနော်။")
        return {"status": "ok"}

    # နှုတ်ဆက်စာများ သို့မဟုတ် ရေမွေးနှင့် မသက်ဆိုင်သော စကားပြောဆိုမှုများအတွက် AI မခေါ်ဘဲ သပ်သပ်ရပ်ရပ် ဖြေမည်
    text_lower = user_text.lower()
    greetings = ["hi", "hello", "ဟိုင်", "ဟယ်လို", "မင်္ဂလာပါ", "နေကောင်းလား", "ဟေး", "hey"]
    if any(g in text_lower for g in greetings) and len(text_lower.split()) <= 3:
        send_telegram_message(
            chat_id,
            f"မင်္ဂလာပါရှင်! 🙏 Kelvin Fragrance Online Shop မှ ကြိုဆိုပါတယ်။\n\n"
            f"သိလိုသည့် ရေမွေးအမည်ကို မေးမြန်းနိုင်ပါတယ်။ ရေမွေးအစုံကို ကြည့်ရှုလိုပါက 👉 {WEBSITE_LINK} တွင် ကြည့်နိုင်ပါတယ်။\n\n"
            f"🛒 Order တင်လိုပါက **'Order တင်မည်'** ဟု ရိုက်ပို့ပေးပါနော်။"
        )
        return {"status": "ok"}

    # OpenRouter DeepSeek AI (Customer က ရေမွေးအကြောင်း သို့မဟုတ် အနံ့အသက် တိတိကျကျ မေးမှသာ အလုပ်လုပ်မည်)
    try:
        products = load_products_cached()
        keywords = text_lower.split()
        
        matched_products = []
        for p in products:
            prod_name = str(p.get("Product Name") or p.get("Name") or "").lower()
            if prod_name and any(kw in prod_name for kw in keywords):
                matched_products.append(p)
                
        # Customer မေးမြန်းသည့် ရေမွေးကို တွေ့မှသာ ၎င်းအချက်အလက်ကို ပို့မည်၊ မတွေ့ပါက ပထမဆုံး အစုံကို ပို့မည်
        selected_products = matched_products if matched_products else products[:20]
        
        summary_products = [
            {
                "name": p.get("Product Name"),
                "price_5ml": p.get("5ml Price"),
                "price_10ml": p.get("10ml Price"),
                "price_30ml": p.get("30ml Price"),
                "category": p.get("Category"),
                "description": p.get("Description")
            }
            for p in selected_products
        ]

        system_content = (
            "သင်သည် Kelvin Fragrance Online Shop ၏ ဖော်ရွေကျွမ်းကျင်သော ရေမွေးအရောင်းကိုယ်စားလှယ် ဖြစ်သည်။ "
            "Customer ၏ မေးခွန်းကို အခြေခံ၍ အောက်ပါ ရေမွေးစာရင်းထဲမှ သက်ဆိုင်ရာ အချက်အလက်များကို မြန်မာဘာသာဖြင့် တိကျဖော်ရွေစွာ ဖြေကြားပါ။ "
            "စည်းမျဉ်းများ- "
            "1. မြန်မာစာ သတ်ပုံ၊ သဒ္ဒါ မှန်ကန်စေရန် ရေးသားပါ။ "
            "2. ဈေးနှုန်းများ (5ml, 10ml, 30ml) နှင့် ရေမွေးအမည်များကို ရှင်းလင်းစွာ ဖော်ပြပါ။ "
            f"3. ရေမွေးအကုန်လုံးကို ကြည့်ချင်ပါက Website ({WEBSITE_LINK}) တွင် ကြည့်နိုင်ကြောင်း ညွှန်းဆိုပါ။ "
            "4. ဝယ်ယူလိုပါက 'Order တင်မည်' ဟု ရိုက်ပို့ရန် ပြောပြပါ။\n\n"
            "ရေမွေးစာရင်း: " + json.dumps(summary_products, ensure_ascii=False)
        )
        
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com",
            "X-Title": "Kelvin Perfume Bot"
        }
        
        payload = {
            "model": "deepseek/deepseek-chat",
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_text}
            ],
            "temperature": 0.5,
            "max_tokens": 500
        }
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=18
        )
        
        res_data = response.json()
        if response.status_code == 200 and "choices" in res_data:
            reply_text = res_data["choices"][0]["message"]["content"]
        else:
            reply_text = f"🌐 ရေမွေးအစုံကို ကြည့်ရှုလိုပါက 👉 {WEBSITE_LINK} တွင် ဝင်ရောက်ကြည့်ရှုနိုင်ပါတယ်ရှင့်။ Order တင်လိုပါက 'Order တင်မည်' ဟု ရိုက်ပို့ပေးပါ။"
            
    except Exception as e:
        reply_text = f"🌐 ရေမွေးအစုံကို ကြည့်ရှုလိုပါက 👉 {WEBSITE_LINK} တွင် ဝင်ရောက်ကြည့်ရှုနိုင်ပါတယ်ရှင့်။ Order တင်လိုပါက 'Order တင်မည်' ဟု ရိုက်ပို့ပေးပါ။"

    send_telegram_message(chat_id, reply_text)
    return {"status": "ok"}

def send_telegram_message(chat_id: [int, str], text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    requests.post(url, json=payload)

def send_telegram_photo(chat_id: [int, str], photo_file_id: str, caption: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": photo_file_id,
        "caption": caption
    }
    requests.post(url, json=payload)

@app.get("/")
async def root():
    return {"status": "Telegram Bot is running smoothly!"}
