# ============================================================
#  VPS BOT — FULL v4 (fixed)
#  video spoiler | top5 lb | log channel full | vps list paginated
#  maintenance mode | admin list all vps | new user log
#  FIX: /broadcastbtn now preserves premium emoji / blockquote via copy_message(reply_markup=...)
#  NEW: /cancel command to cancel any pending FSM state (broadcast, add vps, etc.)
# ============================================================

import asyncio
import html
import logging
import os
import secrets
import string
import subprocess
import urllib.request
import re
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command, BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.mongo import MongoStorage
from aiogram.types import (
    Message, CallbackQuery, ChatMemberUpdated,
    ChatMemberLeft, ChatMemberBanned, ChatMemberRestricted,
    TelegramObject,
)
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Any, Awaitable, Callable, Dict

logging.basicConfig(level=logging.INFO)

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────
BOT_TOKEN   = "8871353741:AAFUVMCK67Qe3CJFSUFWlOaz_I2Z6wHh9Q0"
MONGO_URI   = "mongodb+srv://czllr_db_user:l8bBOIyIzUnwwNbc@cluster0.xqpnqiy.mongodb.net/?appName=Cluster0"
ADMIN_IDS   = [8062871988]
LOG_CHANNEL = -1004355403729
REFS_NEEDED = 10

# ─── VPS PLANS — cost, emoji, button style per plan ───
PLAN_META = {
    "basic":    {"em": "gift2",    "style": "success"},
    "standard": {"em": "bolt2",    "style": "primary"},
    "pro":      {"em": "sword2",   "style": "danger"},
    "premium":  {"em": "diamond2", "style": "primary"},
}
PLAN_PTS = {"standard": 20, "pro": 25, "premium": 30}   # basic = REFS_NEEDED (admin-changeable)

def plan_cost(plan):
    return REFS_NEEDED if plan == "basic" else PLAN_PTS.get(plan, REFS_NEEDED)

PLAN_ROOT = {"basic": False, "standard": False, "pro": False, "premium": False}  # sudo access per plan

WELCOME_VIDEO_URL     = "https://files.catbox.moe/jzrynf.mp4"
WELCOME_VIDEO_FILE_ID = None

FORCE_CHANNELS = ["osintxher", "vps_Leaks", "bynxgc"]
PRIVATE_CHANNELS = {
    -1004445659850: "https://t.me/+405BKd6OXGM0ZWNl",
    -1003794439741: "https://t.me/bynxgc",
    -1003986869965: "https://t.me/+wDmuCBH3qro2OTc1",
}  # private channels: id → invite link

MAINTENANCE = False   # toggled at runtime
_BOT_INFO   = None   # cached bot info
_USER_CACHE: dict = {}   # uid → (user_doc, timestamp)
_CACHE_TTL  = 30         # seconds before re-fetch from mongo
BTN_CYCLE = 0          # cycles button colors every call

# MESSAGE EFFECTS (Bot API — private chats only, works only if bot owner has premium)
EFFECT_FIRE     = "5046509860389126442"
EFFECT_LIKE     = "5107584321108051014"
EFFECT_CONFETTI = "5046589136895476101"
EFFECT_HEART    = "5044134455711629726"

# ─────────────────────────────────────────
#  PREMIUM EMOJIS
# ─────────────────────────────────────────
EM = {
    "disc":      "5215352343419167936",
    "loop":      "5465270065102334742",
    "butterfly": "5305352695912098826",
    "sparkle":   "6066763347095721039",
    "user":      "5258011929993026890",
    "smile":     "5278573677900752088",
    "gift":      "4958699241137505132",
    "love":      "6287305455274301148",
    "sword":     "5215304501778462442",
    "star":      "6105190140320159279",
    "fire":      "6104820463895057992",
    "diamond":   "6105048883140760635",
    "crown":     "6104690120227559861",
    "thunder":   "6104969984591532862",
    "shield":    "6105072282122590595",
    "rocket":    "6122974169668785707",
    "gem":       "6127296324107769784",
    "lock":      "6125230925874731296",
    "key":       "6125103558619568255",
    "check":     "6203911118964924015",
    "vps":       "6127636064610818291",
    "active":    "5429405838345265327",
    "ssh":       "6158867181296685529",
    "deploy":    "6159218239038559473",
    "join":      "6107398427820168649",
    "wrench":    "5258023599419171861",
    "clock":     "5258419835922030550",
    "pen":       "6124975405385391463",
    "sword2":    "6289611483345069681",
    "bolt":      "6163365257596114821",
    "bolt2":     "6145602024479135050",
    "gift2":     "6098277832838881265",
    "brain":     "6321266298554687801",
    "brain2":    "6098431695747291957",
    "kbd":       "5298975240708187753",
    "lock2":     "5305432882951514716",
    "crown2":    "6240081804523479887",
    "diamond2":  "6123070651814124726",
    "check2":    "6255879656310836553",
    "heart2":    "5276526906940883787",
    "rocket2":   "6203911118964924015",
    "phone":     "5334954057192719331",
}

def e(name: str) -> str:
    return f'<tg-emoji emoji-id="{EM.get(name, EM["star"])}">⭐</tg-emoji>'

_SC_FROM  = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_SC_TO    = "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴩqʀꜱᴛᴜᴠᴡxʏᴢᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴩqʀꜱᴛᴜᴠᴡxʏᴢ"
_SC_TABLE = str.maketrans(_SC_FROM, _SC_TO)
def sc(t): return t.translate(_SC_TABLE)

def loops(n=22):
    return "".join([f'<tg-emoji emoji-id="{EM["loop"]}">➿</tg-emoji>' for _ in range(n)])

def swords(n=8):
    return "".join([f'<tg-emoji emoji-id="{EM["sword"]}">⚔️</tg-emoji>' for _ in range(n)])

def progress_bar(cur, total, length=10):
    filled = min(int((cur / total) * length), length)
    pct    = min(int((cur / total) * 100), 100)
    return f"{'▰'*filled}{'▱'*(length-filled)} {pct}%"

# ─────────────────────────────────────────
#  SSH USER PROVISIONING — on REMOTE servers added by admin (not on the bot host)
# ─────────────────────────────────────────
import io
import shlex
import paramiko

def validate_username(username: str):
    allowed = string.ascii_lowercase + string.digits + "_-"
    if not username or len(username) > 32 or not username[0].islower():
        raise ValueError(sc("username lowercase letter se start ho aur 32 chars se chhota ho"))
    if any(ch not in allowed for ch in username):
        raise ValueError(sc("sirf lowercase letters, digits, _ aur - allowed hain"))

def make_password(length=16):
    chars = string.ascii_letters + string.digits + "!@#$%^&*_-"
    return "".join(secrets.choice(chars) for _ in range(length))

def _load_pkey(pem_text: str):
    """load a private key (.pem) of any common type from text"""
    last = None
    for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
        try:
            return cls.from_private_key(io.StringIO(pem_text))
        except Exception as ex:
            last = ex
    raise ValueError(f"invalid .pem key ({last})")

def _raw_exec(client, cmd: str, input_text: str = None, timeout: int = 60):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    if input_text:
        stdin.write(input_text); stdin.flush()
    stdin.channel.shutdown_write()
    rc = stdout.channel.recv_exit_status()
    return rc, stdout.read().decode(errors="ignore").strip(), stderr.read().decode(errors="ignore").strip()

def _ssh_connect(srv: dict) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw = dict(hostname=srv["ip"], port=int(srv["port"]), username=srv["username"],
              timeout=15, banner_timeout=15, auth_timeout=15,
              allow_agent=False, look_for_keys=False)
    if srv.get("pem"):
        kw["pkey"] = _load_pkey(srv["pem"])
    else:
        kw["password"] = srv.get("password", "")
    client.connect(**kw)
    # how do we get root on this server?
    if srv["username"] == "root":
        client._sudo_mode = "root"
    elif _raw_exec(client, "sudo -n true")[0] == 0:
        client._sudo_mode = "nopass"          # passwordless sudo
    elif srv.get("password"):
        client._sudo_mode = "pass"            # sudo with the login password
    else:
        client._sudo_mode = "none"
    return client

def _ssh_exec(client, srv: dict, cmd: str, input_text: str = None, timeout: int = 60):
    """run a command as root on the server (root login, or sudo with/without password)"""
    mode = getattr(client, "_sudo_mode", "root")
    if mode == "nopass":
        cmd = "sudo -n " + cmd
    elif mode == "pass":
        # -k: always ask, -S: read password from stdin (first line), -p '': no prompt text
        cmd = "sudo -k -S -p '' " + cmd
        input_text = srv["password"] + "\n" + (input_text or "")
    return _raw_exec(client, cmd, input_text, timeout)

def test_server(srv: dict) -> dict:
    """check login works and we have root (or passwordless sudo) on the server"""
    try:
        client = _ssh_connect(srv)
    except Exception as ex:
        return {"success": False, "error": f"login failed: {ex}"}
    try:
        rc, out, err = _ssh_exec(client, srv, "id -u")
        if rc != 0 or out != "0":
            return {"success": False, "error": "login ok, par root access nahi mila (sudo password galat hai ya user sudo group me nahi hai). " + (err or out)}
        rc, host, _ = _ssh_exec(client, srv, "hostname")
        return {"success": True, "hostname": host}
    finally:
        client.close()

def create_ssh_user(srv: dict, username: str, password: str = None) -> dict:
    """creates a linux user on the REMOTE server — returns dict(success, username, password | error)"""
    validate_username(username)
    password = password or make_password()
    q = shlex.quote(username)
    home = shlex.quote(f"/home/{username}")
    try:
        client = _ssh_connect(srv)
    except Exception as ex:
        return {"success": False, "error": f"server se connect nahi ho paya: {ex}"}
    try:
        rc, _, _ = _ssh_exec(client, srv, f"id -u {q}")
        if rc == 0:
            return {"success": False, "error": f"username already taken on server: {username}"}
        steps = [
            (f"useradd -m -s /bin/bash {q}", None),
            ("chpasswd", f"{username}:{password}\n"),
            (f"mkdir -p {home}/public_html {home}/.ssh", None),
            (f"chown -R {q}:{q} {home}", None),
            (f"chmod 700 {home}/.ssh", None),
        ]
        for cmd, inp in steps:
            rc, out, err = _ssh_exec(client, srv, cmd, inp)
            if rc != 0:
                _ssh_exec(client, srv, f"userdel -r {q}")  # remove half-created user
                return {"success": False, "error": f"{cmd.split()[0]} failed: {err or out}"}
        return {"success": True, "username": username, "password": password}
    except Exception as ex:
        try: _ssh_exec(client, srv, f"userdel -r {q}")
        except Exception: pass
        return {"success": False, "error": str(ex)}
    finally:
        client.close()

def delete_ssh_user(srv: dict, username: str) -> dict:
    """deletes a linux user from the REMOTE server"""
    validate_username(username)
    try:
        client = _ssh_connect(srv)
    except Exception as ex:
        return {"success": False, "error": str(ex)}
    try:
        rc, out, err = _ssh_exec(client, srv, f"userdel -r {shlex.quote(username)}")
        return {"success": rc == 0, "error": err or out}
    finally:
        client.close()


_SETUP_SCRIPT = r"""
U=__USER__
F=/etc/sudoers.d/__FNAME__
if [ "$U" != "root" ]; then
  echo "$U ALL=(ALL) NOPASSWD:ALL" > "$F" && chmod 440 "$F" && echo SUDO_OK || echo SUDO_FAIL
fi
C=/etc/ssh/sshd_config
if [ -f "$C" ]; then
  cp -n "$C" "$C.bot-backup" 2>/dev/null
  for f in "$C" /etc/ssh/sshd_config.d/*.conf; do
    [ -f "$f" ] && sed -i -E 's/^[#[:space:]]*PasswordAuthentication[[:space:]]+.*/PasswordAuthentication yes/I' "$f"
  done
  head -n 1 "$C" | grep -qiE '^PasswordAuthentication[[:space:]]+yes' || sed -i '1i PasswordAuthentication yes' "$C"
  if command -v sshd >/dev/null 2>&1 && ! sshd -t >/dev/null 2>&1; then
    cp "$C.bot-backup" "$C"; echo SSHD_BAD
  else
    echo PASS_OK
    ( systemctl reload ssh || systemctl reload sshd || service ssh reload || service sshd reload \
      || kill -HUP "$(cat /var/run/sshd.pid)" ) >/dev/null 2>&1 && echo RELOAD_OK || echo RELOAD_FAIL
  fi
else
  echo NO_SSHD
fi
"""

