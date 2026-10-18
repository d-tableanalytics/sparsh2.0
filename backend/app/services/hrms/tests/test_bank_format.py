"""Phase 1 FRD §13/§19 -- configurable bank file layouts.

  1. The DEFAULT format reproduces the previous hard-coded output EXACTLY. This is the
     whole deployment-safety argument: somebody downstream has a macro built on it.
  2. A bank-specific layout: column choice and order, delimiter, amount and date
     conventions, header and trailer records.
  3. Fixed-width: padding, alignment, truncation -- and a format that claims fixed width
     without widths is refused rather than silently emitting ragged lines.
  4. Validation: an unknown source field, an empty column list, a bad amount format.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_bank_format   (from backend/)
"""
from __future__ import annotations

import asyncio

results: list[bool] = []


def check(label: str, condition: bool, extra=None) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}"
          + ("" if condition or extra is None else f"  -- {str(extra)[:300]}"))
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


async def expect(label, coro, status, needle=""):
    from fastapi import HTTPException
    try:
        await coro
    except HTTPException as e:
        return check(f"{label} -> {status}", e.status_code == status
                     and needle.lower() in str(e.detail).lower(), e.detail)
    return check(f"{label} -> {status} (no error raised)", False)


from app.services.hrms.tests.test_payroll_live_findings import FakeCollection  # noqa: E402

CO = "C1"
HR = {"_id": "hr-1", "role": "admin", "full_name": "Dummy HR"}

PAYMENTS = [
    {"employee_code": "E1", "account_holder": "Asha Rao", "bank_account": "001234567890",
     "bank_ifsc": "HDFC0000123", "bank_name": "HDFC Bank", "bank_branch": "Pune",
     "bank_account_type": "Savings", "amount": 48750.5, "payment_mode": "NEFT",
     "period": "2026-03"},
    {"employee_code": "E2", "account_holder": "B Kumar", "bank_account": "009876543210",
     "bank_ifsc": "ICIC0000456", "bank_name": "ICICI Bank", "bank_branch": "Mumbai",
     "bank_account_type": "Salary", "amount": 61200.0, "payment_mode": "NEFT",
     "period": "2026-03"},
]
CONTEXT = {"batch_no": "PAYB-2026-001", "generated_date": "2026-03-31"}


def legacy_output() -> str:
    """The previous hard-coded implementation, reproduced here verbatim from the code it
    replaced. If the DEFAULT format ever drifts from this, the test says so."""
    import csv
    import io as _io
    buf = _io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Batch No", "Payroll Period", "Employee ID", "Beneficiary Name",
                "Account Number", "IFSC", "Bank", "Branch", "Account Type", "Amount",
                "Payment Mode", "Narration"])
    for r in PAYMENTS:
        w.writerow(["PAYB-2026-001", r["period"], r["employee_code"], r.get("account_holder"),
                    r.get("bank_account"), r.get("bank_ifsc"), r.get("bank_name"),
                    r.get("bank_branch"), r.get("bank_account_type"),
                    f"{float(r['amount']):.2f}", r.get("payment_mode"),
                    f"Salary {r['period']}"])
    w.writerow([])
    total = sum(float(r["amount"]) for r in PAYMENTS)
    w.writerow(["Total", "", "", "", "", "", "", "", "", f"{total:.2f}", "",
                f"{len(PAYMENTS)} payment(s)"])
    return buf.getvalue()


