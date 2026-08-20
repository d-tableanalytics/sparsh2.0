"""
TPMS ▸ Leadership Score — cycles, subjects, question master and scoring.

    "All leaders should get the score as per parameters they have."

SCORING
-------
For a subject with R submitted responses:

    question mean   avg(q) = mean over responses of the chosen option's score   -> 1..5
    achievement     ach(q) = avg(q) / 5 * 100                                   -> 0..100
    weighted        w(q)   = ach(q) * weightage(q) / 100
    Leadership Score       = sum of w(q)                                        -> 0..100

A question nobody answered is excluded from the total and its weightage reported as
unearned, rather than counted as zero — a giver's omission must not read as a leader's
failure. Weightages are read from the question master on every calculation, so an HR/MD
change takes effect on the next read with no recompute step.

CONFIDENTIALITY
---------------
    "Ye feedback completely confidential hoga."
    "HR should identify feedback givers and it should be only known to HR."

`giver_id` is stored on responses for authorization and duplicate prevention. It is never
returned to a leader or a reporting manager: every score payload is built by
`subject_score()`, which aggregates and never carries an identity, an individual response,
or a per-giver rating. The relation breakdown is computed for HR only and suppresses any
group with fewer than MIN_GROUP_FOR_BREAKDOWN responses, since a group of one would name
the person who filled it.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from bson import ObjectId

from app.db.mongodb import get_collection
from app.models.leadership import (
    COLL_LS_ASSIGNMENTS,
    COLL_LS_CYCLES, COLL_LS_QUESTIONS, COLL_LS_RESPONSES, COLL_LS_SCORES, COLL_LS_SUBJECTS,
    CYCLE_CLOSED, CYCLE_DRAFT, CYCLE_OPEN,
    DEGREE_360, DEGREE_RELATIONS,
    LEVELS, LEVEL_LABELS, LEVEL_THEMES,
    RECOMMENDED_PER_RELATION, RELATIONS, RELATION_LABELS,
    SCALE_MAX, TOTAL_WEIGHTAGE, WEIGHTAGE_EPSILON,
    all_seed_rows, cycle_label, cycle_period, current_cycle, seed_rows_for_level,
)

logger = logging.getLogger(__name__)

# A relation group smaller than this is folded into the total but not broken out, so a
# single response can never be attributed to the one person who gave it.
MIN_GROUP_FOR_BREAKDOWN = 2

PERSON_COLLECTIONS = ("staff", "learners")


def _display_name(u: dict) -> str:
    return (u.get("full_name")
            or " ".join(filter(None, [u.get("first_name"), u.get("last_name")])).strip()
            or u.get("email") or "Unknown")


def _round(v, nd=2):
    return None if v is None else round(float(v), nd)


# ─────────────────────────────────────────────────────────────
# Question master
# ─────────────────────────────────────────────────────────────
async def seed_questions_if_empty() -> int:
    """Insert-only seed of the level question master. Skipped entirely once any row
    exists, so an admin's edits are never overwritten."""
    col = get_collection(COLL_LS_QUESTIONS)
    if await col.count_documents({}) > 0:
        return 0
    rows = all_seed_rows()
    if not rows:
        return 0
    now = datetime.utcnow()
    for r in rows:
        r["created_at"] = now
        r["updated_at"] = now
    try:
        await col.insert_many(rows, ordered=False)
    except Exception as e:
        logger.warning("Leadership question seed: %s", e)
        return 0
    logger.info("Seeded %s leadership questions", len(rows))
    return len(rows)


async def get_questions(level: Optional[str] = None, include_inactive: bool = False) -> List[dict]:
    await seed_questions_if_empty()
    query: dict = {}
    if level:
        query["level"] = str(level).upper()
    if not include_inactive:
        query["active"] = {"$ne": False}
    docs = await get_collection(COLL_LS_QUESTIONS).find(query).sort(
        [("level", 1), ("order", 1)]).to_list(500)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


async def restore_level_questions(level: str) -> dict:
    """Re-insert any seeded question missing from a level. Insert-only: existing rows,
    including their edited text and weightages, are left exactly as they are."""
    level = str(level).upper()
    col = get_collection(COLL_LS_QUESTIONS)
    present = {d.get("item_id") for d in await col.find({"level": level}).to_list(200)}
    missing = [r for r in seed_rows_for_level(level) if r["item_id"] not in present]
    if missing:
        now = datetime.utcnow()
        for r in missing:
            r["created_at"] = now
            r["updated_at"] = now
        await col.insert_many(missing, ordered=False)
    return {"level": level, "restored": len(missing)}


