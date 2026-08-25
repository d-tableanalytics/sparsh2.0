import api from './api';

/**
 * HRMS ▸ authenticated API client.
 * Thin wrappers over the shared axios instance (house style — no react-query, matching
 * tpmsApi.js / taskApi.js). Backend routes live under /api/hrms (backend/app/routes/hrms.py).
 *
 * The public candidate endpoints (apply / assess / offer / onboard) deliberately do NOT
 * live here — they must be callable with no token, so they get their own client in
 * hrmsPublicApi.js from Phase 4.
 */

// ── Module ──
/** Module status + the caller's resolved role and capability list.
 *  This is the authority for UI gating: the frontend renders from the server's own
 *  capability answer rather than re-deriving permissions from role strings. */
export const getHrmsHealth = () => api.get('/hrms/health');

// ── Audit ──
/** Audit trail. Tenant-scoped server-side — a client-side caller is pinned to their own
 *  company regardless of the company_id param. */
export const getHrmsAudit = (params) => api.get('/hrms/audit', { params });

// ── Company module toggle (Admin / Super Admin only) ──
/** Switch HRMS on or off for a company. Lives here rather than in a company client
 *  because the capability and the 403 copy are HRMS's, not Company Management's. */
export const setHrmsAccess = (companyId, enabled) =>
  api.patch(`/companies/${companyId}/hrms-access`, { enabled });

// ── Company scope ──
/** Companies this caller may work with in HRMS. Internal staff get every HRMS-enabled
 *  company (they need a scope selector); client users get exactly their own. */
export const getHrmsCompanies = () => api.get('/hrms/companies');

// ── Departments ──
// `company_id` is optional for client-side users (the server pins them to their own
// company and ignores the param); internal staff must supply it.
export const getDepartments = (params) => api.get('/hrms/departments', { params });
export const createDepartment = (payload, params) =>
  api.post('/hrms/departments', payload, { params });
export const updateDepartment = (id, payload, params) =>
  api.patch(`/hrms/departments/${id}`, payload, { params });
export const deleteDepartment = (id, params) =>
  api.delete(`/hrms/departments/${id}`, { params });

// ── Designations ──
export const getDesignations = (params) => api.get('/hrms/designations', { params });
export const createDesignation = (payload, params) =>
  api.post('/hrms/designations', payload, { params });
export const updateDesignation = (id, payload, params) =>
  api.patch(`/hrms/designations/${id}`, payload, { params });
export const deleteDesignation = (id, params) =>
  api.delete(`/hrms/designations/${id}`, { params });

/** Distinct department/designation values already on the company's users, with usage
 *  counts. Read-only — nothing is auto-created; HR reviews and creates deliberately. */
export const getMasterSuggestions = (params) =>
  api.get('/hrms/masters/suggestions', { params });

// ── Employees ──
export const getEmployees = (params) => api.get('/hrms/employees', { params });
export const getEmployee = (userId, params) =>
  api.get(`/hrms/employees/${userId}`, { params });
export const createEmployee = (payload, params) =>
  api.post('/hrms/employees', payload, { params });
export const updateEmployee = (userId, payload, params) =>
  api.patch(`/hrms/employees/${userId}`, payload, { params });
export const getEmployeeHierarchy = (userId, params) =>
  api.get(`/hrms/employees/${userId}/hierarchy`, { params });
/** Company users who do not yet have an employee profile — the "Add employee" picker. */
export const getLinkableUsers = (params) => api.get('/hrms/employees/linkable', { params });
/** Your own employee record. Never gated by employee.read, and always includes your salary. */
export const getMyEmployeeProfile = () => api.get('/hrms/employees/me');

// ── Requisitions (FMS) ──
export const getRequisitions = (params) => api.get('/hrms/requisitions', { params });
export const getRequisition = (requestNo, params) =>
  api.get(`/hrms/requisitions/${requestNo}`, { params });
export const createRequisition = (payload, params) =>
  api.post('/hrms/requisitions', payload, { params });
export const updateRequisition = (requestNo, payload, params) =>
  api.patch(`/hrms/requisitions/${requestNo}`, payload, { params });
export const deleteRequisition = (requestNo, params) =>
  api.delete(`/hrms/requisitions/${requestNo}`, { params });
