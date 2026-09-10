from datetime import datetime, timezone
import asyncio
import html
import logging
import re

from telegram import ChatPermissions, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from config import (OWNER_ID, WARN_ACTIONS, WARN_MUTE_DURATION, BOT_BRAND, BROADCAST_DELAY_SECONDS, FILTER_ACTIONS,
                     PENDING_ACTION_TTL_SECONDS, FILE_LIST_PAGE_SIZE, BROADCAST_TO_GROUPS_ENABLED,
                     ADMIN_DEFAULT_CAN_MANAGE_CHAT, ADMIN_DEFAULT_CAN_DELETE_MESSAGES,
                     ADMIN_DEFAULT_CAN_RESTRICT_MEMBERS, ADMIN_DEFAULT_CAN_INVITE_USERS,
                     ADMIN_DEFAULT_CAN_CHANGE_INFO, ADMIN_DEFAULT_CAN_PIN_MESSAGES,
                     ADMIN_DEFAULT_CAN_MANAGE_TOPICS)
from database.db import (
    ensure_group, ensure_user, get_group, list_groups, list_schedules,
    add_warning, reset_warnings, add_filter, remove_filter, get_filters,
    add_log, recent_logs, private_users, list_files, count_files,
    get_file, get_pending, set_pending, clear_pending
)
from database.db import set_group_value
from handlers.common import ensure, is_owner, require_owner_private, require_group_admin, can_manage_group
from utils import parse_duration, duration_label, OPEN_PERMS

def esc(s):
    return html.escape(str(s or ""))


def _filter_reply_payload(message):
    """Return durable data for a filter response; prefer file_id over message_id."""
    if not message:
        return None, None, None, None, None, None
    if message.photo:
        return None, message.chat_id, message.message_id, "photo", message.photo[-1].file_id, message.caption
    if message.video:
        return None, message.chat_id, message.message_id, "video", message.video.file_id, message.caption
    if message.animation:
        return None, message.chat_id, message.message_id, "animation", message.animation.file_id, message.caption
    if message.document:
        return None, message.chat_id, message.message_id, "document", message.document.file_id, message.caption
    if message.audio:
        return None, message.chat_id, message.message_id, "audio", message.audio.file_id, message.caption
    if message.voice:
        return None, message.chat_id, message.message_id, "voice", message.voice.file_id, message.caption
    if message.sticker:
        return None, message.chat_id, message.message_id, "sticker", message.sticker.file_id, None
    if message.video_note:
        return None, message.chat_id, message.message_id, "video_note", message.video_note.file_id, None
    if message.text:
        return message.text, message.chat_id, message.message_id, None, None, None
    return None, message.chat_id, message.message_id, None, None, None


async def admin_cmd(update, context):
    """Promote a replied user (or @username/user_id) to administrator."""
    if not await require_group_admin(update, context):
        return

    m = update.effective_message
    chat = update.effective_chat
    target = None

    if m.reply_to_message and m.reply_to_message.from_user:
        target = m.reply_to_message.from_user
    elif context.args:
        raw = context.args[0]
        try:
            target = await context.bot.get_chat(raw if raw.startswith("@") else int(raw))
        except Exception:
            await m.reply_text("❌ User not found. Reply to the user's message and use /admin.")
            return
    else:
        await m.reply_text(
            "👑 <b>ADD ADMIN</b>\n\n"
            "Reply to the user's message and send:\n"
            "<code>/admin</code>\n\n"
            "Or use:\n"
            "<code>/admin @username</code>",
            parse_mode="HTML"
        )
        return

    try:
        caller = await chat.get_member(update.effective_user.id)
        if update.effective_user.id != OWNER_ID and not getattr(caller, "can_promote_members", False):
            await m.reply_text("⛔ You need Telegram's <b>Add New Admins</b> permission.", parse_mode="HTML")
            return

        from telegram import ChatAdministratorRights
        rights = ChatAdministratorRights(
            is_anonymous=False,
            can_manage_chat=ADMIN_DEFAULT_CAN_MANAGE_CHAT,
            can_delete_messages=ADMIN_DEFAULT_CAN_DELETE_MESSAGES,
            can_manage_video_chats=True,
            can_restrict_members=ADMIN_DEFAULT_CAN_RESTRICT_MEMBERS,
            can_promote_members=False,
            can_change_info=ADMIN_DEFAULT_CAN_CHANGE_INFO,
            can_invite_users=ADMIN_DEFAULT_CAN_INVITE_USERS,
            can_post_messages=True,
            can_edit_messages=True,
            can_pin_messages=ADMIN_DEFAULT_CAN_PIN_MESSAGES,
            can_manage_topics=ADMIN_DEFAULT_CAN_MANAGE_TOPICS,
            can_post_stories=True,
            can_edit_stories=True,
            can_delete_stories=True,
        )
        await context.bot.promote_chat_member(
            chat_id=chat.id,
            user_id=target.id,
            privileges=rights,
        )
        await add_log(chat.id, update.effective_user.id, "PROMOTE_ADMIN", target.id)
        await m.reply_text(
            f"👑 <b>ADMIN ADDED</b>\n\n"
            f"👤 {esc(getattr(target, 'full_name', target.id))}\n"
            f"🆔 <code>{target.id}</code>",
            parse_mode="HTML"
        )
    except Exception as exc:
        await m.reply_text(
            f"❌ <b>ADMIN ADD FAILED</b>\n\n<code>{esc(exc)}</code>",
            parse_mode="HTML"
        )