def setup_server(srv: dict) -> list:
    """auto-prepare a server: passwordless sudo + password login on + ssh reload. returns report lines"""
    report = []
    try:
        client = _ssh_connect(srv)
    except Exception as ex:
        return [f"❌ login failed: {ex}"]
    try:
        script = (_SETUP_SCRIPT.replace("__USER__", shlex.quote(srv["username"]))
                               .replace("__FNAME__", re.sub(r"[^A-Za-z0-9_-]", "_", srv["username"]) + "-bot"))
        rc, out, err = _ssh_exec(client, srv, "sh -c " + shlex.quote(script), timeout=90)
        tags = set(out.split())
        if srv["username"] == "root":
            report.append("✅ root login — sudo ki zaroorat nahi")
        elif "SUDO_OK" in tags:
            report.append("✅ passwordless sudo set")
        else:
            report.append("❌ sudo set nahi hua: " + (err or out)[:200])
        if "PASS_OK" in tags:
            report.append("✅ password login on (users login kar payenge)")
        elif "SSHD_BAD" in tags:
            report.append("❌ sshd config me error, purana config wapas laga diya")
        elif "NO_SSHD" in tags:
            report.append("⚠️ /etc/ssh/sshd_config nahi mila — kya server pe openssh-server hai?")
        if "RELOAD_OK" in tags:
            report.append("✅ ssh reloaded")
        elif "RELOAD_FAIL" in tags:
            report.append("⚠️ ssh reload nahi hua — server ek baar restart kar do")
    except Exception as ex:
        report.append(f"❌ setup error: {ex}")
    finally:
        client.close()
    pw = srv.get("password") or ""
    if pw and (len(pw) < 10 or pw.isdigit()):
        report.append("⚠️ server ka password weak hai — passwd se strong password rakho, phir server dobara add karo")
    return report

async def pick_server(db):
    """server with the fewest vps gets the next one"""
    return await db.servers.find_one({}, sort=[("vps_count", 1)])

# ─────────────────────────────────────────
#  MAINTENANCE MIDDLEWARE
# ─────────────────────────────────────────
MAINTENANCE_TEXT = (
    f"<blockquote>"
    f'<tg-emoji emoji-id="{EM["pen"]}">✍️</tg-emoji> <b>{sc("bot under maintenance")}</b>\n\n'
    f'<tg-emoji emoji-id="{EM["wrench"]}">🔧</tg-emoji> {sc("bot maintenance mein hai.")}\n'
    f'<tg-emoji emoji-id="{EM["clock"]}">🕔</tg-emoji> {sc("please wait & try again later.")}'
    f"</blockquote>"
)

class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: Dict[str, Any]) -> Any:
        if not MAINTENANCE:
            return await handler(event, data)
        uid = None
        if hasattr(event, "from_user") and event.from_user:
            uid = event.from_user.id
        if uid in ADMIN_IDS:
            return await handler(event, data)
        bot: Bot = data.get("bot")
        if bot:
            try:
                if hasattr(event, "message") and event.message:
                    await event.message.answer(MAINTENANCE_TEXT, parse_mode="HTML")
                elif hasattr(event, "answer"):
                    await event.answer(MAINTENANCE_TEXT, parse_mode="HTML")
                elif hasattr(event, "chat"):
                    await bot.send_message(event.chat.id, MAINTENANCE_TEXT, parse_mode="HTML")
            except: pass
        return None

# ─────────────────────────────────────────
#  GROUP SILENCER
# ─────────────────────────────────────────
# Groups/supergroups me bot kisi user message ya button-click ka reply nahi karega.
# Broadcasts is middleware se affect nahi hote, kyunki woh bot.send_message/copy_message
# se directly bheje jaate hain. Private DM me saare handlers normal chalenge.
class GroupChatSilencer(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: Dict[str, Any]) -> Any:
        chat = None
        if isinstance(event, Message):
            chat = event.chat
        elif isinstance(event, CallbackQuery) and event.message:
            chat = event.message.chat

        if chat and chat.type in ("group", "supergroup"):
            return None
        return await handler(event, data)

# ─────────────────────────────────────────
#  KEYBOARDS
# ─────────────────────────────────────────
STYLE_CYCLE = [["success","primary","danger"],["danger","success","primary"],["primary","danger","success"]]

def next_styles():
    global BTN_CYCLE
    BTN_CYCLE = (BTN_CYCLE + 1) % len(STYLE_CYCLE)
    return STYLE_CYCLE[BTN_CYCLE]

def kb_main() -> dict:
    s = next_styles()
    return {"inline_keyboard": [
        [
            {"text": f"{sc('create vps')}",  "callback_data": "create_vps", "icon_custom_emoji_id": EM["rocket"], "style": s[0]},
            {"text": f"{sc('my vps')}",       "callback_data": "my_vps", "icon_custom_emoji_id": EM["shield"],     "style": s[1]},
        ],
        [
            {"text": f"{sc('my profile')}",   "callback_data": "my_profile", "icon_custom_emoji_id": EM["crown"], "style": s[2]},
            {"text": f"{sc('leaderboard')}",  "callback_data": "leaderboard", "icon_custom_emoji_id": EM["star"],"style": s[0]},
        ],
        [
            {"text": f"{sc('vps plans')}", "callback_data": "vps_plans", "icon_custom_emoji_id": EM["diamond2"], "style": "primary"},
        ],
        [
            {"text": f"{sc('buy pts')} ⭐", "callback_data": "buy_pts", "icon_custom_emoji_id": EM["star"], "style": "danger"},
        ],
        [
            {"text": f"{sc('support')}",      "url": "https://t.me/heartfailer", "icon_custom_emoji_id": EM["key"]},
        ],
    ]}

def kb_force_join(channels: list) -> dict:
    rows = []
    # collect all buttons
    btns = []
    for ch in channels:
        ch_str = str(ch)
        if "__noverify" in ch_str or ch_str.startswith("__private__"):
            chat_id = int(ch_str.replace("__private__","").replace("__noverify",""))
            invite  = PRIVATE_CHANNELS.get(chat_id, "")
            btns.append({"text": f"{sc('join gc')}", "url": invite, "style": "success"})
        else:
            btns.append({"text": f"@{ch}", "url": f"https://t.me/{ch}", "style": "success"})

    # layout: first 2 channels side by side, then remaining 2 per row
    # row 1: first 2 public channels (if exist)
    pub = [b for b in btns if b["text"].startswith("@")]
    pvt = [b for b in btns if not b["text"].startswith("@")]

    # public channels — 2 per row
    for i in range(0, len(pub), 2):
        rows.append(pub[i:i+2])
    # private gc — 2 per row
    for i in range(0, len(pvt), 2):
        rows.append(pvt[i:i+2])

    rows.append([{"text": f"{sc('i joined')} ✓", "callback_data": "check_join", "icon_custom_emoji_id": EM["fire"], "style": "success"}])
    return {"inline_keyboard": rows}

def kb_admin() -> dict:
    s = next_styles()
    return {"inline_keyboard": [
        [
            {"text": f"{sc('users')}",          "callback_data": "adm_users", "icon_custom_emoji_id": EM["star"],        "style": s[0]},
            {"text": f"{sc('stats')}",          "callback_data": "adm_stats", "icon_custom_emoji_id": EM["fire"],        "style": s[1]},
        ],
        [
            {"text": f"{sc('broadcast')}",      "callback_data": "adm_broadcast", "icon_custom_emoji_id": EM["rocket"],    "style": "danger"},
            {"text": f"{sc('logs')}",           "callback_data": "adm_logs", "icon_custom_emoji_id": EM["gem"],         "style": "success"},
        ],
        [
            {"text": f"{sc('add fj')}",         "callback_data": "adm_add_fj", "icon_custom_emoji_id": EM["thunder"],       "style": "success"},
            {"text": f"{sc('remove fj')}",      "callback_data": "adm_remove_fj", "icon_custom_emoji_id": EM["lock"],    "style": "danger"},
        ],
        [
            {"text": f"{sc('give admin')}",     "callback_data": "adm_give_admin", "icon_custom_emoji_id": EM["crown"],   "style": "success"},
            {"text": f"{sc('remove admin')}",   "callback_data": "adm_remove_admin", "icon_custom_emoji_id": EM["shield"], "style": "danger"},
        ],
        [
            {"text": f"{sc('give points')}",    "callback_data": "adm_give_credit", "icon_custom_emoji_id": EM["gem"],  "style": "success"},
            {"text": f"{sc('remove points')}", "callback_data": "adm_remove_credit", "icon_custom_emoji_id": EM["key"],"style": "danger"},
        ],
        [
            {"text": f"{sc('create redeem code')}", "callback_data": "adm_create_redeem", "icon_custom_emoji_id": EM["gift"], "style": "primary"},
            {"text": f"{sc('delete redeem code')}", "callback_data": "adm_delete_redeem", "icon_custom_emoji_id": EM["lock"], "style": "danger"},
        ],
        [
            {"text": f"{sc('admin list')}",     "callback_data": "adm_admin_list", "icon_custom_emoji_id": EM["star"],   "style": "success"},
            {"text": f"{sc('vps cost')}: {REFS_NEEDED} {sc('pts')}", "callback_data": "adm_set_cost", "icon_custom_emoji_id": EM["gem"], "style": "primary"},
        ],
        [
            {"text": f"{sc('maintenance')}",    "callback_data": "adm_maintenance", "icon_custom_emoji_id": EM["wrench"],  "style": "danger" if not MAINTENANCE else "success"},
        ],
        [
            {"text": f"{sc('vps servers')}",    "callback_data": "adm_servers", "icon_custom_emoji_id": EM["vps"],  "style": "success"},
        ],
    ]}

def kb_plan_picker() -> dict:
    rows = []
    for p in ("basic", "standard", "pro", "premium"):
        rows.append([{"text": f"{sc(p)} — {plan_cost(p)} pts", "callback_data": f"pickplan_{p}",
                     "icon_custom_emoji_id": EM[PLAN_META[p]["em"]], "style": PLAN_META[p]["style"]}])
    rows.append([{"text": f"{sc('cancel')}", "callback_data": "back_main", "icon_custom_emoji_id": EM["lock"], "style": "danger"}])
    return {"inline_keyboard": rows}

def kb_back() -> dict:
    return {"inline_keyboard": [[
        {"text": f"{sc('back')}", "callback_data": "back_main", "icon_custom_emoji_id": EM["fire"], "style": "primary"}
    ]]}

def kb_cancel() -> dict:
    return {"inline_keyboard": [[
        {"text": f"{sc('cancel')}", "callback_data": "cancel_state", "icon_custom_emoji_id": EM["lock"], "style": "danger"}
    ]]}

def kb_buy_pts() -> dict:
    return {"inline_keyboard": [
        [{"text": f"{sc('i have paid')} ✓", "callback_data": "buy_pts_paid", "icon_custom_emoji_id": EM["fire"], "style": "success"}],
        [{"text": f"{sc('cancel')}", "callback_data": "back_main", "icon_custom_emoji_id": EM["lock"], "style": "danger"}],
    ]}

def kb_admin_payment(uid: int, uname: str) -> dict:
    return {"inline_keyboard": [
        [
            {"text": f"✅ {sc('accept')}", "callback_data": f"pay_accept_{uid}", "style": "success"},
            {"text": f"❌ {sc('decline')}", "callback_data": f"pay_decline_{uid}", "style": "danger"},
        ]
    ]}

def kb_user_confirm_vps() -> dict:
    return {"inline_keyboard": [[
        {"text": f"{sc('yes, claim vps')}", "callback_data": "user_vps_yes", "icon_custom_emoji_id": EM["check"], "style": "success"},
        {"text": f"{sc('cancel')}",          "callback_data": "back_main", "icon_custom_emoji_id": EM["fire"],    "style": "danger"},
    ]]}

def kb_adm_back() -> dict:
    return {"inline_keyboard": [[
        {"text": f"{sc('admin panel')}", "callback_data": "adm_back", "icon_custom_emoji_id": EM["fire"], "style": "primary"}
    ]]}

# ─────────────────────────────────────────
#  FSM
# ─────────────────────────────────────────
class S(StatesGroup):
    broadcast          = State()
    create_vps_username = State()
    create_vps_password = State()
    give_credit_user   = State()
    give_credit_amt    = State()
    remove_credit_user = State()
    remove_credit_amt  = State()
    give_admin_user    = State()
    remove_admin_user  = State()
    add_fj             = State()
    remove_fj          = State()
    set_vps_cost       = State()
    buy_pts_proof      = State()
    decline_reason     = State()
    redeem_code        = State()
    redeem_credits     = State()
    redeem_limit       = State()
    delete_redeem      = State()
    srv_ip             = State()
    srv_port           = State()
    srv_user           = State()
    srv_auth           = State()

# ─────────────────────────────────────────
#  DB
# ─────────────────────────────────────────
async def db_get(db, uid):
    import time
    cached = _USER_CACHE.get(uid)
    if cached:
        doc, ts = cached
        if time.time() - ts < _CACHE_TTL:
            return doc
    doc = await db.users.find_one({"user_id": uid})
    if doc:
        _USER_CACHE[uid] = (doc, time.time())
    return doc

def cache_invalidate(uid):
    _USER_CACHE.pop(uid, None)
async def db_all(db):          return await db.users.find().to_list(None)
async def db_count(db):        return await db.users.count_documents({})
async def db_lb(db):           return await db.users.find().sort("referral_count", -1).limit(5).to_list(5)

async def db_create(db, uid, uname, ref=None):
    if await db_get(db, uid): return False
    await db.users.insert_one({
        "user_id": uid, "username": uname or str(uid),
        "credits": 0, "points": 0, "vps_list": [],
        "referred_by": ref, "referral_count": 0,
        "ref_credited": False,  # credit pending until force join passed
        "is_admin": uid in ADMIN_IDS,
        "joined_at": datetime.now(timezone.utc),
    })
    cache_invalidate(uid)
    return True  # new user — ref credited later on check_join

async def db_credit_ref(db, uid):
    """credit referral to referrer — called after user passes force join"""
    user = await db_get(db, uid)
    if not user: return None
    if user.get("ref_credited", False): return None  # already credited
    ref = user.get("referred_by")
    if not ref: return None
    await db.users.update_one({"user_id": uid}, {"$set": {"ref_credited": True}})
    await db.users.update_one({"user_id": ref}, {"$inc": {"points": 1, "referral_count": 1}})
    cache_invalidate(uid)
    cache_invalidate(ref)
    return ref  # return referrer id

