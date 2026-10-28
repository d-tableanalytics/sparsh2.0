"""FRD 12 -- the 13-stage Payroll Approval Workflow, walked once, in order.

12 is a chain of custody, not a checklist. The stages matter far less individually than
the constraints BETWEEN them, so this suite walks one period from HR's attendance lock to
the closed, paid run, and at every hand-off checks the two things that make the stage real:

  * the gate  -- the stage cannot be reached from the wrong state (stage 8 cannot be
    skipped, stage 10 cannot lock an unapproved run);
  * the duty  -- it cannot be performed by the wrong PERSON. Maker-checker is enforced on
    the ACTOR, never on the role: HR legitimately holds both PAYROLL_PROCESS and
    PAYROLL_CHECK, so a role-level test would let one HR user wave their own run through.

The four-eyes checks are therefore the point of this file. A suite that only drove the
happy path would pass with every separation-of-duties control deleted.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_payroll_approval_workflow   (from backend/)
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
PERIOD = "2026-03"

MAKER = {"_id": "mk-1", "role": "admin", "full_name": "Maya Maker"}
CHECKER = {"_id": "ck-1", "role": "admin", "full_name": "Chandra Checker"}
APPROVER = {"_id": "ap-1", "role": "admin", "full_name": "Anita Approver"}
FINANCE = {"_id": "fi-1", "role": "admin", "full_name": "Farid Finance"}


async def main() -> int:
    from bson import ObjectId
    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_payroll_service as PS
    import app.services.hrms_disbursal_service as DS
    import app.services.hrms_attendance_service as AT
    import app.services.hrms_attendance_rules_service as AR
    import app.services.hrms_shift_service as SH
    import app.services.hrms_policy_version_service as PV
    import app.services.hrms_id_service as IS

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (PS, DS, AT, AR, SH, PV, IS):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    for mod in (PS, DS, AT):
        mod.audit = no_audit
    # WHICH role may see payments is its own subject (hrms_disbursal_service tests it);
    # this suite is about the ORDER of the stages and who may perform each, so Finance is
    # simply recognised as Finance here.
    DS._assert_payroll_role = lambda actor: None

    uid = ObjectId()
    store.setdefault(M.COLL_SETTINGS, FakeCollection()).docs.append(
        {"company_id": CO, "shift_policy": {**M.DEFAULT_SHIFT_POLICY}})
    store.setdefault("learners", FakeCollection()).docs.append(
        {"_id": uid, "company_id": CO, "full_name": "Asha A"})
    store.setdefault("staff", FakeCollection())
    store.setdefault(M.COLL_EMPLOYEE_PROFILES, FakeCollection()).docs.append(
        {"_id": ObjectId(), "company_id": CO, "employee_code": "E1", "user_id": str(uid),
         "joined_on": "2025-01-01", "employment_status": "Active",
         "bank_account": "123456789012", "bank_ifsc": "HDFC0001234",
         "bank_name": "HDFC", "bank_account_holder": "Asha A"})
    store.setdefault(M.COLL_SALARY_COMPONENTS, FakeCollection()).docs.extend([
        {"company_id": CO, "code": "BASIC", "name": "Basic", "active": True,
         "component_type": "Earning", "calculation_method": "Fixed", "sequence": 10},
        {"company_id": CO, "code": "PT", "name": "Professional Tax", "active": True,
         "component_type": "Deduction", "calculation_method": "Fixed", "sequence": 90},
    ])

    # ── Stages 1-2 ──────────────────────────────────────────────────────────────────
    section("1-2. HR finalises attendance exceptions, then locks the snapshot")

    async def _allow(*a, **k):
        return None

    async def _same(actor, company_id, query):
        return query
    AT.can = lambda u, c: True
    AT._assert_self_or_privileged = _allow
    AT._scope_query = _same

    for d in ("2026-03-02", "2026-03-03", "2026-03-04"):
        await AT.mark_attendance(MAKER, CO, {
            "employee_code": "E1", "work_date": d,
            "actual_in": "09:30", "actual_out": "18:30", "source": "Biometric"})
    dash = await AT.closure_dashboard(MAKER, CO, PERIOD)
    check("1. HR can see there is nothing left open", dash["ready_to_lock"] is True, dash)
    lock = await AT.lock_period(MAKER, CO, PERIOD)
    check("2. the attendance snapshot is locked", lock["status"] == "Locked")

    # ── Stage 3 ─────────────────────────────────────────────────────────────────────
    section("3. Payroll Maker opens the period and loads eligible employees")
    run = await PS.create_run(MAKER, CO, {"period": PERIOD})
    check("3. the run opens as a Draft", run["status"] == "Draft", run["status"])
    check("3. ...carrying the period's own bounds (§10 Payroll Period)",
          run["month"] == 3 and run["year"] == 2026
          and run["period_start"] == "2026-03-01" and run["period_end"] == "2026-03-31", run)
    await expect("opening the same period twice",
                 PS.create_run(MAKER, CO, {"period": PERIOD}), 409, "already exists")

    # ── Stages 4-5 ──────────────────────────────────────────────────────────────────
    section("4-5. Structures and inputs load; the run calculates")
    await PS.save_salary_structure(MAKER, CO, {
        "employee_code": "E1", "effective_from": "2026-01-01",
        "components": [{"code": "BASIC", "amount": 50000}, {"code": "PT", "amount": 200}]})

    run = await PS.calculate_payroll(MAKER, CO, PERIOD)
    check("5. the run calculates", run["status"] == "Calculated", run["status"])
    rec = store[M.COLL_PAYROLL_RECORDS].docs[0]
    check("4. the active structure is the basis, and is referenced on the record",
          rec.get("structure_effective_from") == "2026-01-01", rec.get("structure_id"))
    check("5. ...and the attendance basis it rested on is recorded (§18)",
          (run.get("attendance_basis") or {}).get("locked") is True,
          run.get("attendance_basis"))

    # ── Stage 6 ─────────────────────────────────────────────────────────────────────
    section("6. The maker corrects permitted inputs and reruns")
    await PS.adjust_record(MAKER, CO, PERIOD, "E1",
                                 {"arrears": 2500, "tds": 1000, "remarks": "Feb arrear"})
    rec = store[M.COLL_PAYROLL_RECORDS].docs[0]
    check("6. a monthly input is accepted while the run is with the maker",
          rec.get("arrears") == 2500.0, rec.get("arrears"))
    run = await PS.calculate_payroll(MAKER, CO, PERIOD)
    rec = store[M.COLL_PAYROLL_RECORDS].docs[0]
    check("6. ...and a rerun CARRIES IT OVER rather than wiping it",
          rec.get("arrears") == 2500.0 and rec.get("tds") == 1000.0, rec.get("arrears"))

    # ── Stage 7 ─────────────────────────────────────────────────────────────────────
    section("7. The maker submits the batch")
    run = await PS.submit_run(MAKER, CO, PERIOD, {"remarks": "March payroll"})
    check("7. the run is Submitted", run["status"] == "Submitted", run["status"])
    await expect("the maker editing an input after submitting",
                 PS.adjust_record(MAKER, CO, PERIOD, "E1", {"arrears": 9999}),
                 409, "")

    # ── Stage 8 ─────────────────────────────────────────────────────────────────────
    section("8. The Payroll/HR Checker verifies -- and it is never the maker")
    await expect("THE MAKER checking their own run",
                 PS.check_run(MAKER, CO, PERIOD, {"action": "check"}), 403,
                 "maker-checker")
    # A decision that names no action at all must REFUSE, not fall through to a reject.
    # It used to reject: `approved` absent read as False, so a checker who sent only
    # remarks threw the payroll back at the maker without ever saying so.
    await expect("a check naming no action, only remarks",
                 PS.check_run(CHECKER, CO, PERIOD, {"remarks": "looks fine"}),
                 422, "say what to do")
    await expect("a check naming an action that does not exist",
                 PS.check_run(CHECKER, CO, PERIOD, {"action": "appove"}), 422, "action must be")
    check("...and the run is still Submitted, not quietly rejected",
          (await PS.get_run(CHECKER, CO, PERIOD))["status"] == "Submitted")
    # The older clients' boolean still works, when it is actually present.
    run = await PS.check_run(CHECKER, CO, PERIOD, {"action": "check",
                                                   "remarks": "Components verified"})
    check("8. a second person checks it", run["status"] == "Checked", run["status"])
    check("8. Checked is its own state, so stage 9 can SEE the check happened",
          run.get("checked_by_name") == "Chandra Checker", run.get("checked_by_name"))

    # ── Stage 9 ─────────────────────────────────────────────────────────────────────
    section("9. Finance approves -- never the maker, never the checker")
    await expect("THE MAKER approving their own run",
                 PS.decide_run(MAKER, CO, PERIOD, {"action": "approve"}), 403,
                 "maker-checker")
    await expect("THE CHECKER also approving it",
                 PS.decide_run(CHECKER, CO, PERIOD, {"action": "approve"}), 403,
                 "someone else's to give")
    run = await PS.decide_run(APPROVER, CO, PERIOD, {"action": "approve",
                                                     "remarks": "Within variance"})
    check("9. a third person approves", run["status"] == "Approved", run["status"])
    check("9. the decision is attributed and reasoned",
          run.get("decided_by_name") == "Anita Approver"
          and run.get("decision_remarks") == "Within variance", run)

    # ── Stage 10 ────────────────────────────────────────────────────────────────────
    section("10. Payroll locks the approved run")
    run = await PS.lock_run(FINANCE, CO, PERIOD, {"remarks": "Locked for payment"})
    check("10. the run is Locked", run["status"] == "Locked", run["status"])
    await expect("editing an input on a locked run",
                 PS.adjust_record(MAKER, CO, PERIOD, "E1", {"arrears": 1}), 409, "")

    # ── Stages 11-12 ────────────────────────────────────────────────────────────────
    section("11-12. Payment file / advice, then the bank payment")
    batch = await DS.generate_batch(FINANCE, CO, PERIOD, {"payment_mode": "NEFT"})
    check("11. a payment batch is produced from the locked run",
          batch.get("batch_no") and batch.get("employee_count") == 1, batch)
    rows = store[M.COLL_PAYMENTS].docs
    check("11. ...with a payment line per payable employee, starting Pending",
          len(rows) == 1 and rows[0]["status"] == "Pending", rows)
    check("12. ...carrying the bank details the file needs",
          rows[0].get("bank_account") and rows[0].get("bank_ifsc")
          and rows[0].get("amount"), rows[0])

    # ── Stage 13 ────────────────────────────────────────────────────────────────────
    section("13. UTR / payment status captured, then the period closes")
    await expect("marking a payment Processed with no UTR",
                 DS.update_payment(FINANCE, CO, batch["batch_no"], "E1",
                                   {"status": "Processed"}), 422, "utr")
    await DS.update_payment(FINANCE, CO, batch["batch_no"], "E1",
                            {"status": "Processed", "utr": "UTR20260331001",
                             "payment_date": "2026-03-31"})
    paid = store[M.COLL_PAYMENTS].docs[0]
    check("13. the UTR and payment date are captured",
          paid["utr"] == "UTR20260331001" and paid["payment_date"] == "2026-03-31", paid)
    run = await PS.get_run(FINANCE, CO, PERIOD)
    check("13. ...and the run moves to Paid once every payable employee is settled",
          run["status"] == "Paid", run["status"])

    run = await PS.close_run(FINANCE, CO, PERIOD, {"remarks": "March closed"})
    check("13. the period closes", run["status"] == "Closed", run["status"])
    check("13. ...with the payment position frozen on the run",
          (run.get("payment_summary") or {}).get("unpaid") == 0, run.get("payment_summary"))

    # ── The controls that span the chain ────────────────────────────────────────────
    section("Chain controls")
    check("a closed run is a FINAL status, so corrections become adjustments",
          "Closed" in M.PAYROLL_FINAL_STATUSES and "Locked" in M.PAYROLL_FINAL_STATUSES)
    check("the full approval trail survives, stage by stage",
          [t["stage"] for t in run.get("approval_trail") or []]
          == ["Maker", "Maker", "Maker", "Maker", "Checker", "Approver", "Finance",
              "Finance"],
          [(t["stage"], t["action"]) for t in run.get("approval_trail") or []])

    # Stage 8 cannot be skipped when the company requires a checker.
    store[M.COLL_SETTINGS].docs[0]["payroll_policy"] = {"checker_required": True}
    await PS.create_run(MAKER, CO, {"period": "2026-04"})
    store[M.COLL_PAYROLL_RUNS].docs[-1]["status"] = "Submitted"
    await expect("approving a Submitted run while a checker is required",
                 PS.decide_run(APPROVER, CO, "2026-04", {"action": "approve"}),
                 409, "checked by the checker")

    store[M.COLL_PAYROLL_RUNS].docs[-1]["status"] = "Calculated"
    await expect("locking a run nobody approved",
                 PS.lock_run(FINANCE, CO, "2026-04", {}), 409, "approved")

    # -- The §17 roles actually carry the §12 chain -----------------------------------
    section("The §17 roles are sufficient together, and insufficient alone")
    from app.utils import hrms_access as ACC
    C = M.Cap

    def role_caps(governance):
        return ACC.capabilities_for({"_id": f"{governance}-1", "role": "clientuser",
                                     "_source_collection": "learners",
                                     "company_id": CO, "governance_role": governance})

    mk, ck, fn = (role_caps("PAYROLL_MAKER"), role_caps("PAYROLL_CHECKER"),
                  role_caps("FINANCE"))
    # Exactly ONE of the three can perform each stage. That is what makes the chain a
    # control rather than a sequence three people happen to follow in order.
    for stage, cap, holder, others in (
            ("3-7 open/calculate/submit", C.PAYROLL_PROCESS, ("Payroll Maker", mk),
             (("Checker", ck), ("Finance", fn))),
            ("8 check", C.PAYROLL_CHECK, ("Checker", ck), (("Payroll Maker", mk),)),
            ("9 approve", C.PAYROLL_APPROVE, ("Finance", fn),
             (("Payroll Maker", mk), ("Checker", ck))),
    ):
        name, held = holder
        check(f"stage {stage}: the {name} holds it", cap in held)
        for other_name, other in others:
            check(f"...and the {other_name} does not", cap not in other)

    three = {C.PAYROLL_PROCESS, C.PAYROLL_CHECK, C.PAYROLL_APPROVE}
    check("no single §17 role could run a payroll end to end on its own",
          not any(three <= r for r in (mk, ck, fn)))
    check("...but between them they cover every stage", three <= (mk | ck | fn))

    print("\n" + "=" * 66)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 66)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
