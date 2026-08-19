"""HRMS > the client dimension — who a vacancy is being filled FOR.

-- There is no HRMS client master ---------------------------------------------------------
A "client" is a company record the ERP ALREADY holds, in the Companies section (the
`companies` collection). This module is a read-only projection of that collection into the
shape HRMS reports on; nothing here creates, edits or deletes a client, because doing so
would be maintaining a second list of the same organisations.

That was the earlier design and it was wrong: `hrms_clients` meant the same client existed
twice, could be spelled two ways, and had to be re-entered by hand before it could appear on
a dashboard. Companies is the master. A rename there is a rename everywhere, with no sync
step to forget.

-- A client is NOT a tenant ---------------------------------------------------------------
`company_id` remains the ERP tenant that OWNS the recruitment data and is the ONLY thing
tenant scoping ever runs on. `client_id` is a reporting and routing dimension INSIDE one
tenant, which happens to be spelled as another company's id. Keeping that distinction sharp
matters: if the client ever became a security boundary it would be a second, weaker one
running in parallel with the real one -- precisely the "four overlapping authorization
mechanisms" failure the module was rebuilt to avoid.

Concretely: the agency tenant tags its requisitions with the client company they are for.
Nothing flows the other way. Being named as a client on someone's requisition grants that
company no read over the tenant's data, and reading this list yields a company's NAME, never
its records.

-- What callers get -----------------------------------------------------------------------
`client_id` here is the company's `_id` as a string. Every consumer -- the requisition write
path, the analytics client filter, the dashboard dropdown -- already speaks `client_id`, so
repointing the source left those untouched.
"""
import re
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import COLL_CANDIDATES, COLL_REQUISITIONS, ReqClosing
# ── Client engagements ──
from app.models.hrms import (
    AUDIT_ENGAGEMENT_CREATED, AUDIT_ENGAGEMENT_MEMBER_ADDED,
    AUDIT_ENGAGEMENT_MEMBER_REMOVED, AUDIT_ENGAGEMENT_UPDATED,
    COLL_CLIENT_ENGAGEMENTS, ENGAGEMENT_GRANTS_SCOPE, ENTITY_ENGAGEMENT, EngagementStatus,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_public_guard import clean_text

COLL_COMPANIES = "companies"

# Only what a client dropdown and a client header need. Listing the fields explicitly rather
# than returning the company document keeps this from leaking a tenant's GST number, owner or
# member count into HRMS, which has no business displaying any of them.
_PROJECTION = {
    "name": 1, "domain": 1, "company_type": 1, "email": 1, "contact": 1,
    "city": 1, "state": 1, "is_active": 1, "status": 1,
}


def _out(doc: dict) -> dict:
    """A company document in the shape HRMS's client consumers expect.

    The key mapping is `client_id` <- `_id`. `industry` and the contact fields are aliases
    over the Companies equivalents rather than new storage, so there is exactly one place
    each value is written and it is not this module.
    """
    return {
        "client_id": str(doc.get("_id")),
        "name": doc.get("name"),
        "industry": doc.get("company_type"),
        "domain": doc.get("domain"),
        "contact_email": doc.get("email"),
        "contact_phone": doc.get("contact"),
        "location": ", ".join(p for p in (doc.get("city"), doc.get("state")) if p) or None,
        # A company on "hold" is still a client -- it is a billing state, not a hiring one --
        # so `active` tracks is_active alone. `status` rides along for anyone who wants to
        # show the distinction.
        "active": doc.get("is_active", True) is not False,
        "status": doc.get("status") or "active",
    }


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_clients(actor: dict, company_id: str, *, include_inactive: bool = False,
                       search: str = None, with_stats: bool = False) -> dict:
    """Companies that may be named as the client of a requisition.

    `company_id` is the CALLING tenant. It does not filter the companies returned -- a
    client is by definition a different organisation from the tenant recruiting for it -- but
    it does scope `with_stats`, so the counts are this tenant's own hiring and never another's.
    """
    query = {} if include_inactive else {"is_active": {"$ne": False}}
    if search:
        safe = re.escape(search.strip())
        query["$or"] = [
            {"name": {"$regex": safe, "$options": "i"}},
            {"domain": {"$regex": safe, "$options": "i"}},
            {"city": {"$regex": safe, "$options": "i"}},
        ]

    rows = await get_collection(COLL_COMPANIES).find(
        query, _PROJECTION).sort("name", 1).to_list(1000)
    out = [_out(r) for r in rows]

    if with_stats and out:
        ids = [c["client_id"] for c in out]
        # One grouped read for every client rather than N queries -- the same shape
        # hrms_posting_service._application_counts uses.
        counts = await get_collection(COLL_REQUISITIONS).aggregate([
            {"$match": {"company_id": str(company_id), "client_id": {"$in": ids}}},
            {"$group": {"_id": "$client_id", "count": {"$sum": 1}}},
        ]).to_list(len(out) + 10)
        by_client = {r["_id"]: r["count"] for r in counts}

        open_counts = await get_collection(COLL_REQUISITIONS).aggregate([
            {"$match": {"company_id": str(company_id),
                        "closing_status": ReqClosing.OPEN.value,
                        "client_id": {"$in": ids}}},
            {"$group": {"_id": "$client_id", "count": {"$sum": 1}}},
        ]).to_list(len(out) + 10)
        open_by_client = {r["_id"]: r["count"] for r in open_counts}

        for c in out:
            c["requisition_count"] = by_client.get(c["client_id"], 0)
            c["open_requisitions"] = open_by_client.get(c["client_id"], 0)

    return {"clients": out, "total": len(out)}


async def get_client(client_id: str) -> Optional[dict]:
    """Fetch one client company, or None.

    A malformed id returns None rather than raising: `client_id` reaches this from a query
    string, and a 500 on a typo would be a worse answer than "no such client".
    """
    try:
        oid = ObjectId(str(client_id))
    except (InvalidId, TypeError):
        return None
    doc = await get_collection(COLL_COMPANIES).find_one({"_id": oid}, _PROJECTION)
    return _out(doc) if doc else None


async def require_client(client_id: str) -> dict:
    """Resolve a client reference or 422. Used by the requisition write path.

    Takes no `company_id` on purpose. The old client master was tenant-owned, so resolving a
    client WAS a tenant check; a company is a shared ERP record, so pretending to scope the
    lookup would be security theatre. The real boundary is unchanged and lives where it
    always did -- on the requisition's own `company_id`.
    """
    doc = await get_client(client_id)
    if not doc:
        raise HTTPException(
            status_code=422,
            detail="That client does not exist. Pick a company from the Companies section.")
    if not doc["active"]:
        raise HTTPException(
            status_code=422,
            detail=f"'{doc['name']}' is inactive. Reactivate it in Companies before raising "
                   f"work against it.")
    return doc


async def client_summary(company_id: str, client_id: str) -> dict:
    """Headline counts for one client — requisitions raised and candidates in flight.

    Read-only and deliberately small: the full analytics live in hrms_analytics_service,
    which is the one place aggregation belongs. Scoped to the calling tenant, so two agencies
    recruiting for the same client company each see only their own work.
    """
    reqs = await get_collection(COLL_REQUISITIONS).find(
        {"company_id": str(company_id), "client_id": str(client_id)},
        {"request_no": 1, "closing_status": 1, "vacancy": 1}).to_list(2000)
    request_nos = [r["request_no"] for r in reqs if r.get("request_no")]
    candidates = 0
    if request_nos:
        candidates = await get_collection(COLL_CANDIDATES).count_documents(
            {"company_id": str(company_id), "request_no": {"$in": request_nos}})
    return {
        "client_id": str(client_id),
        "requisitions": len(reqs),
        "open_requisitions": sum(1 for r in reqs
                                 if r.get("closing_status") == ReqClosing.OPEN.value),
        "vacancies": sum(int(r.get("vacancy") or 1) for r in reqs
                         if r.get("closing_status") == ReqClosing.OPEN.value),
        "candidates": candidates,
    }


# =============================================================
# Client engagements
# =============================================================
# The relationship the projection above cannot express: this tenant provides recruitment
# services to that company, and these of our users work on it.
#
# A `companies` row says an organisation EXISTS. It does not say it is OUR client, and no
# amount of reading it will. That is the whole reason this collection exists -- without it,
# `require_client()` accepts any company id in the ERP simply because it resolves, and
# "which clients may this user see" has no answer at all.
#
# Nothing here duplicates a company. The engagement stores a reference, a status, a member
# list and an audit trail. Name, address and contacts stay where they belong.
def _engagement_out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    # Returned as a COUNT alongside the list: the count is what a list view renders, the
    # list is what an admin screen needs, and neither is derived in the browser.
    doc["member_count"] = len(doc.get("member_user_ids") or [])
    return doc


async def _company_names(client_ids) -> dict:
    """Current names for a set of client ids.

    Joined at READ time rather than stored, for the same reason analytics refreshes
    `client_name`: a rename in Companies must show through with no sync step.
    """
    oids = []
    for i in {str(c) for c in client_ids if c}:
        try:
            oids.append(ObjectId(i))
        except (InvalidId, TypeError):
            continue
    if not oids:
        return {}
    rows = await get_collection(COLL_COMPANIES).find(
        {"_id": {"$in": oids}}, {"name": 1}).to_list(len(oids))
    return {str(r["_id"]): r.get("name") for r in rows}


async def list_engagements(actor: dict, company_id: str, *, status: str = None,
                           include_ended: bool = False) -> dict:
    """Every client this tenant has engaged.

    `company_id` is part of the QUERY, so another tenant's engagements are not filtered out
    afterwards -- they are never read at all.
    """
    query = {"company_id": str(company_id)}
    if status:
        query["status"] = status
    elif not include_ended:
        query["status"] = {"$ne": EngagementStatus.ENDED.value}

    rows = await get_collection(COLL_CLIENT_ENGAGEMENTS).find(query).sort(
        "created_at", -1).to_list(500)
    names = await _company_names(r.get("client_id") for r in rows)

    out = []
    for row in rows:
        item = _engagement_out(row)
        item["client_name"] = names.get(str(row.get("client_id")))
        out.append(item)
    return {"engagements": out, "total": len(out)}


async def get_engagement(company_id: str, engagement_id: str) -> Optional[dict]:
    doc = await get_collection(COLL_CLIENT_ENGAGEMENTS).find_one(
        {"engagement_id": engagement_id, "company_id": str(company_id)})
    if not doc:
        return None
    out = _engagement_out(doc)
    names = await _company_names([doc.get("client_id")])
    out["client_name"] = names.get(str(doc.get("client_id")))
    return out


async def engaged_client_ids(company_id: str) -> list:
    """Every client id this tenant currently has a scope-granting engagement with.

    The range a Sparsh user's client filter may legitimately cover. NOT an authorisation
    input on its own -- the per-user answer is utils/hrms_access.scope_client_ids.
    """
    rows = await get_collection(COLL_CLIENT_ENGAGEMENTS).find(
        {"company_id": str(company_id),
         "status": {"$in": sorted(ENGAGEMENT_GRANTS_SCOPE)}},
        {"client_id": 1}).to_list(500)
    return sorted({str(r["client_id"]) for r in rows if r.get("client_id")})


async def require_engagement(company_id: str, client_id: str) -> dict:
    """Assert that `client_id` is a live client OF THIS TENANT, or 422.

    The check `require_client()` cannot make. `require_client` proves a company exists;
    this proves it is ours to recruit for.

    DELIBERATELY NOT WIRED into the requisition write path yet: doing so would refuse every
    existing client-track requisition, because no engagement has been opened. The phase that
    owns requisition client scope turns it on.
    """
    doc = await get_collection(COLL_CLIENT_ENGAGEMENTS).find_one(
        {"company_id": str(company_id), "client_id": str(client_id)})
    if not doc:
        raise HTTPException(
            status_code=422,
            detail=("That company is not a client of yours. Open an engagement with them "
                    "before recruiting on their behalf."))
    if doc.get("status") not in ENGAGEMENT_GRANTS_SCOPE:
        raise HTTPException(
            status_code=422,
            detail=(f'The engagement with that client is "{doc.get("status")}". '
                    f"Reactivate it before raising work against it."))
    return _engagement_out(doc)


async def create_engagement(actor: dict, company_id: str, payload: dict) -> dict:
    client_id = clean_text(payload.get("client_id"), limit=40)
    if not client_id:
        raise HTTPException(status_code=422, detail="Choose a company to engage.")
    if str(client_id) == str(company_id):
        raise HTTPException(
            status_code=422,
            detail=("A company cannot be its own client. Hiring for yourself is the "
                    "internal track, which carries no client at all."))

    company = await get_client(client_id)
    if not company:
        raise HTTPException(
            status_code=422,
            detail="That company does not exist. Pick one from the Companies section.")
    if not company.get("active", True):
        raise HTTPException(
            status_code=422,
            detail=f"'{company.get('name')}' is inactive in the Companies section.")

    coll = get_collection(COLL_CLIENT_ENGAGEMENTS)
    existing = await coll.find_one({"company_id": str(company_id),
                                    "client_id": str(client_id)})
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(f"You already have an engagement with '{company.get('name')}' "
                    f"({existing.get('engagement_id')}, {existing.get('status')})."))

    year = datetime.now(timezone.utc).year
    engagement_id = await next_business_id("engagement", str(company_id), year)
    now = datetime.now(timezone.utc)
    doc = {
        "engagement_id": engagement_id,
        "company_id": str(company_id),
        "client_id": str(client_id),
        "status": EngagementStatus.ACTIVE.value,
        "notes": clean_text(payload.get("notes"), limit=2000),
        # Empty on purpose: an engagement grants nobody anything until somebody is added.
        "member_user_ids": [],
        "created_at": now,
        "created_by": str(actor.get("_id") or ""),
        "created_by_name": actor.get("full_name") or actor.get("email"),
        "updated_at": now,
        "updated_by": str(actor.get("_id") or ""),
    }
    try:
        await coll.insert_one(dict(doc))
    except Exception as e:
        if "duplicate" in str(e).lower() or "E11000" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"You already have an engagement with '{company.get('name')}'.")
        raise

    await audit(actor, AUDIT_ENGAGEMENT_CREATED, ENTITY_ENGAGEMENT, engagement_id,
                company.get("name"), company_id)
    out = _engagement_out(doc)
    out["client_name"] = company.get("name")
    return out


