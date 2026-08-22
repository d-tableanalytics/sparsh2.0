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

// The question master is company-scoped: a company that has edited a level reads and
// writes its own copy, everyone else the shared default. So every call below carries the
// company, exactly like the review and sign-off calls further down.

/** The level-specific question master, with per-level weightage totals. */
export const getLeadershipQuestions = (companyId, level, includeInactive = false) =>
  api.get('/leadership/questions', withCompany(companyId, {
    level: level || undefined,
    include_inactive: includeInactive || undefined,
  }));

/** Reword a question or restate its options. Level and item id are immutable. */
export const updateLeadershipQuestion = (companyId, questionId, payload) =>
  api.patch(`/leadership/questions/${questionId}`, payload, withCompany(companyId));

/** Set a level's weightage column. Rejected by the backend unless it totals exactly 100. */
export const saveLeadershipWeightages = (companyId, level, weightages) =>
  api.put('/leadership/questions/weightages', { level, weightages }, withCompany(companyId));

/** Re-insert any seeded question missing from a level (insert-only). */
export const restoreLeadershipQuestions = (companyId, level) =>
  api.post(`/leadership/questions/${level}/restore`, null, withCompany(companyId));

// No review or sign-off client: the seeded questions and options are the single source
// of truth and are used exactly as they stand. Nothing on this screen asks anyone to
// confirm them, and no approval gates a cycle.

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
   Stored in the shared tpms_mail_templates collection under a leadership-only key that
   now includes the COMPANY, so these calls read and write only that company's row.
   Editing one company's invitation no longer changes what any other company sends.
   `{{leadership_link}}` in the body becomes each giver's own /lf/<token> URL at dispatch
   time — nobody types a token. */
export const getLeadershipTemplate = (companyId) =>
  api.get('/leadership/template', withCompany(companyId));

export const saveLeadershipTemplate = (companyId, payload) =>
  api.put('/leadership/template', payload, withCompany(companyId));

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

// ── Eligibility ──
// "Applicable from L4 (Asst Managers) and above." `unlevelled` lists people who look
// senior but carry no leadership_level — the level is never guessed from a designation.
export const getLeadershipEligible = (companyId) =>
  api.get('/leadership/eligible', withCompany(companyId));

/** Put one leader on a different degree from the rest of their cycle (e.g. no direct reports). */
export const setLeadershipSubjectMode = (companyId, cycle, subjectId, modeOverride) =>
  api.patch(`/leadership/subjects/${subjectId}/mode`, { mode_override: modeOverride },
    withCompany(companyId, { cycle }));

// ── Close → compute → publish ──
// A leader sees nothing until publish. Without it they could watch their own number move
// during collection and difference it after each submission.
export const getLeadershipQuorum = (companyId, cycle) =>
  api.get(`/leadership/cycles/${cycle}/quorum`, withCompany(companyId));

export const computeLeadershipCycle = (companyId, cycle) =>
  api.post(`/leadership/cycles/${cycle}/compute`, {}, withCompany(companyId));

export const publishLeadershipCycle = (companyId, cycle) =>
  api.post(`/leadership/cycles/${cycle}/publish`, {}, withCompany(companyId));

// ── RRO discussion + action plan ──
// "Their respective reporting Manager should discuss the score with each leader during RRO."
export const getLeadershipDiscussion = (companyId, cycle, subjectId) =>
  api.get(`/leadership/subjects/${subjectId}/discussion`, withCompany(companyId, { cycle }));

export const logLeadershipDiscussion = (companyId, cycle, subjectId, payload) =>
  api.post(`/leadership/subjects/${subjectId}/discussion`, payload,
    withCompany(companyId, { cycle }));

export const acknowledgeLeadershipDiscussion = (companyId, cycle, subjectId, comment) =>
  api.patch(`/leadership/subjects/${subjectId}/discussion/acknowledge`, { comment },
    withCompany(companyId, { cycle }));

export const getLeadershipPendingDiscussions = (companyId, cycle) =>
  api.get(`/leadership/cycles/${cycle}/discussions/pending`, withCompany(companyId));

// ── Briefing tracker ──
export const getLeadershipBriefings = (companyId, cycle) =>
  api.get(`/leadership/cycles/${cycle}/briefings`, withCompany(companyId));

export const recordLeadershipBriefing = (companyId, cycle, payload) =>
  api.post(`/leadership/cycles/${cycle}/briefings`, payload, withCompany(companyId));

// ── Organisation roll-up ──
export const getLeadershipDashboard = (companyId, cycle) =>
  api.get('/leadership/dashboard', withCompany(companyId, { cycle: cycle || undefined }));
