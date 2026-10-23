"""Seed ONE employee carrying data for every module this branch's post-review gaps touched.

The eight gaps are each pinned by a test suite, but a suite proves a rule and shows nobody
a screen. This builds a single person whose records make each gap visible in the UI:

  Gap 1  a Half Day worth 0.75 of a day, because a grade-scoped ATT_DAY policy says so --
         and the same 0.75 reaching payable days rather than a hard-coded half.
  Gap 2  a regularisation raised under `approval_levels: 1`, so the manager's approval is
         the decision, plus an OD request carrying its own frozen level.
  Gap 3  a PAY_POLICY change DRAFTED and sent for approval rather than written live, so
         the Configuration Approvals inbox has something real in it.
  Gap 4  that PAY_POLICY version SCOPED to one grade, which is what makes it reach this
         employee and nobody else.
  Gap 5  every policy version above activated through the §27 change flow, never through
         the direct status endpoint -- which is now the only way.
  Gap 6  enough attendance, payment and configuration history for all five exports to
         return something worth reading.
  Gap 8  two days where leave and attendance contradict each other: a punch on an approved
         leave day, and an Absent day with nothing behind it.

-- Scoped so it cannot touch anybody else -----------------------------------------------
Policy versions are COMPANY-wide objects, so each one created here is assigned a scope of
`grades: ["M2"]` and this employee is the only person in the company holding that grade
(every existing profile has `grade: None`). That is what keeps a demo of configurable
payroll rules from quietly re-pricing seven real colleagues.

-- What it does NOT do ------------------------------------------------------------------
  * No login account. `create_profile` requires an existing tenant user, and minting a
    credential on a live system to demonstrate a dropdown is the wrong trade; the profile
    is created unlinked, exactly as EMP-2026-008 already is, and shows in the directory as
    pending a user link. This is the one record written directly rather than through a
    service, because the service's precondition is the account this deliberately avoids.
  * No payroll run unless --with-payroll is passed. `calculate_payroll` processes EVERY
    eligible profile, so a run for this one person would also write payroll records for
    the seven real employees and lock the company's attendance month. That blast radius is
    the caller's decision, not this script's.

-- No personal data ---------------------------------------------------------------------
Email is `example.com` (RFC 2606, permanently unroutable), the mobile begins `+91 00000`
(no Indian number starts with 0), and the PAN / Aadhaar / UAN are structurally valid but
impossible -- an Aadhaar never begins with 0 or 1.

Usage (from backend/):
    python scripts/seed_demo_employee.py --company <id> --dry-run
    python scripts/seed_demo_employee.py --company <id>
    python scripts/seed_demo_employee.py --company <id> --with-payroll
    python scripts/seed_demo_employee.py --company <id> --undo
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

import app.db.mongodb as mongo                                        # noqa: E402
from scripts.seed_hrms_recruitment_demo import connect, log           # noqa: E402

MARKER = "demo-employee"
CODE = "EMP-2026-9999"
NAME = "Manoj Patel"
GRADE = "M2"                      # nobody else in the company holds a grade at all
PERIOD = "2026-10"                # the open month; 2026-09 is already locked

# Every collection this script writes to, for --undo. A marker field is stamped on each
# document so undo removes this script's rows and nothing that happens to look like them.
SEEDED = [
    "hrms_employee_profiles", "hrms_salary_structures", "hrms_attendance",
    "hrms_leaves", "hrms_attendance_corrections", "hrms_od_requests",
    "hrms_policy_definitions", "hrms_policy_versions", "hrms_policy_assignments",
    "hrms_config_change_requests", "hrms_config_approvals",
    "hrms_payroll_runs", "hrms_payroll_records", "hrms_payment_batches", "hrms_payments",
]

HR = {"_id": "seed-hr", "role": "superadmin", "governance_role": "HR",
      "full_name": f"Seed script ({MARKER}) — HR"}
# Deliberately HR, not a HOD. `_assert_may_decide` restricts a MANAGER to their own team,
# resolved from `reporting_manager` on the USER document -- and this employee has no user
# account by design, so no seeded manager can ever have them on their team. HR decides for
# anyone, which is both allowed and what actually happens for a record HR created.
MGR = {"_id": "seed-approver", "role": "superadmin", "governance_role": "HR",
       "full_name": f"Seed script ({MARKER}) - Approver"}
APPROVER = {"_id": "seed-md", "role": "superadmin", "governance_role": "MD",
            "full_name": f"Seed script ({MARKER}) — Approver"}

PROFILE = {
    "employee_code": CODE,
    "display_name": NAME, "full_name": NAME,
    "first_name": "Manoj", "last_name": "Patel",
    "identity_snapshot": {"name": NAME, "email": "manoj.patel@example.com"},
    "official_email": "manoj.patel@example.com",
    "personal_email": "manoj.patel.personal@example.com",
    "personal_mobile": "+91 00000 99999",
    "gender": "Male", "date_of_birth": "1990-07-14", "blood_group": "O+",
    "employment_status": "Active", "employment_type": "Permanent",
    "joined_on": "2024-04-01", "confirmation_date": "2024-10-01",
    # Every one of these is a value the Employee Master seed put on the dropdowns, so the
    # profile reads as configured data rather than as free text that happens to match.
    "legal_entity": "Sparsh Magic Pvt Ltd",
    "business_unit": "Technology Services",
    "work_location": "Pune",
    "sub_department": "Payroll & Compliance",
    "grade": GRADE, "level": "Level 3",
    "job_title": "Senior Payroll Analyst",
    "cost_centre": "CC-2001 Technology",
    "employee_category": "Staff",
    "payroll_group": "PG1 Monthly Staff",
    "salary_template": "Standard Staff Structure",
    "attendance_policy_group": "General Shift",
    "holiday_calendar": "Maharashtra",
    "shift_code": "GEN",
    # Structurally valid, deliberately impossible. See the module docstring.
    "pan": "AAAPZ1234C", "aadhaar": "999988887777", "uan": "100100100100",
    "bank_name": "HDFC Bank", "bank_branch": "Pune — Baner",
    "bank_account": "50100999988887", "bank_ifsc": "HDFC0000123",
    "bank_account_holder": NAME, "bank_account_type": "Savings",
    "base_salary": 75000,
}

SALARY = [
    {"code": "BASIC", "amount": 37500},
    {"code": "HRA", "amount": 15000},
    {"code": "SPECIAL", "amount": 22300},
    {"code": "PT", "amount": 200},
]


def _stamp(doc: dict) -> dict:
    return {**doc, "demo_seed": MARKER}


async def _mark(coll: str, query: dict) -> None:
    """Stamp whatever a service just created, so --undo can find it again."""
    await mongo.get_collection(coll).update_many(query, {"$set": {"demo_seed": MARKER}})


# ─────────────────────────────────────────────────────────────
# The build
# ─────────────────────────────────────────────────────────────
async def build(company_id: str, with_payroll: bool) -> None:
    from app.models import hrms as M
    from app.services import hrms_attendance_service as AT
    from app.services import hrms_config_change_service as CC
    from app.services import hrms_leave_service as LV
    from app.services import hrms_payroll_service as PR
    from app.services import hrms_policy_version_service as PV

    profiles = mongo.get_collection(M.COLL_EMPLOYEE_PROFILES)
    if await profiles.find_one({"company_id": company_id, "employee_code": CODE}):
        log(f"{CODE} already exists - run --undo first to rebuild it.")
        return

    now = datetime.now(timezone.utc)
    await profiles.insert_one(_stamp({
        **PROFILE, "company_id": company_id,
        "created_at": now, "updated_at": now}))
    log(f"profile              {CODE}  {NAME}  grade {GRADE}")

    # ── Policy versions, each scoped to this grade and activated through §27 ──────
    async def governed(code: str, name: str, module: str, rules: dict, reason: str) -> int:
        await PV.save_definition(HR, company_id, {"code": code, "name": name,
                                                  "module": module})
        draft = await PV.save_draft(HR, company_id, {
            "policy_code": code, "effective_from": f"{PERIOD}-01", "rules": rules,
            "change_reason": reason})
        v = draft["version_no"]
        await PV.assign_scope(HR, company_id, {
            "policy_code": code, "version_no": v, "scope": {"grades": [GRADE]}})
        req = await CC.create_request(HR, company_id, {
            "entity_type": M.CONFIG_ENTITY_POLICY_VERSION, "entity_code": code,
            "version_no": v, "reason": reason, "effective_from": f"{PERIOD}-01",
            "title": f"{code} v{v} — {name}"})
        no = req["request_no"]
        await CC.analyse_impact(HR, company_id, no)
        await CC.submit(HR, company_id, no)
        # A different person decides: `decide` refuses the requester, which is the rule.
        await CC.decide(APPROVER, company_id, no, {"action": "approve",
                                                   "comments": "Approved for the demo."})
        await CC.activate(APPROVER, company_id, no)
        log(f"policy               {code} v{v} Active, scoped to grade {GRADE}  ({no})")
        return v

    await governed(M.POLICY_ATT_DAY, "Daily rules", "attendance",
                   {"half_day_fraction": 0.75, "daily_grace_minutes": 10},
                   "Gap 1 — a half day is worth three quarters here")
    await governed(M.POLICY_ATT_REGULARISATION, "Regularisation", "attendance",
                   {"approval_levels": 1, "window_days": 14},
                   "Gap 2 — the manager's approval is final for this grade")
    await governed(M.POLICY_PAY_POLICY, "Payroll policy", "payroll",
                   {"net_rounding": "Nearest"},
                   "Gap 4 — round this grade's net pay to the rupee")

    # One change left PENDING on purpose, so the Configuration Approvals inbox has
    # something awaiting a decision rather than only a history of decided ones.
    pending_draft = await PV.save_draft(HR, company_id, {
        "policy_code": M.POLICY_ATT_DAY, "effective_from": "2027-01-01",
        "rules": {"half_day_fraction": 0.5},
        "change_reason": "Gap 3/5 — awaiting a decision, to show the inbox"})
    pending = await CC.create_request(HR, company_id, {
        "entity_type": M.CONFIG_ENTITY_POLICY_VERSION, "entity_code": M.POLICY_ATT_DAY,
        "version_no": pending_draft["version_no"],
        "reason": "Revert the half-day fraction from 2027", "effective_from": "2027-01-01",
        "title": "ATT_DAY — revert the half-day fraction"})
    await CC.analyse_impact(HR, company_id, pending["request_no"])
    await CC.submit(HR, company_id, pending["request_no"])
    log(f"policy               ATT_DAY v{pending_draft['version_no']} PENDING APPROVAL "
        f"({pending['request_no']})")

    for coll in ("hrms_policy_definitions", "hrms_policy_versions",
                 "hrms_policy_assignments", "hrms_config_change_requests",
                 "hrms_config_approvals"):
        await _mark(coll, {"company_id": company_id, "demo_seed": {"$exists": False}})

    # ── Salary structure ──────────────────────────────────────────────────────────
    await PR.save_salary_structure(HR, company_id, {
        "employee_code": CODE, "effective_from": "2025-02-01", "components": SALARY,
        "revision_reason": "Demo structure"})
    await _mark(M.COLL_SALARY_STRUCTURES, {"company_id": company_id, "employee_code": CODE})
    log("salary structure     BASIC 37,500 + HRA 15,000 + SPECIAL 22,300 - PT 200")

    # ── Leave, approved, so Gap 8 has something to contradict ─────────────────────
    leave = await LV.apply_leave(HR, company_id, {
        "employee_code": CODE, "leave_type": "EL",
        "start_date": f"{PERIOD}-13", "end_date": f"{PERIOD}-14",
        "reason": "Family function"})
    try:
        await LV.act_on_leave(MGR, company_id, leave["leave_no"],
                              {"decision": "Manager Approved"})
        await LV.act_on_leave(HR, company_id, leave["leave_no"], {"decision": "Approved"})
    except Exception as e:                       # a one-level company approves in one step
        log(f"  (leave approval: {str(e)[:60]})")
    await _mark(M.COLL_LEAVES, {"company_id": company_id, "employee_code": CODE})
    log(f"leave                {leave['leave_no']}  EL  {PERIOD}-13..14")

    # ── Attendance: the month, with the exceptions each gap needs ─────────────────
    # 13th and 14th are the approved leave. The 13th ALSO carries a punch, which is Gap
    # 8's first mismatch; the 16th is Absent with nothing behind it, which is its second.
    days = []
    for d in range(1, 23):
        ds = f"{PERIOD}-{d:02d}"
        if d in (4, 5, 11, 12, 18, 19):
            days.append((ds, "off", None, None))          # weekends
        elif d == 9:
            days.append((ds, "half", "09:30", "13:00"))   # Gap 1 — worth 0.75
        elif d == 10:
            days.append((ds, "late", "10:55", "19:30"))   # Late / Early tab
        elif d == 13:
            days.append((ds, "leave_punch", "09:35", "18:40"))   # Gap 8 mismatch 1
        elif d == 14:
            days.append((ds, "leave", None, None))
        elif d == 16:
            days.append((ds, "absent", None, None))       # Gap 8 mismatch 2
        elif d == 20:
            days.append((ds, "od", None, None))           # set by the OD approval
        else:
            days.append((ds, "work", "09:28", "18:35"))

    counts = {}
    for ds, kind, tin, tout in days:
        if kind in ("off", "od"):
            continue
        payload = {"employee_code": CODE, "work_date": ds, "source": "Manual"}
        if kind == "absent":
            payload["override_status"] = "Absent"
        elif kind == "leave":
            payload["override_status"] = "On Leave"
        else:
            payload["actual_in"], payload["actual_out"] = tin, tout
        row = await AT.mark_attendance(HR, company_id, payload)
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    await _mark(M.COLL_ATTENDANCE, {"company_id": company_id, "employee_code": CODE})
    log("attendance           " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))

    # ── A regularisation under one approval level (Gap 2) ─────────────────────────
    reg = await AT.request_regularization(HR, company_id, {
        "employee_code": CODE, "work_date": f"{PERIOD}-21",
        "exception_type": "Missing Punch", "request_type": "Missing punch",
        "proposed_in": "09:30", "proposed_out": "18:30",
        "reason": "Forgot to punch out; confirmed with the team"})
    done = await AT.act_on_regularization(MGR, company_id, reg["req_no"], {
        "decision": "Manager Approved", "remarks": "Confirmed"})
    await _mark(M.COLL_ATTENDANCE_CORRECTIONS, {"company_id": company_id,
                                                "employee_code": CODE})
    log(f"regularisation       {reg['req_no']}  levels={reg.get('approval_levels')}  "
        f"-> {done['status']} on the manager's approval alone")

    # ── An OD, approved, which writes the day as On OD ────────────────────────────
    od = await AT.request_od(HR, company_id, {
        "employee_code": CODE, "od_date": f"{PERIOD}-20",
        "purpose": "Client payroll review", "location": "Mumbai"})
    od_done = await AT.act_on_od(MGR, company_id, od["od_no"], {
        "approved": True, "remarks": "Approved"})
    await _mark(M.COLL_OD_REQUESTS, {"company_id": company_id, "employee_code": CODE})
    await _mark(M.COLL_ATTENDANCE, {"company_id": company_id, "employee_code": CODE})
    log(f"outdoor duty         {od['od_no']}  levels={od.get('approval_levels')}  "
        f"-> {od_done['status']}")

    mism = await AT.leave_mismatches(company_id, PERIOD)
    log(f"leave mismatches     {mism['leave_mismatch']} "
        f"({mism['punched_while_on_leave']} punched on leave, "
        f"{mism['absent_without_leave_or_od']} unexplained absence)")

    if not with_payroll:
        log("")
        log("Payroll skipped. --with-payroll locks the company's attendance month and")
        log("calculates EVERY eligible employee, not only this one.")
        return

    await payroll(company_id)


async def payroll(company_id: str) -> None:
    """The run, the batch and a part-paid disbursal -- Gap 6's reconciliation needs all three."""
    from app.models import hrms as M
    from app.services import hrms_attendance_service as AT
    from app.services import hrms_disbursal_service as DB
    from app.services import hrms_payroll_service as PR

    await AT.lock_period(HR, company_id, PERIOD, f"Demo seed ({MARKER})")
    log(f"attendance lock      {PERIOD} Locked")
    await PR.create_run(HR, company_id, {"period": PERIOD})
    await PR.calculate_payroll(HR, company_id, PERIOD)
    for coll in (M.COLL_PAYROLL_RUNS, M.COLL_PAYROLL_RECORDS):
        await _mark(coll, {"company_id": company_id, "period": PERIOD})
    rec = await mongo.get_collection(M.COLL_PAYROLL_RECORDS).find_one(
        {"company_id": company_id, "period": PERIOD, "employee_code": CODE})
    log(f"payroll record       payable {rec.get('payable_days')} days, "
        f"LOP {rec.get('lop_days')}, net {rec.get('net_pay')} "
        f"(policy v{(rec.get('payroll_policy_version') or {}).get('version_no')})")


