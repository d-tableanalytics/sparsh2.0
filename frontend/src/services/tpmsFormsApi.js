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

// Save a submission for a given form type.
export const submitForm = (formType, payload) =>
  api.post(`/forms/${formType}/submissions`, payload);

// List submissions for a form type, optionally filtered.
export const getFormSubmissions = (formType, params = {}) =>
  api.get(`/forms/${formType}/submissions`, { params });

// Fetch a single submission by id.
export const getFormSubmission = (submissionId) =>
  api.get(`/forms/submissions/${submissionId}`);
