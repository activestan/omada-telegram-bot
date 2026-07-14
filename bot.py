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
    elif data == "add_codes":
        await _show_add_codes(query)
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
    success, result, message = await fetch_inactive_customers()
    customers = result["inactive"]

    if success and customers:
        text = f"👥 *Customer Breakdown:*\n\n"
        text += f"📦 Total customers: *{result['total']}*\n"
        text += f"📧 To email (inactive): *{len(customers)}*\n"
        text += f"⏭️ Skipped (active): *{len(result['active'])}*\n"
        text += f"❌ Skipped (no email): *{len(result['no_email'])}*\n\n"
        text += f"*First 10 to email:*\n"
        for i, c in enumerate(customers[:10], 1):
            text += f"{i}. {c.get('name', 'N/A')}\n   📧 {c.get('email')}\n\n"
        if len(customers) > 10:
            text += f"_...and {len(customers) - 10} more_\n"
    else:
        text = f"ℹ️ {message}"
        if result.get("total"):
            text += f"\n\n📦 Total: {result['total']} | ⏭️ Active: {len(result['active'])} | ❌ No email: {len(result['no_email'])}"

    keyboard = [
        [InlineKeyboardButton("▶️ Run Campaign", callback_data="outreach_run")],
        [InlineKeyboardButton("◀️ Back", callback_data="outreach")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def _run_outreach(query, context):
    await query.edit_message_text("🚀 Fetching customers...")
    success, result, message = await fetch_inactive_customers()
    customers = result["inactive"]

    skipped_active = len(result["active"])
    skipped_no_email = len(result["no_email"])
    total_customers = result["total"]

    if not success or not customers:
        text = f"❌ {message}"
        if total_customers:
            text += (
                f"\n\n📦 Total: {total_customers}\n"
                f"⏭️ Skipped (active subs): {skipped_active}\n"
                f"❌ Skipped (no email): {skipped_no_email}"
            )
        keyboard = [[InlineKeyboardButton("◀️ Menu", callback_data="back_to_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    progress_msg = await query.edit_message_text(
        f"📧 Sending to {len(customers)} customers...\n"
        f"⏭️ {skipped_active + skipped_no_email} skipped"
    )

    async def progress_cb(sent, total, email, ok):
        if sent % 5 == 0 or sent == total:
            try:
                await context.bot.edit_message_text(
                    chat_id=query.message.chat_id, message_id=progress_msg.message_id,
                    text=(
                        f"📧 Progress: {sent}/{total}\n"
                        f"Latest: {'✅' if ok else '❌'} {email}"
                    )
                )
            except:
                pass

    results = await send_reengagement_campaigns(customers, progress_cb)

    keyboard = [[InlineKeyboardButton("◀️ Menu", callback_data="back_to_menu")]]
    await query.edit_message_text(
        f"✅ *Campaign Complete!*\n\n"
        f"📦 *Total Customers:* {total_customers}\n\n"
        f"📧 *Emails Sent:* {results['sent']}\n"
        f"❌ *Failed to Send:* {results['failed']}\n\n"
        f"⏭️ *Skipped (active subs):* {skipped_active}\n"
        f"⏭️ *Skipped (no email):* {skipped_no_email}\n"
        f"⏭️ *Total Skipped:* {skipped_active + skipped_no_email}\n\n"
        f"🕐 _{datetime.now().strftime('%Y-%m-%d %H:%M')}_",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
    )


# ============================================
# ADMIN PANEL
# ============================================

async def _show_admin(query):
    text = (
        "⚙️ *Admin Panel*\n\n"
        "📥 *Add Codes* — Paste codes manually\n"
        "🔄 *Extract* — Pull from Omada (needs local setup)\n\n"
        "Target vouchers: `whatsapp_1day`,\n"
        "`whatsapp_3days`, `whatsapp_7days`, `whatsapp_31days`"
    )
    keyboard = [
        [InlineKeyboardButton("📥 Add Codes Manually", callback_data="add_codes")],
        [InlineKeyboardButton("🔄 Extract from Omada", callback_data="extract_codes")],
        [InlineKeyboardButton("📊 View Stats", callback_data="stats")],
        [InlineKeyboardButton("◀️ Menu", callback_data="back_to_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


async def _show_add_codes(query):
    text = (
        "📥 *Add Codes Manually*\n\n"
        "Send codes in this format (one per line):\n\n"
        "```\n"
        "ABC123,daily\n"
        "DEF456,3days\n"
        "GHI789,weekly\n"
        "JKL012,monthly\n"
        "```\n\n"
        "*Duration types:*\n"
        "• `daily` = 1 day\n"
        "• `3days` = 3 days\n"
        "• `weekly` = 7 days\n"
        "• `monthly` = 31 days\n\n"
        "Or send a `.csv` / `.txt` file with the same format.\n\n"
        "👇 *Paste your codes below:*"
    )
    keyboard = [[InlineKeyboardButton("◀️ Back", callback_data="admin")]]

    # Set user state to "adding codes"
    context_user_id = query.from_user.id
    # We'll use a global dict to track state
    _user_states[context_user_id] = "adding_codes"

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)


# Global dict to track user states
_user_states = {}


async def _run_extraction(message):
    """Run the extraction script and report results."""
    await message.reply_text(
        "🔄 Starting code extraction from Omada Cloud...\n"
        "⏳ This may take 30-60 seconds...\n\n"
        "⚠️ *Note:* If this fails on Render, you can:\n"
        "1. Use *Add Codes Manually* instead\n"
        "2. Run `python extract_codes.py` on your local computer",
        parse_mode=ParseMode.MARKDOWN
    )

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

    user_id = update.effective_user.id

    # Check if user is in "adding codes" mode
    if _user_states.get(user_id) == "adding_codes":
        await _process_pasted_codes(update)
        return

    text = update.message.text.lower().strip()
    keyword_map = {
        "daily": "daily", "day": "daily", "1day": "daily",
        "3days": "3days", "3 days": "3days", "3day": "3days",
        "threedays": "3days",
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
    elif text in ["cancel", "stop", "done"]:
        _user_states.pop(user_id, None)
        await update.message.reply_text("✅ Done. Type /start for the menu.")
    else:
        await update.message.reply_text("Type /start for the menu or /help for commands.")


async def _process_pasted_codes(update: Update):
    """Process codes pasted by the user in add-codes mode."""
    user_id = update.effective_user.id
    raw_text = update.message.text.strip()

    if raw_text.lower() in ["cancel", "done", "stop", "/cancel", "/done"]:
        _user_states.pop(user_id, None)
        keyboard = [[InlineKeyboardButton("◀️ Admin", callback_data="admin")]]
        await update.message.reply_text("✅ Done adding codes.", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    await _import_codes_from_text(raw_text, update.message)


async def _import_codes_from_text(raw_text: str, message):
    """Parse and import codes from text. Supports multiple formats:
    - Simple: CODE,daily
    - Omada CSV export: with headers like Code,Duration,Name
    - Tab/comma/pipe separated
    """
    import aiosqlite
    import csv
    import io
    from config import DATABASE_PATH

    valid_durations = {"daily": 1440, "3days": 4320, "weekly": 10080, "monthly": 43200}
    
    # Duration mapping: minutes to our type
    minutes_to_type = {1440: "daily", 4320: "3days", 10080: "weekly", 43200: "monthly"}
    # Also accept close matches
    for mins, dtype in list(minutes_to_type.items()):
        for offset in range(-60, 61):
            minutes_to_type[mins + offset] = dtype

    # Voucher name to duration type mapping
    name_to_type = {
        "whatsapp_1day": "daily", "1day": "daily", "daily": "daily", "1 day": "daily", "24": "daily",
        "whatsapp_3days": "3days", "3days": "3days", "3 day": "3days", "72": "3days",
        "whatsapp_7days": "weekly", "7days": "weekly", "weekly": "weekly", "7 day": "weekly", "168": "weekly",
        "whatsapp_31days": "monthly", "31days": "monthly", "monthly": "monthly", "30 day": "monthly", "31 day": "monthly", "744": "monthly", "720": "monthly",
    }

    codes_to_add = []
    errors = []
    lines = raw_text.strip().split('\n')

    # Try to detect if this is a CSV with headers (Omada export format)
    first_line = lines[0].strip().lower() if lines else ""
    is_csv_with_headers = any(h in first_line for h in ["code", "voucher", "password", "pin", "name", "duration"])

    if is_csv_with_headers:
        # Parse as CSV with headers
        reader = csv.DictReader(io.StringIO(raw_text))
        for i, row in enumerate(reader, 2):
            # Try to find the code field
            code = ""
            for key in ["code", "voucher", "password", "pin", "vouchercode", "voucher_code", "Code", "Password"]:
                if key in row and row[key].strip():
                    code = row[key].strip()
                    break

            if not code:
                # Try first non-empty field
                for val in row.values():
                    if val and val.strip() and len(val.strip()) > 3:
                        code = val.strip()
                        break

            if not code:
                continue

            # Try to find duration from name or duration field
            dur_type = None
            
            # Check name field
            for key in ["name", "portal", "portalname", "Name", "Portal Name"]:
                if key in row and row[key]:
                    name_val = row[key].strip().lower()
                    for pattern, dtype in name_to_type.items():
                        if pattern in name_val:
                            dur_type = dtype
                            break
                if dur_type:
                    break

            # Check duration field (in minutes)
            if not dur_type:
                for key in ["duration", "minutes", "Duration", "time", "validity"]:
                    if key in row and row[key]:
                        try:
                            mins = int(row[key].strip())
                            dur_type = minutes_to_type.get(mins)
                        except ValueError:
                            # Try to parse "24 hours", "3 days", etc.
                            val = row[key].strip().lower()
                            for pattern, dtype in name_to_type.items():
                                if pattern in val:
                                    dur_type = dtype
                                    break
                    if dur_type:
                        break

            # If still no type, check if we can infer from any field
            if not dur_type:
                for val in row.values():
                    if val:
                        val_lower = str(val).strip().lower()
                        for pattern, dtype in name_to_type.items():
                            if pattern in val_lower:
                                dur_type = dtype
                                break
                    if dur_type:
                        break

            if not dur_type:
                errors.append(f"Row {i}: Can't detect duration for `{code[:20]}` — add ,daily/3days/weekly/monthly")
                continue

            dur_minutes = valid_durations[dur_type]
            codes_to_add.append((code, dur_type, dur_minutes, row.get("id", row.get("Id", row.get("ID", "")))))

    else:
        # Simple format: CODE,duration or CODE|duration
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if ',' in line:
                parts = line.split(',')
            elif '|' in line:
                parts = line.split('|')
            elif '\t' in line:
                parts = line.split('\t')
            else:
                errors.append(f"Line {i}: No separator — `{line[:30]}`")
                continue

            if len(parts) < 2:
                errors.append(f"Line {i}: Need code,type — `{line[:30]}`")
                continue

            code = parts[0].strip()
            dur_input = parts[1].strip().lower()

            if not code:
                errors.append(f"Line {i}: Empty code")
                continue

            # Check if it's a direct type or a name pattern
            dur_type = valid_durations.get(dur_input) and dur_input
            if not dur_type:
                dur_type = name_to_type.get(dur_input)
            if not dur_type:
                # Try partial match
                for pattern, dtype in name_to_type.items():
                    if pattern in dur_input:
                        dur_type = dtype
                        break
            if not dur_type:
                # Try as minutes
                try:
                    mins = int(dur_input)
                    dur_type = minutes_to_type.get(mins)
                except ValueError:
                    pass

            if not dur_type:
                errors.append(f"Line {i}: Bad type `{dur_input}` — use daily/3days/weekly/monthly")
                continue

            codes_to_add.append((code, dur_type, valid_durations[dur_type], ""))

    # Insert into database
    inserted = 0
    if codes_to_add:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for code, dur_type, dur_min, vid in codes_to_add:
                try:
                    cursor = await db.execute(
                        "INSERT OR IGNORE INTO codes (code, duration_type, duration_minutes, omada_voucher_id) VALUES (?, ?, ?, ?)",
                        (code, dur_type, dur_min, vid or "")
                    )
                    if cursor.rowcount > 0:
                        inserted += 1
                except:
                    pass
            await db.commit()

    # Build result
    result = f"📥 *Import Results*\n\n"
    result += f"📝 Codes found: {len(codes_to_add)}\n"
    result += f"✅ New codes added: {inserted}\n"
    result += f"♻️ Duplicates skipped: {len(codes_to_add) - inserted}\n"
    if errors:
        result += f"⚠️ Errors: {len(errors)}\n"

    if errors[:5]:
        result += f"\n*Errors:*\n"
        for err in errors[:5]:
            result += f"• {err}\n"
        if len(errors) > 5:
            result += f"_...and {len(errors) - 5} more_\n"

    if codes_to_add:
        by_type = {}
        for _, dt, _, _ in codes_to_add:
            by_type[dt] = by_type.get(dt, 0) + 1
        result += f"\n*Breakdown:*\n"
        for dt, count in sorted(by_type.items()):
            display = DURATION_DISPLAY.get(dt, dt)
            result += f"  {display}: {count} (added: {min(count, inserted)})\n"

    result += f"\n_Send more codes or type `done` to finish._"
    await message.reply_text(result, parse_mode=ParseMode.MARKDOWN)


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded CSV/TXT files with codes."""
    if not is_authorized(update.effective_user.id):
        return

    document = update.message.document
    await update.message.reply_text(f"📁 Processing `{document.file_name}`...", parse_mode=ParseMode.MARKDOWN)

    try:
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()
        raw_text = file_bytes.decode('utf-8')
        await _import_codes_from_text(raw_text, update.message)
    except Exception as e:
        await update.message.reply_text(f"❌ Error reading file: {str(e)}")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("⚠️ An error occurred. Please try again.")


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set!")
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
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
    app.add_handler(MessageHandler(filters.Document.TXT | filters.Document.FileExtension("csv"), handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    print("🤖 Bot running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