/** One transition of the approval chain.
 *  action = 'hr-approve' | 'hr-reject' | 'md-approve' | 'md-reject' */
export const actOnRequisition = (requestNo, payload, params) =>
  api.post(`/hrms/requisitions/${requestNo}/approve`, payload, { params });
export const closeRequisition = (requestNo, status, params) =>
  api.post(`/hrms/requisitions/${requestNo}/close`, { status }, { params });

// ── Job descriptions ──
// JDs are authored with their requisition and approved together, so there is deliberately
// no create and no independent approve/reject client.
export const getJds = (params) => api.get('/hrms/jd', { params });
export const getJd = (jdNo, params) => api.get(`/hrms/jd/${jdNo}`, { params });
export const updateJd = (jdNo, payload, params) =>
  api.patch(`/hrms/jd/${jdNo}`, payload, { params });

// ── Job postings (authenticated) ──
export const getPostings = (params) => api.get('/hrms/postings', { params });
export const createPosting = (payload, params) =>
  api.post('/hrms/postings', payload, { params });
export const updatePosting = (code, payload, params) =>
  api.patch(`/hrms/postings/${code}`, payload, { params });
export const deletePosting = (code, params) =>
  api.delete(`/hrms/postings/${code}`, { params });

/** Preview the public apply URL for a posting code. Kept here so the one place that knows
 *  the public URL shape is the API client, not each component. */
export const applyUrlFor = (code) => `${window.location.origin}/apply/${code}`;

// ── Candidates, screening, journey ──
export const getCandidates = (params) => api.get('/hrms/candidates', { params });
export const getCandidate = (uk, params) => api.get(`/hrms/candidates/${uk}`, { params });
export const createCandidate = (payload, params) =>
  api.post('/hrms/candidates', payload, { params });
export const updateCandidate = (uk, payload, params) =>
  api.patch(`/hrms/candidates/${uk}`, payload, { params });
export const deleteCandidate = (uk, params) =>
  api.delete(`/hrms/candidates/${uk}`, { params });
/** Bulk triage. Returns {moved, skipped} — partial success is expected, not an error. */
export const screenCandidates = (payload, params) =>
  api.post('/hrms/candidates/screen', payload, { params });
/** Full history, reconstructed server-side from the audit trail. */
export const getCandidateJourney = (uk, params) =>
  api.get(`/hrms/candidates/${uk}/journey`, { params });

// ── Assessments (dual review) ──
export const getAssessments = (params) => api.get('/hrms/assessments', { params });
export const getAssessableCandidates = (params) =>
  api.get('/hrms/assessments/assessable', { params });
export const sendAssessment = (payload, params) =>
  api.post('/hrms/assessments', payload, { params });
/** Record ONE reviewer's Pass/Fail. The server decides which slot you fill. */
export const reviewAssessment = (assessmentNo, payload, params) =>
  api.post(`/hrms/assessments/${assessmentNo}/review`, payload, { params });

/** The candidate-facing assessment link. 128-bit access code, case-sensitive. */
export const assessUrlFor = (code) => `${window.location.origin}/assess/${code}`;

// ── Interviews + scorecard ──
export const getInterviews = (params) => api.get('/hrms/interviews', { params });
export const getSchedulableCandidates = (params) =>
  api.get('/hrms/interviews/schedulable', { params });
export const scheduleInterview = (payload, params) =>
  api.post('/hrms/interviews', payload, { params });
export const updateInterview = (no, payload, params) =>
  api.patch(`/hrms/interviews/${no}`, payload, { params });
export const cancelInterview = (no, params) =>
  api.delete(`/hrms/interviews/${no}`, { params });
/** Record the scorecard. Six competencies 0-5, a decision and a required typed signature. */
export const evaluateInterview = (no, payload, params) =>
  api.post(`/hrms/interviews/${no}/evaluate`, payload, { params });
/** Calendar invite download URL (served as a file, not emailed — see PHASE_7_REPORT). */
export const inviteUrlFor = (no) =>
  `${import.meta.env.VITE_API_BASE_URL || '/api'}/hrms/interviews/${no}/invite.ics`;

// ── Offers ──
export const getOffers = (params) => api.get('/hrms/offers', { params });
export const getOfferableCandidates = (params) =>
  api.get('/hrms/offers/offerable', { params });
