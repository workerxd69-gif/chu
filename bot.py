import asyncio
import logging
import re
from collections import defaultdict, deque
from datetime import timedelta
from datetime import datetime, timezone

from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ChatMemberHandler,
    MessageHandler, filters
)

import config
from database.db import init_db, ensure_group, ensure_user, get_group, get_filters, track_file, add_warning, add_log
from handlers.commands import (
    start, help_cmd, panel, groups_cmd, id_cmd, group_info, warn, resetwarn,
    mute, unmute, ban, unban, kick, delete_cmd, purge, lock, unlock, rules,
    setwelcome, setgoodbye, setrules, filter_cmd, files_cmd, broadcast, gbroadcast,
    pending_text, cancel_cmd,
    admin_cmd, unadmin_cmd)
from handlers.scheduler import schedule_cmd, unschedule_cmd, timezone_cmd, clear_timing_cmd
from handlers.callbacks import callbacks
from services.scheduler import apply_scheduler
from handlers.common import is_owner
from utils import parse_duration, OPEN_PERMS

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.WARNING)

# Keep terminal clean: Telegram/httpx and APScheduler run quietly.
for _logger in ("httpx", "httpcore", "apscheduler", "telegram", "telegram.ext", "telegram.ext.Application"):
    logging.getLogger(_logger).setLevel(logging.WARNING)

logger = logging.getLogger("ZEUS")

# Lightweight in-memory security state. It is intentionally ephemeral and scoped
# per chat/user; restart simply clears old rate-limit history.
_message_times = defaultdict(deque)
_duplicate_messages = defaultdict(deque)
_join_times = defaultdict(deque)


async def scheduler_tick(context):
    await apply_scheduler(context.application)

async def on_my_chat_member(update, context):
    cm = update.my_chat_member
    if not cm:
        return
    chat = cm.chat
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        await ensure_group(chat.id, chat.title or str(chat.id), chat.type)

async def on_member_update(update, context):
    cm = update.chat_member
    if not cm:
        return
    chat = cm.chat
    user = cm.new_chat_member.user
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    g = await get_group(chat.id)
    old = cm.old_chat_member.status
    new = cm.new_chat_member.status

    joined = new in ("member", "restricted") and old in ("left", "kicked")
    if joined:
        now = datetime.now(timezone.utc)
        q = _join_times[chat.id]
        q.append(now)
        cutoff = now - timedelta(seconds=config.RAID_WINDOW_SECONDS)
        while q and q[0] < cutoff:
            q.popleft()

        if g and g["raid_protection"] and len(q) >= config.RAID_JOIN_THRESHOLD:
            try:
                await context.bot.send_message(
                    chat.id,
                    f"🛡 <b>Raid protection activated</b>\n\n{len(q)} members joined within {config.RAID_WINDOW_SECONDS}s. New joins are being monitored.",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        if g and g["join_verification"] and not user.is_bot:
            try:
                await context.bot.restrict_chat_member(
                    chat.id,
                    user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=now + timedelta(seconds=config.JOIN_VERIFICATION_TIMEOUT_SECONDS),
                    use_independent_chat_permissions=True,
                )
                sent = await context.bot.send_message(
                    chat.id,
                    f"👋 <b>Welcome, {user.mention_html()}</b>\n\nPlease verify yourself to chat in this group.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Verify", callback_data=f"verify_join:{chat.id}:{user.id}")]]),
                )
                logger.info("Verification requested chat=%s user=%s message=%s", chat.id, user.id, sent.message_id)
            except Exception as exc:
                logger.warning("Join verification failed chat=%s user=%s: %s", chat.id, user.id, exc)

        if g and g["welcome_enabled"] and not (g["join_verification"] and not user.is_bot):
            try:
                members = await chat.get_member_count()
                if g.get("welcome_reply_chat_id") and g.get("welcome_reply_message_id"):
                    await context.bot.copy_message(
                        chat_id=chat.id,
                        from_chat_id=g["welcome_reply_chat_id"],
                        message_id=g["welcome_reply_message_id"],
                    )
                else:
                    text = (g["welcome_text"] or "").format(
                        mention=user.mention_html(), username=user.username or "", user_id=user.id,
                        group_name=chat.title or "", members=members, date=datetime.now().date(),
                        time=datetime.now().strftime("%I:%M %p"), reason="", duration="", admin=""
                    )
                    await context.bot.send_message(chat.id, text, parse_mode="HTML")
            except Exception:
                pass

    if new in ("left", "kicked") and old not in ("left", "kicked") and g and g["goodbye_enabled"]:
        try:
            if g.get("goodbye_reply_chat_id") and g.get("goodbye_reply_message_id"):
                await context.bot.copy_message(
                    chat_id=chat.id,
                    from_chat_id=g["goodbye_reply_chat_id"],
                    message_id=g["goodbye_reply_message_id"],
                )
            else:
                text = (g["goodbye_text"] or "").format(
                    mention=user.mention_html(), username=user.username or "", user_id=user.id,
                    group_name=chat.title or "", members="", date=datetime.now().date(),
                    time=datetime.now().strftime("%I:%M %p"), reason="", duration="", admin=""
                )
                await context.bot.send_message(chat.id, text, parse_mode="HTML")
        except Exception:
            pass

