'use strict';

// ---------- Config ----------
const STORAGE_KEY = 'money-tracker.v1';

// Starting categories; the user can add, rename and delete them on the Budgets page
const DEFAULT_CATEGORIES = {
  income: [
    { name: 'Salary', icon: '💼' },
    { name: 'Business', icon: '🏪' },
    { name: 'Freelance', icon: '💻' },
    { name: 'Gift', icon: '🎁' },
    { name: 'Interest', icon: '🏦' },
    { name: 'Other income', icon: '💰' },
  ],
  expense: [
    { name: 'Food', icon: '🍔' },
    { name: 'Groceries', icon: '🛒' },
    { name: 'Transport', icon: '🚌' },
    { name: 'Rent', icon: '🏠' },
    { name: 'Bills', icon: '💡' },
    { name: 'Shopping', icon: '🛍️' },
    { name: 'Health', icon: '💊' },
    { name: 'Entertainment', icon: '🎬' },
    { name: 'Education', icon: '📚' },
    { name: 'Other expense', icon: '📦' },
  ],
};

const ICON_CHOICES = [
  '🍔', '🍜', '☕', '🧋', '🛒', '🚌', '🚗', '⛽', '🏍️', '🏠', '💡', '💧',
  '📱', '🌐', '🛍️', '👕', '💊', '🏥', '🎬', '🎮', '📚', '🎓', '👶', '🐶',
  '✂️', '🎁', '✈️', '💳', '🙏', '💼', '💻', '🏪', '🏦', '📈', '💰', '📦',
];

const currency = new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP' });
const monthFmt = new Intl.DateTimeFormat('en-PH', { month: 'long', year: 'numeric' });
const shortMonthFmt = new Intl.DateTimeFormat('en-PH', { month: 'short' });
const monthNameFmt = new Intl.DateTimeFormat('en-PH', { month: 'long' });
const shortDateFmt = new Intl.DateTimeFormat('en-PH', { month: 'short', day: 'numeric', year: 'numeric' });
const monthDayFmt = new Intl.DateTimeFormat('en-PH', { month: 'short', day: 'numeric' });
const dayFmt = new Intl.DateTimeFormat('en-PH', { weekday: 'short', month: 'short', day: 'numeric' });

// ---------- Helpers ----------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = (cents) => currency.format(cents / 100);
const signed = (cents) => (cents < 0 ? '−' : '+') + money(Math.abs(cents));

function compact(cents) {
  const v = Math.abs(cents / 100);
  const sign = cents < 0 ? '−' : '';
  if (v >= 1e6) return `${sign}₱${+(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${sign}₱${+(v / 1e3).toFixed(1)}K`;
  return `${sign}₱${Math.round(v)}`;
}