async def unadmin_cmd(update, context):
    """Demote a replied admin or a specified user."""
    if not await require_group_admin(update, context):
        return

    m = update.effective_message
    chat = update.effective_chat
    target = None

    if m.reply_to_message and m.reply_to_message.from_user:
        target = m.reply_to_message.from_user
    elif context.args:
        try:
            target = await context.bot.get_chat(
                context.args[0] if context.args[0].startswith("@") else int(context.args[0])
            )
        except Exception:
            await m.reply_text("❌ User not found. Reply to the admin and use /unadmin.")
            return
    else:
        await m.reply_text("Reply to an admin or use /unadmin @username")
        return

    try:
        caller = await chat.get_member(update.effective_user.id)
        if update.effective_user.id != OWNER_ID and not getattr(caller, "can_promote_members", False):
            await m.reply_text("⛔ You need Telegram's <b>Add New Admins</b> permission.", parse_mode="HTML")
            return

        await context.bot.promote_chat_member(
            chat_id=chat.id,
            user_id=target.id,
            is_anonymous=False,
            can_manage_chat=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_post_messages=False,
            can_edit_messages=False,
            can_pin_messages=False,
            can_manage_topics=False,
            can_post_stories=False,
            can_edit_stories=False,
            can_delete_stories=False,
        )
        await add_log(chat.id, update.effective_user.id, "DEMOTE_ADMIN", target.id)
        await m.reply_text(
            f"✅ <b>ADMIN REMOVED</b>\n\n👤 {esc(getattr(target, 'full_name', target.id))}",
            parse_mode="HTML"
        )
    except Exception as exc:
        await m.reply_text(
            f"❌ <b>DEMOTE FAILED</b>\n\n<code>{esc(exc)}</code>",
            parse_mode="HTML"
        )


def parse_multiple_time_windows(text):
    """
    Accepts:
      08:00 AM - 11:00 AM
      08:00 AM - 11:00 AM 02:00 PM - 05:00 PM
      08:00 AM - 11:00 AM, 02:00 PM - 05:00 PM
    Returns list[(start, end)] in normalized AM/PM strings.
    """
    clean = " ".join((text or "").strip().split())
    # Find complete time pairs anywhere in the message.
    pattern = re.compile(
        r'(\d{1,2}:\d{2}\s*[AP]M)\s*(?:-|–|—|to)\s*(\d{1,2}:\d{2}\s*[AP]M)',
        re.I
    )
    matches = pattern.findall(clean)
    if not matches:
        raise ValueError("No valid time window found")

    windows = []
    for start, end in matches:
        start = " ".join(start.upper().split())
        end = " ".join(end.upper().split())
        datetime.strptime(start, "%I:%M %p")
        datetime.strptime(end, "%I:%M %p")
        if start == end:
            raise ValueError("Opening and closing time cannot be identical")
        windows.append((start, end))

    # Remove duplicates while preserving order.
    seen = set()
    unique = []
    for pair in windows:
        if pair not in seen:
            seen.add(pair)
            unique.append(pair)
    return unique


async def start(update, context):
    await ensure(update)
    if update.effective_chat.type == ChatType.PRIVATE and await is_owner(update):
        text = (
            f"⚡ <b>{BOT_BRAND} CONTROL CENTER</b>\n\n"
            "Welcome back, Owner.\n"
            "Everything important can be controlled from the buttons below.\n\n"
            "👥 Select a group → configure timing, security, files, messages, locks and logs."
        )
        from services.ui import main_panel
        await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=main_panel())
    elif update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text("⚡ ZEUS is online. Private controls are owner-only.")
    else:
        await update.effective_message.reply_text("⚡ <b>ZEUS ONLINE</b>\n\nUse /help for group commands.", parse_mode="HTML")

async def help_cmd(update, context):
    await ensure(update)
    text = (
        "⚡ <b>ZEUS COMMANDS</b>\n\n"
        "<b>Moderation</b>\n"
        "/warn • /mute 10m • /ban • /kick\n"
        "/unmute • /unban • /resetwarn\n"
        "/del • /purge 50\n\n"
        "<b>Group</b>\n"
        "/id • /group • /rules • /lock • /unlock\n"
        "/filter apk reply • reply to media: /filter apk\n"
        "/filter add apk delete|warn|mute\n"
        "/filter remove apk • /filter list\n"
        "/files\n\n"
        "<b>Private Owner</b>\n"
        "/start • /panel\n"
        "/broadcast • /gbroadcast\n"
        "/schedulefor • /unschedulefor • /timezonefor"
    )
    from services.ui import main_panel
    if update.effective_chat.type == ChatType.PRIVATE and await is_owner(update):
        await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=main_panel())
    else:
        await update.effective_message.reply_text(text, parse_mode="HTML")

async def panel(update, context):
    await ensure(update)

    if update.effective_chat.type == ChatType.PRIVATE:
        if not await require_owner_private(update, context):
            return
        from services.ui import main_panel
        await update.effective_message.reply_text(
            "⚡ <b>ZEUS CONTROL CENTER</b>\\n\\nChoose an operation.",
            parse_mode="HTML",
            reply_markup=main_panel()
        )
        return

    if not await require_group_admin(update, context):
        return

    from services.ui import group_local_panel
    await update.effective_message.reply_text(
        "⚡ <b>ZEUS GROUP CONTROL</b>\\n\\n"
        "Settings can be changed directly from this group.",
        parse_mode="HTML",
        reply_markup=group_local_panel(update.effective_chat.id)
    )

async def groups_cmd(update, context):
    await ensure(update)
    if not await require_owner_private(update, context):
        return
    groups = await list_groups()
    if not groups:
        await update.effective_message.reply_text(
            "👥 No groups registered yet.\n\nAdd ZEUS as admin to a group and send a message there."
        )
        return
    from services.ui import group_selector
    await update.effective_message.reply_text("👥 <b>SELECT GROUP</b>", parse_mode="HTML", reply_markup=group_selector(groups))

