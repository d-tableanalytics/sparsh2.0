"""HRMS > Salary disbursal (Phase 1 FRD §13, §12 stages 10-13, §18).

The recommended Phase 1 approach, as the FRD states it: HRMS generates the approved bank
payment file / advice; Finance processes it in the bank portal; Finance or Payroll records
(or imports) the UTR and payment status per employee. No direct bank API.

  * A PAYMENT BATCH (PAYB-YYYY-NNN) is generated only from a LOCKED payroll (FRD §18). It
    takes every employee with net pay above zero who is not already paid or in a pending
    batch. Anyone without bank account / IFSC is left out and reported, never sent blank.
  * Each employee's PAYMENT row carries the destination (account masked in the UI), amount,
    status (Pending / Processed / Failed / Rejected), payment date, UTR and failure reason.
  * A FAILED or REJECTED payment is reprocessed through a RETRY batch, which records the
    original batch and links each retried payment back to it.
  * When every payable employee is Processed the run is marked Paid; Finance then closes
    the period (hrms_payroll_service.close_run).
"""
import csv
import io
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_PAYMENT_BATCH, AUDIT_PAYMENT_FILE, AUDIT_PAYMENT_STATUS, COLL_EMPLOYEE_PROFILES,
    COLL_PAYMENT_BATCHES, COLL_PAYMENTS, COLL_PAYROLL_RECORDS, COLL_PAYROLL_RUNS,
    ENTITY_PAYMENT_BATCH, PAYROLL_FINAL_STATUSES, PayrollRunStatus, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_employee_master_service import mask
from app.services.hrms_id_service import next_business_id

PAYMENT_MODES = ("NEFT", "RTGS", "IMPS", "Bank Transfer", "Cheque", "Cash", "Manual Advice")
PENDING, PROCESSED, FAILED, REJECTED = "Pending", "Processed", "Failed", "Rejected"
PAYMENT_STATUSES = (PENDING, PROCESSED, FAILED, REJECTED)
OPEN_OR_PAID = (PENDING, PROCESSED)


def _actor_id(actor) -> str:
    return str((actor or {}).get("_id") or "")


def _out(doc: dict, *, full_account: bool = False) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    if not full_account and doc.get("bank_account"):
        doc["bank_account"] = mask(doc["bank_account"])
    return doc


def _assert_payroll_role(actor: dict) -> None:
    from app.utils.hrms_access import sees_all_payroll
    if not sees_all_payroll(actor):
        raise HTTPException(status_code=403, detail="Only payroll / finance can see payments.")


async def _run(company_id: str, period: str) -> dict:
    run = await get_collection(COLL_PAYROLL_RUNS).find_one(
        {"company_id": str(company_id), "period": period})
    if not run:
        raise HTTPException(status_code=404, detail=f"No payroll run for {period}.")
    return run


