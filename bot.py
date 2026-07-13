"""
Omada Telegram Bot - Main Bot Module
Provides access codes via Telegram with inline keyboard buttons.
"""
import logging
import asyncio
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
from omada_fetcher import sync_codes_from_omada, import_codes_from_file
from flutterwave_client import fetch_inactive_customers
from email_sender import send_reengagement_campaigns

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Duration display names
DURATION_DISPLAY = {
    "daily": "📅 Daily (24hrs)",
    "3days": "📆 3 Days",
    "weekly": "📋 Weekly (7 days)",
    "monthly": "🗓️ Monthly (30 days)"
}


def is_authorized(user_id: int) -> bool:
    """Check if the user is authorized to use the bot."""
    if not config.ALLOWED_USER_IDS:
        return True  # No restriction if no IDs configured
    return user_id in config.ALLOWED_USER_IDS


# ============================================
# COMMAND HANDLERS
# ============================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - show main menu."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Sorry, you are not authorized to use this bot.")
        return

    welcome_text = (
        f"👋 Welcome to the *Omada Code Bot*!\n\n"
        f"Here's what I can do for you:\n\n"
        f"🔑 *Get Access Codes* - Request WiFi access codes\n"
        f"📊 *View Stats* - Check code inventory\n"
        f"📜 *History* - View your recent codes\n"
        f"📧 *Customer Outreach* - Email inactive customers\n"
        f"⚙️ *Admin Panel* - Sync & manage codes\n\n"
        f"Choose an option below:"
    )

    keyboard = [
        [InlineKeyboardButton("🔑 Daily Code", callback_data="code_daily"),
         InlineKeyboardButton("📆 3-Day Code", callback_data="code_3days")],
        [InlineKeyboardButton("📋 Weekly Code", callback_data="code_weekly"),
         InlineKeyboardButton("🗓️ Monthly Code", callback_data="code_monthly")],
        [InlineKeyboardButton("📊 View Stats", callback_data="stats"),
         InlineKeyboardButton("📜 My History", callback_data="history")],
        [InlineKeyboardButton("📧 Customer Outreach", callback_data="outreach")],
        [InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = (
        "🤖 *Bot Commands:*\n\n"
        "/start - Show main menu\n"
        "/daily - Get daily code\n"
        "/3days - Get 3-day code\n"
        "/weekly - Get weekly code\n"
        "/monthly - Get monthly code\n"
        "/stats - View code statistics\n"
        "/history - View your recent codes\n"
        "/outreach - Customer email campaign\n"
        "/help - Show this help message\n\n"
        "💡 *Tip:* Use the buttons for quick access!"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


# ============================================
# QUICK CODE COMMANDS
# ============================================

async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /daily command."""
    await _handle_code_request(update, "daily")


async def threedays_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /3days command."""
    await _handle_code_request(update, "3days")


async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /weekly command."""
    await _handle_code_request(update, "weekly")


async def monthly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /monthly command."""
    await _handle_code_request(update, "monthly")


# ============================================
# CALLBACK QUERY HANDLERS
# ============================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all inline button presses."""
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ Not authorized.")
        return

    data = query.data

    # Code requests
    if data.startswith("code_"):
        duration_type = data.replace("code_", "")
        await _handle_code_request_callback(query, duration_type)

    # Stats
    elif data == "stats":
        await _show_stats(query)

    # History
    elif data == "history":
        await _show_history(query)

    # Customer Outreach
    elif data == "outreach":
        await _show_outreach_menu(query)

    elif data == "outreach_run":
        await _run_outreach_campaign(query, context)

    elif data == "outreach_preview":
        await _preview_outreach(query)

    # Admin Panel
    elif data == "admin":
        await _show_admin_panel(query)

    elif data.startswith("sync_"):
        duration_type = data.replace("sync_", "")
        await _sync_codes(query, duration_type)

    elif data == "sync_all":
        await _sync_all_codes(query)

    elif data == "import_file":
        await query.edit_message_text(
            "📁 To import codes from a file:\n\n"
            "1. Create a file with format:\n"
            "   CODE123,daily\n"
            "   CODE456,weekly\n\n"
            "2. Place it as 'codes_import.csv' in the bot directory\n"
            "3. Press the button below to import"
        )
        keyboard = [[InlineKeyboardButton("▶️ Import Now", callback_data="do_import")]]
        keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="admin")])
        await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))

    elif data == "do_import":
        await _import_file(query)

    # Navigation
    elif data == "back_to_menu":
        await _back_to_menu(query)