async def undo(company_id: str) -> None:
    total = 0
    for coll in SEEDED:
        res = await mongo.get_collection(coll).delete_many(
            {"company_id": company_id, "demo_seed": MARKER})
        if res.deleted_count:
            log(f"  {coll:<34} - {res.deleted_count}")
            total += res.deleted_count
    await mongo.get_collection("hrms_attendance_locks").delete_many(
        {"company_id": company_id, "period": PERIOD, "override_reason": {"$regex": MARKER}})
    log(f"Removed {total} document(s) stamped '{MARKER}'.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", required=True)
    parser.add_argument("--with-payroll", action="store_true",
                        help="also lock the month and run payroll for EVERY employee")
    parser.add_argument("--undo", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = await connect()
    try:
        log(f"Company {args.company}   employee {CODE}   period {PERIOD}")
        if args.undo:
            await undo(args.company)
        elif args.dry_run:
            log("Dry run - nothing written. This would create:")
            log(f"  1 profile ({NAME}, grade {GRADE}, no login account)")
            log("  1 salary structure, 3 Active policy versions scoped to that grade,")
            log("  4 config change requests (3 activated, 1 left pending),")
            log("  1 approved leave, ~16 attendance days, 1 regularisation, 1 OD")
            log(f"  {'and a payroll run for EVERY employee' if args.with_payroll else 'and NO payroll run'}")
        else:
            await build(args.company, args.with_payroll)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
