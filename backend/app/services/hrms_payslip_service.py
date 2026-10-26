"""HRMS > the employee payslip (§7.13/§22.7, screens SM-HR-031/SM-HR-064).

hrms_payroll_service.py already builds a genuinely component-driven payroll RECORD —
prorated structure earnings, PF/ESI/PT/TDS, arrears, reimbursements, variable pay, advance
and notice recovery. What did not exist anywhere was an ITEMISED view of that record an
employee could actually read, and a way for an employee to reach their own record at all
(list_records required PAYROLL_READ with no self-scope branch). This module is that view.

-- Presentation, not a new source of numbers --------------------------------------------
Every figure here is read from hrms_payroll_records (already computed by the payroll run)
plus the employee's own salary structure (for line-item LABELS — "Basic", "HRA" — rather
than a single "structured_gross" total). Nothing is recalculated.

-- Rendering, not a stored artifact -------------------------------------------------------
Unlike Letters/Appointment/Offer, a payslip is not reissued or amended — it is a read of a
payroll run that itself becomes immutable when the run is Locked. So there is no PDF
generation or S3 storage here: the frontend renders this JSON as a document and the browser
prints it, the exact pattern Offer/Appointment letters already use for the same reason
(what must stay byte-identical between two renderings is cheaper to keep as one JSON shape
read by one component than as a server-rendered file).

-- Template configuration is deliberately thin ---------------------------------------------
§7.13's own BR: "Detailed statutory and salary-component configuration requires a payroll
workshop." Full payslip theming is out of scope until that workshop happens; what a company
can configure today is the header/footer note that appears on every payslip it issues.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    COLL_DEPARTMENTS, COLL_DESIGNATIONS,
    COLL_EMPLOYEE_PROFILES, COLL_PAYROLL_RECORDS, COLL_PAYROLL_RUNS, COLL_PAYROLL_TEMPLATES,
    COLL_PAYSLIP_TEMPLATE_VERSIONS, COLL_SALARY_COMPONENTS, COLL_SALARY_STRUCTURES,
    DEDUCTING_TYPES, PAYROLL_FINAL_STATUSES, ComponentType, HrmsRole, PayslipSection,
)
from app.utils.hrms_access import hrms_role


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _oid(value) -> Optional[ObjectId]:
    """A display-only lookup id — malformed input means "no name to show", never a 400."""
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        return None


async def _own_employee_code(actor: dict, company_id: str) -> Optional[str]:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "user_id": str(actor.get("_id") or "")})
    return (profile or {}).get("employee_code")


async def _resolve_employee_code(actor: dict, company_id: str,
                                  requested: Optional[str]) -> str:
    """An EMPLOYEE caller always gets their OWN code, regardless of what was requested —
    the same untrusted-input treatment hrms_appointment_service._scope_filter applies to a
    caller-supplied `uk`. Every other role may name one; naming none means their own — the
    "My Payslip" tab asks exactly that, for HR as much as for anybody else."""
    from app.utils.hrms_access import sees_all_payroll
    if not sees_all_payroll(actor):
        # Everyone outside HR/MD/Finance reads their OWN payslip only — whatever code they
        # asked for. (Once every staff member holds PAYROLL_READ for self-service, an
        # EMPLOYEE-only check would let a manager or support user read anybody's.)
        own = await _own_employee_code(actor, company_id)
        if not own:
            raise HTTPException(status_code=404, detail="You have no linked employee profile.")
        return own
    if requested:
        return requested
    own = await _own_employee_code(actor, company_id)
    if not own:
        raise HTTPException(
            status_code=404,
            detail="Your account has no employee profile in this company, so there is no "
                   "payslip of your own. To see an employee's payslip, open it from a run "
                   "on the Payroll Runs tab.")
    return own


def _line(label: str, amount) -> Optional[dict]:
    amount = float(amount or 0)
    return {"label": label, "amount": round(amount, 2)} if amount else None


async def _department_names(company_id: str, ids: set) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await get_collection(COLL_DEPARTMENTS).find(
        {"company_id": str(company_id), "_id": {"$in": [_oid(i) for i in ids if _oid(i)]}},
        {"name": 1}).to_list(len(ids))
    return {str(r["_id"]): r.get("name") for r in rows}


async def _designation_names(company_id: str, ids: set) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await get_collection(COLL_DESIGNATIONS).find(
        {"company_id": str(company_id), "_id": {"$in": [_oid(i) for i in ids if _oid(i)]}},
        {"name": 1}).to_list(len(ids))
    return {str(r["_id"]): r.get("name") for r in rows}


async def _latest_structure(company_id: str, employee_code: str, period: str) -> Optional[dict]:
    return await get_collection(COLL_SALARY_STRUCTURES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code,
         "effective_from": {"$lte": f"{period}-28"}},
        sort=[("effective_from", -1)],
    )


def _compose_payslip(record: dict, *, period: str, run_status: Optional[str],
                     employee_name: Optional[str], department_name: Optional[str],
                     designation_name: Optional[str], structure: Optional[dict],
                     component_meta: dict, template: dict) -> dict:
    """Every figure here is read straight off `record` (already computed by the payroll
    run) plus `structure` (for line-item LABELS — "Basic", "HRA" — rather than a single
    `structured_gross` total). Nothing is recalculated. Shared by `get_payslip` (one
    employee) and `list_payslips` (a whole run), so the two can never render differently for
    the same record."""
    if record.get("lines") is not None:
        return _compose_from_lines(record, period=period, run_status=run_status,
                                   employee_name=employee_name,
                                   department_name=department_name,
                                   designation_name=designation_name, template=template)
    earnings, structured_deductions = [], []
    for c in (structure or {}).get("components", []):
        meta = component_meta.get(c.get("code")) or {}
        row = _line(meta.get("name") or c.get("code"), c.get("amount"))
        if not row:
            continue
        if meta.get("component_type") == ComponentType.EARNING.value:
            earnings.append(row)
        elif (meta.get("component_type") == ComponentType.DEDUCTION.value
              and record.get("structured_deductions")):
            # Only when the record actually deducted them — a record calculated before
            # structure deductions were counted must not show a line its total never took.
            structured_deductions.append(row)

    # Show each earning at what was actually PAID for the month, with the full-month figure
    # alongside. Listing full-month amounts over a prorated Gross made the lines add up to
    # 50,000 above a "Gross Earnings ₹25,806.45" — correct, and indistinguishable from an
    # error to anybody reading it. Split in proportion, with the rounding remainder on the
    # last line so the lines sum to the record's own prorated_gross exactly.
    full_total = sum(r["amount"] for r in earnings)
    paid_total = float(record.get("prorated_gross") or 0)
    if earnings and full_total and round(paid_total, 2) != round(full_total, 2):
        ratio = paid_total / full_total
        for r in earnings:
            r["full_amount"] = r["amount"]
            r["amount"] = round(r["full_amount"] * ratio, 2)
        earnings[-1]["amount"] = round(
            earnings[-1]["amount"] + paid_total - sum(r["amount"] for r in earnings), 2)

    proration_note = None
    if record["payable_days"] != record["days_in_period"]:
        proration_note = (f'Prorated for {record["payable_days"]} of '
                          f'{record["days_in_period"]} payable days '
                          f'({record["lop_days"]} LOP).')

    # §22.7 — arbitrary named ad-hoc lines, alongside the fixed named fields below. Each was
    # resolved against the component master at the moment it was set (hrms_payroll_service.
    # set_adjustments), so the type is read straight off the stored line, no second lookup.
    adjustment_earnings = [row for row in (
        _line(a.get("name") or a.get("code"), a.get("amount"))
        for a in (record.get("adjustments") or [])
        if a.get("component_type") == ComponentType.EARNING.value
    ) if row]
    adjustment_deductions = [row for row in (
        _line(a.get("name") or a.get("code"), a.get("amount"))
        for a in (record.get("adjustments") or [])
        if a.get("component_type") == ComponentType.DEDUCTION.value
    ) if row]

    other_earnings = [row for row in [
        _line("Variable Pay", record.get("variable_pay_payout")),
        _line("Arrears", record.get("arrears")),
        _line("Reimbursements", record.get("reimbursements")),
        _line("Other Earnings", record.get("other_earnings")),
    ] if row] + adjustment_earnings

    deductions = structured_deductions + [row for row in [
        _line("PF", record.get("pf")),
        _line("ESI", record.get("esi")),
        _line("Professional Tax", record.get("pt")),
        _line("TDS", record.get("tds")),
        _line("Salary Advance Recovery", record.get("advance_recovery")),
        _line("Notice Period Recovery", record.get("notice_recovery")),
        _line("Other Deductions", record.get("other_deductions")),
    ] if row] + adjustment_deductions

    return {
        "period": period,
        "run_status": run_status,
        "employee_code": record["employee_code"],
        "employee_name": record.get("employee_name") or employee_name,
        "designation": designation_name,
        "department": department_name,
        "days_in_period": record["days_in_period"], "payable_days": record["payable_days"],
        "lop_days": record["lop_days"], "proration_note": proration_note,
        "earnings": earnings,
        "other_earnings": other_earnings,
        "deductions": deductions,
        "gross_earnings": record["gross_earnings"],
        "total_deductions": record["total_deductions"],
        "net_pay": record["net_pay"],
        "template": template,
    }


def _compose_from_lines(record: dict, *, period: str, run_status: Optional[str],
                        employee_name: Optional[str], department_name: Optional[str],
                        designation_name: Optional[str], template: dict) -> dict:
    """FRD §14 / §18: the payslip shows the component values ACTUALLY USED in the final
    payroll -- the lines stored on the record at calculation, each mapped to its configured
    payslip section -- not a fresh read of today's structure or component master."""
    hide_zero = template.get("hide_zero_lines", True) is not False

    def row(label, amount, full=None):
        amount = round(float(amount or 0), 2)
        if hide_zero and not amount:
            return None
        out = {"label": label, "amount": amount}
        if full is not None and round(float(full), 2) != amount:
            out["full_amount"] = round(float(full), 2)
        return out

    # FRD §14 Deductions "LOP": with the template's lop_as_deduction on, earnings show at
    # their full amount and the days lost appear as ONE deduction line instead of inside
    # each earning. Net pay is the same either way -- only where the LOP is shown moves.
    lop_line = bool(template.get("lop_as_deduction")) and float(record.get("lop_days") or 0) > 0
    lop_amount = 0.0
    earnings, other_earnings, deductions, employer = [], [], [], []
    for line in record.get("lines") or []:
        section = line.get("section") or PayslipSection.REGULAR_EARNINGS.value
        amount = line.get("amount")
        earning = section not in (PayslipSection.EMPLOYER.value, PayslipSection.DEDUCTIONS.value,
                                  PayslipSection.HIDDEN.value) \
            and line.get("component_type") not in DEDUCTING_TYPES
        if lop_line and earning and line.get("full_amount") is not None:
            lop_amount += float(line["full_amount"]) - float(amount or 0)
            amount = line["full_amount"]
        r = row(line.get("name") or line.get("code"), amount,
                None if lop_line and earning else line.get("full_amount"))
        if not r or section == PayslipSection.HIDDEN.value:
            continue
        if section == PayslipSection.EMPLOYER.value:
            employer.append(r)
        elif section == PayslipSection.DEDUCTIONS.value or \
                line.get("component_type") in DEDUCTING_TYPES:
            deductions.append(r)
        elif section == PayslipSection.OTHER_EARNINGS.value:
            other_earnings.append(r)
        else:
            earnings.append(r)

    for label, key in (("Variable Pay / Incentive", "variable_pay_payout"),
                       ("Arrears", "arrears"), ("Reimbursements", "reimbursements"),
                       ("Bonus", "bonus"), ("Other Earnings", "other_earnings")):
        r = row(label, record.get(key))
        if r:
            other_earnings.append(r)
    for label, key in (("PF", "pf"), ("ESI", "esi"), ("Professional Tax", "pt"),
                       ("TDS", "tds"), ("Salary Advance Recovery", "advance_recovery"),
                       ("Notice Period Recovery", "notice_recovery"),
                       ("Other Deductions", "other_deductions")):
        r = row(label, record.get(key))
        if r:
            deductions.append(r)
    for a in record.get("adjustments") or []:
        r = row(a.get("name") or a.get("code"), a.get("amount"))
        if not r:
            continue
        if a.get("reason"):
            r["note"] = a["reason"]
        ctype = a.get("component_type")
        if ctype == ComponentType.EMPLOYER_CONTRIBUTION.value:
            employer.append(r)
        elif ctype in DEDUCTING_TYPES:
            deductions.append(r)
        elif ctype != ComponentType.INFORMATIONAL.value:
            other_earnings.append(r)

    lop_amount = round(lop_amount, 2)
    if lop_line and lop_amount > 0:
        deductions.insert(0, {"label": f'Loss of Pay ({record["lop_days"]} day(s))',
                              "amount": lop_amount})
    proration_note = None
    if record.get("lop_days") and not (lop_line and lop_amount > 0):
        proration_note = (f'Prorated for {record["payable_days"]} of '
                          f'{record["days_in_period"]} payable days '
                          f'({record["lop_days"]} LOP).')
    return {
        "period": period,
        "run_status": run_status,
        "employee_code": record["employee_code"],
        "employee_name": record.get("employee_name") or employee_name,
        "designation": designation_name,
        "department": department_name,
        "date_of_joining": record.get("date_of_joining"),
        "days_in_period": record["days_in_period"], "payable_days": record["payable_days"],
        "lop_days": record["lop_days"], "present_days": record.get("present_days"),
        "proration_note": proration_note,
        "earnings": earnings,
        "other_earnings": other_earnings,
        "deductions": deductions,
        "employer_contributions": employer if template.get("show_employer_contributions") else [],
        "gross_earnings": round(float(record["gross_earnings"]) + lop_amount, 2)
        if lop_line else record["gross_earnings"],
        "total_deductions": round(float(record["total_deductions"]) + lop_amount, 2)
        if lop_line else record["total_deductions"],
        "lop_amount": lop_amount if lop_line else None,
        "total_employer_contributions": record.get("total_employer_contributions"),
        "net_pay": record["net_pay"],
        "net_pay_words": _in_words(record["net_pay"]) if template.get(
            "show_net_in_words", True) is not False else None,
        "template": template,
    }


