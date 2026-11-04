"""Delegation > bulk import: many tasks from one Excel / CSV sheet.

Every row becomes exactly the task the Assign Task form would have created. Rows are not
written by this module at all -- each valid row is handed to calendar_events.create_event,
the same function the form calls, so the access check, the assignee eligibility and rank
rules, the past-date policy, separate-per-assignee mode, notifications, the activity log and
the realtime refresh all apply unchanged. What this module owns is only the spreadsheet: the
template, reading it, and turning each row into a task payload or a list of row errors.

-- The template is built for the person downloading it ----------------------------------------
Category and Assign To are dropdowns filled from THIS user's categories and the people THEY may
assign to (a hidden-in-plain-sight "Lists" sheet), Deadline Date only accepts a date from today
on, and the mandatory columns (Task Title, Category, Deadline Date) have a red header. The
dropdowns still accept typed values -- a new category, or several assignees separated by commas.

-- Import is preview first ---------------------------------------------------------------------
A PREVIEW (dry run) validates every row and writes nothing. Anything a row is missing -- a
deadline above all -- can be filled in on the preview screen itself: those values come back
as `overrides` ({sheet row: {column: value}}) and are applied over the sheet before validating,
so the user never has to go back to Excel to set a due date. Then the import creates the valid
rows and reports the rest. A row with an error is never half-created.

-- One-time and repeating tasks ---------------------------------------------------------------
A row with no Repeat is a one-time task and needs a Deadline Date. A row with Repeat = Daily /
Weekly / Monthly / Yearly is a recurring task (a "Recurring Checklist"): it has no deadline --
each occurrence is due at the end of its own day -- and instead takes a Start Date, an optional
Repeat End Date, and for Weekly / Monthly the days it falls on (Repeat On). The series is then
built by the same engine as a repeating task from the form. "Periodically" and "Custom" stay in
the form.
"""
import csv
import io
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

MAX_ROWS = 500
IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_DEADLINE_TIME = time(23, 59)

# (key, header, required, help) -- the template's columns, in order.
COLUMNS = [
    ("title", "Task Title", True, "What has to be done."),
    ("description", "Description", False, "Details for the assignee."),
    ("category", "Category", True,
     "Pick from the list, or type a new category name (it is added to the list)."),
    ("assignees", "Assign To", False,
     "Pick a person from the list, or type names / emails separated by commas. "
     "Blank = assigned to yourself."),
    ("assignment_mode", "Assignment Mode", False,
     "Combined (one shared task, default) or Separate (one task per person). "
     "Only used when there are several assignees."),
    ("deadline_date", "Deadline Date", True,
     "ONE-TIME tasks: the due date, typed as DD-MM-YYYY (e.g. 22-11-2026), today or later. "
     "If you leave it blank you can still set it on the upload preview. Leave it blank for a "
     "repeating task -- each occurrence is due at the end of its own day."),
    ("deadline_time", "Deadline Time", False, "HH:MM, 24-hour, India time. Blank = 23:59."),
    ("repeat", "Repeat", False,
     "Blank = one-time task. Daily, Weekly, Monthly or Yearly = a repeating task."),
    ("repeat_on", "Repeat On", False,
     "Weekly: the weekdays, e.g. Mon, Thu. Monthly: the dates, e.g. 1, 15, Last (last day "
     "of the month). Blank = the Start Date's weekday / date. Not used for Daily / Yearly."),
    ("start_date", "Start Date", False,
     "Repeating tasks: the first day, DD-MM-YYYY, today or later. Blank = today."),
    ("repeat_end_date", "Repeat End Date", False,
     "Repeating tasks: the last day, DD-MM-YYYY. Blank = keeps repeating with no end."),
    ("priority", "Priority", False, "Low, Normal (default) or High."),
    ("watchers", "In Loop", False, "Names / emails of people kept informed, comma separated."),
    ("tags", "Tags", False, "Comma separated."),
    ("checklist", "Checklist Items", False,
     "Several items in one cell, separated by commas, semicolons or new lines (Alt+Enter): "
     "L1, L2, L3. Use ; or new lines if an item itself contains a comma."),
    ("evidence_required", "Evidence Required", False, "Yes / No (default No)."),
    ("verification_required", "Verification Required", False, "Yes / No (default No)."),
]
_norm_header = lambda h: re.sub(r"[^a-z]", "", str(h or "").lower())  # noqa: E731
HEADER_TO_KEY = {_norm_header(h): k for k, h, _r, _h in COLUMNS}
# Headers of the first template version, so a sheet downloaded before still imports.
HEADER_TO_KEY.update({"assigntoemails": "assignees", "inloopemails": "watchers"})
EDITABLE_ON_PREVIEW = ("deadline_date", "deadline_time", "category", "assignees",
                       "start_date", "repeat_end_date", "repeat_on")
