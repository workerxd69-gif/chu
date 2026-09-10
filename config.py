# ============================================================
# ZEUS MASTER CONFIG
# ============================================================
# Change the main bot behaviour from this file.
# Keep the bot token private. Set ZEUS_BOT_TOKEN in the environment.
# ============================================================

BOT_TOKEN = "8926481416:AAGMVBrRkA6lLxmT2tQEajOjW6v3dYiSFTI"
OWNER_ID = 1241657820

DATABASE_URL = "data/zeus.db"

# ---------------- TIME / SCHEDULER ----------------
DEFAULT_TIMEZONE = "Asia/Kolkata"
SCHEDULER_TICK_SECONDS = 15
PENDING_ACTION_TTL_SECONDS = 300
SECURITY_MESSAGE_WINDOW_SECONDS = 10
ANTI_FLOOD_MAX_MESSAGES = 6
ANTI_SPAM_REPEAT_THRESHOLD = 3
ANTI_SPAM_MUTE_SECONDS = 60
MENTION_SPAM_MAX = 5
DUPLICATE_WINDOW_SECONDS = 30
JOIN_VERIFICATION_TIMEOUT_SECONDS = 1800
SCHEDULER_REMINDER_MINUTES = 10
TIME_FORMAT = "%I:%M %p"

# ---------------- WARNINGS ----------------
DEFAULT_WARN_LIMIT = 3
WARN_ACTIONS = {
    1: "warn",
    2: "warn",
    3: "mute",
    4: "ban",
}
WARN_MUTE_DURATION = "10m"

# ---------------- SECURITY DEFAULTS ----------------
DEFAULT_ANTI_SPAM = True
DEFAULT_ANTI_FLOOD = True
DEFAULT_ANTI_LINK = False
DEFAULT_ANTI_FORWARD = False
DEFAULT_MENTION_SPAM = True
DEFAULT_DUPLICATE_MESSAGES = True
DEFAULT_CAPS_PROTECTION = False
DEFAULT_BAD_WORD_FILTER = False
BAD_WORDS = ()  # Add normalized words/phrases here when Bad Words protection is enabled.
DEFAULT_RAID_PROTECTION = False
RAID_WINDOW_SECONDS = 60
RAID_JOIN_THRESHOLD = 8
DEFAULT_JOIN_VERIFICATION = False

# ---------------- WELCOME / GOODBYE / RULES ----------------
DEFAULT_WELCOME_ENABLED = True
DEFAULT_GOODBYE_ENABLED = True
WELCOME_DELETE_AFTER = 0
GOODBYE_DELETE_AFTER = 0

WELCOME_MESSAGE = (
    "⚡ <b>Welcome, {mention}</b>\n\n"
    "👥 Group: <b>{group_name}</b>\n"
    "🆔 User ID: <code>{user_id}</code>\n"
    "👤 Members: <code>{members}</code>"
)
GOODBYE_MESSAGE = "👋 <b>{mention}</b> has left <b>{group_name}</b>."
RULES_MESSAGE = (
    "📜 <b>{group_name} — RULES</b>\n\n"
    "1. Respect everyone.\n"
    "2. No spam or flood.\n"
    "3. No unwanted links/files.\n"
    "4. Follow moderator instructions."
)

# ---------------- LOCK TYPES ----------------
DEFAULT_LOCK_LINKS = False
DEFAULT_LOCK_MEDIA = False
DEFAULT_LOCK_STICKERS = False
DEFAULT_LOCK_GIFS = False
DEFAULT_LOCK_FORWARDS = False
DEFAULT_LOCK_VOICE = False
DEFAULT_LOCK_FILES = False

# ---------------- FILE SYSTEM ----------------
FILE_LOG_LIMIT_PER_GROUP = 500
FILE_LIST_PAGE_SIZE = 8
FILE_MAX_RETRIEVAL_SIZE_MB = 50

# ---------------- ADMIN PROMOTION ----------------
ADMIN_DEFAULT_CAN_MANAGE_CHAT = True
ADMIN_DEFAULT_CAN_DELETE_MESSAGES = True
ADMIN_DEFAULT_CAN_RESTRICT_MEMBERS = True
ADMIN_DEFAULT_CAN_INVITE_USERS = True
ADMIN_DEFAULT_CAN_CHANGE_INFO = True
ADMIN_DEFAULT_CAN_PIN_MESSAGES = True
ADMIN_DEFAULT_CAN_MANAGE_TOPICS = True

# ---------------- BROADCAST ----------------
BROADCAST_DELAY_SECONDS = 0.08
BROADCAST_ONLY_STARTED_USERS = True
BROADCAST_TO_GROUPS_ENABLED = True

# ---------------- BRANDING ----------------
BOT_BRAND = "ZEUS"
BOT_VERSION = "3.3.0"
PANEL_TITLE = "⚡ ZEUS CONTROL CENTER"
PANEL_FOOTER = "ZEUS • Premium Group Management"

# ---------------- FILTERS ----------------
FILTER_DEFAULT_ACTION = "delete"
FILTER_ACTIONS = ("reply", "delete", "warn", "mute")

# Supported inline/admin sections.
ENABLE_INLINE_PANEL = True