async def update_question(question_id: str, updates: dict) -> bool:
    fields = {k: v for k, v in updates.items() if v is not None}
    if not fields:
        return False
    fields["updated_at"] = datetime.utcnow()
    res = await get_collection(COLL_LS_QUESTIONS).update_one(
        {"_id": ObjectId(str(question_id))}, {"$set": fields})
    return res.matched_count > 0


async def set_weightages(level: str, weightages: Dict[str, float]) -> dict:
    """Write a level's weightage column. Totalling to 100 is validated by the payload
    model and re-checked here so a direct service call cannot bypass it."""
    level = str(level).upper()
    total = round(sum(weightages.values()), 2)
    if abs(total - TOTAL_WEIGHTAGE) > WEIGHTAGE_EPSILON:
        raise ValueError(
            f"Total weightage must be exactly {TOTAL_WEIGHTAGE:g}% (currently {total:g}%)")

    col = get_collection(COLL_LS_QUESTIONS)
    known = {d.get("item_id") for d in await col.find({"level": level}).to_list(200)}
    unknown = [i for i in weightages if i not in known]
    if unknown:
        raise ValueError(f"Unknown question(s) for {level}: {', '.join(unknown)}")

    now = datetime.utcnow()
    for item_id, w in weightages.items():
        await col.update_one({"level": level, "item_id": item_id},
                             {"$set": {"weightage": round(float(w), 2), "updated_at": now}})
    return {"level": level, "updated": len(weightages), "total": total}


async def weightage_summary() -> List[dict]:
    """Per-level totals, so the admin screen can flag a level that does not add to 100."""
    await seed_questions_if_empty()
    out = []
    for level in LEVELS:
        rows = await get_collection(COLL_LS_QUESTIONS).find(
            {"level": level, "active": {"$ne": False}}).to_list(200)
        total = round(sum(float(r.get("weightage") or 0) for r in rows), 2)
        out.append({
            "level": level,
            "label": LEVEL_LABELS.get(level, level),
            "theme": LEVEL_THEMES.get(level, ""),
            "questions": len(rows),
            "total_weightage": total,
            "is_valid": abs(total - TOTAL_WEIGHTAGE) <= WEIGHTAGE_EPSILON,
        })
    return out


# ─────────────────────────────────────────────────────────────
# Cycles
# ─────────────────────────────────────────────────────────────
async def list_cycles(company_id: str, limit: int = 50) -> List[dict]:
    from app.services.leadership_link_service import cycle_is_expired

    docs = await get_collection(COLL_LS_CYCLES).find(
        {"company_id": str(company_id)}).sort("cycle", -1).to_list(limit)
    out = []
    for d in docs:
        d["_id"] = str(d["_id"])
        d["label"] = cycle_label(d.get("cycle") or "")
        d["subject_count"] = await get_collection(COLL_LS_SUBJECTS).count_documents(
            {"company_id": str(company_id), "cycle": d.get("cycle")})
        d["response_count"] = await get_collection(COLL_LS_RESPONSES).count_documents(
            {"company_id": str(company_id), "cycle": d.get("cycle")})
        # Additive: lets the UI disable dispatch without re-deriving the window in JS, and
        # mirrors exactly what assert_dispatchable enforces server-side.
        d["expired"] = cycle_is_expired(d.get("cycle") or "")
        d["can_dispatch"] = d.get("status") != CYCLE_CLOSED and not d["expired"]
        out.append(d)
    return out


async def get_cycle(company_id: str, cycle: str) -> Optional[dict]:
    doc = await get_collection(COLL_LS_CYCLES).find_one(
        {"company_id": str(company_id), "cycle": str(cycle)})
    if doc:
        doc["_id"] = str(doc["_id"])
        doc["label"] = cycle_label(doc.get("cycle") or "")
    return doc


