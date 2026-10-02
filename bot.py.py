import logging
import secrets
import sqlite3
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==========================================
# ⚠️ CONFIGURATION - SETUP YOUR TOKENS HERE
# ==========================================
TOKEN = "8733510542:AAGg8fne6k7d9hSL9h68McBGr5IUUQQEAxQ"          # <-- Paste your token from @BotFather here
ADMIN_TELEGRAM_ID = 5826046052        # <-- Replace with your numeric Telegram ID
CHANNEL_USERNAME = "@cameraaccessory_bot" # <-- Replace with your channel username
TICKET_PRICE_ETB = 500

# Enable logging to see tracking errors in the terminal
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==========================================
# DATABASE INITIALIZATION
# ==========================================
def init_db():
    conn = sqlite3.connect("lottery.db")
    cursor = conn.cursor()
    # Table to hold finalized ticket positions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            chosen_number INTEGER UNIQUE,
            reference_code TEXT,
            payment_status TEXT DEFAULT 'PENDING'
        )
    ''')
    # Table to track temporary live carts per user session
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS carts (
            user_id INTEGER,
            chosen_number INTEGER,
            PRIMARY KEY (user_id, chosen_number)
        )
    ''')
    conn.commit()
    conn.close()

# Run database setup immediately
init_db()

# ==========================================
# HELPER: BUILD KEYBOARD PAGES WITH BATCH CART DATA
# ==========================================
def build_numbers_keyboard(user_id: int, page: int) -> InlineKeyboardMarkup:
    buttons_per_page = 50
    columns = 5
    total_slots = 450
    
    start_num = ((page - 1) * buttons_per_page) + 1
    end_num = min(start_num + buttons_per_page - 1, total_slots)
    
    conn = sqlite3.connect("lottery.db")
    cursor = conn.cursor()
    
    # Get numbers that are permanently taken or pending in other checkouts
    cursor.execute("SELECT chosen_number FROM tickets")
    taken_numbers = {row[0] for row in cursor.fetchall()}
    
    # Get numbers currently in THIS user's active shopping cart session
    cursor.execute("SELECT chosen_number FROM carts WHERE user_id = ?", (user_id,))
    cart_numbers = {row[0] for row in cursor.fetchall()}
    
    conn.close()
    
    keyboard = []
    row = []
    
    for num in range(start_num, end_num + 1):
        if num in taken_numbers:
            btn = InlineKeyboardButton(f"{num} ❌", callback_data="taken")
        elif num in cart_numbers:
            btn = InlineKeyboardButton(f"{num} 🛒", callback_data=f"toggle_{num}_{page}")
        else:
            btn = InlineKeyboardButton(f"{num}", callback_data=f"toggle_{num}_{page}")
        row.append(btn)
        
        if len(row) == columns:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    # Navigation Buttons Row
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Back", callback_data=f"page_{page-1}"))
    
    total_pages = math.ceil(total_slots / buttons_per_page)
    nav_row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="ignore"))
    
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{page+1}"))
    keyboard.append(nav_row)
    
    # Global Checkout Action Row
    checkout_btn = [InlineKeyboardButton(f"💳 Check Out & Pay ({len(cart_numbers)} Selected)", callback_data="checkout")]
    keyboard.append(checkout_btn)
    
    return InlineKeyboardMarkup(keyboard)

