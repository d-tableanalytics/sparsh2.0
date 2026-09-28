"""Three payroll defects found by the live Jan-2025 test run, pinned so they stay fixed.

1. Deduction lines on a salary structure were never deducted — a "Professional Tax 200"
   structure paid 50,000, and the payslip had no PT line.
2. Every record for Sparsh's own staff had `employee_name: null` (their profiles carry no
   name; identity lives on the user document), so the run table showed bare codes.
3. The payslip listed full-month earnings above a prorated Gross, so a 16-of-31-day payslip
   read "30,000 + 12,000 + 8,000 ... Gross 25,806.45" — correct, and looks like an error.

The live run's own figures are used as the expected values.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_payroll_live_findings   (from backend/)
"""
from __future__ import annotations

import asyncio

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


from app.services.hrms.tests.test_phase2_employee import (  # noqa: E402
    FakeCollection as _BaseFake, _matches,
)


class FakeCollection(_BaseFake):
    """+ delete_many, which calculate_payroll uses to replace a run's records on rerun."""

    async def find_one(self, query, projection=None, sort=None):
        hits = [d for d in self.docs if _matches(d, query)]
        for key, direction in reversed(sort or []):
            hits.sort(key=lambda d: d.get(key) or "", reverse=direction < 0)
        return hits[0] if hits else None

    async def delete_many(self, query):
        keep = [d for d in self.docs if not _matches(d, query)]
        removed = len(self.docs) - len(keep)
        self.docs[:] = keep
        return type("R", (), {"deleted_count": removed})()

CO = "C1"
PERIOD = "2025-01"


