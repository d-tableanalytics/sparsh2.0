"""HRMS ▸ Disbursal ▸ configurable bank file formats (Phase 1 FRD §13, §19, §21).

§19 lists "Bank File Format — bank-specific layout and mandatory fields" as an open
decision. The implementation answered it anyway, in code: one CSV, twelve columns, in an
order nobody chose, with a totals row some banks reject outright. Every bank's upload
template differs — column order, fixed-width padding, date and amount conventions, header
and trailer records — so the one thing certain about a hard-coded layout is that it is
wrong for the bank the client actually uses.

A FORMAT is a small spec. Rendering it is this module; what the rows CONTAIN stays with
hrms_disbursal_service, which knows what a payment is.

── The DEFAULT format ──────────────────────────────────────────────────────────────────
Seeded to reproduce the previous hard-coded output EXACTLY, including the blank line and
the totals row. That is deliberate and it is tested: a company that has configured nothing
must get byte-identical files after this change, because somebody downstream has a macro
built on the old shape.

── Why a spec rather than a template string ────────────────────────────────────────────
A free-text template ("{account},{amount}\\n") would be shorter and would also be a tiny
programming language with no validation, no preview and no way to answer "which fields does
this format require". A column list can be checked, previewed, and asked questions.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import COLL_BANK_FILE_FORMATS
from app.services.hrms_audit_service import audit

AUDIT_BANK_FORMAT_SAVED = "bank file format saved"
ENTITY_BANK_FORMAT = "bank_file_format"

# Every value a column may draw on. Named here so the designer can offer a list and
# `save_format` can refuse a typo rather than silently emitting blanks for every employee.
SOURCE_FIELDS = {
    "batch_no": "Batch number",
    "period": "Payroll period (YYYY-MM)",
    "employee_code": "Employee ID",
    "employee_name": "Employee name",
    "account_holder": "Beneficiary name",
    "bank_account": "Account number",
    "bank_ifsc": "IFSC",
    "bank_name": "Bank",
    "bank_branch": "Branch",
    "bank_account_type": "Account type",
    "amount": "Net pay",
    "payment_mode": "Payment mode",
    "narration": "Narration",
    "generated_date": "File generated date",
    "serial": "Row number (1, 2, 3 …)",
    "constant": "A fixed value you type",
}
ALIGNMENTS = ("left", "right")
AMOUNT_FORMATS = {
    "2dp": "1234.50",
    "0dp": "1235",
    "paise": "123450          (no decimal point)",
    "comma": "1,234.50",
}
DATE_FORMATS = {
    "iso": "2026-03-31", "dmy": "31/03/2026", "dmy_dash": "31-03-2026",
    "mdy": "03/31/2026", "compact": "20260331",
}

DEFAULT_FORMAT_NAME = "DEFAULT"

# The previous hard-coded layout, as a format -- totals row included -- plus the Generated
# Date column P1-108 requires.
DEFAULT_FORMAT = {
    "name": DEFAULT_FORMAT_NAME,
    "bank": None,
    "description": "The original HRMS layout. Kept so existing downstream tooling is "
                   "unaffected; copy it to build a bank-specific one.",
    "delimiter": ",",
    "fixed_width": False,
    "quote_all": False,
    "include_header": True,
    "amount_format": "2dp",
    "date_format": "iso",
    "narration_template": "Salary {period}",
    "include_totals_row": True,
    "columns": [
        {"source": "batch_no", "label": "Batch No"},
        {"source": "period", "label": "Payroll Period"},
        # P1-108: the file carries the date it was generated, beside batch, period and the
        # control total. The one deliberate change to the original layout.
        {"source": "generated_date", "label": "Generated Date"},
        {"source": "employee_code", "label": "Employee ID"},
        {"source": "account_holder", "label": "Beneficiary Name"},
        {"source": "bank_account", "label": "Account Number"},
        {"source": "bank_ifsc", "label": "IFSC"},
        {"source": "bank_name", "label": "Bank"},
        {"source": "bank_branch", "label": "Branch"},
        {"source": "bank_account_type", "label": "Account Type"},
        {"source": "amount", "label": "Amount"},
        {"source": "payment_mode", "label": "Payment Mode"},
        {"source": "narration", "label": "Narration"},
    ],
}


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id", "")) or None
    return doc


def _actor_id(actor) -> str:
    return str((actor or {}).get("_id") or "")


# ─────────────────────────────────────────────────────────────
# Format master
# ─────────────────────────────────────────────────────────────
async def list_formats(company_id: str) -> list:
    """Every format this company has, with DEFAULT always present.

    DEFAULT is synthesised rather than written at onboarding: a company that has never
    opened this screen still needs a format to download with, and seeding a row for every
    company to hold a constant would be a migration that buys nothing.
    """
    rows = await get_collection(COLL_BANK_FILE_FORMATS).find(
        {"company_id": str(company_id)}).sort("name", 1).to_list(100)
    out = [_out(r) for r in rows]
    if not any(f["name"] == DEFAULT_FORMAT_NAME for f in out):
        out.insert(0, {**DEFAULT_FORMAT, "id": None, "built_in": True})
    return out


async def get_format(company_id: str, name: Optional[str]) -> dict:
    """One format by name, or the company's default. Never raises for a missing format —
    an unknown name resolves to DEFAULT, because a download that fails is worse than one
    in a layout somebody has to fix."""
    if name and name != DEFAULT_FORMAT_NAME:
        doc = await get_collection(COLL_BANK_FILE_FORMATS).find_one(
            {"company_id": str(company_id), "name": name})
        if doc:
            return _out(doc)
    doc = await get_collection(COLL_BANK_FILE_FORMATS).find_one(
        {"company_id": str(company_id), "name": DEFAULT_FORMAT_NAME})
    return _out(doc) if doc else {**DEFAULT_FORMAT, "built_in": True}


def _clean_columns(columns) -> list:
    if not isinstance(columns, list) or not columns:
        raise HTTPException(status_code=422, detail="A format needs at least one column.")
    if len(columns) > 60:
        raise HTTPException(status_code=422, detail="A format may have up to 60 columns.")
    out = []
    for i, col in enumerate(columns, start=1):
        source = str((col or {}).get("source") or "").strip()
        if source not in SOURCE_FIELDS:
            raise HTTPException(
                status_code=422,
                detail=f"Column {i}: '{source}' is not a field. Use one of: "
                       f"{', '.join(sorted(SOURCE_FIELDS))}.")
        entry = {"source": source,
                 "label": str(col.get("label") or SOURCE_FIELDS[source])[:60]}
        if source == "constant":
            entry["value"] = str(col.get("value") or "")[:120]
        if col.get("width") is not None:
            try:
                entry["width"] = max(1, min(200, int(col["width"])))
            except (TypeError, ValueError):
                raise HTTPException(status_code=422,
                                    detail=f"Column {i}: width must be a whole number.")
        align = str(col.get("align") or "left").lower()
        if align not in ALIGNMENTS:
            raise HTTPException(status_code=422,
                                detail=f"Column {i}: align must be left or right.")
        entry["align"] = align
        if col.get("pad"):
            entry["pad"] = str(col["pad"])[:1]
        out.append(entry)
    return out


async def save_format(actor: dict, company_id: str, payload: dict) -> dict:
    name = str(payload.get("name") or "").strip().upper()[:40]
    if not name:
        raise HTTPException(status_code=422, detail="A format needs a name.")
    columns = _clean_columns(payload.get("columns"))
    fixed = bool(payload.get("fixed_width"))
    if fixed and any("width" not in c for c in columns):
        raise HTTPException(
            status_code=422,
            detail="A fixed-width format needs a width on every column — without one there "
                   "is nothing to pad to.")
    amount_format = str(payload.get("amount_format") or "2dp")
    if amount_format not in AMOUNT_FORMATS:
        raise HTTPException(status_code=422,
                            detail=f"Amount format must be one of: "
                                   f"{', '.join(sorted(AMOUNT_FORMATS))}.")
    date_format = str(payload.get("date_format") or "iso")
    if date_format not in DATE_FORMATS:
        raise HTTPException(status_code=422,
                            detail=f"Date format must be one of: "
                                   f"{', '.join(sorted(DATE_FORMATS))}.")

    now = datetime.now(timezone.utc)
    coll = get_collection(COLL_BANK_FILE_FORMATS)
    current = await coll.find_one({"company_id": str(company_id), "name": name})
    doc = {
        "bank": str(payload.get("bank") or "").strip()[:80] or None,
        "description": str(payload.get("description") or "").strip()[:300] or None,
        "delimiter": str(payload.get("delimiter") or ",")[:3],
        "fixed_width": fixed,
        "quote_all": bool(payload.get("quote_all")),
        "include_header": bool(payload.get("include_header", True)),
        "include_totals_row": bool(payload.get("include_totals_row")),
        "amount_format": amount_format,
        "date_format": date_format,
        "narration_template": str(payload.get("narration_template") or "Salary {period}")[:120],
        "header_lines": [str(x)[:300] for x in (payload.get("header_lines") or [])][:5],
        "trailer_lines": [str(x)[:300] for x in (payload.get("trailer_lines") or [])][:5],
        "columns": columns,
        "updated_at": now,
        # A format carries a version for the same reason a payslip template does: a batch
        # records which one produced it, so a file can be explained months later.
        "version": int((current or {}).get("version") or 0) + 1,
    }
    await coll.update_one(
        {"company_id": str(company_id), "name": name},
        {"$set": doc,
         "$setOnInsert": {"company_id": str(company_id), "name": name, "created_at": now,
                          "created_by": _actor_id(actor)}},
        upsert=True)
    await audit(actor, AUDIT_BANK_FORMAT_SAVED, ENTITY_BANK_FORMAT, name,
                doc.get("bank"), company_id)
    return _out(await coll.find_one({"company_id": str(company_id), "name": name}))


async def delete_format(actor: dict, company_id: str, name: str) -> dict:
    if str(name).upper() == DEFAULT_FORMAT_NAME:
        raise HTTPException(status_code=409,
                            detail="The DEFAULT format cannot be deleted — it is what a "
                                   "download falls back to.")
    await get_collection(COLL_BANK_FILE_FORMATS).delete_one(
        {"company_id": str(company_id), "name": str(name).upper()})
    return {"removed": True}


# ─────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────
def _half_up(value: float) -> int:
    """Round half AWAY FROM ZERO, which is what a finance team means by "rounded".

    Python's round() is banker's rounding: round(48750.5) is 48750, not 48751. That is the
    right default for statistics and the wrong one for a payment instruction, where the
    figure has to match what the payroll register says to the rupee.
    """
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _format_amount(value, how: str) -> str:
    amount = float(value or 0)
    if how == "0dp":
        return f"{_half_up(amount):d}"
    if how == "paise":
        return f"{_half_up(amount * 100):d}"
    if how == "comma":
        return f"{amount:,.2f}"
    return f"{amount:.2f}"


def _format_date(value, how: str) -> str:
    text = str(value or "")[:10]
    if len(text) != 10 or how == "iso":
        return text
    y, m, d = text[:4], text[5:7], text[8:10]
    return {"dmy": f"{d}/{m}/{y}", "dmy_dash": f"{d}-{m}-{y}",
            "mdy": f"{m}/{d}/{y}", "compact": f"{y}{m}{d}"}.get(how, text)


def _cell(column: dict, payment: dict, context: dict, fmt: dict) -> str:
    source = column["source"]
    if source == "constant":
        return str(column.get("value") or "")
    if source == "serial":
        return str(context.get("serial") or "")
    if source == "amount":
        return _format_amount(payment.get("amount"), fmt.get("amount_format") or "2dp")
    if source == "generated_date":
        return _format_date(context.get("generated_date"), fmt.get("date_format") or "iso")
    if source == "narration":
        template = fmt.get("narration_template") or "Salary {period}"
        try:
            return template.format(period=payment.get("period") or "",
                                   employee_code=payment.get("employee_code") or "",
                                   employee_name=payment.get("employee_name") or "",
                                   batch_no=context.get("batch_no") or "")
        except (KeyError, IndexError):
            # A template naming something that is not a field must not break every
            # download; the raw template is a visible symptom, an exception is not.
            return template
    # Fall back to the batch context: batch_no and period describe the FILE, and a payment
    # row is not obliged to repeat them. Reading only the row is how the batch number came
    # out blank the first time this was written.
    value = payment.get(source)
    if value is None:
        value = context.get(source)
    return str(value if value is not None else "")


def _pad(text: str, column: dict) -> str:
    width = column.get("width")
    if not width:
        return text
    pad = (column.get("pad") or " ")[:1] or " "
    text = text[:width]
    return text.rjust(width, pad) if column.get("align") == "right" else text.ljust(width, pad)


def render(fmt: dict, payments: list, context: dict) -> str:
    """The bank file, as text. Pure — no DB, no clock — so it is testable standalone and a
    preview and a real download go through exactly the same code."""
    columns = fmt.get("columns") or DEFAULT_FORMAT["columns"]
    fixed = bool(fmt.get("fixed_width"))
    delimiter = "" if fixed else (fmt.get("delimiter") or ",")
    quote_all = bool(fmt.get("quote_all")) and not fixed

    def line(cells: list) -> str:
        if fixed:
            return "".join(_pad(c, columns[i]) for i, c in enumerate(cells))
        if quote_all:
            return delimiter.join('"' + c.replace('"', '""') + '"' for c in cells)
        return delimiter.join(
            ('"' + c.replace('"', '""') + '"') if (delimiter and delimiter in c) or '"' in c
            else c for c in cells)

    out = list(fmt.get("header_lines") or [])
    if fmt.get("include_header", True):
        out.append(line([c.get("label") or c["source"] for c in columns]))
    total = 0.0
    for i, payment in enumerate(payments, start=1):
        total += float(payment.get("amount") or 0)
        out.append(line([_cell(c, payment, {**context, "serial": i}, fmt) for c in columns]))

    if fmt.get("include_totals_row"):
        # The original layout's trailing blank line and totals row, reproduced exactly.
        out.append("")
        cells = [""] * len(columns)
        for i, c in enumerate(columns):
            if c["source"] == "batch_no":
                cells[i] = "Total"
            elif c["source"] == "amount":
                cells[i] = _format_amount(total, fmt.get("amount_format") or "2dp")
            elif c["source"] == "narration":
                cells[i] = f"{len(payments)} payment(s)"
        out.append(line(cells))

    out.extend(fmt.get("trailer_lines") or [])
    return "\r\n".join(out) + "\r\n" if fmt.get("crlf") else "\n".join(out) + "\n"


SAMPLE_PAYMENTS = [
    {"employee_code": "EMP001", "employee_name": "A Sample", "account_holder": "A Sample",
     "bank_account": "001234567890", "bank_ifsc": "HDFC0000123", "bank_name": "HDFC Bank",
     "bank_branch": "Pune", "bank_account_type": "Savings", "amount": 48750.5,
     "payment_mode": "NEFT", "period": "2026-03", "batch_no": "PAYB-2026-001"},
    {"employee_code": "EMP002", "employee_name": "B Sample", "account_holder": "B Sample",
     "bank_account": "009876543210", "bank_ifsc": "ICIC0000456", "bank_name": "ICICI Bank",
     "bank_branch": "Mumbai", "bank_account_type": "Salary", "amount": 61200.0,
     "payment_mode": "NEFT", "period": "2026-03", "batch_no": "PAYB-2026-001"},
]


def preview(fmt: dict) -> dict:
    """Two invented rows through the real renderer — §19's "mandatory fields" question is
    far easier to answer against output than against a column list."""
    text = render(fmt, SAMPLE_PAYMENTS,
                  {"batch_no": "PAYB-2026-001", "generated_date": "2026-03-31"})
    return {"preview": text, "columns": len(fmt.get("columns") or []),
            "fixed_width": bool(fmt.get("fixed_width"))}