async def process_file_tracking(update, context):
    m = update.effective_message
    c = update.effective_chat
    u = update.effective_user
    if not m or not c or c.type not in (ChatType.GROUP, ChatType.SUPERGROUP) or not u:
        return

    data = None
    if m.document:
        data = ("document", m.document.file_id, m.document.file_name, m.document.mime_type, m.document.file_size)
    elif m.photo:
        data = ("photo", m.photo[-1].file_id, "photo.jpg", "image/jpeg", m.photo[-1].file_size)
    elif m.video:
        data = ("video", m.video.file_id, m.video.file_name, m.video.mime_type, m.video.file_size)
    elif m.audio:
        data = ("audio", m.audio.file_id, m.audio.file_name, m.audio.mime_type, m.audio.file_size)
    elif m.voice:
        data = ("voice", m.voice.file_id, None, m.voice.mime_type, m.voice.file_size)
    elif m.animation:
        data = ("animation", m.animation.file_id, m.animation.file_name, m.animation.mime_type, m.animation.file_size)

    if data:
        await track_file(c.id, m.message_id, u.id, *data)

def _message_match_text(message):
    """Build the text Rose-style filters should inspect, including media filenames and captions."""
    parts = []
    if message.text:
        parts.append(message.text)
    if message.caption:
        parts.append(message.caption)
    if message.document:
        if message.document.file_name:
            parts.append(message.document.file_name)
        if message.document.mime_type:
            parts.append(message.document.mime_type)
    if message.video:
        if message.video.file_name:
            parts.append(message.video.file_name)
        if message.video.mime_type:
            parts.append(message.video.mime_type)
    if message.audio:
        if message.audio.file_name:
            parts.append(message.audio.file_name)
        if message.audio.mime_type:
            parts.append(message.audio.mime_type)
    if message.animation:
        if message.animation.file_name:
            parts.append(message.animation.file_name)
        if message.animation.mime_type:
            parts.append(message.animation.mime_type)
    return "\n".join(str(x) for x in parts if x).lower()

async def _delete_safely(message):
    try:
        await message.delete()
        return True
    except Exception as exc:
        logging.getLogger("ZEUS").warning("Delete failed for chat=%s message=%s: %s", getattr(message, "chat_id", "?"), getattr(message, "message_id", "?"), exc)
        return False

async def _restrict_temporarily(chat, user_id, seconds):
    try:
        await chat.restrict_member(
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=datetime.now(timezone.utc) + timedelta(seconds=seconds),
            use_independent_chat_permissions=True,
        )
        return True
    except Exception as exc:
        logger.warning("Temporary restriction failed chat=%s user=%s: %s", chat.id, user_id, exc)
        return False

