"""Company-level HRMS access control — the module's ONE authorization surface.

Mirrors app/utils/tpms_access.py in shape and defaults: HRMS is **opt-in per company**,
so a missing `hrms_enabled` flag means OFF and a company stays dark until an Admin /
Super Admin switches it on.

Three layers use this:
  • ensure_hrms_enabled()      — router guard; client-side users of a disabled company
                                 are refused. Internal staff always pass so they can
                                 administer and support across clients.
  • hrms_enabled_company_ids() — data-layer filter; disabled companies are excluded from
                                 every list, dashboard, report and aggregation.
  • hrms_tenant_company_ids()  — where HRMS records actually live. The fallback scope for
                                 internal staff when NO company has the toggle on, so
                                 administering a switched-off module is still possible.
  • can() / require_cap()      — the capability check every feature gate resolves through.

── Why a capability check and not role strings ──────────────────────────────────
The source HRMS accumulated four overlapping authorization mechanisms with three
different "admin" role sets, a helper (`canAccessHrms`) whose name no longer matched
what it did, an accepted-but-never-created "MD" role, and a granted-but-unread
permission (BACKEND_ANALYSIS §7.3, Risk #13). Its own analysis calls this the highest
risk of "a gate being added in the wrong place".

Here there is exactly one path: resolve the caller to an HrmsRole, resolve that role to a
capability set, and ask `can(user, Cap.X)`. Adding a capability is a one-line change in
models/hrms.py; there is nowhere else for a gate to hide.
"""
from typing import Optional, Set

from bson import ObjectId
from fastapi import Depends, HTTPException

from app.controllers.auth_controller import get_current_user
from app.db.mongodb import get_collection
from app.models.hrms import (
    CLIENT_ROLES, GOVERNANCE_TO_HRMS, INTERNAL_OWNER_ROLES, INTERNAL_STAFF_ROLES,
    ROLE_CAPABILITIES, TOGGLE_ROLES, Cap, HrmsRole,
)
from app.models.hrms import COLL_CLIENT_ENGAGEMENTS, ENGAGEMENT_GRANTS_SCOPE

MODULE_DISABLED_MESSAGE = (
    "The HRMS module is not enabled for your company. Please contact your administrator."
)
NO_ACCESS_MESSAGE = "You do not have access to the HRMS module."

# ─────────────────────────────────────────────────────────────
# The client-participant stamp
# ─────────────────────────────────────────────────────────────
# A user of a CLIENT organisation is not a tenant of HRMS. Their own company has the module
# switched off -- correctly, because they do not run a hiring pipeline; Sparsh runs one FOR
# them. They reach HRMS as a participant in Sparsh's tenant, through a client engagement.
#
# Establishing that takes a database read, and `hrms_role` / `can` are synchronous and
# called on every gate in the module. So the entry dependency (`ensure_hrms_enabled`, which
# already runs per request) resolves it once and STAMPS the answer on the user dict, and
# the synchronous resolvers read the stamp.
#
# Two properties this must hold, because getting either wrong is a privilege escalation:
#
#   1. The stamp is SERVER-SET ONLY. `ensure_hrms_enabled` clears any inbound value before
#      deciding, so a crafted request body can never award itself a tenant.
#   2. A stamped user is a CLIENT, whatever their governance_role says. A client company's
#      "HR" is HR *of that company*; inside Sparsh's HRMS they are a client contact, and
#      mapping their title to HrmsRole.HR would hand them Sparsh's entire HR capability set.
CLIENT_TENANT_FIELD = "_hrms_client_tenant"


# ─────────────────────────────────────────────────────────────
# Identity
# ─────────────────────────────────────────────────────────────
def is_internal_user(user: dict) -> bool:
    """Sparsh internal (staff collection) rather than a client-side user.

    Prefers the `_source_collection` stamp set by auth_controller.get_user_from_token,
    falls back to `tag`, then to the role — the same precedence auth_controller uses, so
    the two never disagree.
    """
    if not user:
        return False
    src = user.get("_source_collection")
    if src == "staff":
        return True
    if src == "learners":
        return False
    tag = user.get("tag")
    if tag == "staff":
        return True
    if tag == "learner":
        return False
    role = (user.get("role") or "").lower()
    return role in INTERNAL_OWNER_ROLES or role in INTERNAL_STAFF_ROLES


def is_client_side_user(user: dict) -> bool:
    return bool(user) and not is_internal_user(user)