export const createOffer = (payload, params) => api.post('/hrms/offers', payload, { params });
export const updateOffer = (no, payload, params) =>
  api.patch(`/hrms/offers/${no}`, payload, { params });
export const sendOffer = (no, payload, params) =>
  api.post(`/hrms/offers/${no}/send`, payload, { params });
export const revokeOffer = (no, payload, params) =>
  api.post(`/hrms/offers/${no}/revoke`, payload, { params });
export const deleteOffer = (no, params) => api.delete(`/hrms/offers/${no}`, { params });

/** The candidate-facing offer link. 128-bit access code, case-sensitive. */
export const offerUrlFor = (code) => `${window.location.origin}/offer/${code}`;

// ── Onboarding ──
export const getOnboardings = (params) => api.get('/hrms/onboarding', { params });
export const getOnboardableCandidates = (params) =>
  api.get('/hrms/onboarding/onboardable', { params });
export const getOnboarding = (no, params) => api.get(`/hrms/onboarding/${no}`, { params });
export const startOnboarding = (payload, params) =>
  api.post('/hrms/onboarding', payload, { params });
export const updateOnboarding = (no, payload, params) =>
  api.patch(`/hrms/onboarding/${no}`, payload, { params });
export const updateOnboardingBg = (no, payload, params) =>
  api.post(`/hrms/onboarding/${no}/bg`, payload, { params });
export const verifyOnboardingDocuments = (no, params) =>
  api.post(`/hrms/onboarding/${no}/verify`, {}, { params });
export const addOnboardingDocuments = (no, payload, params) =>
  api.post(`/hrms/onboarding/${no}/documents`, payload, { params });
export const setOnboardingChecklist = (no, payload, params) =>
  api.post(`/hrms/onboarding/${no}/checklist`, payload, { params });
/** The irreversible step: mints the Employee ID and creates the employee record. */
export const generateEmployeeId = (no, params) =>
  api.post(`/hrms/onboarding/${no}/generate-id`, {}, { params });
/** Attach an onboarding-created employee record to a real login account. */
export const linkEmployeeUser = (employeeCode, payload, params) =>
  api.post(`/hrms/employees/link/${employeeCode}`, payload, { params });

/** The new hire's pre-onboarding link. 128-bit access code, case-sensitive. */
export const onboardUrlFor = (code) => `${window.location.origin}/onboard/${code}`;

// ── Analytics & reports (Phase 10, read-only) ──
export const getHrmsDashboard = (params) => api.get('/hrms/analytics/dashboard', { params });
export const getHrmsFunnel = (params) => api.get('/hrms/analytics/funnel', { params });
export const getHrmsBreakdown = (params) => api.get('/hrms/analytics/breakdown', { params });
export const getHrmsReport = (entity, params) =>
  api.get(`/hrms/reports/${entity}`, { params });

/** Position-wise CV status matrix (Phase 11-R, Item 4): one row per requisition, one
 *  column per stage. Same scoping and caps as every other analytics read. */
export const getHrmsPositions = (params) => api.get('/hrms/analytics/positions', { params });

// ══════════════════════════════════════════════════════════════
// Phase 11-R — recruitment review enhancements
// ══════════════════════════════════════════════════════════════

// ── Item 1: the public-link registry ──
// The registry SCREEN was removed (HRMS ▸ Links); its /hrms/links endpoints still exist
// server-side and still govern the candidate-facing links the pipeline issues, so nothing
// about link validity changed — only the admin view over them is gone.

// ── Item 2: documentation ──
export const getDocumentTypes = (params) => api.get('/hrms/document-types', { params });
export const createDocumentType = (payload, params) =>
  api.post('/hrms/document-types', payload, { params });
export const updateDocumentType = (id, payload, params) =>
  api.patch(`/hrms/document-types/${id}`, payload, { params });
export const deleteDocumentType = (id, params) =>
  api.delete(`/hrms/document-types/${id}`, { params });

export const getDocuments = (params) => api.get('/hrms/documents', { params });
export const getDocument = (docNo, params) => api.get(`/hrms/documents/${docNo}`, { params });
/** Every applicable type for one person, with its status or `Pending`, plus the read-only
 *  view over files already attached elsewhere (resume, KYC scans). */
export const getDocumentChecklist = (params) =>
  api.get('/hrms/documents/checklist', { params });
