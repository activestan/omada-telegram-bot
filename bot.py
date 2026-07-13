"""
Omada Telegram Bot - Main Bot Module
Serves access codes from the SQLite database via Telegram buttons.
NO Playwright needed at runtime - just reads from the database.
"""
import logging
import asyncio
import subprocess
import sys
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from telegram.constants import ParseMode

import config
from database import (
    init_db, get_unused_code, get_code_stats,
    check_request_cooldown, get_recent_usage
)
from flutterwave_client import fetch_inactive_customers
from email_sender import send_reengagement_campaigns

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DURATION_DISPLAY = {
    "daily": "📅 Daily (1 day)",
    "3days": "📆 3 Days",
    "weekly": "📋 Weekly (7 days)",
    "monthly": "🗓️ Monthly (31 days)"
}


def is_authorized(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS:
        return True
    return user_id in config.ALLOWED_USER_IDS


# ============================================
# COMMAND HANDLERS
# ============================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Not authorized.")
        return

    welcome = (
        "👋 *Omada Code Bot*\n\n"
        "Get your WiFi access codes below:\n"
    )

    keyboard = [
        [InlineKeyboardButton("📅 Daily", callback_data="code_daily"),
         InlineKeyboardButton("📆 3 Days", callback_data="code_3days")],
        [InlineKeyboardButton("📋 Weekly", callback_data="code_weekly"),
         InlineKeyboardButton("🗓️ Monthly", callback_data="code_monthly")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats"),
         InlineKeyboardButton("📜 History", callback_data="history")],
        [InlineKeyboardButton("📧 Customer Outreach", callback_data="outreach")],
        [InlineKeyboardButton("⚙️ Admin", callback_data="admin")],
    ]

    await update.message.reply_text(
        welcome, reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Commands:*\n\n"
        "/start - Main menu\n"
        "/daily - Get daily code\n"
        "/threedays - Get 3-day code\n"
        "/weekly - Get weekly code\n"
        "/monthly - Get monthly code\n"
        "/stats - Code statistics\n"
        "/history - Your recent codes\n"
        "/extract - Run code extraction from Omada\n"
        "/help - This message",
        parse_mode=ParseMode.MARKDOWN
    )


# Quick code commands
async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_code(update, "daily")

async def threedays_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_code(update, "3days")

async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_code(update, "weekly")

async def monthly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_code(update, "monthly")

async def extract_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually trigger code extraction from Omada."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Not authorized.")
        return
    await _run_extraction(update.message)


# ============================================
# BUTTON HANDLER
# ============================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Not authorized.")
        return

    data = query.data

    if data.startswith("code_"):
        await _send_code_callback(query, data.replace("code_", ""))
    elif data == "stats":
        await _show_stats(query)
    elif data == "history":
        await _show_history(query)
    elif data == "outreach":
        await _show_outreach_menu(query)
    elif data == "outreach_preview":
        await _preview_outreach(query)
    elif data == "outreach_run":
        await _run_outreach(query, context)
    elif data == "admin":
        await _show_admin(query)
    elif data == "extract_codes":
        await _run_extraction(query.message)
    elif data == "back_to_menu":
        await _back_to_menu(query)


# ============================================
# CODE DELIVERY
# ============================================

async def _send_code(update: Update, duration_type: str):
    if not is_authorized(update.effective_user.id):
        return

    user_id = update.effective_user.id
    display = DURATION_DISPLAY.get(duration_type, duration_type)

    allowed, msg = await check_request_cooldown(user_id, duration_type)
    if not allowed:
        await update.message.reply_text(msg)
        return

    code = await get_unused_code(duration_type, user_id)

    if code:
        await update.message.reply_text(
            f"✅ *{display}*\n\n"
            f"Your WiFi code:\n`{code}`\n\n"
            f"🔒 Unique code — won't be repeated.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            f"❌ No {display} codes available!\n"
            f"Run /extract to pull codes from Omada.",
            parse_mode=ParseMode.MARKDOWN
        )


