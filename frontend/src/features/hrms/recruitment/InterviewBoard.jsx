import React, { useCallback, useEffect, useState } from 'react';
import {
  CalendarClock, Plus, X, Video, MapPin, Star, CalendarDays, Ban, Download, Clock,
  CalendarPlus, Paperclip, ChevronRight, Check,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getInterviews, getSchedulableCandidates, scheduleInterview, updateInterview,
  cancelInterview, evaluateInterview, getInterviewPanelOptions, downloadInterviewInvite,
  downloadInterviewRecording, attachInterviewMedia, removeInterviewMedia,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ interviews.
 *
 * Grouped by day, because "what is happening today" is the question this screen exists to
 * answer. Every row carries `can_evaluate` computed **server-side**, so the Evaluate button
 * appears only where the API will actually accept a scorecard — including the MD-round
 * restriction, which the client never has to know about.
 */

const ROUNDS = ['Panel Interview', 'HR Round', 'Technical', 'Manager Round', 'MD Round'];
// Internal vacancies use the server's round list (Panel Interview; + Management for senior roles).
const OTHER_ROUNDS = ROUNDS.filter((r) => r !== 'Panel Interview');
const STATUSES = ['Scheduled', 'Completed', 'Cancelled', 'No Show'];
const COMPETENCIES = [
  ['technical', 'Technical Knowledge'],
  ['communication', 'Communication'],
  ['problem_solving', 'Problem Solving'],
  ['behavior', 'Behaviour'],
  ['confidence', 'Confidence'],
  ['team_fit', 'Team Fit'],
];

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

const STATUS_TONE = {
  Scheduled: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Completed: 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
  Cancelled: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  'No Show': 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
};
const OUTCOME_TONE = {
  Pass: 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
  Fail: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
  Hold: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
};

/** Human day header — "Today", "Tomorrow", else a weekday + date. */
const dayLabel = (iso) => {
  if (!iso) return 'Unscheduled';
  const d = new Date(`${iso}T00:00:00`);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((d - today) / 86400000);
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Tomorrow';
  if (diff === -1) return 'Yesterday';
  return d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' });
};

const timeOf = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '—'
    : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

// One numbered block of the schedule form. Module-level on purpose: a component defined
// inside the modal would be a new type every render, remounting the inputs (and dropping
// focus) on each keystroke.
const Section = ({ n, title, children }) => (
  <section className="space-y-2.5">
    <p className="flex items-center gap-2 text-[12px] font-bold text-[var(--text-main)]">
      <span className="h-5 w-5 grid place-items-center rounded-full bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[10.5px]">{n}</span>
      {title}
    </p>
    {children}
  </section>
);

const ScheduleModal = ({ onClose, onScheduled }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [people, setPeople] = useState([]);
  // Only the people who conduct interviews (HR, HOD / Manager, MD) — see panel_options.
  const [options, setOptions] = useState({ people: [], internal: false, required_roles: [], required_labels: [] });
  const [panelIds, setPanelIds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    uk: '', round: 'HR Round', mode: 'Virtual', scheduled_at: '',
    duration_min: 45, interviewer_id: '', meeting_link: '', location: '', notes: '',
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    Promise.all([
      getSchedulableCandidates(scope).then(({ data }) => setPeople(data?.candidates || [])),
      getInterviewPanelOptions(null, scope).then(({ data }) => setOptions(data)),
    ]).catch((err) => showError(err?.response?.data?.detail || 'Could not load options.'))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The rounds and the panel depend on the candidate's vacancy (and the round chosen), so
  // re-read them when either changes. On an internal vacancy the server picks the round that
  // is due next; the form follows it.
  useEffect(() => {
    if (!form.uk) return;
    getInterviewPanelOptions(form.uk, { ...scope, round: form.round }).then(({ data }) => {
      setOptions(data);
      if (data?.internal && data.round && data.round !== form.round) {
        setForm((f) => ({ ...f, round: data.round }));
      }
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.uk, form.round]);

  const isFinalRound = options.internal && form.round === 'MD Round';
  // The Management interview is the MD's own sitting, so only Management may lead it.
  const leaders = (options.people || []).filter((p) => !isFinalRound || p.role === 'md');

  const byId = Object.fromEntries((options.people || []).map((p) => [p.user_id, p]));
  // The interviewer always sits on the panel.
  const panel = [...new Set([form.interviewer_id, ...panelIds].filter(Boolean))];
  const coveredRoles = new Set(panel.map((id) => byId[id]?.role).filter(Boolean));
  const missing = (options.required_roles || []).filter((r) => !coveredRoles.has(r));
  const labelOf = { hr: 'HR', manager: 'HOD / Manager', md: 'MD' };
  const togglePanel = (id) => setPanelIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const { data } = await scheduleInterview({
        ...form,
        panel: options.internal ? panel.map((user_id) => ({ user_id })) : undefined,
        duration_min: Number(form.duration_min) || 45,
        meeting_link: form.mode === 'Virtual' ? form.meeting_link : null,
        location: form.mode === 'Offline' ? form.location : null,
      }, scope);
      // The server WARNS and never blocks (short notice, an interview outside the
      // department's window). A warning the screen swallows is one nobody acts on.
      if (data?.warning) showError(data.warning);
      showSuccess('Interview scheduled');
      onScheduled();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not schedule the interview.');
    } finally {
      setSaving(false);
    }
  };

  // What still stands between the form and a booking, in plain words, for the footer.
  const roundDue = !options.internal || !form.uk
    || (options.rounds || []).some((r) => r.value === form.round && r.available);
  const blockers = !roundDue
    ? ['nothing is due — this candidate has had their interview (next step: the Shortlist Committee)']
    : [
    !form.uk && 'pick a candidate',
    !form.scheduled_at && 'choose the date & time',
    !form.interviewer_id && 'choose the interviewer',
    options.internal && form.uk && missing.length > 0
      && `add ${missing.map((r) => labelOf[r] || r).join(' and ')} to the panel`,
    form.mode === 'Virtual' && !form.meeting_link.trim() && 'add the meeting link',
    form.mode === 'Offline' && !form.location.trim() && 'add the location',
  ].filter(Boolean);

  const chosen = people.find((p) => p.uk === form.uk);
  // The candidate's path on an internal vacancy, with the step being booked highlighted.
  const path = !options.internal ? [] : options.two_interviews
    ? [['Panel Interview', 'Panel Interview'], ['Management Interview', 'MD Round'],
      ['MD final decision']]
    : [['Panel Interview', 'Panel Interview'], ['Committee (HR + HOD)'], ['Selected']];
  const ROUND_TITLE = { 'Panel Interview': 'Panel Interview', 'MD Round': 'Management Interview' };
  const roundSub = (r) => (r.value === 'MD Round'
    ? 'With the MD, who then makes the final decision'
    : `Panel: ${(r.value === form.round ? options.required_labels : null)?.join(' + ') || r.label.replace(/^[^(]*\(|\)$/g, '')}`);
  const seats = [['hr', 'HR'], ['manager', 'HOD / Manager'], ['md', 'MD']];
  const needs = new Set(options.required_roles || []);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-3 sm:p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[92vh] flex flex-col">
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-[var(--border)]">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold text-[var(--text-main)]">Schedule an interview</h2>
            <p className="text-[11.5px] text-[var(--text-muted)] truncate">
              {chosen ? `${chosen.candidate_name} · ${chosen.request_no || ''}` : 'Pick the candidate, then the round, time and panel.'}
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <form id="schedule-form" onSubmit={submit} className="px-5 py-4 space-y-5 overflow-y-auto">
          <Section n="1" title="Candidate & round">
            {loading ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Loading…</p>
            ) : people.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                No candidates are ready to interview. Roles that require an assessment only
                become schedulable once the candidate reaches <strong>Assessment Passed</strong>.
              </p>
            ) : (
              <select id="i-uk" required value={form.uk} onChange={set('uk')} className={FIELD}>
                <option value="">Select a candidate…</option>
                {people.map((p) => (
                  <option key={p.uk} value={p.uk}>{p.candidate_name} — {p.application_status}</option>
                ))}
              </select>
            )}

            {form.uk && path.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                {path.map(([label, round], idx) => (
                  <React.Fragment key={label}>
                    {idx > 0 && <ChevronRight size={12} className="text-[var(--text-muted)]" />}
                    <span className={`px-2 py-0.5 rounded-full border font-semibold ${
                      round && round === form.round
                        ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                        : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                      {label}
                    </span>
                  </React.Fragment>
                ))}
                <span className="basis-full text-[var(--text-muted)]">
                  {options.two_interviews
                    ? 'Senior / managerial role: two interviews. Pass the Panel Interview and the candidate goes to the Management interview with the MD, who makes the final decision. A fail on the panel stops here.'
                    : 'Junior / mid role: one interview only. After it, the committee (HR + HOD) decides — 4.0+ strong, below 3.0 reject.'}
                </span>
              </div>
            )}

            {form.uk && (options.internal && (options.rounds || []).length ? (
              <div role="radiogroup" aria-label="Round" className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {options.rounds.map((r) => {
                  const on = form.round === r.value;
                  return (
                    <button key={r.value} type="button" role="radio" aria-checked={on}
                      disabled={!r.available}
                      onClick={() => setForm((f) => ({ ...f, round: r.value }))}
                      className={`text-left rounded-xl border px-3 py-2.5 transition ${on
                        ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]'
                        : 'border-[var(--border)] hover:border-[var(--accent-indigo)]'} disabled:opacity-50 disabled:cursor-not-allowed`}>
                      <p className={`text-[13px] font-bold ${on ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-main)]'}`}>
                        {ROUND_TITLE[r.value] || r.value}
                      </p>
                      <p className="text-[11px] text-[var(--text-muted)]">
                        {r.available ? roundSub(r)
                          : /^already/.test(r.reason || '') ? `Already ${r.reason.replace(/^already /, '')}`
                            : `Opens ${r.reason}`}
                      </p>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div>
                <label className={LABEL} htmlFor="i-round">Round</label>
                <select id="i-round" value={form.round} onChange={set('round')} className={FIELD}>
                  {OTHER_ROUNDS.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
            ))}
          </Section>

          <Section n="2" title="When & where">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="sm:col-span-2">
                <label className={LABEL} htmlFor="i-when">Date &amp; time *</label>
                <input id="i-when" type="datetime-local" required value={form.scheduled_at}
                  onChange={set('scheduled_at')} className={FIELD} />
              </div>
              <div>
                <label className={LABEL} htmlFor="i-dur">Duration (min)</label>
                <input id="i-dur" type="number" min="15" step="15" value={form.duration_min}
                  onChange={set('duration_min')} className={FIELD} />
              </div>
            </div>
            <div className="flex gap-2" role="radiogroup" aria-label="Mode">
              {[['Virtual', 'Virtual (video call)', Video], ['Offline', 'In person', MapPin]].map(([v, l, Icon]) => (
                <button key={v} type="button" role="radio" aria-checked={form.mode === v}
                  onClick={() => setForm((f) => ({ ...f, mode: v }))}
                  className={`flex-1 h-9 rounded-lg border text-[12px] font-bold inline-flex items-center justify-center gap-1.5 ${
                    form.mode === v ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                      : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                  {React.createElement(Icon, { size: 13 })} {l}
                </button>
              ))}
            </div>
            {form.mode === 'Virtual' ? (
              <input id="i-link" required value={form.meeting_link} onChange={set('meeting_link')}
                aria-label="Meeting link" placeholder="Meeting link — https://meet.google.com/…" className={FIELD} />
            ) : (
              <input id="i-loc" required value={form.location} onChange={set('location')}
                aria-label="Location" placeholder="Location — meeting room, floor, address…" className={FIELD} />
            )}
          </Section>

          <Section n="3" title="Who will interview">
            <div>
              <label className={LABEL} htmlFor="i-who">Interviewer (leads it) *</label>
              <select id="i-who" required value={form.interviewer_id}
                onChange={set('interviewer_id')} className={FIELD}>
                <option value="">Select who will take it…</option>
                {leaders.map((s) => (
                  <option key={s.user_id} value={s.user_id}>{s.name} — {s.role_label}</option>
                ))}
              </select>
              <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                {isFinalRound
                  ? 'The Management interview is led by the MD.'
                  : 'Only people who conduct interviews are listed: HR, HODs / Managers and the MD.'}
              </p>
            </div>

            {options.internal && form.uk && (options.required_roles || []).length > 0 && (
              <div className="rounded-xl border border-[var(--border)] p-3 space-y-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[12px] font-bold text-[var(--text-main)]">Interview panel</p>
                  <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${missing.length
                    ? 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]'
                    : 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,#16a34a)]'}`}>
                    {missing.length ? `Still needed: ${missing.map((r) => labelOf[r] || r).join(', ')}` : 'Panel complete'}
                  </span>
                </div>
                <p className="text-[11px] text-[var(--text-muted)]">
                  {isFinalRound
                    ? 'The MD is required. HR or the HOD may sit in if you tick them.'
                    : 'Tick one person for each needed seat — each a different person. The interviewer is on the panel automatically.'}
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  {seats.map(([role, title]) => {
                    const inSeat = (options.people || []).filter((p) => p.role === role);
                    const covered = coveredRoles.has(role);
                    return (
                      <div key={role} className="rounded-lg bg-[var(--input-bg)] p-2 space-y-1.5">
                        <p className="flex items-center justify-between text-[10.5px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
                          {title}
                          <span className={covered ? 'text-[var(--accent-green,#16a34a)]' : needs.has(role) ? 'text-[var(--accent-orange)]' : ''}>
                            {covered ? <span className="inline-flex items-center gap-0.5"><Check size={11} /> set</span>
                              : needs.has(role) ? 'needed' : 'optional'}
                          </span>
                        </p>
                        {inSeat.length === 0 && <p className="text-[11px] text-[var(--text-muted)]">Nobody with this role</p>}
                        {inSeat.map((p) => {
                          const isLead = p.user_id === form.interviewer_id;
                          const on = panel.includes(p.user_id);
                          return (
                            <label key={p.user_id}
                              className={`flex items-start gap-2 rounded-md border px-2 py-1.5 text-[12px] cursor-pointer bg-[var(--bg-card)] ${
                                on ? 'border-[var(--accent-indigo)]' : 'border-transparent'}`}>
                              <input type="checkbox" className="mt-0.5" checked={on} disabled={isLead}
                                onChange={() => togglePanel(p.user_id)} />
                              <span className="min-w-0 leading-tight">
                                <span className="block font-semibold text-[var(--text-main)] break-words">{p.name}</span>
                                {isLead && <span className="text-[10.5px] text-[var(--accent-indigo)] font-semibold">interviewer</span>}
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </Section>

          <Section n="4" title="Notes (optional)">
            <textarea id="i-notes" rows={2} value={form.notes} onChange={set('notes')}
              placeholder="Anything the panel should know — CV points to probe, documents to bring…"
              className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] resize-y" />
          </Section>
        </form>

        <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 border-t border-[var(--border)]">
          <p className="text-[11.5px] text-[var(--text-muted)] min-w-0">
            {blockers.length ? <>To schedule: {blockers.join(', ')}.</> : <span className="text-[var(--accent-green,#16a34a)] font-semibold">Ready to schedule.</span>}
          </p>
          <div className="flex gap-2 ml-auto">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="submit" form="schedule-form" disabled={saving || blockers.length > 0}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Scheduling…' : 'Schedule'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

const StarRow = ({ label, value, onChange }) => (
  <div className="flex items-center justify-between gap-3">
    <span className="text-[12.5px] text-[var(--text-main)]">{label}</span>
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" aria-label={`${label} ${n}`}
          // Clicking the current value clears it — otherwise a mis-click can never be undone.
          onClick={() => onChange(value === n ? 0 : n)}
          className={n <= value ? 'text-[var(--accent-indigo)]' : 'text-[var(--border)]'}>
          <Star size={17} fill={n <= value ? 'currentColor' : 'none'} />
        </button>
      ))}
    </div>
  </div>
);

const EvaluateModal = ({ interview: i, onClose, onEvaluated }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [scores, setScores] = useState(
    Object.fromEntries(COMPETENCIES.map(([k]) => [k, 0])));
  const [outcome, setOutcome] = useState('');
  const [remarks, setRemarks] = useState('');
  const [signature, setSignature] = useState('');
  const [saving, setSaving] = useState(false);

  const isMd = i.round === 'MD Round';

  const submit = async () => {
    setSaving(true);
    try {
      await evaluateInterview(i.interview_no, {
        ...scores, outcome, remarks: remarks.trim() || null, signature: signature.trim(),
      }, scope);
      showSuccess(`Recorded: ${outcome}`);
      onEvaluated();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the evaluation.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold text-[var(--text-main)] truncate">
              {isMd ? 'MD final decision — Management interview' : 'Evaluate interview'}
            </h2>
            <p className="text-[11.5px] text-[var(--text-muted)]">
              {i.candidate_name} · {i.round}
            </p>
          </div>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <div className="p-5 space-y-4 overflow-y-auto">
          <div className="space-y-2">
            {COMPETENCIES.map(([key, label]) => (
              <StarRow key={key} label={label} value={scores[key]}
                onChange={(v) => setScores((s) => ({ ...s, [key]: v }))} />
            ))}
          </div>

          <div>
            <span className={LABEL}>Decision *</span>
            <div className="flex gap-2">
              {(isMd ? ['Pass', 'Hold', 'Fail'] : ['Pass', 'Hold', 'Fail']).map((v) => (
                <button key={v} type="button" onClick={() => setOutcome(v)}
                  className={`flex-1 h-9 rounded-lg border text-[12.5px] font-bold ${
                    outcome === v
                      ? v === 'Pass'
                        ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                        : v === 'Fail'
                        ? 'border-[var(--accent-red)] bg-[var(--accent-red-bg)] text-[var(--accent-red)]'
                        : 'border-[var(--border)] bg-[var(--input-bg)] text-[var(--text-main)]'
                      : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                  {isMd && v === 'Pass' ? 'Approve' : isMd && v === 'Fail' ? 'Reject' : v}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className={LABEL} htmlFor="e-remarks">Remarks</label>
            <textarea id="e-remarks" rows={3} value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] resize-none" />
          </div>

          <div>
            <label className={LABEL} htmlFor="e-sign">Signature *</label>
            <input id="e-sign" value={signature} onChange={(e) => setSignature(e.target.value)}
              placeholder="Type your full name" className={FIELD} />
            <p className="mt-1 text-[11px] text-[var(--text-muted)]">
              This evaluation may justify a rejection later, so it is recorded against your name.
            </p>
          </div>

          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="button" disabled={saving || !outcome || !signature.trim()}
              onClick={submit}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Saving…' : 'Record'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────
// The interview recording. The ERP does not record calls itself — they run on Meet / Zoom /
// in person — so a recording exists once someone attaches it here: the file, or the link
// where the meeting tool saved it.
// ─────────────────────────────────────────────────────────────
const MAX_RECORDING_MB = 500;
const readAsDataUrl = (file) => new Promise((resolve, reject) => {
  const r = new FileReader();
  r.onload = () => resolve(r.result);
  r.onerror = () => reject(new Error('The file could not be read.'));
  r.readAsDataURL(file);
});
const fmtSize = (b) => (b ? `${(b / 1024 / 1024).toFixed(b > 10 * 1024 * 1024 ? 0 : 1)} MB` : '');

const RecordingModal = ({ interview: i, canAttach, onClose, onChanged, onDownload }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [how, setHow] = useState('file');
  const [file, setFile] = useState(null);
  const [link, setLink] = useState('');
  const [saving, setSaving] = useState(false);
  const rec = i.recording;

  const attach = async () => {
    setSaving(true);
    try {
      let body;
      if (how === 'link') {
        body = { external_url: link.trim(), name: 'Meeting recording' };
      } else {
        if (file.size > MAX_RECORDING_MB * 1024 * 1024) {
          showError(`That file is over ${MAX_RECORDING_MB} MB — attach a link to the recording instead.`);
          setSaving(false); return;
        }
        body = { name: file.name, mime_type: file.type, data: await readAsDataUrl(file) };
      }
      await attachInterviewMedia(i.interview_no, 'recording', body, scope);
      showSuccess(rec ? 'Recording replaced.' : 'Recording attached — it can now be downloaded.');
      onChanged();
    } catch (err) {
      showError(err?.response?.data?.detail || err?.message || 'Could not attach the recording.');
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm('Remove this recording from the interview?')) return;
    setSaving(true);
    try {
      await removeInterviewMedia(i.interview_no, 'recording', scope);
      showSuccess('Recording removed.');
      onChanged();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not remove the recording.');
    } finally {
      setSaving(false);
    }
  };

  const ready = how === 'link' ? /^https?:\/\//i.test(link.trim()) : !!file;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold text-[var(--text-main)] truncate">Interview recording</h2>
            <p className="text-[11.5px] text-[var(--text-muted)]">{i.candidate_name} · {i.round} · {i.interview_no}</p>
          </div>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <div className="p-5 space-y-4 overflow-y-auto">
          {rec ? (
            <div className="rounded-xl border border-[var(--border)] p-3 space-y-2">
              <p className="text-[13px] font-semibold text-[var(--text-main)] break-all">
                {rec.is_external ? 'Link to the meeting recording' : rec.name}
              </p>
              <p className="text-[11px] text-[var(--text-muted)]">
                {[fmtSize(rec.size_bytes), rec.uploaded_by_name && `added by ${rec.uploaded_by_name}`,
                  rec.uploaded_at && new Date(rec.uploaded_at).toLocaleDateString()].filter(Boolean).join(' · ')}
              </p>
              <button type="button" onClick={() => onDownload(i)}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold inline-flex items-center gap-1.5">
                <Download size={13} /> {rec.is_external ? 'Open recording' : 'Download recording'}
              </button>
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-[var(--border)] p-3">
              <p className="text-[13px] font-semibold text-[var(--text-main)]">No recording yet</p>
              <p className="mt-1 text-[11.5px] text-[var(--text-muted)]">
                Sparsh does not record calls by itself. After the interview, attach the recording
                here — the video/audio file, or the link where Google Meet / Zoom saved it.
                {!canAttach && ' Ask HR to attach it.'}
              </p>
            </div>
          )}

          {canAttach && (
            <div className="space-y-3">
              <p className={LABEL}>{rec ? 'Replace the recording' : 'Attach the recording'}</p>
              <div className="flex gap-2">
                {[['file', 'Upload a file'], ['link', 'Paste a link']].map(([v, l]) => (
                  <button key={v} type="button" onClick={() => setHow(v)}
                    className={`flex-1 h-9 rounded-lg border text-[12px] font-bold ${
                      how === v ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                        : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                    {l}
                  </button>
                ))}
              </div>
              {how === 'file' ? (
                <div>
                  <input type="file" accept="video/mp4,video/webm,video/quicktime,video/x-matroska,audio/mpeg,audio/mp4,audio/wav,audio/webm"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                    className="block w-full text-[12px] text-[var(--text-main)]" />
                  <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                    Video (MP4, WebM, MOV, MKV) or audio (MP3, M4A, WAV), up to {MAX_RECORDING_MB} MB.
                  </p>
                </div>
              ) : (
                <div>
                  <input type="url" value={link} onChange={(e) => setLink(e.target.value)}
                    placeholder="https://drive.google.com/… or https://zoom.us/rec/…" className={FIELD} />
                  <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                    Best for long calls — the recording stays where Meet / Zoom saved it.
                  </p>
                </div>
              )}
              <div className="flex justify-between gap-2">
                {rec ? (
                  <button type="button" onClick={remove} disabled={saving}
                    className="h-9 px-3 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--accent-red)] disabled:opacity-50">
                    Remove
                  </button>
                ) : <span />}
                <button type="button" onClick={attach} disabled={saving || !ready}
                  className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
                  {saving ? 'Saving…' : rec ? 'Replace' : 'Attach'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const InterviewBoard = () => {
  const { can, scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  // Save the interview's calendar invite (.ics) — opens in Outlook / Google / Apple Calendar.
  const downloadInvite = async (no) => {
    try {
      const { data } = await downloadInterviewInvite(no, scope);
      const url = URL.createObjectURL(new Blob([data], { type: 'text/calendar' }));
      const a = document.createElement('a');
      a.href = url; a.download = `${no}.ics`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      let msg = 'Could not download the calendar invite.';
      try { msg = JSON.parse(await err?.response?.data?.text?.())?.detail || msg; } catch { /* keep default */ }
      showError(msg);
    }
  };

  const [data, setData] = useState({ interviews: [], stats: {} });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [round, setRound] = useState('');
  const [status, setStatus] = useState('');
  const [showSchedule, setShowSchedule] = useState(false);
  const [evaluating, setEvaluating] = useState(null);
  const [recordingFor, setRecordingFor] = useState(null);

  const canSchedule = can(CAP.INTERVIEW_SCHEDULE);
  const canAttachRecording = can(CAP.INTERVIEW_MEDIA);

  // Download: the interview's recording. None attached yet -> the recording window, where
  // HR can attach it (and anyone else is told who to ask).
  const downloadRecording = async (i) => {
    if (!i.recording) { setRecordingFor(i); return; }
    try {
      const { data } = await downloadInterviewRecording(i.interview_no, scope);
      if (data.external_url) {
        window.open(data.external_url, '_blank', 'noopener,noreferrer');
        return;
      }
      const a = document.createElement('a');
      a.href = data.download_url; a.download = data.name || `${i.interview_no}-recording`;
      a.rel = 'noopener';
      document.body.appendChild(a); a.click(); a.remove();
      showSuccess('Recording download started.');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not download the recording.');
    }
  };

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data: res } = await getInterviews({
        ...scope, round: round || undefined, status: status || undefined,
      });
      setData(res);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load interviews.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, round, status]);

  useEffect(() => { load(); }, [load]);

  const setStatusFor = async (i, next) => {
    try {
      await updateInterview(i.interview_no, { status: next }, scope);
      showSuccess(`${i.interview_no} marked ${next}`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not update the interview.');
    }
  };

  const cancel = async (i) => {
    if (!window.confirm(`Cancel ${i.interview_no} (${i.round} — ${i.candidate_name})?`)) return;
    try {
      await cancelInterview(i.interview_no, scope);
      showSuccess('Interview cancelled');
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not cancel.');
    }
  };

  // Group by day, preserving the server's chronological order.
  const groups = [];
  data.interviews.forEach((i) => {
    const key = i.day || null;
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(i);
    else groups.push({ key, items: [i] });
  });

  const stats = data.stats || {};

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={CalendarClock}
        title="Interviews"
        subtitle="Schedule rounds, capture scorecards and drive the decision chain."
        actions={
          <div className="flex items-center gap-2">
            <HrmsScopeBar />
            {canSchedule && (
              <button type="button" onClick={() => setShowSchedule(true)}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5">
                <Plus size={14} /> Schedule
              </button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[['Today', stats.today], ['Upcoming', stats.upcoming],
          ['Completed', stats.completed], ['Cancelled / No show', stats.dropped]].map(([l, v]) => (
          <div key={l} className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
            <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{l}</p>
            <p className="mt-1.5 text-[20px] font-bold text-[var(--text-main)]">{v ?? 0}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select value={round} onChange={(e) => setRound(e.target.value)}
          className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]">
          <option value="">All rounds</option>
          {ROUNDS.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]">
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {loading ? (
        <HrmsLoading label="Loading interviews…" />
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : data.interviews.length === 0 ? (
        <HrmsEmpty icon={CalendarClock} title="No interviews scheduled"
          hint={canSchedule
            ? 'Schedule one for a candidate who has cleared screening or their assessment.'
            : 'Interviews you are booked for will appear here.'} />
      ) : (
        <div className="space-y-5">
          {groups.map((g) => (
            <div key={g.key || 'none'}>
              <p className="mb-2 text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] flex items-center gap-1.5">
                <CalendarDays size={12} /> {dayLabel(g.key)}
              </p>
              <div className="space-y-2">
                {g.items.map((i) => (
                  <div key={i.interview_no}
                    className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] flex flex-wrap items-center gap-3">
                    <div className="text-center shrink-0 w-16">
                      <p className="text-[14px] font-bold text-[var(--text-main)]">
                        {timeOf(i.scheduled_at)}
                      </p>
                      <p className="text-[10.5px] text-[var(--text-muted)]">{i.duration_min}m</p>
                    </div>

                    <div className="min-w-0 flex-1">
                      <p className="text-[13.5px] font-bold text-[var(--text-main)] truncate">
                        {i.candidate_name}
                      </p>
                      <p className="text-[11.5px] text-[var(--text-muted)] flex items-center gap-1.5 flex-wrap">
                        <span>{i.round}</span>
                        <span>·</span>
                        {i.mode === 'Virtual'
                          ? <><Video size={11} /> Virtual</>
                          : <><MapPin size={11} /> {i.location}</>}
                        <span>·</span>
                        <span>{i.interviewer_name}</span>
                      </p>
                    </div>

                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className={`px-2 py-0.5 rounded-md text-[10.5px] font-bold ${
                        STATUS_TONE[i.status] || STATUS_TONE.Scheduled}`}>
                        {i.status}
                      </span>
                      {i.outcome && (
                        <span className={`px-2 py-0.5 rounded-md text-[10.5px] font-bold ${
                          OUTCOME_TONE[i.outcome]}`}>
                          {i.outcome}
                        </span>
                      )}
                      {typeof i.average_score === 'number' && (
                        <span className="px-1.5 py-0.5 rounded bg-[var(--input-bg)] text-[10.5px] font-bold text-[var(--text-main)] flex items-center gap-0.5">
                          <Star size={10} fill="currentColor" /> {i.average_score}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-1.5">
                      {i.mode === 'Virtual' && i.meeting_link && i.status === 'Scheduled' && (
                        <a href={i.meeting_link} target="_blank" rel="noopener noreferrer"
                          className="h-8 px-3 rounded-lg bg-[var(--accent-indigo)] text-white text-[11.5px] font-bold">
                          Join
                        </a>
                      )}
                      <button type="button" onClick={() => downloadRecording(i)}
                        title={i.recording
                          ? (i.recording.is_external ? 'Open the interview recording' : 'Download the interview recording')
                          : 'No recording yet' + (canAttachRecording ? ' — click to attach one' : '')}
                        className={`h-8 w-8 grid place-items-center rounded-lg border ${
                          i.recording
                            ? 'border-[var(--accent-indigo)] text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]'
                            : 'border-[var(--border)] text-[var(--text-muted)] opacity-60 hover:opacity-100'}`}>
                        <Download size={13} />
                      </button>
                      {canAttachRecording && (
                        <button type="button" onClick={() => setRecordingFor(i)}
                          title={i.recording ? 'Replace or remove the recording' : 'Attach the recording'}
                          className="h-8 w-8 grid place-items-center rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
                          <Paperclip size={13} />
                        </button>
                      )}
                      <button type="button" onClick={() => downloadInvite(i.interview_no)}
                        title="Add to calendar — downloads the invite for Outlook / Google Calendar"
                        className="h-8 w-8 grid place-items-center rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
                        <CalendarPlus size={13} />
                      </button>
                      {i.can_evaluate && !i.outcome && i.status !== 'Cancelled' && (
                        <button type="button" onClick={() => setEvaluating(i)}
                          className="h-8 px-3 rounded-lg border border-[var(--accent-indigo)] text-[var(--accent-indigo)] text-[11.5px] font-bold">
                          Evaluate
                        </button>
                      )}
                      {canSchedule && i.status === 'Scheduled' && (
                        <>
                          <button type="button" onClick={() => setStatusFor(i, 'No Show')}
                            title="Mark no show"
                            className="h-8 px-2.5 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)]">
                            <Clock size={12} />
                          </button>
                          <button type="button" onClick={() => cancel(i)} title="Cancel"
                            className="h-8 w-8 grid place-items-center rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-red)]">
                            <Ban size={13} />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {showSchedule && (
        <ScheduleModal onClose={() => setShowSchedule(false)}
          onScheduled={() => { setShowSchedule(false); load(); }} />
      )}
      {recordingFor && (
        <RecordingModal
          interview={(data.interviews || []).find((x) => x.interview_no === recordingFor.interview_no) || recordingFor}
          canAttach={canAttachRecording} onDownload={downloadRecording}
          onClose={() => setRecordingFor(null)}
          onChanged={() => { setRecordingFor(null); load(); }} />
      )}
      {evaluating && (
        <EvaluateModal interview={evaluating} onClose={() => setEvaluating(null)}
          onEvaluated={() => { setEvaluating(null); load(); }} />
      )}
    </div>
  );
};

export default InterviewBoard;