async def generate_batch(actor: dict, company_id: str, period: str, payload: dict) -> dict:
    run = await _run(company_id, period)
    if run["status"] not in PAYROLL_FINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="A bank payment file is generated only from an approved and LOCKED "
                   "payroll (FRD §18).")
    if run["status"] == PayrollRunStatus.CLOSED.value:
        raise HTTPException(status_code=409, detail="This payroll period is closed.")
    mode = payload.get("payment_mode") or "NEFT"
    if mode not in PAYMENT_MODES:
        raise HTTPException(status_code=422,
                            detail=f"Payment mode must be one of: {', '.join(PAYMENT_MODES)}.")

    payments = get_collection(COLL_PAYMENTS)
    retry_of = (payload.get("retry_of") or "").strip() or None
    if retry_of:
        source = await get_collection(COLL_PAYMENT_BATCHES).find_one(
            {"company_id": str(company_id), "batch_no": retry_of, "period": period})
        if not source:
            raise HTTPException(status_code=404, detail=f"Batch {retry_of} not found.")
        retry_rows = await payments.find(
            {"company_id": str(company_id), "batch_no": retry_of,
             "status": {"$in": [FAILED, REJECTED]}, "retry_batch_no": None}).to_list(5000)
        wanted = {r["employee_code"] for r in retry_rows}
        if not wanted:
            raise HTTPException(status_code=409,
                                detail=f"{retry_of} has no failed payments left to retry.")
    else:
        wanted = None

    records = await get_collection(COLL_PAYROLL_RECORDS).find(
        {"company_id": str(company_id), "period": period}).to_list(5000)
    already = {p["employee_code"] for p in await payments.find(
        {"company_id": str(company_id), "period": period,
         "status": {"$in": list(OPEN_OR_PAID)}}, {"employee_code": 1}).to_list(5000)}
    profiles = {p["employee_code"]: p for p in await get_collection(
        COLL_EMPLOYEE_PROFILES).find({"company_id": str(company_id)}).to_list(5000)}

    now = datetime.now(timezone.utc)
    included, skipped = [], []
    for r in records:
        code = r["employee_code"]
        if wanted is not None and code not in wanted:
            continue
        if float(r.get("net_pay") or 0) <= 0:
            continue
        if code in already:
            continue
        p = profiles.get(code) or {}
        if mode not in ("Cash", "Cheque", "Manual Advice") and \
                not (p.get("bank_account") and p.get("bank_ifsc")):
            skipped.append({"employee_code": code, "employee_name": r.get("employee_name"),
                            "reason": "Bank account / IFSC missing"})
            continue
        included.append({
            "company_id": str(company_id), "period": period, "employee_code": code,
            "employee_name": r.get("employee_name"),
            "account_holder": p.get("bank_account_holder") or r.get("employee_name"),
            "bank_name": p.get("bank_name"), "bank_branch": p.get("bank_branch"),
            "bank_account": p.get("bank_account"), "bank_ifsc": p.get("bank_ifsc"),
            "bank_account_type": p.get("bank_account_type"),
            "amount": round(float(r["net_pay"]), 2), "payment_mode": mode,
            "status": PENDING, "utr": None, "payment_date": None, "failure_reason": None,
            "retry_batch_no": None, "retry_of_batch": retry_of,
            "created_at": now, "updated_at": now,
        })
    if not included:
        raise HTTPException(
            status_code=409,
            detail="Nobody left to pay in this period" + (
                f" ({len(skipped)} skipped for missing bank details)." if skipped else "."))

    batch_no = await next_business_id("payment_batch", str(company_id), now.year)
    batch = {
        "company_id": str(company_id), "batch_no": batch_no, "period": period,
        "payment_mode": mode, "status": "Generated", "retry_of": retry_of,
        "employee_count": len(included),
        "total_amount": round(sum(p["amount"] for p in included), 2),
        "skipped": skipped, "generated_by": _actor_id(actor),
        "generated_by_name": (actor or {}).get("full_name") or (actor or {}).get("email"),
        "generated_at": now, "file_downloaded_at": None, "created_at": now, "updated_at": now,
    }
    await get_collection(COLL_PAYMENT_BATCHES).insert_one(dict(batch))
    for p in included:
        p["batch_no"] = batch_no
    await payments.insert_many([dict(p) for p in included])
    if retry_of:
        for code in {p["employee_code"] for p in included}:
            await payments.update_one(
                {"company_id": str(company_id), "batch_no": retry_of, "employee_code": code},
                {"$set": {"retry_batch_no": batch_no, "updated_at": now}})
    await audit(actor, AUDIT_PAYMENT_BATCH, ENTITY_PAYMENT_BATCH, batch_no,
                f"{period}: {len(included)} payment(s), {batch['total_amount']}", company_id)
    return await get_batch(actor, company_id, batch_no)


async def list_batches(actor: dict, company_id: str, period: str) -> dict:
    _assert_payroll_role(actor)
    rows = await get_collection(COLL_PAYMENT_BATCHES).find(
        {"company_id": str(company_id), "period": period}).sort("generated_at", -1).to_list(200)
    return {"batches": [_out(r) for r in rows],
            "summary": await payment_summary(company_id, period)}


async def get_batch(actor: dict, company_id: str, batch_no: str) -> dict:
    _assert_payroll_role(actor)
    batch = await get_collection(COLL_PAYMENT_BATCHES).find_one(
        {"company_id": str(company_id), "batch_no": batch_no})
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_no} not found.")
    rows = await get_collection(COLL_PAYMENTS).find(
        {"company_id": str(company_id), "batch_no": batch_no}).sort(
        "employee_code", 1).to_list(5000)
    out = _out(batch)
    out["payments"] = [_out(r) for r in rows]
    return out


