"""Inter-Departmental Feedback API (/api/idf). Rules live in app/services/idf_*.py.

  GET  /idf/access                          what the caller may do (drives the menu)
  GET|PUT /idf/setup                        parameters, deadlines, comment rule — HR / Admin / MD / Sparsh Admin
  GET  /idf/cycles/options                  start-cycle dialog: departments + HODs from Team, last mapping
  GET|POST /idf/cycles                      list / start a feedback cycle — HR / Admin / MD
  GET  /idf/cycles/{id}/status              submission status only (no content) — HR / Admin / MD
  POST /idf/cycles/{id}/cancel
  GET  /idf/my-forms, POST /idf/submit      the HOD's forms for the open cycle
  GET  /idf/dashboard                       the complete management dashboard — MD only
  GET  /idf/reports/{cycle_id}/{kind}       compiled | analysis | pdf — MD only
  GET  /idf/actions, PATCH /idf/actions/{id} action plans — MD, TPS Coordinator, owners (their own)
"""
import io
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import StreamingResponse

from app.controllers.auth_controller import get_current_user
from app.services import idf_analysis as analysis
from app.services import idf_reports as reports
from app.services import idf_service as idf

router = APIRouter(prefix="/idf", tags=["Inter-Departmental Feedback"])


@router.get("/access")
async def idf_access(current_user: dict = Depends(get_current_user)):
    return await idf.access(current_user)


@router.get("/setup")
async def idf_get_setup(company_id: Optional[str] = Query(None), current_user: dict = Depends(get_current_user)):
    return await idf.get_setup(current_user, company_id)


@router.put("/setup")
async def idf_save_setup(payload: dict = Body(...), company_id: Optional[str] = Query(None),
                         current_user: dict = Depends(get_current_user)):
    return await idf.save_setup(current_user, company_id, payload)


@router.get("/cycles/options")
async def idf_cycle_options(company_id: Optional[str] = Query(None), current_user: dict = Depends(get_current_user)):
    """Start-cycle dialog: departments with their HOD(s) from Team + the last cycle's mapping."""
    return await idf.cycle_options(current_user, company_id)


@router.get("/cycles")
async def idf_cycles(company_id: Optional[str] = Query(None), current_user: dict = Depends(get_current_user)):
    return await idf.list_cycles(current_user, company_id)


@router.post("/cycles", status_code=201)
async def idf_start_cycle(payload: dict = Body(...), company_id: Optional[str] = Query(None),
                          current_user: dict = Depends(get_current_user)):
    return await idf.start_cycle(current_user, company_id, payload)


@router.get("/cycles/{cycle_id}/status")
async def idf_cycle_status(cycle_id: str, company_id: Optional[str] = Query(None),
                           current_user: dict = Depends(get_current_user)):
    return await idf.cycle_status(current_user, company_id, cycle_id)


@router.get("/cycles/{cycle_id}/delete-preview")
async def idf_delete_preview(cycle_id: str, company_id: Optional[str] = Query(None),
                             current_user: dict = Depends(get_current_user)):
    """What deleting this cycle removes (MD, Client Admin, Super Admin)."""
    return await idf.delete_preview(current_user, company_id, cycle_id)


@router.delete("/cycles/{cycle_id}")
async def idf_delete_cycle(cycle_id: str, confirm: str = Query(""), company_id: Optional[str] = Query(None),
                           current_user: dict = Depends(get_current_user)):
    return await idf.delete_cycle(current_user, company_id, cycle_id, confirm)


@router.delete("/issues/{issue_id}")
async def idf_delete_issue(issue_id: str, company_id: Optional[str] = Query(None),
                           current_user: dict = Depends(get_current_user)):
    from app.services import idf_process
    return await idf_process.delete_issue(current_user, company_id, issue_id)


@router.delete("/actions/{action_id}")
async def idf_delete_action(action_id: str, company_id: Optional[str] = Query(None),
                            current_user: dict = Depends(get_current_user)):
    return await analysis.delete_action(current_user, company_id, action_id)


@router.post("/cycles/{cycle_id}/cancel")
async def idf_cancel_cycle(cycle_id: str, company_id: Optional[str] = Query(None),
                           current_user: dict = Depends(get_current_user)):
    return await idf.cancel_cycle(current_user, company_id, cycle_id)


