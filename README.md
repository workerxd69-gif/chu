# ZEUS Complete Group Management Bot

## Setup
1. Open `config.py`.
2. Put your BotFather token in `BOT_TOKEN`.
3. OWNER_ID is already set to 1241657820.
4. Install packages:
   `pip install -r requirements.txt`
5. Run:
   - Windows: `start.bat`
   - VPS/Linux: `bash start.sh`

## Important
ZEUS must be an administrator in each managed group and have the permissions
required for moderation and changing chat permissions.

## Private control
DM the bot with `/start` and open the inline control center.
From the private panel you can select a managed group and configure:
- Daily scheduler (unlimited windows)
- Timezone
- Security
- Welcome / goodbye / rules
- Locks
- Filters
- Files / Get Files
- Logs
- Group status

Timing is EVERY DAY only. No weekday scheduler is used.

## Broadcast
Owner private chat:
- `/broadcast message`
- Reply to a message and send `/broadcast`
- `/gbroadcast → select a group → send the message`

## Group commands
- `/id`
- `/group`
- `/warn`, `/resetwarn`
- `/mute 10m`, `/unmute`
- `/ban`, `/unban`, `/kick`
- `/del`
- `/purge 50`
- `/lock`, `/unlock`
- `/rules`
- `/filter add word [action]`
- `/filter remove word`
- `/filter list`
- `/files`
- `/getfiles`


ADMIN MANAGEMENT
- /admin: promote a replied user to admin
- /admin @username: promote by username
- /unadmin: remove admin rights from replied user
- Requires Telegram's Add New Admins permission for non-owner admins
PRIVATE SETTING NOTIFICATIONS
- Every private control-panel group setting change sends a confirmation message into that group.

GROUP-SIDE CONTROL CENTER
- /panel now works inside managed groups for authorized admins.
- Group admins can change scheduler, security, locks, filters, messages, files, logs and status without going to private chat.
- The private Owner Control Center remains available.
- Private control is not the only control path.


## Secure token setup
1. Open `config.py` and set `BOT_TOKEN`.
2. Put your BotFather token in `BOT_TOKEN` inside `config.py`.
3. Start with `./start.sh` on Linux/VPS or `start.bat` on Windows.

The bot uses `Asia/Kolkata` by default. A group's timezone can be changed from the Timing panel or `/timezone`.
For an exact broadcast/filter media copy, reply to the source message and use the corresponding command.
