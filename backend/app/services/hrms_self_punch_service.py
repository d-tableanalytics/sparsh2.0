"""HRMS > Attendance > self check-in / check-out, geo-fenced to the company's offices.

An employee punches IN and OUT themselves from the Attendance page. The browser supplies
the device's location; this service decides whether that location is inside one of the
company's offices (name, lat/lng, radius in metres, set by HR). Outside every office -> the
punch is refused and nothing is written.

What a punch writes is the same day record HR's "Mark attendance" writes (actual_in /
actual_out, status, late minutes from the shift policy), with source "self" and the
location it was made from -- plus an append-only punch segment, like every other punch.

-- What the location can and cannot prove ------------------------------------------------
The position comes from the employee's own device. A determined person can fake it, as with
any browser/phone check-in. The server therefore (a) refuses a fix too imprecise to place
someone inside an office, and (b) keeps the coordinates, accuracy, office and distance on
every punch, so a pattern is visible to HR. It is a strong everyday control, not a
tamper-proof one.
"""
import math
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import COLL_ATTENDANCE, COLL_PUNCH_SEGMENTS, COLL_SETTINGS, compute_daily_status
from app.services.hrms_audit_service import audit
from app.services.hrms_ics import IST

ENTITY_ATTENDANCE = "attendance"
AUDIT_SELF_PUNCH = "self punch recorded"
AUDIT_OFFICES_SAVED = "office locations updated"

DEFAULT_RADIUS_M = 200
MIN_RADIUS_M, MAX_RADIUS_M = 25, 5000
# A location reported as "somewhere within 1.5 km" cannot place anybody inside an office.
MAX_ACCURACY_M = 300


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres (haversine). Pure."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_office(offices: list, lat: float, lng: float) -> Optional[dict]:
    """The closest office to a point, with the distance to it. Pure."""
    best = None
    for o in offices or []:
        d = distance_m(lat, lng, float(o["lat"]), float(o["lng"]))
        if best is None or d < best["distance_m"]:
            best = {**o, "distance_m": round(d)}
    return best


def _coord(value, label: str, low: float, high: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label} must be a number.")
    if not (low <= v <= high) or math.isnan(v):
        raise HTTPException(status_code=422, detail=f"{label} is out of range.")
    return v


# ─────────────────────────────────────────────────────────────
# Offices (HR)
# ─────────────────────────────────────────────────────────────
async def get_offices(company_id: str) -> list:
    doc = await get_collection(COLL_SETTINGS).find_one({"company_id": str(company_id)},
                                                       {"office_locations": 1})
    return list((doc or {}).get("office_locations") or [])


async def save_offices(actor: dict, company_id: str, offices: list) -> list:
    """Replace the company's office list. Each: name, lat, lng, radius_m."""
    if not isinstance(offices, list) or len(offices) > 50:
        raise HTTPException(status_code=422, detail="Send a list of up to 50 offices.")
    clean = []
    for o in offices:
        name = str((o or {}).get("name") or "").strip()[:80]
        if not name:
            raise HTTPException(status_code=422, detail="Every office needs a name.")
        lat = _coord(o.get("lat"), f"{name}: latitude", -90, 90)
        lng = _coord(o.get("lng"), f"{name}: longitude", -180, 180)
        try:
            radius = int(o.get("radius_m") or DEFAULT_RADIUS_M)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{name}: radius must be a whole number.")
        if not MIN_RADIUS_M <= radius <= MAX_RADIUS_M:
            raise HTTPException(status_code=422,
                                detail=f"{name}: radius must be {MIN_RADIUS_M}–{MAX_RADIUS_M} metres.")
        clean.append({"id": str(o.get("id") or ObjectId()), "name": name,
                      "lat": round(lat, 6), "lng": round(lng, 6), "radius_m": radius})
    await get_collection(COLL_SETTINGS).update_one(
        {"company_id": str(company_id)},
        {"$set": {"office_locations": clean, "updated_at": datetime.now(timezone.utc)},
         "$setOnInsert": {"company_id": str(company_id)}},
        upsert=True)
    await audit(actor, AUDIT_OFFICES_SAVED, ENTITY_ATTENDANCE, "offices",
                ", ".join(o["name"] for o in clean) or "none", company_id)
    return clean


# ─────────────────────────────────────────────────────────────
# The employee's own punches
# ─────────────────────────────────────────────────────────────
async def _own_code(actor: dict, company_id: str) -> str:
    from app.services.hrms_attendance_service import _own_employee_code
    code = await _own_employee_code(actor, company_id)
    if not code:
        raise HTTPException(
            status_code=409,
            detail="You have no employee record here yet, so there is nothing to check in to. "
                   "Ask HR to create your employee profile.")
    return code


def _local_now():
    now = datetime.now(timezone.utc).astimezone(IST)
    return now, now.strftime("%Y-%m-%d"), now.strftime("%H:%M")


