import api from './api';

/**
 * TPMS ▸ core API.
 * Thin wrappers over the shared axios instance (house style — no react-query).
 * Backend routes live under /api/tpms (see backend/app/routes/tpms.py).
 *
 * The forms sub-module has its own client in tpmsFormsApi.js — keep them separate,
 * they map to two different routers.
 */

// ── Master data ──
export const getActivities = () => api.get('/tpms/activities');
export const getDepartments = () => api.get('/tpms/departments');
export const getReminderRules = (activity) =>
  api.get('/tpms/reminder-rules', { params: { activity: activity || undefined } });

// ── Scheduling ──
// Month feed for the calendar grid. `month` is 1-12.
export const getSchedules = (params) => api.get('/tpms/schedules', { params });

// Once-per-month duplicate warning. Returns {conflict, scope, period, existing[]}.
// Advisory only — the UI may proceed anyway.
export const checkScheduleConflict = (payload) =>
  api.post('/tpms/schedules/check-conflict', payload);

export const createSchedule = (payload) => api.post('/tpms/schedules', payload);
export const updateSchedule = (id, payload) => api.patch(`/tpms/schedules/${id}`, payload);
export const deleteSchedule = (id) => api.delete(`/tpms/schedules/${id}`);

// ── Lifecycle: two-step completion ──
// The doer claims it…
export const markLearnerDone = (id) => api.post(`/tpms/schedules/${id}/learner-done`);
// …and internal staff confirm. Only this sets status Completed.
export const confirmCompletion = (id) => api.post(`/tpms/schedules/${id}/confirm`);

// ── Lifecycle: reschedule workflow ──
export const requestReschedule = (id, payload) =>
  api.post(`/tpms/schedules/${id}/reschedule-request`, payload);
export const getRescheduleRequests = (status = 'Pending') =>
  api.get('/tpms/reschedule-requests', { params: { status } });
export const decideRescheduleRequest = (requestId, approve, note = '') =>
  api.post(`/tpms/reschedule-requests/${requestId}/decide`, { approve, note });

// ── Proof-of-work uploads ──
export const getScheduleUploads = (id) => api.get(`/tpms/schedules/${id}/uploads`);
export const uploadScheduleFile = (id, file) => {
  const form = new FormData();
  form.append('file', file);
  return api.post(`/tpms/schedules/${id}/uploads`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};
export const getCompanyUploads = (params) => api.get('/tpms/uploads', { params });

// ── Success measures ──
export const getSuccessMeasures = (params) => api.get('/tpms/success-measures', { params });
export const saveManualScore = (payload) => api.post('/tpms/manual-scores', payload);
export const syncSuccessMeasures = (period) =>
  api.post('/tpms/success-measures/sync', null, { params: { period: period || undefined } });

// ── Dashboards ──
export const getAnalyticsDashboard = (params) => api.get('/tpms/dashboards/analytics', { params });
export const getStaffDashboard = (params) => api.get('/tpms/dashboards/staff', { params });
export const getClientDashboard = (params) => api.get('/tpms/dashboards/client', { params });
export const getHodDashboard = (params) => api.get('/tpms/dashboards/hod', { params });
export const getEmployeeActivityDashboard = (params) =>
  api.get('/tpms/dashboards/employee-activity', { params });
export const getImplementationTracker = (params) =>
  api.get('/tpms/dashboards/implementation', { params });
export const getEscalationDashboard = (params) =>
  api.get('/tpms/dashboards/escalations', { params });

// ── Reports ──
export const getLogsReport = (params) => api.get('/tpms/reports/logs', { params });
export const getReviewReports = (params) => api.get('/tpms/reports/reviews', { params });

/** Current month as the canonical 'YYYY-MM' the backend expects. */
export const currentPeriod = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};

/** 'YYYY-MM' → 'July26', matching the label format the sheets used. */
export const periodLabel = (p) => {
  if (!p || p.length < 7) return '';
  const months = ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'];
  return `${months[Number(p.slice(5, 7)) - 1]}${p.slice(2, 4)}`;
};
