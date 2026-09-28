"""The phone-screen queue offers a call to everyone the interview gate would refuse.

The queue (screenable_candidates) listed only Shortlisted / Under Review. CV Shortlist on a
role that requires an assessment sends the candidate straight to Assessment Pending, so they
never appeared on it — and assert_telephonic_cleared then refused their interview for want of
a call nobody had been offered. Two functions answering the same question differently.

This walks every pre-panel stage and asserts the two agree, in both directions: whoever the
gate refuses is in the queue, and whoever the gate lets through is not.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_phone_queue_matches_gate   (from backend/)
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


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

CO = "C1"


async def main() -> int:
    from bson import ObjectId
    from fastapi import HTTPException

    from app.models import hrms as M
    import app.db.mongodb as mongo

    REQ = {"request_no": "HR-REQ-2026-001", "company_id": CO,
           "requisition_track": M.REQUISITION_TRACK_INTERNAL, "designation_name": "Engineer"}
    CLIENT_REQ = {"request_no": "CR-2026-001", "company_id": CO,
                  "requisition_track": "client", "designation_name": "Client role"}

    def cand(uk, status, req="HR-REQ-2026-001"):
        return {"_id": ObjectId(), "uk": uk, "company_id": CO, "candidate_name": uk,
                "request_no": req, "application_status": status, "requires_assessment": True}

    S = M.AppStatus
    candidates = FakeCollection([
        # Stages BEFORE the panel — the gate refuses all of these with no call on record.
        cand("CAN-REVIEW", S.UNDER_REVIEW.value),
        cand("CAN-SHORT", S.SHORTLISTED.value),
        cand("CAN-ASMPEND", S.ASSESSMENT_PENDING.value),     # where CV Shortlist sends them
        cand("CAN-ASMDONE", S.ASSESSMENT_COMPLETED.value),
        cand("CAN-ASMPASS", S.ASSESSMENT_PASSED.value),      # Bhumika's case
        # The gate's exits — none of these needs a call.
        cand("CAN-CALLED", S.ASSESSMENT_PASSED.value),       # has a passing screen
        cand("CAN-INTV", S.ASSESSMENT_PASSED.value),         # already interviewing
        cand("CAN-WAIVED", S.ASSESSMENT_PASSED.value),       # approved exception
        # Not on the internal track at all.
        cand("CAN-CLIENT", S.SHORTLISTED.value, req="CR-2026-001"),
        # Out of contention.
        cand("CAN-REJ", S.REJECTED.value),
    ])
    telephonic = FakeCollection([
        {"_id": ObjectId(), "company_id": CO, "uk": "CAN-CALLED", "outcome": "Passed"}])
    interviews = FakeCollection([
        {"_id": ObjectId(), "company_id": CO, "uk": "CAN-INTV", "interview_no": "INT-2026-001"}])
    store = {M.COLL_CANDIDATES: candidates, M.COLL_TELEPHONIC: telephonic,
             M.COLL_INTERVIEWS: interviews,
             M.COLL_REQUISITIONS: FakeCollection([dict(REQ), dict(CLIENT_REQ)])}
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_telephonic_service as T
    import app.services.hrms_exception_service as EX
    T.get_collection = mongo.get_collection

    async def fake_waiver(company_id, kind, request_no, uk):
        return {"exc_no": "EXC-1"} if uk == "CAN-WAIVED" else None
    EX.approved_exception_for = fake_waiver

    queue = {r["uk"] for r in await T.screenable_candidates({}, CO)}

    async def gate_refuses(uk):
        doc = next(d for d in candidates.docs if d["uk"] == uk)
        req = REQ if doc["request_no"] == REQ["request_no"] else CLIENT_REQ
        try:
            await T.assert_telephonic_cleared(CO, doc, req)
            return False
        except HTTPException as e:
            return e.status_code == 409

    section("Everyone the gate refuses is offered a call")
    for uk in ("CAN-REVIEW", "CAN-SHORT", "CAN-ASMPEND", "CAN-ASMDONE", "CAN-ASMPASS"):
        refused = await gate_refuses(uk)
        check(f"{uk}: gate refuses the interview", refused)
        check(f"{uk}: and the queue offers the call", uk in queue)

    section("Nobody the gate lets through is on the queue")
    for uk, why in (("CAN-CALLED", "already cleared by a call"),
                    ("CAN-INTV", "already interviewing"),
                    ("CAN-WAIVED", "waived by an approved exception"),
                    ("CAN-CLIENT", "client track has no phone step")):
        check(f"{uk} ({why}): gate lets them through", not await gate_refuses(uk))
        check(f"{uk}: and they are not on the queue", uk not in queue)

    section("Out of contention")
    check("a rejected candidate is not offered a call", "CAN-REJ" not in queue)

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