_ONES = ("Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen "
         "Fourteen Fifteen Sixteen Seventeen Eighteen Nineteen").split()
_TENS = "Zero Ten Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()


def _words_below_1000(n: int) -> str:
    parts = []
    if n >= 100:
        parts.append(f"{_ONES[n // 100]} Hundred")
        n %= 100
    if n >= 20:
        parts.append(_TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else ""))
    elif n:
        parts.append(_ONES[n])
    return " ".join(parts)


def _in_words(amount) -> Optional[str]:
    """Indian numbering: crore / lakh / thousand."""
    try:
        amount = round(float(amount or 0), 2)
    except (TypeError, ValueError):
        return None
    if amount < 0:
        return None
    rupees, paise = int(amount), int(round((amount - int(amount)) * 100))
    if rupees == 0 and paise == 0:
        return "Rupees Zero Only"
    parts = []
    for size, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1000, "Thousand")):
        if rupees >= size:
            parts.append(f"{_words_below_1000(rupees // size)} {name}")
            rupees %= size
    if rupees:
        parts.append(_words_below_1000(rupees))
    text = "Rupees " + " ".join(parts) if parts else "Rupees Zero"
    if paise:
        text += f" and {_words_below_1000(paise)} Paise"
    return text + " Only"


async def _released(actor: dict, company_id: str, period: str, employee_code: str,
                    run: Optional[dict]) -> bool:
    """FRD §14 Release: an employee sees their payslip only after final approval and lock
    (or, if the company chose so, only once their payment is confirmed). Payroll roles see
    the provisional one while they work on it."""
    from app.utils.hrms_access import sees_all_payroll
    if sees_all_payroll(actor):
        return True
    status = (run or {}).get("status")
    if status not in PAYROLL_FINAL_STATUSES:
        return False
    from app.services.hrms_payroll_service import get_payroll_policy
    policy = await get_payroll_policy(company_id)
    if policy.get("payslip_release") == "after_payment" and status != "Closed":
        from app.services.hrms_disbursal_service import my_payment
        payment = await my_payment(company_id, period, employee_code)
        return bool(payment and payment.get("status") == "Processed")
    return True