def hrms_role(user: dict) -> Optional[HrmsRole]:
    """Resolve an ERP user to their HRMS role, or None if they have none.

    Internal:  superadmin              → ADMIN     (full owner, cross-company)
               admin / coach / staff   → INTERNAL  (cross-company operator + support)
    Client:    clientadmin             → MD        (top of their company's ladder)
               governance_role MD      → MD
               governance_role HR      → HR
               governance_role FINANCE → FINANCE   (internal-track budget authority)
               governance_role HOD     → MANAGER
               anything else           → EMPLOYEE  (self-service only)

    A client user with no governance_role falls through to EMPLOYEE, matching
    auth_controller.client_rank's treatment of the same case (lowest rank by default).
    """
    if not user:
        return None
    role = (user.get("role") or "").strip().lower()

    if is_internal_user(user):
        if role in INTERNAL_OWNER_ROLES:
            return HrmsRole.ADMIN
        return HrmsRole.INTERNAL

    # A participant from a CLIENT organisation, admitted through an engagement. Checked
    # before the governance ladder on purpose: their title describes their standing in
    # their OWN company, and reading it here would promote a client's HR to Sparsh's HR or
    # a client's owner (clientadmin) to Sparsh's MD. In this module they are a client.
    if user.get(CLIENT_TENANT_FIELD):
        return HrmsRole.CLIENT

    if role == "clientadmin":
        return HrmsRole.MD
    if role in CLIENT_ROLES:
        governance = (user.get("governance_role") or "").strip().upper()
        return GOVERNANCE_TO_HRMS.get(governance, HrmsRole.EMPLOYEE)
    return None


# ─────────────────────────────────────────────────────────────
# Company module toggle
# ─────────────────────────────────────────────────────────────
async def is_hrms_enabled(company_id: str) -> bool:
    """Whether HRMS is switched on for a company. A missing flag means OFF — the module
    is opt-in per company, so nothing is exposed until it is explicitly enabled."""
    if not company_id:
        return False
    try:
        company = await get_collection("companies").find_one({"_id": ObjectId(company_id)})
    except Exception:
        return False
    if not company:
        return False
    return bool(company.get("hrms_enabled", False))


async def ensure_hrms_enabled(current_user: dict, company_id: str = None) -> None:
    """Raise 403 when a client-side user's company has HRMS switched off.

    Internal staff always pass: they administer HRMS across clients, and the data layer
    (hrms_enabled_company_ids) already excludes disabled companies from what they see.
    `company_id` defaults to the caller's own company, which is the case that matters —
    a client user can only ever act within it.
    """
    if is_internal_user(current_user):
        return

    # Never trust an inbound stamp. This runs before any decision, so a value arriving on
    # the request body or a stale dict cannot award itself a tenant.
    current_user.pop(CLIENT_TENANT_FIELD, None)

    target = company_id or str(current_user.get("company_id") or "")
    if await is_hrms_enabled(target):
        return

    # Their own company has HRMS off. Before refusing, ask the question the old code never
    # did: is this a CLIENT organisation's user, participating in a tenant that DOES run
    # HRMS? That is the whole client-hiring model -- a client does not run a pipeline, they
    # are a party to somebody else's -- and without this every client contact was refused
    # at the door, which is exactly the reported "client HR cannot access HRMS".
    tenant = await client_participant_tenant(current_user)
    if tenant:
        current_user[CLIENT_TENANT_FIELD] = tenant
        return

    raise HTTPException(status_code=403, detail=MODULE_DISABLED_MESSAGE)


async def client_participant_tenant(user: dict) -> Optional[str]:
    """The HRMS tenant this user takes part in as a client contact, or None.

    An engagement that lists them as a member, whose status grants scope, belonging to a
    company that actually has HRMS enabled. All three conditions matter: a lapsed
    engagement grants nothing, and an engagement in a tenant with the module switched off
    is not a way in through the back.

    Fails closed on any error, for the same reason `scope_client_ids` does -- a resolver
    that returns access because a read failed is a lock that opens when it breaks.
    """
    user_id = str((user or {}).get("_id") or "")
    if not user_id:
        return None
    try:
        rows = await get_collection(COLL_CLIENT_ENGAGEMENTS).find(
            {"member_user_ids": user_id,
             "status": {"$in": sorted(ENGAGEMENT_GRANTS_SCOPE)}},
            {"company_id": 1}).to_list(50)
        if not rows:
            return None
        enabled = await hrms_enabled_company_ids()
        for row in rows:
            candidate = str(row.get("company_id") or "")
            if candidate in enabled:
                return candidate
    except Exception as e:
        print(f"[WARN] HRMS client-participant lookup failed for {user_id}: {e}")
    return None