function ordinal(n) {
  const s = n % 100 >= 11 && n % 100 <= 13 ? 'th' : { 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th';
  return n + s;
}

function formatTime(hhmm) {
  const [h, m] = hhmm.split(':').map(Number);
  return `${h % 12 || 12}:${pad(m)} ${h < 12 ? 'AM' : 'PM'}`;
}

function describeSchedule(r) {
  if (!r) return '';
  const parts = [];
  if (r.days && r.days.length) {
    const days = [...r.days].sort((a, b) => a - b).map(ordinal);
    parts.push(`Every ${days.length === 1 ? days[0] : `${days.slice(0, -1).join(', ')} & ${days[days.length - 1]}`}`);
  }
  if (r.date) parts.push(`${parts.length ? 'once on' : 'Once on'} ${shortDateFmt.format(parseISODate(r.date))}`);
  return parts.length ? `${parts.join(', ')} · ${formatTime(r.time || '09:00')}` : '';
}

function hasSchedule(c) {
  return !!(c && c.reminder && ((c.reminder.days && c.reminder.days.length) || c.reminder.date));
}

function pad(n) { return String(n).padStart(2, '0'); }
function toISODate(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
function parseISODate(s) { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); }
function monthKey(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`; }
function addMonths(d, n) { return new Date(d.getFullYear(), d.getMonth() + n, 1); }

function parseAmount(text) {
  const clean = String(text).replace(/[₱,\s]/g, '');
  if (!/^\d*\.?\d*$/.test(clean) || clean === '' || clean === '.') return NaN;
  return Math.round(parseFloat(clean) * 100);
}

function defaultCategories() { return JSON.parse(JSON.stringify(DEFAULT_CATEGORIES)); }
function cats(type) { return state.data.categories[type]; }

function validCategories(c) {
  return !!c && ['income', 'expense'].every((t) => Array.isArray(c[t]) && c[t].length > 0 &&
    c[t].every((x) => x && typeof x.name === 'string' && x.name.trim() && typeof x.icon === 'string'));
}

function categoryIcon(type, name) {
  const c = cats(type).find((x) => x.name === name);
  return c ? c.icon : type === 'income' ? '💰' : '📦';
}

function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

// ---------- State & storage ----------
// Opened through scripts/start.bat, the app talks to the server (server/server.py), which saves
// data to a file and sends reminders on Telegram. Opened as a plain file, it falls back
// to browser storage.
const HELPER_URL = 'http://127.0.0.1:8765/';
const onHelper = location.protocol === 'http:' || location.protocol === 'https:';

const DEFAULT_REMINDERS = {
  enabled: true,
  bills: true,
  billDaysBefore: 3,
  budgets: true,
  nudge: true,
  nudgeHour: 20,
};

// A spending category may carry an amount per payment (cents) and a reminder:
// { amount: 65000, reminder: { days: [14, 29], date: '2026-10-30', time: '09:00' } }
// (days repeat every month; date is a one-time due date)
function migrateCategories(categories, budgets = {}) {
  for (const c of categories.expense) {
    if (c.dueDay && !c.reminder) c.reminder = { days: [Number(c.dueDay)], time: '09:00' };
    delete c.dueDay;
    // Older versions kept a monthly budget per category; turn it into an amount per payment
    if (c.amount == null && budgets[c.name] > 0) {
      const n = c.reminder && c.reminder.days && c.reminder.days.length ? new Set(c.reminder.days).size : 1;
      c.amount = Math.round(budgets[c.name] / n);
    }
  }
  return categories;
}

function normalizeData(parsed) {
  return {
    transactions: parsed.transactions,
    budgets: {}, // replaced by the amount per payment on each category
    categories: migrateCategories(validCategories(parsed.categories) ? parsed.categories : defaultCategories(), parsed.budgets || {}),
    reminders: { ...DEFAULT_REMINDERS, ...(parsed.reminders || {}) },
  };
}

const state = {
  data: normalizeData({ transactions: [] }),
  month: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
  view: 'summary',
  period: new Date().getDate() <= 15 ? 'h1' : 'h2', // half of the month shown on the Expenses page
  editingId: null,
  helper: null, // status reported by the helper
  user: null,   // the logged-in user
  version: null, // version of the saved data (detects edits from another device)
  bot: { ready: false, bot: '' }, // the shared Telegram bot
  tgLink: null, // this user's personal link to connect Telegram
};

function readLocal() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return parsed && Array.isArray(parsed.transactions) ? parsed : null;
  } catch (e) {
    return null;
  }
}

const PROTECTED_KEY = 'money-tracker.protected'; // set once data has moved to the password-protected helper

async function load() {
  if (onHelper) {
    // Data comes only from the helper (after login); nothing is kept in the browser
    const res = await fetch('api/data', { cache: 'no-store' });
    if (res.status === 401) { location.reload(); return; }
    const body = res.ok ? await res.json() : null;
    state.version = res.headers.get('X-Data-Version');
    if (body && Array.isArray(body.transactions)) {
      state.data = normalizeData(body);
      if (body.budgets && Object.keys(body.budgets).length) save(); // store the converted amounts
    }
    return;
  }
  const local = readLocal();
  if (local) state.data = normalizeData(local);
}

let saveTimer = null;
let saveErrorShown = false;

function save() {
  if (onHelper) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(pushToHelper, 300);
    return;
  }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.data));
  } catch (e) {
    showToast('Could not save. Your browser may be blocking storage.');
  }
}

async function pushToHelper(keepalive = false) {
  saveTimer = null;
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (state.version != null) headers['X-Data-Version'] = state.version;
    const res = await fetch('api/data', { method: 'PUT', headers, body: JSON.stringify(state.data), keepalive });
    if (res.status === 401) { location.reload(); return; }
    if (res.status === 409) {
      // Saved from another device in the meantime: load that version instead of overwriting it
      state.data = normalizeData({ transactions: [] });
      await load();
      render();
      showToast('Your data was changed on another device, so the latest version was loaded. Please check your last change.');
      return;
    }
    if (res.status === 400) {
      const body = await res.json().catch(() => ({}));
      showToast(`Not saved: ${body.error || 'the data is not valid.'}`);
      return;
    }
    if (!res.ok) throw new Error(res.status);
    state.version = res.headers.get('X-Data-Version') || state.version;
    saveErrorShown = false;
  } catch (e) {
    if (!saveErrorShown) {
      saveErrorShown = true;
      showToast('Could not save to the helper. Is the Money Tracker window still open?');
    }
  }
}

// Don't lose a change made right before closing the tab
window.addEventListener('pagehide', () => {
  if (saveTimer) { clearTimeout(saveTimer); pushToHelper(true); }
});

async function moveToHelper() {
  // Opened as a plain file while the helper is running: hand over this
  // browser's data (first time only) and switch to the helper version.
  try {
    const ctrl = new AbortController();
    setTimeout(() => ctrl.abort(), 800);
    const status = await (await fetch(HELPER_URL + 'api/status', { signal: ctrl.signal })).json();
    const local = readLocal();
    if (!status.hasData && local) {
      await fetch(HELPER_URL + 'api/import', { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify(local) });
    }
    // The helper now holds the data behind a password: drop this browser's copy
    try {
      localStorage.removeItem(STORAGE_KEY);
      localStorage.setItem(PROTECTED_KEY, '1');
    } catch (e) { /* ignore */ }
    location.replace(HELPER_URL);
    return true;
  } catch (e) {
    return false;
  }
}

// ---------- Derived data ----------
function txInMonth(d) {
  const key = monthKey(d);
  return state.data.transactions.filter((t) => t.date.startsWith(key));
}

function totals(list) {
  let income = 0, expense = 0;
  for (const t of list) t.type === 'income' ? (income += t.amount) : (expense += t.amount);
  return { income, expense, net: income - expense };
}

function spendingByCategory(list) {
  const map = new Map();
  for (const t of list) if (t.type === 'expense') map.set(t.category, (map.get(t.category) || 0) + t.amount);
  return Array.from(map, ([name, amount]) => ({ name, amount })).sort((a, b) => b.amount - a.amount);
}

// ---------- Rendering ----------
function render() {
  $('#monthLabel').textContent = monthFmt.format(state.month);
  renderBalance();
  if (state.view === 'overview') renderColumns();
  if (state.view === 'summary') renderSummary();
  if (state.view === 'budgets') renderBudgets();
  if (state.view === 'profile') renderProfile();
  if (state.view === 'users') renderUsers();
}

function renderBalance() {
  const all = totals(state.data.transactions);
  const month = totals(txInMonth(state.month));
  const bal = $('#balanceValue');
  bal.textContent = (all.net < 0 ? '−' : '') + money(Math.abs(all.net));
  bal.classList.toggle('neg', all.net < 0);
  const period = totals(txInPeriod());
  $('#monthIn').textContent = money(period.income);
  $('#monthOut').textContent = money(period.expense);
  const label = periodLabel();
  $('#periodInLabel').textContent = `Money in · ${label}`;
  $('#periodOutLabel').textContent = `Money out · ${label}`;
  // What's left of the month's money in after everything paid (bills included)
  const left = month.income - month.expense;
  const leftEl = $('#monthLeft');
  leftEl.textContent = (left < 0 ? '−' : '') + money(Math.abs(left));
  leftEl.className = 'split-value ' + (left < 0 ? 'neg' : 'pos');
  $('#leftLabel').textContent = `Left in ${monthNameFmt.format(state.month)}`;
}

// ---------- Half-month periods ----------
function periodRange(period = state.period, month = state.month) {
  const y = month.getFullYear(), m = month.getMonth();
  const last = new Date(y, m + 1, 0).getDate();
  const from = period === 'h2' ? 16 : 1;
  const to = period === 'h1' ? 15 : last;
  return [toISODate(new Date(y, m, from)), toISODate(new Date(y, m, to))];
}

function periodLabel(period = state.period) {
  const [from, to] = periodRange(period);
  const mon = shortMonthFmt.format(state.month);
  return period === 'all' ? `All of ${monthNameFmt.format(state.month)}` : `${mon} ${Number(from.slice(8))}–${Number(to.slice(8))}`;
}

function txInPeriod() {
  const [from, to] = periodRange();
  return state.data.transactions.filter((t) => t.date >= from && t.date <= to);
}

function renderPeriodSwitch() {
  for (const b of $$('.period-switch button')) {
    b.textContent = periodLabel(b.dataset.period);
    b.setAttribute('aria-pressed', String(b.dataset.period === state.period));
  }
}

// Reminder dates of a category within a month (the 29th-31st fall on the last day of short months)
function reminderDates(c, y, m) {
  const last = new Date(y, m + 1, 0).getDate();
  return [...new Set(c.reminder.days.map((d) => Math.min(d, last)))].sort((a, b) => a - b).map((d) => toISODate(new Date(y, m, d)));
}

// Scheduled dates of a category from last month to next month, plus its one-time date
function categoryDates(c, y, m) {
  const set = new Set();
  if (c.reminder.days && c.reminder.days.length) {
    for (const off of [-1, 0, 1]) {
      const d = new Date(y, m + off, 1);
      reminderDates(c, d.getFullYear(), d.getMonth()).forEach((x) => set.add(x));
    }
  }
  if (c.reminder.date) set.add(c.reminder.date);
  return [...set].sort();
}

// Number of payments due in a month (a category without any schedule counts as one)
function paymentsInMonth(c, month = state.month) {
  if (!hasSchedule(c)) return 1;
  const key = monthKey(month);
  return categoryDates(c, month.getFullYear(), month.getMonth()).filter((d) => d.startsWith(key)).length;
}

// Monthly limit for budget alerts: amount per payment × payments that month
function monthlyLimit(c, month = state.month) {
  return c.amount ? c.amount * paymentsInMonth(c, month) : 0;
}

// Which reminder date each payment is for. A payment made with "Record payment" remembers its
// due date (dueFor); any other payment counts for the nearest unpaid reminder date around it.
// server.py uses the same rule for the reminder messages.
function assignPayments(dates, payments) {
  const paidFor = new Map();
  const rest = [];
  for (const t of payments) {
    if (t.dueFor && dates.includes(t.dueFor) && !paidFor.has(t.dueFor)) paidFor.set(t.dueFor, t);
    else rest.push(t);
  }
  const gap = (a, b) => Math.abs(parseISODate(a) - parseISODate(b));
  for (const t of rest) {
    const before = dates.filter((d) => d <= t.date).pop();
    const after = dates.find((d) => d > t.date);
    const options = [before, after].filter(Boolean).sort((a, b) => gap(a, t.date) - gap(b, t.date));
    const due = options.find((d) => !paidFor.has(d));
    if (due) paidFor.set(due, t);
  }
  return paidFor;
}

// Scheduled payments of spending categories that fall in the shown period, with their status
function scheduledInPeriod() {
  return scheduledInRange(...periodRange());
}

function scheduledInRange(from, to) {
  const y = state.month.getFullYear(), m = state.month.getMonth();
  const today = toISODate(new Date());
  const out = [];
  for (const c of cats('expense')) {
    if (!hasSchedule(c)) continue;
    const real = categoryDates(c, y, m);
    const dates = ['0000-01-01', ...real, '9999-12-31']; // open ends so every date has neighbours
    const perPayment = c.amount || 0;
    const payments = state.data.transactions
      .filter((t) => t.type === 'expense' && t.category === c.name)
      .sort((a, b) => (a.date === b.date ? a.created - b.created : a.date < b.date ? -1 : 1));
    const paidFor = assignPayments(real, payments);
    dates.forEach((due, i) => {
      if (i === 0 || i === dates.length - 1 || due < from || due > to) return;
      const prev = dates[i - 1];
      const paid = paidFor.get(due);
      out.push({ cat: c, due, prev, paid, amount: perPayment, status: paid ? 'paid' : due < today ? 'late' : due === today ? 'today' : 'upcoming' });
    });
  }
  return out.sort((a, b) => (a.due < b.due ? -1 : 1));
}

function scheduleRow(s, today) {
  const dueText = dayFmt.format(parseISODate(s.due));
  const days = Math.round((parseISODate(s.due) - parseISODate(today)) / 864e5);
  const pill = s.status === 'paid' ? '<span class="pill paid">Paid</span>'
    : s.status === 'late' ? '<span class="pill late">Overdue</span>'
    : s.status === 'today' ? '<span class="pill due">Due today</span>'
    : `<span class="pill">Due in ${days} day${days === 1 ? '' : 's'}</span>`;
  const amount = s.paid
    ? `<span class="item-amount neg">−${money(s.paid.amount)}</span>`
    : `<span class="item-amount planned">${s.amount ? money(s.amount) : ''}<span class="pay-hint">Record payment</span></span>`;
  const attrs = s.paid
    ? `data-id="${esc(s.paid.id)}" aria-label="Edit payment for ${esc(s.cat.name)}"`
    : `data-pay="${esc(s.cat.name)}" data-due="${s.due}" data-prev="${s.prev}" data-amount="${s.amount}" aria-label="Record payment for ${esc(s.cat.name)} due ${esc(dueText)}"`;
  return `
    <button class="item sched" ${attrs}>
      <span class="item-icon" aria-hidden="true">${esc(s.cat.icon)}</span>
      <span class="item-main">
        <span class="item-cat">${esc(s.cat.name)}</span>
        <span class="item-sub">${pill} ${s.paid
          ? (s.paid.date === s.due ? `on ${esc(dueText)}` : `${esc(dayFmt.format(parseISODate(s.paid.date)))} · due ${esc(dueText)}`)
          : esc(dueText)}</span>
      </span>
      ${amount}
    </button>`;
}

function renderColumns() {
  renderPeriodSwitch();
  const list = txInPeriod()
    .sort((a, b) => (a.date === b.date ? b.created - a.created : a.date < b.date ? 1 : -1));
  const scheduled = scheduledInPeriod();
  const today = toISODate(new Date());
  const yesterday = toISODate(new Date(Date.now() - 864e5));
  const dayLabel = (date) => (date === today ? 'Today' : date === yesterday ? 'Yesterday' : dayFmt.format(parseISODate(date)));

  for (const type of ['expense', 'income']) {
    const items = list.filter((t) => t.type === type);
    const total = items.reduce((s, t) => s + t.amount, 0);
    $(`#${type}Meta`).textContent = items.length ? money(total) : '';
    // Scheduled spending categories come first in the Expenses column; their payments aren't listed twice
    const sched = type === 'expense' ? scheduled : [];
    const shownIds = new Set(sched.filter((s) => s.paid).map((s) => s.paid.id));
    const rest = items.filter((t) => !shownIds.has(t.id));
    const schedHtml = sched.length
      ? `<div class="sched-head"><span>Bills · ${esc(periodLabel())}</span><span>${sched.filter((s) => s.paid).length} of ${sched.length} paid</span></div>` +
        sched.map((s) => scheduleRow(s, today)).join('') +
        (rest.length ? '<div class="sched-head items-head"><span>Other expenses</span></div>' : '')
      : '';
    $(`#${type}List`).innerHTML = schedHtml + (rest.length
      ? rest.map((t) => `
          <button class="item" data-id="${esc(t.id)}" aria-label="Edit ${esc(t.category)} ${esc(money(t.amount))}">
            <span class="item-icon" aria-hidden="true">${esc(categoryIcon(t.type, t.category))}</span>
            <span class="item-main">
              <span class="item-cat">${esc(t.category)}</span>
              <span class="item-sub">${esc(dayLabel(t.date))}${t.note ? ' · ' + esc(t.note) : ''}</span>
            </span>
            <span class="item-amount ${type === 'income' ? 'pos' : 'neg'}">${type === 'income' ? '+' : '−'}${money(t.amount)}</span>
          </button>`).join('')
      : sched.length ? '' : `<div class="empty">No ${type === 'income' ? 'money in' : 'expenses'} in ${esc(periodLabel())} yet.<br>Click <b>${type === 'income' ? 'In' : 'Expenses'}</b> above to add one.</div>`);
  }
}

// ---------- Summary & charts ----------
const tips = new Map();