# ============================================
# CODE REQUEST HANDLING
# ============================================

async def _handle_code_request(update: Update, duration_type: str):
    """Handle code request from slash commands."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ Not authorized.")
        return

    user_id = update.effective_user.id
    display_name = DURATION_DISPLAY.get(duration_type, duration_type)

    # Check cooldown
    allowed, msg = await check_request_cooldown(user_id, duration_type)
    if not allowed:
        await update.message.reply_text(msg)
        return

    # Get code
    code = await get_unused_code(duration_type, user_id)

    if code:
        await update.message.reply_text(
            f"✅ *{display_name}*\n\n"
            f"Your access code:\n`{code}`\n\n"
            f"⏰ Valid for {duration_type.replace('3days', '3 days')}\n"
            f"🔒 This code is unique and won't be repeated.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            f"❌ *No codes available!*\n\n"
            f"There are no unused {display_name} codes in the database.\n"
            f"Please use the Admin Panel to sync new codes from Omada.",
            parse_mode=ParseMode.MARKDOWN
        )


async def _handle_code_request_callback(query, duration_type: str):
    """Handle code request from button press."""
    user_id = query.from_user.id
    display_name = DURATION_DISPLAY.get(duration_type, duration_type)

    # Check cooldown
    allowed, msg = await check_request_cooldown(user_id, duration_type)
    if not allowed:
        await query.edit_message_text(msg)
        return

    # Get code
    code = await get_unused_code(duration_type, user_id)

    if code:
        keyboard = [[InlineKeyboardButton("◀️ Back to Menu", callback_data="back_to_menu")]]
        await query.edit_message_text(
            f"✅ *{display_name}*\n\n"
            f"Your access code:\n`{code}`\n\n"
            f"⏰ Valid for {duration_type.replace('3days', '3 days')}\n"
            f"🔒 This code is unique and won't be repeated.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        keyboard = [
            [InlineKeyboardButton("⚙️ Go to Admin Panel", callback_data="admin")],
            [InlineKeyboardButton("◀️ Back to Menu", callback_data="back_to_menu")]
        ]
        await query.edit_message_text(
            f"❌ *No codes available!*\n\n"
            f"There are no unused {display_name} codes.\n"
            f"Use the Admin Panel to sync new codes.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )


# ============================================
# STATS & HISTORY
# ============================================

async def _show_stats(query):
    """Show code inventory statistics."""
    stats = await get_code_stats()

    if not stats:
        text = "📊 *Code Statistics*\n\nNo codes in database yet."
    else:
        text = "📊 *Code Statistics*\n\n"
        total_unused = 0
        total_used = 0

        for dtype, info in stats.items():
            display = DURATION_DISPLAY.get(dtype, dtype)
            text += (
                f"*{display}:*\n"
                f"  📦 Total: {info['total']} | "
                f"✅ Available: {info['unused']} | "
                f"🔒 Used: {info['used']}\n\n"
            )
            total_unused += info['unused']
            total_used += info['used']

        text += f"━━━━━━━━━━━━━━━\n"
        text += f"📦 *Grand Total:* {total_unused + total_used}\n"
        text += f"✅ *Available:* {total_unused}\n"
        text += f"🔒 *Used:* {total_used}"

    keyboard = [[InlineKeyboardButton("◀️ Back to Menu", callback_data="back_to_menu")]]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def _show_history(query):
    """Show user's recent code history."""
    usage = await get_recent_usage(query.from_user.id)

    if not usage:
        text = "📜 *Your History*\n\nNo codes requested yet."
    else:
        text = "📜 *Your Recent Codes*\n\n"
        for code, dtype, timestamp in usage:
            display = DURATION_DISPLAY.get(dtype, dtype)
            time_str = timestamp[:16] if len(timestamp) > 16 else timestamp
            text += f"`{code}` - {display}\n_{time_str}_\n\n"

    keyboard = [[InlineKeyboardButton("◀️ Back to Menu", callback_data="back_to_menu")]]
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ============================================
# CUSTOMER OUTREACH
# ============================================

