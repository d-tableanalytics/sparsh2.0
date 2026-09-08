import api from './api';

/**
 * IRM — Individual Result Matrix ▸ API client.
 * Thin wrappers over the shared axios instance (house style — no react-query).
 * Backend routes live under /api/irm (see backend/app/routes/irm.py).
 *
 * `companyId` is only meaningful for internal staff; client-side users are pinned to
 * their own company server-side, so passing it (or not) makes no difference for them.
 */

/**
 * The roster the weightage screen picks from, each row flagged `has_override` so the
 * picker can mark who is already on their own column. Deliberately not /irm/scores:
 * filling a dropdown does not need everyone's tasks, ratings and punches computed.
 */
export const getIrmPeople = (companyId) =>
  api.get('/irm/people', { params: { company_id: companyId || undefined } });

/** The evaluation parameters + their seed weightages — so the UI hardcodes nothing. */
export const getIrmParameters = () => api.get('/irm/parameters');

/**
 * A weightage column, its total, and whether it currently adds up to 100.
 *
 * `personId` is optional and selects the SCOPE: omit it for the company column (what this
 * has always returned), pass it for that person's effective column. The response carries
 * `scope` ('person' | 'company' | 'default') and `inherited`, so the screen can tell a
 * person's own mix from the company one they are riding.
 */
export const getIrmConfig = (companyId, personId) =>
  api.get('/irm/config', {
    params: { company_id: companyId || undefined, person_id: personId || undefined },
  });

/**
 * Save a weightage column. `weightages` is [{code, weightage}] and must total exactly
 * 100 — the backend rejects anything else with a 400 carrying the reason.
 *
 * With `personId` this writes that person's override and leaves the company column and
 * everyone else untouched; without it, the company default.
 */
export const saveIrmConfig = (companyId, weightages, personId) =>
  api.put('/irm/config', { weightages }, {
    params: { company_id: companyId || undefined, person_id: personId || undefined },
  });

/** Drop one person's override so they inherit the company column again. */
export const clearIrmPersonConfig = (companyId, personId) =>
  api.delete('/irm/config', {
    params: { company_id: companyId || undefined, person_id: personId },
  });

/** Every person's IRM for a period, with the full per-parameter breakdown. */
export const getIrmScores = (companyId, period) =>
  api.get('/irm/scores', {
    params: { company_id: companyId || undefined, period: period || undefined },
  });

/** One person's IRM. */
export const getPersonIrm = (personId, companyId, period) =>
  api.get(`/irm/scores/${personId}`, {
    params: { company_id: companyId || undefined, period: period || undefined },
  });

/**
 * The shift punctuality is measured against — start, end and grace, all company-wide.
 * Changing it re-scores history on the next read: the verdict is derived from the stored
 * punches rather than frozen into them, so no re-import is needed.
 */
export const saveIrmShift = (companyId, shift) =>
  api.put('/irm/shift', shift, { params: { company_id: companyId || undefined } });

/**
 * Load punch times from an .xlsx/.csv export.
 *
 * The response reports `imported`, `updated`, `skipped` and any `unmatched` identifiers —
 * rows that matched nobody on the roster are named rather than guessed at, so a file whose
 * employee codes are wrong fails loudly instead of scoring the wrong people.
 */
export const importIrmAttendance = (companyId, file) => {
  const body = new FormData();
  body.append('file', file);
  return api.post('/irm/attendance/import', body, {
    params: { company_id: companyId || undefined },
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};

/**
 * The import template as an .xlsx blob: the expected headers plus a row per person, with
 * Employee ID / Name / Email already filled in. Those are the identifiers the importer
 * matches on, so starting from this file is what stops a whole import landing in
 * `unmatched` because the employee codes came from somewhere else.
 */
export const getIrmAttendanceTemplate = (companyId) =>
  api.get('/irm/attendance/template', {
    params: { company_id: companyId || undefined },
    responseType: 'blob',
  });

/**
 * The stored punches as an .xlsx blob, in exactly the shape the importer reads back —
 * so the export is also how a bad import gets corrected and re-loaded.
 * With nothing stored yet the server returns the empty template, headers and all.
 */
export const exportIrmAttendance = (companyId, period) =>
  api.get('/irm/attendance/export', {
    params: { company_id: companyId || undefined, period: period || undefined },
    responseType: 'blob',
  });

/** Refresh the stored snapshot. Reads are always live, so this is for history only. */
export const recalculateIrm = (companyId, period) =>
  api.post('/irm/recalculate', null, {
    params: { company_id: companyId || undefined, period: period || undefined },
  });