function niceStep(raw) {
  if (raw <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(raw)));
  const f = raw / exp;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * exp;
}

function topRoundedBar(x, y, w, h, r = 4) {
  if (h <= 0) return '';
  r = Math.min(r, h, w / 2);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function rightRoundedBar(x, y, w, h, r = 4) {
  if (w <= 0) return '';
  r = Math.min(r, w, h / 2);
  return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
}

function ttRow(label, value, keyClass) {
  return `<div class="tt-row"><span>${keyClass ? `<i class="key ${keyClass}"></i>` : ''}${esc(label)}</span><b>${esc(value)}</b></div>`;
}

function renderSummary() {
  const month = totals(txInMonth(state.month));
  $('#statIn').textContent = money(month.income);
  $('#statOut').textContent = money(month.expense);
  const net = $('#statNet');
  net.textContent = signed(month.net);
  net.className = 'stat-value ' + (month.net < 0 ? 'neg' : month.net > 0 ? 'pos' : '');
  $('#statRate').textContent = month.income > 0 ? `${Math.round((month.net / month.income) * 100)}%` : '—';
  $('#catSub').textContent = monthFmt.format(state.month);

  tips.clear();
  renderTrendChart();
  renderCategoryChart();
}

function renderTrendChart() {
  const el = $('#chartTrend');
  const months = [];
  for (let i = 5; i >= 0; i--) {
    const d = addMonths(state.month, -i);
    months.push({ date: d, label: shortMonthFmt.format(d), ...totals(txInMonth(d)) });
  }

  $('#tableTrend').innerHTML = `<table><thead><tr><th>Month</th><th>Money in</th><th>Money out</th><th>Net</th></tr></thead><tbody>${
    months.map((m) => `<tr><td>${esc(monthFmt.format(m.date))}</td><td>${money(m.income)}</td><td>${money(m.expense)}</td><td>${signed(m.net)}</td></tr>`).join('')
  }</tbody></table>`;

  const W = Math.max(el.clientWidth, 260), H = 230;
  const m = { top: 12, right: 4, bottom: 28, left: 52 };
  const pw = W - m.left - m.right, ph = H - m.top - m.bottom;
  const maxVal = Math.max(...months.map((x) => Math.max(x.income, x.expense)));
  const step = niceStep(maxVal / 4 || 100000);
  const yMax = Math.max(step * Math.ceil(maxVal / step), step * 4);
  const y = (v) => m.top + ph - (v / yMax) * ph;

  let svg = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Money in and money out for the last 6 months">`;
  for (let v = 0; v <= yMax + 1; v += step) {
    const yy = Math.round(y(v)) + 0.5;
    svg += `<line class="${v === 0 ? 'baseline' : 'grid'}" x1="${m.left}" x2="${W - m.right}" y1="${yy}" y2="${yy}"/>`;
    svg += `<text x="${m.left - 8}" y="${yy + 4}" text-anchor="end">${compact(v)}</text>`;
  }

  const bw = pw / months.length;
  const barW = Math.max(6, Math.min(24, (bw - 18) / 2));
  months.forEach((mo, i) => {
    const bx = m.left + i * bw;
    const gx = bx + (bw - (barW * 2 + 2)) / 2;
    const id = `trend-${i}`;
    tips.set(id, `<div class="tt-title">${esc(monthFmt.format(mo.date))}</div>${ttRow('Money in', money(mo.income), 'key-in')}${ttRow('Money out', money(mo.expense), 'key-out')}${ttRow('Net', signed(mo.net))}`);
    const isCurrent = i === months.length - 1;
    svg += `<g class="band" data-tip="${id}">
      <rect class="hover-wash" x="${bx + 2}" y="${m.top}" width="${bw - 4}" height="${ph}" rx="6"/>
      <path d="${topRoundedBar(gx, y(mo.income), barW, m.top + ph - y(mo.income))}" fill="var(--series-in)"/>
      <path d="${topRoundedBar(gx + barW + 2, y(mo.expense), barW, m.top + ph - y(mo.expense))}" fill="var(--series-out)"/>
      <text x="${bx + bw / 2}" y="${H - 8}" text-anchor="middle" ${isCurrent ? 'style="fill:var(--fg);font-weight:600"' : ''}>${esc(mo.label)}</text>
      <rect class="hit" x="${bx}" y="0" width="${bw}" height="${H}"/>
    </g>`;
  });
  svg += '</svg>';
  el.innerHTML = svg;
}

function renderCategoryChart() {
  const el = $('#chartCategory');
  let cats = spendingByCategory(txInMonth(state.month));
  const total = cats.reduce((s, c) => s + c.amount, 0);

  if (!cats.length) {
    el.innerHTML = `<div class="chart-empty">No spending recorded in ${esc(monthFmt.format(state.month))}.</div>`;
    $('#tableCategory').innerHTML = '';
    return;
  }

  if (cats.length > 7) {
    const rest = cats.slice(6).reduce((s, c) => s + c.amount, 0);
    cats = [...cats.slice(0, 6), { name: 'All others', amount: rest }];
  }

  $('#tableCategory').innerHTML = `<table><thead><tr><th>Category</th><th>Spent</th><th>Share</th></tr></thead><tbody>${
    cats.map((c) => `<tr><td>${esc(c.name)}</td><td>${money(c.amount)}</td><td>${Math.round((c.amount / total) * 100)}%</td></tr>`).join('')
  }</tbody></table>`;

  const W = Math.max(el.clientWidth, 260);
  const rowH = 36, barH = 16;
  const H = cats.length * rowH + 4;
  const labelW = Math.min(124, W * 0.34);
  const valueW = 76;
  const pw = W - labelW - valueW;
  const max = cats[0].amount;

  let svg = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Spending by category">`;
  svg += `<line class="baseline" x1="${labelW + 0.5}" x2="${labelW + 0.5}" y1="0" y2="${H}"/>`;
  cats.forEach((c, i) => {
    const yy = i * rowH;
    const w = Math.max(2, (c.amount / max) * pw);
    const id = `cat-${i}`;
    tips.set(id, `<div class="tt-title">${esc(c.name)}</div>${ttRow('Spent', money(c.amount))}${ttRow('Share of spending', Math.round((c.amount / total) * 100) + '%')}`);
    svg += `<g class="band" data-tip="${id}">
      <rect class="hover-wash" x="0" y="${yy + 2}" width="${W}" height="${rowH - 4}" rx="6"/>
      <text class="cat-label" x="${labelW - 10}" y="${yy + rowH / 2 + 4}" text-anchor="end">${esc(truncate(c.name, labelW))}</text>
      <path d="${rightRoundedBar(labelW + 1, yy + (rowH - barH) / 2, w, barH)}" fill="var(--series-in)"/>
      <text class="value-label" x="${labelW + w + 8}" y="${yy + rowH / 2 + 4}">${compact(c.amount)}</text>
      <rect class="hit" x="0" y="${yy}" width="${W}" height="${rowH}"/>
    </g>`;
  });
  svg += '</svg>';
  el.innerHTML = svg;
}

function truncate(text, px) {
  const maxChars = Math.floor((px - 12) / 7);
  return text.length > maxChars ? text.slice(0, maxChars - 1) + '…' : text;
}

// ---------- Budgets ----------
const ICON_EDIT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4"/></svg>';
const ICON_BELL = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4l2-2zM10 21h4"/></svg>';
const ICON_ALERT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M12 8v5M12 17h.01"/><circle cx="12" cy="12" r="10"/></svg>';

function renderBudgets() {
  const spent = new Map(spendingByCategory(txInMonth(state.month)).map((c) => [c.name, c.amount]));

  const month = totals(txInMonth(state.month));
  const left = month.income - month.expense;
  const flow = `<div class="money-flow">
      <div><span class="label">Money in</span><b class="pos">${money(month.income)}</b></div>
      <div><span class="label">Bills paid</span><b class="neg">−${money(month.expense)}</b></div>
      <div><span class="label">Left</span><b class="${left < 0 ? 'neg' : 'pos'}">${left < 0 ? '−' : ''}${money(Math.abs(left))}</b></div>
    </div>`;
  // Bills scheduled this month: how many are paid and what's still to pay
  const due = scheduledInRange(...periodRange('all'));
  const paidCount = due.filter((d) => d.paid).length;
  const toPay = due.filter((d) => !d.paid).reduce((sum, d) => sum + (d.amount || 0), 0);
  const late = due.filter((d) => d.status === 'late').length;
  $('#budgetTotal').innerHTML = `<div class="budget-top" style="margin-bottom:10px"><span class="budget-name">${esc(monthFmt.format(state.month))}</span></div>` + flow + (due.length
    ? `<div class="budget-top"><span class="budget-name" style="font-weight:500">${paidCount} of ${due.length} bills paid</span><b>${toPay ? `${money(toPay)} still to pay` : 'All paid ✓'}</b></div>
       <div class="meter ${paidCount === due.length ? '' : late ? 'over' : ''}"><div style="width:${(paidCount / due.length) * 100}%"></div></div>
       <div class="budget-foot"><span>${Math.round((paidCount / due.length) * 100)}% paid</span>${late ? `<span class="status neg">${ICON_ALERT}${late} overdue</span>` : '<span></span>'}</div>`
    : `<div class="budget-foot"><span>Set a due date or repeating days on a bill (✏️) to track it here.</span></div>`);

  // Only rebuild the cards when categories change
  const list = $('#budgetList');
  const sig = cats('expense').map((c) => c.icon + c.name + (c.amount || '') + JSON.stringify(c.reminder || '')).join('|');
  if (list.dataset.sig !== sig) {
    list.dataset.sig = sig;
    list.innerHTML = cats('expense').map((c) => `
      <div class="card budget" data-cat="${esc(c.name)}">
        <div class="budget-top">
          <span class="item-icon" aria-hidden="true">${esc(c.icon)}</span>
          <span class="budget-name">${esc(c.name)}</span>
          <span class="budget-amount">${c.amount ? `${money(c.amount)} <small>per payment</small>` : '<small>No amount set</small>'}</span>
          <button class="icon-btn sm" data-edit-cat="expense" data-name="${esc(c.name)}" aria-label="Edit ${esc(c.name)}">${ICON_EDIT}</button>
        </div>
        <div class="meter"><div></div></div>
        <div class="budget-foot"></div>
        <div class="card-actions">
          <button class="card-reminder ${hasSchedule(c) ? 'on' : ''}" data-edit-cat="expense" data-name="${esc(c.name)}" data-focus="reminder">
            ${ICON_BELL}<span>${hasSchedule(c) ? esc(describeSchedule(c.reminder)) : 'No reminder'}</span>
            <span class="edit-hint">${hasSchedule(c) ? 'Change' : 'Set reminder'}</span>
          </button>
          <button class="btn pay-btn" data-pay-cat="${esc(c.name)}"></button>
        </div>
      </div>`).join('');
  }


  for (const card of list.children) {
    const name = card.dataset.cat;
    const cat = cats('expense').find((x) => x.name === name);
    const budget = cat ? monthlyLimit(cat) : 0;
    const s = spent.get(name) || 0;
    const pct = budget ? s / budget : 0;
    const meter = card.querySelector('.meter');
    meter.className = 'meter ' + (budget ? meterClass(pct) : 'none');
    meter.firstElementChild.style.width = budget ? `${Math.min(100, pct * 100)}%` : '0%';
    card.querySelector('.budget-foot').innerHTML = budget
      ? `<span>Spent ${money(s)} of ${money(budget)}</span>${budgetStatus(s, budget)}`
      : `<span>Spent ${money(s)}</span><span>${cat && cat.amount ? `Nothing due in ${esc(monthNameFmt.format(state.month))}` : 'No limit'}</span>`;

    const pay = nextPayment(name);
    const btn = card.querySelector('.pay-btn');
    btn.disabled = !!(pay.done || pay.waiting);
    btn.classList.toggle('done', !!pay.done || !!(pay.waiting && pay.paidBefore));
    btn.classList.toggle('waiting', !!(pay.waiting && !pay.paidBefore));
    const nextShort = pay.waiting ? monthDayFmt.format(parseISODate(pay.due)) : '';
    btn.innerHTML = pay.done
      ? `✓ Paid for ${esc(monthNameFmt.format(state.month))}`
      : pay.waiting
        ? (pay.paidBefore ? `✓ Paid · next ${esc(nextShort)}` : `Next: ${esc(nextShort)}`)
        : `Paid${pay.amount ? ` · ${money(pay.amount)}` : ''}`;
    const opens = pay.waiting ? `${dayFmt.format(pay.opensAt)} at ${formatTime(`${pad(pay.opensAt.getHours())}:${pad(pay.opensAt.getMinutes())}`)}` : '';
    btn.title = pay.waiting ? `Opens ${opens}, when the reminder is sent` : '';
    btn.setAttribute('aria-label', pay.done
      ? `${name} is paid for ${monthNameFmt.format(state.month)}`
      : pay.waiting
        ? `${name}: next payment ${nextShort}. The Paid button opens ${opens}, when the reminder is sent.`
        : `Mark ${name} as paid${pay.amount ? ', ' + money(pay.amount) : ''}${pay.due ? ' for ' + dayFmt.format(parseISODate(pay.due)) : ''}`);
  }
}

// What the Paid button on a spending card records, for the month shown
function nextPayment(name) {
  const c = cats('expense').find((x) => x.name === name);
  const lastPaid = state.data.transactions
    .filter((t) => t.type === 'expense' && t.category === name)
    .sort((a, b) => (a.date === b.date ? b.created - a.created : a.date < b.date ? 1 : -1))[0];
  const fallback = (c && c.amount) || (lastPaid ? lastPaid.amount : 0);
  if (hasSchedule(c)) {
    // Next unpaid scheduled date this month (overdue ones first)
    const month = scheduledInRange(...periodRange('all')).filter((s) => s.cat.name === name);
    const open = month.filter((s) => !s.paid);
    if (open.length) {
      const s = open[0];
      // The button opens again once that date's reminder is sent (or the date has passed)
      const opensAt = reminderStart(c, s.due);
      if (s.due >= toISODate(new Date()) && new Date() < opensAt) {
        return { waiting: true, due: s.due, opensAt, paidBefore: month.some((x) => x.paid) };
      }
      return { due: s.due, prev: s.prev, amount: s.amount || fallback };
    }
    // Something was scheduled this month and it's all paid
    if (paymentsInMonth(c) > 0) return { done: true };
  }
  return { amount: fallback };
}

// When the reminder for a due date is sent: the early reminder (if set) or the due date, at the bill's time
function reminderStart(c, due) {
  const r = state.data.reminders;
  const daysBefore = r.bills ? Number(r.billDaysBefore) || 0 : 0;
  const [h, m] = ((c.reminder && c.reminder.time) || '09:00').split(':').map(Number);
  const d = parseISODate(due);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() - daysBefore, h, m);
}

