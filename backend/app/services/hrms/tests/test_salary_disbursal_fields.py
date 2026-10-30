"""FRD 13 -- Salary Disbursal fields, and the two rules the table states rather than lists.

The twelve fields are the easy half. The two that carry a REQUIREMENT inside them are:

  * "Bank / Account / IFSC -- account should be MASKED IN UI". A field being present is not
    the same as it being safe: the account has to come back masked everywhere a screen
    reads it, and in full only in the bank file itself. So this suite checks the masking
    from the read side, not by inspecting what is stored.
  * "Retry Batch -- reference if failed payment is reprocessed". A retry is only useful if
    it links BOTH ways: the new batch knows what it retries, and the failed row points at
    where it went. A one-way link leaves the original looking permanently failed.

13's stated Phase 1 approach is file-out / status-in -- HRMS produces the advice, Finance
pays in the bank portal, the UTR comes back by hand or by import. There is deliberately no
bank API, so "no direct debit from here" is a property to confirm, not a gap to report.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_salary_disbursal_fields   (from backend/)
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
ACCOUNT = "50100999988887"
FIN = {"_id": "fi-1", "role": "admin", "full_name": "Farid Finance"}


async def main() -> int:
    from bson import ObjectId
    import app.db.mongodb as mongo
    from app.models import hrms as M
    import app.services.hrms_disbursal_service as DS
    import app.services.hrms_id_service as IS

    store: dict = {}
    getter = lambda name: store.setdefault(name, FakeCollection())  # noqa: E731
    mongo.get_collection = getter
    for mod in (DS, IS):
        mod.get_collection = getter

    async def no_audit(*a, **k):
        return None
    audited: list = []

    async def record_audit(actor, action, *a, **k):
        audited.append(action)
    DS.audit = record_audit
    # WHO may see payments is hrms_disbursal_service's own subject; this suite is about
    # the FIELDS and the two rules inside them, so Finance is recognised as Finance.
    DS._assert_payroll_role = lambda actor: None

    store.setdefault(M.COLL_PAYROLL_RUNS, FakeCollection()).docs.append(
        {"company_id": CO, "period": PERIOD, "status": "Locked"})
    store.setdefault(M.COLL_EMPLOYEE_PROFILES, FakeCollection()).docs.extend([
        {"_id": ObjectId(), "company_id": CO, "employee_code": "E1",
         "bank_name": "HDFC", "bank_branch": "Pune Baner", "bank_account": ACCOUNT,
         "bank_ifsc": "HDFC0000123", "bank_account_holder": "Asha A",
         "bank_account_type": "Savings"},
        # E2 has no bank details at all -- a NEFT batch must not silently drop them.
        {"_id": ObjectId(), "company_id": CO, "employee_code": "E2"},
    ])
    store.setdefault(M.COLL_PAYROLL_RECORDS, FakeCollection()).docs.extend([
        {"company_id": CO, "period": PERIOD, "employee_code": "E1",
         "employee_name": "Asha A", "net_pay": 47551.61},
        {"company_id": CO, "period": PERIOD, "employee_code": "E2",
         "employee_name": "Bela B", "net_pay": 38000.0},
        # Nothing to pay -- must not reach the bank at all.
        {"company_id": CO, "period": PERIOD, "employee_code": "E3",
         "employee_name": "Chandra C", "net_pay": 0.0},
    ])

    # -- The twelve fields -------------------------------------------------------------
    section("The fields 13 lists")
    batch = await DS.generate_batch(FIN, CO, PERIOD, {"payment_mode": "NEFT"})
    pay = batch["payments"][0]

    for key, label in (("period", "Payroll Period"),):
        check(f"{label}", batch.get(key) == PERIOD, batch.get(key))
    for key, label in (("employee_code", "Employee ID"), ("employee_name", "Name"),
                       ("bank_name", "Bank"), ("bank_account", "Account"),
                       ("bank_ifsc", "IFSC"), ("amount", "Net Pay"),
                       ("payment_mode", "Payment Mode"), ("batch_no", "Batch Number"),
                       ("payment_date", "Payment Date"), ("status", "Payment Status"),
                       ("utr", "UTR / Transaction Reference"),
                       ("failure_reason", "Failure Reason"),
                       ("retry_batch_no", "Retry Batch")):
        check(f"{label}", key in pay, sorted(pay))
    check("Generated Date -- when the file/advice was produced",
          batch.get("generated_at") is not None and batch.get("generated_by_name"), batch)
    check("Net Pay is the APPROVED transfer amount, to the paisa",
          pay["amount"] == 47551.61, pay["amount"])
    check("a payment starts Pending, with no UTR and no failure reason",
          pay["status"] == "Pending" and pay["utr"] is None
          and pay["failure_reason"] is None, pay)

    # -- Masking -----------------------------------------------------------------------
    section("'account should be masked in UI' -- checked from the READ side")
    check("the account comes back MASKED from the batch read",
          pay["bank_account"] != ACCOUNT and pay["bank_account"].endswith(ACCOUNT[-4:]),
          pay["bank_account"])
    check("...masked means the last four only, not the whole number",
          ACCOUNT[:-4] not in str(pay["bank_account"]), pay["bank_account"])
    check("the IFSC is NOT masked -- it identifies a branch, not a person",
          pay["bank_ifsc"] == "HDFC0000123", pay["bank_ifsc"])
    stored = store[M.COLL_PAYMENTS].docs[0]
    check("the FULL account is still stored -- masking is a view, not data loss",
          stored["bank_account"] == ACCOUNT, stored["bank_account"])

    name, content = await DS.bank_file(FIN, CO, batch["batch_no"])
    check("the bank FILE carries the full account -- it is the one place that may",
          ACCOUNT in content, content[:160])
    check("...and the download is audited",
          any("payment file" in str(a).lower() for a in audited), audited)
    reread = await DS.get_batch(FIN, CO, batch["batch_no"])
    check("...and downloading it does not unmask the screen afterwards",
          reread["payments"][0]["bank_account"] != ACCOUNT,
          reread["payments"][0]["bank_account"])
    check("the batch records WHEN the file went out and in which format",
          reread.get("file_downloaded_at") is not None
          and reread.get("bank_format"), reread.get("bank_format"))

    # -- Who is in the batch -----------------------------------------------------------
    section("Who reaches the bank")
    codes = {p["employee_code"] for p in batch["payments"]}
    check("an employee with nothing to pay is not in the batch", "E3" not in codes, codes)
    check("an employee with NO bank details is SKIPPED, not silently dropped",
          "E2" not in codes
          and any(s["employee_code"] == "E2" for s in batch.get("skipped") or []),
          batch.get("skipped"))
    check("...and the skip says why, so somebody can fix it",
          "bank" in (batch["skipped"][0].get("reason") or "").lower(), batch["skipped"])
    check("the batch totals only what it actually pays",
          batch["total_amount"] == 47551.61 and batch["employee_count"] == 1, batch)

    # -- Status, UTR and failure -------------------------------------------------------
    section("Payment Status / UTR / Failure Reason")
    check("the four statuses 13 names are the ones accepted",
          set(DS.PAYMENT_STATUSES) == {"Pending", "Processed", "Failed", "Rejected"},
          DS.PAYMENT_STATUSES)
    await expect("a status outside that set",
                 DS.update_payment(FIN, CO, batch["batch_no"], "E1", {"status": "Done"}),
                 422, "status must be")
    await expect("Processed with no UTR",
                 DS.update_payment(FIN, CO, batch["batch_no"], "E1",
                                   {"status": "Processed"}), 422, "utr")
    await expect("Processed with a UTR but no bank date",
                 DS.update_payment(FIN, CO, batch["batch_no"], "E1",
                                   {"status": "Processed", "utr": "U1"}), 422,
                 "processing date")
    await expect("Failed with no reason",
                 DS.update_payment(FIN, CO, batch["batch_no"], "E1",
                                   {"status": "Failed"}), 422, "why the payment failed")

    failed = await DS.update_payment(FIN, CO, batch["batch_no"], "E1",
                                     {"status": "Failed",
                                      "failure_reason": "Account frozen at the bank"})
    check("a failure is recorded with its reason",
          failed["status"] == "Failed"
          and failed["failure_reason"] == "Account frozen at the bank", failed)

    # -- Retry -------------------------------------------------------------------------
    section("Retry Batch -- the link has to go BOTH ways")
    store[M.COLL_EMPLOYEE_PROFILES].docs[0]["bank_account"] = "50100111122223"
    retry = await DS.generate_batch(FIN, CO, PERIOD, {
        "payment_mode": "NEFT", "retry_of": batch["batch_no"], "employee_codes": ["E1"]})
    check("the retry batch knows which batch it is retrying",
          retry.get("retry_of") == batch["batch_no"], retry.get("retry_of"))
    original = await DS.get_batch(FIN, CO, batch["batch_no"])
    orig_row = next(p for p in original["payments"] if p["employee_code"] == "E1")
    check("...and the FAILED row points at where it was reprocessed",
          orig_row.get("retry_batch_no") == retry["batch_no"],
          orig_row.get("retry_batch_no"))
    check("a reprocessed payment is not paid twice -- the retry is its own Pending row",
          retry["payments"][0]["status"] == "Pending"
          and retry["payments"][0]["batch_no"] == retry["batch_no"], retry["payments"][0])

    done = await DS.update_payment(FIN, CO, retry["batch_no"], "E1",
                                   {"status": "Processed", "utr": "UTR20260331001",
                                    "payment_date": "2026-03-31"})
    check("the retry settles with its UTR and bank date",
          done["utr"] == "UTR20260331001" and done["payment_date"] == "2026-03-31", done)
    check("...and a settled payment carries no stale failure reason",
          done.get("failure_reason") is None, done.get("failure_reason"))

    summary = await DS.payment_summary(CO, PERIOD)
    check("E1 is now settled", summary.get("paid") == 1, summary)
    # E2 was skipped for missing bank details and is STILL OWED. The summary says so
    # rather than reporting the period square, and `not_in_batch` is what distinguishes
    # "nobody generated a payment for them" from "their payment failed" -- which is the
    # difference between a data fix and a bank problem. §12 stage 13 then refuses to
    # close the period over an unpaid employee without a reason, so a skip raised here
    # cannot be quietly forgotten downstream.
    check("...and the employee skipped for missing bank details is still counted UNPAID",
          summary.get("unpaid") == 1 and summary.get("not_in_batch") == 1, summary)
    check("...with the amount still owed visible, not netted away",
          summary.get("payable_amount") > summary.get("paid_amount"), summary)

    # -- Phase 1 approach --------------------------------------------------------------
    section("13's Phase 1 approach: file out, status in -- no bank API")
    import inspect
    src = inspect.getsource(DS)
    check("nothing here calls a bank directly -- no outbound HTTP at all",
          not any(t in src for t in ("requests.", "httpx.", "aiohttp", "urlopen")), "")
    check("the UTR arrives by hand (update_payment) or by file (import_statuses)",
          hasattr(DS, "update_payment") and hasattr(DS, "import_statuses"))

    print("\n" + "=" * 66)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 66)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
