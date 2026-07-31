"""HRMS index plan.

The app has no migration step, so indexes have to be declared somewhere that runs. This is
that place. It is deliberately conservative:

  * It ONLY touches collections in models.hrms.HRMS_COLLECTIONS — all `hrms_*`, all created by
    this module, none of which hold pre-existing data. A guard below refuses any other name, so
    a future edit cannot accidentally point it at `staff`, `learners` or `calendar_events`.
  * It only ever CREATES indexes. There is no drop, no reindex, no data write, no schema change.
  * `create_index` is idempotent: re-running it with the same keys and name is a no-op, so this
    is safe on every restart.

Kept out of the request path and called once from the lifespan startup in main.py.
"""
import logging

from pymongo import ASCENDING, DESCENDING, TEXT

from app.db.mongodb import get_collection
from app.models.hrms import (
    HRMS_COLLECTIONS,
    COL_EMPLOYEES, COL_EMPLOYEE_EVENTS, COL_ORG_MASTERS,
    COL_ATTENDANCE, COL_LEAVES, COL_LEAVE_BALANCES,
    COL_PAYROLL_RUNS, COL_PAYSLIPS,
    COL_REQUISITIONS, COL_JDS, COL_POSTINGS, COL_CANDIDATES,
    COL_EXIT_DOCUMENTS,
)

logger = logging.getLogger(__name__)

# (collection, keys, kwargs). `unique` is used only where a duplicate would be a real bug —
# one attendance row per person per day, one balance per person per year, unique business ids.
INDEX_PLAN = [
    (COL_EMPLOYEES, [("employee_code", ASCENDING)], {"unique": True, "name": "uq_employee_code"}),
    (COL_EMPLOYEES, [("user_id", ASCENDING)], {"name": "ix_employee_user"}),
    (COL_EMPLOYEES, [("status", ASCENDING)], {"name": "ix_employee_status"}),
    (COL_EMPLOYEES, [("department", ASCENDING)], {"name": "ix_employee_department"}),
    (COL_EMPLOYEES, [("created_at", DESCENDING)], {"name": "ix_employee_created"}),
    # Directory search across the columns the employee list searches on.
    (COL_EMPLOYEES,
     [("full_name", TEXT), ("employee_code", TEXT), ("designation", TEXT),
      ("department", TEXT), ("work_email", TEXT)],
     {"name": "tx_employee_search"}),

    (COL_EMPLOYEE_EVENTS, [("employee_code", ASCENDING), ("created_at", DESCENDING)],
     {"name": "ix_emp_events_code_date"}),

    (COL_ORG_MASTERS, [("kind", ASCENDING), ("active", ASCENDING)], {"name": "ix_org_kind_active"}),

    # One attendance document per person per day — the daily summary; punches are embedded.
    (COL_ATTENDANCE, [("user_id", ASCENDING), ("punch_date", ASCENDING)],
     {"unique": True, "name": "uq_attendance_user_date"}),
    (COL_ATTENDANCE, [("punch_date", ASCENDING)], {"name": "ix_attendance_date"}),

    (COL_LEAVES, [("user_id", ASCENDING), ("status", ASCENDING)], {"name": "ix_leaves_user_status"}),
    (COL_LEAVES, [("start_date", ASCENDING)], {"name": "ix_leaves_start"}),

    (COL_LEAVE_BALANCES, [("user_id", ASCENDING), ("year", ASCENDING)],
     {"unique": True, "name": "uq_leave_balance_user_year"}),

    (COL_PAYROLL_RUNS, [("year", ASCENDING), ("month", ASCENDING)],
     {"unique": True, "name": "uq_payroll_run_period"}),
    (COL_PAYSLIPS, [("run_id", ASCENDING), ("user_id", ASCENDING)],
     {"unique": True, "name": "uq_payslip_run_user"}),

    (COL_REQUISITIONS, [("request_no", ASCENDING)], {"unique": True, "name": "uq_requisition_no"}),
    (COL_REQUISITIONS, [("closing_status", ASCENDING)], {"name": "ix_requisition_status"}),

    (COL_JDS, [("jd_no", ASCENDING)], {"unique": True, "name": "uq_jd_no"}),
    (COL_POSTINGS, [("public_code", ASCENDING)], {"unique": True, "name": "uq_posting_code"}),

    (COL_CANDIDATES, [("uk", ASCENDING)], {"unique": True, "name": "uq_candidate_uk"}),
    (COL_CANDIDATES, [("stage", ASCENDING)], {"name": "ix_candidate_stage"}),
    (COL_CANDIDATES, [("request_no", ASCENDING)], {"name": "ix_candidate_requisition"}),

    (COL_EXIT_DOCUMENTS, [("employee_code", ASCENDING)], {"name": "ix_exit_docs_employee"}),
]


async def ensure_hrms_indexes() -> None:
    """Create the HRMS indexes if they don't exist. Never drops, never writes data.

    A failure here must not stop the app from starting — a missing index degrades performance,
    it does not break correctness — so every error is logged and swallowed.
    """
    created = 0
    for collection_name, keys, kwargs in INDEX_PLAN:
        # Hard guard: this service may only ever touch HRMS collections.
        if collection_name not in HRMS_COLLECTIONS:
            logger.error("HRMS index plan refused non-HRMS collection %r — skipped", collection_name)
            continue
        try:
            await get_collection(collection_name).create_index(keys, **kwargs)
            created += 1
        except Exception as e:
            logger.warning("HRMS index %s on %s skipped: %s", kwargs.get("name"), collection_name, e)
    logger.info("HRMS indexes ensured (%d/%d).", created, len(INDEX_PLAN))