function payCategory(name) {
  const pay = nextPayment(name);
  if (pay.done || pay.waiting) return;
  const now = new Date();
  const today = toISODate(now);
  const inShownMonth = monthKey(now) === monthKey(state.month);
  // Date it today when that fits this payment; otherwise on its due date (or the 1st of the shown month)
  const date = pay.due
    ? (today > pay.prev && today <= pay.due ? today : pay.due)
    : (inShownMonth ? today : toISODate(state.month));
  const note = pay.due ? `Payment due ${dayFmt.format(parseISODate(pay.due))}` : 'Paid';
  if (!pay.amount) {
    // First payment in this category: ask for the amount
    openDialog(null, 'expense', { category: name, dueFor: pay.due, date, note });
    return;
  }
  const tx = { id: uid(), created: Date.now(), type: 'expense', amount: pay.amount, category: name, date, note, ...(pay.due ? { dueFor: pay.due } : {}) };
  state.data.transactions.push(tx);
  save();
  render();
  const m = totals(txInMonth(parseISODate(date)));
  const left = m.income - m.expense;
  showToast(`${name} paid ${money(pay.amount)} — deducted from your money in. ${left < 0 ? '−' : ''}${money(Math.abs(left))} left for ${monthNameFmt.format(parseISODate(date))}.`, 'Undo', () => {
    state.data.transactions = state.data.transactions.filter((t) => t.id !== tx.id);
    save();
    render();
  });
}

function meterClass(pct) { return pct > 1 ? 'over' : pct >= 0.8 ? 'warn' : ''; }

function budgetStatus(spent, budget) {
  if (spent > budget) return `<span class="status neg">${ICON_ALERT}Over by ${money(spent - budget)}</span>`;
  if (spent / budget >= 0.8) return `<span class="status">${ICON_ALERT}${money(budget - spent)} left</span>`;
  return `<span>${money(budget - spent)} left</span>`;
}

// ---------- Dialog ----------
const dialog = $('#txDialog');
const form = $('#txForm');

function fillCategories(type, selected) {
  const list = [...cats(type)];
  // Keep a deleted category selectable when editing an old entry that uses it
  if (selected && !list.some((c) => c.name === selected)) list.push({ name: selected, icon: categoryIcon(type, selected) });
  form.category.innerHTML = list
    .map((c) => `<option value="${esc(c.name)}" ${c.name === selected ? 'selected' : ''}>${esc(c.icon)}  ${esc(c.name)}</option>`)
    .join('') + '<option value="__new__">＋  New category…</option>';
  form.category.dataset.prev = form.category.value;
}

form.category.addEventListener('change', () => {
  if (form.category.value !== '__new__') { form.category.dataset.prev = form.category.value; return; }
  const type = form.type.value;
  const prev = form.category.dataset.prev;
  openCatDialog(type, null, (name) => fillCategories(type, name || prev));
});

function dialogTitle(type, editing) {
  return `${editing ? 'Edit' : 'Add'} ${type === 'income' ? 'money in' : 'expense'}`;
}

function openDialog(tx, newType = 'expense', prefill = null) {
  state.editingId = tx ? tx.id : null;
  state.dueFor = (!tx && prefill && prefill.dueFor) || null;
  const type = tx ? tx.type : newType;
  $('#txDialogTitle').textContent = dialogTitle(type, !!tx);
  $('#deleteTx').hidden = !tx;
  form.type.value = type;
  fillCategories(type, tx ? tx.category : prefill && prefill.category);
  form.amount.value = tx ? (tx.amount / 100).toFixed(2) : '';
  form.note.value = tx ? tx.note || '' : (prefill && prefill.note) || '';
  const now = new Date();
  form.date.value = tx ? tx.date : monthKey(now) === monthKey(state.month) ? toISODate(now) : toISODate(state.month);
  if (prefill) {
    if (prefill.amount) form.amount.value = (prefill.amount / 100).toFixed(2);
    if (prefill.date) form.date.value = prefill.date;
  }
  setAmountError(false);
  dialog.showModal();
  if (!tx) setTimeout(() => form.amount.focus(), 50);
}

function setAmountError(on) {
  $('#amountError').hidden = !on;
  form.amount.setAttribute('aria-invalid', on ? 'true' : 'false');
}

form.addEventListener('change', (e) => {
  if (e.target.name === 'type') {
    fillCategories(e.target.value);
    $('#txDialogTitle').textContent = dialogTitle(e.target.value, !!state.editingId);
  }
});
form.amount.addEventListener('input', () => setAmountError(false));

form.addEventListener('submit', (e) => {
  e.preventDefault();
  const amount = parseAmount(form.amount.value);
  if (!(amount > 0)) { setAmountError(true); form.amount.focus(); return; }
  if (!form.date.value) { form.date.focus(); return; }
  if (form.category.value === '__new__') { form.category.focus(); return; }

  const entry = {
    type: form.type.value,
    amount,
    category: form.category.value,
    date: form.date.value,
    note: form.note.value.trim(),
  };

  if (state.editingId) {
    const t = state.data.transactions.find((x) => x.id === state.editingId);
    if (t.category !== entry.category || t.type !== entry.type) delete t.dueFor;
    Object.assign(t, entry);
    showToast('Transaction updated');
  } else {
    state.data.transactions.push({ id: uid(), created: Date.now(), ...entry, ...(state.dueFor && entry.type === 'expense' ? { dueFor: state.dueFor } : {}) });
    showToast(`${entry.type === 'income' ? 'Money in' : 'Expense'} of ${money(amount)} added`);
  }
  save();
  dialog.close();

  // Jump to the month of the saved entry so it's visible
  const d = parseISODate(entry.date);
  if (monthKey(d) !== monthKey(state.month)) state.month = new Date(d.getFullYear(), d.getMonth(), 1);
  render();
});

$('#deleteTx').addEventListener('click', () => {
  const idx = state.data.transactions.findIndex((x) => x.id === state.editingId);
  if (idx < 0) return;
  const [removed] = state.data.transactions.splice(idx, 1);
  save();
  dialog.close();
  render();
  showToast('Transaction deleted', 'Undo', () => {
    state.data.transactions.push(removed);
    save();
    render();
  });
});

