"""Reminder rules for Money Tracker (no I/O): which bills are due, paid or late, budget alerts
and the daily nudge. app.js uses the same rules on the Expenses and Bills pages."""

import calendar
import datetime as dt
def peso(cents):
    return f"₱{cents / 100:,.2f}"


def ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def category_schedule(c):
    """Repeating days (1-31), reminder time and one-time due date of a spending category.

    Supports the older single dueDay."""
    r = c.get("reminder") or {}
    raw_days = r.get("days") or ([c["dueDay"]] if c.get("dueDay") else [])
    days = sorted({int(d) for d in raw_days if str(d).isdigit() and 1 <= int(d) <= 31})
    try:
        hour, minute = (int(x) for x in str(r.get("time") or "09:00").split(":")[:2])
        at = dt.time(hour, minute)
    except ValueError:
        at = dt.time(9, 0)
    try:
        one_time = dt.date.fromisoformat(r["date"]) if r.get("date") else None
    except ValueError:
        one_time = None
    return days, at, one_time


def category_dates(c, today, months=(-1, 0, 1)):
    """Scheduled dates around this month (repeating days) plus the one-time date."""
    days, _, one_time = category_schedule(c)
    dates = {d for offset in months for d in occurrences(days, *shift_month(today, offset))}
    if one_time:
        dates.add(one_time)
    return sorted(dates)


def category_amount(c, budgets):
    """Amount per payment; older data kept a monthly budget per category instead."""
    if c.get("amount"):
        return int(c["amount"])
    budget = budgets.get(c.get("name"), 0)
    if budget:
        days, _, _ = category_schedule(c)
        return round(budget / max(1, len(days)))
    return 0


def monthly_limit(c, budgets, today):
    """Amount per payment x payments due this month (one, if nothing is scheduled)."""
    amount = category_amount(c, budgets)
    if not amount:
        return 0
    days, _, one_time = category_schedule(c)
    if not days and not one_time:
        return amount
    month = today.strftime("%Y-%m")
    return amount * sum(1 for d in category_dates(c, today, (0,)) if d.isoformat().startswith(month))


def shift_month(day, offset):
    month_index = day.year * 12 + day.month - 1 + offset
    return month_index // 12, month_index % 12 + 1


def occurrences(days, year, month):
    """Dates in a month for the chosen days; e.g. the 31st falls on the 30th in a 30-day month."""
    last = calendar.monthrange(year, month)[1]
    return {dt.date(year, month, min(d, last)) for d in days}


def assign_payments(dates, payments):
    """Which reminder date each payment is for -> {due date: payment}.

    A payment made with "Record payment" remembers its due date (dueFor); any other payment
    counts for the nearest unpaid reminder date around it. app.js uses the same rule.
    """
    paid_for, rest = {}, []
    for t in sorted(payments, key=lambda t: (t.get("date", ""), t.get("created", 0))):
        due_for = t.get("dueFor")
        if due_for in dates and due_for not in paid_for:
            paid_for[due_for] = t
        else:
            rest.append(t)
    gap = lambda a, b: abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)
    for t in rest:
        p = t["date"]
        before = [d for d in dates if d <= p]
        after = [d for d in dates if d > p]
        options = sorted([x for x in (before[-1] if before else None, after[0] if after else None) if x], key=lambda d: gap(d, p))
        due = next((d for d in options if d not in paid_for), None)
        if due:
            paid_for[due] = t
    return paid_for


def month_schedule(data, today):
    """This month's scheduled payments with their status (same rules as the Expenses page)."""
    txs = [t for t in data.get("transactions", []) if isinstance(t, dict) and t.get("date")]
    budgets = data.get("budgets") or {}
    rows = []
    month = today.strftime("%Y-%m")
    for c in (data.get("categories") or {}).get("expense", []):
        occ = category_dates(c, today)
        if not occ:
            continue
        name = c.get("name", "")
        this_month = [d for d in occ if d.isoformat().startswith(month)]
        paid_for = assign_payments([d.isoformat() for d in occ],
                                   [t for t in txs if t.get("type") == "expense" and t.get("category") == name])
        expected = category_amount(c, budgets)
        for due in this_month:
            paid = paid_for.get(due.isoformat())
            status = "Paid" if paid else "Overdue" if due < today else "Due today" if due == today else "Upcoming"
            rows.append({"category": name, "due": due.isoformat(), "expected": expected, "status": status,
                         "paid_on": paid["date"] if paid else None, "paid_amount": paid["amount"] if paid else None})
    return sorted(rows, key=lambda r: (r["due"], r["category"]))


