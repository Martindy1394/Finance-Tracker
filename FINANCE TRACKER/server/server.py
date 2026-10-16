"""Money Tracker web server.

Serves the Money Tracker web app (to this PC by default; set "host" to "0.0.0.0" in
server-config.json to also allow phones and laptops on the same network), stores every user's
data in data/money-tracker.db, sends reminders on Telegram and closes each month on the 1st.

    python server.py           start the server (opens your browser)
    python server.py --check   check reminders / close months once and exit (Task Scheduler)
    python server.py --test    send a test Telegram message to the admin and exit
    python server.py --reset-password [username]   set a temporary password (default: the admin)

Only the Python standard library is used.
"""

import calendar
import datetime as dt
import ipaddress
import json
import os
import re
import shutil
import socket
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.dont_write_bytecode = True  # keep the app folder free of __pycache__
import accounts  # noqa: E402
import database  # noqa: E402
from accounts import AuthError, ConflictError  # noqa: E402
from excel_export import build_workbook  # noqa: E402
from reminders import (assign_payments, category_amount, category_dates, category_schedule,  # noqa: E402,F401
                       find_reminders, month_schedule, monthly_limit, occurrences, ordinal, peso, shift_month)

# Folder layout: index.html at the top, assets/ (app.js, styles.css), server/ (this code),
# config/ (settings), data/ (database, archive, backups, logs), scripts/ (.bat files), docs/
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(BASE, "assets")
CONFIG_DIR = os.path.join(BASE, "config")
DATA_DIR = os.path.join(BASE, "data")
DB_FILE = os.path.join(DATA_DIR, "money-tracker.db")
STATE_FILE = os.path.join(DATA_DIR, "reminder-state.json")
LOG_FILE = os.path.join(DATA_DIR, "reminders.log")
ARCHIVE_DIR = os.path.join(DATA_DIR, "archive")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
TELEGRAM_FILE = os.path.join(CONFIG_DIR, "telegram-config.json")
CONFIG_FILE = os.path.join(CONFIG_DIR, "server-config.json")
# Files from the single-user version (moved into the database on first start)
LEGACY_DATA = os.path.join(DATA_DIR, "money-tracker.json")
LEGACY_AUTH = os.path.join(DATA_DIR, "auth.json")

DEFAULT_CONFIG = {
    "host": "127.0.0.1",    # "127.0.0.1" = this PC only (default); "0.0.0.0" = also phones/laptops on the same network
    "port": 8765,
    "public_url": "",       # e.g. "https://money.example.com" when published through a tunnel/proxy
    "trust_proxy": False,   # true only behind your own HTTPS proxy/tunnel
    "backups_to_keep": 14,  # daily copies of the database in data/backups
}
# Browser security rules for the app page (only fonts from Google, scripts only from this server)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
OWNER = "Reymartin Esperida"
TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
COOKIE = "mt_session"

# Only these files are served; everything else (database, settings) stays private
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/assets/styles.css": (os.path.join("assets", "styles.css"), "text/css; charset=utf-8"),
    "/assets/app.js": (os.path.join("assets", "app.js"), "text/javascript; charset=utf-8"),
}

data_lock = threading.RLock()
login_lock = threading.Lock()
attempts = {}  # username/ip -> {"fails": n, "locked_until": datetime}


# ---------- Files & settings ----------
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def log(message):
    os.makedirs(DATA_DIR, exist_ok=True)
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M}  {message}"
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1_000_000:
            os.replace(LOG_FILE, LOG_FILE + ".1")  # keep one older log, so the file never grows forever
    except OSError:
        pass
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        print(line)
    except (UnicodeEncodeError, OSError):
        pass  # console without UTF-8 (or no console): the log file still has it


def config():
    cfg = dict(DEFAULT_CONFIG, **load_json(CONFIG_FILE, {}))
    if not os.path.exists(CONFIG_FILE):
        save_json(CONFIG_FILE, DEFAULT_CONFIG)
    return cfg