async def update_engagement(actor: dict, company_id: str, engagement_id: str,
                            payload: dict) -> dict:
    """Change an engagement's status or notes.

    Suspending or ending one revokes its members' scope IMMEDIATELY, because
    `scope_client_ids` only reads engagements whose status grants scope. No membership row
    is touched and nothing can be left behind holding access.
    """
    coll = get_collection(COLL_CLIENT_ENGAGEMENTS)
    current = await coll.find_one({"engagement_id": engagement_id,
                                   "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Engagement not found.")

    updates = {}
    if payload.get("status") is not None:
        raw = getattr(payload["status"], "value", payload["status"])
        try:
            updates["status"] = EngagementStatus(raw).value
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=(f"Status must be one of: "
                        f"{', '.join(s.value for s in EngagementStatus)}."))
    if payload.get("notes") is not None:
        updates["notes"] = clean_text(payload["notes"], limit=2000)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    updates["updated_by"] = str(actor.get("_id") or "")
    await coll.update_one({"engagement_id": engagement_id, "company_id": str(company_id)},
                          {"$set": updates})
    await audit(actor, AUDIT_ENGAGEMENT_UPDATED, ENTITY_ENGAGEMENT, engagement_id,
                ", ".join(sorted(k for k in updates
                                 if k not in ("updated_at", "updated_by"))), company_id)
    return await get_engagement(company_id, engagement_id)


