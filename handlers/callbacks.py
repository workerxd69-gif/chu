import html
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatType
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from config import OWNER_ID, FILE_LIST_PAGE_SIZE, FILE_MAX_RETRIEVAL_SIZE_MB
from database.db import (
    list_groups, get_group, list_schedules, clear_schedules, delete_schedule,
    set_group_value, get_filters, list_files, count_files, get_file,
    recent_logs, set_pending
)
from handlers.common import is_owner, can_manage_group
from utils import OPEN_PERMS
from services.ui import (
    main_panel, group_selector, group_panel, timing_panel, files_panel,
    file_retrieve_button, security_panel, locks_panel, messages_panel, back_group,
    group_local_panel, gbroadcast_group_selector
)

def esc(x):
    return html.escape(str(x or ""))


async def _safe_edit(q, text, **kwargs):
    """Edit an inline-panel message without spamming logs on idempotent clicks.

    Telegram returns BadRequest("Message is not modified") when a user taps a
    button that would leave the panel exactly unchanged. That is not a real
    failure, so treat it as a no-op while surfacing other Telegram errors.
    """
    try:
        return await q.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return None
        raise

async def notify_group_setting(context, chat_id, title, body):
    """Send a private-panel configuration change notification into the managed group."""
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "⚡ <b>ZEUS SETTINGS UPDATED</b>\n"
                "━━━━━━━━━━━━━━━━\n"
                f"🔧 <b>{esc(title)}</b>\n\n"
                f"{body}\n\n"
                "👑 Changed from ZEUS Control Center"
            ),
            parse_mode="HTML",
        )
    except Exception as exc:
        # Keep the private control panel usable; surface only the actual failure.
        print(f"⚠️ WARNING | Group notification failed for {chat_id}: {exc}")


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    # Join verification must be available to the joining member even though the
    # rest of group controls are admin-only. The callback is bound to that exact user/chat.
    if data.startswith("verify_join:"):
        try:
            _, raw_chat, raw_user = data.split(":", 2)
            chat_id, user_id = int(raw_chat), int(raw_user)
        except (ValueError, TypeError):
            return await q.answer("Invalid verification request.", show_alert=True)
        if update.effective_user.id != user_id or not q.message or q.message.chat.id != chat_id:
            return await q.answer("This verification button is not for you.", show_alert=True)
        try:
            await context.bot.restrict_chat_member(
                chat_id, user_id, permissions=OPEN_PERMS,
                use_independent_chat_permissions=True,
            )
            await q.answer("Verified.")
            await q.edit_message_text("✅ <b>Verification complete.</b> You can chat now.", parse_mode="HTML")
            return
        except Exception as exc:
            return await q.answer(f"Verification failed: {exc}", show_alert=True)

    # Group-local Control Center: group admins can use these buttons.
    if data.startswith("local_"):
        if not q.message or q.message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            return await _safe_edit(q, "⛔ Group control only.")
        if not (await can_manage_group(update, q.message.chat.id)):
            return await q.answer("Admin access required.", show_alert=True)

        action = data.split(":", 1)[0]
        cid = q.message.chat.id

        if action == "local_status":
            g = await get_group(cid)
            slots = await list_schedules(cid)
            return await _safe_edit(q, 
                f"⚡ <b>ZEUS GROUP CONTROL</b>\n\n"
                f"👥 <b>{esc(g['title'])}</b>\n"
                f"🆔 <code>{cid}</code>\n"
                f"🌐 <code>{esc(g['timezone'])}</code>\n"
                f"⏰ Windows: <code>{len(slots)}</code>\n"
                f"🔒 {'LOCKED' if g['locked'] else 'OPEN'}\n"
                f"🛡 Anti-link: {'ON' if g['anti_link'] else 'OFF'}",
                parse_mode="HTML",
                reply_markup=group_local_panel(cid),
            )

        if action == "local_timing":
            slots = await list_schedules(cid)
            body = "⏰ <b>DAILY SCHEDULER</b>\n\n" + (
                "\n".join(
                    f"#{idx} • 🟢 {s['unlock_time']} → 🔴 {s['lock_time']}" for idx, s in enumerate(slots, 1)
                ) or "No windows configured."
            )
            return await _safe_edit(q, 
                body, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Add Window", callback_data=f"local_timing_add:{cid}")],
                    [InlineKeyboardButton("🗑 Clear All", callback_data=f"local_timing_clear:{cid}")],
                    [InlineKeyboardButton("⬅️ Back", callback_data=f"local_status:{cid}")],
                ])
            )

        if action == "local_timing_add":
            await set_pending(update.effective_user.id, "local_add_timing", cid)
            return await _safe_edit(q, 
                "➕ <b>ADD DAILY WINDOW</b>\n\n"
                "Ab isi group me ek message bhejo:\n"
                "<code>08:00 AM - 11:00 AM</code>\n\n"
                "Unlimited windows • EVERY DAY only",
                parse_mode="HTML",
                reply_markup=group_local_panel(cid),
            )

        if action == "local_timing_clear":
            await clear_schedules(cid)
            permission_error = None
            try:
                from services.scheduler import OPEN_PERMS
                await context.bot.set_chat_permissions(cid, OPEN_PERMS)
                await set_group_value(cid, "locked", 0)
            except Exception as exc:
                permission_error = exc
            try:
                await context.bot.send_message(
                    cid,
                    "⚡ <b>ZEUS • SCHEDULER UPDATED</b>\n\n"
                    "🗑 All daily time windows cleared.\n"
                    "👤 Changed by an authorized ZEUS admin.",
                    parse_mode="HTML",
                )
            except Exception as exc:
                print(f"⚠️ WARNING | Group notification failed for {cid}: {exc}")
            body = "✅ <b>All daily windows cleared.</b>"
            if permission_error:
                body += f"\n\n⚠️ Permissions could not be reset: <code>{esc(permission_error)}</code>"
            return await _safe_edit(q, body, parse_mode="HTML", reply_markup=group_local_panel(cid))

        if action == "local_security":
            g = await get_group(cid)
            return await _safe_edit(q, 
                "🛡 <b>SECURITY</b>",
                parse_mode="HTML",
                reply_markup=security_panel(cid, g),
            )

        if action == "local_locks":
            g = await get_group(cid)
            return await _safe_edit(q, 
                "🔒 <b>LOCK SYSTEM</b>",
                parse_mode="HTML",
                reply_markup=locks_panel(cid, g),
            )

        if action == "local_messages":
            return await _safe_edit(q, 
                "💬 <b>MESSAGES</b>",
                parse_mode="HTML",
                reply_markup=messages_panel(cid),
            )

        if action == "local_filters":
            fs = await get_filters(cid)
            body = "🧹 <b>FILTERS</b>\n\n" + (
                "\n".join(f"• <code>{esc(row[0])}</code> → {esc(row[2] or '📎 Media / message reply')[:80]}" for row in fs)
                or "No filters configured."
            )
            return await _safe_edit(q, 
                body + "\n\nUse /filter add word [delete|warn|mute]",
                parse_mode="HTML",
                reply_markup=group_local_panel(cid),
            )

        if action == "local_files":
            rows = await list_files(cid, limit=FILE_LIST_PAGE_SIZE, offset=0)
            total = await count_files(cid)
            body = "📁 <b>GET FILES</b>\n\n"
            body += "\n".join(
                f"#{r['id']} • {esc(r['file_name'] or r['file_type'])}" for r in rows
            ) or "No tracked files."
            return await _safe_edit(q, 
                body + f"\n\nTotal: <code>{total}</code>",
                parse_mode="HTML",
                reply_markup=group_local_panel(cid),
            )

        if action == "local_logs":
            logs = await recent_logs(cid, 12)
            body = "📜 <b>AUDIT LOG</b>\n\n" + (
                "\n".join(
                    f"• {a} | actor={actor} | target={t or '-'} | {esc(d or '')}"
                    for actor, a, t, d, _ in logs
                ) or "No logs yet."
            )
            return await _safe_edit(q, 
                body, parse_mode="HTML",
                reply_markup=group_local_panel(cid),
            )

        return

    # Remaining callbacks are allowed in the right context:
    # - Private chat: owner only
    # - Group/supergroup: group admins only
    effective_chat = update.effective_chat
    if effective_chat and effective_chat.type == ChatType.PRIVATE:
        if update.effective_user.id != OWNER_ID:
            return await _safe_edit(q, "⛔ Private owner control only.")
    elif effective_chat and effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        if not await can_manage_group(update, effective_chat.id):
            return await q.answer("Admin access required.", show_alert=True)
    else:
        return await q.answer("This control is available only in a private chat or group.", show_alert=True)

    if data == "panel":
        return await _safe_edit(q, "⚡ <b>ZEUS CONTROL CENTER</b>\n\nChoose a section.", parse_mode="HTML", reply_markup=main_panel())

    if data == "groups":
        groups = [g for g in await list_groups() if await can_manage_group(update, int(g["chat_id"]))]
        if not groups:
            return await _safe_edit(q, 
                "👥 No managed groups yet.\n\nAdd ZEUS as admin to a group and send a message there.",
                reply_markup=main_panel()
            )
        return await _safe_edit(q, "👥 <b>SELECT GROUP</b>", parse_mode="HTML", reply_markup=group_selector(groups))

    if data == "gbroadcast_cancel":
        from database.db import clear_pending
        await clear_pending(update.effective_user.id)
        return await _safe_edit(q, "📢 <b>Group broadcast cancelled.</b>", parse_mode="HTML", reply_markup=main_panel())

    if data.startswith("gbroadcast_group:"):
        if effective_chat.type != ChatType.PRIVATE or update.effective_user.id != OWNER_ID:
            return await _safe_edit(q, "⛔ Private owner control only.")
        try:
            cid = int(data.split(":", 1)[1])
        except (TypeError, ValueError):
            return await _safe_edit(q, "❌ Invalid group selection.", reply_markup=main_panel())
        groups = await list_groups()
        group = next((g for g in groups if int(g["chat_id"]) == cid), None)
        if not group or not await can_manage_group(update, cid):
            return await _safe_edit(q, "❌ That group is not available for broadcasting.", reply_markup=main_panel())
        await set_pending(update.effective_user.id, "gbroadcast_message", cid)
        return await _safe_edit(
            q,
            f"📢 <b>GROUP BROADCAST</b>\n\nTarget: <b>{esc(group.get('title') or cid)}</b>\n\nSend the message now.\nYou can send text, photo, video, GIF, sticker, document, audio, voice, etc.\n\nUse /cancel to stop.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="gbroadcast_cancel")]])
        )

    if data == "broadcast":
        return await _safe_edit(q,
            "📢 <b>BROADCAST</b>\n\n"
            "Private broadcast: reply to the message you want to send and use <code>/broadcast</code>.\n\n"
            "Group broadcast: use <code>/gbroadcast</code>, select the group, then send the message.",
            parse_mode="HTML", reply_markup=main_panel()
        )

    if data == "global_status":
        groups = await list_groups()
        return await _safe_edit(q, 
            f"📊 <b>GLOBAL STATUS</b>\n\n"
            f"👥 Managed groups: <code>{len(groups)}</code>\n"
            f"🤖 Bot status: 🟢 ONLINE",
            parse_mode="HTML", reply_markup=main_panel()
        )

    if data == "help":
        return await _safe_edit(q, 
            "📖 <b>ZEUS HELP</b>\n\n"
            "Select a group to access the complete control center.\n"
            "Timing is EVERY DAY only and supports unlimited windows.",
            parse_mode="HTML", reply_markup=main_panel()
        )

    if data.startswith("group:"):
        try:
            cid = int(data.split(":", 1)[1])
        except (ValueError, TypeError):
            return await _safe_edit(q, "❌ Invalid group selection.", reply_markup=main_panel())
        if not await can_manage_group(update, cid):
            return await _safe_edit(q, "⛔ You cannot manage this group.", reply_markup=main_panel())
        g = await get_group(cid)
        if not g:
            return await _safe_edit(q, "❌ Group not found.", reply_markup=main_panel())
        slots = await list_schedules(cid)
        text = (
            f"👥 <b>{esc(g['title'])}</b>\n\n"
            f"🆔 <code>{cid}</code>\n"
            f"🌐 {esc(g['timezone'])}\n"
            f"⏰ Daily windows: <code>{len(slots)}</code>\n"
            f"🔒 {'LOCKED' if g['locked'] else 'OPEN'}\n"
            f"🛡 Anti-link: {'ON' if g['anti_link'] else 'OFF'}"
        )
        return await _safe_edit(q, text, parse_mode="HTML", reply_markup=group_panel(cid))

    if ":" in data:
        key, raw = data.split(":", 1)
        if key == "timing":
            try: cid = int(raw)
            except (ValueError, TypeError): return await _safe_edit(q, "❌ Invalid group selection.")
            g = await get_group(cid)
            slots = await list_schedules(cid)
            body = f"⏰ <b>DAILY SCHEDULER</b>\n\n👥 {esc(g['title'])}\n🌐 <code>{esc(g['timezone'])}</code>\n\n"
            body += "\n".join(
                f"#{idx} • 🟢 {s['unlock_time']} → 🔴 {s['lock_time']}" for idx, s in enumerate(slots, 1)
            ) or "No windows configured."
            return await _safe_edit(q, body, parse_mode="HTML", reply_markup=timing_panel(cid))

        if key == "timing_add":
            cid = int(raw)
            await set_pending(update.effective_user.id, "add_timing", cid, "private")
            return await _safe_edit(q, 
                "➕ <b>ADD DAILY WINDOW</b>\n\n"
                "Ab private chat me time window bhejo:\n"
                "<code>08:00 AM - 11:00 AM</code>\n\n"
                "Unlimited windows allowed. EVERY DAY only.",
                parse_mode="HTML", reply_markup=timing_panel(cid)
            )

        if key == "timing_clear":
            cid = int(raw)
            await clear_schedules(cid)
            permission_error = None
            try:
                from services.scheduler import OPEN_PERMS
                await context.bot.set_chat_permissions(cid, OPEN_PERMS)
                await set_group_value(cid, "locked", 0)
            except Exception as exc:
                permission_error = exc
            await notify_group_setting(
                context, cid, "Daily Scheduler",
                "🗑️ All daily time windows were cleared."
            )
            body = "🗑️ <b>ALL WINDOWS CLEARED</b>"
            if permission_error:
                body += f"\n\n⚠️ Permissions could not be reset: <code>{esc(permission_error)}</code>"
            return await _safe_edit(q, body, parse_mode="HTML", reply_markup=timing_panel(cid))

        if key == "timezone":
            cid = int(raw)
            g = await get_group(cid)
            await set_pending(update.effective_user.id, "set_timezone", cid, "private")
            return await _safe_edit(q, 
                f"🌐 <b>TIMEZONE</b>\n\nCurrent: <code>{esc(g['timezone'])}</code>\n\nSend an IANA timezone, e.g. <code>Asia/Kolkata</code>.",
                parse_mode="HTML", reply_markup=back_group(cid)
            )

        if key == "security":
            cid = int(raw); g = await get_group(cid)
            return await _safe_edit(q, "🛡 <b>SECURITY</b>", parse_mode="HTML", reply_markup=security_panel(cid, g))

        if key == "locks":
            cid = int(raw); g = await get_group(cid)
            return await _safe_edit(q, "🔒 <b>LOCK SYSTEM</b>", parse_mode="HTML", reply_markup=locks_panel(cid, g))

        if key == "messages":
            cid = int(raw)
            return await _safe_edit(q, "💬 <b>MESSAGES</b>\n\nChoose a message to edit.", parse_mode="HTML", reply_markup=messages_panel(cid))

        if key == "filters":
            cid = int(raw); fs = await get_filters(cid)
            return await _safe_edit(q, 
                "🧹 <b>FILTERS</b>\n\n" + ("\n".join(f"• <code>{esc(row[0])}</code> → {esc(row[2] or '📎 Media / message reply')[:80]}" for row in fs) or "No filters configured.") +
                "\n\nUse /filter apk reply — or reply to a message/media with /filter apk.\n"
                "Actions: /filter add apk reply|delete|warn|mute",
                parse_mode="HTML", reply_markup=back_group(cid)
            )

        if key == "files":
            parts = raw.split(":")
            cid = int(parts[0]); page = int(parts[1]) if len(parts) > 1 else 0
            rows = await list_files(cid, limit=FILE_LIST_PAGE_SIZE, offset=max(page,0)*FILE_LIST_PAGE_SIZE)
            total = await count_files(cid)
            body = "📁 <b>GET FILES</b>\n\n"
            if not rows:
                body += "No tracked files on this page."
            else:
                body += "\n".join(
                    f"#{r['id']} • {esc(r['file_name'] or r['file_type'])} • {r['file_type']}"
                    for r in rows
                )
            body += f"\n\nTotal tracked: <code>{total}</code>"
            return await _safe_edit(q, body, parse_mode="HTML", reply_markup=files_panel(cid, page, rows))

        if key == "file_get":
            db_id = int(raw)
            row = await get_file(db_id)
            if not row:
                return await _safe_edit(q, "❌ File record no longer exists.", reply_markup=main_panel())
            if not await can_manage_group(update, row["chat_id"]):
                return await _safe_edit(q, "⛔ You cannot access this group file.")
            context.chat_data["file_get_id"] = db_id
            max_bytes = int(FILE_MAX_RETRIEVAL_SIZE_MB * 1024 * 1024)
            if row.get("file_size") and int(row["file_size"]) > max_bytes:
                return await _safe_edit(
                    q,
                    f"📁 This file is larger than the configured {FILE_MAX_RETRIEVAL_SIZE_MB} MB retrieval limit.",
                    reply_markup=files_panel(row["chat_id"], 0),
                )
            try:
                if row["file_type"] == "document":
                    await context.bot.send_document(update.effective_chat.id, row["file_id"], caption=f"📁 {row['file_name'] or 'File'}")
                elif row["file_type"] == "photo":
                    await context.bot.send_photo(update.effective_chat.id, row["file_id"], caption=f"🖼 {row['file_name'] or 'Photo'}")
                elif row["file_type"] == "video":
                    await context.bot.send_video(update.effective_chat.id, row["file_id"], caption=f"🎬 {row['file_name'] or 'Video'}")
                elif row["file_type"] == "audio":
                    await context.bot.send_audio(update.effective_chat.id, row["file_id"], caption=f"🎵 {row['file_name'] or 'Audio'}")
                elif row["file_type"] == "voice":
                    await context.bot.send_voice(update.effective_chat.id, row["file_id"])
                elif row["file_type"] == "animation":
                    await context.bot.send_animation(update.effective_chat.id, row["file_id"])
                else:
                    await context.bot.send_message(update.effective_chat.id, f"📁 File ID: <code>{esc(row['file_id'])}</code>", parse_mode="HTML")
                return
            except Exception as exc:
                return await _safe_edit(q, f"❌ Could not retrieve file: {esc(exc)}", reply_markup=main_panel())

        if key == "toggle":
            p = raw.split(":")
            cid, field = int(p[0]), p[1]
            g = await get_group(cid)
            if field not in g or field in ("chat_id", "title", "chat_type", "updated_at"):
                return
            new_val = 0 if g[field] else 1
            await set_group_value(cid, field, new_val)
            g = await get_group(cid)
            if field.startswith("lock_"):
                label = field.replace("lock_", "").replace("_", " ").title()
                await notify_group_setting(
                    context, cid, "Lock Settings",
                    f"{'🟢 Enabled' if new_val else '🔴 Disabled'}: <b>{esc(label)}</b>"
                )
                return await _safe_edit(q, "🔒 <b>LOCK SETTINGS</b>", parse_mode="HTML", reply_markup=locks_panel(cid, g))
            label = field.replace("_", " ").title()
            await notify_group_setting(
                context, cid, "Security Settings",
                f"{'🟢 Enabled' if new_val else '🔴 Disabled'}: <b>{esc(label)}</b>"
            )
            return await _safe_edit(q, "🛡 <b>SECURITY</b>", parse_mode="HTML", reply_markup=security_panel(cid, g))

        if key in ("manual_lock", "manual_unlock"):
            cid = int(raw)
            try:
                from services.scheduler import LOCK_PERMS, OPEN_PERMS
                perms = LOCK_PERMS if key == "manual_lock" else OPEN_PERMS
                await context.bot.set_chat_permissions(cid, perms)
                locked_now = 1 if key == "manual_lock" else 0
                await set_group_value(cid, "locked", locked_now)
                await set_group_value(cid, "manual_override", 1)
                await notify_group_setting(
                    context, cid, "Group Lock",
                    "🔒 Group locked by ZEUS Control Center." if locked_now else "🔓 Group unlocked by ZEUS Control Center."
                )
                return await _safe_edit(q, 
                    "🔒 <b>GROUP LOCKED</b>" if key == "manual_lock" else "🔓 <b>GROUP UNLOCKED</b>",
                    parse_mode="HTML", reply_markup=locks_panel(cid, await get_group(cid))
                )
            except Exception as exc:
                return await _safe_edit(q, f"❌ Permission change failed: {esc(exc)}", reply_markup=locks_panel(cid, await get_group(cid)))

        if key.startswith("msg_"):
            cid = int(raw)
            field = {"msg_welcome":"welcome_text","msg_goodbye":"goodbye_text","msg_rules":"rules_text"}[key]
            g = await get_group(cid)
            origin = "group" if q.message and q.message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) else "private"
            await set_pending(update.effective_user.id, f"set_message:{field}", cid, origin)
            current = esc(g[field])
            label = {"welcome_text":"Welcome","goodbye_text":"Goodbye","rules_text":"Rules"}[field]
            destination = "this group" if origin == "group" else "private chat"
            return await _safe_edit(q, 
                f"✏️ <b>EDIT {label.upper()}</b>\n\nCurrent:\n{current or '(not set)'}\n\nSend the new text in {destination}.",
                parse_mode="HTML", reply_markup=messages_panel(cid)
            )

        if key == "logs":
            cid = int(raw); logs = await recent_logs(cid, 12)
            body = "📜 <b>AUDIT LOG</b>\n\n"
            body += "\n".join(
                f"• {a} | actor={actor} | target={t or '-'} | {esc(d or '')}" for actor,a,t,d,_ in logs
            ) or "No logs yet."
            return await _safe_edit(q, body, parse_mode="HTML", reply_markup=back_group(cid))

        if key == "status":
            cid = int(raw); g = await get_group(cid); slots = await list_schedules(cid)
            return await _safe_edit(q, 
                f"📊 <b>GROUP STATUS</b>\n\n"
                f"🏷 {esc(g['title'])}\n🆔 <code>{cid}</code>\n"
                f"🌐 <code>{esc(g['timezone'])}</code>\n"
                f"⏰ Windows: <code>{len(slots)}</code>\n"
                f"🔒 {'LOCKED' if g['locked'] else 'OPEN'}\n"
                f"🛡 Anti-link: {'ON' if g['anti_link'] else 'OFF'}\n"
                f"🧹 Filters: {len(await get_filters(cid))}",
                parse_mode="HTML", reply_markup=back_group(cid)
            )