async def assert_dispatchable(company_id: str, cycle: str) -> dict:
    """Raise unless invitations may still be sent for this cycle.

    Two independent reasons to refuse, both server-side so a stale browser tab or a direct
    API call cannot bypass them:

      • the cycle is CLOSED — its scores are frozen, so collecting more feedback would
        change nothing and would invite people to a form that no longer counts;
      • the cycle's window has ELAPSED — every link expires with the window, so the mail
        would deliver a URL that answers 410 the moment it is clicked.

    Returns the cycle document, so callers do not fetch it twice.
    """
    from app.services.leadership_link_service import cycle_expiry_utc, cycle_is_expired

    cyc = await get_cycle(company_id, cycle)
    if not cyc:
        raise ValueError("This cycle does not exist")
    if cyc.get("status") == CYCLE_CLOSED:
        raise ValueError(
            f"{cycle_label(cycle)} is closed. Its scores are final, so invitations and "
            "reminders can no longer be sent.")
    if cycle_is_expired(cycle):
        expiry = cycle_expiry_utc(cycle)
        raise ValueError(
            f"The {cycle_label(cycle)} window ended on "
            f"{expiry.strftime('%d %b %Y') if expiry else 'its closing date'}. "
            "Feedback links have expired, so nothing further can be sent.")
    return cyc


async def panel_shortfall(company_id: str, cycle: str, subject_id: str) -> Dict[str, int]:
    """How many givers each relation is still short of, for one leader's panel.

    The document is specific about who is asked: "hum aapke 8 logon se feedback lenge — 2
    superiors, 2 peers, 2 other departments, aur 2 direct reports". That is not decoration.
    A single superior's rating IS that superior's opinion, and a leader reading a 360° score
    built from two juniors is reading something the label does not describe.

    Returns {relation: missing} for every relation the cycle's degree collects. An empty
    dict means the panel is complete. Reporting the shortfall rather than a bare boolean
    lets the caller tell HR exactly who is still needed.
    """
    cyc = await get_cycle(company_id, cycle)
    wanted = DEGREE_RELATIONS.get((cyc or {}).get("degree") or DEGREE_360, RELATIONS)

    rows = await get_collection(COLL_LS_ASSIGNMENTS).find({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id),
    }).to_list(500)

    have: Dict[str, int] = {}
    for r in rows:
        rel = str(r.get("relation") or "")
        have[rel] = have.get(rel, 0) + 1

    return {rel: RECOMMENDED_PER_RELATION - have.get(rel, 0)
            for rel in wanted
            if have.get(rel, 0) < RECOMMENDED_PER_RELATION}


def describe_shortfall(missing: Dict[str, int]) -> str:
    """'2 x Supervisor, 1 x Junior / Direct report' — for an error a human reads.

    Counted rather than pluralised: the labels already carry parentheses ("Peer (same
    department)"), and appending an "s" to those reads as a typo.
    """
    return ", ".join(f"{n} x {RELATION_LABELS.get(rel, rel)}" for rel, n in missing.items())


async def incomplete_panels(company_id: str, cycle: str) -> Dict[str, dict]:
    """{subject_id: {name, missing, summary}} for every enrolled leader whose panel is short.

    Used by the cycle-wide dispatch, which mails the leaders that ARE ready and reports the
    rest rather than refusing the whole batch — one unfinished panel should not hold up
    seven finished ones.
    """
    out: Dict[str, dict] = {}
    for s in await get_collection(COLL_LS_SUBJECTS).find({
        "company_id": str(company_id), "cycle": str(cycle),
    }).to_list(500):
        sid = str(s.get("subject_id"))
        missing = await panel_shortfall(company_id, cycle, sid)
        if missing:
            out[sid] = {"subject_name": s.get("subject_name") or sid,
                        "missing": missing,
                        "summary": describe_shortfall(missing)}
    return out


async def create_cycle(company_id: str, payload, user: dict) -> dict:
    cycle = str(payload.cycle or current_cycle())
    cycle_label(cycle)  # validates the code shape; raises ValueError on nonsense
    existing = await get_collection(COLL_LS_CYCLES).find_one(
        {"company_id": str(company_id), "cycle": cycle})
    if existing:
        raise ValueError(f"A cycle already exists for {cycle_label(cycle)}")

    now = datetime.utcnow()
    doc = {
        "company_id": str(company_id),
        "cycle": cycle,
        "period": cycle_period(cycle),
        "degree": payload.degree,
        "min_responses": int(payload.min_responses or 1),
        "status": CYCLE_DRAFT,
        "notes": payload.notes or "",
        "created_by": _display_name(user),
        "created_by_id": str(user.get("_id") or ""),
        "created_at": now,
        "updated_at": now,
        "closed_at": None,
    }
    await get_collection(COLL_LS_CYCLES).insert_one(doc)
    await seed_questions_if_empty()
    doc["_id"] = str(doc.get("_id", ""))
    doc["label"] = cycle_label(cycle)
    return doc


