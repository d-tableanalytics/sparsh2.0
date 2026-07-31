"""HRMS — module root.

Phase 0 (foundation) only: the access gate, the permission probe the UI renders its nav from,
and the router other HRMS phases hang off. Business endpoints arrive per phase — see
docs/HRMS_REPLICATION_ROADMAP.md.

Every route in this module sits behind `require_hrms_access` (internal Sparsh staff only), and
anything touching another person's record additionally checks a per-module permission via
`has_hrms_permission`. Two layers, matching how Task & Delegation gates itself.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from app.controllers.auth_controller import (
    require_hrms_access,
    has_hrms_access,
    has_hrms_permission,
    get_current_user,
)
from app.db.mongodb import get_collection
from app.models.hrms import (
    HRMS_PERMISSION_MODULES, HrmsAccessResponse,
    COL_EMPLOYEES, COL_EMPLOYEE_EVENTS, COL_ORG_MASTERS,
    ORG_KINDS, ORG_KIND_DEPARTMENT, ORG_KIND_DESIGNATION, ORG_KIND_LOCATION,
    EMPLOYEE_STATUSES, EMPLOYMENT_TYPES, WORK_MODES, EXITED_STATUSES,
    OrgMasterCreate, OrgMasterUpdate,
    EmployeeCreate, EmployeeUpdate, EmployeeEventCreate,
    EVENT_CREATED, EVENT_UPDATED, EVENT_STATUS_CHANGE, EVENT_EXIT, EVENT_NOTE,
)
from app.services.activity_log_service import log_activity
from app.services.hrms_employee_service import (
    can_read_personal_data, serialize_employee, serialize_event, serialize_org_master,
    add_employee_event, upsert_org_master, generate_employee_code,
    build_employee_query, get_employee_stats, find_employee, link_user_exists,
)

router = APIRouter(prefix="/hrms", tags=["HRMS"])


def _require(current_user: dict, module: str, action: str):
    """403 unless the caller holds `module.action`. The module gate (internal staff) is already
    applied by the route dependency; this is the second layer."""
    if not has_hrms_permission(current_user, module, action):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission for this HRMS action.",
        )


@router.get("/meta", response_model=HrmsAccessResponse)
async def hrms_meta(current_user: dict = Depends(require_hrms_access)):
    """What this user may do in the HRMS.

    The UI renders its HRMS nav from this rather than from role names, so the backend stays the
    single source of truth for access and a role rename can't silently open or hide a screen.
    """
    is_super = current_user.get("role") == "superadmin"
    perms = current_user.get("permissions", {}) or {}
    resolved = {
        module: {
            action: has_hrms_permission(current_user, module, action)
            for action in ("create", "read", "update", "delete")
        }
        for module in HRMS_PERMISSION_MODULES
    }
    return HrmsAccessResponse(
        has_access=True,
        permissions=resolved,
        is_superadmin=is_super,
        modules=HRMS_PERMISSION_MODULES,
        # Populated in Phase 1, once employee records exist and the caller can be matched to one.
        employee_code=None,
    )


@router.get("/access")
async def hrms_access(current_user: dict = Depends(get_current_user)):
    """Non-403 access probe.

    `/meta` 403s a user without the module, which is right for the app shell but wrong for a
    nav that simply wants to know whether to show the HRMS group. This answers that question
    for ANY authenticated user without raising.
    """
    return {"has_access": has_hrms_access(current_user)}