async def db_assign_direct(db, uid, vps, cost=None):
    """push a freshly ssh-provisioned vps into the user's vps_list and deduct points"""
    if cost is None: cost = REFS_NEEDED
    vps["assigned_at"] = datetime.now(timezone.utc)
    await db.users.update_one({"user_id": uid}, {"$push": {"vps_list": vps}, "$inc": {"points": -cost}})
    cache_invalidate(uid)

async def db_set_admin(db, uid, val):
    await db.users.update_one({"user_id": uid}, {"$set": {"is_admin": val}})
    cache_invalidate(uid)
    if val and uid not in ADMIN_IDS: ADMIN_IDS.append(uid)
    elif not val and uid in ADMIN_IDS: ADMIN_IDS.remove(uid)

async def db_credit(db, uid, amt):
    await db.users.update_one({"user_id": uid}, {"$inc": {"points": amt}})

async def db_reserve_points(db, uid, cost):
    """atomically deduct points only if balance is enough (no negative balance / double-spend)"""
    r = await db.users.update_one({"user_id": uid, "points": {"$gte": cost}}, {"$inc": {"points": -cost}})
    cache_invalidate(uid)
    return r.modified_count == 1

async def db_redeem_code(db, code, uid):
    """Atomically redeem a code once per user and only while slots remain."""
    code = code.strip().upper()
    result = await db.redeem_codes.update_one(
        {"code": code, "remaining_users": {"$gt": 0}, "redeemed_by": {"$ne": uid}},
        {"$inc": {"remaining_users": -1, "redeemed_count": 1}, "$addToSet": {"redeemed_by": uid}},
    )
    if result.modified_count == 1:
        doc = await db.redeem_codes.find_one({"code": code}, {"credits": 1, "remaining_users": 1})
        await db_credit(db, uid, int(doc.get("credits", 0)))
        cache_invalidate(uid)
        return {"status": "redeemed", "credits": int(doc.get("credits", 0)), "remaining": int(doc.get("remaining_users", 0))}
    doc = await db.redeem_codes.find_one({"code": code}, {"remaining_users": 1, "redeemed_by": 1})
    if not doc:
        return {"status": "invalid"}
    if uid in doc.get("redeemed_by", []):
        return {"status": "used"}
    return {"status": "full"}

async def db_log(db, text, actor=None):
    await db.logs.insert_one({"text": text, "actor_id": actor, "timestamp": datetime.now(timezone.utc)})

# ─── PERSISTENT CONFIG (mongo) ───────────
async def cfg_load(db):
    """load FORCE_CHANNELS + MAINTENANCE + REFS_NEEDED from mongo on startup"""
    global FORCE_CHANNELS, MAINTENANCE, REFS_NEEDED
    doc = await db.config.find_one({"key": "bot_config"})
    if doc:
        FORCE_CHANNELS[:] = doc.get("force_channels", FORCE_CHANNELS)
        globals()["MAINTENANCE"] = doc.get("maintenance", False)
        globals()["REFS_NEEDED"] = doc.get("refs_needed", REFS_NEEDED)

async def cfg_save(db):
    """persist FORCE_CHANNELS + MAINTENANCE + REFS_NEEDED to mongo"""
    await db.config.update_one(
        {"key": "bot_config"},
        {"$set": {"force_channels": FORCE_CHANNELS, "maintenance": MAINTENANCE, "refs_needed": REFS_NEEDED}},
        upsert=True,
    )

# ─────────────────────────────────────────
#  UTILS
# ─────────────────────────────────────────
async def force_check(bot, uid, db=None):
    if uid in ADMIN_IDS:
        return []  # admins bypass force join
    from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
    out = []
    # check public channels only
    for ch in FORCE_CHANNELS:
        try:
            m = await bot.get_chat_member(f"@{ch}", uid)
            if isinstance(m, (ChatMemberLeft, ChatMemberBanned, ChatMemberRestricted)):
                out.append(ch)
        except TelegramForbiddenError:
            pass  # bot not admin — skip
        except TelegramBadRequest:
            out.append(ch)
        except:
            pass  # any other error — skip, dont block
    # private channels — check mongo verified record (survives restart)
    for chat_id, invite_link in PRIVATE_CHANNELS.items():
        if db is not None:
            rec = await db.force_join_verified.find_one({"user_id": uid, "chats": chat_id})
            if rec:
                continue  # verified via join request — pass
        try:
            m = await bot.get_chat_member(chat_id, uid)
            if isinstance(m, (ChatMemberLeft, ChatMemberBanned, ChatMemberRestricted)):
                out.append(f"__private__{chat_id}")
        except TelegramForbiddenError:
            out.append(f"__private__{chat_id}__noverify")
        except Exception:
            pass
    return out

async def log_ch(bot, text):
    try: await bot.send_message(LOG_CHANNEL, text, parse_mode="HTML")
    except: pass

async def send_welcome(bot, chat_id, caption, markup):
    global WELCOME_VIDEO_FILE_ID
    # spoiler video
    if WELCOME_VIDEO_FILE_ID:
        try:
            await bot.send_video(chat_id, WELCOME_VIDEO_FILE_ID,
                caption=caption, reply_markup=markup, parse_mode="HTML",
                has_spoiler=True)
            return
        except: WELCOME_VIDEO_FILE_ID = None
    try:
        sent = await bot.send_video(chat_id, WELCOME_VIDEO_URL,
            caption=caption, reply_markup=markup, parse_mode="HTML",
            has_spoiler=True)
        if sent.video:
            WELCOME_VIDEO_FILE_ID = sent.video.file_id
            logging.info(f"[VIDEO] cached: {WELCOME_VIDEO_FILE_ID[:20]}")
        return
    except Exception as ex:
        logging.warning(f"[VIDEO] fallback text: {ex}")
    await bot.send_message(chat_id, caption, reply_markup=markup, parse_mode="HTML")

async def safe_edit(cb: CallbackQuery, text: str, markup: dict):
    try:
        await cb.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception as ex:
        if "not modified" in str(ex).lower():
            await cb.answer(); return
        try: await cb.message.delete()
        except: pass
        await cb.message.answer(text, reply_markup=markup, parse_mode="HTML")

# ─────────────────────────────────────────
#  VPS DELIVERY TEXT
# ─────────────────────────────────────────
def vps_delivery_text(uname: str, vd: dict, pts_remaining: int = 0, vps_remaining: int = 0, plan: str = None) -> str:
    pm = PLAN_META.get(plan, PLAN_META["basic"]) if plan else None
    plan_line = (f'<tg-emoji emoji-id="{EM[pm["em"]]}">💎</tg-emoji> <b>{sc("plan")}: {sc(plan)}</b>\n' if pm else "")
    ssh_cmd = f"ssh -p {vd['port']} {vd['username']}@{vd['ip']}"
    return (
        f"<blockquote>"
        f'<tg-emoji emoji-id="{EM["disc"]}">💿</tg-emoji> '
        f"{plan_line}"
        f"<b>{sc('vps claimed successfully!')}</b>\n\n"
        f"{loops(22)}\n"
        f'<tg-emoji emoji-id="{EM["butterfly"]}">🦋</tg-emoji> '
        f"<b>{sc('vps details')}</b>\n\n"
        f'<tg-emoji emoji-id="{EM["sparkle"]}">✨</tg-emoji>'
        f"<b>{sc('ssh host')} :</b> <code>{ssh_cmd}</code>\n"
        f'<tg-emoji emoji-id="{EM["user"]}">👤</tg-emoji>'
        f"<b>{sc('username')} :</b> <code>{vd['username']}</code>\n"
        f'<tg-emoji emoji-id="{EM["smile"]}">😀</tg-emoji>'
        f"<b>{sc('password')} :</b> <tg-spoiler><code>{vd['password']}</code></tg-spoiler>\n"
        f'<tg-emoji emoji-id="{EM["gift"]}">🎁</tg-emoji>'
        f"<b>{sc('ip address')} :</b> <code>{vd['ip']}</code>\n"
        f'<tg-emoji emoji-id="{EM["love"]}">🥰</tg-emoji>'
        f"<b>{sc('ssh port')} :</b> <code>{vd['port']}</code>\n\n"
        f"{e('active')} {sc('status')} : <b>{sc('active')}</b> 🐺\n"
        f"{e('ssh')} {sc('access')} : <b>{sc('ssh enabled')}</b>\n"
        f"{e('gem')} {sc('points remaining')} : <code>{pts_remaining}</code>\n\n"
        f"{e('deploy')} <b>{sc('your vps is ready to use!')}</b>\n\n"
        f"<i>{sc('deploy bots')} • {sc('host apps')} • {sc('run scripts')}</i>\n\n"
        f"{e('sparkle')} <b>{sc('thank you for using our vps service!')}</b>"
        f"</blockquote>"
    )


# ─────────────────────────────────────────
#  VPS PLANS — /start screen + plans button
# ─────────────────────────────────────────
def vps_plans_text() -> str:
    return (
        f"<blockquote>"
        f"{e('crown')} <b>{sc('vps plans')}</b>\n\n"
        f"╭─ <b>{sc('basic')}</b>\n"
        f"│ {e('gift2')} {sc('required points')} → <code>{plan_cost('basic')}</code> {sc('pts')}\n"
        f"│ {e('bolt')} 1 cpu · {e('brain')} 1 gb ram\n"
        f"│ {e('kbd')} 30 gb ssd · {e('lock2')} {sc('non-root')}\n"
        f"╰──────────────\n"
        f"╭─ <b>{sc('standard')}</b>\n"
        f"│ {e('gift2')} {sc('required points')} → <code>{plan_cost('standard')}</code> {sc('pts')}\n"
        f"│ {e('bolt2')} 2 cpu · {e('brain')} 3 gb ram\n"
        f"│ {e('kbd')} 80 gb ssd · {e('lock2')} {sc('non-root')}\n"
        f"╰──────────────\n"
        f"╭─ <b>{sc('pro')}</b>\n"
        f"│ {e('sword2')} {sc('required points')} → <code>{plan_cost('pro')}</code> {sc('pts')}\n"
        f"│ {e('bolt2')} 4 cpu · {e('brain')} 6 gb ram\n"
        f"│ {e('kbd')} 500 gb ssd · {e('lock2')} {sc('non-root')}\n"
        f"╰──────────────\n"
        f"╭─ {e('diamond2')} <b>{sc('premium')}</b>\n"
        f"│ {e('check2')} {sc('required points')} → <code>{plan_cost('premium')}</code> {sc('pts')}\n"
        f"│ {e('bolt2')} 8 cpu · {e('brain')} 12 gb ram\n"
        f"│ {e('kbd')} 900 gb ssd · {e('lock2')} {sc('non-root')}\n"
        f"╰──────────────\n\n"
        f"{e('rocket2')} <b>{sc('pick your power')}</b>\n"
        f"{e('heart2')} {sc('buy')} • {sc('deploy')} • {sc('run')}\n\n"
        f"{e('phone')} <b>{sc('ready to deploy!')}</b>"
        f"</blockquote>"
    )

# ─────────────────────────────────────────
#  HOME TEXTS
# ─────────────────────────────────────────
async def get_bot_info(bot):
    global _BOT_INFO
    if not _BOT_INFO:
        _BOT_INFO = await bot.get_me()
    return _BOT_INFO

async def build_home_text(bot, db, uid, uname):
    user, bi = await asyncio.gather(db_get(db, uid), get_bot_info(bot))
    pts     = user["points"] if user else 0
    refs    = user["referral_count"] if user else 0
    vps_got = len(user["vps_list"]) if user else 0
    bar     = progress_bar(pts, REFS_NEEDED)
    rl      = f"https://t.me/{bi.username}?start=ref_{uid}"
    return (
        f"<blockquote>"
        f"{e('rocket')} <b>{sc('vps bot')}</b>\n"
        f"{e('star')} <b>{sc('get free vps → refer 10 friends!')}</b>\n\n"
        f"{e('user')} {sc('name')}: <b>{uname}</b>\n"
        f"{e('gem')} {sc('user id')}: <code>{uid}</code>\n"
        f"{e('fire')} {sc('points')}: <code>{pts}/{REFS_NEEDED}</code> | {sc('refs')}: <code>{refs}</code>\n"
        f"{e('vps')} {sc('vps claimed')}: <code>{vps_got}</code>\n\n"
        f"{e('thunder')} {sc('vps unlock progress')}:\n"
        f"<code>{bar}</code>\n\n"
        f"{e('key')} {sc('ref link')}:\n<code>{rl}</code>"
        f"</blockquote>"
    )