async def update_cycle(company_id: str, cycle: str, updates: dict, user: dict) -> dict:
    fields = {k: v for k, v in updates.items() if v is not None}
    if not fields:
        raise ValueError("Nothing to update")

    # Closing a cycle freezes its scores so history can never silently move afterwards.
    closing = fields.get("status") == CYCLE_CLOSED
    fields["updated_at"] = datetime.utcnow()
    if closing:
        fields["closed_at"] = datetime.utcnow()

    res = await get_collection(COLL_LS_CYCLES).update_one(
        {"company_id": str(company_id), "cycle": str(cycle)}, {"$set": fields})
    if res.matched_count == 0:
        raise ValueError("Cycle not found")

    if closing:
        await snapshot_cycle_scores(company_id, cycle)
    return await get_cycle(company_id, cycle)


# ─────────────────────────────────────────────────────────────
# Subjects (the leaders being rated)
# ─────────────────────────────────────────────────────────────
async def _find_person(person_id: str, company_id: str) -> Optional[dict]:
    try:
        oid = ObjectId(str(person_id))
    except Exception:
        return None
    for coll in PERSON_COLLECTIONS:
        doc = await get_collection(coll).find_one({"_id": oid})
        if doc and str(doc.get("company_id") or "") == str(company_id):
            return doc
    return None


async def list_company_people(company_id: str) -> List[dict]:
    """The company's active roster — the pool HR picks leaders and givers from."""
    people = []
    query = {"company_id": str(company_id), "is_active": {"$ne": False}}
    for coll in PERSON_COLLECTIONS:
        for u in await get_collection(coll).find(query).to_list(2000):
            people.append({
                "person_id": str(u["_id"]),
                "name": _display_name(u),
                "email": u.get("email"),
                "designation": u.get("designation"),
                "department": u.get("department"),
                "reporting_manager": u.get("reporting_manager"),
            })
    people.sort(key=lambda p: (p.get("name") or "").lower())
    return people


async def list_subjects(company_id: str, cycle: str) -> List[dict]:
    from app.services.leadership_link_service import effective_status

    subjects = await get_collection(COLL_LS_SUBJECTS).find(
        {"company_id": str(company_id), "cycle": str(cycle)}).to_list(500)

    assignments = await get_collection("tpms_leadership_assignments").find(
        {"company_id": str(company_id), "cycle": str(cycle)}).to_list(4000)
    by_subject: Dict[str, list] = {}
    for a in assignments:
        by_subject.setdefault(str(a.get("subject_id")), []).append(a)

    now = datetime.now(timezone.utc)
    out = []
    for s in subjects:
        s["_id"] = str(s["_id"])
        panel = by_subject.get(str(s.get("subject_id")), [])
        s["panel_size"] = len(panel)
        s["submitted_count"] = len([p for p in panel if p.get("status") == "submitted"])
        s["pending_count"] = len([p for p in panel
                                  if effective_status(p, now) in ("sent", "opened")])
        s["level_label"] = LEVEL_LABELS.get(s.get("level") or "", s.get("level") or "")
        out.append(s)
    out.sort(key=lambda x: (x.get("subject_name") or "").lower())
    return out


async def add_subject(company_id: str, cycle: str, subject_id: str, level: str,
                      user: dict) -> dict:
    person = await _find_person(subject_id, company_id)
    if not person:
        raise ValueError("That person is not on this company's roster")

    questions = await get_questions(level)
    if not questions:
        raise ValueError(f"No active questions configured for {level}")

    existing = await get_collection(COLL_LS_SUBJECTS).find_one({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})
    if existing:
        raise ValueError("This leader is already enrolled in this cycle")

    now = datetime.utcnow()
    # Snapshot name/designation/level so a later promotion or rename cannot retro-change
    # a closed cycle's record.
    doc = {
        "company_id": str(company_id),
        "cycle": str(cycle),
        "period": cycle_period(cycle),
        "subject_id": str(subject_id),
        "subject_name": _display_name(person),
        "designation": person.get("designation") or "",
        "department": person.get("department") or "",
        "reporting_manager": str(person.get("reporting_manager") or ""),
        "level": str(level).upper(),
        "enrolled_by": _display_name(user),
        "enrolled_by_id": str(user.get("_id") or ""),
        "created_at": now,
        "updated_at": now,
    }
    await get_collection(COLL_LS_SUBJECTS).insert_one(doc)
    doc["_id"] = str(doc.get("_id", ""))
    return doc


