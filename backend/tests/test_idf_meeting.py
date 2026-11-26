"""Inter-Departmental Feedback — the results meeting (Setup defaults, link / venue, invitation,
reschedule by HR / Admin / MD, RSVP). Self-contained: in-memory collections, no real email.
Run from backend/:   PYTHONPATH=. python tests/test_idf_meeting.py
"""
import asyncio
import sys
from datetime import date, timedelta

from bson import ObjectId

from app.services.hrms.tests.test_phase2_employee import check, results, section
import os as _os
sys.path.insert(0, _os.path.dirname(__file__))
from test_inter_department_feedback import Coll, refused  # noqa: E402


async def main():
    import app.db.mongodb as mongo
    store = {}
    mongo.get_collection = lambda name: store.setdefault(name, Coll())
    import app.services.idf_service as S
    import app.services.idf_process as P
    import app.services.smtp_delivery as smtp
    import app.services.notification_service as ns
    from app.config.settings import settings
    for name, mod in list(sys.modules.items()):
        if name.startswith("app.") and hasattr(mod, "get_collection"):
            mod.get_collection = mongo.get_collection
    mails = []

    async def fake_email(to, subject, message, user_id=None, slug="manual", cc=None, meta=None):
        mails.append({"to": to, "subject": subject, "body": message, "slug": slug})
        return True

    async def fake_send(msg, rcpt):
        return True, None

    async def no_log(*a, **k):
        return None
    ns.send_email_notification, smtp.send_message, ns.log_notification = fake_email, fake_send, no_log
    settings.SMTP_USERNAME, settings.SMTP_PASSWORD = "noreply@test", "x"

    C = str(ObjectId())
    store["companies"] = Coll([{"_id": ObjectId(C), "name": "Test Co"}])
    D = {n: ObjectId() for n in ("HR", "Sales")}
    store["hrms_departments"] = Coll([{"_id": D[n], "company_id": C, "name": n, "active": True} for n in D])
    MD = {"_id": ObjectId(), "company_id": C, "role": "clientadmin", "governance_role": "MD",
          "full_name": "Md Person", "email": "md@co.test", "is_active": True}
    HRM = {"_id": ObjectId(), "company_id": C, "role": "clientuser", "governance_role": "HR",
           "full_name": "Hr Person", "email": "hr@co.test", "is_active": True}
    HOD = {n: {"_id": ObjectId(), "company_id": C, "role": "clientuser", "department": "HOD",
               "department_id": str(D[n]), "department_name": n, "full_name": f"{n} Head",
               "email": f"{n.lower()}@co.test", "is_active": True} for n in D}
    OUT = {"_id": ObjectId(), "company_id": C, "role": "clientuser", "full_name": "Not Invited",
           "email": "x@co.test", "is_active": True}
    store["learners"] = Coll([MD, HRM, *HOD.values(), OUT])

    section("Setup ▸ Results meeting")
    await refused("an invalid meeting time", S.save_setup(HRM, None, {"meeting": {"time": "25:00"}}), 422)
    await refused("a link that is not a web address", S.save_setup(HRM, None, {"meeting": {"link": "meet-room"}}), 422)
    st = await S.save_setup(HRM, None, {"meeting": {"time": "15:30", "duration": 45, "days_after": 2, "mode": "both",
                                                    "link": "https://meet.google.com/abc-defg-hij", "venue": "Board room"}})
    check("time, length, days after results, type, link and venue are saved",
          st["meeting"] == {"time": "15:30", "duration": 45, "days_after": 2, "mode": "both",
                            "link": "https://meet.google.com/abc-defg-hij", "venue": "Board room"})

    section("The meeting is booked from those settings when the cycle completes")
    cyc = await S.start_cycle(HRM, None, {"period": date.today().strftime("%Y-%m"),
                                          "reviews": [{"receiver_dept_id": str(D["HR"]), "giver_dept_ids": [str(D["Sales"])]},
                                                      {"receiver_dept_id": str(D["Sales"]), "giver_dept_ids": [str(D["HR"])]}]})
    form = {"ratings": {"information": 4, "planning": 4, "task_closure": 4, "ownership": 4}, "comments": {},
            "strength": "Responsive", "improvement": "Plan earlier"}
    await S.submit(HOD["Sales"], {**form, "giver_dept_id": str(D["Sales"]), "receiver_dept_id": str(D["HR"])})
    mails.clear()
    await S.submit(HOD["HR"], {**form, "giver_dept_id": str(D["HR"]), "receiver_dept_id": str(D["Sales"])})
    ev = next(e for e in store["LEARNER_CALENDER"].docs if e.get("kind") == "idf_results_meeting")
    c = store["idf_cycles"].docs[0]
    day = P.add_working_days(P._as_date(c["completed_at"]), 2)
    check("on the set day and India time (15:30 IST = 10:00 UTC), 45 minutes",
          ev["start"] == f"{day.isoformat()}T10:00:00Z" and ev["end"] == f"{day.isoformat()}T10:45:00Z")
    check("with the default link and venue", ev["meeting_link"] == "https://meet.google.com/abc-defg-hij"
          and ev["location"] == "Board room" and ev["meeting_mode"] == "both")
    inv = [m for m in mails if m["slug"] == "idf_meeting_invite_email"]
    check("the MD and both HODs get an invitation with date, time, link and venue",
          sorted(m["to"] for m in inv) == ["hr@co.test", "md@co.test", "sales@co.test"]
          and all("3:30 pm" in m["body"] and "meet.google.com" in m["body"] and "Board room" in m["body"] for m in inv))

    section("Who sees and manages it")
    mt = await P.get_meeting(HRM, None, cyc["id"])
    check("HR sees it with every invitee pending", mt["can_manage"] and len(mt["invitees"]) == 3
          and all(i["response"] == "pending" for i in mt["invitees"]))
    check("an invitee sees it (not as a manager)", not (await P.get_meeting(HOD["Sales"], None, cyc["id"]))["can_manage"])
    await refused("someone not invited", P.get_meeting(OUT, None, cyc["id"]), 403)

    section("RSVP")
    r1 = await P.rsvp_meeting(HOD["Sales"], cyc["id"], {"response": "attending"})
    check("Sales HOD replies Attending", r1["my_response"] == "attending" and r1["attending"] == 1)
    await refused("declining without a reason", P.rsvp_meeting(HOD["HR"], cyc["id"], {"response": "declined"}), 422)
    await refused("someone not invited replies", P.rsvp_meeting(OUT, cyc["id"], {"response": "attending"}), 403)
    mails.clear()
    r2 = await P.rsvp_meeting(HOD["HR"], cyc["id"], {"response": "declined", "reason": "On leave that day"})
    check("HR HOD declines with a reason", r2["declined"] == 1)
    dec = [m for m in mails if m["slug"] == "idf_meeting_declined_email"]
    check("the organisers (HR and the MD) are told, with the reason",
          sorted(m["to"] for m in dec) == ["hr@co.test", "md@co.test"] and all("On leave that day" in m["body"] for m in dec))

    section("Reschedule (HR / Client Admin / MD)")
    await refused("an HOD reschedules", P.reschedule_meeting(HOD["Sales"], None, cyc["id"], {"date": "2030-01-10"}), 403)
    await refused("a time in the past", P.reschedule_meeting(HRM, None, cyc["id"], {"date": "2020-01-10", "time": "10:00"}), 422)
    new_day = (date.today() + timedelta(days=10)).isoformat()
    mails.clear()
    rs = await P.reschedule_meeting(HRM, None, cyc["id"], {"date": new_day, "time": "10:00", "duration": 60,
                                                           "meeting_link": "https://teams.microsoft.com/l/xyz",
                                                           "venue": "Conference room 2", "note": "Moved for the HR HOD's leave."})
    check("moved to the new day and time with the new link and venue",
          rs["date"] == new_day and rs["time"] == "10:00" and rs["meeting_link"].startswith("https://teams")
          and rs["venue"] == "Conference room 2")
    check("everyone is asked to reply again", all(i["response"] == "pending" for i in rs["invitees"]))
    res = [m for m in mails if m["slug"] == "idf_meeting_rescheduled_email"]
    check("every invitee is emailed the new time, with the note",
          sorted(m["to"] for m in res) == ["hr@co.test", "md@co.test", "sales@co.test"]
          and all("Moved for the HR HOD's leave." in m["body"] and "10:00 am" in m["body"] for m in res))
    check("the cycle shows the new meeting date", store["idf_cycles"].docs[0]["results_meeting_date"] == new_day)
    md_rs = await P.reschedule_meeting(MD, None, cyc["id"], {"venue": "Board room"})
    check("the MD can change it too (venue only: same time, replies kept)", md_rs["venue"] == "Board room"
          and md_rs["date"] == new_day)

    print(f"\n=== {sum(results)}/{len(results)} checks passed ===")
    if sum(results) != len(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
