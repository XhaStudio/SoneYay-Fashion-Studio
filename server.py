import os
import json
import uuid
import threading
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
import telebot
from telebot import types

load_dotenv()

PORT = int(os.getenv("PORT", 3000))
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
NGROK_AUTHTOKEN = os.getenv("NGROK_AUTHTOKEN")

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN is missing from .env")

WALLETS = {
    "KBZPay": {
        "label": "KBZPay",
        "name": os.getenv("KBZPAY_NAME", ""),
        "number": os.getenv("KBZPAY_NUMBER", ""),
    },
    "WavePay": {
        "label": "WavePay",
        "name": os.getenv("WAVEPAY_NAME", ""),
        "number": os.getenv("WAVEPAY_NUMBER", ""),
    },
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
ORDERS_FILE = os.path.join(BASE_DIR, "orders.json")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

orders_lock = threading.Lock()

# ---------- Simple JSON-file order store ----------


def load_orders():
    try:
        with open(ORDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_orders(orders):
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, indent=2, ensure_ascii=False)


def find_pending_wallet_order(orders, user_id):
    """Most recent order from this user still waiting on a payment screenshot."""
    candidates = [
        o for o in orders.values()
        if str(o.get("userId")) == str(user_id) and o.get("status") == "awaiting_payment"
    ]
    candidates.sort(key=lambda o: o.get("createdAt", ""), reverse=True)
    return candidates[0] if candidates else None


def format_order_summary(order):
    lines = "\n".join(
        f"- {i['title']} ({i['color']}, {i['size']}) x{i['qty']}" for i in order["items"]
    )
    return (
        f"{lines}\n\n"
        f"*Total:* ${order['total']}\n"
        f"*Payment:* {order['paymentMethod']}\n"
        f"*Address:* {order['address']}"
    )


# ---------- Telegram bot ----------

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)


@bot.message_handler(commands=["start"])
def handle_start(message):
    markup = types.InlineKeyboardMarkup()
    if WEBAPP_URL:
        markup.add(
            types.InlineKeyboardButton(
                "🛍️ Open Shop WebApp", web_app=types.WebAppInfo(WEBAPP_URL)
            )
        )
    bot.reply_to(
        message,
        "Welcome to our Fashion Shop! Click below to browse products:",
        reply_markup=markup,
    )


@bot.message_handler(commands=["whoami"])
def handle_whoami(message):
    bot.reply_to(message, f"Your Telegram ID: {message.from_user.id}")


# Fallback path: customer can still send the screenshot directly in the chat
# (in addition to the in-app upload box in the WebApp).
@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    user_id = message.from_user.id
    with orders_lock:
        orders = load_orders()
        order = find_pending_wallet_order(orders, user_id)
        if not order:
            bot.reply_to(
                message,
                "မှတ်ပုံတင်ထားသော အော်ဒါ မရှိသေးပါ။ ပထမဆုံး Shop ထဲမှ အော်ဒါ တင်ပေးပါ။",
            )
            return
        file_id = message.photo[-1].file_id
        order["proofFileId"] = file_id
        order["status"] = "proof_submitted"
        orders[order["id"]] = order
        save_orders(orders)

    bot.reply_to(
        message, "✅ ငွေလွှဲ Screenshot လက်ခံရရှိပါပြီ။ အတည်ပြုပြီးပါက အကြောင်းကြားပေးပါမည်။"
    )
    notify_admin_with_proof(order, file_id_or_obj=file_id, first_name=message.from_user.first_name)


def notify_admin_with_proof(order, file_id_or_obj, first_name=""):
    """file_id_or_obj can be a Telegram file_id (str) or an open file object."""
    if not ADMIN_CHAT_ID:
        return
    caption = (
        "🧾 *Payment proof received*\n\n"
        f"Order: `{order['id']}`\n"
        f"From: {first_name or ''} ({order['userId']})\n\n"
        f"{format_order_summary(order)}"
    )
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Approve", callback_data=f"approve:{order['id']}"),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"reject:{order['id']}"),
    )
    try:
        bot.send_photo(
            ADMIN_CHAT_ID,
            file_id_or_obj,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=markup,
        )
    except Exception as e:
        print("Failed to notify admin:", e)


@bot.callback_query_handler(
    func=lambda call: call.data and (call.data.startswith("approve:") or call.data.startswith("reject:"))
)
def handle_admin_decision(call):
    action, order_id = call.data.split(":", 1)

    if not ADMIN_CHAT_ID or str(call.from_user.id) != str(ADMIN_CHAT_ID):
        bot.answer_callback_query(call.id, "Not authorized", show_alert=True)
        return

    with orders_lock:
        orders = load_orders()
        order = orders.get(order_id)
        if not order:
            bot.answer_callback_query(call.id, "Order not found", show_alert=True)
            return

        if action == "approve":
            order["status"] = "paid"
            orders[order_id] = order
            save_orders(orders)
            suffix = "\n\n✅ *APPROVED*"
            customer_msg = (
                "✅ *Payment Confirmed!*\n\nYour order is now being processed.\n\n"
                f"{format_order_summary(order)}"
            )
        else:
            order["status"] = "awaiting_payment"
            order["proofFileId"] = None
            orders[order_id] = order
            save_orders(orders)
            suffix = "\n\n❌ *REJECTED — waiting on resend*"
            customer_msg = (
                "❌ ငွေပေးချေမှု Screenshot ကို အတည်မပြုနိုင်ပါ။ "
                "ကျေးဇူးပြု၍ မှန်ကန်သော Screenshot ကို ပြန်လည်ပို့ပေးပါ။"
            )

    try:
        bot.send_message(order["userId"], customer_msg, parse_mode="Markdown")
    except Exception as e:
        print("Failed to notify customer:", e)

    try:
        new_caption = (call.message.caption or "") + suffix
        bot.edit_message_caption(
            new_caption,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
        )
    except Exception as e:
        print("Failed to edit admin message:", e)

    bot.answer_callback_query(call.id, "Order approved" if action == "approve" else "Order rejected")