async def build_welcome_text(bot, db, uid, uname, nj):
    user, bi = await asyncio.gather(db_get(db, uid), get_bot_info(bot))
    pts   = user.get("points", 0) if user else 0
    refs  = user["referral_count"] if user else 0
    bar   = progress_bar(pts, REFS_NEEDED)
    rl    = f"https://t.me/{bi.username}?start=ref_{uid}"
    chs   = "\n".join([f"  {e('thunder')} @{ch}" for ch in nj])
    return (
        f"<blockquote>"
        f"{e('crown')} <b>{sc('welcome to vps bot!')}</b>\n\n"
        f"{e('rocket')} <b>{sc('get free vps with 10 referrals!')}</b>\n\n"
        f"{e('gem')} {sc('user id')}: <code>{uid}</code>\n"
        f"{e('fire')} {sc('points')}: <code>{pts}/{REFS_NEEDED}</code> | {sc('refs')}: <code>{refs}</code>\n"
        f"{e('vps')} {sc('vps')}: <code>{len(user['vps_list']) if user else 0}</code>\n\n"
        f"{e('thunder')} {sc('progress')}:\n<code>{bar}</code>\n\n"
        f"{e('key')} {sc('ref link')}:\n<code>{rl}</code>\n\n"
        f"{e('shield')} {sc('join all channels below to continue')}"
        f"</blockquote>"
    )

async def home(src, bot, db, uid, uname):
    global WELCOME_VIDEO_FILE_ID
    text    = await build_home_text(bot, db, uid, uname)
    chat_id = src.chat.id if isinstance(src, Message) else src.message.chat.id
    if WELCOME_VIDEO_FILE_ID:
        try:
            await src.bot.send_video(chat_id, WELCOME_VIDEO_FILE_ID,
                caption=text, reply_markup=kb_main(), parse_mode="HTML", has_spoiler=True)
            return
        except: WELCOME_VIDEO_FILE_ID = None
    try:
        sent = await src.bot.send_video(chat_id, WELCOME_VIDEO_URL,
            caption=text, reply_markup=kb_main(), parse_mode="HTML", has_spoiler=True)
        if sent.video: WELCOME_VIDEO_FILE_ID = sent.video.file_id
        return
    except: pass
    fn = src.answer if isinstance(src, Message) else src.message.answer
    await fn(text, reply_markup=kb_main(), parse_mode="HTML")
    # vps plans right on home screen
    try:
        await src.bot.send_message(chat_id, vps_plans_text(), parse_mode="HTML")
    except: pass

# ─────────────────────────────────────────
#  ROUTER
# ─────────────────────────────────────────
def adm(fn):
    async def w(cb: CallbackQuery, *a, **kw):
        if cb.from_user.id not in ADMIN_IDS:
            await cb.answer("denied", show_alert=True); return
        # pass db, bot, state etc through kwargs
        return await fn(cb, *a, **kw)
    w.__name__ = fn.__name__
    # preserve signature so aiogram injects db properly
    import inspect
    w.__wrapped__ = fn
    return w

router = Router()

