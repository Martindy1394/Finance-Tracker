"""Users, logins and each user's app data (SQLite, Python standard library).

Roles: 'admin' (manages users and the Telegram bot) and 'user'. Passwords are stored only as
salted PBKDF2 hashes. Each user's categories, bills and settings are kept in `user_state`;
their money in / money out also goes to the `transactions` table (see database.py).
"""

import datetime as dt
import hashlib
import hmac
import json
import re
import secrets

import database

PBKDF2_ROUNDS = 300_000
REMEMBER_DAYS = 30
SESSION_HOURS = 12
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,30}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    username         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name             TEXT NOT NULL,
    role             TEXT NOT NULL DEFAULT 'user',      -- 'admin' or 'user'
    pw_salt          TEXT NOT NULL,
    pw_hash          TEXT NOT NULL,
    pw_rounds        INTEGER NOT NULL,
    must_change      INTEGER NOT NULL DEFAULT 0,        -- temporary password set by the admin
    disabled         INTEGER NOT NULL DEFAULT 0,
    telegram_chat_id INTEGER,
    telegram_name    TEXT,
    telegram_code    TEXT,                               -- one-time code for linking Telegram
    created_at       TEXT NOT NULL,
    last_login       TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    expires    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_state (
    user_id    INTEGER PRIMARY KEY,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version    INTEGER NOT NULL DEFAULT 0     -- goes up on every save (detects edits from two devices)
);
CREATE TABLE IF NOT EXISTS telegram_starts (
    code    TEXT PRIMARY KEY,                  -- the code from t.me/<bot>?start=<code>
    chat_id INTEGER NOT NULL,
    name    TEXT,
    seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reset_codes (
    user_id INTEGER PRIMARY KEY,
    salt    TEXT NOT NULL,
    hash    TEXT NOT NULL,
    rounds  INTEGER NOT NULL,
    expires TEXT NOT NULL,
    sent    TEXT NOT NULL,
    tries   INTEGER NOT NULL DEFAULT 0
);
"""


class AuthError(Exception):
    pass


class ConflictError(Exception):
    """The data was saved from another device after this one loaded it."""


def connect(path):
    con = database.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(user_state)")}
    if cols and "version" not in cols:
        con.execute("ALTER TABLE user_state ADD COLUMN version INTEGER NOT NULL DEFAULT 0")
    con.executescript(SCHEMA)
    return con


def now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


# ---------- Secrets ----------
def hash_secret(secret, salt=None, rounds=PBKDF2_ROUNDS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), bytes.fromhex(salt), rounds).hex()
    return {"salt": salt, "hash": digest, "rounds": rounds}


def secret_matches(secret, salt, digest, rounds):
    test = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), bytes.fromhex(salt), rounds).hex()
    return hmac.compare_digest(test, digest)


def check_password_rules(password):
    if len(password) < 8:
        raise AuthError("Use at least 8 characters for the password.")
    if len(password) > 200:
        raise AuthError("That password is too long.")


def token_key(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def temporary_password():
    """Easy-to-read temporary password for a new user, e.g. 'mango-4821-river'."""
    words = ["mango", "river", "cloud", "pearl", "tiger", "lemon", "maple", "coral", "amber", "sunny",
             "ocean", "piano", "cocoa", "berry", "lotus", "falcon", "jade", "orbit", "violet", "honey"]
    return f"{secrets.choice(words)}-{secrets.randbelow(9000) + 1000}-{secrets.choice(words)}"


# ---------- Users ----------
def public_user(row, entries=None):
    if row is None:
        return None
    out = {
        "id": row["id"], "username": row["username"], "name": row["name"], "role": row["role"],
        "disabled": bool(row["disabled"]), "mustChange": bool(row["must_change"]),
        "telegram": {"connected": row["telegram_chat_id"] is not None, "name": row["telegram_name"] or ""},
        "createdAt": row["created_at"], "lastLogin": row["last_login"],
    }
    if entries is not None:
        out["entries"] = entries
    return out


def count_users(con):
    return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def get_user(con, user_id):
    return con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def find_user(con, username):
    return con.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username.strip(),)).fetchone()


def all_users(con):
    return con.execute("SELECT * FROM users ORDER BY role = 'admin' DESC, name COLLATE NOCASE").fetchall()


def check_username(con, username, user_id=None):
    username = username.strip()
    if not USERNAME_RE.match(username):
        raise AuthError("Usernames are 3–30 characters: letters, numbers, dots, dashes or underscores.")
    other = find_user(con, username)
    if other and other["id"] != user_id:
        raise AuthError(f"The username “{username}” is already taken.")
    return username


def check_name(name):
    name = " ".join(str(name).split())
    if not 1 <= len(name) <= 60:
        raise AuthError("Enter a name (up to 60 characters).")
    return name


def create_user(con, username, name, password, role="user", must_change=False, stored_hash=None):
    username = check_username(con, username)
    name = check_name(name)
    if role not in ("admin", "user"):
        raise AuthError("Unknown role.")
    if stored_hash is None:
        check_password_rules(password)
        stored_hash = hash_secret(password)
    cur = con.execute(
        "INSERT INTO users (username, name, role, pw_salt, pw_hash, pw_rounds, must_change, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (username, name, role, stored_hash["salt"], stored_hash["hash"], stored_hash.get("rounds", PBKDF2_ROUNDS),
         int(must_change), now_iso()))
    con.commit()
    return cur.lastrowid


def active_admins(con, exclude=None):
    return con.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled = 0 AND id != ?",
                       (exclude or 0,)).fetchone()[0]


def update_user(con, user_id, acting_admin_id=None, **changes):
    row = get_user(con, user_id)
    if row is None:
        raise AuthError("That user doesn't exist any more.")
    fields = {}
    if "name" in changes:
        fields["name"] = check_name(changes["name"])
    if "username" in changes:
        fields["username"] = check_username(con, changes["username"], user_id)
    if "role" in changes:
        if changes["role"] not in ("admin", "user"):
            raise AuthError("Unknown role.")
        if row["role"] == "admin" and changes["role"] != "admin":
            if user_id == acting_admin_id:
                raise AuthError("You can't remove your own admin role.")
            if not active_admins(con, exclude=user_id):
                raise AuthError("Keep at least one active admin.")
        fields["role"] = changes["role"]
    if "disabled" in changes:
        disabled = bool(changes["disabled"])
        if disabled and user_id == acting_admin_id:
            raise AuthError("You can't disable your own account.")
        if disabled and row["role"] == "admin" and not active_admins(con, exclude=user_id):
            raise AuthError("Keep at least one active admin.")
        fields["disabled"] = int(disabled)
    if fields:
        con.execute(f"UPDATE users SET {', '.join(k + ' = ?' for k in fields)} WHERE id = ?", (*fields.values(), user_id))
        if fields.get("disabled"):
            end_sessions(con, user_id)
        con.commit()
    return get_user(con, user_id)


def delete_user(con, user_id, acting_admin_id):
    row = get_user(con, user_id)
    if row is None:
        raise AuthError("That user doesn't exist any more.")
    if user_id == acting_admin_id:
        raise AuthError("You can't delete your own account.")
    if row["role"] == "admin" and not active_admins(con, exclude=user_id):
        raise AuthError("Keep at least one active admin.")
    for table in ("sessions", "user_state", "reset_codes"):
        con.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    con.execute("DELETE FROM users WHERE id = ?", (user_id,))
    database.delete_user_rows(con, user_id)
    con.commit()
    return row


def verify_password(row, password):
    return secret_matches(password, row["pw_salt"], row["pw_hash"], row["pw_rounds"])


def set_password(con, user_id, password, must_change=False, keep_token=None):
    check_password_rules(password)
    h = hash_secret(password)
    con.execute("UPDATE users SET pw_salt = ?, pw_hash = ?, pw_rounds = ?, must_change = ? WHERE id = ?",
                (h["salt"], h["hash"], h["rounds"], int(must_change), user_id))
    end_sessions(con, user_id, keep=keep_token)
    con.execute("DELETE FROM reset_codes WHERE user_id = ?", (user_id,))
    con.commit()


# ---------- Sessions ----------
def new_session(con, user_id, remember):
    token = secrets.token_urlsafe(32)
    expires = dt.datetime.now() + (dt.timedelta(days=REMEMBER_DAYS) if remember else dt.timedelta(hours=SESSION_HOURS))
    con.execute("DELETE FROM sessions WHERE expires < ?", (now_iso(),))
    con.execute("INSERT INTO sessions (token_hash, user_id, expires) VALUES (?, ?, ?)",
                (token_key(token), user_id, expires.isoformat(timespec="seconds")))
    con.execute("UPDATE users SET last_login = ? WHERE id = ?", (now_iso(), user_id))
    con.commit()
    return token, (REMEMBER_DAYS * 86400 if remember else None)


def session_user(con, token):
    if not token:
        return None
    row = con.execute(
        "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id"
        " WHERE sessions.token_hash = ? AND sessions.expires > ? AND users.disabled = 0",
        (token_key(token), now_iso())).fetchone()
    return row


def end_session(con, token):
    con.execute("DELETE FROM sessions WHERE token_hash = ?", (token_key(token or ""),))
    con.commit()


def end_sessions(con, user_id, keep=None):
    con.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user_id, token_key(keep) if keep else ""))


# ---------- App data per user ----------
def load_state(con, user_id):
    row = con.execute("SELECT data FROM user_state WHERE user_id = ?", (user_id,)).fetchone()
    return json.loads(row["data"]) if row else None


def state_version(con, user_id):
    row = con.execute("SELECT version FROM user_state WHERE user_id = ?", (user_id,)).fetchone()
    return row["version"] if row else 0


def save_state(con, user_id, data, base_version=None):
    """Save a user's data. With base_version, refuse if it was saved elsewhere in the meantime.
    Returns the new version."""
    current = state_version(con, user_id)
    if base_version is not None and base_version != current:
        raise ConflictError()
    con.execute("INSERT INTO user_state (user_id, data, updated_at, version) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at,"
                " version = excluded.version",
                (user_id, json.dumps(data, ensure_ascii=False), now_iso(), current + 1))
    con.commit()
    return current + 1


# ---------- Password reset codes (sent on Telegram) ----------
def new_reset_code(con, user_id):
    row = con.execute("SELECT sent FROM reset_codes WHERE user_id = ?", (user_id,)).fetchone()
    if row and (dt.datetime.now() - dt.datetime.fromisoformat(row["sent"])).total_seconds() < 60:
        raise AuthError("A code was just sent. Wait a minute before asking for another.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    h = hash_secret(code)
    con.execute("INSERT OR REPLACE INTO reset_codes (user_id, salt, hash, rounds, expires, sent, tries) VALUES (?, ?, ?, ?, ?, ?, 0)",
                (user_id, h["salt"], h["hash"], h["rounds"],
                 (dt.datetime.now() + dt.timedelta(minutes=10)).isoformat(timespec="seconds"), now_iso()))
    con.commit()
    return code


def check_reset_code(con, user_id, code):
    row = con.execute("SELECT * FROM reset_codes WHERE user_id = ?", (user_id,)).fetchone()
    if not row or row["expires"] < now_iso():
        raise AuthError("That code has expired. Ask for a new one.")
    if not secret_matches(code.strip(), row["salt"], row["hash"], row["rounds"]):
        tries = row["tries"] + 1
        if tries >= 5:
            con.execute("DELETE FROM reset_codes WHERE user_id = ?", (user_id,))
        else:
            con.execute("UPDATE reset_codes SET tries = ? WHERE user_id = ?", (tries, user_id))
        con.commit()
        raise AuthError("Wrong code." + (" Ask for a new one." if tries >= 5 else ""))


# ---------- Telegram link per user ----------
def new_telegram_code(con, user_id):
    code = secrets.token_hex(4)  # 8 characters, used as t.me/<bot>?start=<code>
    con.execute("UPDATE users SET telegram_code = ? WHERE id = ?", (code, user_id))
    con.commit()
    return code


def set_telegram(con, user_id, chat_id, name):
    # One Telegram chat belongs to one account
    con.execute("UPDATE users SET telegram_chat_id = NULL, telegram_name = NULL WHERE telegram_chat_id = ? AND id != ?",
                (chat_id, user_id))
    con.execute("UPDATE users SET telegram_chat_id = ?, telegram_name = ?, telegram_code = NULL WHERE id = ?",
                (chat_id, name, user_id))
    con.commit()


def remember_telegram_start(con, code, chat_id, name):
    con.execute("INSERT OR REPLACE INTO telegram_starts (code, chat_id, name, seen_at) VALUES (?, ?, ?, ?)",
                (code, chat_id, name, now_iso()))
    # Forget Start messages older than a week
    con.execute("DELETE FROM telegram_starts WHERE seen_at < ?",
                ((dt.datetime.now() - dt.timedelta(days=7)).isoformat(timespec="seconds"),))
    con.commit()


def telegram_start_for(con, code):
    return con.execute("SELECT * FROM telegram_starts WHERE code = ?", (code,)).fetchone()


def clear_telegram(con, user_id):
    con.execute("UPDATE users SET telegram_chat_id = NULL, telegram_name = NULL, telegram_code = NULL WHERE id = ?", (user_id,))
    con.commit()
