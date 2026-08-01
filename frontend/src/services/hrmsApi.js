import api from './api';

// HRMS API wrappers. Everything lives under /hrms and is internal-staff-only server-side
// (auth_controller.require_hrms_access) — see docs/HRMS_REPLICATION_ROADMAP.md.
//
// This file is the one place the HRMS talks to the backend, so a route change lands here and
// nowhere else. Calls are added as each phase lands.

// ─── Access (Phase 0) ───
// What the caller may do inside the HRMS. 403s a user without the module — use getHrmsAccess
// for a question that must not raise.
export const getHrmsMeta = () => api.get('/hrms/meta');

// Non-throwing access probe, safe for any authenticated user (used by the sidebar).
export const getHrmsAccess = () => api.get('/hrms/access');

// ─── Core HR (Phase 1) ───
// Enum values + master lists for the form pickers, served by the backend so the dropdowns can
// never drift from what the API accepts.
export const getHrmsOptions = () => api.get('/hrms/options');

// Org structure master data. `kind` = department | designation | location.
export const getOrgMasters = (params) => api.get('/hrms/org', { params });
export const createOrgMaster = (payload) => api.post('/hrms/org', payload);
export const updateOrgMaster = (id, updates) => api.patch(`/hrms/org/${id}`, updates);

// Employee directory. Search / filter / sort / paging are all server-side.
export const getEmployees = (params) => api.get('/hrms/employees', { params });
export const getEmployee = (code) => api.get(`/hrms/employees/${code}`);
export const createEmployee = (payload) => api.post('/hrms/employees', payload);
export const updateEmployee = (code, updates) => api.patch(`/hrms/employees/${code}`, updates);

// Profile timeline — every create / edit / status change, plus manual notes.
export const getEmployeeEvents = (code) => api.get(`/hrms/employees/${code}/events`);
export const addEmployeeEvent = (code, payload) => api.post(`/hrms/employees/${code}/events`, payload);

// ─── Attendance (Phase 2) ───
// Policy the punch UI needs (geofence on/off, office coordinates, selfie requirement, shift).
export const getAttendanceSettings = () => api.get('/hrms/attendance/settings');
export const updateAttendanceSettings = (updates) => api.put('/hrms/attendance/settings', updates);

// A month for one person — your own unless a user_id is passed (which needs attendance.read).
export const getAttendance = (params) => api.get('/hrms/attendance', { params });

// One toggle for in AND out: the server decides which, from the day's open segment.
export const punchAttendance = (payload) => api.post('/hrms/attendance/punch', payload);

// HR recording a missed punch on someone's behalf.
export const addManualAttendance = (payload) => api.post('/hrms/attendance/manual', payload);

// Who is in today, joined to the employee directory.
export const getTeamAttendance = (params) => api.get('/hrms/attendance/team', { params });

// ─── Leave (Phase 3) ───
// Types + counting policy. The apply form reads its dropdown from here, so a type the server
// would reject is never offered.
export const getLeaveSettings = () => api.get('/hrms/leaves/settings');
export const updateLeaveSettings = (updates) => api.put('/hrms/leaves/settings', updates);

// Entitlement / used / remaining per type.
export const getLeaveBalance = (params) => api.get('/hrms/leaves/balance', { params });

// scope: 'mine' (default) | 'pending' (approvals inbox) | 'all'
export const getLeaves = (params) => api.get('/hrms/leaves', { params });
export const applyLeave = (payload) => api.post('/hrms/leaves', payload);
export const decideLeave = (id, payload) => api.patch(`/hrms/leaves/${id}/decide`, payload);
export const cancelLeave = (id) => api.patch(`/hrms/leaves/${id}/cancel`);

// ─── Payroll (Phase 4) ───
export const getPayrollConfig = () => api.get('/hrms/payroll/config');
export const updatePayrollConfig = (updates) => api.put('/hrms/payroll/config', updates);
export const getPayrollRuns = () => api.get('/hrms/payroll/runs');

// Reads a STORED run — never computes, never writes.
export const getPayroll = (params) => api.get('/hrms/payroll', { params });

// Computes and stores a draft. Re-running replaces the draft; a locked period is refused.
export const runPayroll = (payload) => api.post('/hrms/payroll/run', payload);

// Freezes the period. After this the figures are what people were paid against.
export const lockPayroll = (payload) => api.post('/hrms/payroll/lock', payload);

// An employee's own payslip — served only once the period is locked.
export const getMyPayslip = (params) => api.get('/hrms/payroll/payslip', { params });

// ─── Recruitment (Phase 5) ───
export const getRequisitions = (params) => api.get('/hrms/requisitions', { params });
export const getRequisition = (no) => api.get(`/hrms/requisitions/${no}`);
export const createRequisition = (payload) => api.post('/hrms/requisitions', payload);
export const updateRequisition = (no, updates) => api.patch(`/hrms/requisitions/${no}`, updates);

// One endpoint drives the whole approval chain. action: advance | reject | resubmit — the
// server derives which step that means from the requisition's current state.
export const decideRequisition = (no, payload) => api.post(`/hrms/requisitions/${no}/decide`, payload);

// Where the vacancy stands, independent of the approval chain.
export const closeRequisition = (no, payload) => api.post(`/hrms/requisitions/${no}/close`, payload);

// ─── Candidate pipeline (Phase 6) ───
export const getPostings = () => api.get('/hrms/postings');
export const createPosting = (payload) => api.post('/hrms/postings', payload);
export const updatePosting = (id, updates) => api.patch(`/hrms/postings/${id}`, updates);

export const getCandidates = (params) => api.get('/hrms/candidates', { params });
export const getCandidate = (uk) => api.get(`/hrms/candidates/${uk}`);
export const createCandidate = (payload) => api.post('/hrms/candidates', payload);

// Bulk stage move. Returns { moved, skipped } — skipped rows are reported, not swallowed.
export const screenCandidates = (payload) => api.post('/hrms/candidates/screen', payload);

// Returns the access code ONCE, to the HR user who created it. No list endpoint ever
// includes it.
export const sendAssessment = (uk, payload) => api.post(`/hrms/candidates/${uk}/assessments`, payload);
export const reviewAssessment = (uk, id, payload) =>
  api.post(`/hrms/candidates/${uk}/assessments/${id}/review`, payload);

export const scheduleInterview = (uk, payload) => api.post(`/hrms/candidates/${uk}/interviews`, payload);
export const evaluateInterview = (uk, id, payload) =>
  api.post(`/hrms/candidates/${uk}/interviews/${id}/evaluate`, payload);

// ─── Public (unauthenticated) ───
// Used by the Apply and Assessment pages, which render outside the authenticated shell.
export const getPublicPosting = (code) => api.get(`/hrms/public/postings/${code}`);
export const submitApplication = (code, payload) => api.post(`/hrms/public/postings/${code}/apply`, payload);
export const getPublicAssessment = (code) => api.get(`/hrms/public/assessments/${code}`);
export const submitAssessment = (code, payload) => api.post(`/hrms/public/assessments/${code}/submit`, payload);
