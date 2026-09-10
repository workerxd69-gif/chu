from pathlib import Path
from datetime import datetime, timezone
import aiosqlite
from config import (
    DATABASE_URL, DEFAULT_TIMEZONE, DEFAULT_WARN_LIMIT,
    DEFAULT_WELCOME_ENABLED, DEFAULT_GOODBYE_ENABLED,
    DEFAULT_ANTI_SPAM, DEFAULT_ANTI_FLOOD, DEFAULT_ANTI_LINK,
    DEFAULT_ANTI_FORWARD, DEFAULT_MENTION_SPAM, DEFAULT_DUPLICATE_MESSAGES,
    DEFAULT_CAPS_PROTECTION, DEFAULT_BAD_WORD_FILTER, DEFAULT_RAID_PROTECTION,
    DEFAULT_JOIN_VERIFICATION, WELCOME_MESSAGE, GOODBYE_MESSAGE, RULES_MESSAGE,
    DEFAULT_LOCK_LINKS, DEFAULT_LOCK_MEDIA, DEFAULT_LOCK_STICKERS,
    DEFAULT_LOCK_GIFS, DEFAULT_LOCK_FORWARDS, DEFAULT_LOCK_VOICE, DEFAULT_LOCK_FILES, FILE_LOG_LIMIT_PER_GROUP
)

DB_PATH = (Path(__file__).resolve().parent.parent / DATABASE_URL).resolve()

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    chat_type TEXT NOT NULL DEFAULT 'supergroup',
    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    locked INTEGER NOT NULL DEFAULT 0,
    lockdown INTEGER NOT NULL DEFAULT 0,
    manual_override INTEGER NOT NULL DEFAULT 0,
    warn_limit INTEGER NOT NULL DEFAULT 3,
    welcome_enabled INTEGER NOT NULL DEFAULT 1,
    goodbye_enabled INTEGER NOT NULL DEFAULT 1,
    anti_spam INTEGER NOT NULL DEFAULT 1,
    anti_flood INTEGER NOT NULL DEFAULT 1,
    anti_link INTEGER NOT NULL DEFAULT 0,
    anti_forward INTEGER NOT NULL DEFAULT 0,
    mention_spam INTEGER NOT NULL DEFAULT 1,
    duplicate_messages INTEGER NOT NULL DEFAULT 1,
    caps_protection INTEGER NOT NULL DEFAULT 0,
    bad_word_filter INTEGER NOT NULL DEFAULT 0,
    raid_protection INTEGER NOT NULL DEFAULT 0,
    join_verification INTEGER NOT NULL DEFAULT 0,
    lock_links INTEGER NOT NULL DEFAULT 0,
    lock_media INTEGER NOT NULL DEFAULT 0,
    lock_stickers INTEGER NOT NULL DEFAULT 0,
    lock_gifs INTEGER NOT NULL DEFAULT 0,
    lock_forwards INTEGER NOT NULL DEFAULT 0,
    lock_voice INTEGER NOT NULL DEFAULT 0,
    lock_files INTEGER NOT NULL DEFAULT 0,
    welcome_text TEXT,
    goodbye_text TEXT,
    welcome_reply_chat_id INTEGER,
    welcome_reply_message_id INTEGER,
    goodbye_reply_chat_id INTEGER,
    goodbye_reply_message_id INTEGER,
    rules_text TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    is_bot INTEGER NOT NULL DEFAULT 0,
    started_private INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS warnings (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    unlock_time TEXT NOT NULL,
    lock_time TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS filters (
    chat_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'reply',
    reply_text TEXT,
    reply_chat_id INTEGER,
    reply_message_id INTEGER,
    reply_media_type TEXT,
    reply_file_id TEXT,
    reply_caption TEXT,
    PRIMARY KEY(chat_id, word)
);
CREATE TABLE IF NOT EXISTS scheduled_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    time TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    actor_id INTEGER,
    action TEXT NOT NULL,
    target_id INTEGER,
    details TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    user_id INTEGER,
    file_type TEXT NOT NULL,
    file_id TEXT NOT NULL,
    file_name TEXT,
    mime_type TEXT,
    file_size INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_actions (
    user_id INTEGER PRIMARY KEY,
    action TEXT NOT NULL,
    chat_id INTEGER,
    payload TEXT,
    created_at TEXT NOT NULL
);
"""

GROUP_DEFAULTS = {
    "timezone": DEFAULT_TIMEZONE,
    "locked": 0, "lockdown": 0, "warn_limit": DEFAULT_WARN_LIMIT,
    "welcome_enabled": int(DEFAULT_WELCOME_ENABLED),
    "goodbye_enabled": int(DEFAULT_GOODBYE_ENABLED),
    "anti_spam": int(DEFAULT_ANTI_SPAM),
    "anti_flood": int(DEFAULT_ANTI_FLOOD),
    "anti_link": int(DEFAULT_ANTI_LINK),
    "anti_forward": int(DEFAULT_ANTI_FORWARD),
    "mention_spam": int(DEFAULT_MENTION_SPAM),
    "duplicate_messages": int(DEFAULT_DUPLICATE_MESSAGES),
    "caps_protection": int(DEFAULT_CAPS_PROTECTION),
    "bad_word_filter": int(DEFAULT_BAD_WORD_FILTER),
    "raid_protection": int(DEFAULT_RAID_PROTECTION),
    "join_verification": int(DEFAULT_JOIN_VERIFICATION),
    "lock_links": int(DEFAULT_LOCK_LINKS),
    "lock_media": int(DEFAULT_LOCK_MEDIA),
    "lock_stickers": int(DEFAULT_LOCK_STICKERS),
    "lock_gifs": int(DEFAULT_LOCK_GIFS),
    "lock_forwards": int(DEFAULT_LOCK_FORWARDS),
    "lock_voice": int(DEFAULT_LOCK_VOICE),
    "lock_files": int(DEFAULT_LOCK_FILES),
    "welcome_text": WELCOME_MESSAGE,
    "goodbye_text": GOODBYE_MESSAGE,
    "rules_text": RULES_MESSAGE,
}

async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        # Backward-compatible migrations for existing ZEUS databases.
        cur = await db.execute("PRAGMA table_info(groups)")
        group_cols = {row[1] for row in await cur.fetchall()}
        if "manual_override" not in group_cols:
            await db.execute("ALTER TABLE groups ADD COLUMN manual_override INTEGER NOT NULL DEFAULT 0")
        for col, typ in (
            ("welcome_reply_chat_id", "INTEGER"),
            ("welcome_reply_message_id", "INTEGER"),
            ("goodbye_reply_chat_id", "INTEGER"),
            ("goodbye_reply_message_id", "INTEGER"),
        ):
            if col not in group_cols:
                await db.execute(f"ALTER TABLE groups ADD COLUMN {col} {typ}")
        cur = await db.execute("PRAGMA table_info(filters)")
        cols = {row[1] for row in await cur.fetchall()}
        for col, typ in (("reply_text", "TEXT"), ("reply_chat_id", "INTEGER"), ("reply_message_id", "INTEGER"),
                         ("reply_media_type", "TEXT"), ("reply_file_id", "TEXT"), ("reply_caption", "TEXT")):
            if col not in cols:
                await db.execute(f"ALTER TABLE filters ADD COLUMN {col} {typ}")
        await db.commit()

def _now():
    return datetime.now(timezone.utc).isoformat()

async def ensure_user(user_id, username, full_name, is_bot=False, started_private=False):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users(user_id,username,full_name,is_bot,started_private,updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name,
                is_bot=excluded.is_bot,
                started_private=MAX(users.started_private, excluded.started_private),
                updated_at=excluded.updated_at
        """, (user_id, username, full_name, int(is_bot), int(started_private), _now()))
        await db.commit()

