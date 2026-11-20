"""Calendar form validation — a form activity cannot be marked Done / Completed until EVERY
assigned respondent has submitted EVERY form it requires.

Self-contained: in-memory fake collections, no database. Run from backend/:
    python -m tests.test_calendar_form_validation
"""
import asyncio
import sys

from bson import ObjectId
from fastapi import HTTPException

from app.services.hrms.tests.test_phase2_employee import FakeCollection, check, results, section

CID = str(ObjectId())
HODS = ["Dhirendra Tanwar", "Manoj Pillai", "Sarvjeet Singh Panwar", "Ajey Soni",
        "Suraj Yadav", "Rahul Puri Goswami"]


async def expect_409(label, coro, needle=None):
    try:
        await coro
        check(f"{label} -> refused", False)
    except HTTPException as e:
        ok = e.status_code == 409 and (needle is None or needle in str(e.detail))
        check(f"{label} -> refused (409{', names ' + needle if needle else ''})", ok)


async def main():
    import app.db.mongodb as mongo
    from app.models.tpms import TPMS_EVENT_KIND

    store = {}
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())
    import app.services.tpms_form_link_service as FL
    import app.services.tpms_lifecycle_service as LC
    import app.services.tpms_schedule_service as SS
    for name, mod in list(sys.modules.items()):
        if name.startswith("app.") and hasattr(mod, "get_collection"):
            mod.get_collection = mongo.get_collection

    form_ev = {"_id": ObjectId(), "kind": TPMS_EVENT_KIND, "company_id": CID,
               "activity": "Accountability & Ownership Rating", "start": "2026-11-14T09:00:00",
               "tpms_status": "Scheduled", "title": "Accountability & Ownership Rating"}
    plain_ev = {"_id": ObjectId(), "kind": TPMS_EVENT_KIND, "company_id": CID,
                "activity": "HOD Review Meeting", "start": "2026-11-16T09:00:00",
                "tpms_status": "Scheduled", "title": "HOD Review Meeting"}
    store["STAFF_CALENDER"] = FakeCollection([form_ev, plain_ev])
    # A TPMS-enabled company, so the Edit path reaches the form check (and is not refused
    # earlier for a different reason).
    store["companies"] = FakeCollection([{"_id": ObjectId(CID), "name": "Test Co", "tpms_enabled": True}])
    links = FakeCollection([
        {"_id": ObjectId(), "company_id": CID, "period": "2026-11", "form_type": ft,
         "respondent_id": f"u{i}", "respondent_name": n,
         "status": "sent" if n == "Suraj Yadav" else "submitted"}
        for i, n in enumerate(HODS) for ft in ("accountability", "ownership")])
    store[FL.ASSIGNMENT_COLLECTION] = links

    client = {"_id": "c1", "role": "clientuser", "company_id": CID, "full_name": "Doer"}
    staff = {"_id": "s1", "role": "superadmin", "full_name": "Staff"}

    section("Status: 6 HODs x 2 forms, Suraj Yadav has submitted neither")
    st = await FL.form_submission_status(form_ev)
    check("form activity requires forms", st["required"] is True)
    check("12 links, 10 submitted", (st["total"], st["submitted"]) == (12, 10))
    check("Suraj Yadav pending on both forms",
          st["pending"] == [{"name": "Suraj Yadav", "forms": ["Accountability Rating", "Ownership Rating"]}]
          or (len(st["pending"]) == 1 and st["pending"][0]["name"] == "Suraj Yadav"
              and len(st["pending"][0]["forms"]) == 2))
    check("non-form activity requires nothing", (await FL.form_submission_status(plain_ev))["required"] is False)

    section("Every completion path is refused while a form is missing")
    await expect_409("Mark Done (doer)", LC.mark_learner_done(client, str(form_ev["_id"])), "Suraj Yadav")
    check("...learner_done NOT set", not store["STAFF_CALENDER"].docs[0].get("learner_done"))
    await expect_409("Confirm Complete (staff)", LC.confirm_completion(staff, str(form_ev["_id"])), "10 of 12")
    await expect_409("Edit status -> Completed", SS.update_schedule(staff, str(form_ev["_id"]), {"status": "Completed"}))
    check("...activity still Scheduled", store["STAFF_CALENDER"].docs[0].get("tpms_status") == "Scheduled")

    section("Non-form activity is unaffected")
    out = await LC.mark_learner_done(client, str(plain_ev["_id"]))
    check("Mark Done works on a non-form activity", out.get("ok") is True)

    section("Once Suraj submits, the activity can be completed")
    for d in links.docs:
        d["status"] = "submitted"
    out = await LC.mark_learner_done(client, str(form_ev["_id"]))
    check("Mark Done allowed when all 12 are in", out.get("ok") is True)
    out = await LC.confirm_completion(staff, str(form_ev["_id"]))
    check("Confirm Complete allowed -> Completed", out.get("status") == "Completed")

    section("No links issued for the month: falls back to the submissions")
    culture_ev = {"_id": ObjectId(), "kind": TPMS_EVENT_KIND, "company_id": CID,
                  "activity": "Culture Rating", "start": "2026-11-16T09:00:00", "tpms_status": "Scheduled"}
    store["STAFF_CALENDER"].docs.append(culture_ev)
    await expect_409("Culture, nothing submitted", LC.confirm_completion(staff, str(culture_ev["_id"])))
    from app.models.forms import submission_collection
    store.setdefault(submission_collection("culture"), FakeCollection()).docs.append(
        {"_id": ObjectId(), "company_id": CID, "period": "2026-11", "hod_id": "u0"})
    out = await LC.confirm_completion(staff, str(culture_ev["_id"]))
    check("Culture completes once a submission exists", out.get("status") == "Completed")

    passed = sum(results)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
