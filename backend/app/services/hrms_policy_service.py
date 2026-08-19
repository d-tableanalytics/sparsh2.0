"""HRMS > the policy register and its review cycle (SOP §14).

"This policy shall be reviewed annually, or earlier if statutory or business requirements
change. All amendments shall be logged in the Modification History table."

-- Why a register rather than a document ------------------------------------------------------
The policy document itself lives wherever documents live -- it is a PDF in the register, and
`document_id` points at it. What could not be answered before this phase was everything
AROUND it:

    which version is actually in force?
    when is it next due to be looked at?
    what changed last time, who asked for it, and who approved it?

A file in a folder answers none of those. A dated register answers all three, and the third
is the "Modification History table" §14 asks for by name.

-- Approval is what makes a version the one in force ------------------------------------------
A revision is DRAFTED (`policy.write`, HR) and APPROVED (`policy.approve`, MD only). Drafting
one changes nothing about which version governs; the approval is the act. That split is the
same one the requisition chain, the scorecard and the exception log all draw, and for the
same reason -- the person who writes a change is not the person who decides it applies.

-- The review cycle is announced, not enforced -------------------------------------------------
A policy inside POLICY_REVIEW_NOTICE_DAYS of its review date notifies the MD and HR. An
overdue one appears on the dashboard as a governance warning. Nothing is BLOCKED by an
overdue review, and that is deliberate: refusing to hire because a policy review slipped
would punish the wrong people for the wrong thing, and would guarantee the register gets
worked around.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_POLICY_APPROVED, AUDIT_POLICY_REGISTERED, AUDIT_POLICY_REVISED, COLL_POLICIES,
    COLL_POLICY_REVISIONS, DEFAULT_POLICIES, ENTITY_POLICY, POLICY_REVIEW_MONTHS,
    POLICY_REVIEW_NOTICE_DAYS, PolicyStatus, is_iso_date,
)
from app.services.hrms_audit_service import audit
from app.utils.hrms_public_guard import clean_text

POLICY_KEY_MAX = 60


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _actor_name(actor: Optional[dict]) -> str:
    actor = actor or {}
    return (actor.get("full_name")
            or f"{actor.get('first_name') or ''} {actor.get('last_name') or ''}".strip()
            or actor.get("email") or "system")


def _add_months(iso_date: str, months: int) -> str:
    """`iso_date` plus N calendar months, clamped to the end of the target month.

    Same arithmetic, and the same reasoning, as hrms_probation_service._add_months: 31
    January plus twelve months is 31 January, and 29 February plus twelve is 28 February --
    never 1 March.
    """
    try:
        year, month, day = (int(p) for p in str(iso_date)[:10].split("-"))
    except (ValueError, TypeError):
        return iso_date
    total = (year * 12) + (month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last_day = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return f"{year:04d}-{month:02d}-{min(day, last_day):02d}"


def _days_until(target: str) -> Optional[int]:
    """Whole days from today to `target`. Negative when it has passed. Pure-ish."""
    try:
        due = datetime.strptime(str(target)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return (due.date() - datetime.now(timezone.utc).date()).days


def _review_state(doc: dict) -> dict:
    """Where a policy sits in its review cycle. DERIVED on read, never stored.

    A stored "overdue" flag would be wrong for a day after every review, and the review is
    the case that matters -- the same reasoning `budget_status` and `effective_link_status`
    already follow.
    """
    days = _days_until(doc.get("next_review_due"))
    if days is None:
        return {"days_until_review": None, "review_status": "unscheduled",
                "review_note": "No review date has been set for this policy."}
    if days < 0:
        return {"days_until_review": days, "review_status": "overdue",
                "review_note": f"The annual review is {abs(days)} day(s) overdue."}
    if days <= POLICY_REVIEW_NOTICE_DAYS:
        return {"days_until_review": days, "review_status": "due_soon",
                "review_note": f"Due for review in {days} day(s)."}
    return {"days_until_review": days, "review_status": "current",
            "review_note": None}


# =============================================================
# Read
# =============================================================
async def list_policies(company_id: str, *, include_withdrawn: bool = False) -> dict:
    """The register, seeding the two policies this module implements on first read.

    Seeded on READ, exactly as document types, communication templates and surveys are: a
    company gets a register that is not empty without anybody remembering to run something.
    """
    coll = get_collection(COLL_POLICIES)
    if not await coll.count_documents({"company_id": str(company_id)}):
        await _seed_policies(company_id)

    query = {"company_id": str(company_id)}
    if not include_withdrawn:
        query["status"] = {"$ne": PolicyStatus.WITHDRAWN.value}
    rows = await coll.find(query).sort("policy_key", 1).to_list(100)
    out = [{**_out(r), **_review_state(r)} for r in rows]
    return {
        "policies": out,
        "total": len(out),
        # The two counts a governance dashboard leads with.
        "overdue": sum(1 for r in out if r["review_status"] == "overdue"),
        "due_soon": sum(1 for r in out if r["review_status"] == "due_soon"),
    }


async def _seed_policies(company_id: str) -> None:
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    for policy_key, title, version, owner_role in DEFAULT_POLICIES:
        try:
            await get_collection(COLL_POLICIES).insert_one({
                "company_id": str(company_id),
                "policy_key": policy_key,
                "title": title,
                "version": version,
                "effective_date": today,
                "owner_role": owner_role.value,
                "status": PolicyStatus.IN_FORCE.value,
                "next_review_due": _add_months(today, POLICY_REVIEW_MONTHS),
                "document_id": None,
                "seeded": True,
                "created_at": now,
            })
        except Exception as e:
            print(f"[WARN] HRMS policy seeding skipped for {company_id}/{policy_key}: {e}")


async def get_policy(company_id: str, policy_key: str) -> Optional[dict]:
    await list_policies(company_id, include_withdrawn=True)      # seed on first touch
    doc = await get_collection(COLL_POLICIES).find_one(
        {"company_id": str(company_id), "policy_key": policy_key})
    if not doc:
        return None
    revisions = await get_collection(COLL_POLICY_REVISIONS).find(
        {"company_id": str(company_id), "policy_key": policy_key}).sort(
        "changed_at", -1).to_list(200)
    return {**_out(doc), **_review_state(doc),
            # SOP §14's "Modification History table", newest first.
            "revisions": [_out(r) for r in revisions]}


async def due_reviews(company_id: str, *,
                      within_days: int = POLICY_REVIEW_NOTICE_DAYS) -> dict:
    """Policies overdue for review, and those falling due inside the window.

    Split rather than merged, the same way `GET /probation/due` splits: a missed commitment
    and a diary entry are two different conversations.
    """
    listing = await list_policies(company_id)
    overdue = [p for p in listing["policies"] if p["review_status"] == "overdue"]
    soon = [p for p in listing["policies"]
            if p["review_status"] == "due_soon"
            and (p["days_until_review"] or 0) <= within_days]
    return {"overdue": overdue, "due_soon": soon,
            "total": len(overdue) + len(soon),
            "within_days": within_days, "as_of": _today()}


async def notify_due_reviews(actor: Optional[dict], company_id: str) -> dict:
    """Tell the MD and HR about reviews falling due.

    Driven WEEKLY by `hrms_scheduler_service` (Phase INT-3). Weekly rather than daily
    because this one has no per-record guard of its own -- an annual review that is due
    stays due, so a daily job would repeat the same notice every morning until somebody
    acted, which is how a governance alert becomes noise.

    Deliberately not fired from an HTTP request: that would make governance alerting depend
    on somebody opening a screen.
    """
    due = await due_reviews(company_id)
    if not due["total"]:
        return {"notified": 0, **due}

    from app.services.hrms_notify_service import notify_hrms_role
    lines = [f'{p["title"]} v{p["version"]} — {p["review_note"]}'
             for p in due["overdue"] + due["due_soon"]]
    await notify_hrms_role(
        company_id, ["MD", "HR"],
        f'{due["total"]} recruitment policy review(s) due',
        "\n".join(lines), kind="warning", link="/hrms/policies", email=True)
    return {"notified": due["total"], **due}


# =============================================================
# Write
# =============================================================
async def register_policy(actor: dict, company_id: str, payload: dict) -> dict:
    """Add a policy to the register."""
    policy_key = clean_text(payload.get("policy_key"), limit=POLICY_KEY_MAX)
    if not policy_key:
        raise HTTPException(status_code=422, detail="A policy needs a key.")
    policy_key = policy_key.strip().lower().replace(" ", "_")

    title = clean_text(payload.get("title"), limit=200)
    if not title:
        raise HTTPException(status_code=422, detail="A policy needs a title.")

    coll = get_collection(COLL_POLICIES)
    if await coll.find_one({"company_id": str(company_id), "policy_key": policy_key}):
        raise HTTPException(
            status_code=409,
            detail=(f"'{policy_key}' is already in the register. Log a REVISION against it "
                    f"rather than registering it twice -- two rows for one policy means two "
                    f"answers to which version is in force."))

    effective = payload.get("effective_date") or _today()
    if not is_iso_date(effective):
        raise HTTPException(
            status_code=422, detail="The effective date must be a valid YYYY-MM-DD date.")
    review_due = payload.get("next_review_due") or _add_months(
        effective, POLICY_REVIEW_MONTHS)
    if not is_iso_date(review_due):
        raise HTTPException(
            status_code=422, detail="The review date must be a valid YYYY-MM-DD date.")

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id),
        "policy_key": policy_key,
        "title": title,
        "version": clean_text(payload.get("version"), limit=20) or "1.0",
        "effective_date": effective,
        "owner_role": clean_text(payload.get("owner_role"), limit=40),
        "status": PolicyStatus.IN_FORCE.value,
        "next_review_due": review_due,
        "document_id": clean_text(payload.get("document_id"), limit=40),
        "seeded": False,
        "registered_by": str(actor.get("_id") or ""),
        "registered_by_name": _actor_name(actor),
        "created_at": now,
    }
    await coll.insert_one(dict(doc))
    await audit(actor, AUDIT_POLICY_REGISTERED, ENTITY_POLICY, policy_key,
                f'{title} v{doc["version"]}', company_id)
    return {**_out(doc), **_review_state(doc)}


async def log_revision(actor: dict, company_id: str, policy_key: str,
                       payload: dict) -> dict:
    """Record an amendment. It does NOT come into force until it is approved.

    That separation is the point. Anybody with `policy.write` may draft "v1.1: added a
    clause about panel composition"; until the MD approves it, the register still says v1.0
    is what governs. A revision that took effect the moment somebody typed it would make the
    approval capability decorative.
    """
    policy = await get_collection(COLL_POLICIES).find_one(
        {"company_id": str(company_id), "policy_key": policy_key})
    if not policy:
        raise HTTPException(status_code=404, detail="That policy is not in the register.")

    version = clean_text(payload.get("version"), limit=20)
    if not version:
        raise HTTPException(status_code=422, detail="A revision needs a version number.")
    summary = clean_text(payload.get("summary_of_change"), limit=4000)
    if not summary:
        raise HTTPException(
            status_code=422,
            detail=("Say what changed. A modification history that does not say what was "
                    "modified is a list of dates."))

    effective = payload.get("effective_date") or _today()
    if not is_iso_date(effective):
        raise HTTPException(
            status_code=422, detail="The effective date must be a valid YYYY-MM-DD date.")

    coll = get_collection(COLL_POLICY_REVISIONS)
    if await coll.find_one({"company_id": str(company_id), "policy_key": policy_key,
                            "version": version}):
        raise HTTPException(
            status_code=409,
            detail=(f"v{version} of {policy_key} is already logged. Use a new version "
                    f"number -- rewriting a logged revision is what the history exists to "
                    f"prevent."))

    now = datetime.now(timezone.utc)
    doc = {
        "company_id": str(company_id),
        "policy_key": policy_key,
        "version": version,
        "summary_of_change": summary,
        "effective_date": effective,
        "document_id": clean_text(payload.get("document_id"), limit=40),
        "changed_by": str(actor.get("_id") or ""),
        "changed_by_name": _actor_name(actor),
        "changed_at": now,
        "approved_by": None,
        "approved_by_name": None,
        "approved_at": None,
        "created_at": now,
    }
    await coll.insert_one(dict(doc))
    await audit(actor, AUDIT_POLICY_REVISED, ENTITY_POLICY, policy_key,
                f"v{version} drafted: {summary[:200]}", company_id)
    return _out(doc)


async def approve_revision(actor: dict, company_id: str, policy_key: str,
                           payload: dict) -> dict:
    """Approve a revision, and make it the version in force. MD only (`policy.approve`).

    This is the act that changes what governs. It moves the register's `version`, resets the
    review clock to a year out, and stamps the approval on the revision row -- so the
    Modification History says who decided, not merely who typed.
    """
    version = clean_text(payload.get("version"), limit=20)
    if not version:
        raise HTTPException(status_code=422, detail="Which version are you approving?")

    signature = clean_text(payload.get("signature"), limit=140)
    if not signature:
        raise HTTPException(
            status_code=422,
            detail=("Type your name to sign this approval. It changes which version of the "
                    "policy the company is held to."))

    revisions = get_collection(COLL_POLICY_REVISIONS)
    revision = await revisions.find_one(
        {"company_id": str(company_id), "policy_key": policy_key, "version": version})
    if not revision:
        raise HTTPException(
            status_code=404, detail=f"v{version} of {policy_key} has not been logged.")
    if revision.get("approved_at"):
        raise HTTPException(
            status_code=409, detail=f"v{version} was already approved.")

    now = datetime.now(timezone.utc)
    # Compare-and-swap on the unapproved state, so two approvers clicking at once cannot
    # both land -- the same rule the exception log and the requisition chain follow.
    result = await revisions.update_one(
        {"company_id": str(company_id), "policy_key": policy_key, "version": version,
         "approved_at": None},
        {"$set": {"approved_by": str(actor.get("_id") or ""),
                  "approved_by_name": _actor_name(actor),
                  "approved_at": now, "signature": signature,
                  "approval_remarks": clean_text(payload.get("remarks"), limit=2000)}})
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail="This revision was approved by someone else. Reload and try again.")

    effective = revision.get("effective_date") or now.strftime("%Y-%m-%d")
    await get_collection(COLL_POLICIES).update_one(
        {"company_id": str(company_id), "policy_key": policy_key},
        {"$set": {"version": version,
                  "effective_date": effective,
                  "status": PolicyStatus.IN_FORCE.value,
                  # The review clock restarts from the new version's effective date. A
                  # policy revised in June is not still due for its annual review in
                  # January because that is when the last one landed.
                  "next_review_due": _add_months(effective, POLICY_REVIEW_MONTHS),
                  "document_id": (revision.get("document_id")
                                  or None),
                  "updated_at": now}})
    await audit(actor, AUDIT_POLICY_APPROVED, ENTITY_POLICY, policy_key,
                f"v{version} approved and in force from {effective}", company_id)
    return await get_policy(company_id, policy_key)
