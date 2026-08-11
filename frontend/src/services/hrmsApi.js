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
export const createPostings = (payload, params) =>
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
/** Every public link this company has issued, with open counts and live status. */
export const getHrmsLinks = (params) => api.get('/hrms/links', { params });
export const getHrmsLink = (linkId, params) => api.get(`/hrms/links/${linkId}`, { params });
/** Kill a live link. Enforced server-side by assert_link_live, not merely displayed. */
export const revokeHrmsLink = (linkId, payload, params) =>
  api.post(`/hrms/links/${linkId}/revoke`, payload, { params });
/** Mint a fresh credential and revoke the old one. Apply links cannot be reissued. */
export const reissueHrmsLink = (linkId, params) =>
  api.post(`/hrms/links/${linkId}/reissue`, {}, { params });

/** Absolute URL for a registry row. The registry stores the relative `path`, so this is
 *  the one place that knows how to make it clickable — same role applyUrlFor plays. */
export const linkUrlFor = (path) => `${window.location.origin}${path || ''}`;

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

// ── Item 4: the client master + client sharing ──
export const getClients = (params) => api.get('/hrms/clients', { params });
export const getClient = (clientId, params) =>
  api.get(`/hrms/clients/${clientId}`, { params });
export const createClient = (payload, params) =>
  api.post('/hrms/clients', payload, { params });
export const updateClient = (clientId, payload, params) =>
  api.patch(`/hrms/clients/${clientId}`, payload, { params });
export const deleteClient = (clientId, params) =>
  api.delete(`/hrms/clients/${clientId}`, { params });
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