async def today(actor: dict, company_id: str) -> dict:
    """The caller's own day: checked in / out yet, and the offices a punch can be made at."""
    code = await _own_code(actor, company_id)
    _, day, _ = _local_now()
    rec = await get_collection(COLL_ATTENDANCE).find_one(
        {"company_id": str(company_id), "employee_code": code, "work_date": day}) or {}
    offices = await get_offices(company_id)
    return {
        "employee_code": code, "work_date": day,
        "actual_in": rec.get("actual_in"), "actual_out": rec.get("actual_out"),
        "status": rec.get("status"), "late_minutes": rec.get("late_minutes"),
        "worked_minutes": rec.get("worked_minutes"),
        "in_office": (rec.get("self_in") or {}).get("office"),
        "out_office": (rec.get("self_out") or {}).get("office"),
        "locked": bool(rec.get("locked")),
        "offices": [{"name": o["name"], "radius_m": o["radius_m"]} for o in offices],
        "can_check_in": bool(offices) and not rec.get("actual_in") and not rec.get("locked"),
        "can_check_out": bool(rec.get("actual_in")) and not rec.get("actual_out")
        and not rec.get("locked"),
    }


async def punch(actor: dict, company_id: str, payload: dict) -> dict:
    """Check in or out, only from inside an office."""
    action = str(payload.get("action") or "").lower()
    if action not in ("in", "out"):
        raise HTTPException(status_code=422, detail='Action must be "in" or "out".')
    lat = _coord(payload.get("lat"), "Latitude", -90, 90)
    lng = _coord(payload.get("lng"), "Longitude", -180, 180)
    try:
        accuracy = float(payload.get("accuracy")) if payload.get("accuracy") is not None else None
    except (TypeError, ValueError):
        accuracy = None

    code = await _own_code(actor, company_id)
    offices = await get_offices(company_id)
    if not offices:
        raise HTTPException(
            status_code=409,
            detail="No office location is set up yet, so check-in is not available. Ask HR to "
                   "add the office on the Attendance page (Office locations).")
    if accuracy is not None and accuracy > MAX_ACCURACY_M:
        raise HTTPException(
            status_code=422,
            detail=(f"Your location is only accurate to about {round(accuracy)} m, which is too "
                    f"rough to confirm you are at the office. Turn on GPS / precise location "
                    f"and try again."))

    office = nearest_office(offices, lat, lng)
    if office["distance_m"] > office["radius_m"]:
        raise HTTPException(
            status_code=403,
            detail=(f"You are about {office['distance_m']} m from {office['name']}. Check-"
                    f"{action} only works within {office['radius_m']} m of an office."))

    now_utc = datetime.now(timezone.utc)
    _, day, hhmm = _local_now()
    coll = get_collection(COLL_ATTENDANCE)
    rec = await coll.find_one({"company_id": str(company_id), "employee_code": code,
                               "work_date": day}) or {}
    if rec.get("locked"):
        raise HTTPException(status_code=409, detail="Today's attendance is locked.")
    if action == "in" and rec.get("actual_in"):
        raise HTTPException(status_code=409,
                            detail=f"You already checked in today at {rec['actual_in']}.")
    if action == "out" and not rec.get("actual_in"):
        raise HTTPException(status_code=409, detail="Check in first — there is no check-in today.")
    if action == "out" and rec.get("actual_out"):
        raise HTTPException(status_code=409,
                            detail=f"You already checked out today at {rec['actual_out']}.")

    actual_in = hhmm if action == "in" else rec.get("actual_in")
    actual_out = hhmm if action == "out" else rec.get("actual_out")
    from app.services.hrms_attendance_rules_service import compute_day
    computed = await compute_day(company_id, code, day, actual_in, actual_out)
    where = {"lat": round(lat, 6), "lng": round(lng, 6),
             "accuracy_m": round(accuracy) if accuracy is not None else None,
             "office": office["name"], "office_id": office.get("id"),
             "distance_m": office["distance_m"], "at": now_utc}

    await coll.update_one(
        {"company_id": str(company_id), "employee_code": code, "work_date": day},
        {"$set": {"company_id": str(company_id), "employee_code": code, "work_date": day,
                  "actual_in": actual_in, "actual_out": actual_out,
                  "status": computed["status"], "worked_minutes": computed["worked_minutes"],
                  "late_minutes": computed["late_minutes"], "source": "self",
                  f"self_{action}": where, "locked": False, "updated_at": now_utc,
                  "updated_by": str(actor.get("_id") or "")},
         "$setOnInsert": {"created_at": now_utc}},
        upsert=True)
    await get_collection(COLL_PUNCH_SEGMENTS).insert_one({
        "company_id": str(company_id), "employee_code": code, "work_date": day,
        "punch_in": hhmm if action == "in" else None,
        "punch_out": hhmm if action == "out" else None,
        "source": "self", "location": where,
        "recorded_by": str(actor.get("_id") or ""), "recorded_at": now_utc,
    })
    await audit(actor, AUDIT_SELF_PUNCH, ENTITY_ATTENDANCE, f"{code}:{day}",
                f"check-{action} {hhmm} at {office['name']} ({office['distance_m']} m)", company_id)
    out = await today(actor, company_id)
    out["message"] = (f"Checked {action} at {hhmm} — {office['name']} "
                      f"({office['distance_m']} m away).")
    return out
