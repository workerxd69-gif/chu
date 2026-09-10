import re
from datetime import timedelta
from telegram import ChatPermissions

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

def parse_duration(value):
    if not value:
        return None
    m = re.fullmatch(r"(\d+)\s*(s|m|h|d|w)", str(value).strip().lower())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(seconds=n if unit=="s" else n*60 if unit=="m" else n*3600 if unit=="h" else n*86400 if unit=="d" else n*604800)

def duration_label(td):
    if not td:
        return "Permanent"
    sec = int(td.total_seconds())
    if sec % 604800 == 0: return f"{sec//604800}w"
    if sec % 86400 == 0: return f"{sec//86400}d"
    if sec % 3600 == 0: return f"{sec//3600}h"
    if sec % 60 == 0: return f"{sec//60}m"
    return f"{sec}s"