async def get_subject(company_id: str, cycle: str, subject_id: str) -> Optional[dict]:
    doc = await get_collection(COLL_LS_SUBJECTS).find_one({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def remove_subject(company_id: str, cycle: str, subject_id: str) -> dict:
    """Un-enrol a leader who has collected no feedback yet. Once any response exists the
    subject stays — deleting would destroy collected feedback."""
    responses = await get_collection(COLL_LS_RESPONSES).count_documents({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})
    if responses:
        raise ValueError("Feedback has already been submitted for this leader; they cannot be removed")

    await get_collection("tpms_leadership_assignments").delete_many({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})
    res = await get_collection(COLL_LS_SUBJECTS).delete_one({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})
    return {"removed": res.deleted_count}


async def set_panel(company_id: str, cycle: str, subject_id: str,
                    givers: List, user: dict) -> dict:
    """Set a subject's feedback panel and mint a link for each member.

    Members already holding a link keep it (and their submitted feedback). Members dropped
    from the list lose their unsubmitted link. Nothing already submitted is ever removed.
    """
    from app.services.leadership_link_service import create_assignment, remove_assignment

    subject = await get_subject(company_id, cycle, subject_id)
    if not subject:
        raise ValueError("This leader is not enrolled in this cycle")

    cyc = await get_cycle(company_id, cycle)
    allowed = set(DEGREE_RELATIONS.get((cyc or {}).get("degree") or DEGREE_360, RELATIONS))

    company = None
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(str(company_id))})
    except Exception:
        company = None
    company_name = (company or {}).get("name") or ""

    wanted: Dict[str, str] = {}
    for g in givers:
        if g.relation not in allowed:
            raise ValueError(
                f"{RELATION_LABELS.get(g.relation, g.relation)} is not collected in a "
                f"{(cyc or {}).get('degree', DEGREE_360)}° cycle")
        if str(g.giver_id) == str(subject_id):
            raise ValueError("A leader cannot be on their own feedback panel")
        person = await _find_person(g.giver_id, company_id)
        if not person:
            raise ValueError("A selected feedback giver is not on this company's roster")
        wanted[str(g.giver_id)] = g.relation

    created = 0
    for giver_id, relation in wanted.items():
        person = await _find_person(giver_id, company_id)
        await create_assignment(
            company_id=company_id, company_name=company_name, cycle=cycle,
            subject=subject, giver=person, relation=relation, assigned_by=user)
        created += 1

    # Drop anyone no longer on the panel (unsubmitted only).
    existing = await get_collection("tpms_leadership_assignments").find({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id),
    }).to_list(500)
    removed = 0
    for row in existing:
        if str(row.get("giver_id")) not in wanted:
            if await remove_assignment(company_id, cycle, subject_id, row.get("giver_id")):
                removed += 1

    return {"panel_size": created, "removed": removed}


