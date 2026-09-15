"""HRMS > Employee 360° (BA/Functional Design v2.2, §6).

A single, aggregated workspace pulling together everything a company's OTHER modules already
track about one employee — attendance, leave, movements, discipline, PIP, exit/separation
history and probation — rather than a new record of its own. §6 asks for a workspace, not a
new source of truth, so this module owns no collection: every section below is produced by
calling straight into the module that already owns that data (hrms_attendance_service,
hrms_leave_service, hrms_movement_service, hrms_discipline_service, hrms_pip_service,
hrms_exit_service, hrms_probation_service), never by reading their collections directly.

-- Permission-controlled, section by section, not a second access-control system -----------
§17 step 136 (discipline) and §22.5 step 222 (PIP) both say the same thing in different
words: a "restricted" record is visible in Employee 360° only to someone AUTHORISED to see
it there too, not to everyone who can open the workspace. This module does not invent a new
permission model to enforce that — it checks the SAME capability each section's own screen
already requires (Cap.ATTENDANCE_READ, Cap.DISCIPLINE_READ, and so on) and simply OMITS a
section entirely when the caller lacks it, the same "absent, not a placeholder" discipline
hrms_employee_service already uses for salary. A caller who cannot see a section on its own
screen cannot see it stitched into this one either.

-- Self-view is the same inherent right the base profile already grants -------------------
`get_employee_360` calls hrms_employee_service.get_employee FIRST and lets it decide whether
the caller may see this employee at all (an inherent right for their own record, EMPLOYEE_READ
otherwise) — the entry gate for the whole workspace is that decision, not a new one.
"""
from typing import Optional

from app.db.mongodb import get_collection
from app.models.hrms import COLL_PROBATION_REVIEWS, Cap
from app.services import hrms_employee_service as employees
from app.utils.hrms_access import can


async def _probation_summary(company_id: str, employee_code: str) -> Optional[dict]:
    row = await get_collection(COLL_PROBATION_REVIEWS).find_one(
        {"company_id": str(company_id), "employee_code": employee_code},
        sort=[("started_on", -1)])
    if not row:
        return None
    return {
        "prb_no": row.get("prb_no"), "started_on": row.get("started_on"),
        "ends_on": row.get("ends_on"), "outcome": row.get("outcome"),
        "rating": row.get("rating"),
    }


async def get_employee_360(actor: dict, company_id: str, user_id: str) -> dict:
    # The base profile IS the entry gate: self-view is an inherent right there, otherwise
    # EMPLOYEE_READ is required — this call raises 403/404 on its own if the caller may not
    # see this employee at all, before any section below is even considered.
    profile = await employees.get_employee(actor, user_id, company_id=company_id)
    employee_code = profile.get("employee_code")

    view = {"profile": profile}
    if not employee_code:
        # An onboarding-stage record with no employee_code yet has nothing else to compose —
        # every other module below addresses people by employee_code.
        return view

    if can(actor, Cap.PROBATION_READ):
        view["probation"] = await _probation_summary(company_id, employee_code)

    if can(actor, Cap.ATTENDANCE_READ):
        from app.services import hrms_attendance_service as attendance_mgmt
        view["recent_attendance"] = await attendance_mgmt.list_attendance(
            actor, company_id, employee_code=employee_code, limit=30)
        view["late_coming"] = await attendance_mgmt.late_coming_summary(
            actor, company_id, employee_code=employee_code)

    if can(actor, Cap.LEAVE_READ):
        from app.services import hrms_leave_service as leave_mgmt
        view["leave_balances"] = await leave_mgmt.get_leave_balances(actor, company_id, employee_code)
        view["recent_leaves"] = await leave_mgmt.list_leaves(
            actor, company_id, employee_code=employee_code, limit=10)

    if can(actor, Cap.MOVEMENT_READ):
        from app.services import hrms_movement_service as movement_mgmt
        view["movements"] = await movement_mgmt.list_movements(
            actor, company_id, employee_code=employee_code, limit=50)

    if can(actor, Cap.DISCIPLINE_READ):
        from app.services import hrms_discipline_service as discipline_mgmt
        # employee_summary is already the "permission-controlled summary" §17 step 136
        # asks for — POSH/Restricted cases stay excluded unless the caller separately holds
        # POSH access, exactly as the standalone Discipline screen already enforces.
        view["discipline_summary"] = await discipline_mgmt.employee_summary(
            actor, company_id, employee_code)

    if can(actor, Cap.PIP_READ):
        from app.services import hrms_pip_service as pip_mgmt
        view["pip_history"] = await pip_mgmt.list_pips(
            actor, company_id, employee_code=employee_code, limit=20)

    if can(actor, Cap.SEPARATION_READ):
        from app.services import hrms_exit_service as exit_mgmt
        view["separation_history"] = await exit_mgmt.list_separations(
            actor, company_id, employee_code=employee_code, limit=10)

    if can(actor, Cap.ABSCONDING_READ):
        from app.services import hrms_absconding_service as absconding_mgmt
        view["absconding_history"] = await absconding_mgmt.list_cases(
            actor, company_id, employee_code=employee_code, limit=10)

    if can(actor, Cap.LETTER_READ):
        from app.services import hrms_letter_service as letter_mgmt
        view["letters"] = await letter_mgmt.list_letters(
            actor, company_id, employee_code=employee_code, limit=20)

    if can(actor, Cap.INDUCTION_READ):
        from app.services import hrms_orientation_service as orientation_mgmt
        view["orientation"] = await orientation_mgmt.get_assignment(
            actor, company_id, employee_code)

    if can(actor, Cap.PULSE_READ):
        # §22.4 step 214: "linked to Employee 360° where permitted" — PULSE_READ is the
        # permission this phase defines that boundary with (see its own Cap comment).
        from app.services import hrms_pulse_service as pulse_mgmt
        view["pulse_surveys"] = await pulse_mgmt.list_responses(
            actor, company_id, employee_code=employee_code, limit=10)

    # ── BR-028 — the Appointment Letter, if one was ever raised. Appointments are keyed by
    # candidate `uk`, not employee_code — profile["source_uk"] is the join hrms_onboarding_
    # service stamps at Employee ID generation, the same link hrms_appointment_service's own
    # EMPLOYEE self-scope resolves independently.
    if can(actor, Cap.APPOINTMENT_READ) and profile.get("source_uk"):
        from app.services import hrms_appointment_service as appointment_mgmt
        letters = await appointment_mgmt.list_appointments(
            actor, company_id, uk=profile["source_uk"])
        view["appointment"] = (letters.get("appointments") or [None])[0]

    # ── Phase GMP-1 (§22 "GMP section") ──
    if can(actor, Cap.GMP_READ):
        from app.services import hrms_gmp_service as gmp_mgmt
        view["gmp"] = await gmp_mgmt.get_gmp(actor, company_id, employee_code)

    return view