async def bank_file(actor: dict, company_id: str, batch_no: str,
                    format_name: Optional[str] = None) -> tuple:
    """The bank upload / advice file. Full account numbers appear ONLY here, for the user
    holding payroll approval, and every download is audited (FRD §13, §18).

    The LAYOUT comes from a configurable format (FRD §19), not from this function. A
    company that has configured none gets the DEFAULT format, which reproduces the previous
    hard-coded output byte for byte — downstream tooling built on the old shape keeps
    working. The format and its version are recorded on the batch, so a file can be
    explained months after it was sent.
    """
    from app.services import hrms_bank_format_service as BF
    batch = await get_batch(actor, company_id, batch_no)
    rows = await get_collection(COLL_PAYMENTS).find(
        {"company_id": str(company_id), "batch_no": batch_no}).sort(
        "employee_code", 1).to_list(5000)

    fmt = await BF.get_format(company_id, format_name or batch.get("bank_format"))
    now = datetime.now(timezone.utc)
    content = BF.render(fmt, rows, {
        "batch_no": batch_no,
        "generated_date": now.strftime("%Y-%m-%d"),
        "period": batch.get("period"),
    })
    extension = "txt" if fmt.get("fixed_width") else "csv"
    await get_collection(COLL_PAYMENT_BATCHES).update_one(
        {"company_id": str(company_id), "batch_no": batch_no},
        {"$set": {"file_downloaded_at": now, "file_downloaded_by": _actor_id(actor),
                  "bank_format": fmt.get("name"),
                  "bank_format_version": fmt.get("version"), "updated_at": now}})
    await audit(actor, AUDIT_PAYMENT_FILE, ENTITY_PAYMENT_BATCH, batch_no,
                fmt.get("name"), company_id)
    # DEF-12: the download's file name carries the date it was generated, as the file does.
    return f"{batch_no}_{batch['period']}_{now.strftime('%Y%m%d')}.{extension}", content


def _clean_status(payload: dict) -> dict:
    status = str(payload.get("status") or "").strip().title()
    if status not in PAYMENT_STATUSES:
        raise HTTPException(status_code=422,
                            detail=f"Status must be one of: {', '.join(PAYMENT_STATUSES)}.")
    out = {"status": status}
    utr = (payload.get("utr") or "").strip()
    pdate = (payload.get("payment_date") or "").strip()[:10]
    reason = (payload.get("failure_reason") or "").strip()
    if status == PROCESSED:
        if not utr:
            raise HTTPException(status_code=422, detail="A processed payment needs its UTR / reference.")
        if not pdate or not is_iso_date(pdate):
            raise HTTPException(status_code=422, detail="Give the bank processing date (YYYY-MM-DD).")
        out.update({"utr": utr[:64], "payment_date": pdate, "failure_reason": None})
    elif status in (FAILED, REJECTED):
        if not reason:
            raise HTTPException(status_code=422, detail="Say why the payment failed.")
        out.update({"failure_reason": reason[:300], "utr": utr[:64] or None,
                    "payment_date": pdate or None})
    return out


async def update_payment(actor: dict, company_id: str, batch_no: str, employee_code: str,
                         payload: dict) -> dict:
    _assert_payroll_role(actor)
    payments = get_collection(COLL_PAYMENTS)
    row = await payments.find_one({"company_id": str(company_id), "batch_no": batch_no,
                                   "employee_code": employee_code})
    if not row:
        raise HTTPException(status_code=404, detail="No such payment in this batch.")
    if row.get("retry_batch_no"):
        raise HTTPException(status_code=409,
                            detail=f"This payment was reprocessed in {row['retry_batch_no']}; "
                                   f"update it there.")
    clean = _clean_status(payload)
    if row["status"] == PROCESSED and clean["status"] != PROCESSED:
        # A bank return after confirmation happens; it is recorded, not silently changed.
        clean["previous_utr"] = row.get("utr")
    clean.update({"updated_at": datetime.now(timezone.utc), "updated_by": _actor_id(actor)})
    await payments.update_one({"_id": row["_id"]}, {"$set": clean})
    await audit(actor, AUDIT_PAYMENT_STATUS, ENTITY_PAYMENT_BATCH,
                f"{batch_no}:{employee_code}", f"{clean['status']} {clean.get('utr') or ''}",
                company_id)
    await _refresh_batch(company_id, batch_no, row["period"])
    return _out(await payments.find_one({"_id": row["_id"]}))


