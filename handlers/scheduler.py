from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.constants import ChatType
from database.db import (
    ensure_group, get_group, add_schedule, delete_schedule,
    list_schedules, clear_schedules, set_group_value, delete_schedule_slot
)
from handlers.common import is_owner, can_manage_group, require_group_admin, ensure
from config import TIME_FORMAT

def parse_time(text):
    text = " ".join(text.strip().upper().split())
    datetime.strptime(text, "%I:%M %p")
    return text

async def schedule_cmd(update, context):
    """Add one or many EVERY DAY windows in a single message.

    Group example:
      /schedule
      08:00 AM - 11:00 AM
      02:00 PM - 05:00 PM
      09:00 PM - 01:00 AM

    Private owner example:
      /schedulefor CHAT_ID
      08:00 AM - 11:00 AM
      02:00 PM - 05:00 PM
      09:00 PM - 01:00 AM
    """
    await ensure(update)

    raw_text = update.effective_message.text or ""
    # Keep the body exactly as sent so newlines between windows are supported.
    body = raw_text

    if update.effective_chat.type == ChatType.PRIVATE:
        if not await is_owner(update):
            return
        lines = raw_text.strip().splitlines()
        if not lines:
            await update.effective_message.reply_text(
                "⏰ Use:\n/schedulefor CHAT_ID\n08:00 AM - 11:00 AM\n02:00 PM - 05:00 PM\n09:00 PM - 01:00 AM"
            )
            return
        command_line = lines[0].strip()
        parts = command_line.split()
        if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
            await update.effective_message.reply_text(
                "⏰ Use:\n<code>/schedulefor CHAT_ID</code>\n"
                "<code>08:00 AM - 11:00 AM</code>\n"
                "<code>02:00 PM - 05:00 PM</code>\n"
                "<code>09:00 PM - 01:00 AM</code>",
                parse_mode="HTML"
            )
            return
        target = int(parts[1])
        if not await can_manage_group(update, target):
            await update.effective_message.reply_text("⛔ You cannot manage that group.")
            return
        chat = await context.bot.get_chat(target)
        await ensure_group(target, chat.title or str(target), chat.type)
        # Body is everything after /schedulefor CHAT_ID.
        body = raw_text.split("\n", 1)[1] if "\n" in raw_text else " ".join(parts[2:])
    else:
        if not await require_group_admin(update, context):
            return
        target = update.effective_chat.id
        # Body is everything after /schedule.
        body = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text.split(None, 1)[1] if len(raw_text.split(None, 1)) == 2 else ""

    # Import the same parser used by the Timing panel so both flows behave identically.
    from handlers.commands import parse_multiple_time_windows
    try:
        windows = parse_multiple_time_windows(body)
    except ValueError:
        await update.effective_message.reply_text(
            "❌ <b>INVALID TIMING FORMAT</b>\n\n"
            "Ek hi message mein aise bhejo:\n\n"
            "<code>08:00 AM - 11:00 AM</code>\n"
            "<code>02:00 PM - 05:00 PM</code>\n"
            "<code>09:00 PM - 01:00 AM</code>",
            parse_mode="HTML"
        )
        return

    added = []
    for unlock, lock in windows:
        sid = await add_schedule(target, unlock, lock)
        added.append((sid, unlock, lock))

    lines = "\n".join(
        f"⏰ <code>{unlock} - {lock}</code>" for _, unlock, lock in added
    )
    # Apply the newly saved schedule immediately instead of waiting for the next
    # 15-second scheduler tick. The normal tick continues to re-apply it thereafter.
    try:
        from services.scheduler import apply_scheduler
        await apply_scheduler(context.application)
    except Exception:
        # The scheduler loop will retry on its next tick; saving the schedule itself
        # must not fail just because an immediate Telegram reconciliation failed.
        pass

    await update.effective_message.reply_text(
        "⚡ <b>ZEUS • GROUP TIMING SET</b>\n\n"
        f"{lines}\n\n"
        "📅 <b>EVERY DAY</b>\n"
        f"📦 <b>{len(added)} window(s)</b> added automatically.",
        parse_mode="HTML"
    )