async def hrms_enabled_company_ids() -> set:
    """Ids of every company with HRMS switched on — the data-layer filter. Aggregations
    intersect against this so a disabled company never appears in a list, dashboard,
    report, filter dropdown or rollup."""
    docs = await get_collection("companies").find(
        {"hrms_enabled": True}, {"_id": 1}
    ).to_list(5000)
    return {str(d["_id"]) for d in docs}


# Collections whose rows mean "the HRMS module has been used in this company". Deliberately
# a short list of the things only a TENANT owns -- a client company is named inside a
# requisition's `client_id`, never as the `company_id` of one, so this cannot mistake a
# client for the operator.
HRMS_TENANT_COLLECTIONS = ("hrms_requisitions", "hrms_employee_profiles", "hrms_settings")


async def hrms_tenant_company_ids() -> set:
    """Companies that actually hold HRMS records, whether or not the module is switched on.

    Used for ONE thing: giving Sparsh internal staff somewhere to stand when no company has
    the toggle enabled.

    `ensure_hrms_enabled` has always let internal staff through -- they administer the
    module and support it across clients, so the toggle was never meant to gate them. But
    the company SELECTOR listed only enabled companies, so with everything switched off they
    landed inside a module with nothing to select and every endpoint answering
    "company_id is required". The toggle governs whether a company's OWN users can reach
    HRMS; it was never supposed to lock out the people who administer it.

    Reading the data rather than a flag is deliberate. There is no "this is the operator"
    marker on a company, and inventing one would be a second source of truth to keep in
    step. Where the requisitions and employee records actually live is not an opinion.

    Fails closed: an empty set on any error, so a broken read narrows access and never
    widens it.
    """
    found: set = set()
    for name in HRMS_TENANT_COLLECTIONS:
        try:
            for cid in await get_collection(name).distinct("company_id"):
                if cid:
                    found.add(str(cid))
        except Exception as e:
            print(f"[WARN] HRMS tenant lookup failed on {name}: {e}")
    return found


def can_toggle_module(user: dict) -> bool:
    """Only Admin / Super Admin may switch HRMS on or off for a company. Matches the
    TPMS toggle rule exactly."""
    return bool(user) and (user.get("role") or "").lower() in TOGGLE_ROLES


# ─────────────────────────────────────────────────────────────
# Capabilities
# ─────────────────────────────────────────────────────────────
def capabilities_for(user: dict) -> Set[Cap]:
    """Every capability this user holds.

    ADMIN holds everything implicitly — deliberately resolved as "all of Cap" rather than
    a maintained list, so a capability added in a later phase can never accidentally lock
    the module owner out of their own system.
    """
    role = hrms_role(user)
    if role is None:
        return set()
    if role == HrmsRole.ADMIN:
        return set(Cap)
    return set(ROLE_CAPABILITIES.get(role, set()))


def can(user: dict, capability: Cap) -> bool:
    """THE authorization question. Every HRMS gate — route, service or UI hint — resolves
    through this and nothing else."""
    return capability in capabilities_for(user)


def require_cap(capability: Cap):
    """FastAPI dependency factory enforcing one capability.

    Usage:  @router.get("/x", dependencies=[Depends(require_cap(Cap.AUDIT_READ))])
       or:  async def handler(user: dict = Depends(require_cap(Cap.AUDIT_READ)))
    Returns the user so the second form works.
    """
    async def _checker(current_user: dict = Depends(get_current_user)) -> dict:
        if not can(current_user, capability):
            raise HTTPException(status_code=403, detail=NO_ACCESS_MESSAGE)
        return current_user
    return _checker


# ─────────────────────────────────────────────────────────────
# Scoping
# ─────────────────────────────────────────────────────────────
def scope_company_id(user: dict, requested: str = None) -> Optional[str]:
    """The company a request should operate on.

    A client-side user is pinned to their own company — a requested id is ignored rather
    than honoured, so a crafted query string can never reach another tenant. Internal
    staff may target any company (or all, when `requested` is None).
    """
    if is_internal_user(user):
        return requested or None
    # A client participant works inside the TENANT's data, not their own company's -- their
    # own company holds no HRMS records at all. What narrows them to their own candidates
    # and requests is `scope_client_ids`, which is a different axis: this says WHOSE
    # database, that says WHICH ROWS in it. A requested id is ignored here exactly as it is
    # for any other client-side user.
    tenant = user.get(CLIENT_TENANT_FIELD)
    if tenant:
        return str(tenant)
    return str(user.get("company_id") or "") or None


def company_filter(user: dict, requested: str = None) -> dict:
    """A ready-made Mongo filter fragment applying tenant scoping.

    Returns `{}` for an internal user with no specific company (they see everything the
    data layer allows), otherwise `{"company_id": <scoped id>}`.
    """
    scoped = scope_company_id(user, requested)
    return {"company_id": scoped} if scoped else {}