async def id_cmd(update, context):
    await ensure(update)
    m = update.effective_message
    if not m:
        return
    if m.reply_to_message and m.reply_to_message.from_user:
        u = m.reply_to_message.from_user
        await m.reply_text(
            f"🪪 <b>USER INFORMATION</b>\n\n"
            f"👤 Name: {esc(u.full_name)}\n"
            f"🆔 ID: <code>{u.id}</code>\n"
            f"🔹 Username: @{esc(u.username) if u.username else 'None'}\n"
            f"🤖 Bot: {'Yes' if u.is_bot else 'No'}",
            parse_mode="HTML"
        )
    else:
        c = update.effective_chat
        await m.reply_text(
            f"🪪 <b>CHAT INFORMATION</b>\n\n"
            f"🏷 {esc(c.title or c.full_name or 'Private Chat')}\n"
            f"🆔 <code>{c.id}</code>\n"
            f"📌 {c.type.upper()}",
            parse_mode="HTML"
        )

async def group_info(update, context):
    if not await require_group_admin(update, context):
        return
    from database.db import ensure_group
    c = update.effective_chat
    await ensure_group(c.id, c.title or str(c.id), c.type)
    g = await get_group(c.id)
    admins = await c.get_administrators()
    try:
        members = await c.get_member_count()
    except Exception:
        members = "?"
    slots = await list_schedules(c.id)
    await update.effective_message.reply_text(
        f"⚡ <b>GROUP INFORMATION</b>\n━━━━━━━━━━━━━━\n"
        f"🏷 <b>{esc(c.title)}</b>\n"
        f"🆔 <code>{c.id}</code>\n"
        f"📌 {c.type.upper()}\n"
        f"👥 Members: {members}\n"
        f"👑 Admins: {len(admins)}\n"
        f"🔒 State: {'LOCKED' if g['locked'] else 'OPEN'}\n"
        f"⏰ Daily windows: {len(slots)}\n"
        f"🌐 Timezone: <code>{g['timezone']}</code>\n"
        f"⚠️ Warn limit: {g['warn_limit']}\n"
        f"🛡 Anti-link: {'ON' if g['anti_link'] else 'OFF'}",
        parse_mode="HTML"
    )

async def warn(update, context):
    if not await require_group_admin(update, context): return
    m = update.effective_message
    if not m.reply_to_message:
        await m.reply_text("Reply to a user's message.")
        return
    target = m.reply_to_message.from_user
    reason = " ".join(context.args) or "No reason provided"
    # Never escalate warnings against Telegram administrators/owner.
    try:
        target_member = await m.chat.get_member(target.id)
        if getattr(target_member, "status", None) in ("administrator", "creator", "owner"):
            await m.reply_text("I can't issue escalating moderation actions against an administrator or the group owner.")
            return
    except Exception:
        pass
    count = await add_warning(m.chat_id, target.id)
    g = await get_group(m.chat_id)
    await add_log(m.chat_id, update.effective_user.id, "WARN", target.id, reason)
    await m.reply_text(
        f"⚠️ <b>WARNING ISSUED</b>\n\n"
        f"👤 {esc(target.full_name)}\n"
        f"⚠️ {count}/{g['warn_limit']}\n"
        f"📝 {esc(reason)}",
        parse_mode="HTML"
    )
    limit = max(1, int(g.get("warn_limit") or 3))
    if count == limit:
        action = "mute"
    elif count > limit:
        action = "ban"
    else:
        action = "warn"
    if action == "mute":
        td = parse_duration(WARN_MUTE_DURATION)
        if td:
            await m.chat.restrict_member(
                target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now(timezone.utc) + td
            )
    elif action == "ban":
        await m.chat.ban_member(target.id)

async def resetwarn(update, context):
    if not await require_group_admin(update, context): return
    m = update.effective_message
    if not m.reply_to_message:
        await m.reply_text("Reply to a user.")
        return
    await reset_warnings(m.chat_id, m.reply_to_message.from_user.id)
    await m.reply_text("✅ <b>Warnings reset.</b>", parse_mode="HTML")

async def _moderation_target(m):
    """Resolve the target exactly like Rose-style moderation: reply to the user message."""
    if not m or not m.reply_to_message or not m.reply_to_message.from_user:
        return None, "Reply to the user's message, then run the command."
    return m.reply_to_message.from_user, None


async def _ensure_bot_can_restrict(m, target_id, bot):
    """Give a useful error instead of silently failing when Telegram blocks moderation."""
    try:
        bot_member = await m.chat.get_member(bot.id)
        if bot_member.status not in ("administrator", "creator"):
            return False, "ZEUS must be an administrator in this group."
        if bot_member.status == "administrator" and not getattr(bot_member, "can_restrict_members", False):
            return False, "ZEUS needs Telegram's <b>Ban Users / Restrict Members</b> permission."

        target_member = await m.chat.get_member(target_id)
        if target_member.status in ("administrator", "creator"):
            return False, "I can't mute an administrator or the group owner."
    except Exception as exc:
        return False, f"Could not verify Telegram permissions: <code>{esc(exc)}</code>"
    return True, None