# ─────────────────────────────────────────────────────────────
# Response capture
# ─────────────────────────────────────────────────────────────
async def record_response(assignment: dict, answers: List) -> dict:
    """Store one giver's completed form.

    Validates every (question, option) pair against the live master for the SUBJECT's
    level, so a client cannot post a score the rubric does not offer — the document's
    option scores are 1, 2, 4 and 5, and nothing else is accepted.
    """
    level = str(assignment.get("subject_level") or "").upper()
    questions = {q["item_id"]: q for q in await get_questions(level)}
    if not questions:
        raise ValueError(f"No active questions configured for {level}")

    stored: Dict[str, dict] = {}
    for a in answers:
        q = questions.get(a.question_id)
        if not q:
            raise ValueError(f"Unknown question '{a.question_id}' for {level}")
        option = next((o for o in (q.get("options") or [])
                       if str(o.get("option_id")) == str(a.option_id)), None)
        if not option:
            raise ValueError(f"Unknown option '{a.option_id}' for question '{a.question_id}'")
        stored[a.question_id] = {
            "option_id": option["option_id"],
            "option_label": option.get("label", ""),
            "score": float(option.get("score") or 0),
        }

    if not stored:
        raise ValueError("No valid answers supplied")

    now = datetime.utcnow()
    key = {
        "company_id": str(assignment.get("company_id")),
        "cycle": str(assignment.get("cycle")),
        "subject_id": str(assignment.get("subject_id")),
        "giver_id": str(assignment.get("giver_id")),
    }
    await get_collection(COLL_LS_RESPONSES).update_one(
        key,
        {"$set": {
            **key,
            "period": assignment.get("period"),
            "subject_level": level,
            # Relation is kept for the HR-only breakdown; never returned to a leader.
            "relation": assignment.get("relation"),
            "answers": stored,
            "submitted_at": now,
            "updated_at": now,
        },
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"saved": len(stored)}


async def has_responded(assignment: dict) -> bool:
    return bool(await get_collection(COLL_LS_RESPONSES).find_one({
        "company_id": str(assignment.get("company_id")),
        "cycle": str(assignment.get("cycle")),
        "subject_id": str(assignment.get("subject_id")),
        "giver_id": str(assignment.get("giver_id")),
    }))


# ─────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────
def _score_answers(responses: List[dict], questions: List[dict]) -> dict:
    """The weighted calculation, over an already-selected set of responses."""
    parameters = []
    total = 0.0
    applicable = 0.0

    for q in questions:
        item_id = q["item_id"]
        weightage = float(q.get("weightage") or 0)
        scores = [
            float((r.get("answers") or {}).get(item_id, {}).get("score"))
            for r in responses
            if (r.get("answers") or {}).get(item_id, {}).get("score") is not None
        ]

        if scores:
            avg = sum(scores) / len(scores)
            achievement = avg / SCALE_MAX * 100
            weighted = achievement * weightage / 100
            total += weighted
            applicable += weightage
        else:
            avg = achievement = weighted = None

        parameters.append({
            "item_id": item_id,
            "title": q.get("title", ""),
            "prompt": q.get("prompt", ""),
            "weightage": _round(weightage),
            "max_score": _round(weightage),
            "average_rating": _round(avg),          # 1..5
            "achievement": _round(achievement),     # 0..100
            "weighted_score": _round(weighted or 0),
            "answered_by": len(scores),
            "has_data": bool(scores),
        })

    return {
        "parameters": parameters,
        "leadership_score": _round(total),
        "applicable_weightage": _round(applicable),
        "unearned_weightage": _round(round(sum(p["weightage"] for p in parameters), 2) - applicable),
        "score_on_applicable": _round(total / applicable * 100) if applicable else None,
    }


async def subject_score(company_id: str, cycle: str, subject_id: str,
                        include_relations: bool = False) -> dict:
    """One leader's Leadership Score for one cycle.

    NEVER includes giver identity or individual responses. `include_relations` adds the
    per-relation breakdown and is passed True only for HR/staff — and even then a group
    with fewer than MIN_GROUP_FOR_BREAKDOWN responses is withheld.
    """
    subject = await get_subject(company_id, cycle, subject_id)
    if not subject:
        raise ValueError("This leader is not enrolled in this cycle")

    cyc = await get_cycle(company_id, cycle) or {}
    min_responses = int(cyc.get("min_responses") or 1)

    questions = await get_questions(subject.get("level"))
    responses = await get_collection(COLL_LS_RESPONSES).find({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id),
    }).to_list(200)

    panel_size = await get_collection("tpms_leadership_assignments").count_documents({
        "company_id": str(company_id), "cycle": str(cycle), "subject_id": str(subject_id)})

    head = {
        "company_id": str(company_id),
        "cycle": str(cycle),
        "cycle_label": cycle_label(cycle),
        "period": cycle_period(cycle),
        "subject_id": str(subject_id),
        "subject_name": subject.get("subject_name"),
        "designation": subject.get("designation"),
        "department": subject.get("department"),
        "level": subject.get("level"),
        "level_label": LEVEL_LABELS.get(subject.get("level") or "", subject.get("level") or ""),
        "level_theme": LEVEL_THEMES.get(subject.get("level") or "", ""),
        "response_count": len(responses),
        "panel_size": panel_size,
        "min_responses": min_responses,
        "degree": cyc.get("degree"),
        "cycle_status": cyc.get("status"),
    }

    if len(responses) < min_responses:
        # Below the configured threshold nothing is computed at all — there is no partial
        # number to leak and no breakdown to attribute.
        return {
            **head,
            "state": "awaiting_responses",
            "parameters": [],
            "leadership_score": None,
        }

    result = _score_answers(responses, questions)
    payload = {**head, "state": "scored", **result}

    if include_relations:
        breakdown = []
        for rel in RELATIONS:
            group = [r for r in responses if str(r.get("relation") or "") == rel]
            if len(group) < MIN_GROUP_FOR_BREAKDOWN:
                # Withheld rather than shown: a group of one names its author.
                breakdown.append({
                    "relation": rel,
                    "relation_label": RELATION_LABELS[rel],
                    "response_count": len(group),
                    "leadership_score": None,
                    "withheld": True,
                })
                continue
            g = _score_answers(group, questions)
            breakdown.append({
                "relation": rel,
                "relation_label": RELATION_LABELS[rel],
                "response_count": len(group),
                "leadership_score": g["leadership_score"],
                "withheld": False,
            })
        payload["by_relation"] = breakdown

    return payload


