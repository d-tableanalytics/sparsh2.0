"""Attendance — punch handling, the derived daily summary, geofence and settings.

Design notes that differ deliberately from the reference project:

  * **One source of truth per day.** A day document holds `segments` (each in/out tap); the
    summary — first in, last out, worked minutes — is DERIVED on read. The reference stores a
    daily row *and* a segments table and lets them drift, which is why its payroll ignores
    manual corrections entirely.
  * **Manual entries are ordinary segments** flagged `source: "manual"` with the actor. Every
    consumer, payroll included, therefore counts them without needing to know they exist.
  * **The day boundary is IST**, matching the rest of the app (reminder_scheduler uses the same
    +5:30 boundary), so a 00:30 punch belongs to that IST day.
  * **Location is always recorded, but only blocks when geofencing is switched on** — enabling
    it retroactively would otherwise reject staff legitimately off-site.

Nothing here deletes attendance. A wrong entry is corrected by HR and the correction is
attributed, so the record stays auditable.
"""
import base64
import binascii
import io
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.db.mongodb import get_collection
from app.models.hrms import (
    COL_ATTENDANCE, SETTING_ATTENDANCE,
    AttendanceSettings, PUNCH_SOURCE_SELF, PUNCH_SOURCE_MANUAL,
)
from app.services.s3_service import upload_file_to_s3_with_key

logger = logging.getLogger(__name__)

# The product runs on Indian Standard Time. Same offset the reminder scheduler applies, so
# "today" means the same day in both.
IST = timezone(timedelta(hours=5, minutes=30))

# Selfies and any future attendance media go under a dedicated prefix so they can be served
# through an authorized route rather than a public bucket path.
SELFIE_PREFIX = "hrms/attendance"
MAX_SELFIE_BYTES = 4 * 1024 * 1024   # a webcam JPEG is ~100-400 KB; 4 MB is generous


def ist_now() -> datetime:
    return datetime.now(IST)