/** Upload a document, or a new version (supply `doc_no` for a version). */
export const uploadDocument = (payload, params) =>
  api.post('/hrms/documents', payload, { params });
export const updateDocument = (docNo, payload, params) =>
  api.patch(`/hrms/documents/${docNo}`, payload, { params });
/** Verify / reject / move to Under Review. Rejecting REQUIRES remarks. */
export const setDocumentStatus = (docNo, payload, params) =>
  api.post(`/hrms/documents/${docNo}/status`, payload, { params });
/** A short-lived signed URL, minted per request — never stored. */
export const getDocumentUrl = (docNo, params) =>
  api.get(`/hrms/documents/${docNo}/url`, { params });
export const deleteDocument = (docNo, params) =>
  api.delete(`/hrms/documents/${docNo}`, { params });

// ── Item 3: appointment letters ──
export const getAppointments = (params) => api.get('/hrms/appointments', { params });
export const getAppointableCandidates = (params) =>
  api.get('/hrms/appointments/eligible', { params });
export const getAppointment = (no, params) =>
  api.get(`/hrms/appointments/${no}`, { params });
export const createAppointment = (payload, params) =>
  api.post('/hrms/appointments', payload, { params });
export const updateAppointment = (no, payload, params) =>
  api.patch(`/hrms/appointments/${no}`, payload, { params });
export const sendAppointment = (no, payload, params) =>
  api.post(`/hrms/appointments/${no}/send`, payload, { params });
export const cancelAppointment = (no, payload, params) =>
  api.post(`/hrms/appointments/${no}/cancel`, payload, { params });

/** The candidate-facing appointment link. 128-bit access code, case-sensitive. */
export const appointmentUrlFor = (code) => `${window.location.origin}/appointment/${code}`;

// ── Item 4: the client dimension + client sharing ──
/** The companies that may be named as the client of a requisition.
 *
 *  READ ONLY, and that is the point: these rows are the ERP's own Companies, projected into
 *  the `{ client_id, name }` shape HRMS reports on. There is no create/update/delete because
 *  a client is a company — it is created and edited in the Companies section, once. */
export const getClients = (params) => api.get('/hrms/clients', { params });
export const getClient = (clientId, params) =>
  api.get(`/hrms/clients/${clientId}`, { params });
/** Record the hiring client's verdict on a shared CV. Rejecting REQUIRES remarks. */
export const recordClientResponse = (payload, params) =>
  api.post('/hrms/candidates/client-response', payload, { params });

// ── Item 7: sanctioned strength ──
export const getSanctionedStrength = (params) =>
  api.get('/hrms/sanctioned-strength', { params });
/** Live sanctioned/actual/available for ONE position — read by the requisition form on
 *  every change, so the raiser learns about escalation before they submit. */
export const getSanctionedPosition = (params) =>
  api.get('/hrms/sanctioned-strength/position', { params });
export const setSanctionedStrength = (payload, params) =>
  api.post('/hrms/sanctioned-strength', payload, { params });
export const updateSanctionedStrength = (id, payload, params) =>
  api.patch(`/hrms/sanctioned-strength/${id}`, payload, { params });
export const deleteSanctionedStrength = (id, params) =>
  api.delete(`/hrms/sanctioned-strength/${id}`, { params });

/** Download a report. The file is rendered SERVER-side from already-scoped rows, so this
 *  only has to save the blob — it never sees rows the API withheld. */
