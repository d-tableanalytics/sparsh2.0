import api from './api';

/**
 * IRM — Individual Result Matrix ▸ API client.
 * Thin wrappers over the shared axios instance (house style — no react-query).
 * Backend routes live under /api/irm (see backend/app/routes/irm.py).
 *
 * `companyId` is only meaningful for internal staff; client-side users are pinned to
 * their own company server-side, so passing it (or not) makes no difference for them.
 */

/** The evaluation parameters + their seed weightages — so the UI hardcodes nothing. */
export const getIrmParameters = () => api.get('/irm/parameters');

/** A company's weightage column, its total, and whether it currently adds up to 100. */
export const getIrmConfig = (companyId) =>
  api.get('/irm/config', { params: { company_id: companyId || undefined } });

/**
 * Save the weightage column. `weightages` is [{code, weightage}] and must total exactly
 * 100 — the backend rejects anything else with a 400 carrying the reason.
 */
export const saveIrmConfig = (companyId, weightages) =>
  api.put('/irm/config', { weightages }, { params: { company_id: companyId || undefined } });

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

/** Refresh the stored snapshot. Reads are always live, so this is for history only. */
export const recalculateIrm = (companyId, period) =>
  api.post('/irm/recalculate', null, {
    params: { company_id: companyId || undefined, period: period || undefined },
  });