$$('[data-close]').forEach((b) => b.addEventListener('click', () => dialog.close()));
dialog.addEventListener('click', (e) => { if (e.target === dialog) dialog.close(); });

// ---------- Category dialog ----------
const catDialog = $('#catDialog');
const catForm = $('#catForm');
let catEditing = null;   // { type, name } when editing an existing category
let catType = 'expense';
let catDone = null;      // callback(newName | null) when opened from the transaction dialog

function openCatDialog(type, name = null, onDone = null, focus = null) {
  catType = type;
  catDone = onDone;
  const existing = name ? cats(type).find((c) => c.name === name) : null;
  catEditing = existing ? { type, name } : null;
  $('#catDialogTitle').textContent = type === 'income' ? (existing ? 'Edit category' : 'New money in category')
    : existing ? 'Edit bill' : onDone ? 'New spending category' : 'New bill';
  catForm.cname.value = existing ? existing.name : '';
  $('#dueField').hidden = type !== 'expense';
  $('#payFields').hidden = type !== 'expense';
  const r = existing && existing.reminder;
  catForm.camount.value = existing && existing.amount ? (existing.amount / 100).toFixed(2) : '';
  // One-time due date: today for a new category, the saved date (if any) when editing
  catForm.cdate.value = existing ? (r && r.date) || '' : toISODate(new Date());
  for (const box of $$('#dayGrid input')) box.checked = !!r && !!r.days && r.days.includes(Number(box.value));
  catForm.ctime.value = (r && r.time) || '09:00';
  updateRemSummary();
  const icon = existing ? existing.icon : type === 'income' ? '💰' : '📦';
  const choices = ICON_CHOICES.includes(icon) ? ICON_CHOICES : [icon, ...ICON_CHOICES];
  $('#iconGrid').innerHTML = choices.map((i) => `
    <label><input type="radio" name="cicon" value="${esc(i)}" ${i === icon ? 'checked' : ''} aria-label="${esc(i)}"><span>${esc(i)}</span></label>`).join('');
  $('#deleteCat').hidden = !existing;
  setCatError('');
  catDialog.showModal();
  setTimeout(() => {
    if (focus === 'reminder' && type === 'expense') {
      $('#dueField').scrollIntoView({ block: 'center' });
      $('#dayGrid input').focus();
    } else {
      catForm.cname.focus();
    }
  }, 50);
}

function selectedDays() {
  return $$('#dayGrid input:checked').map((b) => Number(b.value));
}

function updateRemSummary() {
  const days = selectedDays();
  const date = catForm.cdate.value;
  $('#remSummary').textContent = days.length || date
    ? `🔔 ${describeSchedule({ days, date, time: catForm.ctime.value || '09:00' })}${days.some((d) => d > 28) ? ' (the 29th–31st fall on the last day in shorter months)' : ''}`
    : 'No reminder. Pick a one-time due date or repeating days, e.g. 14 and 29.';
}

function setCatError(msg) {
  const el = $('#catError');
  el.textContent = msg;
  el.hidden = !msg;
}

catForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const name = catForm.cname.value.trim().replace(/\s+/g, ' ');
  const checked = catForm.querySelector('input[name="cicon"]:checked');
  const icon = checked ? checked.value : '📦';
  const days = catType === 'expense' ? selectedDays() : [];
  const date = catType === 'expense' ? catForm.cdate.value : '';
  const reminder = days.length || date ? { days, ...(date ? { date } : {}), time: catForm.ctime.value || '09:00' } : null;
  const amountText = catType === 'expense' ? catForm.camount.value.trim() : '';
  const amount = amountText ? parseAmount(amountText) : 0;
  if (amountText && !(amount > 0)) { setCatError('Enter the amount per payment as a number, e.g. 650.'); catForm.camount.focus(); return; }
  if (!name) { setCatError('Enter a name for the category.'); catForm.cname.focus(); return; }
  if (name === '__new__') { setCatError('Please choose a different name.'); return; }
  const list = cats(catType);
  const duplicate = list.some((c) => c.name.toLowerCase() === name.toLowerCase() && (!catEditing || c.name !== catEditing.name));
  if (duplicate) { setCatError('You already have a category with that name.'); catForm.cname.focus(); return; }

  if (catEditing) {
    const c = list.find((x) => x.name === catEditing.name);
    const oldName = c.name;
    c.name = name;
    c.icon = icon;
    if (reminder) c.reminder = reminder; else delete c.reminder;
    if (amount) c.amount = amount; else delete c.amount;
    if (oldName !== name) {
      // Carry existing entries over to the new name
      for (const t of state.data.transactions) if (t.type === catType && t.category === oldName) t.category = name;
    }
    showToast('Category updated');
  } else {
    list.push({ name, icon, ...(amount ? { amount } : {}), ...(reminder ? { reminder } : {}) });
    showToast(`Added “${name}”`);
  }
  save();
  const done = catDone;
  catDone = null;
  catDialog.close();
  render();
  if (done) done(name);
});

$('#deleteCat').addEventListener('click', () => {
  const { type, name } = catEditing;
  const list = cats(type);
  if (list.length <= 1) { setCatError('Keep at least one category.'); return; }
  const used = state.data.transactions.filter((t) => t.type === type && t.category === name).length;
  if (used && !confirm(`${used} ${used === 1 ? 'entry uses' : 'entries use'} “${name}”. They will keep this name, but it won't be offered for new entries.\n\nDelete the category?`)) return;

  const idx = list.findIndex((c) => c.name === name);
  const [removed] = list.splice(idx, 1);
  save();
  catDialog.close();
  render();
  showToast(`Deleted “${name}”`, 'Undo', () => {
    list.splice(idx, 0, removed);
    save();
    render();
  });
});

$('#dayGrid').innerHTML = Array.from({ length: 31 }, (_, i) =>
  `<label><input type="checkbox" value="${i + 1}" aria-label="Day ${i + 1}"><span>${i + 1}</span></label>`).join('');
$('#dayGrid').addEventListener('change', updateRemSummary);
catForm.cdate.addEventListener('input', updateRemSummary);
$('#clearDate').addEventListener('click', () => { catForm.cdate.value = ''; updateRemSummary(); });
catForm.ctime.addEventListener('input', updateRemSummary);
$('#clearDays').addEventListener('click', () => {
  for (const box of $$('#dayGrid input')) box.checked = false;
  updateRemSummary();
});

$$('[data-close-cat]').forEach((b) => b.addEventListener('click', () => catDialog.close()));
catDialog.addEventListener('click', (e) => { if (e.target === catDialog) catDialog.close(); });
catDialog.addEventListener('close', () => {
  // Cancelled while adding from the transaction dialog: restore the previous choice
  if (catDone) { const done = catDone; catDone = null; done(null); }
});

document.addEventListener('click', (e) => {
  const add = e.target.closest('[data-add-cat]');
  if (add) { openCatDialog(add.dataset.addCat); return; }
  const edit = e.target.closest('[data-edit-cat]');
  if (edit) openCatDialog(edit.dataset.editCat, edit.dataset.name, null, edit.dataset.focus);
});

// ---------- Profile & Telegram notifications ----------
const remForm = $('#remForm');
let tgLinkPending = false;

function initials(name) {
  return String(name || '').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('') || '?';
}

async function apiGet(path) {
  const res = await fetch(path, { cache: 'no-store' });
  if (res.status === 401) { location.reload(); throw new Error('Please log in.'); }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || 'Something went wrong.');
  return body;
}

async function apiPost(path, payload, button) {
  if (button) button.disabled = true;
  try {
    const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload || {}) });
    if (res.status === 401) { location.reload(); throw new Error('Please log in.'); }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || 'Something went wrong.');
    return body;
  } catch (err) {
    throw new Error(err.message === 'Failed to fetch' ? 'Money Tracker is not responding. Is its window still open?' : err.message);
  } finally {
    if (button) button.disabled = false;
  }
}

function renderProfile() {
  const u = state.user;
  if (!u) return;
  $('#profAvatar').textContent = initials(u.name);
  $('#profName').textContent = u.name;
  $('#profUsername').textContent = u.username;
  const role = $('#profRole');
  role.textContent = u.role === 'admin' ? 'System admin' : 'User';
  role.className = 'role-badge ' + u.role;
  const nameInput = $('#profileForm').elements.name;
  if (document.activeElement !== nameInput) nameInput.value = u.name;
  renderReminders();
  if (state.bot.ready && !u.telegram.connected && !state.tgLink) ensureTelegramLink();
}

function renderReminders() {
  const r = state.data.reminders;
  remForm.enabled.checked = !!r.enabled;
  remForm.bills.checked = !!r.bills;
  remForm.budgets.checked = !!r.budgets;
  remForm.nudge.checked = !!r.nudge;
  remForm.billDaysBefore.value = String(r.billDaysBefore);
  remForm.nudgeHour.value = String(r.nudgeHour);
  remForm.setAttribute('aria-disabled', String(!r.enabled));
  renderTelegram();
}

function renderTelegram() {
  const u = state.user;
  const bot = state.bot || {};
  const connected = !!(u && u.telegram.connected);
  $('#tgNoBot').hidden = !onHelper || !!bot.ready || connected;
  $('#tgGuide').hidden = !onHelper || !bot.ready || connected;
  $('#tgStepDone').hidden = !connected;
  $('#testMessage').disabled = !connected || !bot.ready;
  const handle = bot.bot ? '@' + bot.bot : 'the bot';
  for (const id of ['#tgBotName', '#tgBotName2', '#tgBotName3']) $(id).textContent = handle;
  if (u) $('#tgChatName').textContent = u.telegram.name || 'your Telegram';
  if (state.tgLink) {
    $('#tgOpenBot').href = state.tgLink.link;
    $('#tgCode').textContent = state.tgLink.code;
  }
  const el = $('#helperStatus');
  if (!onHelper) {
    el.className = 'helper-status warn';
    el.innerHTML = 'Telegram reminders need the Money Tracker server. Open the app with <code>scripts/start.bat</code>.';
  } else if (!bot.ready && !connected) {
    el.className = 'helper-status warn';
    el.textContent = u && u.role === 'admin' ? 'Set up the Telegram bot on the Users page first.' : "Your admin hasn't set up Telegram reminders yet.";
  } else if (!connected) {
    el.className = 'helper-status warn';
    el.textContent = 'Not connected yet. Follow the steps below to get reminders on your phone.';
  } else {
    el.className = 'helper-status ok';
    el.textContent = `Connected. Your reminders go to ${u.telegram.name || 'your Telegram'} on Telegram.`;
  }
}