def ist_date_str(when: Optional[datetime] = None) -> str:
    return (when or ist_now()).strftime("%Y-%m-%d")


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres. Used for the geofence radius check."""
    r = 6371e3
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─── Settings ───────────────────────────────────────────────────────────────────
async def get_attendance_settings() -> dict:
    """Current policy, seeded with defaults on first read."""
    col = get_collection("system_settings")
    doc = await col.find_one({"setting_name": SETTING_ATTENDANCE})
    if not doc:
        return AttendanceSettings().model_dump()
    defaults = AttendanceSettings().model_dump()
    defaults.update({k: v for k, v in doc.items() if k in defaults and v is not None})
    return defaults


def validate_settings(updates: dict) -> dict:
    """Reject values that would corrupt downstream maths.

    Payroll reads these in Phase 4, so a bad radius or an unparseable shift time must be caught
    at the boundary rather than becoming a NaN in someone's salary.
    """
    clean = {}
    for key, value in updates.items():
        if value is None:
            continue
        if key in ("office_latitude", "office_longitude"):
            v = float(value)
            limit = 90 if key.endswith("latitude") else 180
            if not -limit <= v <= limit:
                raise ValueError(f"{key} must be between -{limit} and {limit}")
            clean[key] = v
        elif key == "office_radius_meters":
            v = int(value)
            if not 10 <= v <= 100_000:
                raise ValueError("office_radius_meters must be between 10 and 100000")
            clean[key] = v
        elif key in ("shift_start", "shift_end"):
            parse_hhmm(str(value))       # raises if malformed
            clean[key] = str(value)
        elif key == "weekly_offs":
            days = [int(d) for d in value]
            if any(d < 0 or d > 6 for d in days):
                raise ValueError("weekly_offs must be weekday numbers 0-6")
            clean[key] = sorted(set(days))
        elif key in ("geofence_enabled", "selfie_required"):
            clean[key] = bool(value)
    return clean


def parse_hhmm(value: str) -> int:
    """'HH:MM' -> minutes since midnight. Raises ValueError on anything else."""
    parts = str(value).split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time '{value}', expected HH:MM")
    hh, mm = int(parts[0]), int(parts[1])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"Invalid time '{value}'")
    return hh * 60 + mm


# ─── Selfie upload ──────────────────────────────────────────────────────────────
def store_selfie(data_uri: str, user_id: str, punch_date: str) -> str:
    """Decode a base64 selfie and put it on S3, returning the key.

    Returns "" on any problem: a punch must never fail because a photo didn't upload — the
    attendance record is the thing that matters, the selfie is supporting evidence.
    """
    if not data_uri:
        return ""
    try:
        raw = data_uri.split(",", 1)[1] if data_uri.startswith("data:") else data_uri
        blob = base64.b64decode(raw, validate=True)
        if not blob or len(blob) > MAX_SELFIE_BYTES:
            logger.warning("Selfie rejected for %s (%d bytes)", user_id, len(blob or b""))
            return ""
        name = f"{SELFIE_PREFIX}/{user_id}/{punch_date}_{int(ist_now().timestamp())}.jpg"
        result = upload_file_to_s3_with_key(io.BytesIO(blob), name, "image/jpeg")
        return (result or {}).get("key") or ""
    except (binascii.Error, ValueError, IndexError) as e:
        logger.warning("Selfie decode failed for %s: %s", user_id, e)
        return ""
    except Exception as e:
        logger.error("Selfie upload failed for %s: %s", user_id, e)
        return ""


# ─── Derived daily summary ──────────────────────────────────────────────────────
def summarize_day(doc: dict) -> dict:
    """Turn a day's segments into the numbers the UI and payroll read.

    Derived, never stored: there is exactly one place a day's totals can come from, so a manual
    correction changes them automatically.
    """
    segments = sorted(
        (doc or {}).get("segments", []),
        key=lambda s: s.get("in") or "",
    )
    if not segments:
        return {"firstIn": None, "lastOut": None, "workedMinutes": 0, "open": False, "segments": []}

    worked = 0
    for s in segments:
        if s.get("in") and s.get("out"):
            try:
                start = datetime.fromisoformat(s["in"])
                end = datetime.fromisoformat(s["out"])
                worked += max(0, int((end - start).total_seconds() // 60))
            except Exception:
                continue

    first_in = segments[0].get("in")
    closed = [s for s in segments if s.get("out")]
    last_out = closed[-1].get("out") if closed else None
    # A day is "open" while the most recent segment has no out — that is what the punch button
    # keys off, so it must reflect the newest tap, not merely any unclosed one.
    is_open = not segments[-1].get("out")

    return {
        "firstIn": first_in,
        "lastOut": last_out,
        "workedMinutes": worked,
        "open": is_open,
        "segments": segments,
    }


def serialize_day(doc: dict) -> dict:
    summary = summarize_day(doc)
    return {
        "id": str(doc.get("_id")),
        "userId": doc.get("user_id"),
        "punchDate": doc.get("punch_date"),
        "firstIn": summary["firstIn"],
        "lastOut": summary["lastOut"],
        "workedMinutes": summary["workedMinutes"],
        "open": summary["open"],
        "segments": summary["segments"],
        # True when ANY segment was entered by HR — the UI flags the row so a corrected day is
        # never mistaken for a self-recorded one.
        "hasManual": any(s.get("source") == PUNCH_SOURCE_MANUAL for s in summary["segments"]),
        "createdAt": doc.get("created_at"),
        "updatedAt": doc.get("updated_at"),
    }


# ─── Punching ───────────────────────────────────────────────────────────────────
async def get_day(user_id: str, punch_date: str) -> Optional[dict]:
    return await get_collection(COL_ATTENDANCE).find_one(
        {"user_id": user_id, "punch_date": punch_date})


async def punch(user_id: str, settings: dict, latitude: Optional[float],
                longitude: Optional[float], selfie: Optional[str],
                source: str = PUNCH_SOURCE_SELF, actor_id: Optional[str] = None) -> dict:
    """Toggle: open a segment if the day has none open, otherwise close the open one.

    A single endpoint rather than separate in/out calls, so the client can't desynchronise from
    the server about which state the day is in.
    """
    now = ist_now()
    punch_date = ist_date_str(now)
    col = get_collection(COL_ATTENDANCE)

    if settings.get("geofence_enabled"):
        if latitude is None or longitude is None:
            raise ValueError("Location is required to punch. Please allow location access.")
        distance = haversine_meters(
            float(latitude), float(longitude),
            float(settings.get("office_latitude") or 0),
            float(settings.get("office_longitude") or 0),
        )
        radius = int(settings.get("office_radius_meters") or 0)
        if distance > radius:
            raise ValueError(
                f"You are {int(distance)} m from the office. "
                f"Punching is allowed within {radius} m.")

    if settings.get("selfie_required") and not selfie:
        raise ValueError("A selfie is required to punch.")

    doc = await get_day(user_id, punch_date)
    segments = list((doc or {}).get("segments", []))
    selfie_key = store_selfie(selfie, user_id, punch_date) if selfie else ""

    stamp = now.isoformat()
    location = ({"lat": float(latitude), "lng": float(longitude)}
                if latitude is not None and longitude is not None else None)

    open_index = next((i for i, s in enumerate(segments) if not s.get("out")), None)
    if open_index is None:
        segments.append({
            "in": stamp, "out": None,
            "inLocation": location, "outLocation": None,
            "inSelfie": selfie_key, "outSelfie": "",
            "source": source,
            "actor": actor_id or user_id,
        })
        action = "in"
    else:
        segments[open_index]["out"] = stamp
        segments[open_index]["outLocation"] = location
        segments[open_index]["outSelfie"] = selfie_key
        action = "out"

    await col.update_one(
        {"user_id": user_id, "punch_date": punch_date},
        {
            "$set": {"segments": segments, "updated_at": datetime.now(timezone.utc)},
            "$setOnInsert": {
                "user_id": user_id, "punch_date": punch_date,
                "created_at": datetime.now(timezone.utc),
            },
        },
        upsert=True,
    )
    saved = await get_day(user_id, punch_date)
    return {"action": action, "day": serialize_day(saved)}


async def add_manual_segment(user_id: str, punch_date: str, punch_in: str,
                             punch_out: Optional[str], note: str, actor_id: str) -> dict:
    """HR recording a missed punch. Stored as an ordinary segment so payroll counts it."""
    in_minutes = parse_hhmm(punch_in)
    out_minutes = parse_hhmm(punch_out) if punch_out else None
    if out_minutes is not None and out_minutes <= in_minutes:
        raise ValueError("Punch out must be after punch in.")

    try:
        day = datetime.strptime(punch_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("punch_date must be YYYY-MM-DD")

    def stamp(minutes: int) -> str:
        return day.replace(hour=minutes // 60, minute=minutes % 60, tzinfo=IST).isoformat()

    segment = {
        "in": stamp(in_minutes),
        "out": stamp(out_minutes) if out_minutes is not None else None,
        "inLocation": None, "outLocation": None,
        "inSelfie": "", "outSelfie": "",
        "source": PUNCH_SOURCE_MANUAL,
        "actor": actor_id,
        "note": note or "",
    }

    await get_collection(COL_ATTENDANCE).update_one(
        {"user_id": user_id, "punch_date": punch_date},
        {
            "$push": {"segments": segment},
            "$set": {"updated_at": datetime.now(timezone.utc)},
            "$setOnInsert": {
                "user_id": user_id, "punch_date": punch_date,
                "created_at": datetime.now(timezone.utc),
            },
        },
        upsert=True,
    )
    saved = await get_day(user_id, punch_date)
    return serialize_day(saved)
