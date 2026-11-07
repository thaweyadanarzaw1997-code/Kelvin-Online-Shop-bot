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
                    "🎉 Order အောင်မြင်စွာ တင်ပြီးပါပြီရှင့်!\n\n"
                    f"👤 အမည်: {state.get('name')}\n"
                    f"📞 ဖုန်း: {state.get('phone')}\n"
                    f"📍 လိပ်စာ: {state.get('address')}\n"
                    f"🌸 ရေမွေး: {state.get('product')}\n"
                    f"💳 Payment: {state.get('payment')}\n\n"
                    "ကျေးဇူးအထူးတင်ရှိပါတယ်။ Kelvin Fragrance မှ မကြာမီ ဆက်သွယ်ပေးပါမည်ရှင့်။"
                )
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
            f"🔍 လိုချင်သော ရေမွေးအကြောင်း၊ အနံ့အသက် သို့မဟုတ် အမျိုးအစားများကို AI ဖြင့် မေးမြန်းနိုင်ပါတယ်။\n"
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
        send_telegram_message(chat_id, "📞 ဆက်သွယ်ရန် **ဖုန်းနံပါတ်** ကို ရေးပေးပါနော်።")
        return {"status": "ok"}

    elif current_step == "WAITING_PHONE":
        state["phone"] = user_text
        state["step"] = "WAITING_ADDRESS"
        USER_STATES[chat_id] = state
        send_telegram_message(chat_id, "📍 ပို့ဆောင်ပေးရမည့် နေရပ်လိပ်စာ ကို ရေးပေးပါနော်።")
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

    # -------------------------------------------------------------
    # SMART AI HYBRID SYSTEM (Timeout လုံးဝမဖြစ်အောင် Filter လုပ်ပြီးမှ AI သို့ ပို့မည်)
    # -------------------------------------------------------------
    try:
        products = load_products_cached()
        matched_summary = []
        text_lower = user_text.lower()
        keywords = text_lower.split()
        
        # Google Sheet ထဲက Customer မေးတဲ့ စကားလုံးနဲ့ ကိုက်ညီတဲ့ ရေမွေးတွေကိုပဲ ယူမယ်
        for p in products:
            prod_name = str(p.get("Product Name") or p.get("Name") or p.get("product") or "").lower()
            if prod_name and any(kw in prod_name for kw in keywords):
                name = p.get("Product Name") or p.get("Name") or p.get("product") or "Unknown"
                p5 = p.get("5ml Price") or p.get("5ml") or "-"
                p10 = p.get("10ml Price") or p.get("10ml") or "-"
                matched_summary.append(f"- ရေမွေးအမည်: {name} | 5ml ဈေး: {p5} | 10ml ဈေး: {p10}")
                
        products_text = "\n".join(matched_summary[:12]) if matched_summary else "ဆိုင်တွင် ရေမွေးအမျိုးမျိုး ရရှိနိုင်ပါသည်။"
        
        ai_prompt = (
            "သင်သည် Kelvin Fragrance Online Shop ၏ ဖော်ရွေသော ရေမွေးဆိုင် အရောင်းကျွမ်းကျင်သူ AI ဖြစ်သည်။ "
            "Customer က ရေမွေးအကြောင်း၊ အနံ့အသက် သို့မဟုတ် ရွေးချယ်စရာများကို မေးမြန်းထားသည်။ "
            "အောက်ပါဆိုင်ရှိ ရေမွေးအချက်အလက်များကို အခြေခံ၍ Customer ၏ မေးခွန်းကို မြန်မာဘာသာဖြင့် ဖော်ရွေကျွမ်းကျင်စွာ ရှင်းပြပါ။ "
            f"ရေမွေးအကုန်ကြည့်ချင်ပါက {WEBSITE_LINK} တွင် ကြည့်နိုင်ကြောင်း ထည့်ပြောပါ။ "
            "Markdown formatting (*, _, etc.) ကို လုံးဝမသုံးပါနဲ့။\n\n"
            f"ဆိုင်တွင်ရှိသော သက်ဆိုင်ရာ ရေမွေးအချက်အလက်များ:\n{products_text}\n\n"
            f"Customer ၏ မေးခွန်း: {user_text}"
        )
        
        # Gemini AI ကို ခေါ်ယူခြင်း (v1beta endpoint & gemini-1.5-flash)
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": ai_prompt}]}]}
        
        response = requests.post(gemini_url, json=payload, timeout=20)
        res_data = response.json()
        
        if response.status_code == 200 and "candidates" in res_data:
            reply_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            # AI ဘက်က တစ်ခုခု Error တက်ရင်တောင် Sheet ထဲက တွေ့ထားတာတွေကို တိုက်ရိုက်ထုတ်ပြပေးမယ်
            if matched_summary:
                reply_text = "✨ **ရှာတွေ့သော ရေမွေးများ:**\n\n"
                for s in matched_summary:
                    reply_text += f"🌸 {s}\n"
                reply_text += f"\n🛒 မှာယူလိုပါက **'Order တင်မည်'** ဟု ရိုက်ပို့ပါ။\n🌐 ရေမွေးအစုံကြည့်ရန် 👉 {WEBSITE_LINK}"
            else:
                reply_text = (
                    f"မင်္ဂလာပါရှင့်! 🙏 Kelvin Fragrance Online Shop မှ ကြိုဆိုပါတယ်။\n"
                    f"🌐 ရေမွေးအကုန်လုံးကို အသေးစိတ်ကြည့်ရှုလိုပါက 👉 {WEBSITE_LINK} တွင် ဝင်ရောက်ကြည့်ရှုနိုင်ပါတယ်ရှင့်။\n"
                    f"🛒 Order တင်လိုပါက **'Order တင်မည်'** ဟု ရိုက်ပို့ပေးပါနော်။"
                )
            
    except Exception as e:
        reply_text = (
            f"မင်္ဂလာပါရှင့်! 🙏 Kelvin Fragrance မှ ကြိုဆိုပါတယ်။\n"
            f"🌐 ရေမွေးအစုံကို ကြည့်ရှုလိုပါက 👉 {WEBSITE_LINK} တွင် ဝင်ရောက်ကြည့်ရှုနိုင်ပါတယ်ရှင့်။\n"
            f"🛒 Order တင်လိုပါက **'Order တင်မည်'** ဟု ရိုက်ပို့ပေးပါနော်။"
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