async def _show_outreach_menu(query):
    """Show the customer outreach options."""
    text = (
        "📧 *Customer Outreach Campaign*\n\n"
        "This will:\n"
        "1️⃣ Fetch all customers from Flutterwave\n"
        "2️⃣ Identify those without active subscriptions\n"
        "3️⃣ Send them a re-engagement email with:\n"
        "   - Your WhatsApp link\n"
        "   - Your Telegram bot link\n\n"
        "⚠️ *This action sends real emails. Be sure!*"
    )

    keyboard = [
        [InlineKeyboardButton("👀 Preview Inactive Customers", callback_data="outreach_preview")],
        [InlineKeyboardButton("▶️ Run Campaign Now", callback_data="outreach_run")],
        [InlineKeyboardButton("◀️ Back to Menu", callback_data="back_to_menu")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def _preview_outreach(query):
    """Preview inactive customers before sending emails."""
    await query.edit_message_text("🔍 Fetching inactive customers from Flutterwave...\n⏳ Please wait...")

    success, customers, message = await fetch_inactive_customers()

    if success and customers:
        text = f"👥 *Inactive Customers Preview*\n\n"
        text += f"Found *{len(customers)}* inactive customers:\n\n"

        # Show first 10
        for i, c in enumerate(customers[:10], 1):
            name = c.get('name', 'N/A')
            email = c.get('email', 'N/A')
            text += f"{i}. {name}\n   📧 {email}\n\n"

        if len(customers) > 10:
            text += f"_...and {len(customers) - 10} more_\n"

        text += f"\n⚠️ Running the campaign will email all {len(customers)} customers."
    else:
        text = f"ℹ️ {message}"

    keyboard = [
        [InlineKeyboardButton("▶️ Run Campaign", callback_data="outreach_run")],
        [InlineKeyboardButton("◀️ Back", callback_data="outreach")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def _run_outreach_campaign(query, context):
    """Run the full outreach campaign."""
    await query.edit_message_text("🚀 Starting campaign...\n📡 Fetching inactive customers...")

    success, customers, message = await fetch_inactive_customers()

    if not success or not customers:
        keyboard = [[InlineKeyboardButton("◀️ Back", callback_data="outreach")]]
        await query.edit_message_text(
            f"❌ {message}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Progress tracking
    progress_msg = await query.edit_message_text(
        f"📧 Sending emails to {len(customers)} customers...\n⏳ Progress: 0/{len(customers)}"
    )

    async def progress_callback(sent, total, email, was_success):
        """Update progress message periodically."""
        if sent % 5 == 0 or sent == total:  # Update every 5 emails
            try:
                status = "✅" if was_success else "❌"
                await context.bot.edit_message_text(
                    chat_id=query.message.chat_id,
                    message_id=progress_msg.message_id,
                    text=(
                        f"📧 Sending emails...\n"
                        f"⏳ Progress: {sent}/{total}\n"
                        f"Latest: {status} {email}"
                    )
                )
            except Exception:
                pass  # Message might be too old to edit

    results = await send_reengagement_campaigns(customers, progress_callback)

    # Final result
    keyboard = [[InlineKeyboardButton("◀️ Back to Menu", callback_data="back_to_menu")]]
    await query.edit_message_text(
        f"✅ *Campaign Complete!*\n\n"
        f"📊 *Results:*\n"
        f"  ✅ Sent: {results['sent']}\n"
        f"  ❌ Failed: {results['failed']}\n"
        f"  📦 Total: {results['total']}\n\n"
        f"🕐 Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ============================================
# ADMIN PANEL
# ============================================

async def _show_admin_panel(query):
    """Show admin panel with sync options."""
    text = (
        "⚙️ *Admin Panel*\n\n"
        "🔄 *Sync Codes* - Create new codes on Omada\n"
        "   and add them to the database\n\n"
        "📥 *Import All* - Import existing unused\n"
        "   vouchers from Omada controller\n\n"
        "📁 *Import File* - Load codes from a file\n"
    )

    keyboard = [
        [InlineKeyboardButton("🔄 Sync Daily (20)", callback_data="sync_daily"),
         InlineKeyboardButton("🔄 Sync 3-Day (20)", callback_data="sync_3days")],
        [InlineKeyboardButton("🔄 Sync Weekly (20)", callback_data="sync_weekly"),
         InlineKeyboardButton("🔄 Sync Monthly (20)", callback_data="sync_monthly")],
        [InlineKeyboardButton("📥 Import All Unused from Omada", callback_data="sync_all")],
        [InlineKeyboardButton("📁 Import from File", callback_data="import_file")],
        [InlineKeyboardButton("◀️ Back to Menu", callback_data="back_to_menu")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def _sync_codes(query, duration_type: str):
    """Sync codes of a specific type from Omada."""
    display = DURATION_DISPLAY.get(duration_type, duration_type)
    await query.edit_message_text(f"🔄 Syncing {display} codes from Omada...\n⏳ Please wait...")

    success, message = await sync_codes_from_omada(duration_type, count=20)

    keyboard = [
        [InlineKeyboardButton("📊 View Stats", callback_data="stats")],
        [InlineKeyboardButton("◀️ Back to Admin", callback_data="admin")]
    ]

    if success:
        await query.edit_message_text(
            f"✅ *Sync Complete!*\n\n{message}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await query.edit_message_text(
            f"❌ *Sync Failed!*\n\n{message}\n\n"
            f"💡 Check your Omada controller settings in .env",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )


async def _sync_all_codes(query):
    """Import all unused vouchers from Omada."""
    await query.edit_message_text("📥 Importing all unused vouchers from Omada...\n⏳ Please wait...")

    success, message = await sync_codes_from_omada(duration_type=None)

    keyboard = [
        [InlineKeyboardButton("📊 View Stats", callback_data="stats")],
        [InlineKeyboardButton("◀️ Back to Admin", callback_data="admin")]
    ]

    status = "✅" if success else "❌"
    await query.edit_message_text(
        f"{status} *{'Import Complete' if success else 'Import Failed'}!*\n\n{message}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def _import_file(query):
    """Import codes from a file."""
    await query.edit_message_text("📁 Importing codes from 'codes_import.csv'...")

    success, message = await import_codes_from_file("codes_import.csv")

    keyboard = [
        [InlineKeyboardButton("📊 View Stats", callback_data="stats")],
        [InlineKeyboardButton("◀️ Back to Admin", callback_data="admin")]
    ]

    status = "✅" if success else "❌"
    await query.edit_message_text(
        f"{status} {message}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================================
# NAVIGATION
# ============================================

async def _back_to_menu(query):
    """Return to the main menu."""
    welcome_text = (
        f"👋 *Omada Code Bot*\n\n"
        f"Choose an option below:"
    )

    keyboard = [
        [InlineKeyboardButton("🔑 Daily Code", callback_data="code_daily"),
         InlineKeyboardButton("📆 3-Day Code", callback_data="code_3days")],
        [InlineKeyboardButton("📋 Weekly Code", callback_data="code_weekly"),
         InlineKeyboardButton("🗓️ Monthly Code", callback_data="code_monthly")],
        [InlineKeyboardButton("📊 View Stats", callback_data="stats"),
         InlineKeyboardButton("📜 My History", callback_data="history")],
        [InlineKeyboardButton("📧 Customer Outreach", callback_data="outreach")],
        [InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin")],
    ]

    await query.edit_message_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


# ============================================
# TEXT MESSAGE HANDLER
# ============================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages - interpret keywords."""
    if not is_authorized(update.effective_user.id):
        return

    text = update.message.text.lower().strip()

    # Map text to actions
    if text in ["daily", "day", "1day", "1 day"]:
        await _handle_code_request(update, "daily")
    elif text in ["3days", "3 days", "3day", "3 day", "threedays"]:
        await _handle_code_request(update, "3days")
    elif text in ["weekly", "week", "7days", "7 days"]:
        await _handle_code_request(update, "weekly")
    elif text in ["monthly", "month", "30days", "30 days"]:
        await _handle_code_request(update, "monthly")
    elif text in ["stats", "statistics", "inventory"]:
        # Create a fake query object for stats
        class FakeQuery:
            from_user = update.effective_user
            message = update.message
            chat_id = update.effective_chat.id
            async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        await _show_stats(FakeQuery())
    else:
        await update.message.reply_text(
            "🤔 I didn't understand that. Type /start to see the menu, or /help for commands."
        )


# ============================================
# ERROR HANDLER
# ============================================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors."""
    logger.error(f"Exception while handling update: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An error occurred. Please try again."
        )


# ============================================
# MAIN APPLICATION
# ============================================

def main():
    """Start the bot."""
    if not config.TELEGRAM_BOT_TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN not set in .env file!")
        print("   Copy .env.example to .env and fill in your credentials.")
        return

    # Initialize database
    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())

    # Build application
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("weekly", weekly_command))
    app.add_handler(CommandHandler("monthly", monthly_command))
    # Note: Telegram doesn't support commands starting with numbers
    # Use /threedays as alternative
    app.add_handler(CommandHandler("threedays", threedays_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Error handler
    app.add_error_handler(error_handler)

    # Start polling
    print("🤖 Bot is running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