async function ensureTelegramLink() {
  if (tgLinkPending || !onHelper) return;
  tgLinkPending = true;
  try {
    state.tgLink = await apiPost('api/telegram/link');
    renderTelegram();
  } catch (err) {
    showToast(err.message);
  } finally {
    tgLinkPending = false;
  }
}

async function refreshMe() {
  if (!onHelper) return;
  try {
    const me = await apiGet('api/me');
    state.user = me.user;
    state.bot = me.bot;
  } catch (e) { return; }
  applyUserUI();
  if (state.view === 'profile') renderProfile();
}

function applyUserUI() {
  const u = state.user;
  const admin = !!(u && u.role === 'admin');
  $$('[data-admin-only]').forEach((el) => { el.hidden = !admin; });
  if (u) $('#menuUser').innerHTML = `<b>${esc(u.name)}</b>@${esc(u.username)} · ${admin ? 'System admin' : 'User'}`;
  // Nudge users to connect Telegram until they do (or choose "Later")
  let later = false;
  try { later = localStorage.getItem(`money-tracker.welcome-later.${u && u.id}`) === '1'; } catch (e) { /* ignore */ }
  $('#welcomeBanner').hidden = !(u && state.bot.ready && !u.telegram.connected && !later && state.view !== 'profile');
}

$('#welcomeLater').addEventListener('click', () => {
  try { localStorage.setItem(`money-tracker.welcome-later.${state.user.id}`, '1'); } catch (e) { /* ignore */ }
  $('#welcomeBanner').hidden = true;
});

document.addEventListener('click', (e) => {
  const go = e.target.closest('[data-goto]');
  if (go) setView(go.dataset.goto);
});

$('#profileForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const body = await apiPost('api/profile', { name: e.currentTarget.elements.name.value }, e.submitter);
    state.user = body.user;
    applyUserUI();
    renderProfile();
    remNote('', '');
    $('#profNote').textContent = 'Saved';
    $('#profNote').className = 'rem-note ok';
  } catch (err) {
    $('#profNote').textContent = err.message;
    $('#profNote').className = 'rem-note err';
  }
});
$('#profPassword').addEventListener('click', () => openPwDialog());

$('#tgConnect').addEventListener('click', async (e) => {
  try {
    const body = await apiPost('api/telegram/connect', {}, e.currentTarget);
    state.user = body.user;
    state.tgLink = null;
    applyUserUI();
    renderProfile();
    showToast('Connected! Check Telegram for a confirmation message.');
  } catch (err) { showToast(err.message); }
});

$('#tgDisconnect').addEventListener('click', async () => {
  if (!confirm('Stop sending reminders to this Telegram chat? You can connect again later.')) return;
  try {
    const body = await apiPost('api/telegram/disconnect');
    state.user = body.user;
    applyUserUI();
    renderProfile();
    showToast('Telegram disconnected');
  } catch (err) { showToast(err.message); }
});

function remNote(text, kind = '') {
  const el = $('#remNote');
  el.textContent = text;
  el.className = 'rem-note ' + kind;
}

remForm.addEventListener('submit', (e) => e.preventDefault());
remForm.addEventListener('change', () => {
  const r = state.data.reminders;
  r.enabled = remForm.enabled.checked;
  r.bills = remForm.bills.checked;
  r.budgets = remForm.budgets.checked;
  r.nudge = remForm.nudge.checked;
  r.billDaysBefore = Number(remForm.billDaysBefore.value);
  r.nudgeHour = Number(remForm.nudgeHour.value);
  save();
  renderReminders();
  remNote('Saved', 'ok');
});

$('#testMessage').addEventListener('click', async (e) => {
  remNote('Sending…');
  try {
    await apiPost('api/test-message', {}, e.currentTarget);
    remNote('Test message sent. Check Telegram on your phone.', 'ok');
  } catch (err) { remNote(err.message, 'err'); }
});

// ---------- Users (admin) ----------
let adminUsers = [];
let adminSystem = null;
let editingUserId = null;
const userDialog = $('#userDialog');
const userForm = $('#userForm');
const credDialog = $('#credDialog');

async function loadUsers() {
  try {
    const [u, sys] = await Promise.all([apiGet('api/admin/users'), apiGet('api/admin/system')]);
    adminUsers = u.users;
    adminSystem = sys;
    state.bot = sys.bot;
    renderUsers();
  } catch (err) { showToast(err.message); }
}

function shortDate(iso) {
  return iso ? shortDateFmt.format(new Date(iso)) : '';
}

function renderUsers() {
  if (!adminSystem || !state.user) return;
  $('#userList').innerHTML = adminUsers.map((u) => {
    const me = u.id === state.user.id;
    return `
      <div class="card user-card ${u.disabled ? 'disabled' : ''}">
        <div class="user-top">
          <div class="avatar" aria-hidden="true">${esc(initials(u.name))}</div>
          <div class="user-who"><b>${esc(u.name)}${me ? '<span class="you-badge">YOU</span>' : ''}</b><span>@${esc(u.username)}</span></div>
          <span class="role-badge ${u.role}">${u.role === 'admin' ? 'Admin' : 'User'}</span>
        </div>
        <div class="user-facts">
          <span class="${u.telegram.connected ? 'ok' : 'no'}">${u.telegram.connected ? '📱 Telegram connected' : '📵 Telegram not connected'}</span>
          <span>${u.entries} entr${u.entries === 1 ? 'y' : 'ies'}</span>
          <span>${u.lastLogin ? 'Last login ' + esc(shortDate(u.lastLogin)) : 'Never logged in'}</span>
          ${u.mustChange ? '<span class="no">Temporary password</span>' : ''}
          ${u.disabled ? '<span class="no">Disabled</span>' : ''}
        </div>
        <div class="user-actions">
          <button class="btn ghost" data-user-act="edit" data-id="${u.id}">Edit</button>
          <button class="btn ghost" data-user-act="reset" data-id="${u.id}">Reset password</button>
          ${me ? '' : `<button class="btn ghost" data-user-act="toggle" data-id="${u.id}">${u.disabled ? 'Enable' : 'Disable'}</button>
          <button class="btn danger" data-user-act="delete" data-id="${u.id}">Delete</button>`}
        </div>
      </div>`;
  }).join('');
  const bot = adminSystem.bot;
  $('#botSetup').hidden = bot.ready;
  $('#botReady').hidden = !bot.ready;
  $('#botName').textContent = '@' + bot.bot;
  const others = adminSystem.urls.filter((u) => !u.includes('127.0.0.1'));
  $('#addrHint').innerHTML = others.length
    ? `People open Money Tracker at: ${others.map((u) => `<code>${esc(u)}</code>`).join(' or ')} (this PC: <code>${esc(adminSystem.urls[0])}</code>).`
    : `Right now Money Tracker opens only on this PC (<code>${esc(adminSystem.urls[0])}</code>). To let people use their own phones or laptops on your Wi-Fi, see “Using Money Tracker on other devices” in docs/README.md.`;
}

function openUserDialog(u) {
  editingUserId = u ? u.id : null;
  $('#userDialogTitle').textContent = u ? `Edit ${u.name}` : 'Add user';
  $('#userSave').textContent = u ? 'Save' : 'Add user';
  userForm.reset();
  if (u) {
    userForm.elements.name.value = u.name;
    userForm.elements.username.value = u.username;
    userForm.elements.role.value = u.role;
  }
  $('#userError').hidden = true;
  userDialog.showModal();
  setTimeout(() => userForm.elements.name.focus(), 50);
}

function bestUrl() {
  const urls = (adminSystem && adminSystem.urls) || [location.origin + '/'];
  return urls.find((u) => !u.includes('127.0.0.1')) || urls[0];
}

function showCredentials(u, password, reset = false) {
  $('#credDialogTitle').textContent = reset ? `New temporary password for ${u.name}` : `Give these to ${u.name}`;
  $('#credUser').textContent = u.username;
  $('#credPass').textContent = password;
  $('#credNote').textContent = '';
  const url = bestUrl();
  $('#credText').value = reset
    ? `Hi ${u.name}! Your Money Tracker password was reset.\n\n` +
      `Open Money Tracker: ${url}\nUsername: ${u.username}\nTemporary password: ${password}\n\n` +
      `When you log in, you'll choose a new password.`
    : `Hi ${u.name}! I've set up Money Tracker for you — an app for tracking your money in, expenses and bills.\n\n` +
      `1. Open Money Tracker: ${url}\n` +
      `2. Log in with\n   Username: ${u.username}\n   Temporary password: ${password}\n   You'll choose your own password right away.\n` +
      `3. Get reminders on your phone (free):\n` +
      `   • Install Telegram from the App Store or Google Play and sign up with your mobile number.\n` +
      `   • In Money Tracker, open Profile → Telegram notifications.\n` +
      `   • Tap "Open the bot in Telegram", press Start in Telegram, then tap Connect.\n` +
      `   You'll get bill reminders, budget alerts, a monthly summary on the 1st and password reset codes there.`;
  credDialog.showModal();
}

$('#credCopy').addEventListener('click', async () => {
  const text = $('#credText').value;
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    $('#credText').select();
    document.execCommand('copy');
  }
  $('#credNote').textContent = 'Copied — paste it in a message to them.';
  $('#credNote').className = 'rem-note ok';
});
$$('[data-close-cred]').forEach((b) => b.addEventListener('click', () => credDialog.close()));
$$('[data-close-user]').forEach((b) => b.addEventListener('click', () => userDialog.close()));
$('#addUserBtn').addEventListener('click', () => openUserDialog(null));

userForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = userForm.elements;
  const payload = { name: f.name.value, username: f.username.value.trim(), role: f.role.value };
  try {
    if (editingUserId) {
      await apiPost('api/admin/users/update', { id: editingUserId, ...payload }, $('#userSave'));
      userDialog.close();
      showToast('User updated');
      if (editingUserId === state.user.id) await refreshMe();
    } else {
      const body = await apiPost('api/admin/users/create', payload, $('#userSave'));
      userDialog.close();
      showCredentials(body.user, body.password);
    }
    loadUsers();
  } catch (err) {
    $('#userError').textContent = err.message;
    $('#userError').hidden = false;
  }
});