REPEATS = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "yearly": "Yearly",
           "annually": "Yearly"}
NO_REPEAT = ("", "no", "none", "does not repeat", "one-time", "one time", "once")
# The form's weekday numbers: JavaScript's, Sun=0 ... Sat=6.
WEEKDAYS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
WEEKDAY_LABEL = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
EXAMPLE = {
    "title": "Submit monthly sales report", "description": "Region-wise numbers for October",
    "category": "Reporting", "assignees": "Asha Rao <asha@company.com>, ravi@company.com",
    "assignment_mode": "Separate", "deadline_date": "05-11-2026", "deadline_time": "17:00",
    "priority": "High", "watchers": "manager@company.com", "tags": "sales, monthly",
    "checklist": "Collect data; Prepare sheet; Share with manager",
    "repeat": "Weekly (or blank)", "repeat_on": "Mon, Thu", "start_date": "02-11-2026",
    "repeat_end_date": "31-03-2027",
    "evidence_required": "Yes", "verification_required": "No",
}


def person_label(user: dict) -> str:
    """How a person appears in the Assign To dropdown, and is read back: "Name <email>"."""
    name = (user.get("full_name") or "").strip()
    email = (user.get("email") or "").strip()
    return f"{name} <{email}>" if name and email and name != email else (email or name)