async def mute(update, context):
    if not await require_group_admin(update, context):
        return
    m = update.effective_message
    target, target_error = await _moderation_target(m)
    if target_error:
        await m.reply_text(
            "🔇 <b>MUTE</b>\n\n"
            f"{target_error}\n\n"
            "Usage: reply + <code>/mute 7d [reason]</code>\n"
            "Examples: <code>10m</code>, <code>2h</code>, <code>7d</code>, <code>2w</code>",
            parse_mode="HTML",
        )
        return

    if not context.args:
        await m.reply_text(
            "🔇 <b>MUTE</b>\n\n"
            "Usage: reply + <code>/mute 7d [reason]</code>",
            parse_mode="HTML",
        )
        return

    td = parse_duration(context.args[0])
    if not td or td.total_seconds() <= 0:
        await m.reply_text(
            "❌ <b>INVALID DURATION</b>\n\n"
            "Use: <code>10m</code>, <code>2h</code>, <code>7d</code> or <code>2w</code>.",
            parse_mode="HTML",
        )
        return

    ok, error = await _ensure_bot_can_restrict(m, target.id, context.bot)
    if not ok:
        await m.reply_text(f"❌ <b>MUTE FAILED</b>\n\n{error}", parse_mode="HTML")
        return

    reason = " ".join(context.args[1:]).strip() or "No reason provided"
    until = datetime.now(timezone.utc) + td
    try:
        await m.chat.restrict_member(
            target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
            use_independent_chat_permissions=True,
        )
    except Exception as exc:
        await m.reply_text(
            "❌ <b>MUTE FAILED</b>\n\n"
            f"<code>{esc(exc)}</code>\n\n"
            "Check that ZEUS is an admin with Restrict Members permission and that the target is not an admin.",
            parse_mode="HTML",
        )
        return

    await add_log(m.chat_id, update.effective_user.id, "MUTE", target.id, reason)
    await m.reply_text(
        f"🔇 <b>MUTED</b>\n\n"
        f"👤 {esc(target.full_name)}\n"
        f"⏱ <b>{duration_label(td)}</b>\n"
        f"🕒 Until: <code>{until.strftime('%Y-%m-%d %H:%M:%S UTC')}</code>\n"
        f"📝 {esc(reason)}",
        parse_mode="HTML"
    )


async def unmute(update, context):
    if not await require_group_admin(update, context):
        return
    m = update.effective_message
    t, target_error = await _moderation_target(m)
    if target_error:
        await m.reply_text("🔊 <b>UNMUTE</b>\n\nReply to the user's message, then use <code>/unmute</code>.", parse_mode="HTML")
        return

    ok, error = await _ensure_bot_can_restrict(m, t.id, context.bot)
    if not ok:
        await m.reply_text(f"❌ <b>UNMUTE FAILED</b>\n\n{error}", parse_mode="HTML")
        return
    try:
        await m.chat.restrict_member(t.id, permissions=OPEN_PERMS, use_independent_chat_permissions=True)
    except Exception as exc:
        await m.reply_text(f"❌ <b>UNMUTE FAILED</b>\n\n<code>{esc(exc)}</code>", parse_mode="HTML")
        return
    await add_log(m.chat_id, update.effective_user.id, "UNMUTE", t.id)
    await m.reply_text(f"🔊 <b>UNMUTED</b>\n\n👤 {esc(t.full_name)}", parse_mode="HTML")

async def ban(update, context):
    if not await require_group_admin(update, context):
        return
    m = update.effective_message
    target, target_error = await _moderation_target(m)
    if target_error:
        await m.reply_text("🚫 <b>BAN</b>\n\nReply to the user's message, then use <code>/ban [duration] [reason]</code>.", parse_mode="HTML")
        return

    td = None
    reason_args = list(context.args)
    if context.args:
        candidate = parse_duration(context.args[0])
        if candidate and candidate.total_seconds() > 0:
            td = candidate
            reason_args = context.args[1:]
        elif re.fullmatch(r"\d+[smhdw]", context.args[0].strip().lower()):
            await m.reply_text("❌ <b>INVALID BAN DURATION</b>\n\nUse <code>10m</code>, <code>2h</code>, <code>7d</code> or <code>2w</code>.", parse_mode="HTML")
            return
    ok, error = await _ensure_bot_can_restrict(m, target.id, context.bot)
    if not ok:
        await m.reply_text(f"❌ <b>BAN FAILED</b>\n\n{error}", parse_mode="HTML")
        return

    reason = " ".join(reason_args).strip() or "No reason provided"
    until = datetime.now(timezone.utc) + td if td else None
    try:
        await m.chat.ban_member(target.id, until_date=until)
    except Exception as exc:
        await m.reply_text(f"❌ <b>BAN FAILED</b>\n\n<code>{esc(exc)}</code>", parse_mode="HTML")
        return
    await add_log(m.chat_id, update.effective_user.id, "BAN", target.id, reason)
    await m.reply_text(
        f"🚫 <b>BANNED</b>\n👤 {esc(target.full_name)}\n"
        f"⏱ {duration_label(td) if td else 'Permanent'}\n📝 {esc(reason)}",
        parse_mode="HTML"
    )

async def unban(update, context):
    if not await require_group_admin(update, context):
        return
    m = update.effective_message
    target, target_error = await _moderation_target(m)
    if target_error:
        await m.reply_text("✅ <b>UNBAN</b>\n\nReply to the user's message, then use <code>/unban</code>.", parse_mode="HTML")
        return
    try:
        await m.chat.unban_member(target.id, only_if_banned=True)
    except Exception as exc:
        await m.reply_text(f"❌ <b>UNBAN FAILED</b>\n\n<code>{esc(exc)}</code>", parse_mode="HTML")
        return
    await add_log(m.chat_id, update.effective_user.id, "UNBAN", target.id)
    await m.reply_text("✅ <b>USER UNBANNED</b>", parse_mode="HTML")

async def kick(update, context):
    if not await require_group_admin(update, context):
        return
    m = update.effective_message
    target, target_error = await _moderation_target(m)
    if target_error:
        await m.reply_text("👢 <b>KICK</b>\n\nReply to the user's message, then use <code>/kick</code>.", parse_mode="HTML")
        return
    ok, error = await _ensure_bot_can_restrict(m, target.id, context.bot)
    if not ok:
        await m.reply_text(f"❌ <b>KICK FAILED</b>\n\n{error}", parse_mode="HTML")
        return
    try:
        await m.chat.ban_member(target.id)
        await m.chat.unban_member(target.id)
    except Exception as exc:
        await m.reply_text(f"❌ <b>KICK FAILED</b>\n\n<code>{esc(exc)}</code>", parse_mode="HTML")
        return
    await add_log(m.chat_id, update.effective_user.id, "KICK", target.id)
    await m.reply_text(f"👢 <b>KICKED</b>\n👤 {esc(target.full_name)}", parse_mode="HTML")

