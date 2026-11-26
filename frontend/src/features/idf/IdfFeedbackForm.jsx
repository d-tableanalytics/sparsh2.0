import React, { useState } from 'react';
import { AlertTriangle, Clock, Lightbulb } from 'lucide-react';
import { useNotification } from '../../context/NotificationContext';
import { submitIdfFeedback } from '../../services/idfApi';
import { FIELD } from './idfKit';

/* ─────────────────────────────────────────────────────────────
   The Inter-Departmental Feedback form itself — used by My Feedback Forms and by the page an
   emailed link opens, so both are the same form.

   Client requirement §3: each parameter rated 1–5 or N/A (blank = not applicable this cycle),
   a comment mandatory for the configured ratings (1, 2, 5), mandatory Strength / Improvement.
   ───────────────────────────────────────────────────────────── */

const NA = 'na';

const IdfFeedbackForm = ({ form, parameters, commentRequiredFor, ratingLabels, onSubmitted, onCancel }) => {
  const { showSuccess, showError } = useNotification();
  const [ratings, setRatings] = useState({});
  const [comments, setComments] = useState({});
  const [strength, setStrength] = useState('');
  const [improvement, setImprovement] = useState('');
  const [busy, setBusy] = useState(false);
  const params = parameters || [];
  const needComment = new Set(commentRequiredFor || [1, 2, 5]);
  const labels = ratingLabels || {};

  // What still blocks submission — shown next to the button so nobody guesses.
  const problems = [];
  params.forEach((p) => {
    const v = ratings[p.code];
    if (v === undefined) problems.push(`Rate ${p.name} (or N/A)`);
    else if (v !== NA && needComment.has(v) && !(comments[p.code] || '').trim()) problems.push(`Comment on ${p.name}`);
  });
  if (params.length && params.every((p) => ratings[p.code] === NA)) problems.push('Rate at least one parameter');
  if (!strength.trim()) problems.push('Strength');
  if (!improvement.trim()) problems.push('Improvement');

  const submit = async () => {
    if (problems.length || busy) return;
    setBusy(true);
    try {
      const res = await submitIdfFeedback({
        giver_dept_id: form.giver_dept_id, receiver_dept_id: form.receiver_dept_id,
        ratings: Object.fromEntries(params.map((p) => [p.code, ratings[p.code] === NA ? null : ratings[p.code]])),
        comments, strength: strength.trim(), improvement: improvement.trim(),
      });
      showSuccess(res.data?.cycle_completed
        ? 'Submitted — that was the last one; the cycle is complete and the report has gone to the MD.'
        : `Feedback for ${form.receiver_name} submitted. Your calendar activity is now Completed.`);
      onSubmitted?.(res.data);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not submit the feedback.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="space-y-4">
        {/* Standard Approach: "Teach good feedback" and "Rate the process, not the person". */}
        <div className="flex items-start gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--accent-indigo-bg)] px-3.5 py-2.5 text-[12px] text-[var(--text-main)]">
          <Lightbulb size={15} className="mt-0.5 shrink-0 text-[var(--accent-indigo)]" />
          <span>
            <b>Good feedback:</b> rate the process, not the person. Be specific — describe the situation and its effect,
            and suggest one change. A 1, 2 or 5 needs a one-line reason, so no score lands without context.
          </span>
        </div>
        <p className="text-[11.5px] text-[var(--text-muted)]">
          Scale: {Object.entries(ratingLabels || { 1: 'Poor', 2: 'Below Average', 3: 'Average', 4: 'Good', 5: 'Excellent' })
            .map(([n, l]) => `${n} ${l}`).join(' · ')} · N/A = not applicable this cycle.
        </p>
        {params.map((p) => {
          const v = ratings[p.code];
          const required = v !== undefined && v !== NA && needComment.has(v);
          return (
            <div key={p.code} className="space-y-1.5 rounded-xl border border-[var(--border)] p-3">
              <p className="text-[12.5px] font-black text-[var(--text-main)]">{p.name}</p>
              <p className="text-[12px] text-[var(--text-muted)]">{p.question.replace(/\b(the department|Department)\b/, form.receiver_name)}</p>
              <div className="flex flex-wrap gap-1.5">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button key={n} type="button" onClick={() => setRatings((r) => ({ ...r, [p.code]: n }))} title={labels[n]}
                    className={`min-w-[44px] px-2 h-9 rounded-lg border text-[12px] font-black transition-colors ${v === n
                      ? 'bg-[var(--accent-indigo)] border-[var(--accent-indigo)] text-white'
                      : 'border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--accent-indigo)]'}`}>
                    {n}
                  </button>
                ))}
                <button type="button" onClick={() => setRatings((r) => ({ ...r, [p.code]: NA }))}
                  className={`px-3 h-9 rounded-lg border text-[11.5px] font-black ${v === NA
                    ? 'bg-[var(--text-muted)] border-[var(--text-muted)] text-white' : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                  N/A
                </button>
                {v !== undefined && v !== NA && <span className="self-center text-[11.5px] font-bold text-[var(--text-muted)]">{labels[v]}</span>}
              </div>
              <textarea rows={2} value={comments[p.code] || ''} className={`${FIELD} w-full`}
                placeholder={required ? `Comment required for a rating of ${v}` : 'Comment (optional)'}
                onChange={(e) => setComments((c) => ({ ...c, [p.code]: e.target.value }))} />
            </div>
          );
        })}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="space-y-1">
            <span className="text-[12px] font-black text-[var(--text-main)]">Strength *</span>
            <textarea rows={3} value={strength} onChange={(e) => setStrength(e.target.value)} className={`${FIELD} w-full`}
              placeholder="One thing this department does well." />
          </label>
          <label className="space-y-1">
            <span className="text-[12px] font-black text-[var(--text-main)]">Improvement *</span>
            <textarea rows={3} value={improvement} onChange={(e) => setImprovement(e.target.value)} className={`${FIELD} w-full`}
              placeholder="One thing this department should improve." />
          </label>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 pt-4 mt-4 border-t border-[var(--border)]">
        <span className="text-[11px] text-[var(--text-muted)] inline-flex items-center gap-1">
          {problems.length
            ? <><AlertTriangle size={12} className="text-[var(--accent-orange)]" /> Still needed: {problems.slice(0, 3).join(' · ')}{problems.length > 3 ? '…' : ''}</>
            : <><Clock size={12} /> Once submitted it cannot be edited.</>}
        </span>
        <div className="flex gap-2">
          {onCancel && (
            <button type="button" onClick={onCancel} disabled={busy}
              className="px-4 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)]">Cancel</button>
          )}
          <button type="button" onClick={submit} disabled={problems.length > 0 || busy}
            className="px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-black disabled:opacity-50">
            {busy ? 'Submitting…' : 'Submit feedback'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default IdfFeedbackForm;