async def _send_code_callback(query, duration_type: str):
    user_id = query.from_user.id
    display = DURATION_DISPLAY.get(duration_type, duration_type)

    allowed, msg = await check_request_cooldown(user_id, duration_type)
    if not allowed:
        await query.edit_message_text(msg)
        return

    code = await get_unused_code(duration_type, user_id)

    if code:
        keyboard = [[InlineKeyboardButton("◀️ Menu", callback_data="back_to_menu")]]
        await query.edit_message_text(
            f"✅ *{display}*\n\n"
            f"Your WiFi code:\n`{code}`\n\n"
            f"🔒 Unique code — won't be repeated.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        keyboard = [
            [InlineKeyboardButton("⚙️ Extract Codes", callback_data="extract_codes")],
            [InlineKeyboardButton("◀️ Menu", callback_data="back_to_menu")]
        ]
        await query.edit_message_text(
            f"❌ No {display} codes available!\nTap below to extract from Omada.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )


# ============================================
# STATS & HISTORY
# ============================================

async def _show_stats(query):
    stats = await get_code_stats()

    if not stats:
        text = "📊 *Stats*\n\nNo codes in database.\nRun /extract to pull codes."
    else:
        text = "📊 *Code Inventory*\n\n"
        for dtype, info in sorted(stats.items()):
            display = DURATION_DISPLAY.get(dtype, dtype)
            text += f"*{display}*\n"
            text += f"  ✅ Available: {info['unused']} | 🔒 Used: {info['used']}\n\n"

    keyboard = [[InlineKeyboardButton("◀️ Menu", callback_data="back_to_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def _show_history(query):
    usage = await get_recent_usage(query.from_user.id)

    if not usage:
        text = "📜 *History*\n\nNo codes requested yet."
    else:
        text = "📜 *Your Recent Codes*\n\n"
        for code, dtype, ts in usage:
            display = DURATION_DISPLAY.get(dtype, dtype)
            text += f"`{code}` — {display}\n_{ts[:16]}_\n\n"

    keyboard = [[InlineKeyboardButton("◀️ Menu", callback_data="back_to_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


# ============================================
# CUSTOMER OUTREACH
# ============================================

async def _show_outreach_menu(query):
    text = (
        "📧 *Customer Outreach*\n\n"
        "Fetches inactive Flutterwave customers\n"
        "and sends re-engagement emails.\n\n"
        "⚠️ Sends real emails!"
    )
    keyboard = [
        [InlineKeyboardButton("👀 Preview", callback_data="outreach_preview")],
        [InlineKeyboardButton("▶️ Run Campaign", callback_data="outreach_run")],
        [InlineKeyboardButton("◀️ Menu", callback_data="back_to_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def _preview_outreach(query):
    await query.edit_message_text("🔍 Fetching inactive customers...")
    success, customers, message = await fetch_inactive_customers()

    if success and customers:
        text = f"👥 *{len(customers)} inactive customers:*\n\n"
        for i, c in enumerate(customers[:10], 1):
            text += f"{i}. {c.get('name', 'N/A')}\n   📧 {c.get('email')}\n\n"
        if len(customers) > 10:
            text += f"_...and {len(customers) - 10} more_\n"
    else:
        text = f"ℹ️ {message}"

    keyboard = [
        [InlineKeyboardButton("▶️ Run Campaign", callback_data="outreach_run")],
        [InlineKeyboardButton("◀️ Back", callback_data="outreach")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def _run_outreach(query, context):
    await query.edit_message_text("🚀 Fetching customers...")
    success, customers, message = await fetch_inactive_customers()

    if not success or not customers:
        await query.edit_message_text(f"❌ {message}")
        return

    progress_msg = await query.edit_message_text(f"📧 Sending to {len(customers)} customers...")

    async def progress_cb(sent, total, email, ok):
        if sent % 5 == 0 or sent == total:
            try:
                await context.bot.edit_message_text(
                    chat_id=query.message.chat_id, message_id=progress_msg.message_id,
                    text=f"📧 Progress: {sent}/{total}\nLatest: {'✅' if ok else '❌'} {email}"
                )
            except:
                pass

    results = await send_reengagement_campaigns(customers, progress_cb)

    keyboard = [[InlineKeyboardButton("◀️ Menu", callback_data="back_to_menu")]]
    await query.edit_message_text(
        f"✅ *Campaign Done!*\n\n"
        f"✅ Sent: {results['sent']}\n❌ Failed: {results['failed']}\n📦 Total: {results['total']}",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
    )


# ============================================
# ADMIN PANEL
# ============================================

async def _show_admin(query):
    text = (
        "⚙️ *Admin Panel*\n\n"
        "🔄 *Extract Codes* — Run the extraction\n"
        "script to pull voucher codes from\n"
        "your Omada Cloud Controller.\n\n"
        "This pulls: `whatsapp_1day`, `whatsapp_3days`,\n"
        "`whatsapp_7days`, `whatsapp_31days`"
    )
    keyboard = [
        [InlineKeyboardButton("🔄 Extract Codes Now", callback_data="extract_codes")],
        [InlineKeyboardButton("📊 View Stats", callback_data="stats")],
        [InlineKeyboardButton("◀️ Menu", callback_data="back_to_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def _run_extraction(message):
    """Run the extraction script and report results."""
    await message.reply_text("🔄 Starting code extraction from Omada Cloud...\n⏳ This may take 30-60 seconds...")

    try:
        result = subprocess.run(
            [sys.executable, "extract_codes.py"],
            capture_output=True, text=True, timeout=180,
            cwd="."
        )

        output = result.stdout
        if result.returncode == 0:
            # Extract key info from output
            lines = [l.strip() for l in output.split('\n') if l.strip()]
            summary = []
            for line in lines:
                if any(kw in line for kw in ['✅', '💾', '📊', '📋', '🔍', '⚠️', '❌']):
                    summary.append(line)

            if summary:
                text = "✅ *Extraction Complete!*\n\n" + "\n".join(summary[-10:])
            else:
                text = f"✅ Extraction completed.\n```\n{output[-500:]}\n```"
        else:
            error = result.stderr[-500:] if result.stderr else output[-500:]
            text = f"❌ *Extraction Failed!*\n\n```\n{error}\n```"

    except subprocess.TimeoutExpired:
        text = "⏰ Extraction timed out (3 min limit)"
    except Exception as e:
        text = f"❌ Error: {str(e)}"

    keyboard = [
        [InlineKeyboardButton("📊 View Stats", callback_data="stats")],
        [InlineKeyboardButton("◀️ Menu", callback_data="back_to_menu")]
    ]
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


# ============================================
# NAVIGATION
# ============================================

async def _back_to_menu(query):
    keyboard = [
        [InlineKeyboardButton("📅 Daily", callback_data="code_daily"),
         InlineKeyboardButton("📆 3 Days", callback_data="code_3days")],
        [InlineKeyboardButton("📋 Weekly", callback_data="code_weekly"),
         InlineKeyboardButton("🗓️ Monthly", callback_data="code_monthly")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats"),
         InlineKeyboardButton("📜 History", callback_data="history")],
        [InlineKeyboardButton("📧 Customer Outreach", callback_data="outreach")],
        [InlineKeyboardButton("⚙️ Admin", callback_data="admin")],
    ]
    await query.edit_message_text(
        "👋 *Omada Code Bot*\n\nChoose an option:",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    text = update.message.text.lower().strip()
    keyword_map = {
        "daily": "daily", "day": "daily", "1day": "daily",
        "3days": "3days", "3 days": "3days", "3day": "3days",
        "weekly": "weekly", "week": "weekly", "7days": "weekly",
        "monthly": "monthly", "month": "monthly", "31days": "monthly",
    }

    duration = keyword_map.get(text)
    if duration:
        await _send_code(update, duration)
    elif text in ["stats", "statistics"]:
        class FakeQuery:
            from_user = update.effective_user
            async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        await _show_stats(FakeQuery())
    elif text in ["extract", "sync", "pull"]:
        await _run_extraction(update.message)
    else:
        await update.message.reply_text("Type /start for the menu or /help for commands.")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("⚠️ An error occurred. Please try again.")


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set!")
        return

    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("threedays", threedays_command))
    app.add_handler(CommandHandler("weekly", weekly_command))
    app.add_handler(CommandHandler("monthly", monthly_command))
    app.add_handler(CommandHandler("extract", extract_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    print("🤖 Bot running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