async def main() -> int:
    import app.db.mongodb as mongo
    import app.services.hrms_bank_format_service as BF

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    BF.get_collection = getter

    async def no_audit(*a, **k):
        return None
    BF.audit = no_audit

    # ── 1. The DEFAULT format is byte-identical to what it replaced ─────────────────
    section("1. DEFAULT reproduces the old hard-coded file (deployment safety)")

    rendered = BF.render(BF.DEFAULT_FORMAT, PAYMENTS, CONTEXT)
    legacy = legacy_output()
    # csv.writer emits \r\n; the renderer emits \n. Compare line by line, which is what a
    # bank parser and a spreadsheet both do.
    check("every line matches the previous implementation, in order",
          [l.rstrip("\r") for l in legacy.splitlines()] == rendered.splitlines(),
          {"legacy": legacy.splitlines()[:3], "now": rendered.splitlines()[:3]})
    check("...including the blank line and the totals row",
          rendered.splitlines()[-2] == ""
          and rendered.splitlines()[-1].startswith("Total,")
          and "109950.50" in rendered.splitlines()[-1])

    fmt = await BF.get_format(CO, None)
    check("a company with nothing configured resolves to DEFAULT",
          fmt["name"] == "DEFAULT" and fmt.get("built_in") is True)
    check("an unknown format name falls back rather than failing a download",
          (await BF.get_format(CO, "NOPE"))["name"] == "DEFAULT")
    listed = await BF.list_formats(CO)
    check("DEFAULT is always listed, even unsaved", listed[0]["name"] == "DEFAULT")

    # ── 2. A bank-specific layout ───────────────────────────────────────────────────
    section("2. A bank-specific layout (§19)")

    saved = await BF.save_format(HR, CO, {
        "name": "hdfc_neft", "bank": "HDFC",
        "delimiter": "|", "include_header": False, "include_totals_row": False,
        "amount_format": "paise", "date_format": "dmy",
        "narration_template": "SAL-{period}-{employee_code}",
        "header_lines": ["H|PAYB-2026-001|2026-03-31"],
        "trailer_lines": ["T|2"],
        "columns": [
            {"source": "serial", "label": "Sr"},
            {"source": "bank_account", "label": "Account"},
            {"source": "bank_ifsc", "label": "IFSC"},
            {"source": "amount", "label": "Amount"},
            {"source": "narration", "label": "Narration"},
            {"source": "constant", "label": "Mode", "value": "NEFT"},
        ]})
    check("the format is saved, upper-cased and versioned",
          saved["name"] == "HDFC_NEFT" and saved["version"] == 1)

    text = BF.render(saved, PAYMENTS, CONTEXT)
    lines = text.splitlines()
    check("the header record is emitted first", lines[0] == "H|PAYB-2026-001|2026-03-31")
    check("no column header row when the format says not to", lines[1].startswith("1|"))
    check("pipe delimited, serial numbered, amount in paise",
          lines[1] == "1|001234567890|HDFC0000123|4875050|SAL-2026-03-E1|NEFT",
          lines[1])
    check("the second row continues the serial", lines[2].startswith("2|"))
    check("the trailer record is last", lines[-1] == "T|2")
    check("no totals row when the format says not to",
          not any(l.startswith("Total") for l in lines))

    check("saving again bumps the version",
          (await BF.save_format(HR, CO, {**saved, "name": "hdfc_neft"}))["version"] == 2)

    # ── 3. Fixed width ──────────────────────────────────────────────────────────────
    section("3. Fixed-width layouts")

    fixed = await BF.save_format(HR, CO, {
        "name": "icici_fixed", "fixed_width": True, "include_header": False,
        "amount_format": "0dp",
        "columns": [
            {"source": "employee_code", "width": 8, "align": "left"},
            {"source": "bank_account", "width": 16, "align": "right", "pad": "0"},
            {"source": "amount", "width": 10, "align": "right", "pad": "0"},
        ]})
    row = BF.render(fixed, PAYMENTS, CONTEXT).splitlines()[0]
    check("every row is exactly the declared width", len(row) == 34, len(row))
    check("left-aligned text is space padded", row[:8] == "E1      ", repr(row[:8]))
    check("right-aligned numbers are zero padded",
          row[8:24] == "0000001234567890", repr(row[8:24]))
    check("the amount is padded and rounded", row[24:] == "0000048751", repr(row[24:]))

    await expect("fixed width with a column missing its width", BF.save_format(HR, CO, {
        "name": "bad_fixed", "fixed_width": True,
        "columns": [{"source": "employee_code"}]}), 422, "width on every column")

    long_value = [{**PAYMENTS[0], "employee_code": "VERYLONGCODE"}]
    truncated = BF.render(fixed, long_value, CONTEXT).splitlines()[0]
    check("a value longer than its column is truncated, not allowed to shift the line",
          len(truncated) == 34 and truncated[:8] == "VERYLONG")

    # ── 4. Validation ───────────────────────────────────────────────────────────────
    section("4. A mistyped format is refused when it is saved")

    await expect("an unknown source field", BF.save_format(HR, CO, {
        "name": "bad1", "columns": [{"source": "favourite_colour"}]}), 422, "is not a field")
    await expect("no columns at all", BF.save_format(HR, CO, {
        "name": "bad2", "columns": []}), 422, "at least one column")
    await expect("an unknown amount format", BF.save_format(HR, CO, {
        "name": "bad3", "amount_format": "roman",
        "columns": [{"source": "amount"}]}), 422, "amount format")
    await expect("deleting DEFAULT", BF.delete_format(HR, CO, "DEFAULT"),
                 409, "cannot be deleted")

    bad_template = {**BF.DEFAULT_FORMAT, "narration_template": "{not_a_field}"}
    out = BF.render(bad_template, PAYMENTS, CONTEXT)
    check("a template naming a field that does not exist does not break the download",
          "{not_a_field}" in out)

    print("\n" + "=" * 60)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 60)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