def find_reminders(data, now, sent):
    """Return [(key, text)] for reminders that are due and not sent yet."""
    rem = data.get("reminders") or {}
    today = now.date()
    month = today.strftime("%Y-%m")
    txs = [t for t in data.get("transactions", []) if isinstance(t, dict)]
    month_tx = [t for t in txs if str(t.get("date", "")).startswith(month)]
    expense_cats = (data.get("categories") or {}).get("expense", [])
    found = []

    spent = {}
    for t in month_tx:
        if t.get("type") == "expense":
            spent[t.get("category")] = spent.get(t.get("category"), 0) + int(t.get("amount", 0))

    if rem.get("bills", True):
        days_before = int(rem.get("billDaysBefore", 3))
        for c in expense_cats:
            _, at, _ = category_schedule(c)
            # Dates from last month to two months ahead (periods can cross month ends) + one-time date
            occ = category_dates(c, today, (-1, 0, 1, 2))
            if not occ:
                continue
            name, icon = c.get("name", ""), c.get("icon", "")
            payments = [t for t in txs if t.get("type") == "expense" and t.get("category") == name
                        and str(t.get("date", "")) <= today.isoformat()]
            paid_for = assign_payments([d.isoformat() for d in occ], payments)
            occ = [dt.date.min] + occ + [dt.date.max]  # open ends so every date has neighbours
            for prev, due, nxt in zip(occ, occ[1:], occ[2:]):
                def paid_by(limit, due=due):
                    p = paid_for.get(due.isoformat())
                    return bool(p) and p["date"] <= limit.isoformat()
                key = f"bill|{name}|{due.isoformat()}"
                early = due - dt.timedelta(days=days_before)
                if days_before and early <= today < due and now >= dt.datetime.combine(early, at) and not paid_by(today):
                    n = (due - today).days
                    found.append((key + "|before", f"{icon} {name} is coming up in {n} day{'s' if n > 1 else ''}, on {due:%a, %b %d}."))
                elif today == due and now >= dt.datetime.combine(due, at) and not paid_by(today):
                    found.append((key + "|due", f"{icon} Reminder: {name} is today ({due:%b %d}) and isn't recorded as paid yet."))
                elif due < today < nxt and now >= dt.datetime.combine(due + dt.timedelta(days=1), at) and not paid_by(today):
                    found.append((key + "|late", f"{icon} {name} was due on {due:%b %d} ({ordinal(due.day)}) and still isn't recorded as paid."))

    if rem.get("budgets", True):
        budgets = data.get("budgets") or {}
        for c in expense_cats:
            name, icon = c.get("name", ""), c.get("icon", "")
            budget = monthly_limit(c, budgets, today)
            if budget <= 0:
                continue
            s = spent.get(name, 0)
            if s > budget:
                found.append((f"budget|{name}|{month}|over", f"{icon} Over budget on {name}: spent {peso(s)} of {peso(budget)} ({peso(s - budget)} over)."))
            elif s >= budget * 0.8 and f"budget|{name}|{month}|over" not in sent and not any(category_schedule(c)[::2]):
                # (scheduled bills only alert when over: paying them in full is the plan)
                found.append((f"budget|{name}|{month}|80", f"{icon} {name} is at {round(s / budget * 100)}% of its budget: {peso(s)} of {peso(budget)} ({peso(budget - s)} left)."))

    if rem.get("nudge", True) and now.hour >= int(rem.get("nudgeHour", 20)):
        if not any(t.get("date") == today.isoformat() for t in txs):
            found.append((f"nudge|{today.isoformat()}", "📝 You haven't recorded any money in or out today. Take a minute to log today's spending."))

    return [(k, text) for k, text in found if k not in sent]
