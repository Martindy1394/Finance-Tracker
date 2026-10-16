"""Money Tracker database (SQLite, Python standard library).

Every money in / money out of every user is stored in the `transactions` table. Edits update
the row and deletions only mark it (deleted_at), so the history is kept. When a month ends, a
summary row is added to `monthly_closings`. Users, logins and settings live in accounts.py.
"""

import calendar
import datetime as dt
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL DEFAULT 1,
    type        TEXT NOT NULL,            -- 'income' or 'expense'
    category    TEXT NOT NULL,
    amount      INTEGER NOT NULL,         -- centavos
    date        TEXT NOT NULL,            -- YYYY-MM-DD
    note        TEXT NOT NULL DEFAULT '',
    due_for     TEXT,                     -- bill due date this payment is for
    created_ms  INTEGER,
    saved_at    TEXT NOT NULL,            -- first saved
    updated_at  TEXT NOT NULL,            -- last changed
    deleted_at  TEXT                      -- set when deleted in the app
);
CREATE INDEX IF NOT EXISTS transactions_date ON transactions(date);
CREATE TABLE IF NOT EXISTS monthly_closings (
    user_id      INTEGER NOT NULL DEFAULT 1,
    month        TEXT NOT NULL,           -- YYYY-MM
    money_in     INTEGER NOT NULL,
    money_out    INTEGER NOT NULL,
    left_amount  INTEGER NOT NULL,
    entries      INTEGER NOT NULL,
    closed_at    TEXT NOT NULL,
    archive_file TEXT,
    PRIMARY KEY (user_id, month)
);
"""

FIELDS = ("type", "category", "amount", "date", "note", "due_for", "created_ms")


def connect(path):
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    _upgrade(con)
    con.executescript(SCHEMA)
    con.execute("CREATE INDEX IF NOT EXISTS transactions_user ON transactions(user_id, date)")
    return con


def _upgrade(con):
    """Databases from the single-user version: give existing rows to user 1 (the admin)."""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "transactions" in tables:
        cols = {r[1] for r in con.execute("PRAGMA table_info(transactions)")}
        if "user_id" not in cols:
            con.execute("ALTER TABLE transactions ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
    if "monthly_closings" in tables:
        cols = {r[1] for r in con.execute("PRAGMA table_info(monthly_closings)")}
        if "user_id" not in cols:
            con.executescript(
                "ALTER TABLE monthly_closings RENAME TO monthly_closings_old;"
                "CREATE TABLE monthly_closings (user_id INTEGER NOT NULL DEFAULT 1, month TEXT NOT NULL,"
                " money_in INTEGER NOT NULL, money_out INTEGER NOT NULL, left_amount INTEGER NOT NULL,"
                " entries INTEGER NOT NULL, closed_at TEXT NOT NULL, archive_file TEXT, PRIMARY KEY (user_id, month));"
                "INSERT INTO monthly_closings (user_id, month, money_in, money_out, left_amount, entries, closed_at, archive_file)"
                " SELECT 1, month, money_in, money_out, left_amount, entries, closed_at, archive_file FROM monthly_closings_old;"
                "DROP TABLE monthly_closings_old;")
    con.commit()


def _row_values(t):
    return {
        "type": t.get("type", ""),
        "category": t.get("category", ""),
        "amount": int(t.get("amount", 0)),
        "date": t.get("date", ""),
        "note": t.get("note") or "",
        "due_for": t.get("dueFor"),
        "created_ms": t.get("created"),
    }


def sync_transactions(con, user_id, transactions, now=None):
    """Make the database match a user's current list. Returns (added, changed, deleted)."""
    now = (now or dt.datetime.now()).isoformat(timespec="seconds")
    existing = {r["id"]: r for r in con.execute("SELECT * FROM transactions WHERE user_id = ?", (user_id,))}
    taken = {r[0] for r in con.execute("SELECT id FROM transactions WHERE user_id != ?", (user_id,))}
    added = changed = deleted = 0
    seen = set()
    for t in transactions:
        if not isinstance(t, dict) or not t.get("id") or not t.get("date"):
            continue
        tid = str(t["id"])
        if tid in taken:  # never touch another user's row
            continue
        seen.add(tid)
        values = _row_values(t)
        row = existing.get(tid)
        if row is None:
            con.execute(
                "INSERT INTO transactions (id, user_id, type, category, amount, date, note, due_for, created_ms, saved_at, updated_at)"
                " VALUES (:id, :uid, :type, :category, :amount, :date, :note, :due_for, :created_ms, :now, :now)",
                {"id": tid, "uid": user_id, "now": now, **values})
            added += 1
        elif row["deleted_at"] or any(row[k] != values[k] for k in FIELDS):
            con.execute(
                "UPDATE transactions SET type=:type, category=:category, amount=:amount, date=:date, note=:note,"
                " due_for=:due_for, created_ms=:created_ms, updated_at=:now, deleted_at=NULL WHERE id=:id",
                {"id": tid, "now": now, **values})
            changed += 1
    for tid, row in existing.items():
        if tid not in seen and not row["deleted_at"]:
            con.execute("UPDATE transactions SET deleted_at=?, updated_at=? WHERE id=?", (now, now, tid))
            deleted += 1
    con.commit()
    return added, changed, deleted