async def import_statuses(actor: dict, company_id: str, batch_no: str, rows: list) -> dict:
    """The bank's response file, mapped to {employee_code, status, utr, payment_date,
    failure_reason} rows. Each row is validated on its own; bad rows are reported back."""
    _assert_payroll_role(actor)
    done, errors = 0, []
    for i, raw in enumerate(rows or [], start=1):
        code = str((raw or {}).get("employee_code") or "").strip()
        try:
            await update_payment(actor, company_id, batch_no, code, raw or {})
            done += 1
        except HTTPException as e:
            errors.append({"row": i, "employee_code": code, "error": e.detail})
    return {"updated": done, "errors": errors,
            "batch": await get_batch(actor, company_id, batch_no)}


async def _refresh_batch(company_id: str, batch_no: str, period: str) -> None:
    rows = await get_collection(COLL_PAYMENTS).find(
        {"company_id": str(company_id), "batch_no": batch_no}, {"status": 1}).to_list(5000)
    statuses = [r["status"] for r in rows]
    if statuses and all(s == PROCESSED for s in statuses):
        status = "Processed"
    elif any(s in (FAILED, REJECTED) for s in statuses):
        status = "Partially Failed" if any(s == PROCESSED for s in statuses) else "Failed"
    elif any(s == PROCESSED for s in statuses):
        status = "Partially Processed"
    else:
        status = "Generated"
    await get_collection(COLL_PAYMENT_BATCHES).update_one(
        {"company_id": str(company_id), "batch_no": batch_no},
        {"$set": {"status": status, "updated_at": datetime.now(timezone.utc)}})
    summary = await payment_summary(company_id, period)
    updates = {"payment_summary": summary}
    run = await get_collection(COLL_PAYROLL_RUNS).find_one(
        {"company_id": str(company_id), "period": period})
    if run and run["status"] == PayrollRunStatus.LOCKED.value and summary["payable"] and \
            summary["unpaid"] == 0:
        updates["status"] = PayrollRunStatus.PAID.value
        updates["paid_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_PAYROLL_RUNS).update_one(
        {"company_id": str(company_id), "period": period}, {"$set": updates})


async def payment_summary(company_id: str, period: str) -> dict:
    records = await get_collection(COLL_PAYROLL_RECORDS).find(
        {"company_id": str(company_id), "period": period},
        {"employee_code": 1, "net_pay": 1}).to_list(5000)
    payable = {r["employee_code"]: float(r.get("net_pay") or 0) for r in records
               if float(r.get("net_pay") or 0) > 0}
    rows = await get_collection(COLL_PAYMENTS).find(
        {"company_id": str(company_id), "period": period}).to_list(10000)
    paid = {r["employee_code"] for r in rows if r["status"] == PROCESSED}
    pending = {r["employee_code"] for r in rows if r["status"] == PENDING}
    failed = {r["employee_code"] for r in rows
              if r["status"] in (FAILED, REJECTED) and not r.get("retry_batch_no")}
    return {
        "payable": len(payable),
        "payable_amount": round(sum(payable.values()), 2),
        "paid": len(paid & set(payable)),
        "paid_amount": round(sum(payable[c] for c in paid if c in payable), 2),
        "pending": len(pending - paid),
        "failed": len(failed - paid - pending),
        "not_in_batch": len(set(payable) - paid - pending - failed),
        "unpaid": len(set(payable) - paid),
    }


async def my_payment(company_id: str, period: str, employee_code: str) -> Optional[dict]:
    """The employee's own payment status, account masked -- for their payslip."""
    rows = await get_collection(COLL_PAYMENTS).find(
        {"company_id": str(company_id), "period": period, "employee_code": employee_code}
    ).sort("created_at", -1).to_list(10)
    if not rows:
        return None
    row = next((r for r in rows if r["status"] == PROCESSED), rows[0])
    return {k: _out(row).get(k) for k in ("status", "utr", "payment_date", "payment_mode",
                                           "bank_name", "bank_account", "batch_no")}