$('#userList').addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-user-act]');
  if (!btn) return;
  const u = adminUsers.find((x) => x.id === Number(btn.dataset.id));
  if (!u) return;
  try {
    if (btn.dataset.userAct === 'edit') openUserDialog(u);
    if (btn.dataset.userAct === 'reset') {
      if (!confirm(`Give ${u.name} a new temporary password? Their current password stops working.`)) return;
      const body = await apiPost('api/admin/users/reset-password', { id: u.id }, btn);
      showCredentials(u, body.password, true);
      loadUsers();
    }
    if (btn.dataset.userAct === 'toggle') {
      await apiPost('api/admin/users/update', { id: u.id, disabled: !u.disabled }, btn);
      showToast(u.disabled ? `${u.name} can log in again` : `${u.name} can't log in until you enable the account`);
      loadUsers();
    }
    if (btn.dataset.userAct === 'delete') {
      if (!confirm(`Delete ${u.name} (@${u.username}) and all of their data — ${u.entries} entries, bills and reminders? This can't be undone.`)) return;
      await apiPost('api/admin/users/delete', { id: u.id }, btn);
      showToast(`${u.name} was deleted`);
      loadUsers();
    }
  } catch (err) { showToast(err.message); }
});

$('#botSave').addEventListener('click', async (e) => {
  const token = $('#botToken').value.trim();
  if (!token) { showToast('Paste the token from @BotFather first'); return; }
  try {
    const body = await apiPost('api/admin/telegram/token', { token }, e.currentTarget);
    $('#botToken').value = '';
    adminSystem.bot = body.bot;
    state.bot = body.bot;
    state.tgLink = null;
    renderUsers();
    applyUserUI();
    showToast(`Bot @${body.bot.bot} saved. Each user can now connect in their Profile.`);
  } catch (err) { showToast(err.message); }
});
$('#botToken').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#botSave').click(); });
$('#botReplace').addEventListener('click', async () => {
  if (!confirm('Use a different bot? Everyone will need to connect Telegram again in their Profile.')) return;
  try {
    const body = await apiPost('api/admin/telegram/remove');
    adminSystem.bot = body.bot;
    state.bot = body.bot;
    renderUsers();
  } catch (err) { showToast(err.message); }
});

// ---------- Toast ----------
let toastTimer;
function showToast(message, actionLabel, onAction) {
  const el = $('#toast');
  el.innerHTML = `<span>${esc(message)}</span>${actionLabel ? `<button type="button">${esc(actionLabel)}</button>` : ''}`;
  el.hidden = false;
  if (actionLabel) {
    el.querySelector('button').addEventListener('click', () => { el.hidden = true; onAction(); }, { once: true });
  }
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, actionLabel ? 6000 : 2500);
}

// ---------- Tooltip ----------
const tooltip = $('#tooltip');
function showTip(e) {
  const g = e.target.closest && e.target.closest('[data-tip]');
  if (!g || !tips.has(g.dataset.tip)) { tooltip.hidden = true; return; }
  tooltip.innerHTML = tips.get(g.dataset.tip);
  tooltip.hidden = false;
  const r = tooltip.getBoundingClientRect();
  let x = e.clientX + 14, y = e.clientY + 14;
  if (x + r.width > window.innerWidth - 8) x = e.clientX - r.width - 14;
  if (y + r.height > window.innerHeight - 8) y = e.clientY - r.height - 14;
  tooltip.style.left = Math.max(8, x) + 'px';
  tooltip.style.top = Math.max(8, y) + 'px';
}
for (const id of ['#chartTrend', '#chartCategory']) {
  const el = $(id);
  el.addEventListener('pointermove', showTip);
  el.addEventListener('pointerdown', showTip);
  el.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse') tooltip.hidden = true; });
}
document.addEventListener('pointerdown', (e) => { if (!e.target.closest('.chart')) tooltip.hidden = true; });
window.addEventListener('scroll', () => { tooltip.hidden = true; }, { passive: true });

