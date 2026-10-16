"""Data checks, the database and user accounts (uses a temporary folder, never your real data).

Run from the Money Tracker folder:   python -m unittest discover tests
"""

import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))
import accounts  # noqa: E402
import database  # noqa: E402
import server  # noqa: E402


def entry(**changes):
    t = {"id": "a1", "created": 1, "type": "expense", "amount": 12300, "category": "Food", "date": "2026-10-16", "note": "lunch"}
    t.update(changes)
    return t


class DataChecks(unittest.TestCase):
    def test_good_data_passes(self):
        self.assertEqual(server.check_data({"transactions": [entry()]}), "")

    def test_bad_entries_are_refused(self):
        for bad in (entry(amount="12.30"), entry(amount=0), entry(amount=True), entry(date="16/10/2026"),
                    entry(date="2026-02-30"), entry(type="gift"), entry(id=""), entry(note="x" * 2000), entry(dueFor="soon")):
            self.assertNotEqual(server.check_data({"transactions": [bad]}), "", bad)

    def test_bad_reminder_days_are_refused(self):
        cats = {"income": [], "expense": [{"name": "Rent", "icon": "🏠", "reminder": {"days": [32]}}]}
        self.assertNotEqual(server.check_data({"transactions": [], "categories": cats}), "")


class Accounts(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.con = accounts.connect(os.path.join(self.dir, "test.db"))

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_passwords_are_hashed_and_checked(self):
        uid = accounts.create_user(self.con, "maria", "Maria", "Secret-pass-1")
        row = accounts.get_user(self.con, uid)
        self.assertNotIn("Secret-pass-1", str(dict(row)))
        self.assertTrue(accounts.verify_password(row, "Secret-pass-1"))
        self.assertFalse(accounts.verify_password(row, "wrong-pass-1"))

    def test_usernames_are_unique_and_checked(self):
        accounts.create_user(self.con, "maria", "Maria", "Secret-pass-1")
        with self.assertRaises(accounts.AuthError):
            accounts.create_user(self.con, "MARIA", "Other", "Secret-pass-2")
        with self.assertRaises(accounts.AuthError):
            accounts.create_user(self.con, "a b", "Bad", "Secret-pass-2")

    def test_last_admin_is_protected(self):
        admin = accounts.create_user(self.con, "admin", "Admin", "Secret-pass-1", role="admin")
        with self.assertRaises(accounts.AuthError):
            accounts.update_user(self.con, admin, acting_admin_id=admin, disabled=True)
        with self.assertRaises(accounts.AuthError):
            accounts.delete_user(self.con, admin, admin)

    def test_sessions_end_when_disabled(self):
        admin = accounts.create_user(self.con, "admin", "Admin", "Secret-pass-1", role="admin")
        uid = accounts.create_user(self.con, "maria", "Maria", "Secret-pass-1")
        token, _ = accounts.new_session(self.con, uid, False)
        self.assertIsNotNone(accounts.session_user(self.con, token))
        accounts.update_user(self.con, uid, acting_admin_id=admin, disabled=True)
        self.assertIsNone(accounts.session_user(self.con, token))

    def test_saving_from_two_devices_is_detected(self):
        uid = accounts.create_user(self.con, "maria", "Maria", "Secret-pass-1")
        v1 = accounts.save_state(self.con, uid, {"transactions": []})
        accounts.save_state(self.con, uid, {"transactions": [entry()]}, base_version=v1)   # phone saves
        with self.assertRaises(accounts.ConflictError):
            accounts.save_state(self.con, uid, {"transactions": []}, base_version=v1)       # PC still has v1

    def test_users_cannot_touch_each_others_entries(self):
        a = accounts.create_user(self.con, "ana", "Ana", "Secret-pass-1")
        b = accounts.create_user(self.con, "ben", "Ben", "Secret-pass-1")
        database.sync_transactions(self.con, a, [entry(id="x1", amount=500)])
        database.sync_transactions(self.con, b, [entry(id="x1", amount=1)])  # same id from another user
        self.assertEqual(database.active_transactions(self.con, a)[0]["amount"], 500)
        self.assertEqual(database.active_transactions(self.con, b), [])

    def test_deleted_entries_are_kept_as_history(self):
        uid = accounts.create_user(self.con, "ana", "Ana", "Secret-pass-1")
        database.sync_transactions(self.con, uid, [entry()])
        database.sync_transactions(self.con, uid, [])
        self.assertEqual(database.active_transactions(self.con, uid), [])
        self.assertIsNotNone(self.con.execute("SELECT deleted_at FROM transactions WHERE id='a1'").fetchone()[0])

    def test_month_close_happens_once(self):
        uid = accounts.create_user(self.con, "ana", "Ana", "Secret-pass-1")
        database.sync_transactions(self.con, uid, [entry(date="2026-09-10")])
        self.assertEqual(database.months_to_close(self.con, uid, dt.date(2026, 10, 1)), ["2026-09"])
        database.close_month(self.con, uid, "2026-09")
        self.assertEqual(database.months_to_close(self.con, uid, dt.date(2026, 10, 2)), [])


if __name__ == "__main__":
    unittest.main()