# ─── CHAT JOIN REQUEST HANDLER ───────────
# when user sends join request to private channel → auto verify + auto approve
@router.chat_join_request()
async def on_join_request(event, bot: Bot, db):
    uid = event.from_user.id
    chat_id = event.chat.id
    # save to mongo — survives restart
    await db.force_join_verified.update_one(
        {"user_id": uid},
        {"$addToSet": {"chats": chat_id}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        upsert=True
    )
    logging.info(f"[JOIN_REQUEST] verified uid={uid} chat={chat_id}")

# ─── GROUP TRACKER (for broadcast to groups) ──
@router.my_chat_member()
async def track_groups(event: ChatMemberUpdated, db):
    if event.chat.type not in ("group", "supergroup"):
        return
    if event.new_chat_member.status in ("member", "administrator"):
        await db.groups.update_one(
            {"chat_id": event.chat.id},
            {"$set": {"chat_id": event.chat.id, "title": event.chat.title or "",
                      "added_at": datetime.now(timezone.utc)}},
            upsert=True)
        logging.info(f"[GROUP] tracked: {event.chat.title} ({event.chat.id})")
    elif event.new_chat_member.status in ("left", "kicked"):
        await db.groups.delete_one({"chat_id": event.chat.id})
        logging.info(f"[GROUP] removed: {event.chat.id}")

# /broadcast — with args = direct broadcast, without args = prompt mode
@router.message(Command("broadcast"))
async def cmd_broadcast(msg: Message, bot: Bot, db, state: FSMContext, command: Command):
    if msg.from_user.id not in ADMIN_IDS:
        return
    await state.clear()  # clear any existing state first
    if command.args:  # /broadcast hello world → direct broadcast
        await _do_broadcast(msg, bot, db, text_override=command.args)
        return
    await state.set_state(S.broadcast)
    await msg.answer(
        f"<blockquote>"
        f"{e('rocket')} <b>{sc('broadcast')}</b>\n\n"
        f"{e('star')} {sc('send the message you want to broadcast')}\n"
        f"{e('key')} {sc('or reply to any message')}\n\n"
        f"{e('fire')} {sc('it will be sent to all users')}\n"
        f"{e('lock')} {sc('send /cancel anytime to abort')}"
        f"</blockquote>",
        reply_markup=kb_cancel(), parse_mode="HTML")

# ─────────────────────────────────────────
#  /cancel — cancel any pending FSM state (broadcast, add vps, give pts, etc.)
# ─────────────────────────────────────────
@router.message(Command("cancel"))
async def cmd_cancel(msg: Message, db, state: FSMContext):
    cur = await state.get_state()
    # also clear any pay_pending "waiting for amount" flow — not FSM-based, stored in mongo
    pending = await db.pay_pending.find_one({"admin_id": msg.from_user.id})
    if pending:
        await db.pay_pending.delete_one({"admin_id": msg.from_user.id})

    if cur is None and not pending:
        await msg.answer(
            f"<blockquote>{e('lock')} {sc('nothing to cancel.')}</blockquote>",
            parse_mode="HTML")
        return

    await state.clear()
    await msg.answer(
        f"<blockquote>{e('lock')} <b>{sc('cancelled.')}</b>\n\n"
        f"{e('check')} {sc('any pending action (broadcast, add vps, etc.) has been aborted.')}"
        f"</blockquote>",
        parse_mode="HTML")

# ─────────────────────────────────────────
#  /broadcastbtn — broadcast with an inline button
# ─────────────────────────────────────────
BROADCASTBTN_USAGE = (
    f"<blockquote>"
    f'{e("star")} <b>{sc("reply to the message you want to broadcast.")}</b>\n\n'
    f"{sc('use')}\n"
    f"<code>/broadcastbtn Button Text | https://example.com | success | EMOJI_ID</code>\n\n"
    f"{e('disc')} {sc('styles')}: <b>primary</b> ({sc('blue')}), <b>success</b> ({sc('green')}), <b>danger</b> ({sc('red')})\n"
    f"{e('key')} {sc('style and premium emoji id are optional.')}"
    f"</blockquote>"
)

@router.message(Command("broadcastbtn"))
async def cmd_broadcastbtn(msg: Message, bot: Bot, db, state: FSMContext, command: Command):
    if msg.from_user.id not in ADMIN_IDS:
        return
    await state.clear()

    if not msg.reply_to_message or msg.reply_to_message.from_user.is_bot:
        await msg.answer(BROADCASTBTN_USAGE, parse_mode="HTML")
        return

    if not command.args or "|" not in command.args:
        await msg.answer(BROADCASTBTN_USAGE, parse_mode="HTML")
        return

    parts = [p.strip() for p in command.args.split("|")]
    btn_text = parts[0] if len(parts) > 0 and parts[0] else ""
    url      = parts[1] if len(parts) > 1 and parts[1] else ""
    style    = parts[2] if len(parts) > 2 and parts[2] in ("primary", "success", "danger") else "primary"
    emoji_id = parts[3] if len(parts) > 3 and parts[3].isdigit() else None

    if not btn_text or not url:
        await msg.answer(BROADCASTBTN_USAGE, parse_mode="HTML")
        return

    btn = {"text": btn_text, "url": url, "style": style}
    if emoji_id:
        btn["icon_custom_emoji_id"] = emoji_id
    markup = {"inline_keyboard": [[btn]]}

    await _do_broadcast(msg, bot, db, target_override=msg.reply_to_message, markup=markup)

# ─────────────────────────────────────────

# /fj — admin force join list
@router.message(Command("fj"))
async def cmd_fj(msg: Message, db):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer(f"<blockquote>{e('lock')} {sc('access denied.')}</blockquote>", parse_mode="HTML"); return
    if not FORCE_CHANNELS:
        text = f"<blockquote>{e('thunder')} {sc('no force join channels.')}</blockquote>"
    else:
        lines = [f"<blockquote>{e('thunder')} <b>{sc('force join channels')}</b>\n"]
        for i, ch in enumerate(FORCE_CHANNELS, 1):
            lines.append(f"\n{i}. @{ch} → https://t.me/{ch}")
        lines.append("</blockquote>")
        text = "".join(lines)
    await msg.answer(text, parse_mode="HTML")

# /start
@router.message(CommandStart())
async def cmd_start(msg: Message, bot: Bot, db, command: CommandStart):
    uid   = msg.from_user.id
    uname = msg.from_user.username or msg.from_user.first_name or str(uid)
    ref   = None
    redeem_code = None
    if command.args and command.args.startswith("ref_"):
        try:
            r = int(command.args[4:])
            if r != uid: ref = r
        except: pass
    elif command.args and command.args.startswith("redeem_"):
        redeem_code = command.args[7:].strip().upper()

    is_new = await db_create(db, uid, uname, ref)

    if redeem_code:
        result = await db_redeem_code(db, redeem_code, uid)
        if result["status"] == "redeemed":
            await msg.answer(
                f"<blockquote>{e('gift')} <b>{sc('redeem successful!')}</b>\n\n"
                f"{e('gem')} +<code>{result['credits']}</code> {sc('points added')}\n"
                f"{e('star')} {sc('slots remaining')}: <code>{result['remaining']}</code></blockquote>",
                parse_mode="HTML")
        elif result["status"] == "used":
            await msg.answer(f"<blockquote>{e('lock')} {sc('you already used this redeem link.')}</blockquote>", parse_mode="HTML")
        elif result["status"] == "full":
            await msg.answer(f"<blockquote>{e('lock')} {sc('this redeem link has reached its user limit.')}</blockquote>", parse_mode="HTML")
        else:
            await msg.answer(f"<blockquote>{e('lock')} {sc('invalid redeem code.')}</blockquote>", parse_mode="HTML")

    # log new user
    if is_new:
        await log_ch(bot,
            f"{e('star')} <b>{sc('new user joined!')}</b>\n"
            f"{e('user')} @{uname} (<code>{uid}</code>)\n"
            f"{e('key')} {sc('joined at')}: {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC"
            + (f"\n{e('fire')} {sc('referred by')}: <code>{ref}</code>" if ref else "")
        )
        # welcome effect to new user (fire animation)
        try:
            await bot.send_message(uid,
                f"<blockquote>{e('rocket')} <b>{sc('welcome!')}</b> 🎉</blockquote>",
                parse_mode="HTML", message_effect_id=EFFECT_FIRE)
        except: pass

    # ref credit happens after force join passed in check_join — one time only via ref_credited flag

    nj = await force_check(bot, uid, db)
    if nj:
        caption = await build_welcome_text(bot, db, uid, uname, nj)
        await send_welcome(bot, uid, caption, kb_force_join(nj))
        return
    await home(msg, bot, db, uid, uname)

@router.callback_query(F.data == "check_join")
async def cb_check_join(cb: CallbackQuery, bot: Bot, db):
    uid   = cb.from_user.id
    uname = cb.from_user.username or cb.from_user.first_name or str(uid)
    nj    = await force_check(bot, uid, db)
    # filter out noverify channels — can't check, trust user
    real_nj = [ch for ch in nj if "__noverify" not in str(ch)]
    if real_nj:
        await cb.answer(sc("still not joined all channels!"), show_alert=True)
        return

    # credit referral NOW — user has passed force join
    ref_id = await db_credit_ref(db, uid)
    if ref_id:
        ru = await db_get(db, ref_id)
        if ru:
            rc  = ru.get("referral_count", 0)
            bar = progress_bar(rc, REFS_NEEDED)
            try:
                await bot.send_message(ref_id,
                    f"<blockquote>"
                    f"{e('star')} <b>{sc('new referral!')}</b>\n"
                    f"{e('fire')} @{uname} {sc('joined & verified')}\n"
                    f"{e('gem')} {sc('points now')}: <code>{rc}</code>/{REFS_NEEDED}\n"
                    f"<code>{bar}</code>"
                    f"</blockquote>", parse_mode="HTML",
                    message_effect_id=EFFECT_FIRE)
            except: pass

    await cb.message.delete()
    await home(cb, bot, db, uid, uname)

@router.callback_query(F.data == "back_main")
async def cb_back(cb: CallbackQuery, bot: Bot, db):
    uid   = cb.from_user.id
    uname = cb.from_user.username or cb.from_user.first_name or str(uid)
    await cb.message.delete()
    await home(cb, bot, db, uid, uname)

@router.callback_query(F.data == "cancel_state")
async def cb_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(cb, f"<blockquote>{e('lock')} {sc('cancelled.')}</blockquote>", {})

# profile
@router.callback_query(F.data == "my_profile")
async def cb_profile(cb: CallbackQuery, bot: Bot, db):
    await cb.answer()
    uid       = cb.from_user.id
    user, bi  = await asyncio.gather(db_get(db, uid), get_bot_info(bot))
    rl        = f"https://t.me/{bi.username}?start=ref_{uid}"
    pts  = user.get("points", 0)
    refs = user["referral_count"]
    bar  = progress_bar(pts, REFS_NEEDED)
    await safe_edit(cb,
        f"<blockquote>"
        f"{e('crown')} <b>{sc('my profile')}</b>\n\n"
        f"{e('user')} @{user['username']}\n"
        f"{e('gem')} id: <code>{uid}</code>\n"
        f"{e('fire')} {sc('points')}: <code>{pts}/{REFS_NEEDED}</code>\n"
        f"{e('star')} {sc('referrals')}: <code>{refs}</code>\n"
        f"{e('vps')} {sc('vps count')}: <code>{len(user['vps_list'])}</code>\n\n"
        f"{e('thunder')} {sc('vps unlock progress')}:\n<code>{bar}</code>\n\n"
        f"{e('key')} {sc('ref link')}:\n<code>{rl}</code>"
        f"</blockquote>",
        kb_back())

# my vps
@router.callback_query(F.data == "my_vps")
async def cb_my_vps(cb: CallbackQuery, db):
    await cb.answer()
    user = await db_get(db, cb.from_user.id)
    if not user or not user["vps_list"]:
        text = (
            f"<blockquote>"
            f"{e('shield')} <b>{sc('my vps')}</b>\n\n"
            f"{e('lock')} {sc('no vps yet.')}\n\n"
            f"{e('rocket')} {sc('tap create vps to get one!')}"
            f"</blockquote>"
        )
    else:
        lines = [
            f"<blockquote>{e('shield')} <b>{sc('my vps')}</b>\n"
        ]
        for i, v in enumerate(user["vps_list"], 1):
            lines.append(
                f"\n{loops(10)}\n"
                f"{e('butterfly')} <b>#{i}</b>\n"
                f"{e('sparkle')}<b>ssh:</b> <code>ssh -p {v.get('port','22')} {v.get('username','root')}@{v.get('ip','—')}</code>\n"
                f"{e('user')}<b>user:</b> <code>{v.get('username','—')}</code>\n"
                f"{e('smile')}<b>pass:</b> <tg-spoiler><code>{v.get('password','—')}</code></tg-spoiler>\n"
                f"{e('gift')}<b>ip:</b> <code>{v.get('ip','—')}</code>\n"
                f"{e('love')}<b>port:</b> <code>{v.get('port','22')}</code>\n"
                f"{e('active')} {sc('active')} 🐺"
            )
        lines.append("\n</blockquote>")
        text = "".join(lines)
    await safe_edit(cb, text, kb_back())


# vps plans
@router.callback_query(F.data == "vps_plans")
async def cb_vps_plans(cb: CallbackQuery):
    await cb.answer()
    await safe_edit(cb, vps_plans_text(), kb_back())

# create vps — plan picker screen
@router.callback_query(F.data == "create_vps")
async def cb_create_vps(cb: CallbackQuery, bot: Bot, db):
    uid   = cb.from_user.id
    user  = await db_get(db, uid)
    pts   = user["points"] if user else 0
    refs  = user["referral_count"] if user else 0

    text = (vps_plans_text().replace("</blockquote>", "")
            + f"\n{e('gem')} {sc('your points')}: <code>{pts}</code>   |   {e('star')} {sc('refs')}: <code>{refs}</code>\n\n"
            + f"{e('diamond')} {sc('pick a plan below')}</blockquote>")
    await safe_edit(cb, text, kb_plan_picker())
# user picks a plan → ask for a username to provision a REAL ssh user on this host
@router.callback_query(F.data.startswith("pickplan_"))
async def cb_pick_plan(cb: CallbackQuery, bot: Bot, db, state: FSMContext):
    plan = cb.data.replace("pickplan_", "")
    if plan not in PLAN_META:
        await cb.answer("invalid plan", show_alert=True); return
    uid   = cb.from_user.id
    user  = await db_get(db, uid)
    pts   = user["points"] if user else 0
    cost  = plan_cost(plan)

    if pts < cost:
        await safe_edit(cb,
            f"<blockquote>"
            f"{e('lock')} <b>{sc('not enough points for')} {sc(plan)}!</b>\n\n"
            f"{e(PLAN_META[plan]['em'])} {sc(plan)} {sc('costs')} <code>{cost}</code> {sc('points')}\n"
            f"{e('gem')} {sc('your points')}: <code>{pts}</code>\n\n"
            f"{e('key')} {sc('refer friends or buy points')}"
            f"</blockquote>",
            kb_back())
        return

    await state.set_state(S.create_vps_username)
    await state.update_data(plan=plan)
    await safe_edit(cb,
        f"<blockquote>"
        f"{e(PLAN_META[plan]['em'])} <b>{sc(plan)} — {sc('enter a username')}</b>\n\n"
        f"{e('user')} {sc('send a username for your vps')}\n"
        f"{e('key')} {sc('lowercase letters, digits, _ - only · must start with a letter · max 32 chars')}\n"
        f"{e('fire')} {sc('cost')}: <code>{cost}</code> {sc('points')}\n\n"
        f"{e('lock')} {sc('send /cancel to abort')}"
        f"</blockquote>",
        kb_cancel())

# in-memory lock to prevent double tap / double-submit
_vps_claiming = set()

# user sends the desired username → provision a REAL linux ssh user on this host, ip auto-fetched
@router.message(S.create_vps_username)
async def vps_username_received(msg: Message, bot: Bot, db, state: FSMContext):
    data = await state.get_data()
    plan = data.get("plan")
    if plan not in PLAN_META:
        await state.clear()
        await msg.answer(
            f"<blockquote>{e('lock')} {sc('session expired, start again from create vps')}</blockquote>",
            parse_mode="HTML", reply_markup=kb_back())
        return

    username = (msg.text or "").strip().lower()
    try:
        validate_username(username)
    except ValueError as err:
        await state.clear()
        await msg.answer(
            f"<blockquote>{e('lock')} {sc('invalid username')}: {html.escape(str(err))}</blockquote>",
            parse_mode="HTML", reply_markup=kb_back())
        return

    await state.set_state(S.create_vps_password)
    await state.update_data(plan=plan, username=username)
    await msg.answer(
        f"<blockquote>{e('key')} <b>{sc('now send your own password')}</b>\n\n"
        f"{sc('8-32 chars · no spaces · or send')} <code>auto</code> {sc('for a random strong password')}\n\n"
        f"{e('lock')} {sc('send /cancel to abort')}</blockquote>",
        parse_mode="HTML", reply_markup=kb_cancel())

def validate_password(pw: str):
    if not (8 <= len(pw) <= 32):
        raise ValueError("password 8 se 32 characters ka hona chahiye")
    if any((not ch.isascii()) or (not ch.isprintable()) or ch.isspace() for ch in pw):
        raise ValueError("password mein space ya special unicode characters allowed nahi")

@router.message(S.create_vps_password)
async def vps_password_received(msg: Message, bot: Bot, db, state: FSMContext):
    data     = await state.get_data()
    plan     = data.get("plan")
    username = data.get("username")
    if plan not in PLAN_META or not username:
        await state.clear()
        await msg.answer(
            f"<blockquote>{e('lock')} {sc('session expired, start again from create vps')}</blockquote>",
            parse_mode="HTML", reply_markup=kb_back())
        return

    raw = (msg.text or "").strip()
    password = None
    if raw.lower() != "auto":
        try:
            validate_password(raw)
        except ValueError as err:
            # stay in state so user can retry
            await msg.answer(
                f"<blockquote>{e('lock')} {sc('invalid password')}: {html.escape(str(err))}\n{sc('try again or send')} <code>auto</code></blockquote>",
                parse_mode="HTML")
            return
        password = raw
        try: await msg.delete()  # remove user's password message from chat
        except Exception: pass
    await state.clear()

    uid   = msg.from_user.id
    uname = msg.from_user.username or msg.from_user.first_name or str(uid)

    if uid in _vps_claiming:
        await msg.answer(f"<blockquote>{e('lock')} {sc('already processing... wait')}</blockquote>", parse_mode="HTML")
        return
    _vps_claiming.add(uid)

    try:
        user = await db_get(db, uid)
        pts  = user["points"] if user else 0
        cost = plan_cost(plan)

        if pts < cost:
            await msg.answer(
                f"<blockquote>{e('lock')} {sc('not enough points anymore!')}</blockquote>",
                parse_mode="HTML", reply_markup=kb_back())
            return

        if not await db_reserve_points(db, uid, cost):
            await msg.answer(
                f"<blockquote>{e('lock')} {sc('not enough points anymore!')}</blockquote>",
                parse_mode="HTML", reply_markup=kb_back())
            return

        status_msg = await msg.answer(
            f"<blockquote>{e('rocket')} {sc('creating your vps... please wait')}</blockquote>",
            parse_mode="HTML")

        srv = await pick_server(db)
        if not srv:
            await db_credit(db, uid, cost); cache_invalidate(uid)  # refund reserved points
            await status_msg.edit_text(
                f"<blockquote>{e('lock')} <b>{sc('no server available right now')}</b>\n\n{sc('please contact support.')}</blockquote>",
                parse_mode="HTML", reply_markup=kb_back())
            return
        # blocking ssh calls → run off the event loop
        result = await asyncio.to_thread(create_ssh_user, srv, username, password)

        if not result["success"]:
            await db_credit(db, uid, cost); cache_invalidate(uid)  # refund reserved points
            await status_msg.edit_text(
                f"<blockquote>{e('lock')} <b>{sc('creation failed')}</b>\n\n{html.escape(str(result.get('error','unknown error')))}</blockquote>",
                parse_mode="HTML", reply_markup=kb_back())
            return

        vd = {
            "ip":        srv["ip"],
            "port":      str(srv["port"]),
            "username":  result["username"],
            "password":  result["password"],
            "ssh":       str(srv["port"]),
            "plan":      plan,
            "server_id": srv["sid"],
        }
        try:
            await db_assign_direct(db, uid, vd, 0)  # points already reserved above
            await db.servers.update_one({"sid": srv["sid"]}, {"$inc": {"vps_count": 1}})
        except Exception:
            await db_credit(db, uid, cost); cache_invalidate(uid)
            await asyncio.to_thread(delete_ssh_user, srv, result["username"])
            raise
        pts_after = pts - cost

        delivery = vps_delivery_text(uname, vd, pts_after, 0, plan=plan)
        try:
            await status_msg.delete()
        except: pass
        await bot.send_message(uid, delivery, parse_mode="HTML", reply_markup=kb_main(),
            message_effect_id=EFFECT_FIRE)
        text = await build_home_text(bot, db, uid, uname)
        await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb_main())

        await log_ch(bot,
            f"<blockquote>"
            f"{e('rocket')} <b>{sc('vps provisioned!')}</b>\n\n"
            f"{e(PLAN_META[plan]['em'])} {sc('plan')}: <b>{sc(plan)}</b>\n"
            f"{e('user')} @{uname} (<code>{uid}</code>)\n"
            f"{e('sparkle')} ssh: <code>ssh -p {vd['port']} {vd['username']}@{vd['ip']}</code>\n"
            f"{e('user')} user: <code>{vd['username']}</code>\n"
            f"{e('smile')} pass: <tg-spoiler><code>{vd['password']}</code></tg-spoiler>\n"
            f"{e('gift')} ip: <code>{vd['ip']}</code>\n"
            f"{e('gem')} pts after: <code>{pts_after}</code>\n"
            f"{e('clock')} {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC"
            f"</blockquote>"
        )
        await db_log(db, f"vps_ssh_created uid={uid} username={vd['username']} plan={plan}", uid)

    finally:
        _vps_claiming.discard(uid)