@router.post("/cycles/{cycle_id}/add")
async def idf_add_to_cycle(cycle_id: str, payload: dict = Body(...), company_id: Optional[str] = Query(None),
                           current_user: dict = Depends(get_current_user)):
    """Add more department feedback to a started cycle (reopens a completed one)."""
    return await idf.add_reviews(current_user, company_id, cycle_id, payload)


# ── The standard process: "you said, we did" and the open feedback channel ──
@router.get("/responses")
async def idf_responses(company_id: Optional[str] = Query(None), current_user: dict = Depends(get_current_user)):
    from app.services import idf_process
    return await idf_process.list_responses(current_user, company_id)


@router.post("/responses/{response_id}")
async def idf_submit_response(response_id: str, payload: dict = Body(...),
                              current_user: dict = Depends(get_current_user)):
    from app.services import idf_process
    return await idf_process.submit_response(current_user, response_id, payload)


@router.get("/issues")
async def idf_issues(company_id: Optional[str] = Query(None), current_user: dict = Depends(get_current_user)):
    from app.services import idf_process
    return await idf_process.list_issues(current_user, company_id)


@router.post("/issues")
async def idf_raise_issue(payload: dict = Body(...), current_user: dict = Depends(get_current_user)):
    from app.services import idf_process
    return await idf_process.raise_issue(current_user, payload)


@router.patch("/issues/{issue_id}")
async def idf_update_issue(issue_id: str, payload: dict = Body(...), company_id: Optional[str] = Query(None),
                           current_user: dict = Depends(get_current_user)):
    from app.services import idf_process
    return await idf_process.update_issue(current_user, company_id, issue_id, payload)


@router.get("/links")
async def idf_links(company_id: Optional[str] = Query(None), cycle_id: Optional[str] = Query(None),
                    current_user: dict = Depends(get_current_user)):
    """Form Links: every HOD's personal form link for a cycle (HR / Admin / MD)."""
    return await idf.list_links(current_user, company_id, cycle_id)


@router.post("/links/{link_id}/resend")
async def idf_resend_link(link_id: str, company_id: Optional[str] = Query(None),
                          current_user: dict = Depends(get_current_user)):
    return await idf.resend_link(current_user, company_id, link_id)


@router.get("/my-forms")
async def idf_my_forms(current_user: dict = Depends(get_current_user)):
    return await idf.my_forms(current_user)


@router.get("/link/{token}")
async def idf_open_link(token: str, current_user: dict = Depends(get_current_user)):
    """The personal form link emailed to an HOD (opened at /idf/f/<token>)."""
    return await idf.open_link(current_user, token)


@router.post("/submit")
async def idf_submit(payload: dict = Body(...), current_user: dict = Depends(get_current_user)):
    return await idf.submit(current_user, payload)


@router.get("/dashboard")
async def idf_dashboard(cycle_id: Optional[str] = Query(None), company_id: Optional[str] = Query(None),
                        current_user: dict = Depends(get_current_user)):
    """The MD's dashboard — also the Sparsh Super Admin / Admin's, for the company they pick."""
    return await analysis.md_dashboard(current_user, cycle_id, company_id)


@router.get("/reports/{cycle_id}/{kind}")
async def idf_report(cycle_id: str, kind: str, company_id: Optional[str] = Query(None),
                     current_user: dict = Depends(get_current_user)):
    fname, data, media = await reports.md_download(current_user, cycle_id, kind, company_id)
    return StreamingResponse(io.BytesIO(data), media_type=media,
                             headers={"Content-Disposition": f'attachment; filename="{fname}"',
                                      "Cache-Control": "no-store"})


@router.get("/actions")
async def idf_actions(company_id: Optional[str] = Query(None), cycle_id: Optional[str] = Query(None),
                      status: Optional[str] = Query(None), band: Optional[str] = Query(None),
                      current_user: dict = Depends(get_current_user)):
    return await analysis.list_actions(current_user, company_id,
                                       {"cycle_id": cycle_id, "status": status, "band": band})


@router.patch("/actions/{action_id}")
async def idf_update_action(action_id: str, payload: dict = Body(...), company_id: Optional[str] = Query(None),
                            current_user: dict = Depends(get_current_user)):
    return await analysis.update_action(current_user, company_id, action_id, payload)
