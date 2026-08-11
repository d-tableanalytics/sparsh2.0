"""HRMS > the client master (Phase 11-R, Item 4).

Who a vacancy is being filled FOR.

-- Why a separate master, and what it is NOT ----------------------------------------------
CONFIRMED WITH THE BUSINESS before this was built (PHASE_11R_REPORT §Decisions): this
deployment runs the recruitment-AGENCY model. The HRMS user recruits on behalf of client
organisations, and those clients are their own entities with their own contacts.

A "client" is therefore NOT `company_id`. `company_id` remains the ERP tenant that OWNS the
data and is the ONLY thing tenant scoping ever runs on. `client_id` is a reporting and
routing dimension living inside one tenant. Keeping that distinction sharp matters: if the
client ever became a security boundary it would be a second, weaker one running in parallel
with the real one, which is precisely the "four overlapping authorization mechanisms"
failure the module was rebuilt to avoid.

Every query below therefore carries `company_id`. A client id from another tenant simply
finds nothing, because it is part of the filter rather than checked afterwards.

-- Deletion is refused while requisitions reference a client ------------------------------
Mongo has no foreign keys, so referential integrity is application-enforced, exactly as it
is for departments and designations. Deactivating is the non-destructive alternative.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import (
    AUDIT_CLIENT_CREATED, AUDIT_CLIENT_DELETED, AUDIT_CLIENT_UPDATED, COLL_CANDIDATES,
    COLL_CLIENTS, COLL_REQUISITIONS, EMAIL_RE, ENTITY_CLIENT, PHONE_RE, ReqClosing,
)
from app.services.hrms_audit_service import audit
from app.services.hrms_id_service import next_business_id
from app.utils.hrms_public_guard import clean_text


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _clean_name(name: str) -> str:
    """Trim and collapse internal whitespace.

    Without this, 'Acme' and 'Acme ' are two clients as far as the unique index is
    concerned -- the same normalisation hrms_masters_service applies, and for the same
    reason: the source accumulated four spellings of one department this way.
    """
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise HTTPException(status_code=422, detail="Client name is required.")
    if len(cleaned) > 160:
        raise HTTPException(
            status_code=422, detail="Client name must be 160 characters or fewer.")
    return cleaned


def _validate_contact(payload: dict) -> dict:
    out = {}
    if payload.get("contact_email") is not None:
        email = (clean_text(payload["contact_email"], limit=180) or "").lower() or None
        if email and not EMAIL_RE.match(email):
            raise HTTPException(status_code=422, detail="Enter a valid contact email.")
        out["contact_email"] = email
    if payload.get("contact_phone") is not None:
        phone = clean_text(payload["contact_phone"], limit=30)
        if phone and not PHONE_RE.match(phone):
            raise HTTPException(status_code=422, detail="Enter a valid contact phone number.")
        out["contact_phone"] = phone
    return out


# -------------------------------------------------------------
# Read
# -------------------------------------------------------------
async def list_clients(actor: dict, company_id: str, *, include_inactive: bool = False,
                       search: str = None, with_stats: bool = False) -> dict:
    query = {"company_id": str(company_id)}
    if not include_inactive:
        query["active"] = True
    if search:
        import re
        safe = re.escape(search.strip())
        query["$or"] = [
            {"name": {"$regex": safe, "$options": "i"}},
            {"client_id": {"$regex": safe, "$options": "i"}},
            {"code": {"$regex": safe, "$options": "i"}},
            {"contact_name": {"$regex": safe, "$options": "i"}},
        ]

    rows = await get_collection(COLL_CLIENTS).find(query).sort("name", 1).to_list(1000)
    out = [_out(r) for r in rows]

    if with_stats and out:
        # One grouped read for every client rather than N queries -- the same shape
        # hrms_posting_service._application_counts uses.
        counts = await get_collection(COLL_REQUISITIONS).aggregate([
            {"$match": {"company_id": str(company_id),
                        "client_id": {"$in": [c["client_id"] for c in out]}}},
            {"$group": {"_id": "$client_id", "count": {"$sum": 1}}},
        ]).to_list(len(out) + 10)
        by_client = {r["_id"]: r["count"] for r in counts}

        open_counts = await get_collection(COLL_REQUISITIONS).aggregate([
            {"$match": {"company_id": str(company_id),
                        "closing_status": ReqClosing.OPEN.value,
                        "client_id": {"$in": [c["client_id"] for c in out]}}},
            {"$group": {"_id": "$client_id", "count": {"$sum": 1}}},
        ]).to_list(len(out) + 10)
        open_by_client = {r["_id"]: r["count"] for r in open_counts}

        for c in out:
            c["requisition_count"] = by_client.get(c["client_id"], 0)
            c["open_requisitions"] = open_by_client.get(c["client_id"], 0)

    return {"clients": out, "total": len(out)}


async def get_client(company_id: str, client_id: str) -> Optional[dict]:
    """Fetch one client, scoped to the company.

    company_id is part of the QUERY, not a post-filter, so a caller cannot read another
    tenant's client by guessing an id.
    """
    doc = await get_collection(COLL_CLIENTS).find_one(
        {"client_id": client_id, "company_id": str(company_id)})
    return _out(doc) if doc else None


async def require_client(company_id: str, client_id: str) -> dict:
    """Resolve a client reference or 422. Used by the requisition service."""
    doc = await get_collection(COLL_CLIENTS).find_one(
        {"client_id": client_id, "company_id": str(company_id)})
    if not doc:
        raise HTTPException(
            status_code=422, detail="That client does not exist for this company.")
    if not doc.get("active", True):
        raise HTTPException(
            status_code=422,
            detail=f"'{doc.get('name')}' is inactive. Reactivate it before raising work "
                   f"against it.")
    return doc


# -------------------------------------------------------------
# Write
# -------------------------------------------------------------
async def create_client(actor: dict, company_id: str, payload: dict) -> dict:
    import re
    name = _clean_name(payload.get("name"))
    coll = get_collection(COLL_CLIENTS)
    # Case-insensitive check; the unique index is case-SENSITIVE so 'Acme' and 'acme' would
    # otherwise both be accepted and become two clients.
    if await coll.find_one({"company_id": str(company_id),
                            "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}):
        raise HTTPException(status_code=409, detail=f"Client '{name}' already exists.")

    client_id = await next_business_id("client", str(company_id))
    doc = {
        "client_id": client_id,
        "company_id": str(company_id),
        "name": name,
        "code": clean_text(payload.get("code"), limit=40),
        "industry": clean_text(payload.get("industry"), limit=120),
        "contact_name": clean_text(payload.get("contact_name"), limit=140),
        "contact_email": None,
        "contact_phone": None,
        "address": clean_text(payload.get("address"), limit=500),
        "notes": clean_text(payload.get("notes"), limit=2000),
        "active": bool(payload.get("active", True)),
        "created_at": datetime.now(timezone.utc),
        "created_by": str(actor.get("_id") or ""),
    }
    doc.update(_validate_contact(payload))

    try:
        await coll.insert_one(dict(doc))
    except Exception as e:
        if "duplicate" in str(e).lower() or "E11000" in str(e):
            raise HTTPException(status_code=409, detail=f"Client '{name}' already exists.")
        raise

    await audit(actor, AUDIT_CLIENT_CREATED, ENTITY_CLIENT, client_id, name, company_id)
    return _out(doc)


async def update_client(actor: dict, company_id: str, client_id: str, payload: dict) -> dict:
    import re
    coll = get_collection(COLL_CLIENTS)
    current = await coll.find_one({"client_id": client_id, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Client not found.")

    updates = {}
    if payload.get("name") is not None:
        name = _clean_name(payload["name"])
        clash = await coll.find_one({
            "company_id": str(company_id), "client_id": {"$ne": client_id},
            "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}})
        if clash:
            raise HTTPException(status_code=409, detail=f"Client '{name}' already exists.")
        updates["name"] = name
    for field, limit in (("code", 40), ("industry", 120), ("contact_name", 140),
                         ("address", 500), ("notes", 2000)):
        if payload.get(field) is not None:
            updates[field] = clean_text(payload[field], limit=limit)
    updates.update(_validate_contact(payload))
    if payload.get("active") is not None:
        updates["active"] = bool(payload["active"])

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    updates["updated_at"] = datetime.now(timezone.utc)
    await coll.update_one({"client_id": client_id, "company_id": str(company_id)},
                          {"$set": updates})
    # A rename follows through to the requisitions that denormalised it, or every existing
    # requisition and report keeps showing a name the master no longer has.
    if "name" in updates:
        await get_collection(COLL_REQUISITIONS).update_many(
            {"company_id": str(company_id), "client_id": client_id},
            {"$set": {"client_name": updates["name"]}})

    await audit(actor, AUDIT_CLIENT_UPDATED, ENTITY_CLIENT, client_id,
                ", ".join(sorted(k for k in updates if k != "updated_at")), company_id)
    return await get_client(company_id, client_id)


async def delete_client(actor: dict, company_id: str, client_id: str) -> dict:
    """Delete a client, refusing while any requisition still references it."""
    coll = get_collection(COLL_CLIENTS)
    current = await coll.find_one({"client_id": client_id, "company_id": str(company_id)})
    if not current:
        raise HTTPException(status_code=404, detail="Client not found.")

    in_use = await get_collection(COLL_REQUISITIONS).count_documents(
        {"company_id": str(company_id), "client_id": client_id})
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=(f"'{current.get('name')}' is named on {in_use} requisition(s). Set the "
                    f"client inactive instead of deleting, so the hiring record survives."))

    await coll.delete_one({"client_id": client_id, "company_id": str(company_id)})
    await audit(actor, AUDIT_CLIENT_DELETED, ENTITY_CLIENT, client_id,
                current.get("name"), company_id)
    return {"deleted": True, "client_id": client_id, "name": current.get("name")}


async def client_summary(company_id: str, client_id: str) -> dict:
    """Headline counts for one client — requisitions raised and candidates in flight.

    Read-only and deliberately small: the full analytics live in hrms_analytics_service,
    which is the one place aggregation belongs.
    """
    reqs = await get_collection(COLL_REQUISITIONS).find(
        {"company_id": str(company_id), "client_id": client_id},
        {"request_no": 1, "closing_status": 1, "vacancy": 1}).to_list(2000)
    request_nos = [r["request_no"] for r in reqs if r.get("request_no")]
    candidates = 0
    if request_nos:
        candidates = await get_collection(COLL_CANDIDATES).count_documents(
            {"company_id": str(company_id), "request_no": {"$in": request_nos}})
    return {
        "client_id": client_id,
        "requisitions": len(reqs),
        "open_requisitions": sum(1 for r in reqs
                                 if r.get("closing_status") == ReqClosing.OPEN.value),
        "vacancies": sum(int(r.get("vacancy") or 1) for r in reqs
                         if r.get("closing_status") == ReqClosing.OPEN.value),
        "candidates": candidates,
    }
