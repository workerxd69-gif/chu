from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import PANEL_TITLE, PANEL_FOOTER, ENABLE_INLINE_PANEL

def main_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Groups", callback_data="groups"),
         InlineKeyboardButton("📢 Broadcast", callback_data="broadcast")],
        [InlineKeyboardButton("📊 Global Status", callback_data="global_status"),
         InlineKeyboardButton("📖 Help", callback_data="help")],
    ])


def gbroadcast_group_selector(groups):
    rows = []
    for g in groups:
        title = (g.get("title") or str(g["chat_id"]))[:34]
        rows.append([InlineKeyboardButton(f"👥 {title}", callback_data=f"gbroadcast_group:{g['chat_id']}")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="gbroadcast_cancel")])
    return InlineKeyboardMarkup(rows)

def group_selector(groups):
    rows = []
    for g in groups:
        title = (g["title"] or str(g["chat_id"]))[:30]
        rows.append([InlineKeyboardButton(f"👥 {title}", callback_data=f"group:{g['chat_id']}")])
    rows.append([InlineKeyboardButton("⬅️ Main", callback_data="panel")])
    return InlineKeyboardMarkup(rows)

def group_panel(chat_id):
    s = str(chat_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏰ Timing", callback_data=f"timing:{s}"),
         InlineKeyboardButton("🌐 Timezone", callback_data=f"timezone:{s}")],
        [InlineKeyboardButton("🛡 Security", callback_data=f"security:{s}"),
         InlineKeyboardButton("🧹 Filters", callback_data=f"filters:{s}")],
        [InlineKeyboardButton("📁 Get Files", callback_data=f"files:{s}"),
         InlineKeyboardButton("💬 Messages", callback_data=f"messages:{s}")],
        [InlineKeyboardButton("🔒 Locks", callback_data=f"locks:{s}"),
         InlineKeyboardButton("📜 Logs", callback_data=f"logs:{s}")],
        [InlineKeyboardButton("📊 Status", callback_data=f"status:{s}")],
        [InlineKeyboardButton("⬅️ Groups", callback_data="groups")],
    ])

def back_group(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Group", callback_data=f"group:{chat_id}")]
    ])

def timing_panel(chat_id):
    s = str(chat_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Window", callback_data=f"timing_add:{s}")],
        [InlineKeyboardButton("📋 Refresh", callback_data=f"timing:{s}"),
         InlineKeyboardButton("🗑 Clear All", callback_data=f"timing_clear:{s}")],
        [InlineKeyboardButton("⬅️ Group", callback_data=f"group:{s}")],
    ])

def files_panel(chat_id, page=0, rows=None):
    s = str(chat_id)
    prev_page = max(0, page-1)
    next_page = page+1
    keyboard = []
    for r in (rows or []):
        label = f"📥 #{r['id']} {str(r.get('file_name') or r.get('file_type') or 'file')[:28]}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"file_get:{r['id']}")])
    keyboard += [
        [InlineKeyboardButton("📋 Refresh", callback_data=f"files:{s}:{page}")],
        [InlineKeyboardButton("⬅️ Prev", callback_data=f"files:{s}:{prev_page}"),
         InlineKeyboardButton("Next ➡️", callback_data=f"files:{s}:{next_page}")],
        [InlineKeyboardButton("⬅️ Group", callback_data=f"group:{s}")],
    ]
    return InlineKeyboardMarkup(keyboard)

def file_retrieve_button(db_id, chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Get File", callback_data=f"file_get:{db_id}")],
        [InlineKeyboardButton("⬅️ Files", callback_data=f"files:{chat_id}:0")],
    ])