# ==========================================
# BOT FUNCTIONS
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    
    # Flush any leftover temporary cart entries on a fresh start command
    conn = sqlite3.connect("lottery.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM carts WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    keyboard = [
        [InlineKeyboardButton("🎟️ Open Lottery Board", callback_data='page_1')],
        [InlineKeyboardButton("📊 View Prize Pool", callback_data='pool')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👋 Welcome to the Interactive Multi-Choice Lottery!\n\nYou can select multiple numbers at once and pay for them in a single batch. Tap below to begin:", 
        reply_markup=reply_markup
    )

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data in ["taken", "ignore"]:
        return

    # Handle Page Grid Navigations
    if data.startswith("page_"):
        current_page = int(data.split("_")[1])
        reply_markup = build_numbers_keyboard(user_id, current_page)
        await query.edit_message_text(
            text="📌 **Tap multiple numbers to add them to your cart (🛒).**\nWhen you are finished picking, click the Checkout button at the bottom!",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
    # Handle Adding / Removing a Number from Cart
    elif data.startswith("toggle_"):
        parts = data.split("_")
        chosen_number = int(parts[1])
        current_page = int(parts[2])
        
        conn = sqlite3.connect("lottery.db")
        cursor = conn.cursor()
        
        # Check if it's already in the cart
        cursor.execute("SELECT * FROM carts WHERE user_id = ? AND chosen_number = ?", (user_id, chosen_number))
        in_cart = cursor.fetchone()
        
        if in_cart:
            # Remove it
            cursor.execute("DELETE FROM carts WHERE user_id = ? AND chosen_number = ?", (user_id, chosen_number))
        else:
            # Check race conditions against permanent entries
            cursor.execute("SELECT * FROM tickets WHERE chosen_number = ?", (chosen_number,))
            if cursor.fetchone():
                conn.close()
                return
            # Add it
            cursor.execute("INSERT OR IGNORE INTO carts (user_id, chosen_number) VALUES (?, ?)", (user_id, chosen_number))
            
        conn.commit()
        conn.close()
        
        # Redraw the keyboard to visually reflect changes instantly
        reply_markup = build_numbers_keyboard(user_id, current_page)
        await query.edit_reply_markup(reply_markup=reply_markup)
        
    # Handle Global Checkout Transition
    elif data == "checkout":
        conn = sqlite3.connect("lottery.db")
        cursor = conn.cursor()
        cursor.execute("SELECT chosen_number FROM carts WHERE user_id = ?", (user_id,))
        items = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        if not items:
            return
            
        total_cost = len(items) * TICKET_PRICE_ETB
        items_str = ", ".join(f"#{x}" for x in sorted(items))
        
        payment_text = (
            f"🛒 **Your Lottery Ticket Cart Summary**\n\n"
            f"🔢 **Selected Positions:** `{items_str}`\n"
            f"🎟️ **Total Tickets:** `{len(items)}`\n"
            f"💵 **Total Price:** `{total_cost} ETB`\n\n"
            "--- 🇪🇹 **CBE & Telebirr Instructions** ---\n\n"
            "🅰️ **Commercial Bank of Ethiopia (CBE)**\n"
            "• Account: `1000797796957`\n"
            "• Name: `Eyob Habtamu Taye`\n\n"
            "🅱️ **Telebirr**\n"
            "• Mobile Number: `0909768127`\n\n"
            "----------------------------------\n"
            f"⚠️ **To claim this entire batch permanently, send the {total_cost} ETB transfer, then type:**\n\n"
            f"👉 `/submit YOUR_REFERENCE_CODE`"
        )
        await query.edit_message_text(text=payment_text, parse_mode="Markdown")
        
    elif data == 'pool':
        conn = sqlite3.connect("lottery.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE payment_status='PAID'")
        total_tickets = cursor.fetchone()[0]
        conn.close()
        
        total_pool = total_tickets * TICKET_PRICE_ETB
        await query.edit_message_text(
            text=f"📊 **Current Prize Pool Status**\n\n"
                 f"💰 Grand Prize Pot: `{total_pool} ETB`\n"
                 f"🎟️ Total Verified Sold Slots: `{total_tickets} / 450`\n\n"
                 f"Select positions to grow the prize pool layout structure!"
        )

async def submit_reference(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.message.from_user
    user_id = user.id
    
    if not context.args:
        await update.message.reply_text("❌ **Format Error!**\nUse: `/submit YOUR_REFERENCE_CODE` \nExample: `/submit FT26ABC123`")
        return
        
    reference_code = context.args[0].upper().strip()
    
    conn = sqlite3.connect("lottery.db")
    cursor = conn.cursor()
    
    # 1. Check if this reference was used before
    cursor.execute("SELECT * FROM tickets WHERE reference_code = ?", (reference_code,))
    if cursor.fetchone():
        await update.message.reply_text("❌ This transaction reference code has already been submitted.")
        conn.close()
        return
        
    # 2. Extract numbers out of their cart
    cursor.execute("SELECT chosen_number FROM carts WHERE user_id = ?", (user_id,))
    cart_items = [row[0] for row in cursor.fetchall()]
    
    if not cart_items:
        await update.message.reply_text("❌ Your cart is empty! Use /start to pick numbers before submitting a reference code.")