def active_transactions(con, user_id, month=None):
    """A user's transactions in the app's format (not deleted), optionally for one month (YYYY-MM)."""
    sql = "SELECT * FROM transactions WHERE deleted_at IS NULL AND user_id = ?"
    args = (user_id,)
    if month:
        sql += " AND substr(date, 1, 7) = ?"
        args = (user_id, month)
    rows = con.execute(sql + " ORDER BY date, created_ms", args).fetchall()
    out = []
    for r in rows:
        t = {"id": r["id"], "type": r["type"], "category": r["category"], "amount": r["amount"],
             "date": r["date"], "note": r["note"], "created": r["created_ms"]}
        if r["due_for"]:
            t["dueFor"] = r["due_for"]
        out.append(t)
    return out


def month_totals(con, user_id, month):
    row = con.execute(
        "SELECT COALESCE(SUM(CASE WHEN type='income' THEN amount END), 0) AS money_in,"
        "       COALESCE(SUM(CASE WHEN type='expense' THEN amount END), 0) AS money_out,"
        "       COUNT(*) AS entries"
        " FROM transactions WHERE deleted_at IS NULL AND user_id = ? AND substr(date, 1, 7) = ?", (user_id, month)).fetchone()
    return row["money_in"], row["money_out"], row["entries"]


def months(con, user_id, today):
    """A user's months with entries or a closing, plus the current month, newest first."""
    keys = {r[0] for r in con.execute(
        "SELECT DISTINCT substr(date, 1, 7) FROM transactions WHERE deleted_at IS NULL AND user_id = ?", (user_id,))}
    closings = {r["month"]: r for r in con.execute("SELECT * FROM monthly_closings WHERE user_id = ?", (user_id,))}
    keys |= set(closings) | {today.strftime("%Y-%m")}
    out = []
    for key in sorted(keys, reverse=True):
        money_in, money_out, entries = month_totals(con, user_id, key)
        y, m = map(int, key.split("-"))
        out.append({"month": key, "label": f"{calendar.month_name[m]} {y}", "closed": key in closings,
                    "moneyIn": money_in, "moneyOut": money_out, "left": money_in - money_out, "entries": entries})
    return out


def months_to_close(con, user_id, today):
    """A user's past months that have entries but no closing yet (oldest first)."""
    current = today.strftime("%Y-%m")
    closed = {r[0] for r in con.execute("SELECT month FROM monthly_closings WHERE user_id = ?", (user_id,))}
    keys = {r[0] for r in con.execute(
        "SELECT DISTINCT substr(date, 1, 7) FROM transactions WHERE deleted_at IS NULL AND user_id = ?", (user_id,))}
    return sorted(k for k in keys if k < current and k not in closed)


def close_month(con, user_id, month, archive_file=None, now=None):
    money_in, money_out, entries = month_totals(con, user_id, month)
    con.execute(
        "INSERT OR IGNORE INTO monthly_closings (user_id, month, money_in, money_out, left_amount, entries, closed_at, archive_file)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, month, money_in, money_out, money_in - money_out, entries,
         (now or dt.datetime.now()).isoformat(timespec="seconds"), archive_file))
    con.commit()
    return {"month": month, "moneyIn": money_in, "moneyOut": money_out, "left": money_in - money_out, "entries": entries}


def entry_counts(con):
    """{user_id: number of entries} for the admin's user list."""
    return {r[0]: r[1] for r in con.execute(
        "SELECT user_id, COUNT(*) FROM transactions WHERE deleted_at IS NULL GROUP BY user_id")}


def delete_user_rows(con, user_id):
    con.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
    con.execute("DELETE FROM monthly_closings WHERE user_id = ?", (user_id,))
    con.commit()