async def _identifiers(company_id: str, employee_code: str, template: dict) -> dict:
    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code}) or {}
    from app.services.hrms_employee_master_service import mask
    out = {}
    if template.get("show_identifiers", True) is not False:
        out.update({"pan": mask(profile.get("pan")), "uan": profile.get("uan"),
                    "pf_number": profile.get("pf_number"), "esi_number": profile.get("esi_number"),
                    "work_location": profile.get("work_location"),
                    "grade": profile.get("grade")})
    if template.get("show_bank", True) is not False:
        out.update({"bank_name": profile.get("bank_name"),
                    "bank_account": mask(profile.get("bank_account"))})
    return out


async def get_payslip(actor: dict, company_id: str, period: str,
                       employee_code: Optional[str] = None) -> dict:
    employee_code = await _resolve_employee_code(actor, company_id, employee_code)

    record = await get_collection(COLL_PAYROLL_RECORDS).find_one(
        {"company_id": str(company_id), "period": period, "employee_code": employee_code})
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"No payroll record for {employee_code} in {period}.")

    run = await get_collection(COLL_PAYROLL_RUNS).find_one(
        {"company_id": str(company_id), "period": period},
        {"status": 1, "payslip_template": 1})
    if not await _released(actor, company_id, period, employee_code, run):
        raise HTTPException(
            status_code=404,
            detail=f"Your {period} payslip is not released yet. It is published once payroll "
                   f"is approved and locked.")

    profile = await get_collection(COLL_EMPLOYEE_PROFILES).find_one(
        {"company_id": str(company_id), "employee_code": employee_code},
        {"designation_id": 1, "department_id": 1, "employee_code": 1,
         "display_name": 1, "full_name": 1})
    # A profile stores department_id/designation_id, not resolved names (see
    # hrms_employee_service._compose) — the same two-lookup join late_coming_summary uses.
    departments = await _department_names(company_id, {(profile or {}).get("department_id")})
    designations = await _designation_names(company_id, {(profile or {}).get("designation_id")})

    structure = await _latest_structure(company_id, employee_code, period)
    component_meta = {c["code"]: c for c in await get_collection(COLL_SALARY_COMPONENTS).find(
        {"company_id": str(company_id)}).to_list(200)}
    # A locked payroll keeps the template version it was released with (FRD §14).
    template = (run or {}).get("payslip_template") or await get_payslip_template(company_id)

    slip = _compose_payslip(
        record, period=period, run_status=(run or {}).get("status"),
        employee_name=(profile or {}).get("display_name") or (profile or {}).get("full_name"),
        department_name=departments.get((profile or {}).get("department_id")),
        designation_name=designations.get((profile or {}).get("designation_id")),
        structure=structure, component_meta=component_meta, template=template)
    slip["identifiers"] = await _identifiers(company_id, employee_code, template)
    from app.services.hrms_disbursal_service import my_payment
    slip["payment"] = await my_payment(company_id, period, employee_code)
    return slip


