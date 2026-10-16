"""Builds the Money Tracker Excel workbook (.xlsx) with the Python standard library only."""

import calendar
import datetime as dt
import io
import re
import zipfile
from xml.sax.saxutils import escape

# Cell styles (indexes into cellXfs in styles.xml below)
TEXT, HEADER, PESO, DATE, BOLD_PESO, BOLD, TITLE, PERCENT, MUTED = range(9)

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="3">
    <numFmt numFmtId="164" formatCode="&quot;₱&quot;#,##0.00;[Red]-&quot;₱&quot;#,##0.00"/>
    <numFmt numFmtId="165" formatCode="mmm d, yyyy"/>
    <numFmt numFmtId="166" formatCode="0%"/>
  </numFmts>
  <fonts count="5">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="16"/><color rgb="FF5E1A96"/><name val="Calibri"/></font>
    <font><i/><sz val="10"/><color rgb="FF7A6A90"/><name val="Calibri"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF5E1A96"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left/><right/><top style="thin"><color rgb="FF5E1A96"/></top><bottom/><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="9">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="164" fontId="2" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
    <xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyFont="1"/>
  </cellXfs>
</styleSheet>"""

_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _col(n):
    name = ""
    while n:
        n, r = divmod(n - 1, 26)
        name = chr(65 + r) + name
    return name


def _excel_date(iso):
    return (dt.date.fromisoformat(iso) - dt.date(1899, 12, 30)).days


class Sheet:
    def __init__(self, name, widths):
        self.name = name
        self.widths = widths
        self.rows = []          # list of lists of (value, style)
        self.header_row = None  # 1-based row to freeze/filter under
        self.filter_cols = 0

    def add(self, *cells):
        self.rows.append([c if isinstance(c, tuple) else (c, TEXT) for c in cells])

    def header(self, *names, filter=False):
        self.add(*[(n, HEADER) for n in names])
        self.header_row = len(self.rows)
        if filter:
            self.filter_cols = len(names)

    def blank(self):
        self.rows.append([])

    def xml(self):
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
        if self.header_row:
            out.append(f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{self.header_row}" '
                       f'topLeftCell="A{self.header_row + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
        out.append("<cols>" + "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
                                      for i, w in enumerate(self.widths, 1)) + "</cols>")
        out.append("<sheetData>")
        for r, row in enumerate(self.rows, 1):
            cells = []
            for c, (value, style) in enumerate(row, 1):
                ref = f"{_col(c)}{r}"
                if value is None or value == "":
                    if style:
                        cells.append(f'<c r="{ref}" s="{style}"/>')
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    cells.append(f'<c r="{ref}" s="{style}"><v>{value}</v></c>')
                else:
                    text = escape(_BAD_XML.sub("", str(value)))
                    cells.append(f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>')
            out.append(f'<row r="{r}">' + "".join(cells) + "</row>")
        out.append("</sheetData>")
        if self.filter_cols and len(self.rows) > self.header_row:
            out.append(f'<autoFilter ref="A{self.header_row}:{_col(self.filter_cols)}{len(self.rows)}"/>')
        out.append("</worksheet>")
        return "".join(out)


def _workbook(sheets):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(sheets) + 1)) + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(s.name)}" sheetId="{i}" r:id="rId{i}"/>' for i, s in enumerate(sheets, 1))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml", STYLES)
        for i, s in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", s.xml())
    return buf.getvalue()


def _peso(cents):
    return round(cents / 100, 2)


def _month_label(key):
    y, m = map(int, key.split("-"))
    return f"{calendar.month_name[m]} {y}"


def build_workbook(data, today, owner, scheduled, amount_of, limit_of, period=None, generated=None):
    """data: the app data; scheduled: the payment schedule; amount_of/limit_of: category amounts.

    period: a month label (e.g. "October 2026") when the workbook covers one month only.
    """
    txs = sorted((t for t in data.get("transactions", []) if isinstance(t, dict) and t.get("date")),
                 key=lambda t: (t["date"], t.get("created", 0)))
    income = sum(t["amount"] for t in txs if t.get("type") == "income")
    expense = sum(t["amount"] for t in txs if t.get("type") == "expense")
    month_key = today.strftime("%Y-%m")

    # --- Summary ---
    summary = Sheet("Summary", [24, 18, 18, 18, 14])
    summary.add((f"Money Tracker report — {period}" if period else "Money Tracker report", TITLE))
    summary.add((f"Generated {(generated or today):%B %d, %Y} · Made by {owner}", MUTED))
    summary.blank()
    scope = period or "all time"
    summary.add(("Left" if period else "Total balance", BOLD), (_peso(income - expense), BOLD_PESO))
    summary.add(f"Money in ({scope})", (_peso(income), PESO))
    summary.add(f"Money out ({scope})", (_peso(expense), PESO))
    summary.add("Transactions", len(txs))
    summary.blank()
    summary.header("Month", "Money in", "Money out", "Net", "Saved")
    months = sorted({t["date"][:7] for t in txs} | {month_key}) if not period else [month_key]
    for key in months:
        mi = sum(t["amount"] for t in txs if t["date"].startswith(key) and t.get("type") == "income")
        mo = sum(t["amount"] for t in txs if t["date"].startswith(key) and t.get("type") == "expense")
        summary.add(_month_label(key), (_peso(mi), PESO), (_peso(mo), PESO), (_peso(mi - mo), PESO),
                    ((mi - mo) / mi, PERCENT) if mi else "")
    summary.add(("Total", BOLD), (_peso(income), BOLD_PESO), (_peso(expense), BOLD_PESO), (_peso(income - expense), BOLD_PESO), ("", BOLD))

    # --- Half-months ---
    halves = Sheet("Half-months", [18, 16, 16, 16, 16])
    halves.header("Month", "Period", "Money in", "Money out", "Net")
    for key in months:
        y, m = map(int, key.split("-"))
        last = calendar.monthrange(y, m)[1]
        for a, b in ((1, 15), (16, last)):
            lo, hi = f"{key}-{a:02d}", f"{key}-{b:02d}"
            part = [t for t in txs if lo <= t["date"] <= hi]
            mi = sum(t["amount"] for t in part if t.get("type") == "income")
            mo = sum(t["amount"] for t in part if t.get("type") == "expense")
            halves.add(_month_label(key), f"{calendar.month_abbr[m]} {a}–{b}", (_peso(mi), PESO), (_peso(mo), PESO), (_peso(mi - mo), PESO))

    # --- Transactions ---
    trans = Sheet("Transactions", [14, 12, 22, 14, 16, 36, 16])
    trans.header("Date", "Type", "Category", "Amount", "Effect on balance", "Note", "Paid for due date", filter=True)
    for t in txs:
        sign = 1 if t.get("type") == "income" else -1
        trans.add((_excel_date(t["date"]), DATE), "Money in" if sign > 0 else "Money out", t.get("category", ""),
                  (_peso(t["amount"]), PESO), (_peso(sign * t["amount"]), PESO), t.get("note", ""),
                  (_excel_date(t["dueFor"]), DATE) if t.get("dueFor") else "")

    # --- Bills & categories ---
    cats = Sheet("Bills & categories", [12, 24, 8, 16, 16, 18, 16, 14, 18, 16, 12])
    mon = calendar.month_abbr[today.month]
    cats.header("Type", "Category", "Icon", "Amount per payment", f"Limit for {mon}", f"Spent in {mon}", "Left / over",
                "Status", "Repeats on days", "One-time date", "Reminder time")
    budgets = data.get("budgets") or {}
    spent = {}
    for t in txs:
        if t.get("type") == "expense" and t["date"].startswith(month_key):
            spent[t.get("category")] = spent.get(t.get("category"), 0) + t["amount"]
    categories = data.get("categories") or {}
    for c in categories.get("expense", []):
        name = c.get("name", "")
        amount, b, s = amount_of(c, budgets), limit_of(c, budgets, today), spent.get(name, 0)
        status = "No limit" if not b else "Over budget" if s > b else "Near limit" if s >= b * 0.8 else "OK"
        rem = c.get("reminder") or {}
        days = ", ".join(str(d) for d in sorted(rem.get("days") or []))
        one_time = rem.get("date") or ""
        cats.add("Spending", name, c.get("icon", ""), (_peso(amount), PESO) if amount else "", (_peso(b), PESO) if b else "",
                 (_peso(s), PESO), (_peso(b - s), PESO) if b else "", status, days,
                 (_excel_date(one_time), DATE) if one_time else "", rem.get("time", "") if (days or one_time) else "")
    for c in categories.get("income", []):
        cats.add("Money in", c.get("name", ""), c.get("icon", ""))

    # --- Payment schedule ---
    sched = Sheet("Payment schedule", [22, 16, 18, 14, 16, 16])
    sched.header("Category", "Due date", "Expected amount", "Status", "Paid on", "Paid amount", filter=True)
    for row in scheduled:
        sched.add(row["category"], (_excel_date(row["due"]), DATE), (_peso(row["expected"]), PESO) if row["expected"] else "",
                  row["status"], (_excel_date(row["paid_on"]), DATE) if row.get("paid_on") else "",
                  (_peso(row["paid_amount"]), PESO) if row.get("paid_amount") else "")
    if not scheduled:
        sched.add(("No spending categories have reminder days yet.", MUTED))

    return _workbook([summary, halves, trans, cats, sched])
