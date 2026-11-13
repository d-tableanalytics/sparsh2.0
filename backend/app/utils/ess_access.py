"""Employee self-service (ESS) scope — who is an "employee login".

One rule, shared by every self-service screen, so the profile page and the settings pages
can never disagree about who is an employee:

  • People who maintain employee records — the System Admin, platform admins and HRMS
    roles holding employee.write (HR / Admin, MD) — are NOT restricted: they can already
    change anyone's record and configure policy, so hiding self-service from them adds
    nothing.
  • Everyone else is an employee login: they see only employee-relevant, approved
    functions. HR-controlled data is read-only, and policy (weekly offs, shifts, holidays,
    notification settings) is configured by authorised HR/Admin, not by the employee.
"""

PLATFORM_ADMIN_ROLES = {"superadmin", "admin"}


def manages_employee_records(user: dict) -> bool:
    if (user.get("role") or "").lower() in PLATFORM_ADMIN_ROLES:
        return True
    try:
        from app.utils.hrms_access import can
        from app.models.hrms import Cap
        return can(user, Cap.EMPLOYEE_WRITE)
    except Exception:
        return False   # HRMS unavailable for this user — treat as an employee (fail closed)


def is_employee_login(user: dict) -> bool:
    return not manages_employee_records(user)
