# Money Tracker (web)

A web-based app for tracking money coming in and going out, for several people. Each user has their
own expenses, bills, reminders and Excel files; a **system admin** manages the users. Works on phone,
tablet and desktop. Plain HTML, CSS and JavaScript plus a Python server (standard library only,
nothing to install).

## Run it
Double-click `scripts\start.bat`. It starts the server in a small minimized window called
**Money Tracker (keep open)** and opens the app at http://127.0.0.1:8765. Close that window to stop it.
If the server ever stops because of an error, that window stays open and shows the message.

## Folders
| Folder / file | What's in it |
|---|---|
| `index.html` | The app page |
| `assets/` | `app.js` (the app) and `styles.css` (the look) |
| `server/` | The Python server: `server.py` (web server, reminders, monthly close, backups), `accounts.py` (users and logins), `database.py` (entries), `reminders.py` (reminder rules), `excel_export.py` (Excel files) |
| `config/` | `server-config.json` (address, port, backups) and `telegram-config.json` (bot token — keep private) |
| `data/` | `money-tracker.db` (the database), `archive/<username>/` (monthly Excel files), `backups/` (daily database copies), `reminders.log` |
| `scripts/` | `start.bat`, `setup_reminders.bat`, `reset_password.bat` |
| `tests/` | Automated checks: run `python -m unittest discover tests` from the Money Tracker folder |
| `docs/` | This guide |

## Accounts
- **Admin:** the first account (created on first start, or your existing account after the upgrade:
  username **admin**, same password as before). The admin sees the **Users** page.
- **Users:** added by the admin. Each user logs in with their own username and password and only
  sees their own data.

Everyone has a **Profile** page: name, change password, and **Telegram notifications**.
Use the menu (top right) to **Log out**. Tick **Keep me signed in on this device** to stay signed in
for 30 days; otherwise you're signed out when the browser closes (or after 12 hours).

### For the admin: adding a user
1. **Users → Add user**: name, username and role (User or Admin). A temporary password is created.
2. The next screen shows what to give them; **Copy instructions** makes a ready-to-send message with
   the address, username, temporary password and the Telegram steps.
3. On first login they choose their own password, and a banner points them to Telegram setup.

On each user card: **Edit** (name, username, role), **Reset password** (new temporary password; the
user is told on Telegram), **Disable/Enable** (blocks logging in, keeps their data) and **Delete**
(removes the user and all their data). You can't disable, demote or delete yourself, and there is
always at least one active admin.

### Telegram notifications (each user, in Profile)
The admin sets up **one bot** for everyone (Users page → *Telegram bot*: create it with @BotFather,
paste the token). Then each user, in **Profile → Telegram notifications**:
1. Installs Telegram (free, App Store / Google Play) and signs up with their mobile number.
2. Taps **Open the bot in Telegram** (a personal link; on a computer they can send the code shown instead).
3. Taps **Start** in Telegram.
4. Comes back and taps **Connect**. They get "✅ Connected!" in Telegram.

What they receive: bill reminders (on each bill's days and time, an optional early reminder and a
reminder the day after if unpaid), budget alerts, an optional daily nudge, the monthly summary on the
1st, and security messages (password reset codes, password changes, wrong-password warnings).
The Profile page also lists what to check when messages don't arrive.

Run `scripts\setup_reminders.bat` once so Windows checks every 15 minutes even when the app is closed
(the PC must be on and online). To turn it off: `scripts\setup_reminders.bat remove`.

### Forgot password
- **Forgot password?** on the login screen sends a 6-digit code to that user's Telegram (valid 10
  minutes). No Telegram? The admin uses **Reset password** on the user's card.
- Admin locked out and no Telegram? Run `scriptseset_password.bat` on the PC that runs Money Tracker. It sets
  a temporary password (for the admin, or the username you type) and keeps all data.
- After 5 wrong passwords, that account's logins pause for a while and the user gets a Telegram alert.

## Using Money Tracker on other devices (web access)
By default Money Tracker only opens on the PC that runs it. To let people open it from their own
phones and laptops **on the same Wi-Fi**:
1. Open `config\server-config.json` and change `"host": "127.0.0.1"` to `"host": "0.0.0.0"`. Save.
2. Close the **Money Tracker (keep open)** window and run `scripts\start.bat` again.
3. If Windows asks whether to allow Python on networks, allow it for **Private networks** only.
4. The window (and the admin's Users page) shows the address to use, e.g. `http://192.168.1.22:8765/`.

Notes: this PC must stay on. On your Wi-Fi the connection is plain `http` (not encrypted), so only do
this on a home network you trust. To reach it from anywhere on the internet you'd need hosting or an
HTTPS tunnel; set `"public_url"` and `"trust_proxy": true` only when running behind your own HTTPS
proxy/tunnel. To go back to this-PC-only, set `"host"` back to `"127.0.0.1"`.

## Features
- Monthly expenses page: total balance, side-by-side **Expenses** and **In** columns, half-month view
  (**Oct 1–15 / Oct 16–31 / Whole month**) and **Left** = money in − money out
- Bills with reminder days appear at the top of the Expenses column, marked **Paid**, **Due today**,
  **Due in N days** or **Overdue**; click one to record the payment
- Summary: last 6 months in vs. out, spending by category, each with a table view
- **Bills** page: *Money in − Bills paid = Left*, bills paid / still to pay, and a card per bill with an
  **amount per payment**, a **one-time due date** and/or **repeating days** (e.g. 14 & 29) and a time.
  **Paid** records the payment with one click and stays locked until the next reminder is sent
- **Download Excel file** (menu): one month or all months, built from the database
- Export to CSV, download a backup and restore it (same menu)
- Purple and black theme

## Where is the data?
- `data/money-tracker.db` — the **database** (SQLite): users, logins (passwords only as salted
  hashes), each user's settings and every money in / money out. Edits are recorded and deleted entries
  are only marked as deleted.
- On the **1st of every month** each user's previous month is closed: totals go into the database, the
  Excel file is saved as `data/archive/<username>/money-tracker-YYYY-MM.xlsx`, and they get a Telegram
  summary. If the PC was off on the 1st, this happens the next time the server runs.
- **Daily backups:** once a day a copy of the database is saved in `data/backups/` (the newest 14 are
  kept; change `"backups_to_keep"` in `config\server-config.json`). To restore one, stop Money Tracker,
  copy the backup over `data/money-tracker.db`, and start it again.
- Saving from two devices at once can't overwrite each other: if your data was changed on another
  device, Money Tracker loads the latest version and asks you to check your last change.
- `config\server-config.json` — address, port and backups. `config\telegram-config.json` — the bot token.
- `data/backups/*.before-users` are copies of the files from before user accounts were added.
Nothing is uploaded; only Telegram messages leave the PC. Keep your Windows account password-protected too.

## Customizing
- Starting categories for new users: `DEFAULT_CATEGORIES` at the top of `app.js`
- Currency: `currency` in `app.js` and the peso signs in `index.html`, `reminders.py` and `excel_export.py`
- Colors: the variables at the top of `styles.css`
