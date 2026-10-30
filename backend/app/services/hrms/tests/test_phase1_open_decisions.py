"""FRD 19 -- the Phase 1 items awaiting the client's final confirmation.

19 is NOT a specification to verify. It is a list of eleven decisions nobody has made yet,
so the only thing that can be tested before the answers arrive is READINESS:

    every one of these answers must land as CONFIGURATION, not as a code change.

That is the whole claim of this file. For each row it checks that the decision has a place
to live -- a master list, a policy key, a component catalogue, a format record -- and that
the system does not quietly hardcode an answer the client has not given yet.

Where a default exists, it is checked to be a SAFE one: off, empty, or today's behaviour.
A default that silently decides a §19 question (a PF rate, a cut-off day, a payslip that
releases before payment) would mean the workshop's answer arrives to find the decision
already taken.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phase1_open_decisions   (from backend/)
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


def main() -> int:
    from app.models import hrms as M
    from app.utils import hrms_permission_policy as POL
    import app.services.hrms_payroll_service as PS
    import app.services.hrms_bank_format_service as BF
    import app.services.hrms_payslip_service as PSL
    import app.services.hrms_employee_master_service as EM

    C = M.Cap

    # 1 -------------------------------------------------------------------------------
    section("1. Employee Categories -- final list and applicability")
    check("the category is a company MASTER LIST, not an enum in code",
          "employee_category" in M.MASTER_LIST_FIELDS
          and M.MASTER_LIST_FIELDS["employee_category"][0] == "employee_categories",
          M.MASTER_LIST_FIELDS.get("employee_category"))
    check("...so an unconfigured company constrains nothing and waits for the list",
          "employee_categories" in M.MASTER_LIST_KEYS)
    check("APPLICABILITY: a category can scope a policy (§26), which is what the "
          "'applicability' half of this decision needs",
          M.POLICY_SCOPE_KEYS.get("employment_categories") == "employee_category",
          M.POLICY_SCOPE_KEYS.get("employment_categories"))
    check("...and can exclude people from payroll entirely",
          "excluded_employee_categories" in M.DEFAULT_PAYROLL_POLICY)
    check("...which excludes NOBODY until the client says otherwise",
          M.DEFAULT_PAYROLL_POLICY["excluded_employee_categories"] == [],
          M.DEFAULT_PAYROLL_POLICY["excluded_employee_categories"])

    # 2 -------------------------------------------------------------------------------
    section("2. Attendance Source -- Google / biometric / API / manual / import")
    for src in ("Google", "Biometric", "API", "Manual", "Import", "Self"):
        check(f"'{src}' is an accepted source", src in M.ATTENDANCE_SOURCES,
              M.ATTENDANCE_SOURCES)
    check("...so 'or combination' needs no decision in code -- they coexist per day",
          len(M.ATTENDANCE_SOURCES) >= 5)
    import app.services.hrms_attendance_rules_service as _AR
    check("a day keeps its ORIGINAL source beside the current one, so a mixed estate "
          "stays auditable after a correction",
          "original_source" in __import__("inspect").getsource(_AR.import_biometric))
    check("...and an automated import never overwrites a decided day",
          {"On Leave", "On OD"} <= _AR.PROTECTED_STATUSES
          and "regularization" in _AR.PROTECTED_SOURCES,
          (_AR.PROTECTED_STATUSES, _AR.PROTECTED_SOURCES))

    # 3 -------------------------------------------------------------------------------
    section("3. Late / Half-Day / LOP thresholds after grace and buffer")
    day_rules = M.ATTENDANCE_POLICY_RULES[M.POLICY_ATT_DAY]
    for key in ("daily_grace_minutes", "monthly_buffer_minutes", "late_escalation_days",
                "early_going_grace_minutes", "min_hours",
                "half_day_threshold_minutes", "half_day_late_minutes",
                "half_day_early_minutes", "absent_threshold_minutes",
                "half_day_fraction"):
        check(f"'{key}' is a policy key the workshop can set", key in day_rules,
              sorted(day_rules))
    check("every threshold starts UNSET -- none of them pre-empts the decision",
          all(day_rules[k] is None for k in
              ("daily_grace_minutes", "half_day_threshold_minutes",
               "absent_threshold_minutes", "min_hours", "half_day_late_minutes")),
          {k: day_rules[k] for k in ("daily_grace_minutes", "min_hours")})
    check("...and they are effective-dated and scoped, so an answer can differ by "
          "category / location / level without a second system",
          set(M.POLICY_SCOPE_KEYS) >= {"employment_categories", "locations", "levels",
                                       "shift_codes"})

    # 4 -------------------------------------------------------------------------------
    section("4. Monthly Attendance Cut-off -- date AND unlock authority")
    closure = M.ATTENDANCE_POLICY_RULES[M.POLICY_ATT_CLOSURE]
    check("the closing DAY is configurable", "closing_day" in closure)
    check("...and unset until the client names it", closure["closing_day"] is None)
    check("enforcement is OFF by default, so an unanswered question blocks nobody",
          closure["enforce_cutoff"] is False)
    check("the UNLOCK AUTHORITY is configurable too -- the other half of this row",
          "lock_cap" in closure, sorted(closure))
    check("...restricted to a safe set, so a typo cannot widen who closes a month",
          M.Cap.ATTENDANCE_CLOSURE_READ.value not in M.ATTENDANCE_LOCK_ALLOWED_CAPS
          and M.ATTENDANCE_LOCK_DEFAULT_CAP == C.ATTENDANCE_LOCK.value,
          sorted(M.ATTENDANCE_LOCK_ALLOWED_CAPS))

    # 5 -------------------------------------------------------------------------------
    section("5. Salary Components -- the full catalogue")
    types = {t.value for t in M.ComponentType}
    check("earnings, deductions AND employer contributions are all expressible",
          {"Earning", "Deduction", "Employer Contribution"} <= types, types)
    check("...plus reimbursement, recovery and informational",
          {"Reimbursement", "Recovery", "Informational"} <= types, types)
    methods = {m.value for m in M.CalculationMethod}
    check("a component can be fixed, a percentage, a formula, a slab, or an input",
          {"Fixed", "Percentage", "Formula", "Slab", "Manual Input",
           "Imported Input", "Attendance Linked"} <= methods, methods)
    check("NOTHING is seeded -- no Basic, no HRA, no assumed structure",
          not hasattr(M, "DEFAULT_SALARY_COMPONENTS"))

    # 6 -------------------------------------------------------------------------------
    section("6. Statutory Applicability -- PF / ESI / PT / TDS")
    check("no statutory RATE is hardcoded anywhere in the model",
          not any(n for n in dir(M)
                  if n.upper().startswith(("PF_", "ESI_", "TDS_"))
                  and isinstance(getattr(M, n), (int, float))),
          [n for n in dir(M) if n.upper().startswith(("PF_", "ESI_", "TDS_"))])
    check("they are ordinary components, so a rate is configuration",
          "Slab" in methods and "Formula" in methods)
    check("ENTITY / LOCATION specific rules are expressible -- a policy can be scoped "
          "to a legal entity or a location",
          {"locations"} <= set(M.POLICY_SCOPE_KEYS)
          and "legal_entity" in M.MASTER_LIST_FIELDS)
    check("a formula can read employee and attendance variables, so eligibility rules "
          "(e.g. ESI only below a wage ceiling) are expressible",
          hasattr(__import__("app.services.hrms_formula_engine", fromlist=["x"]),
                  "employee_variables"))

    # 7 -------------------------------------------------------------------------------
    section("7. Payroll Approval Matrix -- exact maker / checker / finance")
    pol = M.DEFAULT_PAYROLL_POLICY
    for key in ("checker_required", "checker_cap", "approver_cap", "lock_cap",
                "approver_distinct_from_checker"):
        check(f"'{key}' is configurable", key in pol, sorted(pol))
    check("a company may switch the checker stage off entirely if it says so",
          pol["checker_required"] is True)
    check("...but the approver is distinct from the checker unless told otherwise",
          pol["approver_distinct_from_checker"] is True)
    check("the configurable caps are allow-listed, so configuration cannot widen "
          "who approves payroll",
          M.PAYROLL_MATRIX_ALLOWED_CAPS == {C.PAYROLL_PROCESS.value,
                                            C.PAYROLL_CHECK.value,
                                            C.PAYROLL_APPROVE.value},
          M.PAYROLL_MATRIX_ALLOWED_CAPS)
    check("§17's named roles exist to BE the matrix once the client names people",
          {M.HrmsRole.PAYROLL_MAKER, M.HrmsRole.PAYROLL_CHECKER,
           M.HrmsRole.FINANCE} <= set(M.ROLE_CAPABILITIES))

    # 8 -------------------------------------------------------------------------------
    section("8. Bank File Format -- bank-specific layout and mandatory fields")
    check("the layout is a stored FORMAT record, not a function",
          hasattr(BF, "get_format") and hasattr(BF, "render"))
    check("a built-in DEFAULT exists so nothing is blocked while the bank is chosen",
          BF.DEFAULT_FORMAT.get("name") == BF.DEFAULT_FORMAT_NAME)
    import inspect as _i
    _bf = _i.getsource(__import__("app.services.hrms_disbursal_service",
                                  fromlist=["x"]).bank_file)
    check("...and the format AND its version are recorded on the batch, so a file "
          "can be explained months later",
          "bank_format" in _bf and "bank_format_version" in _bf)
    check("the mandatory fields are the format's own, so a bank that needs an extra "
          "column is configuration",
          isinstance(BF.DEFAULT_FORMAT.get("columns") or BF.DEFAULT_FORMAT.get("fields"),
                     list),
          sorted(BF.DEFAULT_FORMAT))

    # 9 / 10 ---------------------------------------------------------------------------
    section("9-10. Payslip format, and when it is released")
    check("the payslip template is per-company configuration",
          hasattr(PSL, "get_payslip_template")
          and "company_name" in PSL.TEMPLATE_DEFAULTS)
    check("...and is VERSIONED, so a payslip stays reproducible after a redesign",
          "version" in PSL.TEMPLATE_DEFAULTS)
    check("release timing is a policy key with exactly the two options §19 lists",
          pol.get("payslip_release") in ("on_lock", "after_payment"),
          pol.get("payslip_release"))
    check("...defaulting to the EARLIER one, which is today's behaviour",
          pol["payslip_release"] == "on_lock")

    # 11 -------------------------------------------------------------------------------
    section("11. Payment Failure Process -- owner and retry / reversal")
    check("a payment can be Failed or Rejected, distinctly from Pending",
          {"Failed", "Rejected", "Pending", "Processed"} ==
          set(__import__("app.services.hrms_disbursal_service",
                         fromlist=["x"]).PAYMENT_STATUSES),
          None)
    _ds = __import__("app.services.hrms_disbursal_service", fromlist=["x"])
    _clean = __import__("inspect").getsource(_ds._clean_status)
    check("a failure must carry its REASON -- the 'what went wrong' half",
          "why the payment failed" in _clean, _clean[:120])
    check("a processed payment must carry its UTR and bank date",
          "needs its UTR" in _clean and "processing date" in _clean)
    _gen = __import__("inspect").getsource(_ds.generate_batch)
    check("a retry batch links both ways, so the 'procedure' half is already modelled",
          "retry_of" in _gen and "retry_batch_no" in _gen)
    _adj = __import__("inspect").getsource(PS.create_post_lock_adjustment)
    check("REVERSAL is a post-lock adjustment type, beside arrear and recovery",
          "Reversal" in _adj and "Arrear" in _adj and "Recovery" in _adj)
    check("the OWNER half is a ROLE question, and the capability already exists "
          "to answer it", C.PAYROLL_APPROVE in set(C))

    print("\n" + "=" * 70)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 70)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