def valid_data(value):
    return isinstance(value, dict) and isinstance(value.get("transactions"), list)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_data(data):
    """Reject saved data that could break reminders, the database or Excel. Returns a problem or ''."""
    if not valid_data(data):
        return "The data is not in the expected format."
    if len(data["transactions"]) > 100_000:
        return "Too many entries."
    for t in data["transactions"]:
        if not isinstance(t, dict):
            return "An entry is not in the expected format."
        if not isinstance(t.get("id"), str) or not 1 <= len(t["id"]) <= 64:
            return "An entry has no valid id."
        if t.get("type") not in ("income", "expense"):
            return "An entry has an unknown type."
        if not isinstance(t.get("amount"), int) or isinstance(t.get("amount"), bool) or not 0 < t["amount"] <= 10**13:
            return f"The amount of an entry on {t.get('date', '?')} is not valid."
        if not isinstance(t.get("date"), str) or not DATE_RE.match(t["date"]):
            return "An entry has a date that is not valid."
        try:
            dt.date.fromisoformat(t["date"])
            if t.get("dueFor") is not None:
                dt.date.fromisoformat(str(t["dueFor"]))
        except ValueError:
            return "An entry has a date that is not valid."
        if not isinstance(t.get("category"), str) or len(t["category"]) > 100:
            return "An entry has a category that is not valid."
        if not isinstance(t.get("note", ""), str) or len(t.get("note", "")) > 1000:
            return "A note is too long."
    cats = data.get("categories")
    if cats is not None:
        if not isinstance(cats, dict) or not all(isinstance(cats.get(k, []), list) for k in ("income", "expense")):
            return "The categories are not in the expected format."
        for c in cats.get("expense", []) + cats.get("income", []):
            if not isinstance(c, dict) or not isinstance(c.get("name"), str):
                return "A category is not in the expected format."
            if "amount" in c and (not isinstance(c["amount"], int) or c["amount"] < 0):
                return f"The amount of {c['name']} is not valid."
            r = c.get("reminder")
            if r is not None:
                if not isinstance(r, dict) or not all(isinstance(d, int) and 1 <= d <= 31 for d in r.get("days") or []):
                    return f"The reminder days of {c['name']} are not valid."
                if r.get("date") and not (isinstance(r["date"], str) and DATE_RE.match(r["date"])):
                    return f"The due date of {c['name']} is not valid."
    if data.get("reminders") is not None and not isinstance(data["reminders"], dict):
        return "The reminder settings are not in the expected format."
    return ""


def db():
    os.makedirs(DATA_DIR, exist_ok=True)
    return accounts.connect(DB_FILE)


def lan_addresses():
    """This PC's addresses on the local network (for opening the app on other devices)."""
    found = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        found.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in found if not ip.startswith("127."))


def app_urls():
    cfg = config()
    urls = [f"http://127.0.0.1:{cfg['port']}/"]
    if cfg["host"] not in ("127.0.0.1", "localhost"):
        urls += [f"http://{ip}:{cfg['port']}/" for ip in lan_addresses()]
    if cfg.get("public_url"):
        urls.append(cfg["public_url"].rstrip("/") + "/")
    return urls


# ---------- Telegram ----------
class TelegramError(Exception):
    pass


def telegram_config():
    return load_json(TELEGRAM_FILE, {})


