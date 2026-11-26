import api from './api';

/**
 * Inter-Departmental Feedback API (backend/app/routes/idf.py).
 * Scores, reports and import/export are served to the company MD only; HR / Admin get setup,
 * cycles and submission status; HODs their forms; action owners their actions.
 */
const co = (companyId) => ({ params: companyId ? { company_id: companyId } : {} });

export const getIdfAccess = () => api.get('/idf/access');

export const getIdfSetup = (companyId) => api.get('/idf/setup', co(companyId));
export const saveIdfSetup = (payload, companyId) => api.put('/idf/setup', payload, co(companyId));

export const getIdfCycles = (companyId) => api.get('/idf/cycles', co(companyId));
// Start-cycle dialog: departments with their HOD(s) from Team + the previous cycle's mapping.
export const getIdfCycleOptions = (companyId) => api.get('/idf/cycles/options', co(companyId));
export const startIdfCycle = (payload, companyId) => api.post('/idf/cycles', payload, co(companyId));
export const getIdfCycleStatus = (cycleId, companyId) => api.get(`/idf/cycles/${cycleId}/status`, co(companyId));
// Add more department feedback to a started cycle (a completed one reopens).
export const addToIdfCycle = (cycleId, payload, companyId) => api.post(`/idf/cycles/${cycleId}/add`, payload, co(companyId));
// The results meeting of a cycle: details + RSVP; HR / Client Admin / MD reschedule it.
export const getIdfMeeting = (cycleId, companyId) => api.get(`/idf/cycles/${cycleId}/results-meeting`, co(companyId));
export const rescheduleIdfMeeting = (cycleId, payload, companyId) => api.post(`/idf/cycles/${cycleId}/results-meeting`, payload, co(companyId));
export const rsvpIdfMeeting = (cycleId, payload) => api.post(`/idf/cycles/${cycleId}/results-meeting/rsvp`, payload);
// Permanent delete — MD, Client Admin, Super Admin. The preview says what goes; typing DELETE confirms.
export const getIdfDeletePreview = (cycleId, companyId) => api.get(`/idf/cycles/${cycleId}/delete-preview`, co(companyId));
export const deleteIdfCycle = (cycleId, companyId) =>
  api.delete(`/idf/cycles/${cycleId}`, { params: { confirm: 'DELETE', ...(companyId ? { company_id: companyId } : {}) } });
export const deleteIdfIssue = (id, companyId) => api.delete(`/idf/issues/${id}`, co(companyId));
export const deleteIdfAction = (id, companyId) => api.delete(`/idf/actions/${id}`, co(companyId));
export const cancelIdfCycle = (cycleId, companyId) => api.post(`/idf/cycles/${cycleId}/cancel`, null, co(companyId));

// Form Links (HR / Admin / MD): every HOD's personal link for a cycle (the open one by default).
export const getIdfLinks = (cycleId, companyId) =>
  api.get('/idf/links', { params: { ...(cycleId ? { cycle_id: cycleId } : {}), ...(companyId ? { company_id: companyId } : {}) } });
export const resendIdfLink = (linkId, companyId) => api.post(`/idf/links/${linkId}/resend`, null, co(companyId));

export const getMyIdfForms = () => api.get('/idf/my-forms');
// The personal form link emailed to an HOD — opened at /idf/f/<token>.
export const openIdfLink = (token) => api.get(`/idf/link/${encodeURIComponent(token)}`);
export const submitIdfFeedback = (payload) => api.post('/idf/submit', payload);

// The MD's dashboard; a Sparsh Super Admin / Admin passes the company they picked.
export const getIdfDashboard = (cycleId, companyId) =>
  api.get('/idf/dashboard', { params: { ...(cycleId ? { cycle_id: cycleId } : {}), ...(companyId ? { company_id: companyId } : {}) } });
export const downloadIdfReport = (cycleId, kind, companyId) =>
  api.get(`/idf/reports/${cycleId}/${kind}`, { responseType: 'blob', ...co(companyId) });

// "You said, we did" (Standard Approach: close the loop within 15 days of results).
export const getIdfResponses = (companyId) => api.get('/idf/responses', co(companyId));
export const submitIdfResponse = (id, payload) => api.post(`/idf/responses/${id}`, payload);
// The open feedback channel — anyone raises an inter-department issue; HR takes it to WRM.
export const getIdfIssues = (companyId) => api.get('/idf/issues', co(companyId));
export const raiseIdfIssue = (payload) => api.post('/idf/issues', payload);
export const updateIdfIssue = (id, payload, companyId) => api.patch(`/idf/issues/${id}`, payload, co(companyId));

export const getIdfActions =(params) => api.get('/idf/actions', { params });
export const updateIdfAction = (id, payload, companyId) => api.patch(`/idf/actions/${id}`, payload, co(companyId));
