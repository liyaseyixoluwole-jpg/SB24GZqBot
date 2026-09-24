"""
Telegram Reminder Bot — @SB24GZqBot
Supports: relative reminders, daily, weekly, list, delete.
"""
import logging
import os
import re
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

import database as db
from reminders import (
    TIMEZONE,
    parse_relative,
    parse_daily,
    parse_weekly,
    next_daily_datetime,
    next_weekly_datetime,
)

# ─────────────────────────── Config ───────────────────────────

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN env variable is missing!")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("reminder-bot")

HELP_TEXT = (
    "🤖 *Reminder Bot*\n\n"
    "*Create a reminder:*\n"
    "• `Remind me in 30 minutes to drink water`\n"
    "• `Remind me in 2 hours 15 minutes`\n"
    "• `Every day at 08:30 to wake up`\n"
    "• `Every monday at 09:00 team meeting`\n\n"
    "*Manage:*\n"
    "• /list — Show active reminders\n"
    "• /delete `<id>` — Delete a reminder\n"
    "• /help — Show this help"
)


# ─────────────────────────── Utilities ───────────────────────────

def extract_label(text: str, default: str = "Reminder") -> str:
    """Pull out the label after 'to <label>' or clean the schedule words."""
    m = re.search(r"\bto\s+(.+)$", text, re.IGNORECASE)
    if m:
        return m.group(1).strip().strip(".!,;") or default

    cleaned = re.sub(
        r"(?:remind me|remind|reminder)?\s*"
        r"(?:every\s+\w+(\s+at\s+\d{1,2}:\d{2})?|"
        r"daily(\s+at\s+\d{1,2}:\d{2})?|"
        r"every\s*day(\s+at\s+\d{1,2}:\d{2})?|"
        r"in\s+[\d\w\s]+)",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip(" -:.,!")
    return cleaned or default


# ─────────────────────────── Handlers ───────────────────────────

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name or "there"
    await update.message.reply_text(
        f"👋 Hello {name}!\n\n{HELP_TEXT}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    rows = db.get_user_reminders(user_id)

    if not rows:
        await update.message.reply_text("📭 You have no active reminders.")
        return

    lines = ["📋 *Your active reminders:*\n"]
    keyboard = []
    for row in rows:
        rid = row["id"]
        text = row["text"]
        remind_at = datetime.fromisoformat(row["remind_at"]).astimezone(TIMEZONE)
        rtype = row["repeat_type"]
        repeat_label = {"none": "", "daily": " 🔁 daily", "weekly": " 🔁 weekly"}.get(
            rtype, ""
        )
        lines.append(
            f"`#{rid}` — *{text}*\n"
            f"     ⏰ {remind_at.strftime('%Y-%m-%d %H:%M')}{repeat_label}\n"
        )
        keyboard.append(
            [InlineKeyboardButton(f"🗑 Delete #{rid}", callback_data=f"del:{rid}")]
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: `/delete <reminder_id>`", parse_mode=ParseMode.MARKDOWN
        )
        return
    try:
        rid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ Reminder ID must be a number.")
        return

    if db.delete_reminder(rid, update.effective_user.id):
        await update.message.reply_text(
            f"✅ Reminder `#{rid}` deleted.", parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            f"❌ Reminder `#{rid}` not found.", parse_mode=ParseMode.MARKDOWN
        )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data.startswith("del:"):
        try:
            rid = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            await query.edit_message_text("⚠️ Invalid reminder ID.")
            return

        if db.delete_reminder(rid, query.from_user.id):
            await query.edit_message_text(
                f"✅ Reminder `#{rid}` deleted.", parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.edit_message_text(
                f"❌ Reminder `#{rid}` not found.", parse_mode=ParseMode.MARKDOWN
            )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Parse natural language and create a reminder."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    lower = text.lower()
    for prefix in ("remind me ", "remind ", "reminder "):
        if lower.startswith(prefix):
            text = text[len(prefix):]
            lower = text.lower()
            break

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # ── Weekly ──
    if "every" in lower and any(
        d in lower
        for d in (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        )
    ):
        parsed = parse_weekly(text)
        if not parsed:
            await update.message.reply_text(
                "❌ Couldn't parse. Example:\n"
                "`Every monday at 09:00 team meeting`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        day, hour, minute = parsed
        remind_at = next_weekly_datetime(day, hour, minute)
        label = extract_label(text, default=f"Weekly reminder ({day})")
        rid = db.add_reminder(
            chat_id,
            user_id,
            label,
            remind_at,
            repeat_type="weekly",
            repeat_value=hour * 100 + minute,
        )
        await update.message.reply_text(
            f"✅ Weekly reminder `#{rid}` set for every *{day.capitalize()}* at "
            f"*{hour:02d}:{minute:02d}*.\n📝 {label}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── Daily ──
    parsed_daily = parse_daily(text)
    if parsed_daily:
        hour, minute = parsed_daily
        remind_at = next_daily_datetime(hour, minute)
        label = extract_label(text, default="Daily reminder")
        rid = db.add_reminder(
            chat_id,
            user_id,
            label,
            remind_at,
            repeat_type="daily",
            repeat_value=hour * 100 + minute,
        )
        await update.message.reply_text(
            f"✅ Daily reminder `#{rid}` set for *{hour:02d}:{minute:02d}*.\n📝 {label}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── Relative ──
    delta = parse_relative(text)
    if delta:
        remind_at = datetime.now(TIMEZONE) + delta
        label = extract_label(text, default="Reminder")
        rid = db.add_reminder(chat_id, user_id, label, remind_at)
        await update.message.reply_text(
            f"✅ Reminder `#{rid}` set for "
            f"*{remind_at.strftime('%Y-%m-%d %H:%M')}*.\n📝 {label}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(
        "🤔 I didn't understand. Try:\n"
        "• `Remind me in 30 minutes to stretch`\n"
        "• `Every day at 08:30 to wake up`\n"
        "• `Every monday at 09:00 team meeting`",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─────────────────────── Scheduler Job ───────────────────────

async def check_due_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatch every reminder whose time has come."""
    now_iso = datetime.now(TIMEZONE).isoformat()
    due = db.get_due_reminders(now_iso)

    for row in due:
        rid = row["id"]
        chat_id = row["chat_id"]
        user_id = row["user_id"]
        text = row["text"]
        remind_at = row["remind_at"]
        rtype = row["repeat_type"]
        rval = row["repeat_value"]

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 *Reminder!*\n\n{text}",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.exception("Failed to send reminder #%s: %s", rid, e)

        try:
            if rtype == "daily":
                hour, minute = divmod(rval, 100)
                db.update_reminder_time(rid, next_daily_datetime(hour, minute))
            elif rtype == "weekly":
                old_dt = datetime.fromisoformat(remind_at)
                db.update_reminder_time(rid, old_dt + timedelta(days=7))
            else:
                db.delete_reminder(rid, user_id)
        except Exception:
            logger.exception("Failed to reschedule #%s", rid)


# ─────────────────────── Health Server ───────────────────────

def run_health_server() -> None:
    port = int(os.getenv("PORT", "8080"))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *args):
            return  # silence

    server = HTTPServer(("0.0.0.0", port), Handler)
    logger.info("Health server listening on :%s", port)
    server.serve_forever()


# ─────────────────────────── Main ───────────────────────────

def main() -> None:
    db.init_db()
    logger.info("Database initialized at %s", os.getenv("DB_PATH", "reminders.db"))

    Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.job_queue.run_repeating(check_due_reminders, interval=30, first=5)

    logger.info("🤖 Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