async def delete_cmd(update, context):
    if not await require_group_admin(update, context): return
    m = update.effective_message
    if m.reply_to_message:
        try: await m.reply_to_message.delete()
        except Exception: pass
    try: await m.delete()
    except Exception: pass

async def purge(update, context):
    if not await require_group_admin(update, context):
        return

    m = update.effective_message
    if not m.reply_to_message:
        await m.reply_text(
            "🧹 <b>PURGE</b>\n\n"
            "Reply to the first message you want removed, then send:\n"
            "<code>/purge</code>\n\n"
            "Optional limit:\n"
            "<code>/purge 50</code>",
            parse_mode="HTML"
        )
        return

    start_id = m.reply_to_message.message_id
    limit = 100
    if context.args and context.args[0].isdigit():
        limit = min(max(int(context.args[0]), 1), 100)

    end_id = m.message_id
    first_id = max(start_id, end_id - limit + 1)
    deleted = 0

    for mid in range(first_id, end_id + 1):
        try:
            await context.bot.delete_message(m.chat_id, mid)
            deleted += 1
        except Exception:
            pass

    try:
        status = await m.chat.send_message(
            f"🧹 <b>PURGE COMPLETE</b>\n\n"
            f"🗑 Deleted: <code>{deleted}</code>\n"
            f"📍 From reply: <code>{start_id}</code>",
            parse_mode="HTML"
        )
        # Purge's completion message is only a temporary status; remove it too.
        try:
            await status.delete()
        except Exception:
            pass
    except Exception:
        return


async def lock(update, context):
    if not await require_group_admin(update, context): return
    m = update.effective_message
    try:
        from services.scheduler import LOCK_PERMS
        await m.chat.set_permissions(LOCK_PERMS)
        await set_group_value(m.chat_id, "locked", 1)
        await add_log(m.chat_id, update.effective_user.id, "LOCK")
        await m.reply_text("🔒 <b>GROUP LOCKED</b>", parse_mode="HTML")
    except Exception as exc:
        await m.reply_text(f"❌ <b>LOCK FAILED</b>\n\n<code>{esc(exc)}</code>", parse_mode="HTML")

async def unlock(update, context):
    if not await require_group_admin(update, context): return
    m = update.effective_message
    try:
        await m.chat.set_permissions(OPEN_PERMS)
        await set_group_value(m.chat_id, "locked", 0)
        await add_log(m.chat_id, update.effective_user.id, "UNLOCK")
        await m.reply_text("🔓 <b>GROUP UNLOCKED</b>", parse_mode="HTML")
    except Exception as exc:
        await m.reply_text(f"❌ <b>UNLOCK FAILED</b>\n\n<code>{esc(exc)}</code>", parse_mode="HTML")

async def rules(update, context):
    await ensure(update)
    g = await get_group(update.effective_chat.id)
    await update.effective_message.reply_text(g["rules_text"] or "No rules configured.", parse_mode="HTML")

async def setwelcome(update, context):
    if not await require_group_admin(update, context): return
    m = update.effective_message
    source = m.reply_to_message
    if source:
        await set_group_value(update.effective_chat.id, "welcome_reply_chat_id", source.chat_id)
        await set_group_value(update.effective_chat.id, "welcome_reply_message_id", source.message_id)
        await set_group_value(update.effective_chat.id, "welcome_text", None)
        await m.reply_text("✅ Welcome message saved. ZEUS will copy the exact original message.")
        return
    if not context.args:
        await m.reply_text(
            "Reply to the message you want ZEUS to copy, then send <code>/setwelcome</code>.\n"
            "Or use <code>/setwelcome Your message</code> for normal text.",
            parse_mode="HTML",
        )
        return
    await set_group_value(update.effective_chat.id, "welcome_reply_chat_id", None)
    await set_group_value(update.effective_chat.id, "welcome_reply_message_id", None)
    await set_group_value(update.effective_chat.id, "welcome_text", " ".join(context.args))
    await m.reply_text("✅ Welcome message updated.")

async def setgoodbye(update, context):
    if not await require_group_admin(update, context): return
    m = update.effective_message
    source = m.reply_to_message
    if source:
        await set_group_value(update.effective_chat.id, "goodbye_reply_chat_id", source.chat_id)
        await set_group_value(update.effective_chat.id, "goodbye_reply_message_id", source.message_id)
        await set_group_value(update.effective_chat.id, "goodbye_text", None)
        await m.reply_text("✅ Goodbye message saved. ZEUS will copy the exact original message.")
        return
    if not context.args:
        await m.reply_text(
            "Reply to the message you want ZEUS to copy, then send <code>/setgoodbye</code>.\n"
            "Or use <code>/setgoodbye Your message</code> for normal text.",
            parse_mode="HTML",
        )
        return
    await set_group_value(update.effective_chat.id, "goodbye_reply_chat_id", None)
    await set_group_value(update.effective_chat.id, "goodbye_reply_message_id", None)
    await set_group_value(update.effective_chat.id, "goodbye_text", " ".join(context.args))
    await m.reply_text("✅ Goodbye message updated.")

async def setrules(update, context):
    if not await require_group_admin(update, context): return
    if not context.args:
        await update.effective_message.reply_text("Use: /setrules Your rules")
        return
    await set_group_value(update.effective_chat.id, "rules_text", " ".join(context.args))
    await update.effective_message.reply_text("✅ Rules updated.")