async def unschedule_cmd(update, context):
    await ensure(update)
    if update.effective_chat.type == ChatType.PRIVATE:
        if not await is_owner(update):
            return
        if len(context.args) != 2 or not context.args[0].lstrip("-").isdigit() or not context.args[1].isdigit():
            await update.effective_message.reply_text("Use: /unschedulefor CHAT_ID SLOT_ID")
            return
        target, sid = int(context.args[0]), int(context.args[1])
        if not await can_manage_group(update, target):
            await update.effective_message.reply_text("⛔ You cannot manage that group.")
            return
    else:
        if not await require_group_admin(update, context):
            return
        if not context.args or not context.args[0].isdigit():
            await update.effective_message.reply_text("Use: /unschedule SLOT_NUMBER")
            return
        target, slot_number = update.effective_chat.id, int(context.args[0])

    if update.effective_chat.type == ChatType.PRIVATE:
        from database.db import delete_schedule
        await delete_schedule(target, sid)
        removed = True
    else:
        removed = await delete_schedule_slot(target, slot_number)

    if not removed:
        await update.effective_message.reply_text("❌ That timing slot does not exist.")
        return
    try:
        from services.scheduler import apply_scheduler
        await apply_scheduler(context.application)
    except Exception as exc:
        print(f"⚠️ WARNING | Immediate scheduler sync after delete failed: {exc}")
    await update.effective_message.reply_text("🗑️ <b>WINDOW REMOVED</b>", parse_mode="HTML")


async def clear_timing_cmd(update, context):
    """Clear all scheduler windows for the current group."""
    await ensure(update)
    if update.effective_chat.type == ChatType.PRIVATE:
        if not await is_owner(update):
            return
        await update.effective_message.reply_text("Use /clear all inside the group.")
        return

    if not await require_group_admin(update, context):
        return

    if not context.args or context.args[0].lower() != "all":
        await update.effective_message.reply_text("Use: /clear all")
        return

    target = update.effective_chat.id
    existing = await list_schedules(target)
    if not existing:
        await update.effective_message.reply_text("ℹ️ No timing windows are currently set.")
        return

    await clear_schedules(target)
    # Removing the scheduler must also remove any scheduler-applied restriction
    # immediately. Otherwise Telegram can remain locked while the DB says OPEN,
    # which then prevents the next schedule window from unlocking correctly.
    try:
        from services.scheduler import OPEN_PERMS
        await context.bot.set_chat_permissions(target, OPEN_PERMS)
    except Exception as exc:
        # Keep the schedule cleared even if Telegram permission reconciliation fails.
        await update.effective_message.reply_text(
            f"⚠️ Timing cleared, but I could not reset group permissions: {exc}",
            parse_mode="HTML"
        )
        await set_group_value(target, "locked", 0)
        return
    await set_group_value(target, "locked", 0)

    await update.effective_message.reply_text(
        "✅ <b>Timing cleared</b>\n\n"
        "All group timing windows have been removed.",
        parse_mode="HTML"
    )

async def timezone_cmd(update, context):
    await ensure(update)
    if update.effective_chat.type == ChatType.PRIVATE:
        if not await is_owner(update):
            return
        if len(context.args) != 2 or not context.args[0].lstrip("-").isdigit():
            await update.effective_message.reply_text("Use: /timezonefor CHAT_ID Asia/Kolkata")
            return
        target, tz = int(context.args[0]), context.args[1]
        if not await can_manage_group(update, target):
            await update.effective_message.reply_text("⛔ You cannot manage that group.")
            return
    else:
        if not await require_group_admin(update, context):
            return
        target = update.effective_chat.id
        tz = context.args[0] if context.args else None
        if not tz:
            g = await get_group(target)
            await update.effective_message.reply_text(f"🌐 <code>{g['timezone']}</code>", parse_mode="HTML")
            return
    try:
        ZoneInfo(tz)
    except Exception:
        await update.effective_message.reply_text("❌ Invalid IANA timezone. Example: Asia/Kolkata")
        return
    await set_group_value(target, "timezone", tz)
    try:
        from services.scheduler import apply_scheduler
        await apply_scheduler(context.application)
    except Exception as exc:
        print(f"⚠️ WARNING | Immediate timezone scheduler sync failed: {exc}")
    await update.effective_message.reply_text(
        f"🌐 <b>TIMEZONE UPDATED</b>\n\n<code>{tz}</code>",
        parse_mode="HTML"
    )