async def list_payslips(actor: dict, company_id: str, period: str) -> list:
    """§22.7 "bulk payslip" — every payslip in one run, HR-only (an EMPLOYEE holding
    PAYROLL_READ is scoped to their own single record everywhere else in this module; a
    listing across the whole run must not become the one place that scope is forgotten)."""
    from app.utils.hrms_access import sees_all_payroll
    if not sees_all_payroll(actor):
        raise HTTPException(status_code=403, detail="You may only view your own payslip.")

    records = await get_collection(COLL_PAYROLL_RECORDS).find(
        {"company_id": str(company_id), "period": period}).sort("employee_code", 1).to_list(5000)
    if not records:
        return []

    run = await get_collection(COLL_PAYROLL_RUNS).find_one(
        {"company_id": str(company_id), "period": period},
        {"status": 1, "payslip_template": 1})
    run_status = (run or {}).get("status")

    codes = [r["employee_code"] for r in records]
    profiles = {p["employee_code"]: p for p in await get_collection(COLL_EMPLOYEE_PROFILES).find(
        {"company_id": str(company_id), "employee_code": {"$in": codes}},
        {"employee_code": 1, "department_id": 1, "designation_id": 1,
         "display_name": 1, "full_name": 1}).to_list(len(codes))}
    departments = await _department_names(
        company_id, {p.get("department_id") for p in profiles.values()})
    designations = await _designation_names(
        company_id, {p.get("designation_id") for p in profiles.values()})
    component_meta = {c["code"]: c for c in await get_collection(COLL_SALARY_COMPONENTS).find(
        {"company_id": str(company_id)}).to_list(200)}
    template = (run or {}).get("payslip_template") or await get_payslip_template(company_id)

    out = []
    for record in records:
        profile = profiles.get(record["employee_code"]) or {}
        structure = await _latest_structure(company_id, record["employee_code"], period)
        out.append(_compose_payslip(
            record, period=period, run_status=run_status,
            employee_name=profile.get("display_name") or profile.get("full_name"),
            department_name=departments.get(profile.get("department_id")),
            designation_name=designations.get(profile.get("designation_id")),
            structure=structure, component_meta=component_meta, template=template))
        out[-1]["identifiers"] = await _identifiers(company_id, record["employee_code"], template)
    return out