async def filter_cmd(update, context):
    """MissRose-style saved-file filters.

    Usage:
      1. Reply to the file/message you want ZEUS to resend.
      2. Send: /filter <trigger>
      3. When <trigger> appears, ZEUS sends the saved file/message again.

    This intentionally keeps the filter feature focused on durable resend data.
    """
    if not await require_group_admin(update, context):
        return

    m = update.effective_message
    args = context.args or []

    if not args:
        await m.reply_text(
            "🧹 <b>FILTER</b>\n\n"
            "Reply to the file/message you want ZEUS to resend, then send:\n"
            "<code>/filter price</code>\n\n"
            "When someone sends <code>price</code>, ZEUS will send the saved file/message again.\n\n"
            "List: <code>/filter list</code>\n"
            "Remove: <code>/filter remove price</code>",
            parse_mode="HTML",
        )
        return

    command = args[0].lower()
    if command == "list":
        fs = await get_filters(m.chat_id)
        lines = []
        for row in fs:
            word, action, reply_text, _rch, _rmid, media_type, file_id, caption = (list(row) + [None] * 8)[:8]
            if action != "reply":
                continue
            kind = media_type or ("text" if reply_text else "saved message")
            lines.append(f"• <code>{esc(word)}</code> → <b>{esc(kind)}</b>")
        await m.reply_text(
            "🧹 <b>FILTERS</b>\n\n" + ("\n".join(lines) if lines else "No resend filters configured."),
            parse_mode="HTML",
        )
        return

    if command == "remove":
        if len(args) < 2:
            await m.reply_text("Use: <code>/filter remove price</code>", parse_mode="HTML")
            return
        word = " ".join(args[1:]).strip().strip('"').lower()
        await remove_filter(m.chat_id, word)
        await add_log(m.chat_id, update.effective_user.id, "FILTER_REMOVE", None, word)
        await m.reply_text(f"🗑️ <b>FILTER REMOVED</b>\n\n<code>{esc(word)}</code>", parse_mode="HTML")
        return

    # Only the MissRose-style saved-message flow is supported here.
    trigger = " ".join(args).strip().strip('"').lower()
    if not trigger:
        await m.reply_text("Use: <code>/filter price</code> while replying to the file/message.", parse_mode="HTML")
        return

    reply_source = m.reply_to_message
    if not reply_source:
        await m.reply_text(
            "Reply to the file/message you want ZEUS to resend, then send:\n"
            "<code>/filter price</code>",
            parse_mode="HTML",
        )
        return

    reply_text, source_chat_id, source_message_id, media_type, file_id, caption = _filter_reply_payload(reply_source)
    # Filter resend is intentionally file/message based. Require a Telegram message
    # that has durable content we can reproduce later.
    if not any((file_id, source_message_id, reply_text)):
        await m.reply_text("That message type cannot be saved for a filter resend.", parse_mode="HTML")
        return

    await add_filter(
        m.chat_id,
        trigger,
        "reply",
        reply_text,
        source_chat_id,
        source_message_id,
        media_type,
        file_id,
        caption,
    )
    await add_log(m.chat_id, update.effective_user.id, "FILTER_ADD", None, f"{trigger} -> reply")
    await m.reply_text(
        "✅ <b>FILTER SAVED</b>\n\n"
        f"Trigger: <code>{esc(trigger)}</code>\n"
        f"Response: <b>{esc(media_type or 'message')}</b>\n\n"
        "Now send the trigger in the group and ZEUS will resend the saved content.",
        parse_mode="HTML",
    )


async def files_cmd(update, context):
    if update.effective_chat.type == ChatType.PRIVATE:
        if not await is_owner(update): return
        if not context.args or not context.args[0].lstrip("-").isdigit():
            await update.effective_message.reply_text("Use /files CHAT_ID")
            return
        chat_id = int(context.args[0])
        if not await can_manage_group(update, chat_id):
            await update.effective_message.reply_text("⛔ You cannot manage that group.")
            return
        from services.ui import files_panel
        from database.db import count_files
        total = await count_files(chat_id)
        rows = await list_files(chat_id, limit=FILE_LIST_PAGE_SIZE, offset=0)
        if not rows:
            await update.effective_message.reply_text("📁 No tracked files for this group.")
            return
        text = "📁 <b>GET FILES</b>\n\n" + "\n".join(
            f"#{r['id']} • {esc(r['file_name'] or r['file_type'])} • {r['file_type']}"
            for r in rows
        )
        await update.effective_message.reply_text(
            text + f"\n\nTotal tracked: <code>{total}</code>",
            parse_mode="HTML", reply_markup=files_panel(chat_id, 0)
        )
        return
    if not await require_group_admin(update, context): return
    rows = await list_files(update.effective_chat.id, limit=FILE_LIST_PAGE_SIZE, offset=0)
    if not rows:
        await update.effective_message.reply_text("📁 No files tracked yet.")
        return
    await update.effective_message.reply_text(
        "📁 <b>RECENT FILES</b>\n\n" + "\n".join(
            f"• {esc(r['file_name'] or r['file_type'])}" for r in rows
        ),
        parse_mode="HTML"
    )

async def _broadcast_copy(bot, destination_chat_id, source_message):
    """Copy the original Telegram message, preserving media, caption and entities."""
    await bot.copy_message(
        chat_id=destination_chat_id,
        from_chat_id=source_message.chat_id,
        message_id=source_message.message_id,
    )