# ─────────────────────────────────────────────────────────────
# Template
# ─────────────────────────────────────────────────────────────
def build_template(categories: Optional[list] = None, people: Optional[list] = None) -> bytes:
    """The workbook for THIS user: their categories and the people they may assign to."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    categories = sorted({str(c).strip() for c in (categories or []) if str(c or "").strip()},
                        key=str.lower)
    labels = sorted({person_label(u) for u in (people or []) if person_label(u)}, key=str.lower)

    wb = Workbook()
    ws = wb.active
    ws.title = "Tasks"
    required_fill = PatternFill("solid", start_color="C00000")
    optional_fill = PatternFill("solid", start_color="1F3864")
    for i, (_k, header, required, _help) in enumerate(COLUMNS, start=1):
        c = ws.cell(1, i, header + (" *" if required else ""))
        c.font = Font(name="Arial", bold=True, color="FFFFFF")
        c.fill = required_fill if required else optional_fill
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = 34 if i in (1, 4) else 22
    ws.freeze_panes = "A2"
    col = {k: get_column_letter(i) for i, (k, *_r) in enumerate(COLUMNS, start=1)}
    last = MAX_ROWS + 1
    rng = lambda key: f"{col[key]}2:{col[key]}{last}"  # noqa: E731

    # The lists the dropdowns read from. Kept as a visible sheet, so the user can see every
    # category / person they may pick, and copy from it.
    lists = wb.create_sheet("Lists")
    lists["A1"], lists["B1"] = "Categories", "People you can assign to"
    for c in (lists["A1"], lists["B1"]):
        c.font = Font(name="Arial", bold=True)
    for r, name in enumerate(categories, start=2):
        lists.cell(r, 1, name).font = Font(name="Arial")
    for r, label in enumerate(labels, start=2):
        lists.cell(r, 2, label).font = Font(name="Arial")
    lists.column_dimensions["A"].width = 30
    lists.column_dimensions["B"].width = 48

    def dropdown(key, source, prompt, strict):
        dv = DataValidation(type="list", formula1=source, allow_blank=True,
                            showDropDown=False, showInputMessage=True, showErrorMessage=True,
                            promptTitle=dict((k, h) for k, h, *_ in COLUMNS)[key][:32],
                            prompt=prompt[:255])
        if not strict:
            # Information style: the list is offered, but a typed value is still accepted
            # (a new category, or several people separated by commas).
            dv.errorStyle = "information"
            dv.errorTitle, dv.error = "Not in the list", "Accepted as typed - check it on the preview."
        else:
            dv.errorTitle, dv.error = "Pick from the list", prompt[:255]
        dv.add(rng(key))
        ws.add_data_validation(dv)

    if categories:
        dropdown("category", f"=Lists!$A$2:$A${len(categories) + 1}",
                 "Required. Pick a category, or type a new one.", strict=False)
    if labels:
        dropdown("assignees", f"=Lists!$B$2:$B${len(labels) + 1}",
                 "Pick a person, or type names / emails separated by commas. Blank = yourself.",
                 strict=False)
    dropdown("priority", '"Low,Normal,High"', "Low, Normal or High.", strict=True)
    dropdown("assignment_mode", '"Combined,Separate"',
             "Combined = one shared task; Separate = one task per person.", strict=True)
    dropdown("repeat", '"Daily,Weekly,Monthly,Yearly"',
             "Blank = one-time task. Pick a frequency for a repeating task.", strict=True)
    dropdown("evidence_required", '"Yes,No"', "Yes or No.", strict=True)
    dropdown("verification_required", '"Yes,No"', "Yes or No.", strict=True)

    # The due date is typed as TEXT, DD-MM-YYYY. An Excel date rule here broke on computers
    # set to month-day-year: "22-11-2026" was rejected as month 22, and "05-11-2026" silently
    # became 11 May. Kept as text, the date reaches the import exactly as typed and is checked
    # (valid, not in the past) on the upload preview, which shows the date it understood.
    for key, title, prompt in (
            ("deadline_date", "Deadline Date",
             "One-time tasks: type the due date as DD-MM-YYYY, e.g. 22-11-2026. Blank for a repeating task."),
            ("deadline_time", "Deadline Time", "Optional. HH:MM, 24-hour, e.g. 17:00. Blank = 23:59."),
            ("repeat_on", "Repeat On", "Weekly: Mon, Thu ... Monthly: 1, 15, Last."),
            ("start_date", "Start Date", "Repeating tasks: first day, DD-MM-YYYY. Blank = today."),
            ("repeat_end_date", "Repeat End Date", "Repeating tasks: last day, DD-MM-YYYY. Blank = no end.")):
        hint = DataValidation(allow_blank=True, showInputMessage=True, showErrorMessage=False,
                              promptTitle=title, prompt=prompt)
        hint.add(rng(key))
        ws.add_data_validation(hint)
        for r in range(2, last + 1):
            ws[f"{col[key]}{r}"].number_format = "@"

    guide = wb.create_sheet("Instructions", 1)
    guide.column_dimensions["A"].width = 24
    guide.column_dimensions["B"].width = 12
    guide.column_dimensions["C"].width = 72
    guide.column_dimensions["D"].width = 42
    rows = [("Fill one task per row on the Tasks sheet. Columns with a RED header and * are "
             "mandatory. Category and Assign To offer a dropdown (see the Lists sheet). Upload "
             "the file from Delegation > Bulk import: you see a preview of every row - and can "
             "fill in a missing deadline, category or assignee there - before anything is created.",
             "", "", ""),
            ("", "", "", ""), ("Column", "Mandatory", "How to fill it", "Example")]
    for key, header, required, help_text in COLUMNS:
        rows.append((header, "Yes" if required else "", help_text, EXAMPLE.get(key, "")))
    for r, values in enumerate(rows, start=1):
        for c, v in enumerate(values, start=1):
            cell = guide.cell(r, c, v)
            cell.font = Font(name="Arial", bold=(r == 3),
                             color="C00000" if (r > 3 and values[1] == "Yes" and c <= 2) else None)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    guide.merge_cells("A1:D1")
    guide.row_dimensions[1].height = 60
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ─────────────────────────────────────────────────────────────
# Reading
# ─────────────────────────────────────────────────────────────
def read_sheet(filename: str, raw: bytes) -> list:
    """[{column key: value}] for every non-empty row of the Tasks sheet (or the CSV)."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        try:
            wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        except Exception:
            raise HTTPException(status_code=422, detail="This file could not be read as Excel.")
        ws = wb["Tasks"] if "Tasks" in wb.sheetnames else wb.worksheets[0]
        table = [list(r) for r in ws.iter_rows(values_only=True)]
    elif name.endswith(".csv"):
        text = raw.decode("utf-8-sig", errors="replace")
        table = [row for row in csv.reader(io.StringIO(text))]
    else:
        raise HTTPException(status_code=415, detail="Upload the filled template as .xlsx or .csv.")
    if not table:
        raise HTTPException(status_code=422, detail="The file is empty.")
    keys = [HEADER_TO_KEY.get(_norm_header(h)) for h in table[0]]
    if "title" not in keys:
        raise HTTPException(
            status_code=422,
            detail="No \"Task Title\" column found. Use the template from the Bulk import screen.")
    out = []
    for number, values in enumerate(table[1:], start=2):
        row = {k: v for k, v in zip(keys, values) if k}
        if all(v in (None, "") or (isinstance(v, str) and not v.strip()) for v in row.values()):
            continue
        row["_row"] = number
        out.append(row)
    if len(out) > MAX_ROWS:
        raise HTTPException(status_code=422,
                            detail=f"The file has {len(out)} tasks; import at most {MAX_ROWS} at a time.")
    return out