export const exportHrmsReport = async (entity, params) => {
  const res = await api.get(`/hrms/reports/${entity}/export`, {
    params, responseType: 'blob',
  });
  const disposition = res.headers?.['content-disposition'] || '';
  const match = /filename="?([^"]+)"?/.exec(disposition);
  const url = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  a.href = url;
  a.download = match?.[1] || `hrms_${entity}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return {
    truncated: res.headers?.['x-export-truncated'] === 'true',
    rows: Number(res.headers?.['x-export-rows'] || 0),
    total: Number(res.headers?.['x-export-total'] || 0),
  };
};

// ══════════════════════════════════════════════════════════════
// Internal (in-house) recruitment track
// ══════════════════════════════════════════════════════════════
// Sparsh Magic hiring for itself, governed by the Internal Recruitment SOP. Everything here
// is ADDITIVE: no existing call changed shape, and `track` is optional everywhere it appears,
// so a caller that omits it gets exactly the behaviour it had before.

/** Position scorecards — the bar a role is hired against, agreed before sourcing. */
export const getScorecards = (params) => api.get('/hrms/scorecards', { params });
export const getScorecard = (scrNo, params) =>
  api.get(`/hrms/scorecards/${scrNo}`, { params });
export const createScorecard = (payload, params) =>
  api.post('/hrms/scorecards', payload, { params });
export const updateScorecard = (scrNo, payload, params) =>
  api.patch(`/hrms/scorecards/${scrNo}`, payload, { params });
/** One approval signature. The scorecard completes when every required role has signed. */
export const approveScorecard = (scrNo, payload, params) =>
  api.post(`/hrms/scorecards/${scrNo}/approve`, payload, { params });
/** Score a candidate against their requisition's scorecard. Records; never moves them. */
export const evaluateAgainstScorecard = (uk, payload, params) =>
  api.post(`/hrms/candidates/${uk}/scorecard-evaluate`, payload, { params });

/** Reference checks. Mandatory before an internal offer; optional on the client track. */
export const getReferenceChecks = (params) => api.get('/hrms/reference-checks', { params });
export const getReferenceCheck = (refNo, params) =>
  api.get(`/hrms/reference-checks/${refNo}`, { params });
export const createReferenceCheck = (payload, params) =>
  api.post('/hrms/reference-checks', payload, { params });
export const updateReferenceCheck = (refNo, payload, params) =>
  api.patch(`/hrms/reference-checks/${refNo}`, payload, { params });

/**
 * Telephonic screening (SOP step 5) — the brief call between CV screening and the panel.
 * Internal track only. A PASSED screen is what clears a candidate for an interview; the
 * gate itself lives server-side on interview creation.
 */
export const getTelephonicScreenings = (params) =>
  api.get('/hrms/telephonic-screenings', { params });
export const getScreenableCandidates = (params) =>
  api.get('/hrms/telephonic-screenings/screenable', { params });
export const getTelephonicScreening = (telNo, params) =>
  api.get(`/hrms/telephonic-screenings/${telNo}`, { params });
export const createTelephonicScreening = (payload, params) =>
  api.post('/hrms/telephonic-screenings', payload, { params });
export const updateTelephonicScreening = (telNo, payload, params) =>
  api.patch(`/hrms/telephonic-screenings/${telNo}`, payload, { params });

/**
 * Per-company configuration (Phase INT-5) — SLA targets, retention periods, probation
 * duration, reminder tiers and score band floors. A company with no settings row follows
 * the module defaults, so `describe` always returns a complete, renderable table.
 */
export const getHrmsSettings = (params) => api.get('/hrms/settings', { params });
export const updateHrmsSettings = (payload, params) =>
  api.patch('/hrms/settings', payload, { params });
/** Stop overriding — distinct from setting a value that happens to equal the default. */
export const resetHrmsSettings = (keys, params) =>
  api.post('/hrms/settings/reset', { keys }, { params });

/**
 * The working calendar (Phase INT-6) — the dates SLA maths skips, for THIS company.
 * HRMS's own, never the ERP's global holidays master; `importHrmsHolidays` adopts a year
 * of that master as a copy, and is safe to run twice.
 */
export const getHrmsHolidays = (params) => api.get('/hrms/holidays', { params });
export const addHrmsHoliday = (payload, params) =>
  api.post('/hrms/holidays', payload, { params });
export const importHrmsHolidays = (year, params) =>
  api.post('/hrms/holidays/import', { year }, { params });
export const removeHrmsHoliday = (date, params) =>
  api.delete(`/hrms/holidays/${date}`, { params });

/**
 * The internal requisition tracker (Phase INT-7, Annexure C) — one row per internal
 * requisition with every stage rolled up server-side. Scoped exactly as the requisition
 * list is; `sla` filters by health: breached | on_track | met | not_started.
 */
export const getInternalTracker = (params) =>
  api.get('/hrms/internal-requisitions/tracker', { params });

/**
 * Salary negotiation (SOP step 9, spec §16) — the record of the rounds. The band gate on
 * the offer is unchanged; `getCandidateNegotiation` previews whether an offer at the latest
 * figure would pass it today.
 */
export const getNegotiationRounds = (params) => api.get('/hrms/negotiations', { params });
export const recordNegotiationRound = (payload, params) =>
  api.post('/hrms/negotiations', payload, { params });
export const getCandidateNegotiation = (uk, params) =>
  api.get(`/hrms/candidates/${uk}/negotiation`, { params });

/** Management's sign-off on an internal offer, mandatory before it can be sent. */
export const approveOffer = (offerNo, payload, params) =>
  api.post(`/hrms/offers/${offerNo}/approve`, payload, { params });

/** Probation. An EMPLOYEE event, not a recruitment stage — see hrms_probation_service. */
export const getProbations = (params) => api.get('/hrms/probation', { params });
export const getProbationsDue = (params) => api.get('/hrms/probation/due', { params });
export const getProbation = (prbNo, params) =>
  api.get(`/hrms/probation/${prbNo}`, { params });
export const openProbation = (payload, params) =>
  api.post('/hrms/probation', payload, { params });
export const updateProbation = (prbNo, payload, params) =>
  api.patch(`/hrms/probation/${prbNo}`, payload, { params });
export const confirmProbation = (prbNo, payload, params) =>
  api.post(`/hrms/probation/${prbNo}/confirm`, payload, { params });
export const closePersonnelFile = (payload, params) =>
  api.post('/hrms/personnel-file/close', payload, { params });

/** The exception log. An APPROVED exception is the only thing that lifts a gate. */
export const getExceptions = (params) => api.get('/hrms/exceptions', { params });
export const getException = (excNo, params) =>
  api.get(`/hrms/exceptions/${excNo}`, { params });
export const raiseException = (payload, params) =>
  api.post('/hrms/exceptions', payload, { params });
export const decideException = (excNo, payload, params) =>
  api.post(`/hrms/exceptions/${excNo}/approve`, payload, { params });

/** SLA milestones for one requisition, and the open-breach sweep. */
export const getRequisitionSla = (requestNo, params) =>
  api.get(`/hrms/requisitions/${requestNo}/sla`, { params });
export const getSlaBreaches = (params) => api.get('/hrms/sla/breaches', { params });


// ══ Phase INT-2 — the remaining Internal Recruitment SOP controls ══
// Every call below is internal-track only. The server refuses a client requisition outright
// rather than half-applying a control the client track has no counterpart for.

/** The internal shortlisting committee (SOP §5). HR and the Department Head jointly
 *  finalise the shortlist, and a FINALISED record is what lifts the gate on `Selected`. */
export const getShortlistReviews = (params) =>
  api.get('/hrms/shortlist-reviews', { params });
export const getShortlistReview = (slrNo, params) =>
  api.get(`/hrms/shortlist-reviews/${slrNo}`, { params });
export const createShortlistReview = (payload, params) =>
  api.post('/hrms/shortlist-reviews', payload, { params });
export const updateShortlistReview = (slrNo, payload, params) =>
  api.patch(`/hrms/shortlist-reviews/${slrNo}`, payload, { params });

/** Batch interview windows (Annexure C). A PREFERENCE, never a rule — scheduling outside
 *  one warns in the response and books the interview anyway. */
export const getInterviewWindows = (params) =>
  api.get('/hrms/interview-windows', { params });
export const createInterviewWindow = (payload, params) =>
  api.post('/hrms/interview-windows', payload, { params });
export const updateInterviewWindow = (id, payload, params) =>
  api.patch(`/hrms/interview-windows/${id}`, payload, { params });
export const deleteInterviewWindow = (id, params) =>
  api.delete(`/hrms/interview-windows/${id}`, { params });

/** Pre-boarding engagement (SOP §6). Tracking, NOT a gate: nothing is blocked by a missing
 *  touchpoint. `due` splits never-contacted from gone-quiet, because those are two
 *  different conversations. */
export const getPreboarding = (params) => api.get('/hrms/preboarding', { params });
export const getPreboardingDue = (params) =>
  api.get('/hrms/preboarding/due', { params });
export const recordPreboardingTouchpoint = (payload, params) =>
  api.post('/hrms/preboarding', payload, { params });

/** The standing salary-band master (Annexure C). A CONVENIENCE for the budget gate; the
 *  offer check still reads the band stamped on the requisition, so a band edited today can
 *  never retroactively legalise an offer approved last month. */
export const getSalaryBands = (params) => api.get('/hrms/salary-bands', { params });
export const getSalaryBand = (bandNo, params) =>
  api.get(`/hrms/salary-bands/${bandNo}`, { params });
export const getSalaryBandPrefill = (requestNo, params) =>
  api.get(`/hrms/salary-bands/for-requisition/${requestNo}`, { params });
export const createSalaryBand = (payload, params) =>
  api.post('/hrms/salary-bands', payload, { params });
export const updateSalaryBand = (bandNo, payload, params) =>
  api.patch(`/hrms/salary-bands/${bandNo}`, payload, { params });

/** The talent pool (Annexure C). Listing is `getCandidates({ talent_pool: true, tags })` —
 *  the pool is a FILTER on the candidate list, not a second collection, so a pooled
 *  candidate keeps the same scoping and the same retention as every other CV. */
export const setTalentPool = (uk, payload, params) =>
  api.post(`/hrms/candidates/${uk}/talent-pool`, payload, { params });
export const sourceFromTalentPool = (uk, requestNo, params) =>
  api.post(`/hrms/candidates/${uk}/source-to/${requestNo}`, null, { params });

/** Candidate communications (Annexure C). Delivery goes through the existing notification
 *  service; what is new is the template and the append-only log. */
export const getCommunications = (params) => api.get('/hrms/communications', { params });
export const getCommTemplates = (params) =>
  api.get('/hrms/communications/templates', { params });
export const updateCommTemplate = (key, payload, params) =>
  api.patch(`/hrms/communications/templates/${key}`, payload, { params });
export const sendCommunication = (payload, params) =>
  api.post('/hrms/communications/send', payload, { params });

/** New-hire experience surveys (SOP §10). READ IS THE AGGREGATE ONLY — there is no endpoint
 *  that returns response rows, and the server suppresses any figure below its minimum
 *  response count. A survey a manager can de-anonymise measures nothing. */
export const getSurveys = (params) => api.get('/hrms/surveys', { params });
export const getSurveyResults = (params) => api.get('/hrms/surveys/results', { params });

/** All eight SOP KPIs, computed server-side and role-scoped. Every ratio carries
 *  `eligible_n`, and `excluded_n` where records were deliberately left out. */
export const getInternalKpis = (params) =>
  api.get('/hrms/analytics/internal-kpis', { params });

/** What is outstanding before a probation can be CONFIRMED (SOP §11). Surfaced while the
 *  probation is still running rather than sprung at the moment somebody tries to confirm. */
export const getProbationStatutory = (prbNo, params) =>
  api.get(`/hrms/probation/${prbNo}/statutory`, { params });

/** The policy register and its review cycle (SOP §14). A revision is DRAFTED and then
 *  APPROVED; drafting one changes nothing about which version governs. */
export const getPolicies = (params) => api.get('/hrms/policies', { params });
export const getPolicy = (policyKey, params) =>
  api.get(`/hrms/policies/${policyKey}`, { params });
export const getPolicyReviewsDue = (params) => api.get('/hrms/policies/due', { params });
export const registerPolicy = (payload, params) =>
  api.post('/hrms/policies', payload, { params });
export const logPolicyRevision = (policyKey, payload, params) =>
  api.post(`/hrms/policies/${policyKey}/revisions`, payload, { params });
export const approvePolicyRevision = (policyKey, payload, params) =>
  api.post(`/hrms/policies/${policyKey}/approve`, payload, { params });

/** The retention purge (SOP §13). Proposals come from `scripts/hrms_retention_purge.py`,
 *  which defaults to a dry run. Approving one REDACTS the personal fields and keeps the ids
 *  and the audit trail — it is not reversible. */
export const getPurgeBatches = (params) => api.get('/hrms/purge-batches', { params });
export const getPurgeBatch = (batchNo, params) =>
  api.get(`/hrms/purge-batches/${batchNo}`, { params });
export const approvePurgeBatch = (batchNo, payload, params) =>
  api.post(`/hrms/purge-batches/${batchNo}/approve`, payload, { params });

/** Printable record documents (SOP §9). One pattern for all five forms, gated by the
 *  entity's existing READ capability — printing a record is reading it. Returns a signed
 *  URL; every figure on the form is read from the record and nothing is re-entered. */
export const getRecordDocument = (entity, businessNo, params) =>
  api.get(`/hrms/records/${entity}/${businessNo}/document`, { params });