async def broadcast(update, context):
    """Broadcast an original message to users who have started the bot privately."""
    await ensure(update)
    if not await require_owner_private(update, context):
        return

    source = update.effective_message.reply_to_message
    if source is None:
        await update.effective_message.reply_text(
            "📢 <b>BROADCAST</b>\n\n"
            "Reply to the message you want to copy and send <code>/broadcast</code>.\n"
            "For text-only broadcast you may also use <code>/broadcast Your message</code>.\n\n"
            "Use /cancel to stop.",
            parse_mode="HTML",
        )
        return

    users = await private_users()
    sent = failed = 0
    for uid in users:
        try:
            await _broadcast_copy(context.bot, uid, source)
            sent += 1
        except Exception as exc:
            logging.getLogger("ZEUS").warning("Broadcast copy to %s failed: %s", uid, exc)
            failed += 1
        if BROADCAST_DELAY_SECONDS:
            await asyncio.sleep(BROADCAST_DELAY_SECONDS)
    await update.effective_message.reply_text(
        f"📢 <b>BROADCAST COMPLETE</b>\n\n✅ Sent: {sent}\n❌ Failed: {failed}",
        parse_mode="HTML",
    )


async def gbroadcast(update, context):
    """Start the guided group broadcast flow: command -> group button -> original message."""
    await ensure(update)
    if not await require_owner_private(update, context):
        return
    if not BROADCAST_TO_GROUPS_ENABLED:
        await update.effective_message.reply_text("Group broadcasting is currently disabled.")
        return

    # Explicit target syntax is still supported for backward compatibility.
    if context.args:
        raw = context.args[0]
        if raw.lstrip("-").isdigit():
            target = int(raw)
            if not await can_manage_group(update, target):
                await update.effective_message.reply_text("You cannot manage that group.")
                return
            await set_pending(update.effective_user.id, "gbroadcast_message", target)
            chat = await context.bot.get_chat(target)
            await update.effective_message.reply_text(
                f"📢 <b>GROUP BROADCAST</b>\n\nTarget: <b>{esc(chat.title or target)}</b>\n\n"
                "Send the message now. Text, photo, video, GIF, sticker, document, audio, voice, etc. are supported.\n\n"
                "Use /cancel to stop.",
                parse_mode="HTML",
            )
            return

    groups = [g for g in await list_groups() if await can_manage_group(update, int(g["chat_id"]))]
    if not groups:
        await update.effective_message.reply_text(
            "📢 <b>GROUP BROADCAST</b>\n\nNo managed groups are available.", parse_mode="HTML"
        )
        return
    from services.ui import gbroadcast_group_selector
    await update.effective_message.reply_text(
        "📢 <b>SELECT GROUP</b>\n\nChoose the group that should receive your message:",
        parse_mode="HTML",
        reply_markup=gbroadcast_group_selector(groups),
    )


async def cancel_cmd(update, context):
    await ensure(update)
    if update.effective_chat.type != ChatType.PRIVATE or not await is_owner(update):
        return
    await clear_pending(update.effective_user.id)
    for key in ("broadcast_step", "broadcast_message"):
        context.user_data.pop(key, None)
    await update.effective_message.reply_text("✅ Current operation cancelled.")