# ─────────────────────────────────────────────────────────────
# Client scope — the SECOND narrowing, inside the tenant
# ─────────────────────────────────────────────────────────────
# `company_id` is and remains the security boundary. Client scope narrows FURTHER, inside
# one tenant, for users who belong to a client organisation rather than to this company.
# It never widens anything, and it never reaches across companies.
#
# -- Why the return type is Optional[list], not list ----------------------------------------
# Two situations look alike and must not be confused:
#
#     None  ->  the caller is NOT client-scoped (Sparsh HR, MD, Finance, a manager...).
#               No client filter applies, and their behaviour is exactly what it was
#               before client scope existed.
#
#     []    ->  the caller IS client-scoped but has no valid membership. Everything must
#               match NOTHING.
#
# Collapsing them into a single empty list would either lock out every HR user or open the
# gate for an unmapped client user, depending which way the collapse went. Both are wrong,
# and only one of them is loud.
def is_client_scoped_user(user: dict) -> bool:
    """Whether this user's access is narrowed to specific client organisations.

    A property of the RESOLVED ROLE, not of any request field. Nothing a caller sends can
    make them client-scoped, and nothing a caller sends can make them stop being.
    """
    return hrms_role(user) is HrmsRole.CLIENT


async def scope_client_ids(user: dict, company_id: str) -> Optional[list]:
    """The client ids this user may work on, or None if they are not client-scoped.

    Resolved ENTIRELY from the engagement records: an engagement of THIS company, whose
    status grants scope, listing THIS user as a member. A client id from a request is never
    consulted -- see the module note above and `assert_client_allowed`.

    Cross-company membership is impossible by construction rather than by a later check:
    `company_id` is part of the query, so an engagement belonging to another tenant simply
    is not found.

    Fails closed on ANY error. An access resolver that returns "unrestricted" because a
    database read failed is a resolver that opens the door when the lock breaks.
    """
    if not is_client_scoped_user(user):
        return None

    user_id = str(user.get("_id") or "")
    if not user_id or not company_id:
        return []

    try:
        rows = await get_collection(COLL_CLIENT_ENGAGEMENTS).find(
            {"company_id": str(company_id),
             "member_user_ids": user_id,
             "status": {"$in": sorted(ENGAGEMENT_GRANTS_SCOPE)}},
            {"client_id": 1}).to_list(200)
    except Exception as e:
        print(f"[WARN] HRMS client scope resolution failed for {user_id}: {e}")
        return []

    # Deduplicated and ordered so the value is stable between requests -- an unstable scope
    # makes a cached or logged decision impossible to compare against a later one.
    return sorted({str(r["client_id"]) for r in rows if r.get("client_id")})


def client_filter(allowed: Optional[list]) -> dict:
    """A Mongo filter fragment for a resolved client scope.

    Takes the RESOLVED scope, never a user and never a request, so there is no path by
    which a query parameter reaches this function.

        None -> {}                                (not client-scoped)
        []   -> {"client_id": {"$in": []}}        (scoped, no membership -> matches nothing)
        [..] -> {"client_id": {"$in": [...]}}

    The empty case is spelled out rather than short-circuited to `{}` on purpose: a caller
    that drops the filter when the list is empty turns "no clients" into "all clients",
    which is the single most likely way this control gets broken later.
    """
    if allowed is None:
        return {}
    return {"client_id": {"$in": list(allowed)}}


def assert_client_allowed(allowed: Optional[list], requested: Optional[str]) -> Optional[str]:
    """Reconcile a REQUESTED client id with the caller's resolved scope.

    This is the function that makes `?client_id=` a FILTER rather than an authorisation
    input. A requested id narrows what the caller already had; it can never add to it.

        not client-scoped   -> the request is honoured as a plain filter (Sparsh staff
                               choosing which client to look at)
        client-scoped, in scope   -> honoured
        client-scoped, out of scope -> 403
        client-scoped, nothing requested -> None, and the caller applies the full
                               `client_filter(allowed)` instead

    Returning the id rather than a boolean lets the caller build one filter and keeps the
    "which client" decision in one place.
    """
    if allowed is None:
        return str(requested) if requested else None
    if not requested:
        return None
    if str(requested) not in set(allowed):
        # 403 rather than an empty result set: the caller asked for something specific and
        # is entitled to know it was refused rather than to read silence as "no data".
        raise HTTPException(
            status_code=403,
            detail="You do not have access to that client.")
    return str(requested)