async def filter_responder(update, context):
    """MissRose-style keyword responder. Runs independently from moderation.

    A filter is created by replying to the saved message/media with /filter <trigger>.
    Any group member whose message/caption contains that trigger (case-insensitive)
    receives the saved content again.
    """
    m = update.effective_message
    c = update.effective_chat
    u = update.effective_user
    if not m or not c or c.type not in (ChatType.GROUP, ChatType.SUPERGROUP) or not u or u.is_bot:
        return False

    text = _message_match_text(m)
    if not text:
        return False

    fs = await get_filters(c.id)
    for row in fs:
        word, action, reply_text, reply_chat_id, reply_message_id, reply_media_type, reply_file_id, reply_caption = (list(row) + [None] * 8)[:8]
        trigger = str(word or "").strip().lower()
        if action != "reply" or not trigger or trigger not in text:
            continue

        try:
            # Prefer copying the original Telegram message. This preserves the
            # exact message payload (including animations, custom emoji/entities,
            # captions and other Telegram metadata) just like broadcast.
            if reply_chat_id and reply_message_id:
                await context.bot.copy_message(
                    chat_id=c.id,
                    from_chat_id=reply_chat_id,
                    message_id=reply_message_id,
                )
            elif reply_media_type and reply_file_id:
                cap = reply_caption or None
                if reply_media_type == "photo":
                    await context.bot.send_photo(chat_id=c.id, photo=reply_file_id, caption=cap)
                elif reply_media_type == "video":
                    await context.bot.send_video(chat_id=c.id, video=reply_file_id, caption=cap)
                elif reply_media_type == "animation":
                    await context.bot.send_animation(chat_id=c.id, animation=reply_file_id, caption=cap)
                elif reply_media_type == "document":
                    await context.bot.send_document(chat_id=c.id, document=reply_file_id, caption=cap)
                elif reply_media_type == "audio":
                    await context.bot.send_audio(chat_id=c.id, audio=reply_file_id, caption=cap)
                elif reply_media_type == "voice":
                    await context.bot.send_voice(chat_id=c.id, voice=reply_file_id, caption=cap)
                elif reply_media_type == "sticker":
                    await context.bot.send_sticker(chat_id=c.id, sticker=reply_file_id)
                elif reply_media_type == "video_note":
                    await context.bot.send_video_note(chat_id=c.id, video_note=reply_file_id)
                else:
                    raise ValueError(f"Unsupported saved filter media type: {reply_media_type}")
            elif reply_text:
                await context.bot.send_message(chat_id=c.id, text=reply_text)
            else:
                logger.warning("Filter %s has no saved response chat=%s", trigger, c.id)
                continue
            await add_log(c.id, u.id, "FILTER_REPLY", u.id, trigger)
        except Exception as exc:
            logger.exception("Filter resend failed chat=%s trigger=%s: %s", c.id, trigger, exc)
        return True
    return False


async def security_filter(update, context):
    m = update.effective_message
    c = update.effective_chat
    u = update.effective_user
    if not m or not c or c.type not in (ChatType.GROUP, ChatType.SUPERGROUP) or not u or u.is_bot:
        return
    g = await get_group(c.id)
    if not g:
        return

    try:
        member = await c.get_member(u.id)
        is_admin = member.status in ("administrator", "creator", "owner")
    except Exception:
        # Never perform destructive moderation when Telegram cannot confirm status.
        return
    if is_admin:
        return

    text = _message_match_text(m)
    now = datetime.now(timezone.utc)
    state_key = (c.id, u.id)

    # Anti-flood: too many messages in a short window.
    times = _message_times[state_key]
    times.append(now)
    cutoff = now - timedelta(seconds=config.SECURITY_MESSAGE_WINDOW_SECONDS)
    while times and times[0] < cutoff:
        times.popleft()
    if g["anti_flood"] and len(times) > config.ANTI_FLOOD_MAX_MESSAGES:
        await _delete_safely(m)
        await add_log(c.id, u.id, "ANTI_FLOOD", u.id, f"count={len(times)}")
        await _restrict_temporarily(c, u.id, config.ANTI_SPAM_MUTE_SECONDS)
        return

    # Track recent message content for repeat-spam and duplicate detection.
    if text:
        dq = _duplicate_messages[state_key]
        dup_cutoff = now - timedelta(seconds=config.DUPLICATE_WINDOW_SECONDS)
        while dq and dq[0][0] < dup_cutoff:
            dq.popleft()
        dq.append((now, text))
        repeats = sum(1 for _, value in dq if value == text)

        if g["anti_spam"] and repeats >= config.ANTI_SPAM_REPEAT_THRESHOLD:
            await _delete_safely(m)
            await add_log(c.id, u.id, "ANTI_SPAM", u.id, text[:120])
            await _restrict_temporarily(c, u.id, config.ANTI_SPAM_MUTE_SECONDS)
            return

        if g["duplicate_messages"] and len(dq) >= 2 and dq[-2][1] == text:
            await _delete_safely(m)
            await add_log(c.id, u.id, "DUPLICATE_MESSAGE", u.id, text[:120])
            return

    if g["mention_spam"]:
        raw = m.text or m.caption or ""
        mention_count = len(m.entities or []) + len(m.caption_entities or [])
        mention_count += len(re.findall(r"@[A-Za-z0-9_]{3,}", raw))
        if mention_count >= config.MENTION_SPAM_MAX:
            await _delete_safely(m)
            await add_log(c.id, u.id, "MENTION_SPAM", u.id, f"mentions={mention_count}")
            return

    if g["bad_word_filter"] and text:
        bad_words = tuple(str(x).strip().lower() for x in getattr(config, "BAD_WORDS", ()) if str(x).strip())
        matched = next((word for word in bad_words if word in text), None)
        if matched:
            await _delete_safely(m)
            await add_log(c.id, u.id, "BAD_WORD", u.id, matched[:120])
            return

    if g["lock_files"] and (m.document or m.audio or m.video):
        await _delete_safely(m); return
    if g["lock_media"] and any([m.photo, m.video, m.animation, m.audio]):
        await _delete_safely(m); return
    if g["lock_stickers"] and m.sticker:
        await _delete_safely(m); return
    if g["lock_gifs"] and m.animation:
        await _delete_safely(m); return
    if g["lock_voice"] and m.voice:
        await _delete_safely(m); return
    if (g["lock_forwards"] or g["anti_forward"]) and getattr(m, "forward_origin", None):
        await _delete_safely(m)
        await add_log(c.id, u.id, "FORWARD_BLOCK", u.id)
        return
    if (g["anti_link"] or g["lock_links"]) and any(x in text for x in ("http://", "https://", "t.me/", "www.")):
        await _delete_safely(m); return
    if g["caps_protection"] and len(text) >= 12:
        source_text = m.text or m.caption or ""
        letters = [ch for ch in source_text if ch.isalpha()]
        if letters and sum(ch.isupper() for ch in source_text if ch.isalpha()) / len(letters) >= 0.85:
            await _delete_safely(m)