def apply_overrides(rows: list, overrides: Optional[dict]) -> list:
    """Values filled in on the preview screen, laid over the sheet: {row: {column: value}}.
    Only the columns the preview lets the user edit; a blank value leaves the sheet's alone."""
    by_row = {str(k): v for k, v in (overrides or {}).items() if isinstance(v, dict)}
    for row in rows:
        for key, value in (by_row.get(str(row["_row"])) or {}).items():
            if key in EDITABLE_ON_PREVIEW and _text(value):
                row[key] = value
    return rows


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _split(value, sep=",") -> list:
    return [p.strip() for p in re.split(sep, _text(value)) if p.strip()]


def _checklist_items(value) -> list:
    """Checklist items in one cell. Separated by ; or new lines when the cell uses them (then a
    comma stays inside an item: "Collect data, verify; Share"); otherwise by commas, the way
    every other list column in the sheet is written ("L1, L2")."""
    text = _text(value)
    return _split(text, r"[;\n]" if re.search(r"[;\n]", text) else ",")


def _yes(value) -> Optional[bool]:
    v = _text(value).lower()
    if v in ("", "no", "n", "false", "0"):
        return False if v else None
    if v in ("yes", "y", "true", "1"):
        return True
    return "bad"


def _parse_date(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    v = _text(value)
    if not v:
        return None
    # A typed date may carry a time ("2026-11-05 00:00:00" from a CSV export): try it whole,
    # then its date part.
    for candidate in (v, v.split(" ")[0]):
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y", "%d %b %Y",
                    "%d-%b-%Y"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return "bad"


def _parse_time(value) -> Optional[time]:
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0)
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    v = _text(value)
    if not v:
        return None
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})(?::\d{2})?\s*([AaPp][Mm])?", v)
    if not m:
        return "bad"
    h, mnt = int(m.group(1)), int(m.group(2))
    if m.group(3):
        if not 1 <= h <= 12:
            return "bad"
        h = h % 12 + (12 if m.group(3).lower() == "pm" else 0)
    if h > 23 or mnt > 59:
        return "bad"
    return time(h, mnt)


