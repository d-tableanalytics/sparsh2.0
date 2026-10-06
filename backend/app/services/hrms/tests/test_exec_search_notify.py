"""Executive Search postings: the MD is told one needs approval, and HR is told when it is
approved. Also: role notifications reach Sparsh Magic's own staff (the `staff` collection).

Run:  python -m app.services.hrms.tests.test_exec_search_notify   (from backend/)
"""
import asyncio
from datetime import datetime, timedelta, timezone

RESULTS = []


def check(label: str, ok: bool) -> None:
    RESULTS.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")


def section(title: str) -> None:
    print(f"\n-- {title} --")


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

CO = "C-SPARSH"


async def main() -> None:
    from bson import ObjectId
    from app.models import hrms as M
    import app.db.mongodb as mongo
    import app.services.hrms_notify_service as N
    import app.services.hrms_posting_service as P
    import app.utils.hrms_access as HA

    U_MD, U_HR, U_HR2, U_HOD = (ObjectId() for _ in range(4))
    staff = FakeCollection([
        {"_id": U_MD, "role": "staff", "governance_role": "MD"},
        {"_id": U_HR, "role": "staff", "governance_role": "HR"},
        {"_id": U_HR2, "role": "staff", "governance_role": "HR"},
        {"_id": U_HOD, "role": "staff", "governance_role": "HOD"},
    ])
    postings = FakeCollection([{
        "posting_code": "JB-EXEC01", "company_id": CO, "title": "Head of Sales",
        "live_status": M.LiveStatus.PENDING_APPROVAL.value, "posted_by": str(U_HR),
        "channels": ["Executive Search"], "created_at": datetime.now(timezone.utc)}])
    store = {"staff": staff, "learners": FakeCollection(), M.COLL_JOB_POSTINGS: postings,
             M.COLL_AUDIT_LOG: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())
    for mod in (N, P):
        mod.get_collection = mongo.get_collection

    async def internal_id():
        return CO
    HA.internal_company_id = internal_id

    sent = []

    async def capture_users(ids, title, message, **kw):
        for i in ids:
            sent.append((str(i), title))

    async def capture_user(uid, title, message, **kw):
        sent.append((str(uid), title))
    N.notify_users = capture_users
    P.notify_user = capture_user

    try:
        section("Role notifications reach the company's own staff")
        await N.notify_hrms_role(CO, ["MD"], "hello", "body")
        check("the internal MD (a staff account) is notified", sent == [(str(U_MD), "hello")])

        section("HR creates an Executive Search posting -> the MD is told")
        sent.clear()
        await P._notify_exec_search_pending(CO, "JB-EXEC01", "Head of Sales")
        check("the MD gets 'Executive Search posting JB-EXEC01 needs your approval.'",
              (str(U_MD), "Executive Search posting JB-EXEC01 needs your approval.") in sent)
        check("nobody else is told", {u for u, _ in sent} == {str(U_MD)})

        section("The MD approves -> HR is told, once each")
        sent.clear()
        MD = {"_id": str(U_MD), "role": "staff", "governance_role": "MD"}
        out = await P.approve_exec_search(MD, CO, "JB-EXEC01")
        check("the approval flow is unchanged: it moves to Draft",
              out["live_status"] == M.LiveStatus.DRAFT.value)
        msg = "Executive Search posting JB-EXEC01 has been approved. You can now publish it."
        check("the HR who created it is told", (str(U_HR), msg) in sent)
        check("the other HR is told too", (str(U_HR2), msg) in sent)
        check("the creator is not told twice",
              sum(1 for u, t in sent if u == str(U_HR)) == 1)
        check("the MD and the HOD are not told", not {str(U_MD), str(U_HOD)} & {u for u, _ in sent})
    finally:
        mongo.get_collection = original

    passed = sum(RESULTS)
    print(f"\n=== {passed}/{len(RESULTS)} checks passed ===")
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