// ---------- Export / backup ----------
function download(filename, content, type) {
  const blob = new Blob([content], { type });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function csvCell(v, isText = true) {
  let s = String(v ?? '');
  // A note like "=HYPERLINK(...)" would run as a formula when the file is opened in Excel
  if (isText && /^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function exportCSV() {
  const rows = [...state.data.transactions].sort((a, b) => (a.date < b.date ? -1 : 1));
  if (!rows.length) { showToast('Nothing to export yet'); return; }
  const lines = [['Date', 'Type', 'Category', 'Amount', 'Note'].join(',')];
  for (const t of rows) {
    lines.push([csvCell(t.date, false), csvCell(t.type === 'income' ? 'Money in' : 'Money out'), csvCell(t.category),
      csvCell((t.amount / 100).toFixed(2), false), csvCell(t.note)].join(','));
  }
  download(`transactions-${toISODate(new Date())}.csv`, '﻿' + lines.join('\r\n'), 'text/csv;charset=utf-8');
}

// Excel download: pick a month (or all months); the helper builds it from the database
const xlsDialog = $('#xlsDialog');
const xlsForm = $('#xlsForm');
let xlsMonths = [];

async function exportExcel() {
  if (saveTimer) { clearTimeout(saveTimer); await pushToHelper(); }
  try {
    const res = await fetch('api/months', { cache: 'no-store' });
    if (res.status === 401) { location.reload(); return; }
    xlsMonths = (await res.json()).months || [];
  } catch (e) {
    showToast('Could not reach the helper. Is the Money Tracker window still open?');
    return;
  }
  const current = monthKey(new Date());
  $('#xlsMonth').innerHTML = '<option value="">All months</option>' + xlsMonths.map((m) =>
    `<option value="${m.month}">${esc(m.label)}${m.month === current ? ' (this month)' : m.closed ? ' (closed)' : ''}</option>`).join('');
  $('#xlsMonth').value = monthKey(state.month);
  if (!$('#xlsMonth').value) $('#xlsMonth').value = '';
  updateXlsInfo();
  xlsDialog.showModal();
}

function updateXlsInfo() {
  const m = xlsMonths.find((x) => x.month === $('#xlsMonth').value);
  const all = xlsMonths.reduce((a, x) => ({ entries: a.entries + x.entries, left: a.left + x.left }), { entries: 0, left: 0 });
  const pick = m || { entries: all.entries, left: all.left, moneyIn: null };
  $('#xlsInfo').textContent = m
    ? `${m.entries} entr${m.entries === 1 ? 'y' : 'ies'} · Money in ${money(m.moneyIn)} · Money out ${money(m.moneyOut)} · Left ${m.left < 0 ? '−' : ''}${money(Math.abs(m.left))}`
    : `${pick.entries} entries across ${xlsMonths.filter((x) => x.entries).length} month(s)`;
}
$('#xlsMonth').addEventListener('change', updateXlsInfo);
$$('[data-close-xls]').forEach((b) => b.addEventListener('click', () => xlsDialog.close()));

xlsForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const month = $('#xlsMonth').value;
  const btn = xlsForm.querySelector('button[type="submit"]');
  btn.disabled = true;
  try {
    const res = await fetch('api/export.xlsx' + (month ? `?month=${month}` : ''), { cache: 'no-store' });
    if (res.status === 401) { location.reload(); return; }
    if (!res.ok) throw new Error(res.status);
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const who = state.user ? state.user.username + '-' : '';
    a.download = month ? `money-tracker-${who}${month}.xlsx` : `money-tracker-${who}all-${toISODate(new Date())}.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    xlsDialog.close();
    showToast('Excel file downloaded');
  } catch (err) {
    showToast('Could not create the Excel file. Is the Money Tracker window still open?');
  } finally {
    btn.disabled = false;
  }
});

function backup() {
  download(`money-tracker-backup-${toISODate(new Date())}.json`, JSON.stringify({ app: 'money-tracker', version: 1, ...state.data }, null, 2), 'application/json');
}

$('#restoreFile').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  e.target.value = '';
  if (!file) return;
  try {
    const parsed = JSON.parse(await file.text());
    const valid = parsed && Array.isArray(parsed.transactions) && parsed.transactions.every(
      (t) => t && typeof t.id === 'string' && (t.type === 'income' || t.type === 'expense') &&
        Number.isInteger(t.amount) && typeof t.category === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(t.date));
    if (!valid) throw new Error('invalid');
    if (!confirm(`Replace your current data with ${parsed.transactions.length} transactions from this backup?`)) return;
    state.data = normalizeData(parsed);
    save();
    render();
    showToast('Backup restored');
  } catch {
    showToast('That file is not a valid Money Tracker backup');
  }
});

// ---------- Menu ----------
const menu = $('#menu');
const menuBtn = $('#menuBtn');
function setMenu(open) {
  menu.hidden = !open;
  menuBtn.setAttribute('aria-expanded', String(open));
}
menuBtn.addEventListener('click', (e) => { e.stopPropagation(); setMenu(menu.hidden); });
document.addEventListener('click', (e) => { if (!menu.hidden && !menu.contains(e.target)) setMenu(false); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') setMenu(false); });
menu.addEventListener('click', (e) => {
  const action = e.target.dataset.action;
  if (!action) return;
  setMenu(false);
  if (action === 'export-csv') exportCSV();
  if (action === 'export-xlsx') exportExcel();
  if (action === 'backup') backup();
  if (action === 'restore') $('#restoreFile').click();
  if (action === 'change-password') openPwDialog();
  if (action === 'logout') logoutNow();
});

// ---------- Navigation & controls ----------
function setView(view) {
  state.view = view;
  $$('.tab').forEach((b) => {
    const active = b.dataset.view === view;
    b.classList.toggle('active', active);
    if (active) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  $$('.view').forEach((v) => { v.hidden = v.id !== `view-${view}`; });
  document.body.dataset.view = view;
  tooltip.hidden = true;
  render();
  if (view === 'profile') refreshMe();
  if (view === 'users') loadUsers();
  if (onHelper && state.user) applyUserUI();
  window.scrollTo({ top: 0 });
}

$$('.tab').forEach((b) => b.addEventListener('click', () => setView(b.dataset.view)));
$('#prevMonth').addEventListener('click', () => { state.month = addMonths(state.month, -1); render(); });
$('#nextMonth').addEventListener('click', () => { state.month = addMonths(state.month, 1); render(); });
$$('[data-add]').forEach((b) => b.addEventListener('click', () => openDialog(null, b.dataset.add)));

$('#view-overview').addEventListener('click', (e) => {
  const period = e.target.closest('[data-period]');
  if (period) { state.period = period.dataset.period; render(); return; }
  const pay = e.target.closest('[data-pay]');
  if (pay) {
    // Pay today if today counts for this reminder date, otherwise date it on the due date
    const today = toISODate(new Date());
    const date = today > pay.dataset.prev && today <= pay.dataset.due ? today : pay.dataset.due;
    openDialog(null, 'expense', { category: pay.dataset.pay, dueFor: pay.dataset.due, amount: Number(pay.dataset.amount), date, note: `Payment due ${dayFmt.format(parseISODate(pay.dataset.due))}` });
    return;
  }
  const row = e.target.closest('.item');
  if (!row) return;
  const tx = state.data.transactions.find((t) => t.id === row.dataset.id);
  if (tx) openDialog(tx);
});

$('#budgetList').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-pay-cat]');
  if (btn && !btn.disabled) payCategory(btn.dataset.payCat);
});

// Every minute: open Paid buttons as soon as a reminder is sent, and start the new month on the 1st
let realMonth = monthKey(new Date());
setInterval(() => {
  if (!authScreen.hidden) return;
  const now = new Date();
  if (monthKey(now) !== realMonth) {
    const wasOnCurrent = monthKey(state.month) === realMonth;
    const finished = monthNameFmt.format(parseISODate(realMonth + '-01'));
    realMonth = monthKey(now);
    if (wasOnCurrent) {
      state.month = new Date(now.getFullYear(), now.getMonth(), 1);
      state.period = 'h1';
      render();
      showToast(`New month! ${finished} is saved to your archive. Expenses start fresh for ${monthNameFmt.format(now)}.`);
    }
    return;
  }
  if (state.view === 'budgets' && !document.hidden) renderBudgets();
}, 60000);

let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (state.view === 'summary') renderSummary(); }, 120);
});

// Keep tabs in sync if the app is open in two windows
window.addEventListener('storage', (e) => { if (!onHelper && e.key === STORAGE_KEY) { load(); render(); } });

// ---------- Login ----------
const authScreen = $('#authScreen');
let authInfo = { hasUsers: false, setupAllowed: false, loggedIn: false, user: null, bot: {} };
let loginDone = null;
let pendingPassword = ''; // temporary password typed at login, needed to set the user's own

function showAuth(formId) {
  authScreen.hidden = false;
  document.body.classList.add('locked');
  for (const f of authScreen.querySelectorAll('.auth-form')) f.hidden = f.id !== formId;
  const form = $('#' + formId);
  form.querySelectorAll('.auth-error, .auth-ok').forEach((el) => { el.hidden = true; });
  const first = [...form.querySelectorAll('input:not([type="checkbox"])')].find((i) => !i.value) || form.querySelector('input');
  if (first) setTimeout(() => first.focus(), 50);
}

function unlock() {
  authScreen.hidden = true;
  document.body.classList.remove('locked');
}

function authMessage(form, text, ok = false) {
  const err = form.querySelector('.auth-error');
  const good = form.querySelector('.auth-ok');
  if (err) { err.textContent = ok ? '' : text; err.hidden = ok || !text; }
  if (good) { good.textContent = ok ? text : ''; good.hidden = !ok || !text; }
}

async function authPost(path, payload) {
  const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || 'Something went wrong.');
  return body;
}

function newPasswordProblem(form) {
  const pw = form.password.value;
  if (pw.length < 8) return 'Use at least 8 characters.';
  if (pw !== form.confirm.value) return "The passwords don't match.";
  return '';
}

async function submitAuth(form, path, payload, onSuccess) {
  const btn = form.querySelector('button[type="submit"]');
  btn.disabled = true;
  try {
    const body = await authPost(path, payload);
    if (onSuccess) { onSuccess(body); return; }
    form.reset();
    if (loginDone) loginDone();
  } catch (err) {
    authMessage(form, err.message === 'Failed to fetch' ? 'Money Tracker is not responding. Is its window still open?' : err.message);
  } finally {
    btn.disabled = false;
  }
}

$('#setupForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = e.currentTarget;
  if (!f.elements.name.value.trim()) { authMessage(f, 'Enter your name.'); return; }
  const problem = newPasswordProblem(f);
  if (problem) { authMessage(f, problem); return; }
  submitAuth(f, 'api/setup', { name: f.elements.name.value, username: f.username.value.trim(), password: f.password.value, remember: f.remember.checked });
});

$('#loginForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = e.currentTarget;
  if (!f.username.value.trim()) { authMessage(f, 'Enter your username.'); return; }
  if (!f.password.value) { authMessage(f, 'Enter your password.'); return; }
  const password = f.password.value;
  submitAuth(f, 'api/login', { username: f.username.value.trim(), password, remember: f.remember.checked }, (body) => {
    f.password.value = '';
    if (body.user && body.user.mustChange) {
      pendingPassword = password;
      showAuth('newPasswordForm');
      return;
    }
    if (loginDone) loginDone();
  });
});

$('#newPasswordForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = e.currentTarget;
  const problem = newPasswordProblem(f);
  if (problem) { authMessage(f, problem); return; }
  if (f.password.value === pendingPassword) { authMessage(f, 'Choose a password that is different from the temporary one.'); return; }
  submitAuth(f, 'api/change-password', { current: pendingPassword, password: f.password.value }, () => {
    pendingPassword = '';
    f.reset();
    if (loginDone) loginDone();
  });
});

$('#forgotForm').addEventListener('submit', (e) => {
  e.preventDefault();
  const f = e.currentTarget;
  if (!f.username.value.trim()) { authMessage(f, 'Enter your username.'); return; }
  if (!/^\d{6}$/.test(f.code.value.trim())) { authMessage(f, 'Enter the 6-digit code from Telegram.'); return; }
  const problem = newPasswordProblem(f);
  if (problem) { authMessage(f, problem); return; }
  submitAuth(f, 'api/reset', { username: f.username.value.trim(), code: f.code.value.trim(), password: f.password.value });
});

$('#sendCode').addEventListener('click', async (e) => {
  const f = $('#forgotForm');
  if (!f.username.value.trim()) { authMessage(f, 'Enter your username first.'); f.username.focus(); return; }
  e.currentTarget.disabled = true;
  try {
    const body = await authPost('api/forgot', { username: f.username.value.trim() });
    authMessage(f, body.message || 'Check Telegram for your code.', true);
    f.code.focus();
  } catch (err) {
    authMessage(f, err.message);
  } finally {
    e.currentTarget.disabled = false;
  }
});

authScreen.addEventListener('click', (e) => {
  const link = e.target.closest('[data-auth]');
  if (!link) return;
  const fromLogin = $('#loginForm').username.value.trim();
  showAuth(link.dataset.auth === 'forgot' ? 'forgotForm' : 'loginForm');
  if (link.dataset.auth === 'forgot' && fromLogin && !$('#forgotForm').username.value) $('#forgotForm').username.value = fromLogin;
});

async function logoutNow() {
  try { await fetch('api/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
  location.reload();
}

// Change password
const pwDialog = $('#pwDialog');
const pwForm = $('#pwForm');
function openPwDialog() {
  pwForm.reset();
  $('#pwError').hidden = true;
  pwDialog.showModal();
  setTimeout(() => pwForm.current.focus(), 50);
}
pwForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = $('#pwError');
  const problem = !pwForm.current.value ? 'Enter your current password.' : newPasswordProblem(pwForm);
  if (problem) { err.textContent = problem; err.hidden = false; return; }
  try {
    await authPost('api/change-password', { current: pwForm.current.value, password: pwForm.password.value });
    pwDialog.close();
    showToast('Password changed');
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  }
});
$$('[data-close-pw]').forEach((b) => b.addEventListener('click', () => pwDialog.close()));

// ---------- Start ----------
window.appReady = (async () => {
  $$('[data-helper-only]').forEach((el) => { el.hidden = !onHelper; });

  if (!onHelper) {
    if (await moveToHelper()) return;
    let protectedApp = false;
    try { protectedApp = localStorage.getItem(PROTECTED_KEY) === '1'; } catch (e) { /* ignore */ }
    // Money Tracker keeps everyone's data on its server, so without it there is nothing to show
    // (MT_LOCAL_MODE is only for testing the pages without a server)
    if (protectedApp || !window.MT_LOCAL_MODE) {
      $('#lockedFileMode h1').textContent = 'Start Money Tracker';
      $('#lockedFileMode .auth-sub').innerHTML = 'Money Tracker isn\'t running. Double-click <code>scripts/start.bat</code> in the Money Tracker folder — it opens the app for you.';
      showAuth('lockedFileMode');
      return;
    }
    await load();
    unlock();
    render();
    return;
  }

  // Remove any copy of the data that older versions kept in this browser
  try { localStorage.removeItem(STORAGE_KEY); } catch (e) { /* ignore */ }

  const authRes = await fetch('api/auth', { cache: 'no-store' });
  if (authRes.status === 404) {
    // An older helper is still running (from before the login feature)
    $('#lockedFileMode h1').textContent = 'Restart Money Tracker';
    $('#lockedFileMode .auth-sub').innerHTML = 'An older version of the helper is still running. Close every <b>Money Tracker (keep open)</b> window, then run <code>scripts/start.bat</code> again.';
    showAuth('lockedFileMode');
    return;
  }
  authInfo = await authRes.json();
  if (!('hasUsers' in authInfo)) {
    // The server window still runs the version from before user accounts
    $('#lockedFileMode h1').textContent = 'Restart Money Tracker';
    $('#lockedFileMode .auth-sub').innerHTML = 'An older version of Money Tracker is still running. Close every <b>Money Tracker (keep open)</b> window, then run <code>scripts/start.bat</code> again.';
    showAuth('lockedFileMode');
    return;
  }
  if (!authInfo.loggedIn || (authInfo.user && authInfo.user.mustChange)) {
    // A temporary password must be replaced right after logging in with it
    if (authInfo.loggedIn) await fetch('api/logout', { method: 'POST' });
    if (!authInfo.hasUsers) showAuth(authInfo.setupAllowed ? 'setupForm' : 'setupElsewhere');
    else showAuth('loginForm');
    await new Promise((resolve) => { loginDone = resolve; });
    loginDone = null;
  }
  await refreshMe();
  await load();
  unlock();
  render();
  applyUserUI();
})();
