import api from './api';

// Admin Reports & Analytics API (superadmin only on the backend).
// Thin wrappers over the shared axios instance so JWT + error handling are reused.

export const getEnterpriseOverview = (params) =>
  api.get('/reports/enterprise-overview', { params }).then((r) => r.data);

export const getReportsOverview = (params) =>
  api.get('/reports/overview', { params }).then((r) => r.data);

export const getCompanyReport = (params) =>
  api.get('/reports/company', { params }).then((r) => r.data);

export const getDepartmentsReport = (params) =>
  api.get('/reports/departments', { params }).then((r) => r.data);

export const getDoers = (params) =>
  api.get('/reports/doers', { params }).then((r) => r.data);

// E2 — Companies
export const getCompanies = (params) =>
  api.get('/reports/companies', { params }).then((r) => r.data);

export const getCompanyDashboard = (companyId, params) =>
  api.get(`/reports/companies/${companyId}`, { params }).then((r) => r.data);

export const getCompanyEmployees = (companyId, params) =>
  api.get(`/reports/companies/${companyId}/employees`, { params }).then((r) => r.data);

// E3 — Employee
export const getEmployeeReport = (userId, params) =>
  api.get(`/reports/employees/${userId}`, { params }).then((r) => r.data);

export const getEmployeeAssignments = (userId, params) =>
  api.get(`/reports/employees/${userId}/assignments`, { params }).then((r) => r.data);

export const getEmployeeAssessments = (userId) =>
  api.get(`/reports/employees/${userId}/assessments`).then((r) => r.data);

export const getEmployeeAttendance = (userId) =>
  api.get(`/reports/employees/${userId}/attendance`).then((r) => r.data);

export const getEmployeeTimeline = (userId, taskId) =>
  api.get(`/reports/employees/${userId}/timeline`, { params: { task_id: taskId } }).then((r) => r.data);

// Export a single employee's report (CSV / XLSX / PDF) — triggers a browser download.
export const exportEmployeeReport = async (userId, { format = 'csv', ...params } = {}) => {
  const res = await api.get(`/reports/employees/${userId}/export`, {
    params: { format, ...params },
    responseType: 'blob',
  });
  const blob = new Blob([res.data]);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `employee_report.${format}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

export const getDoerDetail = (doerId, params) =>
  api.get(`/reports/doers/${doerId}`, { params }).then((r) => r.data);

export const getDoerHistory = (doerId, params) =>
  api.get(`/reports/doers/${doerId}/history`, { params }).then((r) => r.data);

export const getDoerTimeline = (doerId, taskId) =>
  api.get(`/reports/doers/${doerId}/timeline`, { params: { task_id: taskId } }).then((r) => r.data);

// Streams a CSV / XLSX / PDF file and triggers a browser download.
export const exportReport = async ({ format = 'csv', ...params }) => {
  const res = await api.get('/reports/export', {
    params: { format, ...params },
    responseType: 'blob',
  });
  const ext = format;
  const blob = new Blob([res.data]);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `employee_performance.${ext}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};