def _parse_repeat_on(repeat: str, value) -> tuple:
    """(repeat_data, error) for Weekly / Monthly. Blank -> empty repeat_data (filled from the
    Start Date by the caller)."""
    parts = _split(value, r"[,;/]")
    if repeat == "Weekly":
        days = []
        for p in parts:
            d = WEEKDAYS.get(p.strip().lower()[:3])
            if d is None:
                return None, f"Repeat On has an unknown weekday \"{p}\" (use Mon, Tue, Wed, Thu, Fri, Sat, Sun)."
            days.append(d)
        return {"weekdays": sorted(set(days)), "monthlyDates": [], "lastDay": False}, None
    if repeat == "Monthly":
        dates, last = [], False
        for p in parts:
            if p.strip().lower() in ("last", "last day", "l"):
                last = True
            elif p.strip().isdigit() and 1 <= int(p) <= 31:
                dates.append(int(p))
            else:
                return None, f"Repeat On has an unknown month date \"{p}\" (use 1-31 or Last)."
        if last:   # the form keeps "Last day" exclusive of picked dates
            dates = []
        return {"weekdays": [], "monthlyDates": sorted(set(dates)), "lastDay": last}, None
    return {"weekdays": [], "monthlyDates": [], "lastDay": False}, None


def _first_occurrence(start: date, repeat: str, data: dict) -> date:
    """The first day on/after `start` the series actually falls on, so a "Weekly on Mon, Thu"
    series starting on a Sunday opens on Monday, not on the Sunday."""
    import calendar
    for ahead in range(0, 400):
        d = start + timedelta(days=ahead)
        if repeat == "Weekly" and data["weekdays"]:
            if (d.weekday() + 1) % 7 in data["weekdays"]:      # python Mon=0 -> js Mon=1
                return d
        elif repeat == "Monthly" and (data["monthlyDates"] or data["lastDay"]):
            last_day = calendar.monthrange(d.year, d.month)[1]
            if (data["lastDay"] and d.day == last_day) or d.day in data["monthlyDates"]:
                return d
        else:
            return d
    return start


def _repeat_summary(repeat: str, data: dict, start: date, end: Optional[date]) -> str:
    on = ""
    if repeat == "Weekly":
        on = " on " + ", ".join(WEEKDAY_LABEL[d] for d in data["weekdays"])
    elif repeat == "Monthly":
        on = " on " + ("the last day" if data["lastDay"]
                       else "day " + ", ".join(str(d) for d in data["monthlyDates"]))
    return (f"{repeat}{on} from {start.strftime('%d %b %Y')}"
            + (f" to {end.strftime('%d %b %Y')}" if end else ", no end date"))


# ─────────────────────────────────────────────────────────────
# People
# ─────────────────────────────────────────────────────────────
class People:
    """Resolves what a user typed or picked -- "Name <email>", an email, or a name -- to one
    person. A name must match exactly one person; two people with the same name need the email."""

    def __init__(self, users: list):
        self.by_email, self.by_name = {}, {}
        for u in users or []:
            email = (u.get("email") or "").strip().lower()
            if email:
                self.by_email[email] = u
            name = (u.get("full_name") or "").strip().lower()
            if name:
                self.by_name.setdefault(name, []).append(u)

    def find(self, typed: str) -> tuple:
        """(user, None) or (None, why)."""
        text = typed.strip()
        m = re.search(r"<\s*([^<>\s]+@[^<>\s]+)\s*>", text)
        email = (m.group(1) if m else (text if "@" in text else "")).lower()
        if email:
            u = self.by_email.get(email)
            return (u, None) if u else (None, "not found")
        matches = self.by_name.get(text.lower()) or []
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, "more than one person has this name - use the email"
        return None, "not found"