# ---------- HTTP API (Flask) ----------

app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")


@app.route("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/api/payment-info")
def payment_info():
    return jsonify({"wallets": WALLETS})


@app.route("/api/order", methods=["POST"])
def create_order():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("userId")
    items = data.get("items")
    total = data.get("total")
    payment_method = data.get("paymentMethod")
    address = data.get("address")

    if not items:
        return jsonify({"success": False, "message": "Cart is empty"}), 400
    if not user_id:
        return jsonify({"success": False, "message": "Missing Telegram user"}), 400

    is_wallet_payment = payment_method in ("KBZPay", "WavePay")

    order = {
        "id": uuid.uuid4().hex[:8],
        "userId": user_id,
        "items": items,
        "total": total,
        "paymentMethod": payment_method,
        "address": address,
        "status": "awaiting_payment" if is_wallet_payment else "confirmed",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    with orders_lock:
        orders = load_orders()
        orders[order["id"]] = order
        save_orders(orders)

    try:
        if is_wallet_payment:
            wallet = WALLETS[payment_method]
            bot.send_message(
                user_id,
                (
                    "🛍️ *Order Received — Awaiting Payment*\n\n"
                    f"{format_order_summary(order)}\n\n"
                    f"Order ID: `{order['id']}`\n\n"
                    f"Please transfer ${order['total']} to:\n"
                    f"*{wallet['label']}*\nName: {wallet['name']}\nNumber: {wallet['number']}\n\n"
                    "ငွေလွှဲပြီးပါက Screenshot ကို WebApp ထဲက Upload box မှ (သို့) ဒီ chat ထဲ ပို့ပေးပါ။"
                ),
                parse_mode="Markdown",
            )
        else:
            bot.send_message(
                user_id,
                f"🛍️ *Order Confirmed!*\n\n{format_order_summary(order)}",
                parse_mode="Markdown",
            )
    except Exception as e:
        print("Failed to send Telegram message:", e)

    return jsonify({"success": True, "orderId": order["id"], "status": order["status"]})


@app.route("/api/order/<order_id>", methods=["GET"])
def get_order(order_id):
    orders = load_orders()
    order = orders.get(order_id)
    if not order:
        return jsonify({"success": False, "message": "Order not found"}), 404
    return jsonify({"success": True, "status": order["status"]})


ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


@app.route("/api/order/<order_id>/proof", methods=["POST"])
def upload_proof(order_id):
    """Called by the WebApp's upload box right after an order is created."""
    file = request.files.get("proof")
    if not file or not file.filename:
        return jsonify({"success": False, "message": "No file uploaded"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        return jsonify({"success": False, "message": "Unsupported file type"}), 400

    with orders_lock:
        orders = load_orders()
        order = orders.get(order_id)
        if not order:
            return jsonify({"success": False, "message": "Order not found"}), 404

        saved_path = os.path.join(UPLOADS_DIR, f"{order_id}{ext}")
        file.save(saved_path)

        order["status"] = "proof_submitted"
        order["proofFilePath"] = saved_path
        orders[order_id] = order
        save_orders(orders)

    try:
        with open(saved_path, "rb") as f:
            notify_admin_with_proof(order, file_id_or_obj=f)
    except Exception as e:
        print("Failed to notify admin:", e)

    try:
        bot.send_message(
            order["userId"],
            "✅ ငွေလွှဲ Screenshot လက်ခံရရှိပါပြီ။ အတည်ပြုပြီးပါက အကြောင်းကြားပေးပါမည်။",
        )
    except Exception as e:
        print("Failed to notify customer:", e)

    return jsonify({"success": True})


# ---------- Startup: bot polling + ngrok tunnel + Flask ----------


def start_bot_polling():
    bot.infinity_polling(skip_pending=True)


def start_ngrok():
    global WEBAPP_URL
    from pyngrok import ngrok, conf

    if NGROK_AUTHTOKEN:
        conf.get_default().auth_token = NGROK_AUTHTOKEN
    tunnel = ngrok.connect(PORT, "http")
    WEBAPP_URL = tunnel.public_url.replace("http://", "https://")
    print("=" * 46)
    print(f"YOUR NGROK WEBAPP_URL: {WEBAPP_URL}")
    print("=" * 46)


if __name__ == "__main__":
    threading.Thread(target=start_bot_polling, daemon=True).start()

    if NGROK_AUTHTOKEN:
        try:
            start_ngrok()
        except Exception as e:
            print("Ngrok error:", e)
    else:
        print(f"WEBAPP_URL from .env: {WEBAPP_URL or '(not set)'}")

    print(f"Flask server running on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