# ─────────────────────────────────────────────────────────────
# SM-HR-064 — Payslip Template Configuration
# ─────────────────────────────────────────────────────────────
TEMPLATE_DEFAULTS = {
    "company_name": None, "header_note": None, "footer_note": None, "company_address": None,
    "show_lop_days": True, "show_identifiers": True, "show_bank": True,
    "show_employer_contributions": False, "hide_zero_lines": True, "show_net_in_words": True,
    "lop_as_deduction": False,
    "version": 0,
}


async def get_payslip_template(company_id: str) -> dict:
    doc = await get_collection(COLL_PAYROLL_TEMPLATES).find_one({"company_id": str(company_id)})
    out = {**TEMPLATE_DEFAULTS, "company_id": str(company_id)}
    if doc:
        out.update({k: v for k, v in _out(doc).items() if v is not None or k in TEMPLATE_DEFAULTS})
    return out


async def list_template_versions(company_id: str) -> list:
    rows = await get_collection(COLL_PAYSLIP_TEMPLATE_VERSIONS).find(
        {"company_id": str(company_id)}).sort("version", -1).to_list(100)
    return [_out(r) for r in rows]


async def save_payslip_template(actor: dict, company_id: str, payload: dict) -> dict:
    """FRD §14 Template: the Sparsh-approved layout options. Every save is a new VERSION
    (kept in hrms_payslip_template_versions); a locked payroll stores the version it was
    released with, so editing the template never changes an issued payslip."""
    now = datetime.now(timezone.utc)
    current = await get_payslip_template(company_id)
    clean = {
        "company_name": (payload.get("company_name") or "").strip() or None,
        "header_note": (payload.get("header_note") or "").strip() or None,
        "footer_note": (payload.get("footer_note") or "").strip() or None,
        "company_address": (payload.get("company_address") or "").strip() or None,
    }
    for flag in ("show_lop_days", "show_identifiers", "show_bank",
                 "show_employer_contributions", "hide_zero_lines", "show_net_in_words",
                 "lop_as_deduction"):
        value = payload.get(flag)
        clean[flag] = bool(value) if value is not None else current.get(flag)
    clean.update({"version": int(current.get("version") or 0) + 1,
                  "updated_by": str(actor.get("_id") or ""), "updated_at": now})
    await get_collection(COLL_PAYROLL_TEMPLATES).update_one(
        {"company_id": str(company_id)},
        {"$set": clean, "$setOnInsert": {"company_id": str(company_id), "created_at": now}},
        upsert=True,
    )
    await get_collection(COLL_PAYSLIP_TEMPLATE_VERSIONS).insert_one(
        {"company_id": str(company_id), **clean, "created_at": now})
    return await get_payslip_template(company_id)