def telegram_api(token, method, params=None):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(params or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            body = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {"description": str(e)}
        code, desc = e.code, body.get("description", "")
        if code in (401, 404):
            raise TelegramError("Telegram did not accept the bot token. Copy it again from @BotFather.")
        if code == 403:
            raise TelegramError("The bot can't message this person. Open the bot in Telegram, unblock it if needed, and press Start.")
        if code == 400 and "chat not found" in desc.lower():
            raise TelegramError("Chat not found. Open the bot in Telegram, press Start, then click Connect again.")
        raise TelegramError(f"Telegram error: {desc or code}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise TelegramError(f"Could not reach Telegram. Check the internet connection. ({getattr(e, 'reason', e)})")
    if not body.get("ok"):
        raise TelegramError(f"Telegram error: {body.get('description', 'unknown')}")
    return body["result"]


def bot_info():
    cfg = telegram_config()
    return {"ready": bool(cfg.get("bot_token")), "bot": cfg.get("bot_username", "")}


def save_bot_token(token):
    token = token.strip()
    if not TOKEN_RE.match(token):
        raise TelegramError("That doesn't look like a bot token. It looks like 123456789:ABCdef... and comes from @BotFather.")
    me = telegram_api(token, "getMe")
    save_json(TELEGRAM_FILE, {"bot_token": token, "bot_username": me.get("username", "")})
    return me.get("username", "")


def escape_html(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_message(lines, title, chat_id):
    cfg = telegram_config()
    if not cfg.get("bot_token"):
        raise TelegramError("The admin hasn't set up the Telegram bot yet.")
    if not chat_id:
        raise TelegramError("Telegram isn't connected yet.")
    text = f"💸 <b>{escape_html(title)}</b>\n\n" + "\n\n".join(escape_html(line) for line in lines)
    telegram_api(cfg["bot_token"], "sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})


def notify_user(user, text, title="Money Tracker security"):
    """Best-effort message to one user (sqlite Row or dict with telegram_chat_id)."""
    try:
        if user and user["telegram_chat_id"] and bot_info()["ready"]:
            send_message([text], title, user["telegram_chat_id"])
    except Exception as e:
        log(f"Could not send a message to {user['username']}: {e}")


def telegram_link(user_id):
    info = bot_info()
    if not info["ready"]:
        raise TelegramError("The admin hasn't set up the Telegram bot yet. Ask your admin to do it on the Users page.")
    con = db()
    try:
        code = accounts.new_telegram_code(con, user_id)
    finally:
        con.close()
    return {"bot": info["bot"], "code": code, "link": f"https://t.me/{info['bot']}?start={code}"}


def telegram_connect(user_id):
    """Find the '/start <code>' message this user sent to the bot and remember their chat."""
    cfg = telegram_config()
    if not cfg.get("bot_token"):
        raise TelegramError("The admin hasn't set up the Telegram bot yet.")
    con = db()
    try:
        user = accounts.get_user(con, user_id)
        code = user["telegram_code"]
        if not code:
            raise TelegramError("Tap “Open the bot in Telegram” first.")
        collect_telegram_starts(con, cfg["bot_token"])
        start = accounts.telegram_start_for(con, code)
        if not start:
            raise TelegramError(f"We haven't received your Start yet. In Telegram, open @{cfg.get('bot_username')} with the button "
                                f"above and press Start (or send the code {code} to the bot), then tap Connect again.")
        name = start["name"] or "you"
        match = {"id": start["chat_id"]}
        accounts.set_telegram(con, user_id, start["chat_id"], name)
    finally:
        con.close()
    send_message([f"✅ Connected! Hi {name}, your Money Tracker reminders will arrive here.",
                  "You'll get bill reminders, budget alerts, the daily nudge (if you turn it on), "
                  "your monthly summary on the 1st, and security messages such as password reset codes."],
                 "Money Tracker", match["id"])
    return name


def collect_telegram_starts(con, token):
    """Read the bot's new messages, remember every 'Start' (or code) sent to it, and mark them as
    read, so no one's Start is missed however many messages the bot gets."""
    offset = None
    for _ in range(20):  # up to 2,000 new messages per check
        params = {"timeout": 0, "allowed_updates": ["message"], "limit": 100}
        if offset is not None:
            params["offset"] = offset
        updates = telegram_api(token, "getUpdates", params)
        if not updates:
            break
        for u in updates:
            msg = u.get("message") or {}
            chat = msg.get("chat") or {}
            text = (msg.get("text") or "").strip()
            code = text[len("/start "):].strip() if text.startswith("/start ") else text
            if chat.get("type") == "private" and re.fullmatch(r"[0-9a-f]{8}", code or ""):
                name = " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username", "")
                accounts.remember_telegram_start(con, code, chat["id"], name)
        offset = max(u["update_id"] for u in updates) + 1
    if offset is not None:
        telegram_api(token, "getUpdates", {"timeout": 0, "offset": offset, "limit": 1})  # confirm: mark as read


# ---------- Moving the single-user version into accounts ----------
def migrate_legacy():
    """First start after the upgrade: the existing password and data become the 'admin' account."""
    con = db()
    try:
        if accounts.count_users(con):
            return
        auth = load_json(LEGACY_AUTH, {})
        pw = auth.get("password")
        if not pw:
            return  # fresh install: the first admin is created on the setup screen
        user_id = accounts.create_user(con, "admin", OWNER, None, role="admin", stored_hash=pw)
        tg = telegram_config()
        if tg.get("chat_id"):
            accounts.set_telegram(con, user_id, tg["chat_id"], tg.get("chat_name") or OWNER)
            save_json(TELEGRAM_FILE, {k: tg[k] for k in ("bot_token", "bot_username") if k in tg})
        data = load_json(LEGACY_DATA, None)
        if valid_data(data):
            accounts.save_state(con, user_id, data)
            database.sync_transactions(con, user_id, data["transactions"])
        state = load_json(STATE_FILE, {"sent": {}})
        state["sent"] = {(k if re.match(r"^\d+\|", k) else f"{user_id}|{k}"): v for k, v in state.get("sent", {}).items()}
        save_json(STATE_FILE, state)
    finally:
        con.close()
    os.makedirs(BACKUP_DIR, exist_ok=True)
    for path in (LEGACY_AUTH, LEGACY_DATA):
        if os.path.exists(path):
            os.replace(path, os.path.join(BACKUP_DIR, os.path.basename(path) + ".before-users"))
    log("Upgraded to multiple users: your account is now 'admin' (same password)")


# ---------- Per-user data ----------
def load_user_data(con, user_id):
    return accounts.load_state(con, user_id) or {}


def save_user_data(con, user_id, data, base_version=None):
    version = accounts.save_state(con, user_id, data, base_version)
    database.sync_transactions(con, user_id, data.get("transactions", []))
    return version


# ---------- Daily database backup ----------
def backup_database(today=None):
    """Once a day, copy the database to data/backups (keeps the newest few)."""
    today = today or dt.date.today()
    if not os.path.exists(DB_FILE):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    target = os.path.join(BACKUP_DIR, f"money-tracker-{today.isoformat()}.db")
    if os.path.exists(target):
        return None
    with data_lock:
        src = sqlite3.connect(DB_FILE)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)  # consistent copy even while the app is in use
        finally:
            dst.close()
            src.close()
    keep = max(1, int(config().get("backups_to_keep", 14)))
    old = sorted(f for f in os.listdir(BACKUP_DIR) if re.fullmatch(r"money-tracker-\d{4}-\d{2}-\d{2}\.db", f))
    for name in old[:-keep]:
        os.remove(os.path.join(BACKUP_DIR, name))
    log(f"Database backed up to data/backups/{os.path.basename(target)}")
    return target


def workbook_for(con, user, data, month=None):
    txs = database.active_transactions(con, user["id"], month)
    today = dt.date.today()
    view = dict(data, transactions=txs)
    owner = f"{user['name']} · Money Tracker by {OWNER}"
    if month:
        y, m = map(int, month.split("-"))
        ref = today if month == today.strftime("%Y-%m") else dt.date(y, m, calendar.monthrange(y, m)[1])
        return build_workbook(view, ref, owner, month_schedule(view, ref), category_amount, monthly_limit,
                              period=f"{calendar.month_name[m]} {y}", generated=today)
    return build_workbook(view, today, owner, month_schedule(view, today), category_amount, monthly_limit)


# ---------- Reminders & monthly close (every user) ----------
def check_reminders(now=None):
    now = now or dt.datetime.now()
    if not bot_info()["ready"]:
        return []
    sent_lines = []
    with data_lock:
        con = db()
        try:
            state = load_json(STATE_FILE, {"sent": {}})
            sent = state.setdefault("sent", {})
            for user in accounts.all_users(con):
                if user["disabled"] or not user["telegram_chat_id"]:
                    continue
                data = load_user_data(con, user["id"])
                if not (data.get("reminders") or {}).get("enabled"):
                    continue
                prefix = f"{user['id']}|"
                mine = {k[len(prefix):]: v for k, v in sent.items() if k.startswith(prefix)}
                try:
                    due = find_reminders(data, now, mine)
                except Exception as e:  # one user's data must not stop everyone else's reminders
                    log(f"Could not check reminders for {user['username']}: {e}")
                    continue
                if not due:
                    continue
                lines = [text for _, text in due]
                try:
                    send_message(lines, f"Money Tracker · {now:%a, %b %d}", user["telegram_chat_id"])
                except Exception as e:  # try again at the next check
                    log(f"Could not send reminders to {user['username']}: {e}")
                    continue
                for key, _ in due:
                    sent[prefix + key] = now.isoformat(timespec="minutes")
                log(f"Sent {len(lines)} reminder(s) to {user['username']} on Telegram")
                sent_lines += lines
            cutoff = (now - dt.timedelta(days=95)).isoformat()
            state["sent"] = {k: v for k, v in sent.items() if v >= cutoff}
            save_json(STATE_FILE, state)
        finally:
            con.close()
    return sent_lines


_check_timer = None


def schedule_check(delay=5):
    """Check soon after a save, so budget alerts arrive while the app is in use."""
    global _check_timer
    if _check_timer:
        _check_timer.cancel()
    _check_timer = threading.Timer(delay, check_reminders)
    _check_timer.daemon = True
    _check_timer.start()


def close_months(today=None):
    """On the 1st (or the next time the server runs), close every user's finished months:
    store the totals, save the month's Excel file in data/archive/<username>/ and send a summary."""
    today = today or dt.date.today()
    closed_all = []
    with data_lock:
        con = db()
        try:
            for user in accounts.all_users(con):
                data = load_user_data(con, user["id"])
                if not valid_data(data):
                    continue
                try:
                    database.sync_transactions(con, user["id"], data["transactions"])
                    for month in database.months_to_close(con, user["id"], today):
                        folder = os.path.join(ARCHIVE_DIR, user["username"])
                        os.makedirs(folder, exist_ok=True)
                        name = f"money-tracker-{month}.xlsx"
                        with open(os.path.join(folder, name), "wb") as f:
                            f.write(workbook_for(con, user, data, month))
                        c = database.close_month(con, user["id"], month, os.path.join("data", "archive", user["username"], name))
                        closed_all.append((user, c))
                except Exception as e:  # one user's data must not stop the others
                    log(f"Could not close the month for {user['username']}: {e}")
        finally:
            con.close()
    for user, c in closed_all:
        y, m = map(int, c["month"].split("-"))
        log(f"Closed {c['month']} for {user['username']}: in {peso(c['moneyIn'])}, out {peso(c['moneyOut'])}")
        notify_user(user, f"📊 {calendar.month_name[m]} {y} is closed and saved to your archive.\n"
                          f"Money in {peso(c['moneyIn'])} · Money out {peso(c['moneyOut'])} · Left {peso(c['left'])}\n"
                          f"Your Expenses page now starts fresh for {calendar.month_name[today.month]}.", "Money Tracker")
    return [c for _, c in closed_all]


# ---------- Login protection ----------
def check_not_locked(key):
    a = attempts.get(key)
    if a and a.get("locked_until") and dt.datetime.now() < a["locked_until"]:
        seconds = int((a["locked_until"] - dt.datetime.now()).total_seconds()) + 1
        raise AuthError(f"Too many wrong attempts. Try again in {seconds // 60} min {seconds % 60} s." if seconds >= 60
                        else f"Too many wrong attempts. Try again in {seconds} seconds.")


def record_failure(key, user=None):
    a = attempts.setdefault(key, {"fails": 0, "locked_until": None})
    a["fails"] += 1
    a["last"] = dt.datetime.now()
    if a["fails"] >= 5:
        minutes = min(15, 2 ** (a["fails"] - 5))
        a["locked_until"] = dt.datetime.now() + dt.timedelta(minutes=minutes)
        log(f"Login locked for {minutes} min ({key}) after {a['fails']} wrong attempts")
        if a["fails"] == 5 and user is not None:
            notify_user(user, f"⚠️ 5 wrong password attempts on your Money Tracker account at {dt.datetime.now():%I:%M %p}. "
                              "If this wasn't you, someone may be trying to get in.")


def record_success(key):
    attempts.pop(key, None)


def prune_attempts():
    """Forget failed-login counters that are no longer locking anything (keeps memory small)."""
    stale = dt.datetime.now() - dt.timedelta(hours=1)
    with login_lock:
        for key, a in list(attempts.items()):
            # Forget a counter after an hour without wrong guesses and no lock in force
            locked_until = a.get("locked_until")
            if a.get("last", stale) <= stale and (locked_until is None or locked_until < stale):
                attempts.pop(key, None)


# Used so a wrong username takes as long as a wrong password (doesn't reveal which usernames exist)
_DUMMY_HASH = accounts.hash_secret("not-a-real-password")


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    server_version = "MoneyTracker"

    def log_message(self, *args):
        pass

    # --- request helpers ---
    def _from_this_pc(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _https(self):
        return bool(config().get("trust_proxy")) and self.headers.get("X-Forwarded-Proto", "") == "https"

    def _host_ok(self):
        """Accept this PC's names and network addresses (blocks DNS-rebinding tricks)."""
        host = self.headers.get("Host", "")
        name = host.rsplit(":", 1)[0].strip("[]").lower()
        cfg = config()
        public = (cfg.get("public_url") or "").split("//")[-1].split("/")[0].split(":")[0].lower()
        try:
            ipaddress.ip_address(name)
            ok = True
        except ValueError:
            ok = name in ("localhost", socket.gethostname().lower(), socket.gethostname().lower() + ".local") or (public and name == public)
        if not ok:
            self._send(403, {"error": "forbidden"})
        return ok

    def _same_origin(self):
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if origin is None or origin in (f"http://{host}", f"https://{host}"):
            return True
        self._send(403, {"error": "forbidden"})
        return False

    def _token(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return cookie[COOKIE].value if COOKIE in cookie else ""

    def _user(self, con):
        return accounts.session_user(con, self._token())

    def _cookie(self, token, max_age):
        c = f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict"
        if max_age:
            c += f"; Max-Age={max_age}"
        if self._https():
            c += "; Secure"
        return c

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _body(self, limit=20_000_000):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > limit:
            raise ValueError("bad length")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _file_origin(self):
        return self.headers.get("Origin") == "null"

    # --- clear errors instead of a dropped connection ---
    def _safely(self, handler):
        try:
            handler()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log(f"Request failed ({self.command} {self.path.split('?')[0]}): {e}")
            try:
                self._send(500, {"error": "Something went wrong on the server. Please try again."})
            except Exception:
                pass

    def do_GET(self):
        self._safely(self._get)

    def do_PUT(self):
        self._safely(self._put)

    def do_POST(self):
        self._safely(self._post)

    # --- GET ---
    def _get(self):
        if not self._host_ok():
            return
        path, _, query = self.path.partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)

        if path in STATIC:
            name, ctype = STATIC[path]
            with open(os.path.join(BASE, name), "rb") as f:
                extra = {"Content-Security-Policy": CSP} if ctype.startswith("text/html") and config().get("csp", True) else None
                return self._send(200, f.read(), ctype, extra=extra)

        con = db()
        try:
            if path == "/api/status":
                # Asked by the plain-file version of the app on this PC (first-run hand-over)
                body = {"ok": True, "hasData": accounts.count_users(con) > 0 or os.path.exists(LEGACY_DATA)}
                return self._send(200, body, extra={"Access-Control-Allow-Origin": "null"} if self._file_origin() else None)

            if path == "/api/auth":
                user = self._user(con)
                return self._send(200, {
                    "hasUsers": accounts.count_users(con) > 0,
                    "setupAllowed": accounts.count_users(con) == 0 and self._from_this_pc(),
                    "loggedIn": user is not None,
                    "user": accounts.public_user(user),
                    "bot": bot_info(),
                })

            user = self._user(con)
            if user is None:
                return self._send(401, {"error": "Please log in.", "login": True})

            if path == "/api/me":
                return self._send(200, {"user": accounts.public_user(user), "bot": bot_info()})
            if path == "/api/data":
                with data_lock:
                    return self._send(200, load_user_data(con, user["id"]),
                                      extra={"X-Data-Version": str(accounts.state_version(con, user["id"]))})
            if path == "/api/months":
                with data_lock:
                    data = load_user_data(con, user["id"])
                    database.sync_transactions(con, user["id"], data.get("transactions", []))
                    return self._send(200, {"months": database.months(con, user["id"], dt.date.today())})
            if path == "/api/export.xlsx":
                month = params.get("month", "")
                if month and not re.fullmatch(r"\d{4}-\d{2}", month):
                    return self._send(400, {"error": "bad month"})
                with data_lock:
                    data = load_user_data(con, user["id"])
                    database.sync_transactions(con, user["id"], data.get("transactions", []))
                    body = workbook_for(con, user, data, month or None)
                name = f"money-tracker-{user['username']}-{month}.xlsx" if month else \
                    f"money-tracker-{user['username']}-all-{dt.date.today().isoformat()}.xlsx"
                return self._send(200, body, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                  extra={"Content-Disposition": f'attachment; filename="{name}"'})

            if path.startswith("/api/admin/"):
                if user["role"] != "admin":
                    return self._send(403, {"error": "Only the admin can do this."})
                if path == "/api/admin/users":
                    counts = database.entry_counts(con)
                    return self._send(200, {"users": [accounts.public_user(u, counts.get(u["id"], 0)) for u in accounts.all_users(con)]})
                if path == "/api/admin/system":
                    cfg = config()
                    return self._send(200, {"bot": bot_info(), "urls": app_urls(),
                                            "network": cfg["host"] not in ("127.0.0.1", "localhost")})
            self._send(404, {"error": "not found"})
        finally:
            con.close()

    # --- PUT (save your data) ---
    def _put(self):
        if not self._host_ok() or not self._same_origin():
            return
        if self.path != "/api/data":
            return self._send(404, {"error": "not found"})
        con = db()
        try:
            user = self._user(con)
            if user is None:
                return self._send(401, {"error": "Please log in.", "login": True})
            try:
                data = self._body()
            except Exception:
                return self._send(400, {"error": "invalid JSON"})
            problem = check_data(data)
            if problem:
                return self._send(400, {"error": problem})
            base = self.headers.get("X-Data-Version")
            try:
                with data_lock:
                    version = save_user_data(con, user["id"], data, int(base) if base and base.isdigit() else None)
            except ConflictError:
                return self._send(409, {"error": "Your data was changed on another device.", "conflict": True})
        finally:
            con.close()
        schedule_check()
        self._send(200, {"ok": True}, extra={"X-Data-Version": str(version)})

    # --- POST ---
    def _post(self):
        if not self._host_ok():
            return
        if self.path == "/api/import":
            return self._import()
        if not self._same_origin():
            return
        try:
            body = self._body() if int(self.headers.get("Content-Length") or 0) > 0 else {}
        except Exception:
            return self._send(400, {"error": "Invalid request."})

        con = db()
        try:
            # Without a session
            if self.path == "/api/setup":
                return self._setup(con, body)
            if self.path == "/api/login":
                return self._login(con, body)
            if self.path == "/api/forgot":
                return self._forgot(con, body)
            if self.path == "/api/reset":
                return self._reset(con, body)
            if self.path == "/api/logout":
                accounts.end_session(con, self._token())
                return self._send(200, {"ok": True}, extra={"Set-Cookie": self._cookie("", 0) + "; Max-Age=0"})

            user = self._user(con)
            if user is None:
                return self._send(401, {"error": "Please log in.", "login": True})
            try:
                if self.path == "/api/profile":
                    accounts.update_user(con, user["id"], name=body.get("name", ""))
                    return self._send(200, {"user": accounts.public_user(accounts.get_user(con, user["id"]))})
                if self.path == "/api/change-password":
                    return self._change_password(con, user, body)
                if self.path == "/api/telegram/link":
                    return self._send(200, telegram_link(user["id"]))
                if self.path == "/api/telegram/connect":
                    name = telegram_connect(user["id"])
                    log(f"Telegram connected for {user['username']} ({name})")
                    return self._send(200, {"user": accounts.public_user(accounts.get_user(con, user["id"]))})
                if self.path == "/api/telegram/disconnect":
                    accounts.clear_telegram(con, user["id"])
                    return self._send(200, {"user": accounts.public_user(accounts.get_user(con, user["id"]))})
                if self.path == "/api/test-message":
                    send_message(["🔔 Test message. Your phone reminders are working!"], "Money Tracker", user["telegram_chat_id"])
                    return self._send(200, {"ok": True})
                if self.path.startswith("/api/admin/"):
                    if user["role"] != "admin":
                        return self._send(403, {"error": "Only the admin can do this."})
                    return self._admin(con, user, body)
            except (AuthError, TelegramError) as e:
                return self._send(400, {"error": str(e)})
            self._send(404, {"error": "not found"})
        except (AuthError, TelegramError) as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            log(f"Request failed ({self.path}): {e}")
            return self._send(400, {"error": "Something went wrong. Please try again."})
        finally:
            con.close()

    def _import(self):
        """One-time hand-over from the plain-file version, only on this PC, before any account exists."""
        cors = {"Access-Control-Allow-Origin": "null"}
        if not self._from_this_pc() or os.path.exists(LEGACY_DATA):
            return self._send(409, {"error": "not allowed"}, extra=cors)
        con = db()
        try:
            if accounts.count_users(con):
                return self._send(409, {"error": "already has data"}, extra=cors)
        finally:
            con.close()
        try:
            data = self._body()
        except Exception:
            return self._send(400, {"error": "invalid JSON"}, extra=cors)
        if not valid_data(data):
            return self._send(400, {"error": "invalid data"}, extra=cors)
        save_json(LEGACY_DATA, data)  # picked up when the admin account is created
        return self._send(200, {"ok": True}, extra=cors)

    def _setup(self, con, body):
        if accounts.count_users(con):
            raise AuthError("The admin account already exists. Log in instead.")
        if not self._from_this_pc():
            raise AuthError("Create the admin account on the PC that runs Money Tracker.")
        user_id = accounts.create_user(con, body.get("username", ""), body.get("name", ""), str(body.get("password", "")), role="admin")
        data = load_json(LEGACY_DATA, None)
        if valid_data(data):
            save_user_data(con, user_id, data)
            os.replace(LEGACY_DATA, LEGACY_DATA + ".before-users")
        token, age = accounts.new_session(con, user_id, bool(body.get("remember")))
        log(f"Admin account created: {body.get('username')}")
        return self._send(200, {"user": accounts.public_user(accounts.get_user(con, user_id))},
                          extra={"Set-Cookie": self._cookie(token, age)})

    def _login(self, con, body):
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        # Wrong guesses lock that username for a while (people on one PC share an address,
        # so locking by address would lock everyone out)
        key_user = f"user:{username.lower()}"
        with login_lock:
            check_not_locked(key_user)
            user = accounts.find_user(con, username) if username else None
            if user is None:
                accounts.secret_matches(password, _DUMMY_HASH["salt"], _DUMMY_HASH["hash"], _DUMMY_HASH["rounds"])
            if user is None or not accounts.verify_password(user, password):
                record_failure(key_user, user)
                check_not_locked(key_user)
                raise AuthError("Wrong username or password.")
            if user["disabled"]:
                raise AuthError("This account is disabled. Ask your admin.")
            record_success(key_user)
        token, age = accounts.new_session(con, user["id"], bool(body.get("remember")))
        return self._send(200, {"user": accounts.public_user(accounts.get_user(con, user["id"]))},
                          extra={"Set-Cookie": self._cookie(token, age)})

    def _forgot(self, con, body):
        user = accounts.find_user(con, str(body.get("username", "")))
        generic = {"ok": True, "message": "If that account has Telegram connected, a 6-digit code is on its way. "
                                          "No Telegram? Ask your admin to reset your password."}
        if user is None or user["disabled"] or not user["telegram_chat_id"] or not bot_info()["ready"]:
            return self._send(200, generic)
        code = accounts.new_reset_code(con, user["id"])
        send_message([f"🔑 Your password reset code is {code}",
                      "It expires in 10 minutes. If you didn't ask for this, ignore it — your password stays the same."],
                     "Money Tracker", user["telegram_chat_id"])
        log(f"Password reset code sent to {user['username']}")
        return self._send(200, generic)

    def _reset(self, con, body):
        username = str(body.get("username", "")).strip()
        key = f"user:{username.lower()}"
        with login_lock:
            check_not_locked(key)
            user = accounts.find_user(con, username)
            if user is None or user["disabled"]:
                record_failure(key)
                raise AuthError("Wrong code.")
            try:
                accounts.check_reset_code(con, user["id"], str(body.get("code", "")))
            except AuthError:
                record_failure(key, user)
                raise
            record_success(key)
        accounts.set_password(con, user["id"], str(body.get("password", "")))
        token, age = accounts.new_session(con, user["id"], False)
        log(f"Password reset with Telegram code: {user['username']}")
        notify_user(user, f"🔐 Your Money Tracker password was reset at {dt.datetime.now():%I:%M %p}.")
        return self._send(200, {"user": accounts.public_user(accounts.get_user(con, user["id"]))},
                          extra={"Set-Cookie": self._cookie(token, age)})

    def _change_password(self, con, user, body):
        key = f"user:{user['username'].lower()}"
        with login_lock:
            check_not_locked(key)
            if not accounts.verify_password(user, str(body.get("current", ""))):
                record_failure(key, user)
                raise AuthError("Your current password is wrong.")
            record_success(key)
        accounts.set_password(con, user["id"], str(body.get("password", "")), keep_token=self._token())
        log(f"Password changed: {user['username']}")
        notify_user(user, f"🔐 Your Money Tracker password was changed at {dt.datetime.now():%I:%M %p}.")
        return self._send(200, {"user": accounts.public_user(accounts.get_user(con, user["id"]))})

    def _admin(self, con, admin, body):
        if self.path == "/api/admin/users/create":
            password = str(body.get("password") or accounts.temporary_password())
            user_id = accounts.create_user(con, body.get("username", ""), body.get("name", ""), password,
                                           role=body.get("role", "user"), must_change=True)
            log(f"{admin['username']} added user {body.get('username')}")
            return self._send(200, {"user": accounts.public_user(accounts.get_user(con, user_id)), "password": password,
                                    "urls": app_urls()})
        if self.path == "/api/admin/users/update":
            changes = {k: body[k] for k in ("name", "username", "role", "disabled") if k in body}
            row = accounts.update_user(con, int(body.get("id", 0)), acting_admin_id=admin["id"], **changes)
            log(f"{admin['username']} updated user {row['username']}: {', '.join(changes)}")
            return self._send(200, {"user": accounts.public_user(row)})
        if self.path == "/api/admin/users/reset-password":
            target = accounts.get_user(con, int(body.get("id", 0)))
            if target is None:
                raise AuthError("That user doesn't exist any more.")
            password = str(body.get("password") or accounts.temporary_password())
            accounts.set_password(con, target["id"], password, must_change=True)
            log(f"{admin['username']} reset the password of {target['username']}")
            notify_user(target, f"🔐 Your Money Tracker password was reset by the admin at {dt.datetime.now():%I:%M %p}. "
                                "Ask them for your temporary password; you'll choose a new one when you log in.")
            return self._send(200, {"password": password})
        if self.path == "/api/admin/users/delete":
            row = accounts.delete_user(con, int(body.get("id", 0)), admin["id"])
            folder = os.path.join(ARCHIVE_DIR, row["username"])
            if os.path.isdir(folder) and os.path.dirname(os.path.abspath(folder)) == os.path.abspath(ARCHIVE_DIR):
                shutil.rmtree(folder, ignore_errors=True)
            log(f"{admin['username']} deleted user {row['username']}")
            return self._send(200, {"ok": True})
        if self.path == "/api/admin/telegram/token":
            bot = save_bot_token(str(body.get("token", "")))
            log(f"Telegram bot saved: @{bot}")
            return self._send(200, {"bot": bot_info()})
        if self.path == "/api/admin/telegram/remove":
            save_json(TELEGRAM_FILE, {})
            return self._send(200, {"bot": bot_info()})
        return self._send(404, {"error": "not found"})


class Server(ThreadingHTTPServer):
    # Windows lets several programs share a port when address reuse is on, which would start a
    # second server (and duplicate reminders). Claim the port exclusively.
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve():
    cfg = config()
    migrate_legacy()
    local_url = f"http://127.0.0.1:{cfg['port']}/"
    try:
        httpd = Server((cfg["host"], int(cfg["port"])), Handler)
    except OSError:
        # Already running (e.g. started twice): just open the app
        if "--no-browser" not in sys.argv:
            webbrowser.open(local_url)
        return
    print("Money Tracker is running. Open it at:")
    for url in app_urls():
        print("   ", url)
    print("Keep this window open. Close it to stop Money Tracker.")
    if "--no-browser" not in sys.argv:
        con = db()
        try:
            first = accounts.count_users(con) == 0 and not os.path.exists(LEGACY_DATA)
        finally:
            con.close()
        # First run: open the plain-file version once so it can hand over browser data
        url = Path(BASE, "index.html").as_uri() if first else local_url
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    def check_loop():
        # Every 5 minutes: reminders close to their set time, and months closed soon after midnight on the 1st
        while True:
            try:
                backup_database()
            except Exception as e:
                log(f"Could not back up the database: {e}")
            prune_attempts()
            try:
                close_months()
            except Exception as e:
                log(f"Could not close the month: {e}")
            try:
                check_reminders()
            except Exception as e:
                log(f"Reminder check failed: {e}")
            threading.Event().wait(300)

    threading.Thread(target=check_loop, daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    migrate_legacy()
    if "--check" in sys.argv:
        try:
            backup_database()
        except Exception as e:
            log(f"Could not back up the database: {e}")
        try:
            close_months()
        except Exception as e:
            log(f"Could not close the month: {e}")
        check_reminders()
    elif "--reset-password" in sys.argv:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        con = db()
        try:
            user = accounts.find_user(con, args[0]) if args else \
                con.execute("SELECT * FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()
            if user is None:
                print("No such user.")
                return
            password = accounts.temporary_password()
            accounts.set_password(con, user["id"], password, must_change=True)
            if user["disabled"]:
                accounts.update_user(con, user["id"], disabled=False)
        finally:
            con.close()
        log(f"Temporary password set for {user['username']} with reset_password.bat")
        notify_user(user, f"🔐 A temporary password was set for your account with reset_password.bat at {dt.datetime.now():%I:%M %p}.")
        print(f"\nUsername:            {user['username']}\nTemporary password:  {password}\n"
              "Log in with these; you'll be asked to choose a new password. Your data is safe.")
    elif "--test" in sys.argv:
        con = db()
        try:
            admin = con.execute("SELECT * FROM users WHERE role = 'admin' AND telegram_chat_id IS NOT NULL LIMIT 1").fetchone()
        finally:
            con.close()
        if not admin:
            print("No admin with Telegram connected.")
            return
        send_message(["🔔 Test message. Phone reminders are working!"], "Money Tracker", admin["telegram_chat_id"])
        print("Test message sent on Telegram")
    else:
        serve()


if __name__ == "__main__":
    main()
