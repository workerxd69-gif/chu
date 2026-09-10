from datetime import datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo

from telegram import ChatPermissions
from telegram.constants import ChatType

from database.db import list_groups, list_schedules, set_group_value
from config import DEFAULT_TIMEZONE, SCHEDULER_REMINDER_MINUTES

logger = logging.getLogger("ZEUS")

OPEN_PERMS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
)

LOCK_PERMS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)

# Reminder de-duplication and last scheduled state. The first scheduler pass after
# restart reconciles Telegram but deliberately does not announce a fake transition.
_sent_reminders = set()
_last_applied_states = {}


def inside_window(now_time, start_time, end_time):
    if start_time == end_time:
        return False
    if start_time < end_time:
        return start_time <= now_time < end_time
    return now_time >= start_time or now_time < end_time


def _window_datetimes(local_now, start_text, end_text):
    start_t = datetime.strptime(start_text.strip(), "%I:%M %p").time()
    end_t = datetime.strptime(end_text.strip(), "%I:%M %p").time()
    start_dt = datetime.combine(local_now.date(), start_t, tzinfo=local_now.tzinfo)
    end_dt = datetime.combine(local_now.date(), end_t, tzinfo=local_now.tzinfo)
    if end_t < start_t:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def _next_window(local_now, slots):
    candidates = []
    for slot in slots:
        try:
            start_dt, end_dt = _window_datetimes(local_now, slot["unlock_time"], slot["lock_time"])
        except (TypeError, ValueError):
            continue
        if start_dt <= local_now:
            start_dt += timedelta(days=1)
            end_dt += timedelta(days=1)
        candidates.append((start_dt, end_dt, slot))
    return min(candidates, key=lambda item: item[0]) if candidates else None


def _prune_reminders(now):
    cutoff = now - timedelta(days=7)
    for key in list(_sent_reminders):
        try:
            stamp = datetime.fromisoformat(key[1])
        except Exception:
            _sent_reminders.discard(key)
            continue
        if stamp < cutoff:
            _sent_reminders.discard(key)


async def _send_open_reminder(bot, chat_id, start_dt, end_dt):
    remaining_seconds = max(0, int((start_dt - datetime.now(start_dt.tzinfo)).total_seconds()))
    minutes = max(1, (remaining_seconds + 59) // 60)
    key = (chat_id, start_dt.isoformat())
    if key in _sent_reminders or minutes > SCHEDULER_REMINDER_MINUTES:
        return
    try:
        await bot.send_message(
            chat_id,
            "⏰ <b>Group opening soon</b>\n\n"
            f"Group will open in <b>{minutes} minute{'s' if minutes != 1 else ''}</b>.\n"
            f"🟢 Opens: <b>{start_dt.strftime('%I:%M %p')}</b>\n"
            f"🔴 Closes: <b>{end_dt.strftime('%I:%M %p')}</b>",
            parse_mode="HTML",
        )
        _sent_reminders.add(key)
    except Exception as exc:
        logger.warning("Reminder failed chat=%s: %s", chat_id, exc)


async def _apply_chat_permissions(application, chat_id, desired_locked):
    perms = LOCK_PERMS if desired_locked else OPEN_PERMS
    await application.bot.set_chat_permissions(
        chat_id=chat_id,
        permissions=perms,
        use_independent_chat_permissions=True,
    )


async def apply_scheduler(application):
    now_for_cleanup = datetime.now(timezone.utc)
    _prune_reminders(now_for_cleanup)

    for g in await list_groups():
        chat_id = g["chat_id"]
        if g["chat_type"] not in (ChatType.GROUP, ChatType.SUPERGROUP):
            continue

        slots = [slot for slot in await list_schedules(chat_id) if slot["enabled"]]
        if g.get("manual_override"):
            _last_applied_states.pop(chat_id, None)
            continue
        if not slots:
            # No schedule means scheduler no longer owns the lock state. If a
            # previous schedule was active, leave the group OPEN immediately.
            if _last_applied_states.pop(chat_id, None) is not None:
                try:
                    await _apply_chat_permissions(application, chat_id, False)
                    await set_group_value(chat_id, "locked", 0)
                except Exception as exc:
                    logger.warning("Clear-schedule unlock failed chat=%s: %s", chat_id, exc)
            continue

        timezone_name = g.get("timezone") or DEFAULT_TIMEZONE
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            logger.warning("Invalid timezone %r for chat=%s; using %s", timezone_name, chat_id, DEFAULT_TIMEZONE)
            timezone_name = DEFAULT_TIMEZONE
            tz = ZoneInfo(DEFAULT_TIMEZONE)
            await set_group_value(chat_id, "timezone", DEFAULT_TIMEZONE)

        local_now = datetime.now(tz)
        now = local_now.time()
        inside = False
        active_start = active_end = None

        for slot in slots:
            try:
                start_t = datetime.strptime(slot["unlock_time"].strip(), "%I:%M %p").time()
                end_t = datetime.strptime(slot["lock_time"].strip(), "%I:%M %p").time()
            except (TypeError, ValueError):
                logger.error("Invalid schedule row id=%s chat=%s: %r -> %r", slot.get("id"), chat_id, slot.get("unlock_time"), slot.get("lock_time"))
                continue
            if inside_window(now, start_t, end_t):
                inside = True
                active_start, active_end = _window_datetimes(local_now, slot["unlock_time"], slot["lock_time"])
                break

        if not inside:
            upcoming = _next_window(local_now, slots)
            if upcoming:
                start_dt, end_dt, _ = upcoming
                remaining = (start_dt - local_now).total_seconds()
                if 0 < remaining <= SCHEDULER_REMINDER_MINUTES * 60:
                    await _send_open_reminder(application.bot, chat_id, start_dt, end_dt)

        desired_locked = not inside
        previous = _last_applied_states.get(chat_id)
        first_sync = previous is None

        try:
            # Reconcile only when our desired state changed, or on the first pass.
            if previous is None or previous != desired_locked:
                await _apply_chat_permissions(application, chat_id, desired_locked)
                await set_group_value(chat_id, "locked", int(desired_locked))
            _last_applied_states[chat_id] = desired_locked
        except Exception as exc:
            # Do not mark the DB state as applied if Telegram rejected the change.
            logger.error(
                "SCHEDULER PERMISSION FAILED chat=%s timezone=%s desired=%s: %s",
                chat_id, timezone_name, "LOCKED" if desired_locked else "OPEN", exc,
            )
            continue

        if first_sync or previous == desired_locked:
            continue

        try:
            if desired_locked:
                await application.bot.send_message(
                    chat_id,
                    "🔒 <b>Group locked</b>\n\n"
                    "The group is now closed.\n"
                    f"⏰ Closed at: <b>{local_now.strftime('%I:%M %p')}</b>",
                    parse_mode="HTML",
                )
            else:
                close_text = active_end.strftime("%I:%M %p") if active_end else "the scheduled closing time"
                await application.bot.send_message(
                    chat_id,
                    "🔓 <b>Group unlocked</b>\n\n"
                    "The group is now open.\n"
                    f"⏰ Closes at: <b>{close_text}</b>",
                    parse_mode="HTML",
                )
        except Exception as exc:
            logger.warning("Scheduler notification failed chat=%s: %s", chat_id, exc)
