"""Shared test helper: activate a policy version THROUGH the §27 change flow.

Not a suite -- deliberately named without the `test_` prefix so the runner's `test_*.py`
glob does not pick it up as one.

Gap 5 closed the direct route from Draft to Active: `set_status` refuses Approved and
Active for a governed policy, because anyone holding config.approve could otherwise walk a
version live through one endpoint with no impact analysis, no simulation and no second pair
of eyes -- and could approve a rule they drafted themselves.

Several suites need an ACTIVE version as setup, not as their subject. They could each
repeat the five calls, or there could be a test-only back door into `set_status`. A back
door is the wrong answer: it would mean the suites that depend on an active policy stop
exercising the path that actually produces one, so the flow could break and only the one
suite that tests it directly would notice. This drives the real calls instead.

    await activate_policy_version(CC, HR, APPROVER, CO, M.POLICY_ATT_DAY, 1)

`drafter` and `approver` must be different people; `decide()` refuses otherwise, which is
the rule this helper exists to keep honest rather than route around.
"""
from __future__ import annotations

_counter = {"n": 0}


def _fake_business_id(CC) -> None:
    """Give the flow an id generator that does not need a live sequence collection."""
    if getattr(CC.next_business_id, "_is_test_stub", False):
        return

    async def _next(kind, company, year):
        _counter["n"] += 1
        return f"CFG-T{_counter['n']:04d}"

    _next._is_test_stub = True
    CC.next_business_id = _next


async def activate_policy_version(CC, drafter: dict, approver: dict, company_id: str,
                                  policy_code: str, version_no: int,
                                  reason: str = "Test setup: activate this version") -> dict:
    """Request -> Impact -> Submit -> Approve -> Activate, as a real user would.

    Returns the activated change request. The version is left Active, with the scope
    assignments it already carries -- assign the scope BEFORE calling this, exactly as the
    designer does, since activation is what supersedes same-population rivals.
    """
    from app.models.hrms import CONFIG_ENTITY_POLICY_VERSION

    _fake_business_id(CC)
    request = await CC.create_request(drafter, company_id, {
        "entity_type": CONFIG_ENTITY_POLICY_VERSION, "entity_code": policy_code,
        "version_no": version_no, "reason": reason})
    no = request["request_no"]
    await CC.analyse_impact(drafter, company_id, no)
    await CC.submit(drafter, company_id, no)
    await CC.decide(approver, company_id, no, {"action": "approve", "comments": "Test setup"})
    return await CC.activate(approver, company_id, no)