async def cycle_scores(company_id: str, cycle: str, include_relations: bool = False) -> dict:
    """Every enrolled leader's score for a cycle."""
    subjects = await get_collection(COLL_LS_SUBJECTS).find({
        "company_id": str(company_id), "cycle": str(cycle)}).to_list(500)

    rows = []
    for s in subjects:
        try:
            rows.append(await subject_score(company_id, cycle, s.get("subject_id"),
                                            include_relations=include_relations))
        except ValueError:
            continue

    scored = [r for r in rows if r.get("leadership_score") is not None]
    rows.sort(key=lambda r: (r.get("leadership_score") is not None,
                             r.get("leadership_score") or 0), reverse=True)

    cyc = await get_cycle(company_id, cycle) or {}
    return {
        "company_id": str(company_id),
        "cycle": str(cycle),
        "cycle_label": cycle_label(cycle),
        "status": cyc.get("status"),
        "degree": cyc.get("degree"),
        "rows": rows,
        "summary": {
            "leaders": len(rows),
            "scored": len(scored),
            "average_score": _round(sum(r["leadership_score"] for r in scored) / len(scored))
            if scored else None,
            "highest": scored[0]["leadership_score"] if scored else None,
            "lowest": scored[-1]["leadership_score"] if scored else None,
        },
    }


async def snapshot_cycle_scores(company_id: str, cycle: str) -> dict:
    """Freeze a closed cycle's scores into COLL_LS_SCORES for history.

    Writes only into the Leadership Score collections — responses are left untouched.
    """
    result = await cycle_scores(company_id, cycle, include_relations=True)
    now = datetime.utcnow()
    col = get_collection(COLL_LS_SCORES)
    for row in result["rows"]:
        await col.update_one(
            {"company_id": str(company_id), "cycle": str(cycle),
             "subject_id": row["subject_id"]},
            {"$set": {**row, "computed_at": now}},
            upsert=True,
        )
    logger.info("Leadership scores snapshotted: %s rows [company=%s cycle=%s]",
                len(result["rows"]), company_id, cycle)
    return {"snapshotted": len(result["rows"]), "cycle": cycle}


async def subject_history(company_id: str, subject_id: str, limit: int = 12) -> List[dict]:
    """A leader's score across past cycles — the trend an RRO conversation builds on."""
    enrolments = await get_collection(COLL_LS_SUBJECTS).find({
        "company_id": str(company_id), "subject_id": str(subject_id),
    }).sort("cycle", -1).to_list(limit)

    out = []
    for e in enrolments:
        try:
            s = await subject_score(company_id, e.get("cycle"), subject_id)
        except ValueError:
            continue
        out.append({
            "cycle": s["cycle"],
            "cycle_label": s["cycle_label"],
            "level": s["level"],
            "leadership_score": s.get("leadership_score"),
            "response_count": s.get("response_count"),
            "state": s.get("state"),
        })
    return out