async def pending_text(update, context):
    if not update.effective_message:
        return False
    pending = await get_pending(update.effective_user.id)
    if not pending:
        return False
    created = pending.get("created_at")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(created)).total_seconds()
        if age > PENDING_ACTION_TTL_SECONDS:
            await clear_pending(update.effective_user.id)
            await update.effective_message.reply_text("This control request expired. Please start it again.")
            return True
    except Exception:
        await clear_pending(update.effective_user.id)
        return False

    is_private_owner = update.effective_chat.type == ChatType.PRIVATE and await is_owner(update)
    pending_chat_id = pending.get("chat_id")
    pending_origin = pending.get("payload") or ""
    # Guided filter setup is completed in the same group by the admin who started it.
    if pending["action"] == "filter_reply":
        if pending_chat_id is None or update.effective_chat.id != int(pending_chat_id):
            return False
        if not await is_group_admin(update.effective_chat, update.effective_user.id) and not await is_owner(update):
            return False
        trigger = (pending.get("payload") or "").strip().lower()
        if not trigger:
            await clear_pending(update.effective_user.id)
            return True
        reply_text, source_chat_id, source_message_id, media_type, file_id, caption = _filter_reply_payload(update.effective_message)
        if not any((reply_text, source_message_id, file_id)):
            await update.effective_message.reply_text("Send a text or a supported media message as the filter response.")
            return True
        await add_filter(update.effective_chat.id, trigger, "reply", reply_text, source_chat_id, source_message_id, media_type, file_id, caption)
        await add_log(update.effective_chat.id, update.effective_user.id, "FILTER_ADD", None, f"{trigger} -> reply")
        await clear_pending(update.effective_user.id)
        await update.effective_message.reply_text(
            "⚡ <b>FILTER ADDED</b>\n━━━━━━━━━━━━━━━━\n"
            f"🧹 Trigger: <code>{esc(trigger)}</code>\n"
            "📎 Reply: saved message/media\n"
            "🟢 Status: Active",
            parse_mode="HTML"
        )
        return True

    # Guided group broadcast is always completed by the owner in private chat.
    if pending["action"] == "gbroadcast_message":
        if not is_private_owner:
            return False
    # Private control-panel text entry must be accepted in private chat, even though
    # the target group id is stored in the pending record.
    elif pending_origin == "private":
        if not is_private_owner:
            return False
    elif pending_chat_id is not None:
        if update.effective_chat.id != int(pending_chat_id):
            return False
        if not await is_group_admin(update.effective_chat, update.effective_user.id) and not await is_owner(update):
            return False
    elif not is_private_owner:
        return False

    action = pending["action"]
    chat_id = pending_chat_id
    text = (update.effective_message.text or "").strip()

    if action == "gbroadcast_message":
        if not is_private_owner or not update.effective_message:
            return False
        try:
            if not chat_id or not await can_manage_group(update, int(chat_id)):
                await clear_pending(update.effective_user.id)
                await update.effective_message.reply_text("The selected group is no longer available for broadcasting.")
                return True
            await _broadcast_copy(context.bot, int(chat_id), update.effective_message)
            await add_log(int(chat_id), update.effective_user.id, "GROUP_BROADCAST", None, f"source_message={update.effective_message.message_id}")
            await clear_pending(update.effective_user.id)
            group = await context.bot.get_chat(int(chat_id))
            await update.effective_message.reply_text(
                f"✅ <b>GROUP BROADCAST SENT</b>\n\n👥 {esc(group.title or chat_id)}",
                parse_mode="HTML"
            )
        except Exception as exc:
            logging.getLogger("ZEUS").warning("Guided group broadcast failed chat=%s: %s", chat_id, exc)
            await update.effective_message.reply_text(
                f"Unable to send the group broadcast.\n\n<code>{esc(exc)}</code>", parse_mode="HTML"
            )
            return True
        return True

    if action == "local_add_timing":
        try:
            windows = parse_multiple_time_windows(text)
        except Exception:
            await update.effective_message.reply_text(
                "❌ Invalid format.\n\n"
                "Use:\n"
                "<code>08:00 AM - 11:00 AM</code>\n\n"
                "Or multiple:\n"
                "<code>08:00 AM - 11:00 AM 02:00 PM - 05:00 PM 09:00 PM - 01:00 AM</code>",
                parse_mode="HTML"
            )
            return True

        from database.db import add_schedule
        added = []
        for a, b in windows:
            sid = await add_schedule(update.effective_chat.id, a, b)
            added.append((sid, a, b))
        await set_group_value(update.effective_chat.id, "manual_override", 0)

        await clear_pending(update.effective_user.id)
        try:
            from services.scheduler import apply_scheduler
            await apply_scheduler(context.application)
        except Exception as exc:
            logging.getLogger("ZEUS").warning("Immediate local timing sync failed: %s", exc)

        try:
            lines = "\n".join(
                f"🟢 <code>{a}</code> → 🔴 <code>{b}</code>  (#{idx})"
                for idx, (_, a, b) in enumerate(added, 1)
            )
            await context.bot.send_message(
                update.effective_chat.id,
                "⚡ <b>ZEUS • SCHEDULER UPDATED</b>\n\n"
                f"{lines}\n\n"
                "📅 EVERY DAY\n"
                "👤 Changed by an authorized ZEUS admin.",
                parse_mode="HTML"
            )
        except Exception as exc:
            print(f"⚠️ WARNING | Scheduler group notification failed: {exc}")

        from services.ui import group_local_panel
        await update.effective_message.reply_text(
            f"✅ <b>{len(added)} daily window(s) added.</b>",
            parse_mode="HTML",
            reply_markup=group_local_panel(update.effective_chat.id)
        )
        return True

    if action == "add_timing":
        try:
            windows = parse_multiple_time_windows(text)
        except Exception:
            await update.effective_message.reply_text(
                "❌ Invalid format.\n\n"
                "Example:\n"
                "<code>08:00 AM - 11:00 AM 02:00 PM - 05:00 PM 09:00 PM - 01:00 AM</code>",
                parse_mode="HTML"
            )
            return True

        from database.db import add_schedule
        added = []
        for a, b in windows:
            sid = await add_schedule(chat_id, a, b)
            added.append((sid, a, b))
        await set_group_value(chat_id, "manual_override", 0)

        await clear_pending(update.effective_user.id)

        try:
            lines = "\n".join(
                f"🟢 <code>{a}</code> → 🔴 <code>{b}</code>  (#{idx})"
                for idx, (_, a, b) in enumerate(added, 1)
            )
            await context.bot.send_message(
                chat_id,
                "⚡ <b>ZEUS • SCHEDULER UPDATED</b>\n\n"
                f"{lines}\n\n"
                "📅 EVERY DAY\n"
                "👑 Changed from ZEUS Control Center",
                parse_mode="HTML"
            )
        except Exception as exc:
            print(f"⚠️ WARNING | Group notification failed for {chat_id}: {exc}")

        from services.ui import timing_panel
        await update.effective_message.reply_text(
            f"✅ <b>{len(added)} daily window(s) added.</b>",
            parse_mode="HTML",
            reply_markup=timing_panel(chat_id)
        )
        return True

    if action == "set_timezone":
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(text)
        except Exception:
            await update.effective_message.reply_text("Invalid timezone. Example: Asia/Kolkata")
            return True
        await set_group_value(chat_id, "timezone", text)
        await set_group_value(chat_id, "manual_override", 0)
        await clear_pending(update.effective_user.id)
        try:
            await context.bot.send_message(chat_id, f"⚡ <b>ZEUS SETTINGS UPDATED</b>\n\n🌐 Timezone changed to <code>{esc(text)}</code>.", parse_mode="HTML")
        except Exception:
            pass
        from services.ui import group_panel
        await update.effective_message.reply_text(
            f"✅ <b>TIMEZONE UPDATED</b>\n\n<code>{esc(text)}</code>",
            parse_mode="HTML", reply_markup=group_panel(chat_id)
        )
        return True

    if action.startswith("set_message:"):
        field = action.split(":", 1)[1]
        await set_group_value(chat_id, field, text)
        await clear_pending(update.effective_user.id)
        try:
            label = {"welcome_text":"Welcome", "goodbye_text":"Goodbye", "rules_text":"Rules"}.get(field, field)
            await context.bot.send_message(chat_id, f"⚡ <b>ZEUS SETTINGS UPDATED</b>\n\n💬 {esc(label)} message updated.", parse_mode="HTML")
        except Exception:
            pass
        from services.ui import messages_panel
        await update.effective_message.reply_text("✅ Message updated.", reply_markup=messages_panel(chat_id))
        return True

    if action == "broadcast":
        await clear_pending(update.effective_user.id)
        return False

    return False