# -------------------------------------------------------------
# Membership
# -------------------------------------------------------------
async def _require_tenant_user(company_id: str, user_id: str) -> dict:
    """The user being granted access, who must belong to THIS company.

    This is the cross-company rejection. `company_id` is the security boundary, so client
    scope narrows INSIDE it and can never be used to reach a user of another tenant.
    """
    try:
        oid = ObjectId(str(user_id))
    except (InvalidId, TypeError):
        raise HTTPException(status_code=422, detail="That is not a valid user id.")

    # `staff` are Sparsh internal users with no company of their own. They are never
    # client-scoped, so a membership for one could never resolve -- refused loudly rather
    # than stored as a row that does nothing.
    if await get_collection("staff").find_one({"_id": oid}, {"_id": 1}):
        raise HTTPException(
            status_code=422,
            detail=("Internal staff are not client users -- they already see the whole "
                    "tenant. Only a company user can be given client access."))

    doc = await get_collection("learners").find_one(
        {"_id": oid}, {"full_name": 1, "email": 1, "company_id": 1,
                       "governance_role": 1, "is_active": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found.")
    if str(doc.get("company_id") or "") != str(company_id):
        raise HTTPException(
            status_code=422, detail="That user belongs to another company.")
    if doc.get("is_active") is False:
        raise HTTPException(status_code=422, detail="That user is not active.")
    return doc


async def list_engagement_members(company_id: str, engagement_id: str) -> dict:
    doc = await get_collection(COLL_CLIENT_ENGAGEMENTS).find_one(
        {"engagement_id": engagement_id, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Engagement not found.")

    oids = []
    for i in (doc.get("member_user_ids") or []):
        try:
            oids.append(ObjectId(str(i)))
        except (InvalidId, TypeError):
            continue

    members = []
    if oids:
        for row in await get_collection("learners").find(
                {"_id": {"$in": oids}},
                {"full_name": 1, "email": 1, "governance_role": 1,
                 "is_active": 1}).to_list(len(oids)):
            members.append({
                "user_id": str(row["_id"]),
                "name": row.get("full_name") or row.get("email"),
                "email": row.get("email"),
                "governance_role": row.get("governance_role"),
                "is_active": row.get("is_active") is not False,
                # Surfaced so an admin can see WHY a member may have no access: membership
                # alone does nothing unless the user's role resolves to CLIENT.
                "client_scoped": (row.get("governance_role") or "").strip().upper()
                == "CLIENT",
            })
    return {"engagement_id": engagement_id, "members": members, "total": len(members)}


async def add_engagement_member(actor: dict, company_id: str, engagement_id: str,
                                user_id: str) -> dict:
    coll = get_collection(COLL_CLIENT_ENGAGEMENTS)
    if not await coll.find_one({"engagement_id": engagement_id,
                                "company_id": str(company_id)}):
        raise HTTPException(status_code=404, detail="Engagement not found.")

    user = await _require_tenant_user(company_id, user_id)
    # $addToSet, not $push: adding the same person twice must not create two memberships
    # that a single removal would only half undo.
    await coll.update_one(
        {"engagement_id": engagement_id, "company_id": str(company_id)},
        {"$addToSet": {"member_user_ids": str(user_id)},
         "$set": {"updated_at": datetime.now(timezone.utc),
                  "updated_by": str(actor.get("_id") or "")}})
    await audit(actor, AUDIT_ENGAGEMENT_MEMBER_ADDED, ENTITY_ENGAGEMENT, engagement_id,
                user.get("full_name") or user.get("email"), company_id)
    return await list_engagement_members(company_id, engagement_id)


async def remove_engagement_member(actor: dict, company_id: str, engagement_id: str,
                                   user_id: str) -> dict:
    coll = get_collection(COLL_CLIENT_ENGAGEMENTS)
    if not await coll.find_one({"engagement_id": engagement_id,
                                "company_id": str(company_id)}):
        raise HTTPException(status_code=404, detail="Engagement not found.")

    await coll.update_one(
        {"engagement_id": engagement_id, "company_id": str(company_id)},
        {"$pull": {"member_user_ids": str(user_id)},
         "$set": {"updated_at": datetime.now(timezone.utc),
                  "updated_by": str(actor.get("_id") or "")}})
    await audit(actor, AUDIT_ENGAGEMENT_MEMBER_REMOVED, ENTITY_ENGAGEMENT, engagement_id,
                str(user_id), company_id)
    return await list_engagement_members(company_id, engagement_id)