def security_panel(chat_id, g):
    s = str(chat_id)
    def st(v): return "🟢 ON" if v else "🔴 OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Anti-Spam {st(g['anti_spam'])}", callback_data=f"toggle:{s}:anti_spam"),
         InlineKeyboardButton(f"Anti-Flood {st(g['anti_flood'])}", callback_data=f"toggle:{s}:anti_flood")],
        [InlineKeyboardButton(f"Anti-Link {st(g['anti_link'])}", callback_data=f"toggle:{s}:anti_link"),
         InlineKeyboardButton(f"Anti-Forward {st(g['anti_forward'])}", callback_data=f"toggle:{s}:anti_forward")],
        [InlineKeyboardButton(f"Mention Spam {st(g['mention_spam'])}", callback_data=f"toggle:{s}:mention_spam"),
         InlineKeyboardButton(f"Duplicate {st(g['duplicate_messages'])}", callback_data=f"toggle:{s}:duplicate_messages")],
        [InlineKeyboardButton(f"Caps {st(g['caps_protection'])}", callback_data=f"toggle:{s}:caps_protection"),
         InlineKeyboardButton(f"Bad Words {st(g['bad_word_filter'])}", callback_data=f"toggle:{s}:bad_word_filter")],
        [InlineKeyboardButton(f"Raid {st(g['raid_protection'])}", callback_data=f"toggle:{s}:raid_protection"),
         InlineKeyboardButton(f"Verify {st(g['join_verification'])}", callback_data=f"toggle:{s}:join_verification")],
        [InlineKeyboardButton("⬅️ Group", callback_data=f"group:{s}")],
    ])

def locks_panel(chat_id, g):
    s = str(chat_id)
    def st(v): return "🟢" if v else "⚪"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{st(g['lock_links'])} Links", callback_data=f"toggle:{s}:lock_links"),
         InlineKeyboardButton(f"{st(g['lock_media'])} Media", callback_data=f"toggle:{s}:lock_media")],
        [InlineKeyboardButton(f"{st(g['lock_stickers'])} Stickers", callback_data=f"toggle:{s}:lock_stickers"),
         InlineKeyboardButton(f"{st(g['lock_gifs'])} GIFs", callback_data=f"toggle:{s}:lock_gifs")],
        [InlineKeyboardButton(f"{st(g['lock_forwards'])} Forwards", callback_data=f"toggle:{s}:lock_forwards"),
         InlineKeyboardButton(f"{st(g['lock_voice'])} Voice", callback_data=f"toggle:{s}:lock_voice")],
        [InlineKeyboardButton(f"{st(g['lock_files'])} Files", callback_data=f"toggle:{s}:lock_files")],
        [InlineKeyboardButton("🔒 Lock Group Now", callback_data=f"manual_lock:{s}"),
         InlineKeyboardButton("🔓 Unlock Group", callback_data=f"manual_unlock:{s}")],
        [InlineKeyboardButton("⬅️ Group", callback_data=f"group:{s}")],
    ])

def messages_panel(chat_id):
    s = str(chat_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Welcome", callback_data=f"msg_welcome:{s}"),
         InlineKeyboardButton("✏️ Goodbye", callback_data=f"msg_goodbye:{s}")],
        [InlineKeyboardButton("📜 Rules", callback_data=f"msg_rules:{s}")],
        [InlineKeyboardButton("⬅️ Group", callback_data=f"group:{s}")],
    ])


def group_local_panel(chat_id):
    s = str(chat_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏰ Timing", callback_data=f"local_timing:{s}"),
         InlineKeyboardButton("🛡 Security", callback_data=f"local_security:{s}")],
        [InlineKeyboardButton("🧹 Filters", callback_data=f"local_filters:{s}"),
         InlineKeyboardButton("🔒 Locks", callback_data=f"local_locks:{s}")],
        [InlineKeyboardButton("💬 Messages", callback_data=f"local_messages:{s}"),
         InlineKeyboardButton("📁 Files", callback_data=f"local_files:{s}")],
        [InlineKeyboardButton("📊 Status", callback_data=f"local_status:{s}"),
         InlineKeyboardButton("📜 Logs", callback_data=f"local_logs:{s}")],
    ])
