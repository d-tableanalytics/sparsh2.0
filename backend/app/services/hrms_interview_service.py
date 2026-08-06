"""HRMS > interviews and scorecard evaluation.

Schedules rounds, enforces the assessment gate, records structured evaluations and drives
the pass-chain to Selected.

-- Two independent checks on every advance ------------------------------------------
`PASS_NEXT` (models/hrms.py) says where a passed round INTENDS to send a candidate.
`FORWARD_TRANSITIONS` (Phase 5) says whether that move is LEGAL from where they actually
are. Both must agree. A single trusted table would let a stale round type push a candidate
somewhere the lifecycle forbids.

-- Row scoping ----------------------------------------------------------------------
Reading your OWN interviews is an inherent right, not a capability: an interviewer must be
able to see the interview they were booked for, and that must not be revocable by a
permission edit. `interview.read` WIDENS the list; it does not unlock it.

  HR / MD / ADMIN / INTERNAL   every interview in the company
  MANAGER                      their own interviews + candidates on requisitions they raised
  EMPLOYEE / anyone else       only interviews where they are the interviewer
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_INTERVIEW_CANCELLED, AUDIT_INTERVIEW_EVALUATED, AUDIT_INTERVIEW_RESCHEDULED,
    AUDIT_INTERVIEW_SCHEDULED, AUDIT_INTERVIEW_UPDATED, AUDIT_STAGE_CHANGED,
    COLL_CANDIDATES, COLL_INTERVIEWS, COLL_REQUISITIONS, COMPETENCY_KEYS,
    DEFAULT_DURATION_MIN, DURATION_STEP_MIN, ENTITY_CANDIDATE, ENTITY_INTERVIEW,
    MAX_SCORE, MIN_DURATION_MIN, MIN_SCORE, OUTCOME_STATUS, PASS_NEXT,
    PRE_ASSESSMENT_STATUSES, AppStatus, Cap, HrmsRole, InterviewMode, InterviewRound,
    InterviewStatus, Outcome, can_transition,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_ics import build_invite
from app.services.hrms_id_service import next_business_id
from app.services.hrms_notify_service import notify_user
from app.utils.hrms_access import can, hrms_role
from app.utils.hrms_public_guard import clean_text


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _actor_name(actor: dict) -> str:
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "Unknown")


def _parse_when(value: str) -> datetime:
    """Parse an ISO-8601 datetime. Naive input is treated as IST, matching the rest of HRMS."""
    from app.services.hrms_ics import IST
    if not value:
        raise HTTPException(status_code=422, detail="Pick a date and time.")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail="That date and time could not be read. Use a full date and time.")
    return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed


def _validate_duration(value) -> int:
    try:
        duration = int(value if value is not None else DEFAULT_DURATION_MIN)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Duration must be a whole number of minutes.")
    if duration < MIN_DURATION_MIN:
        raise HTTPException(
            status_code=422, detail=f"Duration must be at least {MIN_DURATION_MIN} minutes.")
    if duration % DURATION_STEP_MIN:
        raise HTTPException(
            status_code=422,
            detail=f"Duration must be in {DURATION_STEP_MIN}-minute steps.")
    return duration


def _validate_place(mode, meeting_link, location) -> tuple:
    """Virtual needs a link, Offline needs a location. An interview nobody can find is not
    scheduled, it is only recorded."""
    mode = getattr(mode, "value", mode)
    link = clean_text(meeting_link, limit=500)
    place = clean_text(location, limit=300)
    if mode == InterviewMode.VIRTUAL.value:
        if not link:
            raise HTTPException(
                status_code=422, detail="A virtual interview needs a meeting link.")
        if not link.lower().startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422, detail="The meeting link must start with http:// or https://.")
        return mode, link, None
    if not place:
        raise HTTPException(
            status_code=422, detail="An in-person interview needs a location.")
    return mode, None, place


async def _resolve_interviewer(company_id: str, interviewer_id: str) -> dict:
    if not interviewer_id:
        raise HTTPException(status_code=422, detail="Choose who will take the interview.")
    try:
        oid = ObjectId(str(interviewer_id))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=422, detail="Invalid interviewer.")
    person = await get_collection("learners").find_one(
        {"_id": oid, "company_id": str(company_id)},
        {"full_name": 1, "first_name": 1, "last_name": 1, "email": 1})
    if not person:
        raise HTTPException(
            status_code=422, detail="The interviewer must be a user of this company.")
    return person


def _person_name(doc: dict) -> str:
    return (doc.get("full_name")
            or f"{doc.get('first_name') or ''} {doc.get('last_name') or ''}".strip()
            or doc.get("email") or "Unknown")


# -------------------------------------------------------------
# Scoping
# -------------------------------------------------------------
async def _scope_filter(actor: dict, company_id: str) -> dict:
    """The query clause limiting which interviews `actor` may see.

    Reading your own is never gated -- see the module docstring.
    """
    actor_id = str(actor.get("_id") or "")
    role = hrms_role(actor)

    if can(actor, Cap.INTERVIEW_READ) and role != HrmsRole.MANAGER:
        return {}

    clauses = [{"interviewer_id": actor_id}]
    if role == HrmsRole.MANAGER:
        rows = await get_collection(COLL_REQUISITIONS).find(
            {"company_id": str(company_id), "created_by": actor_id},
            {"request_no": 1}).to_list(2000)
        if rows:
            clauses.append({"request_no": {"$in": [r["request_no"] for r in rows]}})
    return {"$or": clauses}


async def _require_visible(actor: dict, company_id: str, interview_no: str) -> dict:
    query = {"interview_no": interview_no, "company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    doc = await get_collection(COLL_INTERVIEWS).find_one(query)
    if not doc:
        # 404 rather than 403: a 403 would confirm the interview exists.
        raise HTTPException(status_code=404, detail="Interview not found.")
    return doc


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_interviews(actor: dict, company_id: str, *, status: str = None,
                          round_name: str = None, uk: str = None,
                          limit: int = 200) -> dict:
    query = {"company_id": str(company_id)}
    query.update(await _scope_filter(actor, company_id))
    if status:
        query["status"] = status
    if round_name:
        query["round"] = round_name
    if uk:
        query["uk"] = uk

    limit = max(1, min(int(limit or 200), 500))
    rows = await get_collection(COLL_INTERVIEWS).find(query).sort(
        "scheduled_at", 1).limit(limit).to_list(limit)

    actor_id = str(actor.get("_id") or "")
    now = datetime.now(timezone.utc)
    today = now.date()
    out, stats = [], {"today": 0, "upcoming": 0, "completed": 0, "dropped": 0}

    for r in rows:
        item = _out(r)
        item["is_mine"] = str(r.get("interviewer_id") or "") == actor_id
        # Whether THIS caller may evaluate is decided server-side, so the UI never offers a
        # button the API will refuse.
        item["can_evaluate"] = _may_evaluate(actor, r)
        when = r.get("scheduled_at")
        if isinstance(when, datetime):
            aware = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
            item["day"] = aware.date().isoformat()
            if r.get("status") == InterviewStatus.SCHEDULED.value:
                if aware.date() == today:
                    stats["today"] += 1
                elif aware.date() > today:
                    stats["upcoming"] += 1
        if r.get("status") == InterviewStatus.COMPLETED.value:
            stats["completed"] += 1
        elif r.get("status") in (InterviewStatus.CANCELLED.value,
                                 InterviewStatus.NO_SHOW.value):
            stats["dropped"] += 1
        out.append(item)

    return {"interviews": out, "total": len(out), "stats": stats}


def _may_evaluate(actor: dict, doc: dict) -> bool:
    """Who may score this interview.

    The assigned interviewer, or anyone holding `interview.evaluate` within scope. An MD
    round additionally requires `interview.decide_md` -- the final call is the MD's,
    whoever happens to have conducted the conversation.
    """
    if doc.get("round") == InterviewRound.MD.value and not can(actor, Cap.INTERVIEW_DECIDE_MD):
        return False
    if str(doc.get("interviewer_id") or "") == str(actor.get("_id") or ""):
        return True
    return can(actor, Cap.INTERVIEW_EVALUATE)


async def schedulable_candidates(actor: dict, company_id: str) -> list:
    """Candidates who may be booked for an interview.

    Excludes terminal stages, and any candidate whose role requires an assessment they have
    not yet passed. The picker and the server apply the SAME rule, so the UI cannot offer
    somebody the API will refuse.
    """
    rows = await get_collection(COLL_CANDIDATES).find(
        {"company_id": str(company_id)}).sort("created_at", -1).to_list(1000)
    out = []
    for r in rows:
        status = r.get("application_status")
        if not _is_schedulable(r):
            continue
        out.append({"uk": r["uk"], "candidate_name": r.get("candidate_name"),
                    "application_status": status, "request_no": r.get("request_no"),
                    "requires_assessment": bool(r.get("requires_assessment"))})
    return out


def _is_schedulable(candidate: dict) -> bool:
    status = candidate.get("application_status")
    try:
        current = AppStatus(status)
    except ValueError:
        return False
    if current in (AppStatus.REJECTED, AppStatus.DUPLICATE, AppStatus.OFFER_DECLINED,
                   AppStatus.EMPLOYEE_CREATED):
        return False
    if candidate.get("requires_assessment") and current in PRE_ASSESSMENT_STATUSES:
        return False
    # The lifecycle graph is the final word: an interview only makes sense from a stage that
    # can legally reach Interview Scheduled (or is already in the interview chain).
    return (can_transition(status, AppStatus.INTERVIEW_SCHEDULED.value)
            or current in (AppStatus.INTERVIEW_SCHEDULED, AppStatus.TECHNICAL_ROUND,
                           AppStatus.MD_ROUND))


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def schedule_interview(actor: dict, company_id: str, payload: dict) -> dict:
    uk = (payload.get("uk") or "").strip()
    if not uk:
        raise HTTPException(status_code=422, detail="Select a candidate.")

    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found.")

    status = candidate.get("application_status")
    # THE ASSESSMENT GATE. Enforced here as well as in the picker, because the picker is a
    # convenience and this is the boundary.
    if candidate.get("requires_assessment"):
        try:
            current = AppStatus(status)
        except ValueError:
            current = None
        if current in PRE_ASSESSMENT_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=(f'{candidate.get("candidate_name")} is at "{status}". This role '
                        f'requires an assessment, so interviews can only be scheduled once '
                        f'they reach "{AppStatus.ASSESSMENT_PASSED.value}".'))
    if not _is_schedulable(candidate):
        raise HTTPException(
            status_code=409,
            detail=f'{candidate.get("candidate_name")} is at "{status}" and cannot be interviewed.')

    raw_round = getattr(payload.get("round"), "value", payload.get("round")) \
        or InterviewRound.HR.value
    try:
        round_name = InterviewRound(raw_round).value
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Round must be one of: {', '.join(r.value for r in InterviewRound)}.")

    when = _parse_when(payload.get("scheduled_at"))
    if when < datetime.now(timezone.utc) - timedelta(minutes=1):
        raise HTTPException(
            status_code=422, detail="An interview cannot be scheduled in the past.")

    duration = _validate_duration(payload.get("duration_min"))
    mode, link, location = _validate_place(
        payload.get("mode") or InterviewMode.VIRTUAL, payload.get("meeting_link"),
        payload.get("location"))
    interviewer = await _resolve_interviewer(company_id, payload.get("interviewer_id"))

    year = datetime.now(timezone.utc).year
    interview_no = await next_business_id("interview", str(company_id), year)
    now = datetime.now(timezone.utc)

    doc = {
        "interview_no": interview_no,
        "company_id": str(company_id),
        "uk": uk,
        "candidate_name": candidate.get("candidate_name"),
        "candidate_email": candidate.get("can_email"),
        "request_no": candidate.get("request_no"),
        "round": round_name,
        "mode": mode,
        "scheduled_at": when,
        "duration_min": duration,
        "interviewer_id": str(interviewer["_id"]),
        "interviewer_name": _person_name(interviewer),
        "interviewer_email": interviewer.get("email"),
        "meeting_link": link,
        "location": location,
        "notes": clean_text(payload.get("notes"), limit=2000),
        "status": InterviewStatus.SCHEDULED.value,
        "outcome": None,
        # Incremented on every reschedule so a calendar client treats the new invite as an
        # update to the same booking rather than a second one.
        "ics_sequence": 0,
        "created_by": str(actor.get("_id") or ""),
        "created_at": now,
    }
    await get_collection(COLL_INTERVIEWS).insert_one(dict(doc))

    if can_transition(status, AppStatus.INTERVIEW_SCHEDULED.value):
        await get_collection(COLL_CANDIDATES).update_one(
            {"uk": uk, "company_id": str(company_id)},
            {"$set": {"application_status": AppStatus.INTERVIEW_SCHEDULED.value,
                      "updated_at": now}})
        await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                    f"{status} -> {AppStatus.INTERVIEW_SCHEDULED.value}", company_id)

    await audit(actor, AUDIT_INTERVIEW_SCHEDULED, ENTITY_INTERVIEW, interview_no,
                f"{round_name} for {candidate.get('candidate_name')}", company_id)
    await audit(actor, AUDIT_INTERVIEW_SCHEDULED, ENTITY_CANDIDATE, uk,
                f"{interview_no}: {round_name}", company_id)
    await _notify_scheduled(doc, rescheduled=False)
    return _out(doc)


async def _notify_scheduled(doc: dict, *, rescheduled: bool) -> None:
    verb = "rescheduled" if rescheduled else "scheduled"
    when = doc["scheduled_at"]
    when_text = when.strftime("%d %b %Y, %H:%M UTC") if isinstance(when, datetime) else str(when)
    where = doc.get("meeting_link") or doc.get("location") or ""
    await notify_user(
        doc["interviewer_id"],
        f"Interview {verb}: {doc.get('candidate_name')}",
        f"{doc['round']} on {when_text} ({doc['duration_min']} min). {where}".strip(),
        link="/hrms/interviews", email=True)


def invite_for(doc: dict, *, cancelled: bool = False) -> str:
    """The RFC 5545 invite for one interview."""
    where = doc.get("location") or doc.get("meeting_link") or ""
    description = (f"Round: {doc.get('round')}\n"
                   f"Mode: {doc.get('mode')}\n"
                   f"Interviewer: {doc.get('interviewer_name') or ''}")
    if doc.get("notes"):
        description += f"\nNotes: {doc['notes']}"
    when = doc["scheduled_at"]
    if not isinstance(when, datetime):
        when = _parse_when(str(when))
    return build_invite(
        uid=f"{doc['interview_no']}@sparsh-hrms",
        summary=f"{doc.get('round')}: {doc.get('candidate_name')}",
        start=when,
        duration_min=doc.get("duration_min") or DEFAULT_DURATION_MIN,
        description=description,
        location=where,
        url=doc.get("meeting_link"),
        attendee_emails=[e for e in (doc.get("interviewer_email"),
                                     doc.get("candidate_email")) if e],
        sequence=int(doc.get("ics_sequence") or 0),
        cancelled=cancelled,
    )


async def update_interview(actor: dict, company_id: str, interview_no: str,
                           payload: dict) -> dict:
    """Reschedule, change the venue, or set a status."""
    current = await _require_visible(actor, company_id, interview_no)
    if not (can(actor, Cap.INTERVIEW_SCHEDULE)
            or str(current.get("interviewer_id") or "") == str(actor.get("_id") or "")):
        raise HTTPException(
            status_code=403,
            detail="Only the assigned interviewer or a scheduler can change this interview.")
    if current.get("status") == InterviewStatus.CANCELLED.value:
        raise HTTPException(status_code=409, detail="This interview has been cancelled.")

    updates, rescheduled = {}, False

    if payload.get("scheduled_at") is not None:
        when = _parse_when(payload["scheduled_at"])
        if when < datetime.now(timezone.utc) - timedelta(minutes=1):
            raise HTTPException(
                status_code=422, detail="An interview cannot be moved into the past.")
        if when != current.get("scheduled_at"):
            updates["scheduled_at"] = when
            updates["ics_sequence"] = int(current.get("ics_sequence") or 0) + 1
            updates["status"] = InterviewStatus.SCHEDULED.value
            rescheduled = True

    if payload.get("duration_min") is not None:
        updates["duration_min"] = _validate_duration(payload["duration_min"])

    if payload.get("mode") is not None or payload.get("meeting_link") is not None \
            or payload.get("location") is not None:
        mode = payload.get("mode") or current.get("mode")
        mode, link, location = _validate_place(
            mode,
            payload.get("meeting_link", current.get("meeting_link")),
            payload.get("location", current.get("location")))
        updates.update({"mode": mode, "meeting_link": link, "location": location})

    if payload.get("notes") is not None:
        updates["notes"] = clean_text(payload["notes"], limit=2000)

    if payload.get("status") is not None:
        raw = getattr(payload["status"], "value", payload["status"])
        try:
            new_status = InterviewStatus(raw)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid interview status.")
        if new_status == InterviewStatus.COMPLETED and not current.get("outcome"):
            # Completed without a scorecard would leave the candidate stranded mid-chain
            # with no record of why.
            raise HTTPException(
                status_code=409,
                detail="Record the evaluation to mark this interview completed.")
        updates["status"] = new_status.value

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    await get_collection(COLL_INTERVIEWS).update_one(
        {"interview_no": interview_no, "company_id": str(company_id)}, {"$set": updates})

    action = AUDIT_INTERVIEW_RESCHEDULED if rescheduled else AUDIT_INTERVIEW_UPDATED
    await audit(actor, action, ENTITY_INTERVIEW, interview_no,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)

    fresh = await get_collection(COLL_INTERVIEWS).find_one({"interview_no": interview_no})
    if rescheduled:
        await _notify_scheduled(fresh, rescheduled=True)
    return _out(fresh)


async def cancel_interview(actor: dict, company_id: str, interview_no: str) -> dict:
    """Cancel an interview.

    Marked Cancelled rather than deleted: the fact that a round was booked and dropped is
    part of the hiring record, and Phase 5's journey reads it.
    """
    current = await _require_visible(actor, company_id, interview_no)
    if not can(actor, Cap.INTERVIEW_SCHEDULE):
        raise HTTPException(status_code=403, detail="You may not cancel interviews.")
    if current.get("status") == InterviewStatus.CANCELLED.value:
        raise HTTPException(status_code=409, detail="This interview is already cancelled.")

    await get_collection(COLL_INTERVIEWS).update_one(
        {"interview_no": interview_no, "company_id": str(company_id)},
        {"$set": {"status": InterviewStatus.CANCELLED.value,
                  "ics_sequence": int(current.get("ics_sequence") or 0) + 1,
                  "cancelled_at": datetime.now(timezone.utc)}})
    await audit(actor, AUDIT_INTERVIEW_CANCELLED, ENTITY_INTERVIEW, interview_no,
                current.get("round"), company_id)
    await notify_user(
        current["interviewer_id"], f"Interview cancelled: {current.get('candidate_name')}",
        f"The {current.get('round')} has been cancelled.", kind="warning",
        link="/hrms/interviews", email=True)
    return {"cancelled": True, "interview_no": interview_no}


async def evaluate_interview(actor: dict, company_id: str, interview_no: str,
                             payload: dict) -> dict:
    """Record the scorecard and advance the candidate."""
    current = await _require_visible(actor, company_id, interview_no)

    if current.get("round") == InterviewRound.MD.value and not can(actor, Cap.INTERVIEW_DECIDE_MD):
        raise HTTPException(
            status_code=403,
            detail="Only the MD can record the decision for an MD round.")
    if not _may_evaluate(actor, current):
        raise HTTPException(
            status_code=403,
            detail="Only the assigned interviewer or an authorised evaluator can score this.")
    if current.get("status") == InterviewStatus.CANCELLED.value:
        raise HTTPException(status_code=409, detail="This interview was cancelled.")
    if current.get("outcome"):
        raise HTTPException(
            status_code=409, detail="This interview has already been evaluated.")

    raw = getattr(payload.get("outcome"), "value", payload.get("outcome"))
    try:
        outcome = Outcome(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="Decision must be Pass, Fail or Hold.")

    signature = clean_text(payload.get("signature"), limit=120)
    if not signature:
        # The source left this optional despite the UI implying otherwise
        # (BACKEND_ANALYSIS 8). An unsigned evaluation that later justifies a rejection is
        # exactly the record you want attributable.
        raise HTTPException(
            status_code=422, detail="Type your name to sign this evaluation.")

    scores = {}
    for key in COMPETENCY_KEYS:
        value = payload.get(key, 0)
        try:
            score = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{key}: score must be a whole number.")
        if score < MIN_SCORE or score > MAX_SCORE:
            raise HTTPException(
                status_code=422,
                detail=f"{key}: score must be between {MIN_SCORE} and {MAX_SCORE}.")
        scores[f"score_{key}"] = score

    now = datetime.now(timezone.utc)
    average = round(sum(scores.values()) / len(scores), 2) if scores else 0

    # Conditional on the outcome still being unset: two evaluators submitting at once must
    # not both write.
    result = await get_collection(COLL_INTERVIEWS).update_one(
        {"interview_no": interview_no, "company_id": str(company_id), "outcome": None},
        {"$set": {**scores, "outcome": outcome.value, "average_score": average,
                  "eval_remarks": clean_text(payload.get("remarks"), limit=4000),
                  "eval_signature": signature,
                  "eval_by": str(actor.get("_id") or ""), "eval_by_name": _actor_name(actor),
                  "eval_at": now, "status": InterviewStatus.COMPLETED.value,
                  "updated_at": now}})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409, detail="This interview has already been evaluated.")

    await audit(actor, AUDIT_INTERVIEW_EVALUATED, ENTITY_INTERVIEW, interview_no,
                f"{current.get('round')}: {outcome.value} (avg {average})", company_id)

    await _advance_candidate(actor, company_id, current, outcome)

    fresh = await get_collection(COLL_INTERVIEWS).find_one({"interview_no": interview_no})
    return _out(fresh)


async def _advance_candidate(actor: dict, company_id: str, interview: dict,
                             outcome: Outcome) -> None:
    """Move the candidate per PASS_NEXT, re-checked against the lifecycle graph."""
    uk = interview["uk"]
    candidate = await get_collection(COLL_CANDIDATES).find_one(
        {"uk": uk, "company_id": str(company_id)})
    if not candidate:
        return
    current_status = candidate.get("application_status")

    if outcome == Outcome.PASS:
        try:
            target = PASS_NEXT[InterviewRound(interview.get("round"))]
        except (ValueError, KeyError):
            return
    else:
        target = OUTCOME_STATUS[outcome]

    # Second, independent check: PASS_NEXT says where to go, the graph says whether it is
    # legal from where the candidate actually is.
    if not can_transition(current_status, target.value):
        await audit(actor, AUDIT_INTERVIEW_EVALUATED, ENTITY_CANDIDATE, uk,
                    f"outcome {outcome.value}; stage left at {current_status} "
                    f"(no legal move to {target.value})", company_id)
        return

    await get_collection(COLL_CANDIDATES).update_one(
        {"uk": uk, "company_id": str(company_id)},
        {"$set": {"application_status": target.value,
                  "updated_at": datetime.now(timezone.utc)}})
    await audit(actor, AUDIT_STAGE_CHANGED, ENTITY_CANDIDATE, uk,
                f"{current_status} -> {target.value}", company_id)

    if interview.get("interviewer_id"):
        await notify_user(
            interview["interviewer_id"],
            f"{interview.get('candidate_name')}: {outcome.value}",
            f"The {interview.get('round')} outcome was recorded. "
            f"Candidate is now {target.value}.",
            link="/hrms/candidates")