async def directory(current_user: dict) -> tuple:
    """(People the caller may ASSIGN to, People the caller may keep In Loop) -- the same two
    lists the Assign Task form's pickers use -- and the assignable list itself."""
    from app.routes.tasks import list_assignable_users
    assignable = await list_assignable_users(include_all=False, current_user=current_user)
    everyone = await list_assignable_users(include_all=True, current_user=current_user)
    return People(assignable), People(everyone), assignable


async def category_names() -> list:
    from app.routes.task_meta import _list_names
    return [c["name"] for c in await _list_names("task_categories", active_only=True) if c.get("name")]


# ─────────────────────────────────────────────────────────────
# Validation -> task payloads
# ─────────────────────────────────────────────────────────────
def validate_rows(rows: list, assignable: "People", everyone: "People", *, today: date,
                  categories: Optional[list] = None) -> list:
    """One result per row: {row, title, ..., errors, payload}. Pure (no I/O).

    `categories` are the existing names: a typed "marketing" is stored as the existing
    "Marketing" rather than becoming a second category that differs only in case."""
    known = {str(c).strip().lower(): str(c).strip() for c in (categories or []) if str(c or "").strip()}
    results = []
    for raw in rows:
        errors = []
        title = _text(raw.get("title"))[:300]
        category = _text(raw.get("category"))[:100]
        category = known.get(category.lower(), category)
        if not title:
            errors.append("Task Title is required.")
        if not category:
            errors.append("Category is required.")

        assignees, unknown = [], []
        for typed in _split(raw.get("assignees")):
            u, why = assignable.find(typed)
            if u and all(u["_id"] != a["_id"] for a in assignees):
                assignees.append(u)
            elif not u:
                unknown.append(f"{typed} ({why})")
        if unknown:
            errors.append("Cannot assign to: " + "; ".join(unknown)
                          + ". Pick the person from the list, or use their email.")
        watchers, unknown_w = [], []
        for typed in _split(raw.get("watchers")):
            u, why = everyone.find(typed)
            if u and all(u["_id"] != w["_id"] for w in watchers):
                watchers.append(u)
            elif not u:
                unknown_w.append(f"{typed} ({why})")
        if unknown_w:
            errors.append("In Loop not found: " + "; ".join(unknown_w) + ".")

        mode = _text(raw.get("assignment_mode")).lower() or "combined"
        if mode not in ("combined", "separate"):
            errors.append("Assignment Mode must be Combined or Separate.")
        priority = _text(raw.get("priority")).capitalize() or "Normal"
        if priority not in ("Low", "Normal", "High"):
            errors.append("Priority must be Low, Normal or High.")

        repeat_text = _text(raw.get("repeat")).lower()
        repeat = None if repeat_text in NO_REPEAT else REPEATS.get(repeat_text)
        if repeat_text not in NO_REPEAT and not repeat:
            errors.append("Repeat must be blank (one-time), Daily, Weekly, Monthly or Yearly.")
            repeat_text = "bad"

        deadline, series, summary = None, None, None
        if repeat:
            # A repeating task has no deadline: each occurrence is due at the end of its day.
            start = _parse_date(raw.get("start_date"))
            end = _parse_date(raw.get("repeat_end_date"))
            if start == "bad":
                errors.append("Start Date is not a date (use DD-MM-YYYY).")
            if end == "bad":
                errors.append("Repeat End Date is not a date (use DD-MM-YYYY).")
            start = start if isinstance(start, date) else (today if start is None else None)
            data, why = _parse_repeat_on(repeat, raw.get("repeat_on"))
            if why:
                errors.append(why)
            if start and data is not None:
                if start < today:
                    errors.append("Start Date cannot be in the past.")
                # Blank Repeat On: the Start Date's own weekday / date, as the form would.
                if repeat == "Weekly" and not data["weekdays"]:
                    data["weekdays"] = [(start.weekday() + 1) % 7]
                if repeat == "Monthly" and not (data["monthlyDates"] or data["lastDay"]):
                    data["monthlyDates"] = [start.day]
                first = _first_occurrence(start, repeat, data)
                if isinstance(end, date) and end < first:
                    errors.append("Repeat End Date is before the first occurrence.")
                series = {"start": first, "end": end if isinstance(end, date) else None, "data": data}
                summary = _repeat_summary(repeat, data, first, series["end"])
        elif repeat_text != "bad":
            d = _parse_date(raw.get("deadline_date"))
            t = _parse_time(raw.get("deadline_time"))
            if d == "bad":
                errors.append("Deadline Date is not a date (use DD-MM-YYYY).")
            if t == "bad":
                errors.append("Deadline Time is not a time (use HH:MM).")
            if isinstance(d, date):
                if d < today:
                    errors.append("Deadline Date cannot be in the past.")
                deadline = datetime.combine(d, t if isinstance(t, time) else DEFAULT_DEADLINE_TIME, IST)
            elif d is None:
                errors.append("Deadline Date is required - set the due date (or set Repeat for a repeating task).")
        d = _parse_date(raw.get("deadline_date"))

        flags = {}
        for key, label in (("evidence_required", "Evidence Required"),
                           ("verification_required", "Verification Required")):
            v = _yes(raw.get(key))
            if v == "bad":
                errors.append(f"{label} must be Yes or No.")
            flags[key] = bool(v) if v != "bad" else False

        checklist = [{"id": f"imp-{uuid.uuid4().hex[:10]}", "title": item[:300],
                      "completed": False, "completed_at": None}
                     for item in _checklist_items(raw.get("checklist"))]
        result = {
            "row": raw["_row"], "title": title, "category": category,
            # Unresolved entries are shown as typed, so a row that failed to resolve its
            # assignee never reads as "assigned to myself" in the preview.
            "assignees": [u.get("full_name") or u.get("email") for u in assignees]
            + [x.split(" (")[0] for x in unknown],
            "assignees_input": _text(raw.get("assignees")),
            "watchers": [u.get("full_name") or u.get("email") for u in watchers],
            "deadline": deadline.strftime("%d %b %Y, %H:%M") if deadline else None,
            "repeat": repeat, "repeat_summary": summary,
            "repeat_on_input": _text(raw.get("repeat_on")),
            "start_date": series["start"].isoformat() if series else None,
            "repeat_end_date": series["end"].isoformat() if series and series["end"] else None,
            "deadline_date": d.isoformat() if isinstance(d, date) else None,
            "priority": priority, "assignment_mode": mode.capitalize(),
            "checklist_items": len(checklist), "errors": errors, "payload": None,
        }
        if not errors:
            ids = [u["_id"] for u in assignees]
            result["payload"] = {
                "type": "task", "title": title,
                "description": _text(raw.get("description"))[:5000] or None,
                "category": category, "tags": _split(raw.get("tags")),
                "start": (f"{series['start'].isoformat()}T00:00:00+05:30" if series
                          else datetime.now(timezone.utc).isoformat()),
                "end": deadline.astimezone(timezone.utc).isoformat() if deadline else None,
                "repeat": repeat or "Does not repeat", "priority": priority,
                "repeat_interval": 1,
                "repeat_data": series["data"] if series else None,
                "repeat_end_date": (series["end"].isoformat() if series and series["end"] else None),
                "assigned_to": "other" if ids else "myself", "target_staff_id": ids,
                "assignment_mode": mode if len(ids) > 1 else "combined",
                "watchers": [u["_id"] for u in watchers], "checklist": checklist,
                **flags,
            }
        results.append(result)
    return results
