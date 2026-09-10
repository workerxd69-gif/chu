from telegram import Update
from telegram.constants import ChatType, ChatMemberStatus
from database.db import ensure_user, ensure_group
from config import OWNER_ID

GROUP_TYPES = (ChatType.GROUP, ChatType.SUPERGROUP)

async def ensure(update: Update):
    if update.effective_user:
        await ensure_user(
            update.effective_user.id,
            update.effective_user.username,
            update.effective_user.full_name,
            update.effective_user.is_bot,
            bool(update.effective_chat and update.effective_chat.type == ChatType.PRIVATE),
        )
    chat = update.effective_chat
    if chat and chat.type in GROUP_TYPES:
        await ensure_group(chat.id, chat.title or str(chat.id), chat.type)

async def is_owner(update):
    return bool(update.effective_user and update.effective_user.id == OWNER_ID)

async def is_group_admin(chat, user_id):
    if not chat or chat.type not in GROUP_TYPES:
        return False
    try:
        member = await chat.get_member(user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        return False

async def can_manage_group(update, chat_id):
    if not update.effective_user:
        return False
    try:
        chat = await update.get_bot().get_chat(chat_id)
        if chat.type not in GROUP_TYPES:
            return False
        bot_member = await chat.get_member(update.get_bot().id)
        bot_admin = getattr(bot_member, "status", None) in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
        if not bot_admin:
            return False
        if update.effective_user.id == OWNER_ID:
            return True
        return await is_group_admin(chat, update.effective_user.id)
    except Exception:
        return False

async def require_owner_private(update, context):
    ok = bool(update.effective_chat and update.effective_chat.type == ChatType.PRIVATE and await is_owner(update))
    if not ok and update.effective_message:
        await update.effective_message.reply_text("⛔ <b>OWNER PRIVATE CONTROL ONLY</b>", parse_mode="HTML")
    return ok

async def require_group_admin(update, context):
    chat = update.effective_chat
    if not chat or chat.type not in GROUP_TYPES:
        await update.effective_message.reply_text(
            "⚡ <b>GROUP ACTION</b>\n\n"
            "Open ZEUS in private to configure this group.\n"
            "Telegram permissions are applied to the actual group only.",
            parse_mode="HTML"
        )
        return False
    ok = await is_group_admin(chat, update.effective_user.id) or await is_owner(update)
    if not ok:
        await update.effective_message.reply_text("⛔ <b>ADMIN ACCESS REQUIRED</b>", parse_mode="HTML")
    return ok