# vps cost change
@router.callback_query(F.data == "adm_set_cost")
async def adm_set_cost(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("denied", show_alert=True); return
    await state.set_state(S.set_vps_cost)
    await safe_edit(cb,
        f"<blockquote>"
        f"{e('gem')} <b>{sc('set vps cost')}</b>\n\n"
        f"{e('fire')} {sc('current cost')}: <code>{REFS_NEEDED}</code> {sc('points')}\n\n"
        f"{e('star')} {sc('send new cost (number)')}"
        f"</blockquote>",
        kb_cancel())

@router.message(S.set_vps_cost)
async def adm_set_cost_do(msg: Message, bot: Bot, db, state: FSMContext):
    await state.clear()
    try:
        new_cost = int(msg.text.strip())
        if new_cost < 1:
            await msg.answer(f"<blockquote>{e('lock')} {sc('minimum cost is 1')}</blockquote>", parse_mode="HTML"); return
        global REFS_NEEDED
        old_cost = REFS_NEEDED
        REFS_NEEDED = new_cost
        await cfg_save(db)
        await msg.answer(
            f"<blockquote>"
            f"{e('gem')} <b>{sc('vps cost updated!')}</b>\n\n"
            f"{e('lock')} {sc('old cost')}: <code>{old_cost}</code> {sc('pts')}\n"
            f"{e('rocket')} {sc('new cost')}: <code>{REFS_NEEDED}</code> {sc('pts')}"
            f"</blockquote>",
            parse_mode="HTML", reply_markup=kb_adm_back())
        await log_ch(bot, f"{e('gem')} vps cost changed: {old_cost} → {REFS_NEEDED} pts by <code>{msg.from_user.id}</code>")
    except ValueError:
        await msg.answer(f"<blockquote>{e('lock')} {sc('send a valid number')}</blockquote>", parse_mode="HTML")

# ─── BUY PTS FLOW ────────────────────────
@router.callback_query(F.data == "buy_pts")
async def cb_buy_pts(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await safe_edit(cb,
        f"<blockquote>"
        f"{e('star')} <b>{sc('buy pts')} — {sc('manual star payment')}</b>\n\n"
        f"{e('star')} 100 {sc('stars')}  =  {e('gem')} 100 {sc('pts')}\n"
        f"{e('star')} 200 {sc('stars')}  =  {e('gem')} 200 {sc('pts')}\n"
        f"{e('star')} 500 {sc('stars')}  =  {e('gem')} 500 {sc('pts')}\n\n"
        f"📨 {sc('send stars to')} : @flirts_x\n\n"
        f"{e('key')} {sc('after sending, tap')} {e('fire')} <b>{sc('i have paid')}</b> {sc('below.')}"
        f"</blockquote>",
        kb_buy_pts())

@router.callback_query(F.data == "buy_pts_paid")
async def cb_buy_pts_paid(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(S.buy_pts_proof)
    await safe_edit(cb,
        f"<blockquote>"
        f"{e('star')} <b>{sc('send screenshot')}</b>\n\n"
        f"{e('key')} {sc('send your payment screenshot now')}"
        f"</blockquote>",
        kb_cancel())

@router.message(S.buy_pts_proof)
async def buy_pts_proof_received(msg: Message, bot: Bot, db, state: FSMContext):
    await state.clear()
    uid   = msg.from_user.id
    uname = msg.from_user.username or str(uid)

    if not msg.photo and not msg.document:
        await msg.answer(
            f"<blockquote>{e('lock')} {sc('please send a screenshot/photo')}</blockquote>",
            parse_mode="HTML")
        await state.set_state(S.buy_pts_proof)
        return

    # forward screenshot to all admins
    for admin_id in ADMIN_IDS:
        try:
            await bot.forward_message(admin_id, msg.chat.id, msg.message_id)
            await bot.send_message(admin_id,
                f"<blockquote>"
                f"{e('star')} <b>{sc('payment request')}</b>\n\n"
                f"{e('user')} @{uname} (<code>{uid}</code>)\n"
                f"{e('gem')} {sc('review screenshot above and accept/decline')}"
                f"</blockquote>",
                parse_mode="HTML",
                reply_markup=kb_admin_payment(uid, uname))
        except: pass

    await msg.answer(
        f"<blockquote>"
        f"{e('check')} <b>{sc('payment request sent!')}</b>\n\n"
        f"{e('clock')} {sc('admin will review and add pts shortly')}"
        f"</blockquote>",
        parse_mode="HTML", reply_markup=kb_main())
    await db_log(db, f"pay_request uid={uid}", uid)

# ─── ADMIN ACCEPT/DECLINE PAYMENT ────────
@router.callback_query(F.data.startswith("pay_accept_"))
async def pay_accept(cb: CallbackQuery, bot: Bot, db):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("denied", show_alert=True); return
    uid = int(cb.data.replace("pay_accept_", ""))

    # ask how many pts to add
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(
        f"<blockquote>{e('gem')} {sc('how many pts to add for')} <code>{uid}</code>?\n{sc('reply with number (or /cancel)')}</blockquote>",
        parse_mode="HTML")
    # store pending accept
    await db.pay_pending.update_one(
        {"admin_id": cb.from_user.id},
        {"$set": {"target_uid": uid, "action": "accept"}},
        upsert=True)

@router.callback_query(F.data.startswith("pay_decline_"))
async def pay_decline_start(cb: CallbackQuery, bot: Bot, db, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("denied", show_alert=True); return
    uid = int(cb.data.replace("pay_decline_", ""))
    await state.set_state(S.decline_reason)
    await state.update_data(target_uid=uid)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(
        f"<blockquote>{e('lock')} {sc('send reason for declining')} <code>{uid}</code>:</blockquote>",
        parse_mode="HTML")

@router.message(S.decline_reason)
async def pay_decline_reason(msg: Message, bot: Bot, db, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS:
        await state.clear(); return
    data   = await state.get_data()
    await state.clear()
    uid    = data.get("target_uid")
    reason = html.escape(msg.text or "no reason")
    try:
        await bot.send_message(uid,
            f"<blockquote>"
            f"{e('lock')} <b>{sc('payment declined')}</b>\n\n"
            f"{e('fire')} {sc('reason')}: {reason}\n\n"
            f"{e('star')} {sc('please try again or contact')} @flirts_x"
            f"</blockquote>",
            parse_mode="HTML", reply_markup=kb_main())
    except: pass
    await msg.answer(
        f"<blockquote>{e('lock')} {sc('declined. reason sent to user.')}</blockquote>",
        parse_mode="HTML")
    await db_log(db, f"pay_declined uid={uid} reason={reason}", msg.from_user.id)

class PayPendingReply(BaseFilter):
    """fires ONLY when admin has a pending pay_accept awaiting pts amount AND no FSM state is active"""
    async def __call__(self, message: Message, db, state: FSMContext) -> bool:
        if not message.from_user or message.from_user.id not in ADMIN_IDS:
            return False
        if not message.text or message.text.startswith("/"):
            return False
        if await state.get_state() is not None:
            return False  # let the FSM handler take it (broadcast, give pts, etc.)
        pending = await db.pay_pending.find_one({"admin_id": message.from_user.id, "action": "accept"})
        return pending is not None

@router.message(PayPendingReply())
async def admin_pts_add_reply(msg: Message, bot: Bot, db, state: FSMContext):
    """catch admin number reply after pay_accept"""
    pending = await db.pay_pending.find_one({"admin_id": msg.from_user.id, "action": "accept"})
    if not pending: return
    try:
        amt = int(msg.text.strip())
    except ValueError: return
    uid = pending["target_uid"]
    await db.pay_pending.delete_one({"admin_id": msg.from_user.id})
    await db_credit(db, uid, amt)
    try:
        await bot.send_message(uid,
            f"<blockquote>"
            f"{e('check')} <b>{sc('payment accepted!')}</b>\n\n"
            f"{e('gem')} +{amt} {sc('pts added to your account')}\n"
            f"{e('fire')} {sc('thank you!')}"
            f"</blockquote>",
            parse_mode="HTML", reply_markup=kb_main(),
            message_effect_id=EFFECT_FIRE)
    except: pass
    await msg.answer(
        f"<blockquote>{e('check')} +{amt} {sc('pts added to')} <code>{uid}</code></blockquote>",
        parse_mode="HTML")
    await db_log(db, f"pay_accepted uid={uid} pts={amt}", msg.from_user.id)

# leaderboard top 5
@router.callback_query(F.data == "leaderboard")
async def cb_lb(cb: CallbackQuery, db):
    await cb.answer()
    top    = await db_lb(db)
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣"]
    lines  = [f"<blockquote>{e('star')} <b>{sc('top 5 leaderboard')}</b>\n"]
    for i, u in enumerate(top):
        lines.append(f"\n{medals[i]} @{u['username']} — {e('fire')} <code>{u['referral_count']}</code> {sc('referrals')}")
    lines.append("</blockquote>")
    await safe_edit(cb, "".join(lines), kb_back())

# ─────────────────────────────────────────
#  ADMIN
# ─────────────────────────────────────────
@router.message(Command("admin"))
async def cmd_admin(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.answer(f"<blockquote>{e('lock')} {sc('access denied.')}</blockquote>", parse_mode="HTML"); return
    await msg.answer(f"<blockquote>{e('crown')} <b>{sc('admin panel')}</b></blockquote>",
        reply_markup=kb_admin(), parse_mode="HTML")

@router.callback_query(F.data == "adm_back")
async def cb_adm_back(cb: CallbackQuery, db=None):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("denied", show_alert=True); return
    await safe_edit(cb, f"<blockquote>{e('crown')} <b>{sc('admin panel')}</b></blockquote>", kb_admin())

# adm decorator moved above router

@router.callback_query(F.data == "adm_users")
@adm
async def adm_users(cb, db, **_):
    c = await db_count(db)
    await safe_edit(cb, f"<blockquote>{e('star')} {sc('total users')}: <code>{c}</code></blockquote>", kb_admin())

@router.callback_query(F.data == "adm_stats")
@adm
async def adm_stats(cb, db, **_):
    u = await db_count(db)
    agg = await db.users.aggregate([
        {"$project": {"n": {"$size": {"$ifNull": ["$vps_list", []]}}}},
        {"$group": {"_id": None, "total": {"$sum": "$n"}}},
    ]).to_list(1)
    total_vps = agg[0]["total"] if agg else 0
    status = f"{'🔧 MAINTENANCE ON' if MAINTENANCE else '✅ ONLINE'}"
    await safe_edit(cb,
        f"<blockquote>{e('fire')} <b>{sc('stats')}</b>\n\n"
        f"{e('star')} {sc('users')}: <code>{u}</code>\n"
        f"{e('rocket')} {sc('vps provisioned')}: <code>{total_vps}</code>\n"
        f"{e('wrench')} {sc('status')}: <b>{status}</b></blockquote>",
        kb_admin())

@router.callback_query(F.data == "adm_logs")
@adm
async def adm_logs(cb, db, **_):
    logs = await db.logs.find().sort("timestamp",-1).limit(15).to_list(15)
    if not logs:
        text = f"<blockquote>{e('gem')} {sc('no logs.')}</blockquote>"
    else:
        lines = [f"<blockquote>{e('gem')} <b>{sc('logs')}</b>\n"]
        for lg in logs:
            ts = lg["timestamp"].strftime("%d/%m %H:%M")
            lines.append(f"\n<code>[{ts}]</code> {lg['text']}")
        lines.append("</blockquote>")
        text = "".join(lines)
    await safe_edit(cb, text, kb_adm_back())

@router.callback_query(F.data == "adm_admin_list")
@adm
async def adm_admin_list(cb, db, **_):
    admins = await db.users.find({"is_admin": True}).to_list(None)
    lines  = [f"<blockquote>{e('crown')} <b>{sc('admin list')}</b>\n"]
    for a in admins:
        lines.append(f"\n{e('star')} @{a['username']} — <code>{a['user_id']}</code>")
    lines.append("</blockquote>")
    await safe_edit(cb, "".join(lines), kb_admin())

# maintenance toggle
@router.callback_query(F.data == "adm_maintenance")
async def adm_maintenance(cb: CallbackQuery, db):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("denied", show_alert=True); return
    global MAINTENANCE
    MAINTENANCE = not MAINTENANCE
    status = f"{'ON 🔧' if MAINTENANCE else 'OFF ✅'}"
    await cfg_save(db)
    await safe_edit(cb,
        f"<blockquote>{e('wrench')} <b>{sc('maintenance')}: {status}</b></blockquote>",
        kb_admin())

# ─── BROADCAST ──────────────────────────
@router.callback_query(F.data == "adm_broadcast")
@adm
async def adm_broadcast(cb, state: FSMContext, **_):
    await state.clear()
    await state.set_state(S.broadcast)
    await safe_edit(cb,
        f"<blockquote>"
        f"{e('rocket')} <b>{sc('broadcast')}</b>\n\n"
        f"{e('star')} {sc('send the message to broadcast')}\n"
        f"{e('key')} {sc('or reply to any message')}\n"
        f"{e('lock')} {sc('send /cancel anytime to abort')}"
        f"</blockquote>",
        kb_cancel())

async def _do_broadcast(msg: Message, bot: Bot, db, text_override: str = None,
                        target_override: Message = None, markup: dict = None):
    """shared broadcast engine — text_override = direct /broadcast <text> mode"""
    # if admin replied to a message — broadcast that replied message
    # but skip if reply_to is a bot message (like "send broadcast" prompt)
    if target_override is not None:
        target = target_override
    elif (msg.reply_to_message and
        msg.reply_to_message.from_user and
        not msg.reply_to_message.from_user.is_bot and
        not text_override):
        target = msg.reply_to_message
    elif text_override:
        # build a fake text target from the command args
        class _T: pass
        target = _T()
        target.text = text_override
        target.entities = []
        target.photo = target.video = target.document = None
        target.sticker = target.animation = target.voice = None
        target.audio = target.video_note = None
    else:
        target = msg

    users  = await db_all(db)
    groups = await db.groups.find().to_list(None)
    targets = [u["user_id"] for u in users if u["user_id"] != msg.from_user.id]
    targets += [g["chat_id"] for g in groups]
    n_users  = len([t for t in targets if t > 0])
    n_groups = len(targets) - n_users

    # "started" status — edited with progress + final report
    status = await msg.answer(
        f"<blockquote>"
        f"{e('rocket')} <b>{sc('broadcast started!')}</b>\n\n"
        f"{e('star')} {sc('targets')}: <code>{n_users}</code> {sc('users')} + <code>{n_groups}</code> {sc('groups')}\n"
        f"{e('fire')} {sc('sending...')}"
        f"</blockquote>",
        parse_mode="HTML")

    sent  = 0
    fail  = 0
    for tid in targets:
        try:
            if text_override:
                # direct /broadcast <text> mode — plain text, no source message to copy
                await bot.send_message(chat_id=tid, text=text_override)
            elif markup is not None:
                # button mode — native copy preserves premium emoji / blockquote / spoilers
                # 100% intact, then reply_markup swaps in the button. copy_message supports
                # reply_markup override directly — no need to manually rebuild entities
                # (manual rebuild + implicit parse_mode="HTML" default was silently eating formatting)
                await bot.copy_message(
                    chat_id=tid,
                    from_chat_id=target.chat.id,
                    message_id=target.message_id,
                    reply_markup=markup,
                )
            else:
                # native copy — premium emojis, blockquote, bold, spoiler, caption formatting 100% intact
                await bot.copy_message(chat_id=tid, from_chat_id=target.chat.id, message_id=target.message_id)
            sent += 1
            if (sent + fail) % 20 == 0:
                try:
                    await status.edit_text(
                        f"<blockquote>"
                        f"{e('rocket')} <b>{sc('broadcast running...')}</b>\n\n"
                        f"{e('star')} {sc('done')}: <code>{sent + fail}</code>/<code>{len(targets)}</code>\n"
                        f"{e('check')} {sc('sent')}: <code>{sent}</code> | {e('lock')} {sc('failed')}: <code>{fail}</code>\n"
                        f"<code>{progress_bar(sent + fail, len(targets))}</code>"
                        f"</blockquote>",
                        parse_mode="HTML")
                except: pass
                await asyncio.sleep(0.5)
        except Exception:
            fail += 1
    try:
        await status.edit_text(
            f"<blockquote>{e('fire')} <b>{sc('broadcast done!')}</b>\n"
            f"{e('star')} {sc('sent')}: <code>{sent}</code>\n"
            f"{e('lock')} {sc('failed')}: <code>{fail}</code>\n"
            f"{e('vps')} {sc('targets')}: <code>{n_users}</code> {sc('users')} + <code>{n_groups}</code> {sc('groups')}</blockquote>",
            parse_mode="HTML")
    except: pass

# FSM fallback — catches the typed message after the prompt
@router.message(S.broadcast)
async def adm_broadcast_do(msg: Message, bot: Bot, db, state: FSMContext):
    await state.clear()
    if msg.from_user.id not in ADMIN_IDS:
        return
    await _do_broadcast(msg, bot, db)

# ─── FORCE JOIN ─────────────────────────
@router.callback_query(F.data == "adm_add_fj")
@adm
async def adm_add_fj(cb, state: FSMContext, **_):
    await state.set_state(S.add_fj)
    await safe_edit(cb, f"<blockquote>{e('thunder')} {sc('send channel username (no @)')}</blockquote>", kb_cancel())

@router.message(S.add_fj)
async def adm_add_fj_do(msg: Message, state: FSMContext, db):
    await state.clear()
    ch = msg.text.strip().lstrip("@")
    if ch not in FORCE_CHANNELS: FORCE_CHANNELS.append(ch)
    await cfg_save(db)
    await msg.answer(f"<blockquote>{e('thunder')} @{ch} {sc('added')}</blockquote>", parse_mode="HTML")

@router.callback_query(F.data == "adm_remove_fj")
@adm
async def adm_remove_fj(cb, state: FSMContext, **_):
    await state.set_state(S.remove_fj)
    cur = ", ".join(FORCE_CHANNELS) or sc("none")
    await safe_edit(cb, f"<blockquote>{e('lock')} current: {cur}\n{sc('send to remove')}</blockquote>", kb_cancel())

@router.message(S.remove_fj)
async def adm_remove_fj_do(msg: Message, state: FSMContext, db):
    await state.clear()
    ch = msg.text.strip().lstrip("@")
    if ch in FORCE_CHANNELS: FORCE_CHANNELS.remove(ch)
    await cfg_save(db)
    await msg.answer(f"<blockquote>{e('lock')} @{ch} {sc('removed')}</blockquote>", parse_mode="HTML")

# ─── VPS SERVERS (remote machines where vps get created) ───
def kb_servers(servers: list) -> dict:
    rows = []
    for sv in servers:
        rows.append([{"text": f"🖥 {sv['ip']}:{sv['port']} · {sv.get('vps_count', 0)} vps",
                      "callback_data": f"srv_view_{sv['sid']}", "style": "primary"}])
    rows.append([{"text": f"{sc('add server')}", "callback_data": "srv_add", "icon_custom_emoji_id": EM["rocket"], "style": "success"}])
    rows.append([{"text": f"{sc('admin panel')}", "callback_data": "adm_back", "icon_custom_emoji_id": EM["fire"], "style": "primary"}])
    return {"inline_keyboard": rows}

async def _show_servers(cb: CallbackQuery, db):
    servers = await db.servers.find().sort("added_at", 1).to_list(None)
    if servers:
        body = f"{e('check')} {sc('total servers')}: <code>{len(servers)}</code>\n{sc('tap a server to test or delete it')}"
    else:
        body = f"{e('lock')} {sc('no server added yet. vps creation is off until you add one.')}"
    await safe_edit(cb, f"<blockquote>{e('vps')} <b>{sc('vps servers')}</b>\n\n{body}</blockquote>", kb_servers(servers))

@router.callback_query(F.data == "adm_servers")
async def adm_servers(cb: CallbackQuery, db):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("denied", show_alert=True); return
    await cb.answer()
    await _show_servers(cb, db)

@router.callback_query(F.data.startswith("srv_view_"))
async def srv_view(cb: CallbackQuery, db):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("denied", show_alert=True); return
    sid = cb.data.replace("srv_view_", "")
    sv = await db.servers.find_one({"sid": sid})
    if not sv:
        await cb.answer("server not found", show_alert=True); return
    await cb.answer()
    auth = ".pem key" if sv.get("pem") else "password"
    text = (f"<blockquote>{e('vps')} <b>{sc('server details')}</b>\n\n"
            f"{e('gift')} ip: <code>{html.escape(sv['ip'])}</code>\n"
            f"{e('love')} port: <code>{sv['port']}</code>\n"
            f"{e('user')} user: <code>{html.escape(sv['username'])}</code>\n"
            f"{e('key')} auth: <b>{auth}</b>\n"
            f"{e('rocket')} vps created: <code>{sv.get('vps_count', 0)}</code>\n"
            f"{e('clock')} added: {sv['added_at'].strftime('%d/%m/%Y')}</blockquote>")
    kb = {"inline_keyboard": [
        [{"text": f"{sc('test connection')}", "callback_data": f"srv_test_{sid}", "icon_custom_emoji_id": EM["thunder"], "style": "success"},
         {"text": f"{sc('delete server')}", "callback_data": f"srv_del_{sid}", "icon_custom_emoji_id": EM["lock"], "style": "danger"}],
        [{"text": f"{sc('auto setup')}", "callback_data": f"srv_setup_{sid}", "icon_custom_emoji_id": EM["wrench"], "style": "primary"}],
        [{"text": f"{sc('back')}", "callback_data": "adm_servers", "icon_custom_emoji_id": EM["fire"], "style": "primary"}],
    ]}
    await safe_edit(cb, text, kb)

@router.callback_query(F.data.startswith("srv_setup_"))
async def srv_setup(cb: CallbackQuery, db):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("denied", show_alert=True); return
    sv = await db.servers.find_one({"sid": cb.data.replace("srv_setup_", "")})
    if not sv:
        await cb.answer("server not found", show_alert=True); return
    await cb.answer("setting up...")
    report = await asyncio.to_thread(setup_server, sv)
    await cb.message.answer(f"<blockquote><b>{sc('auto setup')}</b>\n\n" + html.escape("\n".join(report)) + "</blockquote>", parse_mode="HTML")

@router.callback_query(F.data.startswith("srv_test_"))
async def srv_test(cb: CallbackQuery, db):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("denied", show_alert=True); return
    sv = await db.servers.find_one({"sid": cb.data.replace("srv_test_", "")})
    if not sv:
        await cb.answer("server not found", show_alert=True); return
    await cb.answer("testing...")
    r = await asyncio.to_thread(test_server, sv)
    msg = f"✅ connected · root ok · {r['hostname']}" if r["success"] else f"❌ {r['error']}"
    await cb.message.answer(f"<blockquote>{html.escape(msg[:900])}</blockquote>", parse_mode="HTML")

@router.callback_query(F.data.startswith("srv_del_"))
async def srv_del(cb: CallbackQuery, db):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("denied", show_alert=True); return
    sid = cb.data.replace("srv_del_", "")
    sv = await db.servers.find_one({"sid": sid})
    if not sv:
        await cb.answer("server not found", show_alert=True); return
    await cb.answer()
    kb = {"inline_keyboard": [[
        {"text": f"{sc('yes, delete')}", "callback_data": f"srv_delok_{sid}", "style": "danger"},
        {"text": f"{sc('no')}", "callback_data": f"srv_view_{sid}", "style": "primary"},
    ]]}
    await safe_edit(cb,
        f"<blockquote>{e('lock')} <b>{sc('delete server')} {html.escape(sv['ip'])}?</b>\n\n"
        f"{sc('bot se server hat jayega, naye vps is pe nahi banenge. jo users already bane hain wo server pe rahenge.')}</blockquote>", kb)

@router.callback_query(F.data.startswith("srv_delok_"))
async def srv_delok(cb: CallbackQuery, db):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("denied", show_alert=True); return
    sid = cb.data.replace("srv_delok_", "")
    sv = await db.servers.find_one_and_delete({"sid": sid})
    await cb.answer("server deleted" if sv else "already deleted", show_alert=True)
    if sv:
        await db_log(db, f"server_deleted ip={sv['ip']}", cb.from_user.id)
    await _show_servers(cb, db)

@router.callback_query(F.data == "srv_add")
async def srv_add(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("denied", show_alert=True); return
    await cb.answer()
    await state.set_state(S.srv_ip)
    await safe_edit(cb, f"<blockquote>{e('gift')} <b>{sc('add server')} — 1/4</b>\n\n{sc('send server ip')}</blockquote>", kb_cancel())

@router.message(S.srv_ip)
async def srv_ip_do(msg: Message, state: FSMContext):
    ip = (msg.text or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9.\-:]{3,253}", ip):
        await msg.answer(f"<blockquote>{e('lock')} {sc('invalid ip, send again')}</blockquote>", parse_mode="HTML"); return
    await state.update_data(srv_ip=ip)
    await state.set_state(S.srv_port)
    await msg.answer(f"<blockquote>{e('love')} <b>{sc('add server')} — 2/4</b>\n\n{sc('send ssh port')} ({sc('usually')} <code>22</code>)</blockquote>",
                     parse_mode="HTML", reply_markup=kb_cancel())

@router.message(S.srv_port)
async def srv_port_do(msg: Message, state: FSMContext):
    t = (msg.text or "").strip()
    if not t.isdigit() or not (1 <= int(t) <= 65535):
        await msg.answer(f"<blockquote>{e('lock')} {sc('invalid port, send a number like 22')}</blockquote>", parse_mode="HTML"); return
    await state.update_data(srv_port=int(t))
    await state.set_state(S.srv_user)
    await msg.answer(f"<blockquote>{e('user')} <b>{sc('add server')} — 3/4</b>\n\n{sc('send ssh username')} ({sc('best')}: <code>root</code>)</blockquote>",
                     parse_mode="HTML", reply_markup=kb_cancel())

@router.message(S.srv_user)
async def srv_user_do(msg: Message, state: FSMContext):
    u = (msg.text or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._\-]{1,32}", u):
        await msg.answer(f"<blockquote>{e('lock')} {sc('invalid username, send again')}</blockquote>", parse_mode="HTML"); return
    await state.update_data(srv_user=u)
    await state.set_state(S.srv_auth)
    await msg.answer(f"<blockquote>{e('key')} <b>{sc('add server')} — 4/4</b>\n\n"
                     f"{sc('send the password as text')}\n{sc('or upload the')} <b>.pem</b> {sc('key file')}</blockquote>",
                     parse_mode="HTML", reply_markup=kb_cancel())

@router.message(S.srv_auth)
async def srv_auth_do(msg: Message, bot: Bot, db, state: FSMContext):
    data = await state.get_data()
    password, pem = None, None
    if msg.document:
        if msg.document.file_size and msg.document.file_size > 20000:
            await msg.answer(f"<blockquote>{e('lock')} {sc('file too big, send a .pem key')}</blockquote>", parse_mode="HTML"); return
        f = await bot.get_file(msg.document.file_id)
        buf = await bot.download_file(f.file_path)
        pem = buf.read().decode(errors="ignore").strip() + "\n"
        if "PRIVATE KEY" not in pem:
            await msg.answer(f"<blockquote>{e('lock')} {sc('this is not a private key file, send again')}</blockquote>", parse_mode="HTML"); return
    elif msg.text:
        password = msg.text.strip()
    else:
        await msg.answer(f"<blockquote>{e('lock')} {sc('send password text or .pem file')}</blockquote>", parse_mode="HTML"); return
    try: await msg.delete()  # don't leave the secret in chat
    except Exception: pass

    srv = {"ip": data["srv_ip"], "port": data["srv_port"], "username": data["srv_user"],
           "password": password, "pem": pem}
    status = await msg.answer(f"<blockquote>{e('rocket')} {sc('testing connection...')}</blockquote>", parse_mode="HTML")
    r = await asyncio.to_thread(test_server, srv)
    if not r["success"]:
        await status.edit_text(
            f"<blockquote>{e('lock')} <b>{sc('server not added')}</b>\n\n{html.escape(r['error'][:800])}\n\n"
            f"{sc('send password / .pem again, or /cancel')}</blockquote>", parse_mode="HTML")
        return  # stay in srv_auth so admin can retry
    await state.clear()
    await status.edit_text(f"<blockquote>{e('wrench')} {sc('login ok, auto setup chal raha hai...')}</blockquote>", parse_mode="HTML")
    report = await asyncio.to_thread(setup_server, srv)
    srv.update({"sid": secrets.token_hex(4), "vps_count": 0,
                "added_at": datetime.now(timezone.utc), "added_by": msg.from_user.id})
    await db.servers.insert_one(srv)
    await db_log(db, f"server_added ip={srv['ip']} host={r['hostname']}", msg.from_user.id)
    await status.edit_text(
        f"<blockquote>{e('check')} <b>{sc('server added!')}</b>\n\n"
        f"{e('gift')} <code>{html.escape(srv['ip'])}:{srv['port']}</code> · {html.escape(r['hostname'])}\n\n"
        + html.escape("\n".join(report)) + "\n\n"
        f"{sc('new vps will now be created on this server.')}</blockquote>",
        parse_mode="HTML", reply_markup={"inline_keyboard": [[
            {"text": f"{sc('vps servers')}", "callback_data": "adm_servers", "icon_custom_emoji_id": EM["vps"], "style": "primary"}]]})

# ─── REDEEM CODES ────────────────────────
@router.callback_query(F.data == "adm_create_redeem")
@adm
async def adm_create_redeem(cb, state: FSMContext, **_):
    await state.clear()
    await state.set_state(S.redeem_code)
    await safe_edit(cb,
        f"<blockquote>{e('gift')} <b>{sc('create redeem code')}</b>\n\n"
        f"{e('key')} {sc('send custom code name')}\n"
        f"<i>A-Z, 0-9, _ and - only; 2-64 characters</i></blockquote>", kb_cancel())

@router.message(S.redeem_code)
async def adm_redeem_code_do(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS:
        await state.clear(); return
    code = (msg.text or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{2,64}", code):
        await msg.answer(f"<blockquote>{e('lock')} {sc('invalid code. use only A-Z, 0-9, _ or -')}</blockquote>", parse_mode="HTML", reply_markup=kb_cancel())
        return
    await state.update_data(redeem_code=code)
    await state.set_state(S.redeem_credits)
    await msg.answer(f"<blockquote>{e('gem')} {sc('send points/credits to give')}</blockquote>", parse_mode="HTML", reply_markup=kb_cancel())

@router.message(S.redeem_credits)
async def adm_redeem_credits_do(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS:
        await state.clear(); return
    try:
        credits = int((msg.text or "").strip())
        if credits < 1 or credits > 1000000000: raise ValueError
    except ValueError:
        await msg.answer(f"<blockquote>{e('lock')} {sc('send a valid positive number')}</blockquote>", parse_mode="HTML", reply_markup=kb_cancel())
        return
    await state.update_data(redeem_credits=credits)
    await state.set_state(S.redeem_limit)
    await msg.answer(f"<blockquote>{e('user')} {sc('send maximum number of users')}</blockquote>", parse_mode="HTML", reply_markup=kb_cancel())

@router.message(S.redeem_limit)
async def adm_redeem_limit_do(msg: Message, bot: Bot, db, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS:
        await state.clear(); return
    try:
        max_users = int((msg.text or "").strip())
        if max_users < 1 or max_users > 1000000000: raise ValueError
    except ValueError:
        await msg.answer(f"<blockquote>{e('lock')} {sc('send a valid positive number')}</blockquote>", parse_mode="HTML", reply_markup=kb_cancel())
        return

    data = await state.get_data()
    await state.clear()
    code = data["redeem_code"]
    if await db.redeem_codes.find_one({"code": code}):
        await msg.answer(f"<blockquote>{e('lock')} {sc('this code already exists.')}</blockquote>", parse_mode="HTML", reply_markup=kb_adm_back())
        return
    await db.redeem_codes.insert_one({
        "code": code,
        "credits": int(data["redeem_credits"]),
        "max_users": max_users,
        "remaining_users": max_users,
        "redeemed_count": 0,
        "redeemed_by": [],
        "created_by": msg.from_user.id,
        "created_at": datetime.now(timezone.utc),
    })
    bi = await get_bot_info(bot)
    link = f"https://t.me/{bi.username}?start=redeem_{code}"
    await msg.answer(
        f"<blockquote>{e('check')} <b>{sc('redeem code created!')}</b>\n\n"
        f"{e('key')} {sc('code')}: <code>{html.escape(code)}</code>\n"
        f"{e('gem')} {sc('credits')}: <code>{data['redeem_credits']}</code>\n"
        f"{e('user')} {sc('user limit')}: <code>{max_users}</code>\n\n"
        f"{e('rocket')} {sc('share this link')}:\n<code>{html.escape(link)}</code></blockquote>",
        parse_mode="HTML", reply_markup=kb_adm_back())
    await db_log(db, f"redeem_created code={code} credits={data['redeem_credits']} max_users={max_users}", msg.from_user.id)

@router.callback_query(F.data == "adm_delete_redeem")
@adm
async def adm_delete_redeem(cb, state: FSMContext, db, **_):
    codes = await db.redeem_codes.find({}, {"code": 1, "credits": 1, "remaining_users": 1}).sort("created_at", -1).to_list(50)
    if not codes:
        await safe_edit(cb, f"<blockquote>{e('lock')} {sc('no redeem codes found.')}</blockquote>", kb_adm_back())
        return
    lines = [f"<blockquote>{e('lock')} <b>{sc('delete redeem code')}</b>\n\n"]
    for item in codes:
        lines.append(
            f"<code>{html.escape(item['code'])}</code> — {item.get('credits', 0)} {sc('pts')} — "
            f"{item.get('remaining_users', 0)} {sc('slots left')}\n"
        )
    lines.append(f"\n{sc('send the code name to delete')}</blockquote>")
    await state.set_state(S.delete_redeem)
    await safe_edit(cb, "".join(lines), kb_cancel())

@router.message(S.delete_redeem)
async def adm_delete_redeem_do(msg: Message, bot: Bot, db, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS:
        await state.clear()
        return
    code = (msg.text or "").strip().upper()
    await state.clear()
    result = await db.redeem_codes.delete_one({"code": code})
    if result.deleted_count != 1:
        await msg.answer(f"<blockquote>{e('lock')} {sc('redeem code not found.')}</blockquote>", parse_mode="HTML", reply_markup=kb_adm_back())
        return
    await msg.answer(f"<blockquote>{e('check')} <b>{sc('redeem code deleted.')}</b>\n<code>{html.escape(code)}</code></blockquote>", parse_mode="HTML", reply_markup=kb_adm_back())
    await db_log(db, f"redeem_deleted code={code}", msg.from_user.id)
    await log_ch(bot, f"{e('lock')} redeem deleted → <code>{html.escape(code)}</code>")

# ─── ADMIN GIVE/REMOVE ──────────────────
@router.callback_query(F.data == "adm_give_admin")
@adm
async def adm_give_admin(cb, state: FSMContext, **_):
    await state.set_state(S.give_admin_user)
    await safe_edit(cb, f"<blockquote>{e('crown')} {sc('send user id to promote')}</blockquote>", kb_cancel())

@router.message(S.give_admin_user)
async def adm_give_admin_do(msg: Message, bot: Bot, db, state: FSMContext):
    await state.clear()
    try: t = int(msg.text.strip())
    except: await msg.answer("<blockquote>invalid id</blockquote>", parse_mode="HTML"); return
    await db_set_admin(db, t, True)
    await msg.answer(f"<blockquote>{e('crown')} <code>{t}</code> {sc('promoted')}</blockquote>", parse_mode="HTML")
    await log_ch(bot, f"{e('crown')} admin given → <code>{t}</code>")

@router.callback_query(F.data == "adm_remove_admin")
@adm
async def adm_remove_admin(cb, state: FSMContext, **_):
    await state.set_state(S.remove_admin_user)
    await safe_edit(cb, f"<blockquote>{e('shield')} {sc('send user id to demote')}</blockquote>", kb_cancel())

@router.message(S.remove_admin_user)
async def adm_remove_admin_do(msg: Message, bot: Bot, db, state: FSMContext):
    await state.clear()
    try: t = int(msg.text.strip())
    except: await msg.answer("<blockquote>invalid id</blockquote>", parse_mode="HTML"); return
    await db_set_admin(db, t, False)
    await msg.answer(f"<blockquote>{e('shield')} <code>{t}</code> {sc('demoted')}</blockquote>", parse_mode="HTML")

# ─── GIVE/REMOVE POINTS ─────────────────
@router.callback_query(F.data == "adm_give_credit")
@adm
async def adm_give_credit(cb, state: FSMContext, **_):
    await state.set_state(S.give_credit_user)
    await safe_edit(cb, f"<blockquote>{e('gem')} <b>{sc('give points')}</b>\n{sc('send user id')}</blockquote>", kb_cancel())

@router.message(S.give_credit_user)
async def adm_give_credit_uid(msg: Message, state: FSMContext):
    try:
        await state.update_data(target=int(msg.text.strip()))
        await state.set_state(S.give_credit_amt)
        await msg.answer(f"<blockquote>{e('gem')} {sc('send amount of points')}</blockquote>", reply_markup=kb_cancel(), parse_mode="HTML")
    except: await msg.answer("<blockquote>invalid id</blockquote>", parse_mode="HTML"); await state.clear()

@router.message(S.give_credit_amt)
async def adm_give_credit_do(msg: Message, bot: Bot, db, state: FSMContext):
    data = await state.get_data(); await state.clear()
    try: amt = int(msg.text.strip())
    except: await msg.answer("<blockquote>invalid amount</blockquote>", parse_mode="HTML"); return
    await db_credit(db, data["target"], amt)
    await msg.answer(f"<blockquote>{e('gem')} +{amt} {sc('points')} → <code>{data['target']}</code></blockquote>", parse_mode="HTML")
    await log_ch(bot, f"{e('gem')} +{amt} points → <code>{data['target']}</code>")

@router.callback_query(F.data == "adm_remove_credit")
@adm
async def adm_remove_credit(cb, state: FSMContext, **_):
    await state.set_state(S.remove_credit_user)
    await safe_edit(cb, f"<blockquote>{e('key')} <b>{sc('remove points')}</b>\n{sc('send user id')}</blockquote>", kb_cancel())

@router.message(S.remove_credit_user)
async def adm_remove_credit_uid(msg: Message, state: FSMContext):
    try:
        await state.update_data(target=int(msg.text.strip()))
        await state.set_state(S.remove_credit_amt)
        await msg.answer(f"<blockquote>{e('key')} {sc('send amount to remove')}</blockquote>", reply_markup=kb_cancel(), parse_mode="HTML")
    except: await msg.answer("<blockquote>invalid id</blockquote>", parse_mode="HTML"); await state.clear()

@router.message(S.remove_credit_amt)
async def adm_remove_credit_do(msg: Message, bot: Bot, db, state: FSMContext):
    data = await state.get_data(); await state.clear()
    try: amt = int(msg.text.strip())
    except: await msg.answer("<blockquote>invalid amount</blockquote>", parse_mode="HTML"); return
    await db_credit(db, data["target"], -amt)
    await msg.answer(f"<blockquote>{e('key')} -{amt} {sc('points')} → <code>{data['target']}</code></blockquote>", parse_mode="HTML")

# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
# ─── REF LINK FOOTER ON ANY USER MSG ────
@router.message(F.text & ~F.text.startswith("/"))
async def user_msg_footer(msg: Message, bot: Bot, db):
    """show ref link below any random user message"""
    uid  = msg.from_user.id
    user = await db_get(db, uid)
    if not user: return
    bi   = await get_bot_info(bot)
    rl   = f"https://t.me/{bi.username}?start=ref_{uid}"
    pts  = user.get("points", 0)
    await msg.answer(
        f"<blockquote>"
        f"{e('key')} {sc('your referral link')}:\n<code>{rl}</code>\n\n"
        f"{e('fire')} {sc('points')}: <code>{pts}/{REFS_NEEDED}</code>"
        f"</blockquote>",
        reply_markup=kb_main(), parse_mode="HTML"
    )

async def main():
    client  = AsyncIOMotorClient(MONGO_URI, maxPoolSize=20, minPoolSize=5, serverSelectionTimeoutMS=3000)
    db      = client["vps_bot"]
    storage = MongoStorage(client=client, db_name="vps_bot")
    bot     = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp      = Dispatcher(storage=storage)

    # Group chats: no replies/interactions; DM behavior remains unchanged.
    # Broadcast delivery is direct bot API traffic and is not blocked by this.
    dp.message.middleware(GroupChatSilencer())
    dp.callback_query.middleware(GroupChatSilencer())

    # maintenance middleware on messages + callbacks
    dp.message.middleware(MaintenanceMiddleware())
    dp.callback_query.middleware(MaintenanceMiddleware())

    dp.include_router(router)

    async def db_mw(handler, event, data):
        data["db"] = db
        return await handler(event, data)
    dp.update.middleware(db_mw)

    await cfg_load(db)
    # create indexes for faster queries
    await db.users.create_index("user_id", unique=True, background=True)
    await db.users.create_index("referral_count", background=True)
    await db.users.create_index("points", background=True)
    await db.force_join_verified.create_index("user_id", background=True)
    await db.redeem_codes.create_index("code", unique=True, background=True)
    await db.redeem_codes.create_index("created_at", background=True)
    await db.logs.create_index("timestamp", background=True)
    await db.groups.create_index("chat_id", unique=True, background=True)
    await db.servers.create_index("sid", unique=True, background=True)
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("vps bot v4 live. vps are created on admin-added remote servers.")
    await dp.start_polling(bot, allowed_updates=["message","callback_query","chat_join_request","chat_member","my_chat_member"], polling_timeout=10)

if __name__ == "__main__":
    asyncio.run(main())
