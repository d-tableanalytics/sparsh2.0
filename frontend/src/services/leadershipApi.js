import api from './api';

/**
 * TPMS ▸ Leadership Score API client.
 * Thin wrappers over the shared axios instance (house style — no react-query).
 * Backend routes live under /api/leadership (see backend/app/routes/leadership.py).
 *
 * `companyId` is only meaningful for internal staff; client-side users are pinned to
 * their own company server-side, so passing it makes no difference for them.
 */

const withCompany = (companyId, extra = {}) => ({
  params: { company_id: companyId || undefined, ...extra },
});

// ── Configuration ──
/** Levels, relations, degrees, cycle options and this user's permissions. */
export const getLeadershipConfig = () => api.get('/leadership/config');

/** The level-specific question master, with per-level weightage totals. */
export const getLeadershipQuestions = (level, includeInactive = false) =>
  api.get('/leadership/questions', {
    params: { level: level || undefined, include_inactive: includeInactive || undefined },
  });

/** Reword a question or restate its options. Level and item id are immutable. */
export const updateLeadershipQuestion = (questionId, payload) =>
  api.patch(`/leadership/questions/${questionId}`, payload);

/** Set a level's weightage column. Rejected by the backend unless it totals exactly 100. */
export const saveLeadershipWeightages = (level, weightages) =>
  api.put('/leadership/questions/weightages', { level, weightages });

/** Re-insert any seeded question missing from a level (insert-only). */
export const restoreLeadershipQuestions = (level) =>
  api.post(`/leadership/questions/${level}/restore`);

// ── Cycles (the 2-month assessment window) ──
export const getLeadershipCycles = (companyId) =>
  api.get('/leadership/cycles', withCompany(companyId));

export const createLeadershipCycle = (companyId, payload) =>
  api.post('/leadership/cycles', payload, withCompany(companyId));

export const updateLeadershipCycle = (companyId, cycle, payload) =>
  api.patch(`/leadership/cycles/${cycle}`, payload, withCompany(companyId));

// ── Subjects (the leaders being rated) ──
/** The company roster HR picks leaders and feedback givers from. */
export const getLeadershipPeople = (companyId) =>
  api.get('/leadership/people', withCompany(companyId));

export const getLeadershipSubjects = (companyId, cycle) =>
  api.get('/leadership/subjects', withCompany(companyId, { cycle }));

export const addLeadershipSubject = (companyId, cycle, payload) =>
  api.post('/leadership/subjects', payload, withCompany(companyId, { cycle }));

export const removeLeadershipSubject = (companyId, cycle, subjectId) =>
  api.delete(`/leadership/subjects/${subjectId}`, withCompany(companyId, { cycle }));

// ── Feedback givers — HR only. These are the only calls that carry giver identity. ──
export const getLeadershipPanel = (companyId, cycle, subjectId) =>
  api.get(`/leadership/subjects/${subjectId}/panel`, withCompany(companyId, { cycle }));

export const saveLeadershipPanel = (companyId, cycle, subjectId, givers) =>
  api.put(`/leadership/subjects/${subjectId}/panel`, { givers },
    withCompany(companyId, { cycle }));

/** Email every pending link for the cycle, or for one leader. */
export const dispatchLeadershipLinks = (companyId, cycle, subjectId) =>
  api.post(`/leadership/cycles/${cycle}/dispatch`, null,
    withCompany(companyId, { subject_id: subjectId || undefined }));

export const resendLeadershipLink = (assignmentId) =>
  api.post(`/leadership/assignments/${assignmentId}/resend`);

export const getLeadershipAssignments = (companyId, cycle) =>
  api.get('/leadership/assignments', withCompany(companyId, { cycle: cycle || undefined }));

/* ── Invitation email template (HR / Admin) ──
   Stored in the shared tpms_mail_templates collection under a leadership-only key, so
   these calls can only ever read or write that one row. `{{leadership_link}}` in the body
   becomes each giver's own /lf/<token> URL at dispatch time — nobody types a token. */
export const getLeadershipTemplate = () => api.get('/leadership/template');

export const saveLeadershipTemplate = (payload) => api.put('/leadership/template', payload);

/** Render a draft against sample values. The link shown is a fake, never a real token. */
export const previewLeadershipTemplate = (payload) =>
  api.post('/leadership/template/preview', payload);

// ── The giver's form (opened by token at /lf/<token>) ──
export const getAssignedLeadershipForm = (token) =>
  api.get(`/leadership/assigned/${token}`);

export const submitLeadershipFeedback = (token, answers) =>
  api.post(`/leadership/assigned/${token}/submit`, { answers });

/** The feedback forms the signed-in user still owes. */
export const getMyLeadershipFeedback = () => api.get('/leadership/my-feedback');

// ── Results — aggregates only; these never carry giver identity ──
export const getLeadershipScores = (companyId, cycle) =>
  api.get('/leadership/scores', withCompany(companyId, { cycle }));

export const getLeaderScore = (companyId, cycle, subjectId) =>
  api.get(`/leadership/scores/${subjectId}`, withCompany(companyId, { cycle }));
