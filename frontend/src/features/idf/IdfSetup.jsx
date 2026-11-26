import React, { useCallback, useEffect, useState } from 'react';
import { Settings2, Save, Plus, Trash2, AlertTriangle, RefreshCw, Info } from 'lucide-react';
import { DashboardHero, HeroButton } from '../tpms/common/dashboardKit';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { getIdfSetup, saveIdfSetup } from '../../services/idfApi';
import { CARD, FIELD, isStaffAdmin } from './idfKit';
import { CompanyPicker } from './IdfBits';

/* ─────────────────────────────────────────────────────────────
   Inter-Departmental Feedback ▸ Setup (HR / Admin / MD / Sparsh Admin) — the rules only:
   feedback parameters, default deadline, reminder timing and the comment rule.

   Department HODs come from Team (a member's Department + the HOD designation), and which
   department reviews which is chosen when a cycle is started (Feedback Cycles ▸ Start cycle).
   ───────────────────────────────────────────────────────────── */

const IdfSetup = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const staff = isStaffAdmin(user);
  const [companyId, setCompanyId] = useState('');
  const [setup, setSetup] = useState(null);
  const [params, setParams] = useState([]);
  const [deadlineDays, setDeadlineDays] = useState(7);
  const [beforeDays, setBeforeDays] = useState(2);
  const [needComment, setNeedComment] = useState([1, 2, 5]);
  const [meeting, setMeeting] = useState({ time: '11:00', duration: 60, days_after: 3, mode: 'online', link: '', venue: '' });
  const [labels, setLabels] = useState(['Poor', 'Below Average', 'Average', 'Good', 'Excellent']);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const cid = staff ? companyId : undefined;

  const apply = (s) => {
    setSetup(s);
    setParams(s.parameters || []);
    setDeadlineDays(s.deadline_days ?? 7);
    setBeforeDays(s.reminder_days_before ?? 2);
    setNeedComment(s.comment_required_for || [1, 2, 5]);
    setMeeting({ ...{ time: '11:00', duration: 60, days_after: 3, mode: 'online', link: '', venue: '' }, ...(s.meeting || {}) });
    setLabels(s.rating_labels?.length === 5 ? s.rating_labels : ['Poor', 'Below Average', 'Average', 'Good', 'Excellent']);
  };

  const load = useCallback(async () => {
    if (staff && !companyId) { setSetup(null); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getIdfSetup(staff ? companyId : undefined);
      apply(data);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load the setup.');
      setSetup(null);
    } finally {
      setLoading(false);
    }
  }, [staff, companyId]);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await saveIdfSetup({
        parameters: params, deadline_days: Number(deadlineDays),
        reminder_days_before: Number(beforeDays), comment_required_for: needComment, rating_labels: labels,
        meeting: { ...meeting, duration: Number(meeting.duration), days_after: Number(meeting.days_after) },
      }, cid);
      apply(data);
      showSuccess('Setup saved.');
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not save the setup.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <DashboardHero icon={Settings2} title="Feedback Setup" subtitle="Parameters, deadlines and reminders">
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
        {setup && <HeroButton icon={Save} onClick={save}>{saving ? 'Saving…' : 'Save setup'}</HeroButton>}
      </DashboardHero>

      {staff && <div className={`${CARD} p-4`}><CompanyPicker value={companyId} onChange={setCompanyId} /></div>}
      {loading && <p className="text-[12.5px] font-bold text-[var(--text-muted)]">Loading…</p>}
      {error && <p className="text-[12.5px] font-bold text-[var(--accent-red)]">{error}</p>}

      {setup && (
        <>
          <div className="flex items-start gap-2 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-4 py-3 text-[12.5px] text-[var(--text-muted)]">
            <Info size={15} className="mt-0.5 shrink-0 text-[var(--accent-indigo)]" />
            <span>
              <b className="text-[var(--text-main)]">HODs come from Team</b> — a member whose Department is set and whose Designation is HOD.
              {' '}<b className="text-[var(--text-main)]">Which department reviews which</b> is chosen each time you start a cycle (Feedback Cycles ▸ Start cycle).
              {setup.md_names?.length ? ` Reports go to: ${setup.md_names.join(', ')} (MD only).` : ''}
            </span>
          </div>
          {setup.md_count === 0 && (
            <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-4 py-3 text-[12.5px] font-semibold text-[var(--accent-orange)]">
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              No MD in this company (governance role MD). Feedback can be collected, but nobody can see the dashboard and no report can be emailed until an MD is set.
            </div>
          )}

          <div className={`${CARD} p-4 space-y-3`}>
            <div>
              <h3 className="text-[14px] font-black text-[var(--text-main)]">Feedback parameters</h3>
              <p className="text-[11.5px] text-[var(--text-muted)]">Rated 1 Poor – 5 Excellent, blank = not applicable. Every form also asks Strength and Improvement.</p>
            </div>
            {setup.has_cycles && (
              <div className="flex items-start gap-2 rounded-lg border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3 py-2 text-[11.5px] font-semibold text-[var(--accent-orange)]">
                <AlertTriangle size={13} className="mt-px shrink-0" />
                Keep the questions unchanged so trends stay comparable from cycle to cycle (Standard Approach). Change them only if you must.
              </div>
            )}
            {params.map((p, i) => (
              <div key={p.code || i} className="grid grid-cols-1 sm:grid-cols-[180px_1fr_auto] gap-2 items-start">
                <input className={FIELD} value={p.name} placeholder="Parameter"
                  onChange={(e) => setParams((ps) => ps.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                <input className={FIELD} value={p.question} placeholder="Question"
                  onChange={(e) => setParams((ps) => ps.map((x, j) => (j === i ? { ...x, question: e.target.value } : x)))} />
                <button type="button" disabled={params.length <= 1} aria-label="Remove parameter"
                  onClick={() => setParams((ps) => ps.filter((_, j) => j !== i))}
                  className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-red)] disabled:opacity-30"><Trash2 size={14} /></button>
              </div>
            ))}
            {params.length < 10 && (
              <button type="button" onClick={() => setParams((ps) => [...ps, { code: '', name: '', question: '' }])}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
                <Plus size={13} /> Add parameter
              </button>
            )}
          </div>

          <div className={`${CARD} p-4 space-y-3`}>
            <div>
              <h3 className="text-[14px] font-black text-[var(--text-main)]">Rating scale</h3>
              <p className="text-[11.5px] text-[var(--text-muted)]">The label HODs see for each rating. Scores stay (average ÷ 5) × 100; new cycles use these labels.</p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-5 gap-2.5">
              {labels.map((l, i) => (
                <label key={i} className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] pl-2.5">
                  <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[var(--accent-indigo)] text-[11px] font-black text-white">{i + 1}</span>
                  <input className="min-w-0 flex-1 bg-transparent py-2 pr-2.5 text-[12.5px] font-bold text-[var(--text-main)] outline-none"
                    value={l} maxLength={30} aria-label={`Label for rating ${i + 1}`}
                    onChange={(e) => setLabels((ls) => ls.map((x, j) => (j === i ? e.target.value : x)))} />
                </label>
              ))}
            </div>
          </div>

          <div className={`${CARD} p-4 space-y-3`}>
            <div>
              <h3 className="text-[14px] font-black text-[var(--text-main)]">Results meeting</h3>
              <p className="text-[11.5px] text-[var(--text-muted)]">
                When a cycle completes, the MD and all HODs get this meeting in their calendar and an invitation email.
                HR, the Client Admin or the MD can reschedule it later.
              </p>
            </div>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <label className="space-y-1">
                <span className="block text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Start time (IST)</span>
                <input type="time" className={`${FIELD} w-full`} value={meeting.time} onChange={(e) => setMeeting({ ...meeting, time: e.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="block text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Length (minutes)</span>
                <input type="number" min={15} max={240} step={15} className={`${FIELD} w-full`} value={meeting.duration} onChange={(e) => setMeeting({ ...meeting, duration: e.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="block text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Working days after results</span>
                <input type="number" min={1} max={15} className={`${FIELD} w-full`} value={meeting.days_after} onChange={(e) => setMeeting({ ...meeting, days_after: e.target.value })} />
              </label>
              <label className="space-y-1">
                <span className="block text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Type</span>
                <select className={`${FIELD} w-full`} value={meeting.mode} onChange={(e) => setMeeting({ ...meeting, mode: e.target.value })}>
                  <option value="online">Online</option><option value="in_person">In person</option><option value="both">Both</option>
                </select>
              </label>
              <label className="space-y-1 col-span-2">
                <span className="block text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Default meeting link</span>
                <input className={`${FIELD} w-full`} placeholder="https://meet.google.com/… or a Teams link" value={meeting.link}
                  onChange={(e) => setMeeting({ ...meeting, link: e.target.value })} />
              </label>
              <label className="space-y-1 col-span-2">
                <span className="block text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Default venue</span>
                <input className={`${FIELD} w-full`} placeholder="e.g. Conference room 1" value={meeting.venue}
                  onChange={(e) => setMeeting({ ...meeting, venue: e.target.value })} />
              </label>
            </div>
          </div>

          <div className={`${CARD} p-4 grid grid-cols-1 sm:grid-cols-3 gap-4`}>
            <label className="space-y-1">
              <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Default deadline (days after start)</span>
              <input type="number" min={1} max={60} className={`${FIELD} w-full`} value={deadlineDays} onChange={(e) => setDeadlineDays(e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Reminder (days before deadline)</span>
              <input type="number" min={0} max={30} className={`${FIELD} w-full`} value={beforeDays} onChange={(e) => setBeforeDays(e.target.value)} />
            </label>
            <div className="space-y-1">
              <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Comment required for ratings</span>
              <div className="flex gap-2">
                {[1, 2, 3, 4, 5].map((n) => (
                  <label key={n} className="inline-flex items-center gap-1 text-[12.5px] font-bold text-[var(--text-main)]">
                    <input type="checkbox" className="accent-[var(--accent-indigo)]" checked={needComment.includes(n)}
                      onChange={() => setNeedComment((s) => (s.includes(n) ? s.filter((x) => x !== n) : [...s, n].sort()))} />
                    {n}
                  </label>
                ))}
              </div>
            </div>
          </div>

          <div className="flex justify-end">
            <button type="button" onClick={save} disabled={saving}
              className="inline-flex items-center gap-1.5 px-5 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-black disabled:opacity-50">
              <Save size={14} /> {saving ? 'Saving…' : 'Save setup'}
            </button>
          </div>
        </>
      )}
    </div>
  );
};

export default IdfSetup;