def escape_html(value):
    import html
    return html.escape(str(value or ""))

def esc_name(value):
    return escape_html(value)


async def tracker(update, context):
    if update.effective_user:
        await ensure_user(
            update.effective_user.id,
            update.effective_user.username,
            update.effective_user.full_name,
            update.effective_user.is_bot,
            bool(update.effective_chat and update.effective_chat.type == ChatType.PRIVATE)
        )
    if update.effective_chat and update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        await ensure_group(
            update.effective_chat.id,
            update.effective_chat.title or str(update.effective_chat.id),
            update.effective_chat.type
        )
        await process_file_tracking(update, context)
        # Filter responses are independent of moderation settings.
        if await filter_responder(update, context):
            return
        await security_filter(update, context)


async def route_private_text(update, context):
    # Handles text entered in private/group chat when a pending inline-panel action exists.
    try:
        from handlers.commands import pending_text
        await pending_text(update, context)
    except Exception as exc:
        print(f"❌ ERROR | Private/group control input failed: {exc}")


async def error_handler(update, context):
    print(f"❌ ERROR | {context.error}")

async def startup_notice(app):
    try:
        await app.bot.send_message(
            config.OWNER_ID,
            f"⚡ <b>ZEUS ONLINE</b>\n\n"
            f"🟢 Bot started successfully.\n"
            f"🔧 Version: <code>{config.BOT_VERSION}</code>\n"
            f"⏰ Scheduler: <code>{config.SCHEDULER_TICK_SECONDS}s</code>\n"
            f"🛡 Control center: /panel",
            parse_mode="HTML"
        )
    except Exception as exc:
        logging.warning("Startup owner notification failed: %s", exc)

async def main():
    if not config.BOT_TOKEN or config.BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("Put BOT_TOKEN in config.py")

    await init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    commands = {
        "start": start, "help": help_cmd, "panel": panel, "groups": groups_cmd,
        "id": id_cmd, "group": group_info, "warn": warn, "resetwarn": resetwarn,
        "mute": mute, "unmute": unmute, "ban": ban, "unban": unban, "kick": kick,
        "del": delete_cmd, "purge": purge, "lock": lock, "unlock": unlock,
        "rules": rules, "setwelcome": setwelcome, "setgoodbye": setgoodbye,
        "setrules": setrules, "filter": filter_cmd, "files": files_cmd,
        "broadcast": broadcast, "gbroadcast": gbroadcast, "cancel": cancel_cmd,
        "admin": admin_cmd, "unadmin": unadmin_cmd,
        "schedule": schedule_cmd, "schedulefor": schedule_cmd,
        "unschedule": unschedule_cmd, "unschedulefor": unschedule_cmd,
        "timezone": timezone_cmd, "timezonefor": timezone_cmd, "clear": clear_timing_cmd,
    }
    for name, fn in commands.items():
        app.add_handler(CommandHandler(name, fn))

    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(on_member_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, route_private_text), group=10)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, tracker), group=20)
    app.add_error_handler(error_handler)

    if app.job_queue:
        app.job_queue.run_repeating(scheduler_tick, interval=config.SCHEDULER_TICK_SECONDS, first=5)

    print("⚡ ZEUS • ONLINE")
    await app.initialize()
    await app.start()
    # Reconcile timing immediately on every restart; do not wait for first 15s tick.
    try:
        await apply_scheduler(app)
    except Exception as exc:
        logger.error("Initial scheduler reconciliation failed: %s", exc)
    await startup_notice(app)
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
