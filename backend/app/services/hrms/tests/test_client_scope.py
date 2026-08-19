"""Multi-client foundation -- client engagements and the client scope resolver.

Covers: engagement lifecycle, membership, `scope_client_ids`, the filter it builds, the
cross-company rejection, and the reconciliation of a REQUESTED client id against the
caller's resolved scope.

Two properties this file exists to protect, and they are the whole point of the phase:

  1. `None` IS NOT `[]`. A Sparsh HR user is not client-scoped, so no client filter applies
     and their behaviour is exactly what it was before. A CLIENT user with no membership is
     scoped to nothing, so everything must match nothing. Collapsing the two would either
     lock out every HR user or open the gate for an unmapped client user.

  2. A CLIENT ID FROM A REQUEST IS NOT AN AUTHORISATION. This is asserted end to end: a
     client-scoped user asking for somebody else's client is refused, and the scope they
     actually hold is unchanged by the asking. The test is written to fail loudly if a
     future change ever makes `request.client_id` an input to the decision.

House convention: self-contained, no pytest, fake collections, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_client_scope   (from backend/)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


async def expect_http(label: str, coro, status: int, fragment: str = None) -> None:
    from fastapi import HTTPException
    try:
        await coro
        check(f"{label} -> {status}", False)
    except HTTPException as e:
        ok = e.status_code == status
        if ok and fragment:
            ok = fragment.lower() in str(e.detail).lower()
        check(f"{label} -> {status}" + (f" ('{fragment}')" if fragment else ""), ok)
    except Exception as e:
        check(f"{label} -> {status} (got {type(e).__name__}: {e})", False)


def expect_http_sync(label: str, fn, status: int, fragment: str = None) -> None:
    from fastapi import HTTPException
    try:
        fn()
        check(f"{label} -> {status}", False)
    except HTTPException as e:
        ok = e.status_code == status
        if ok and fragment:
            ok = fragment.lower() in str(e.detail).lower()
        check(f"{label} -> {status}" + (f" ('{fragment}')" if fragment else ""), ok)


from app.services.hrms.tests.test_phase2_employee import FakeCollection  # noqa: E402

NOW = datetime.now(timezone.utc)


async def main() -> None:
    from bson import ObjectId

    from app.models import hrms as M
    import app.db.mongodb as mongo

    # SPARSH is the tenant. CLIENT_A / CLIENT_B are ERP companies it recruits for.
    # OTHER_TENANT is a different HRMS tenant entirely -- nothing may reach across it.
    SPARSH, OTHER_TENANT = str(ObjectId()), str(ObjectId())
    CLIENT_A, CLIENT_B, CLIENT_C = str(ObjectId()), str(ObjectId()), str(ObjectId())

    U_HR, U_MD = str(ObjectId()), str(ObjectId())
    U_CLIENT_A, U_CLIENT_AB, U_CLIENT_NONE = (str(ObjectId()), str(ObjectId()),
                                              str(ObjectId()))
    U_OTHER_TENANT, U_STAFF = str(ObjectId()), str(ObjectId())

    companies = FakeCollection([
        {"_id": ObjectId(SPARSH), "name": "Sparsh Magic", "is_active": True},
        {"_id": ObjectId(CLIENT_A), "name": "Client A Ltd", "is_active": True},
        {"_id": ObjectId(CLIENT_B), "name": "Client B Ltd", "is_active": True},
        {"_id": ObjectId(CLIENT_C), "name": "Client C Ltd", "is_active": False},
        {"_id": ObjectId(OTHER_TENANT), "name": "Another Tenant", "is_active": True},
    ])

    def learner(uid, name, governance, company=SPARSH, active=True):
        return {"_id": ObjectId(uid), "company_id": company, "full_name": name,
                "email": f"{name.lower().replace(' ', '.')}@example.com",
                "role": "clientuser", "governance_role": governance, "is_active": active}

    learners = FakeCollection([
        learner(U_HR, "Hana HR", "HR"),
        learner(U_MD, "Meera MD", "MD"),
        learner(U_CLIENT_A, "Alice ClientA", "CLIENT"),
        learner(U_CLIENT_AB, "Bob BothClients", "CLIENT"),
        learner(U_CLIENT_NONE, "Nia NoClient", "CLIENT"),
        learner(U_OTHER_TENANT, "Otto OtherTenant", "CLIENT", company=OTHER_TENANT),
    ])
    staff = FakeCollection([
        {"_id": ObjectId(U_STAFF), "full_name": "Sam Staff", "role": "admin",
         "email": "sam@example.com"},
    ])
    engagements = FakeCollection()
    audit_log = FakeCollection()

    store = {"companies": companies, "learners": learners, "staff": staff,
             M.COLL_CLIENT_ENGAGEMENTS: engagements, M.COLL_AUDIT_LOG: audit_log,
             M.COLL_COUNTERS: FakeCollection(), M.COLL_REQUISITIONS: FakeCollection(),
             M.COLL_CANDIDATES: FakeCollection()}
    original = mongo.get_collection
    mongo.get_collection = lambda name: store.setdefault(name, FakeCollection())

    import app.services.hrms_client_service as CS
    import app.services.hrms_audit_service as AUD
    import app.services.hrms_id_service as IDS
    import app.utils.hrms_access as ACCESS
    for mod in (CS, AUD, IDS, ACCESS):
        mod.get_collection = mongo.get_collection

    def actor(uid, governance, company=SPARSH, role="clientuser"):
        return {"_id": uid, "role": role, "_source_collection": "learners",
                "company_id": company, "governance_role": governance,
                "full_name": f"{governance} {uid[-4:]}"}

    HR = actor(U_HR, "HR")
    MD = actor(U_MD, "MD", role="clientadmin")
    CLIENT_A_USER = actor(U_CLIENT_A, "CLIENT")
    CLIENT_AB_USER = actor(U_CLIENT_AB, "CLIENT")
    CLIENT_NONE_USER = actor(U_CLIENT_NONE, "CLIENT")
    INTERNAL = {"_id": U_STAFF, "role": "admin", "_source_collection": "staff",
                "full_name": "Sam Staff"}

    try:
        # =================================================================
        section("The CLIENT role resolves, and changes nobody else")
        # =================================================================
        check("governance_role CLIENT resolves to HrmsRole.CLIENT",
              ACCESS.hrms_role(CLIENT_A_USER) is M.HrmsRole.CLIENT)
        check("HR still resolves to HR", ACCESS.hrms_role(HR) is M.HrmsRole.HR)
        check("MD still resolves to MD", ACCESS.hrms_role(MD) is M.HrmsRole.MD)
        check("a staff user still resolves to an internal role",
              ACCESS.hrms_role(INTERNAL) in (M.HrmsRole.ADMIN, M.HrmsRole.INTERNAL))

        check("a CLIENT user IS client-scoped",
              ACCESS.is_client_scoped_user(CLIENT_A_USER))
        check("an HR user is NOT client-scoped", not ACCESS.is_client_scoped_user(HR))
        check("an MD is NOT client-scoped", not ACCESS.is_client_scoped_user(MD))
        check("internal staff are NOT client-scoped",
              not ACCESS.is_client_scoped_user(INTERNAL))

        check("the CLIENT role's capabilities are deliberately minimal",
              {c.value for c in M.ROLE_CAPABILITIES[M.HrmsRole.CLIENT]}
              == {"module.access", "requisition.read", "client.read"})
        check("a CLIENT user cannot read candidates -- no client scope secures them yet",
              not ACCESS.can(CLIENT_A_USER, M.Cap.CANDIDATE_READ))
        check("nor documents", not ACCESS.can(CLIENT_A_USER, M.Cap.DOCUMENT_READ))
        check("nor analytics", not ACCESS.can(CLIENT_A_USER, M.Cap.ANALYTICS_READ))
        check("and cannot manage engagements",
              not ACCESS.can(CLIENT_A_USER, M.Cap.CLIENT_WRITE))
        check("MD can manage engagements", ACCESS.can(MD, M.Cap.CLIENT_WRITE))
        check("HR cannot -- opening a client is not a recruitment act",
              not ACCESS.can(HR, M.Cap.CLIENT_WRITE))

        # =================================================================
        section("Opening engagements")
        # =================================================================
        eng_a = await CS.create_engagement(MD, SPARSH, {"client_id": CLIENT_A})
        check("an engagement id is minted",
              eng_a["engagement_id"].startswith("CLI-ENG-"))
        check("it starts active", eng_a["status"] == "active")
        check("it points at the ERP company, duplicating nothing",
              eng_a["client_id"] == CLIENT_A and eng_a["client_name"] == "Client A Ltd")
        check("it grants nobody anything yet", eng_a["member_count"] == 0)
        check("opening one is audited",
              any(a["action"] == M.AUDIT_ENGAGEMENT_CREATED for a in audit_log.docs))

        eng_b = await CS.create_engagement(MD, SPARSH, {"client_id": CLIENT_B})

        await expect_http("a duplicate engagement",
                          CS.create_engagement(MD, SPARSH, {"client_id": CLIENT_A}),
                          409, "already have an engagement")
        await expect_http("engaging a company that does not exist",
                          CS.create_engagement(MD, SPARSH,
                                               {"client_id": str(ObjectId())}),
                          422, "does not exist")
        await expect_http("engaging an INACTIVE company",
                          CS.create_engagement(MD, SPARSH, {"client_id": CLIENT_C}),
                          422, "inactive")
        await expect_http("a company engaging ITSELF",
                          CS.create_engagement(MD, SPARSH, {"client_id": SPARSH}),
                          422, "cannot be its own client")

        listing = await CS.list_engagements(MD, SPARSH)
        check("both engagements are listed", listing["total"] == 2)
        check("another tenant sees none of them",
              (await CS.list_engagements(MD, OTHER_TENANT))["total"] == 0)

        # =================================================================
        section("Membership, and the cross-company rejection")
        # =================================================================
        await CS.add_engagement_member(MD, SPARSH, eng_a["engagement_id"], U_CLIENT_A)
        members = await CS.list_engagement_members(SPARSH, eng_a["engagement_id"])
        check("the member is recorded", members["total"] == 1)
        check("and is flagged as actually client-scoped",
              members["members"][0]["client_scoped"] is True)
        check("adding a member is audited",
              any(a["action"] == M.AUDIT_ENGAGEMENT_MEMBER_ADDED for a in audit_log.docs))

        await CS.add_engagement_member(MD, SPARSH, eng_a["engagement_id"], U_CLIENT_A)
        members = await CS.list_engagement_members(SPARSH, eng_a["engagement_id"])
        check("adding the same person twice does not duplicate the membership",
              members["total"] == 1)

        await expect_http(
            "adding a user of ANOTHER company",
            CS.add_engagement_member(MD, SPARSH, eng_a["engagement_id"], U_OTHER_TENANT),
            422, "belongs to another company")
        await expect_http(
            "adding an internal staff user",
            CS.add_engagement_member(MD, SPARSH, eng_a["engagement_id"], U_STAFF),
            422, "not client users")
        await expect_http(
            "adding a user that does not exist",
            CS.add_engagement_member(MD, SPARSH, eng_a["engagement_id"],
                                     str(ObjectId())),
            404, "not found")
        await expect_http(
            "adding to an engagement of another tenant",
            CS.add_engagement_member(MD, OTHER_TENANT, eng_a["engagement_id"],
                                     U_CLIENT_A),
            404, "Engagement not found")

        # Bob serves both clients.
        await CS.add_engagement_member(MD, SPARSH, eng_a["engagement_id"], U_CLIENT_AB)
        await CS.add_engagement_member(MD, SPARSH, eng_b["engagement_id"], U_CLIENT_AB)

        # =================================================================
        section("scope_client_ids — the resolver")
        # =================================================================
        # Test 1 — one client
        scope_a = await ACCESS.scope_client_ids(CLIENT_A_USER, SPARSH)
        check("a user of one client resolves to exactly that client",
              scope_a == [CLIENT_A])

        # Test 2 — multiple clients
        scope_ab = await ACCESS.scope_client_ids(CLIENT_AB_USER, SPARSH)
        check("a user serving two clients resolves to BOTH",
              scope_ab == sorted([CLIENT_A, CLIENT_B]))

        # Test 3 — no membership, fail closed
        scope_none = await ACCESS.scope_client_ids(CLIENT_NONE_USER, SPARSH)
        check("a CLIENT user with no membership resolves to [] -- not None",
              scope_none == [] and scope_none is not None)

        # Test 7 — existing Sparsh users are untouched
        check("an HR user resolves to None -- NOT client-scoped, not empty",
              await ACCESS.scope_client_ids(HR, SPARSH) is None)
        check("an MD resolves to None",
              await ACCESS.scope_client_ids(MD, SPARSH) is None)
        check("internal staff resolve to None",
              await ACCESS.scope_client_ids(INTERNAL, SPARSH) is None)

        # Test 4 — cross-company
        check("a client user resolves to NOTHING against another tenant",
              await ACCESS.scope_client_ids(CLIENT_A_USER, OTHER_TENANT) == [])
        check("and a user of another tenant resolves to nothing here",
              await ACCESS.scope_client_ids(
                  actor(U_OTHER_TENANT, "CLIENT", company=OTHER_TENANT), SPARSH) == [])

        # =================================================================
        section("Suspending an engagement revokes scope immediately")
        # =================================================================
        await CS.update_engagement(MD, SPARSH, eng_b["engagement_id"],
                                   {"status": "suspended"})
        scope_ab = await ACCESS.scope_client_ids(CLIENT_AB_USER, SPARSH)
        check("a suspended engagement stops granting scope",
              scope_ab == [CLIENT_A])
        members = await CS.list_engagement_members(SPARSH, eng_b["engagement_id"])
        check("without touching the membership record itself", members["total"] == 1)

        await CS.update_engagement(MD, SPARSH, eng_b["engagement_id"],
                                   {"status": "active"})
        check("reactivating restores it",
              await ACCESS.scope_client_ids(CLIENT_AB_USER, SPARSH)
              == sorted([CLIENT_A, CLIENT_B]))

        await CS.remove_engagement_member(MD, SPARSH, eng_b["engagement_id"], U_CLIENT_AB)
        check("removing a member revokes that client",
              await ACCESS.scope_client_ids(CLIENT_AB_USER, SPARSH) == [CLIENT_A])

        # =================================================================
        section("client_filter — Test 5 and Test 6")
        # =================================================================
        check("a resolved scope becomes an $in filter",
              ACCESS.client_filter([CLIENT_A, CLIENT_B])
              == {"client_id": {"$in": [CLIENT_A, CLIENT_B]}})
        check("an EMPTY scope becomes $in: [] -- it does NOT drop the filter",
              ACCESS.client_filter([]) == {"client_id": {"$in": []}})
        check("and None means no client filter at all, for a Sparsh user",
              ACCESS.client_filter(None) == {})

        # The composition rule: client scope narrows, never replaces.
        base = {"company_id": SPARSH}
        composed = dict(base)
        composed.update(ACCESS.client_filter([CLIENT_A]))
        composed.update({"request_no": {"$in": ["HR-REQ-1"]}})
        check("client scope COMPOSES with company and manager scope, replacing neither",
              composed == {"company_id": SPARSH,
                           "client_id": {"$in": [CLIENT_A]},
                           "request_no": {"$in": ["HR-REQ-1"]}})

        # =================================================================
        section("Test 10 / §23 — a requested client id is NOT an authorisation")
        # =================================================================
        # THE test of this phase. It must fail if anybody ever makes
        # `request.client_id` an input to the access decision.
        scope_a = await ACCESS.scope_client_ids(CLIENT_A_USER, SPARSH)

        expect_http_sync(
            "Client A's user explicitly asking for Client B",
            lambda: ACCESS.assert_client_allowed(scope_a, CLIENT_B),
            403, "do not have access to that client")

        after = await ACCESS.scope_client_ids(CLIENT_A_USER, SPARSH)
        check("and their resolved scope is UNCHANGED by the asking", after == [CLIENT_A])
        check("the filter built from it still names only their own client",
              ACCESS.client_filter(after) == {"client_id": {"$in": [CLIENT_A]}})

        check("asking for their OWN client is honoured",
              ACCESS.assert_client_allowed(scope_a, CLIENT_A) == CLIENT_A)
        check("asking for nothing leaves the full scope to be applied",
              ACCESS.assert_client_allowed(scope_a, None) is None)

        # A Sparsh user is not client-scoped, so a requested id is a plain filter.
        check("a Sparsh user may filter by any client they name",
              ACCESS.assert_client_allowed(None, CLIENT_B) == CLIENT_B)
        check("and naming none leaves them unfiltered",
              ACCESS.assert_client_allowed(None, None) is None)

        # A client user with NO membership cannot reach anything, named or not.
        expect_http_sync(
            "a CLIENT user with no membership naming any client at all",
            lambda: ACCESS.assert_client_allowed([], CLIENT_A),
            403, "do not have access")
        check("and their filter matches nothing",
              ACCESS.client_filter([]) == {"client_id": {"$in": []}})

        # =================================================================
        section("require_engagement — the §7 primitive")
        # =================================================================
        check("an active engagement resolves",
              (await CS.require_engagement(SPARSH, CLIENT_A))["client_id"] == CLIENT_A)
        await expect_http(
            "a company that exists but is not our client",
            CS.require_engagement(SPARSH, CLIENT_C),
            422, "not a client of yours")
        await CS.update_engagement(MD, SPARSH, eng_b["engagement_id"],
                                   {"status": "ended"})
        await expect_http(
            "an engagement that has ended",
            CS.require_engagement(SPARSH, CLIENT_B),
            422, "reactivate it")
        check("engaged_client_ids lists only scope-granting engagements",
              await CS.engaged_client_ids(SPARSH) == [CLIENT_A])

        # =================================================================
        section("Test 8 — internal recruitment is untouched")
        # =================================================================
        check("the internal track still carries no client",
              M.RequisitionTrack.INTERNAL.value == "internal")
        check("and its approval chain is unchanged",
              M.budget_approval_is_mandatory())
        check("the client track's chain is unchanged too",
              M.md_approval_is_mandatory())
        check("an internal requisition's client scope is not even a question -- a Sparsh "
              "user resolves to None",
              await ACCESS.scope_client_ids(HR, SPARSH) is None)

    finally:
        mongo.get_collection = original

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
