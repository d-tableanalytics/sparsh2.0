"""HRMS > Roles & Permissions -- the catalogue, the defaults, and the company's rules.

Every HRMS action is a capability (Cap). This service presents them the way an HR admin
thinks about them -- MODULE > WORKFLOW STEP > ACTION, in the order the process runs -- and
lets the MD / Admin decide, per action, which roles and which people may do it.

The DEFAULT for each action is what the code grants (ROLE_CAPABILITIES plus the fixed
adjustments in capabilities_for). A saved rule replaces that default for its company;
resetting deletes the rule. The rules themselves are applied in hrms_permission_policy.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from app.db.mongodb import get_collection
from app.models.hrms import COLL_PERMISSION_POLICIES, ROLE_CAPABILITIES, Cap, HrmsRole
from app.services.hrms_audit_service import audit
from app.utils import hrms_permission_policy as policy

ENTITY_PERMISSION = "permission"
AUDIT_PERMISSION_CHANGED = "permission rule changed"
AUDIT_PERMISSION_RESET = "permission rule reset to default"

# The roles an admin assigns actions to, in the order they read on screen. The superadmin
# is not a choice: it always holds everything.
CONFIGURABLE_ROLES = [
    (HrmsRole.EMPLOYEE, "Employee"),
    (HrmsRole.MANAGER, "HOD / Manager"),
    (HrmsRole.HR, "HR"),
    (HrmsRole.FINANCE, "Finance"),
    (HrmsRole.MD, "MD"),
    (HrmsRole.INTERNAL, "Admin (support)"),
]

_VERB = {
    "read": "View", "write": "Create & edit", "create": "Create", "manage": "Manage",
    "approve": "Approve", "review": "Review", "send": "Send", "submit": "Submit",
    "decide": "Decide", "request": "Request", "initiate": "Start", "close": "Close",
    "act": "Act on", "prepare": "Prepare", "process": "Process", "confirm": "Confirm",
    "acknowledge": "Acknowledge", "export": "Export", "verify": "Verify", "schedule": "Schedule",
    "evaluate": "Evaluate", "mark": "Mark",
}

# MODULE > STEP > [(capability, label or None for an automatic label)]. In process order.
CATALOGUE = [
    ("Internal hiring — requisition & planning", [
        ("Manpower requisition", [
            ("requisition.create", "Raise a manpower requisition"),
            ("requisition.read", "View requisitions"),
            ("requisition.write", "Edit a requisition"),
            ("requisition.close", "Close a requisition"),
        ]),
        ("HR verification", [("requisition.review_hr", "Verify a requisition (HR check)")]),
        ("Headcount & budget", [
            ("requisition.approve_budget", "Approve headcount & budget"),
            ("sanction.read", "View sanctioned strength"),
            ("sanction.write", "Set sanctioned strength"),
            ("salary_band.read", "View salary bands"),
            ("salary_band.write", "Set salary bands"),
        ]),
        ("Management approval (over strength)", [
            ("requisition.escalate", "Give Management approval"),
            ("requisition.approve_md", "MD approval authority on requisitions"),
        ]),
        ("Job description", [("jd.read", "View JDs"), ("jd.write", "Write & edit JDs")]),
        ("Position scorecard", [
            ("scorecard.read", "View scorecards"),
            ("scorecard.write", "Draft a scorecard"),
            ("scorecard.approve", "Approve a scorecard (approves the requisition)"),
        ]),
    ]),
    ("Internal hiring — sourcing & screening", [
        ("Job posting", [
            ("posting.read", "View job postings"),
            ("posting.write", "Create & publish job postings"),
            ("posting.approve_exec_search", "Approve executive search"),
        ]),
        ("Candidates", [
            ("candidate.read", "View candidates"),
            ("candidate.write", "Add & edit candidates"),
            ("candidate.screen", "Screen CVs & shortlist"),
        ]),
        ("Telephonic screen", [("telephonic.read", None), ("telephonic.write", "Record a phone screen")]),
        ("Assessment", [
            ("assessment.read", None), ("assessment.send", "Send an assessment"),
            ("assessment.review", "Review an assessment"),
        ]),
    ]),
    ("Internal hiring — interview & selection", [
        ("Interviews", [
            ("interview.read", "View all interviews"),
            ("interview.schedule", "Schedule interviews"),
            ("interview.evaluate", "Evaluate an interview"),
            ("interview.decide_md", "Record the MD's final decision"),
            ("interview.media", "Attach interview recordings"),
        ]),
        ("Shortlist committee", [
            ("shortlist.read", "View & answer committee requests"),
            ("shortlist.convene", "Send the committee approval request"),
            ("shortlist.write", "Manage committee sittings"),
        ]),
        ("References", [("reference.read", None), ("reference.write", "Record a reference check")]),
        ("Negotiation", [("negotiation.read", None), ("negotiation.write", "Record a negotiation round")]),
        ("Exceptions", [
            ("exception.read", None), ("exception.write", "Raise an exception"),
            ("exception.approve", "Approve an exception"),
        ]),
    ]),
    ("Offer & joining", [
        ("Background verification", [
            ("background.read", None), ("background.write", "Record & update checks"),
            ("background.approve", "Approve the verification"),
        ]),
        ("Offer", [
            ("offer.read", None), ("offer.write", "Create & edit offers"),
            ("offer.approve", "Approve an offer"), ("offer.send", "Send an offer"),
        ]),
        ("Appointment letter", [
            ("appointment.read", None), ("appointment.write", "Generate an appointment letter"),
            ("appointment.send", "Send an appointment letter"),
        ]),
        ("Pre-boarding", [("preboarding.read", None), ("preboarding.write", None)]),
        ("Onboarding", [
            ("onboarding.read", None), ("onboarding.write", "Run onboarding"),
            ("onboarding.generate_id", "Issue the Employee ID"),
        ]),
        ("Documents", [("document.read", None), ("document.write", "Upload documents"),
                       ("document.verify", "Verify documents")]),
        ("Candidate links", [("link.read", None), ("link.manage", None)]),
    ]),
    ("After joining", [
        ("Induction & training", [("induction.read", None), ("induction.write", None)]),
        ("Pulse surveys", [("pulse.read", None), ("pulse.manage", None),
                           ("pulse.submit", None), ("survey.read", "View survey results")]),
        ("Probation", [("probation.read", None), ("probation.review", "Review probation"),
                       ("probation.confirm", "Confirm an employee")]),
    ]),
    ("Employees & organisation", [
        ("Employees", [
            ("employee.read", "View employees"), ("employee.write", "Add & edit employees"),
            ("employee.salary.read", "View salaries"), ("employee.salary.write", "Change salaries"),
        ]),
        ("Departments & designations", [
            ("department.read", None), ("department.write", "Manage departments"),
            ("designation.read", None), ("designation.write", "Manage designations"),
        ]),
        ("Letters", [("letter.read", None), ("letter.manage", "Issue & manage letters")]),
        ("Policies", [("policy.read", None), ("policy.write", None), ("policy.approve", None),
                      ("policy.acknowledge", None)]),
        ("Good manufacturing practice", [("gmp.read", None), ("gmp.write", None)]),
        ("Communications", [("comm.read", None), ("comm.write", "Send communications"),
                            ("comm.template.write", "Edit message templates")]),
    ]),
    ("Attendance & leave", [
        ("Attendance", [
            ("attendance.read", None), ("attendance.mark", "Mark attendance"),
            ("attendance.self_punch", "Self check-in / check-out (at an office)"),
            ("attendance.import", "Import the biometric file"),
            ("attendance.flexi_request", "Request flexible timing"),
            ("attendance.flexi_approve", "Approve flexible timing"),
            ("attendance.regularize_request", "Request a regularisation"),
            ("attendance.regularize_approve", "Approve regularisations"),
            ("attendance.lock", "Lock the month"), ("attendance.closure_read", "View month closure"),
        ]),
        ("On duty", [("od.request", "Request on duty"), ("od.approve", "Approve on duty")]),
        ("Leave", [("leave.read", None), ("leave.apply", "Apply for leave"),
                   ("leave.approve", "Approve leave"), ("leave.policy_manage", "Manage leave policy")]),
        ("Comp-off", [("coff.earn_request", "Claim a comp-off"), ("coff.approve", "Approve comp-offs")]),
    ]),
    ("Payroll", [
        ("Payroll run", [("payroll.read", None), ("payroll.process", "Process payroll"),
                         ("payroll.approve", "Approve payroll")]),
        ("Salary structure", [("salary_structure.read", None),
                              ("salary_structure.manage", "Set salary structures")]),
        ("Salary advance", [("advance.read", None), ("advance.request", "Request an advance"),
                            ("advance.approve", "Approve advances"),
                            ("advance.approve_emergency", "Approve emergency advances")]),
        ("Variable pay", [("variable_pay.read", None), ("variable_pay.process", None),
                          ("variable_pay.approve", None), ("variable_pay.hold_manage", "Manage holds")]),
    ]),
    ("Performance & conduct", [
        ("PIP", [("pip.read", None), ("pip.manage", "Start & run a PIP"), ("pip.decide", "Decide a PIP"),
                 ("pip.acknowledge", "Acknowledge a PIP")]),
        ("Movements", [("movement.read", None), ("movement.initiate", "Propose a movement"),
                       ("movement.approve", "Approve a movement")]),
        ("Discipline", [("discipline.read", None), ("discipline.manage", None),
                        ("discipline.decide", None), ("discipline.posh_read", "View POSH cases"),
                        ("discipline.posh_manage", "Manage POSH cases")]),
        ("Absconding", [("absconding.read", None), ("absconding.manage", None),
                        ("absconding.decide", None)]),
        ("Retirement alerts", [("retirement_alert.read", None)]),
    ]),
    ("Exit", [
        ("Separation", [("separation.read", None), ("separation.initiate", "Start a separation"),
                        ("separation.manage", None), ("separation.approve", None)]),
        ("Handover", [("handover.read", None), ("handover.write", None), ("handover.approve", None)]),
        ("Clearance", [("clearance.read", None), ("clearance.manage", None), ("clearance.act", None)]),
        ("Exit interview", [("exit_interview.read", None), ("exit_interview.write", None),
                            ("exit_interview.submit", None)]),
        ("Full & final", [("fnf.read", None), ("fnf.prepare", "Prepare F&F"), ("fnf.approve", "Approve F&F")]),
        ("Personnel file", [("personnel_file.close", "Close a personnel file")]),
    ]),
    ("Reports & administration", [
        ("Reports & analytics", [("report.read", None), ("report.export", None),
                                 ("analytics.read", "View analytics")]),
        ("Audit trail", [("audit.read", "View the audit trail")]),
        ("Settings", [("settings.read", None), ("settings.write", "Change HRMS settings"),
                      ("module.admin", "Administer HRMS users & roles")]),
        ("Data retention", [("retention.purge", "Purge expired records")]),
    ]),
]


def _auto_label(cap: Cap) -> str:
    action = cap.value.split(".", 1)[1]
    return _VERB.get(action, action.replace("_", " ").replace(".", " ").capitalize())


def default_roles(cap: Cap) -> list:
    """The roles that hold `cap` by default (for Sparsh's internal staff)."""
    from app.utils.hrms_access import MD_REVIEW_ONLY_WITHHELD, STAFF_SELF_SERVICE_CAPS
    out = []
    for role, _ in CONFIGURABLE_ROLES:
        caps = set(ROLE_CAPABILITIES.get(role, set())) | set(STAFF_SELF_SERVICE_CAPS)
        if Cap.ATTENDANCE_LOCK in caps or role == HrmsRole.MD:
            caps.add(Cap.ATTENDANCE_CLOSURE_READ)
        if role == HrmsRole.MD:
            caps -= MD_REVIEW_ONLY_WITHHELD
        if cap in caps:
            out.append(role.value)
    return out


def _cap(value: str) -> Cap:
    try:
        cap = Cap(value)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown HRMS action.")
    if not policy.is_editable(cap):
        raise HTTPException(status_code=422,
                            detail="This action cannot be configured (it is fixed for safety).")
    return cap


async def _names(company_id: str, ids) -> list:
    from app.utils.hrms_access import tenant_member
    out = []
    for uid in ids or []:
        person = await tenant_member(company_id, str(uid), {"full_name": 1, "email": 1})
        out.append({"user_id": str(uid),
                    "name": (person or {}).get("full_name") or (person or {}).get("email")
                    or "Unknown user"})
    return out


async def list_permissions(company_id: str) -> dict:
    """The whole catalogue, with each action's default and the company's current rule."""
    rules = {r["cap"]: r for r in await get_collection(COLL_PERMISSION_POLICIES).find(
        {"company_id": str(company_id)}).to_list(1000)}
    listed, modules = set(), []

    async def row(value: str, label: Optional[str]) -> Optional[dict]:
        try:
            cap = Cap(value)
        except ValueError:
            return None
        if not policy.is_editable(cap):
            return None
        listed.add(cap)
        rule = rules.get(value)
        defaults = default_roles(cap)
        return {
            "cap": value, "label": label or _auto_label(cap),
            "default_roles": defaults,
            "roles": list(rule["roles"]) if rule else defaults,
            "customised": bool(rule),
            "allow_users": await _names(company_id, (rule or {}).get("allow_users")),
            "deny_users": await _names(company_id, (rule or {}).get("deny_users")),
            "updated_by_name": (rule or {}).get("updated_by_name"),
            "updated_at": (rule or {}).get("updated_at"),
        }

    for module, steps in CATALOGUE:
        out_steps = []
        for step, actions in steps:
            rows = [r for r in [await row(v, lbl) for v, lbl in actions] if r]
            if rows:
                out_steps.append({"step": step, "actions": rows})
        modules.append({"module": module, "steps": out_steps})
    # Anything the catalogue does not name yet still appears, so nothing is unconfigurable.
    rest = [c for c in Cap if policy.is_editable(c) and c not in listed]
    if rest:
        modules.append({"module": "Other actions", "steps": [
            {"step": "Other", "actions": [await row(c.value, None) for c in rest]}]})
    return {
        "roles": [{"value": r.value, "label": lbl} for r, lbl in CONFIGURABLE_ROLES],
        "modules": modules,
        "customised": len(rules),
    }


async def save_permission(actor: dict, company_id: str, cap_value: str, payload: dict) -> dict:
    """Set who may do one action: roles, plus people always allowed / never allowed."""
    cap = _cap(cap_value)
    valid_roles = {r.value for r, _ in CONFIGURABLE_ROLES}
    roles = [r for r in (payload.get("roles") or []) if r in valid_roles]
    bad = [r for r in (payload.get("roles") or []) if r not in valid_roles]
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown role(s): {', '.join(bad)}.")

    from app.utils.hrms_access import tenant_member
    people = {}
    for key in ("allow_users", "deny_users"):
        ids = []
        for uid in payload.get(key) or []:
            uid = str(uid).strip()
            if not uid or uid in ids:
                continue
            if not await tenant_member(company_id, uid, {"_id": 1}):
                raise HTTPException(status_code=422,
                                    detail="Every person must be a user of this company.")
            ids.append(uid)
        people[key] = ids
    both = set(people["allow_users"]) & set(people["deny_users"])
    if both:
        raise HTTPException(status_code=422,
                            detail="A person cannot be both always allowed and blocked.")

    now = datetime.now(timezone.utc)
    await get_collection(COLL_PERMISSION_POLICIES).update_one(
        {"company_id": str(company_id), "cap": cap.value},
        {"$set": {"company_id": str(company_id), "cap": cap.value, "roles": roles,
                  "allow_users": people["allow_users"], "deny_users": people["deny_users"],
                  "updated_by": str(actor.get("_id") or ""),
                  "updated_by_name": actor.get("full_name") or actor.get("email"),
                  "updated_at": now}},
        upsert=True)
    await audit(actor, AUDIT_PERMISSION_CHANGED, ENTITY_PERMISSION, cap.value,
                f"roles: {', '.join(roles) or 'none'}; allowed: {len(people['allow_users'])}; "
                f"blocked: {len(people['deny_users'])}", company_id)
    await policy.refresh(str(company_id), force=True)
    return await list_permissions(company_id)


async def reset_permission(actor: dict, company_id: str, cap_value: str) -> dict:
    """Back to the default for one action (the company's rule is deleted)."""
    cap = _cap(cap_value)
    await get_collection(COLL_PERMISSION_POLICIES).delete_one(
        {"company_id": str(company_id), "cap": cap.value})
    await audit(actor, AUDIT_PERMISSION_RESET, ENTITY_PERMISSION, cap.value,
                "reset to default", company_id)
    await policy.refresh(str(company_id), force=True)
    return await list_permissions(company_id)
