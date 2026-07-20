import api from './api';

/**
 * TPMS ▸ Forms sub-module API.
 * Thin wrappers over the shared axios instance (house style — no react-query).
 * Backend routes live under /api/forms (see backend/app/routes/forms.py).
 */

// All form definitions (criteria/scale registry).
export const getFormDefinitions = () => api.get('/forms/definitions');

// Companies for the selector (reuses the existing companies endpoint).
export const getCompanies = () => api.get('/companies');

// Candidate team members to rate for a company (optionally excluding the HOD).
export const getFormMembers = (companyId, hodId) =>
  api.get('/forms/members', { params: { company_id: companyId, hod_id: hodId || undefined } });

// ── Rating matrix (Ownership / Accountability / Culture) — cell-level partial submit ──
// Existing ratings for (company, period, hod) so already-saved cells lock.
export const getRatings = (formType, params) =>
  api.get(`/forms/${formType}/ratings`, { params });

// Submit only the newly-filled cells.
export const submitRatings = (formType, payload) =>
  api.post(`/forms/${formType}/ratings`, payload);

// List submissions for a form type, optionally filtered.
export const getFormSubmissions = (formType, params = {}) =>
  api.get(`/forms/${formType}/submissions`, { params });

// Fetch a single submission by id.
export const getFormSubmission = (submissionId) =>
  api.get(`/forms/submissions/${submissionId}`);

// ── Yes/No checklist (Implementation Feedback) ──
// Existing answers for (company, period, md) so already-saved slots lock.
export const getFeedback = (formType, params) =>
  api.get(`/forms/${formType}/feedback`, { params });

// Slot-by-slot submit (only unanswered questions are sent).
export const submitFeedback = (formType, payload) =>
  api.post(`/forms/${formType}/feedback`, payload);