async def private_users():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE started_private=1 AND is_bot=0")
        return [r[0] for r in await cur.fetchall()]

async def ensure_group(chat_id, title, chat_type="supergroup"):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT chat_id FROM groups WHERE chat_id=?", (chat_id,))
        exists = await cur.fetchone()
        if exists:
            # Existing ZEUS groups keep their chosen timezone; only fill legacy/blank values.
            await db.execute("UPDATE groups SET title=?,chat_type=?,timezone=COALESCE(NULLIF(timezone, ''), ?),updated_at=? WHERE chat_id=?",
                             (title, chat_type, DEFAULT_TIMEZONE, _now(), chat_id))
        else:
            cols = ["chat_id", "title", "chat_type", "updated_at"] + list(GROUP_DEFAULTS.keys())
            vals = [chat_id, title, chat_type, _now()] + list(GROUP_DEFAULTS.values())
            qs = ",".join("?" for _ in vals)
            await db.execute(f"INSERT INTO groups({','.join(cols)}) VALUES({qs})", vals)
        await db.commit()

async def list_groups():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM groups ORDER BY title COLLATE NOCASE")
        return [dict(r) for r in await cur.fetchall()]

async def get_group(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM groups WHERE chat_id=?", (chat_id,))
        r = await cur.fetchone()
        return dict(r) if r else None

async def set_group_value(chat_id, key, value):
    allowed = set(GROUP_DEFAULTS) | {"locked", "lockdown", "warn_limit", "title", "chat_type", "welcome_reply_chat_id", "welcome_reply_message_id", "goodbye_reply_chat_id", "goodbye_reply_message_id"}
    if key not in allowed:
        raise ValueError("Invalid group setting")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE groups SET {key}=?,updated_at=? WHERE chat_id=?", (value, _now(), chat_id))
        await db.commit()

async def list_schedules(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM schedules WHERE chat_id=? ORDER BY id", (chat_id,))
        return [dict(r) for r in await cur.fetchall()]

async def add_schedule(chat_id, unlock_time, lock_time):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO schedules(chat_id,unlock_time,lock_time,enabled) VALUES(?,?,?,1)",
            (chat_id, unlock_time, lock_time)
        )
        await db.commit()
        return cur.lastrowid

async def delete_schedule(chat_id, schedule_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM schedules WHERE chat_id=? AND id=?", (chat_id, schedule_id))
        await db.commit()

async def delete_schedule_slot(chat_id, slot_number):
    """Delete a group's 1-based displayed slot number, independent of SQLite AUTOINCREMENT IDs."""
    rows = await list_schedules(chat_id)
    if slot_number < 1 or slot_number > len(rows):
        return False
    await delete_schedule(chat_id, rows[slot_number - 1]["id"])
    return True

async def clear_schedules(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM schedules WHERE chat_id=?", (chat_id,))
        await db.commit()

async def add_warning(chat_id, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO warnings(chat_id,user_id,count) VALUES(?,?,1)
            ON CONFLICT(chat_id,user_id) DO UPDATE SET count=count+1
        """, (chat_id, user_id))
        await db.commit()
        cur = await db.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        return (await cur.fetchone())[0]

async def reset_warnings(chat_id, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        await db.commit()

async def add_filter(chat_id, word, action="reply", reply_text=None, reply_chat_id=None, reply_message_id=None,
              reply_media_type=None, reply_file_id=None, reply_caption=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO filters(chat_id,word,action,reply_text,reply_chat_id,reply_message_id,reply_media_type,reply_file_id,reply_caption)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(chat_id,word) DO UPDATE SET
                action=excluded.action,
                reply_text=excluded.reply_text,
                reply_chat_id=excluded.reply_chat_id,
                reply_message_id=excluded.reply_message_id,
                reply_media_type=excluded.reply_media_type,
                reply_file_id=excluded.reply_file_id,
                reply_caption=excluded.reply_caption
        """, (chat_id, word, action, reply_text, reply_chat_id, reply_message_id, reply_media_type, reply_file_id, reply_caption))
        await db.commit()

async def remove_filter(chat_id, word):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM filters WHERE chat_id=? AND word=?", (chat_id, word))
        await db.commit()

async def get_filters(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT word,action,reply_text,reply_chat_id,reply_message_id,reply_media_type,reply_file_id,reply_caption FROM filters WHERE chat_id=? ORDER BY word", (chat_id,))
        return await cur.fetchall()

async def add_log(chat_id, actor_id, action, target_id=None, details=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO logs(chat_id,actor_id,action,target_id,details,created_at) VALUES(?,?,?,?,?,?)",
            (chat_id, actor_id, action, target_id, details, _now())
        )
        await db.commit()

async def recent_logs(chat_id, limit=12):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT actor_id,action,target_id,details,created_at FROM logs WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit)
        )
        return await cur.fetchall()

async def track_file(chat_id, message_id, user_id, file_type, file_id, file_name=None, mime_type=None, file_size=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO files(chat_id,message_id,user_id,file_type,file_id,file_name,mime_type,file_size,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (chat_id, message_id, user_id, file_type, file_id, file_name, mime_type, file_size, _now()))
        await db.execute("""
            DELETE FROM files WHERE chat_id=? AND id NOT IN
            (SELECT id FROM files WHERE chat_id=? ORDER BY id DESC LIMIT ?)
        """, (chat_id, chat_id, FILE_LOG_LIMIT_PER_GROUP))
        await db.commit()

async def list_files(chat_id, file_type=None, limit=8, offset=0):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if file_type:
            cur = await db.execute(
                "SELECT * FROM files WHERE chat_id=? AND file_type=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (chat_id, file_type, limit, offset)
            )
        else:
            cur = await db.execute(
                "SELECT * FROM files WHERE chat_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (chat_id, limit, offset)
            )
        return [dict(r) for r in await cur.fetchall()]

async def count_files(chat_id, file_type=None):
    async with aiosqlite.connect(DB_PATH) as db:
        if file_type:
            cur = await db.execute("SELECT COUNT(*) FROM files WHERE chat_id=? AND file_type=?", (chat_id, file_type))
        else:
            cur = await db.execute("SELECT COUNT(*) FROM files WHERE chat_id=?", (chat_id,))
        return (await cur.fetchone())[0]

async def get_file(file_db_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM files WHERE id=?", (file_db_id,))
        r = await cur.fetchone()
        return dict(r) if r else None

async def set_pending(user_id, action, chat_id=None, payload=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO pending_actions(user_id,action,chat_id,payload,created_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET action=excluded.action,chat_id=excluded.chat_id,
            payload=excluded.payload,created_at=excluded.created_at
        """, (user_id, action, chat_id, payload, _now()))
        await db.commit()

async def get_pending(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM pending_actions WHERE user_id=?", (user_id,))
        r = await cur.fetchone()
        return dict(r) if r else None

async def clear_pending(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM pending_actions WHERE user_id=?", (user_id,))
        await db.commit()