async def main() -> int:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    U_FULL, U_PART = ObjectId(), ObjectId()
    profiles = FakeCollection([
        {"company_id": CO, "employee_code": "EMP-FULL", "user_id": str(U_FULL), "employment_status": "Active"},
        {"company_id": CO, "employee_code": "EMP-PART", "user_id": str(U_PART), "employment_status": "Active"},
    ])
    staff = FakeCollection([
        {"_id": U_FULL, "full_name": "Dummy HR"},
        {"_id": U_PART, "first_name": "Dummy", "last_name": "Manager"},
    ])
    components = FakeCollection([
        {"company_id": CO, "code": "BASIC", "name": "Basic", "component_type": "Earning", "active": True},
        {"company_id": CO, "code": "HRA", "name": "House Rent Allowance", "component_type": "Earning", "active": True},
        {"company_id": CO, "code": "SPECIAL", "name": "Special Allowance", "component_type": "Earning", "active": True},
        {"company_id": CO, "code": "PT", "name": "Professional Tax", "component_type": "Deduction", "active": True},
    ])
    salary = [{"code": "BASIC", "amount": 30000}, {"code": "HRA", "amount": 12000},
              {"code": "SPECIAL", "amount": 8000}, {"code": "PT", "amount": 200}]
    structures = FakeCollection([
        {"company_id": CO, "employee_code": code, "effective_from": "2025-01-01", "components": salary}
        for code in ("EMP-FULL", "EMP-PART")])
    # EMP-FULL: every day captured. EMP-PART: joined on the 16th, so 1-15 have no row (LOP).
    attendance = FakeCollection(
        [{"company_id": CO, "employee_code": "EMP-FULL", "work_date": f"{PERIOD}-{d:02d}", "status": "Present"}
         for d in range(1, 32)]
        + [{"company_id": CO, "employee_code": "EMP-PART", "work_date": f"{PERIOD}-{d:02d}", "status": "Present"}
           for d in range(16, 32)])
    runs = FakeCollection([{"_id": ObjectId(), "company_id": CO, "period": PERIOD, "status": "Draft"}])
    records = FakeCollection()
    store = {M.COLL_EMPLOYEE_PROFILES: profiles, "staff": staff, "learners": FakeCollection(),
             M.COLL_SALARY_COMPONENTS: components, M.COLL_SALARY_STRUCTURES: structures,
             M.COLL_ATTENDANCE: attendance, M.COLL_PAYROLL_RUNS: runs, M.COLL_PAYROLL_RECORDS: records}
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_payroll_service as PR
    import app.services.hrms_payslip_service as PS
    import app.services.hrms_audit_service as AU
    for mod in (PR, PS, AU):
        mod.get_collection = mongo.get_collection

    HR = {"_id": "hr", "role": "admin"}
    await PR.calculate_payroll(HR, CO, PERIOD)
    by = {r["employee_code"]: r for r in records.docs}
    full, part = by["EMP-FULL"], by["EMP-PART"]

    section("1. A salary structure's own deductions are deducted")
    check("structured_deductions is the structure's Deduction lines (200)",
          full.get("structured_deductions") == 200)
    check("full month: gross 50,000, deductions 200, net 49,800",
          (full["gross_earnings"], full["total_deductions"], full["net_pay"]) == (50000, 200, 49800))
    check("deductions are NOT prorated: 16-of-31 days still owes the full 200",
          part["total_deductions"] == 200)
    check("16-of-31 days: gross 25,806.45, net 25,606.45 (the live run's figures)",
          (part["gross_earnings"], part["net_pay"]) == (25806.45, 25606.45))

    section("   ...but not when nothing was earned")
    profiles.docs.append({"company_id": CO, "employee_code": "EMP-NONE", "user_id": str(ObjectId()),
                          "employment_status": "Active"})
    structures.docs.append({"company_id": CO, "employee_code": "EMP-NONE",
                            "effective_from": "2025-01-01", "components": salary})
    await PR.calculate_payroll(HR, CO, PERIOD)
    none = next(r for r in records.docs if r["employee_code"] == "EMP-NONE")
    check("no paid days -> no PT deducted, net pay 0 (was -200)",
          (none["total_deductions"], none["net_pay"]) == (0, 0))
    full = next(r for r in records.docs if r["employee_code"] == "EMP-FULL")
    part = next(r for r in records.docs if r["employee_code"] == "EMP-PART")

    section("   ...and hand-entered PF/TDS still stack on top")
    await PR.adjust_record(HR, CO, PERIOD, "EMP-FULL", {"pf": 1800, "tds": 500})
    full = next(r for r in records.docs if r["employee_code"] == "EMP-FULL")
    check("50,000 - 200 PT - 1,800 PF - 500 TDS = 47,500",
          (full["total_deductions"], full["net_pay"]) == (2500, 47500))

    section("2. Records carry the employee's name")
    check("full_name from the user document", full["employee_name"] == "Dummy HR")
    check("first + last when there is no full_name", part["employee_name"] == "Dummy Manager")

    section("3. Payslip lines add up to what was paid")
    meta = {c["code"]: c for c in components.docs}

    def slip(record):
        return PS._compose_payslip(
            record, period=PERIOD, run_status="Locked", employee_name=None, department_name=None,
            designation_name=None, structure=structures.docs[0], component_meta=meta, template={})

    s_part = slip(part)
    paid = [e["amount"] for e in s_part["earnings"]]
    check("prorated earning lines sum EXACTLY to Gross (25,806.45)",
          round(sum(paid), 2) == part["prorated_gross"] == 25806.45)
    check("each line keeps its full-month figure alongside",
          [e.get("full_amount") for e in s_part["earnings"]] == [30000, 12000, 8000])
    check("Basic paid 15,483.87 of 30,000", s_part["earnings"][0]["amount"] == 15483.87)
    check("the structure's Professional Tax appears as a deduction line",
          any(d["label"] == "Professional Tax" and d["amount"] == 200 for d in s_part["deductions"]))

    s_full = slip(full)
    check("a full month shows plain amounts, no 'of' figure",
          all("full_amount" not in e for e in s_full["earnings"]))
    check("full-month payslip deductions: PT 200, PF 1,800, TDS 500",
          [(d["label"], d["amount"]) for d in s_full["deductions"]]
          == [("Professional Tax", 200), ("PF", 1800), ("TDS", 500)])

    section("   A record calculated BEFORE this fix is shown as it was paid")
    legacy = {k: v for k, v in part.items() if k != "structured_deductions"}
    s_old = slip(legacy)
    check("no Professional Tax line the old total never took",
          not any(d["label"] == "Professional Tax" for d in s_old["deductions"]))

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
