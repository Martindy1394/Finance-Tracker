"""Reminder rules: bill dates, paid/late detection, budget alerts and the daily nudge.

Run from the Money Tracker folder:   python -m unittest discover tests
"""

import datetime as dt
import os
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))
import reminders  # noqa: E402


def data(cats, txs=(), before=3, nudge=False):
    return {"transactions": list(txs), "budgets": {},
            "categories": {"income": [{"name": "Salary", "icon": "💼"}], "expense": cats},
            "reminders": {"enabled": True, "bills": True, "billDaysBefore": before, "budgets": True, "nudge": nudge, "nudgeHour": 20}}


def pay(category, date, **extra):
    return {"id": f"{category}-{date}", "created": 1, "type": "expense", "amount": 100, "category": category, "date": date, **extra}


def texts(d, now, sent=None):
    return [t for _, t in reminders.find_reminders(d, now, sent or {})]


SUNLIFE = {"name": "SunLife", "icon": "📈", "amount": 65000, "reminder": {"days": [14, 29], "time": "09:00"}}


class BillReminders(unittest.TestCase):
    def test_due_today_only_after_its_time(self):
        self.assertFalse(any("today" in t for t in texts(data([SUNLIFE]), dt.datetime(2026, 10, 14, 8, 59))))
        self.assertTrue(any("SunLife is today (Oct 14)" in t for t in texts(data([SUNLIFE]), dt.datetime(2026, 10, 14, 9, 0))))

    def test_early_reminder(self):
        self.assertTrue(any("coming up in 3 days, on Thu, Oct 29" in t for t in texts(data([SUNLIFE]), dt.datetime(2026, 10, 26, 9, 5))))
        self.assertFalse(any("coming up" in t for t in texts(data([SUNLIFE], before=0), dt.datetime(2026, 10, 26, 9, 5))))

    def test_late_the_next_day(self):
        self.assertTrue(any("was due on Oct 14" in t for t in texts(data([SUNLIFE]), dt.datetime(2026, 10, 15, 9, 0))))

    def test_payment_counts_for_one_date_only(self):
        d = data([SUNLIFE], [pay("SunLife", "2026-10-13")])
        self.assertFalse(any("Oct 14" in t for t in texts(d, dt.datetime(2026, 10, 14, 9, 0))))
        self.assertTrue(any("SunLife is today (Oct 29)" in t for t in texts(d, dt.datetime(2026, 10, 29, 9, 0))))

    def test_record_payment_tag_wins(self):
        d = data([SUNLIFE], [pay("SunLife", "2026-10-22", dueFor="2026-10-14")])
        self.assertFalse(any("Oct 14" in t for t in texts(d, dt.datetime(2026, 10, 23, 9, 0))))
        self.assertTrue(any("Oct 29" in t for t in texts(d, dt.datetime(2026, 10, 29, 9, 0))))

    def test_short_months_use_the_last_day(self):
        self.assertTrue(any("SunLife is today (Feb 28)" in t for t in texts(data([SUNLIFE]), dt.datetime(2027, 2, 28, 9, 0))))

    def test_one_time_due_date(self):
        shopee = {"name": "Shopee", "icon": "✂️", "amount": 120000, "reminder": {"days": [], "date": "2026-10-20", "time": "09:00"}}
        self.assertTrue(any("Shopee is today (Oct 20)" in t for t in texts(data([shopee]), dt.datetime(2026, 10, 20, 9, 0))))
        self.assertEqual(texts(data([shopee], [pay("Shopee", "2026-10-19")]), dt.datetime(2026, 10, 20, 9, 0)), [])

    def test_sent_reminders_are_not_repeated(self):
        d = data([SUNLIFE])
        keys = {k: "x" for k, _ in reminders.find_reminders(d, dt.datetime(2026, 10, 14, 9, 0), {})}
        self.assertEqual(reminders.find_reminders(d, dt.datetime(2026, 10, 14, 9, 0), keys), [])


class BudgetsAndNudge(unittest.TestCase):
    def test_monthly_limit_is_amount_times_payments(self):
        self.assertEqual(reminders.monthly_limit(SUNLIFE, {}, dt.date(2026, 10, 16)), 130000)

    def test_over_budget_alert(self):
        d = data([SUNLIFE], [dict(pay("SunLife", "2026-10-14"), amount=140000)])
        self.assertTrue(any("Over budget on SunLife" in t for t in texts(d, dt.datetime(2026, 10, 16, 9, 0))))

    def test_plain_category_gets_80_percent_alert(self):
        food = {"name": "Food", "icon": "🍔", "amount": 400000}
        d = data([food], [dict(pay("Food", "2026-10-05"), amount=340000)])
        self.assertTrue(any("Food is at 85%" in t for t in texts(d, dt.datetime(2026, 10, 16, 9, 0))))

    def test_daily_nudge_after_its_hour(self):
        d = data([], nudge=True)
        self.assertFalse(any("haven't recorded" in t for t in texts(d, dt.datetime(2026, 10, 16, 19, 0))))
        self.assertTrue(any("haven't recorded" in t for t in texts(d, dt.datetime(2026, 10, 16, 20, 5))))


if __name__ == "__main__":
    unittest.main()
