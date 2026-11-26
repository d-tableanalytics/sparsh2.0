import React, { useCallback, useEffect, useState } from 'react';
import { CalendarClock, RefreshCw, Play, X, Ban, Building2, Check, Plus, Trash2, Users, UserRound, AlertTriangle, PlusCircle, Lock, Repeat, CalendarRange, MessageSquareReply } from 'lucide-react';
import { DashboardHero, HeroButton } from '../tpms/common/dashboardKit';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { getIdfCycles, startIdfCycle, getIdfCycleStatus, cancelIdfCycle, getIdfCycleOptions, addToIdfCycle, getIdfDeletePreview, deleteIdfCycle } from '../../services/idfApi';
import { CARD, FIELD, TH, TD, day, dayTime, monthLabel, isStaffAdmin, canDelete } from './idfKit';
import { StatusChip, CompanyPicker } from './IdfBits';

/* ─────────────────────────────────────────────────────────────
   Inter-Departmental Feedback ▸ Cycles & Status (HR / Admin / MD).

   Client document §4: HR/Admin start a cycle — every rater gets a calendar activity and the
   initial notification; reminders follow automatically. §4E monitoring: totals, completed,
   pending, overdue and department-wise submission %. STATUS ONLY — no ratings or comments.
   ───────────────────────────────────────────────────────────── */

const thisMonth = () => new Date().toISOString().slice(0, 7);
const plusDays = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };

const Kpi = ({ label, value, tone }) => (
  <div className={`${CARD} px-4 py-3`}>
    <p className="text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)]">{label}</p>
    <p className="text-[22px] font-black tabular-nums" style={{ color: tone || 'var(--text-main)' }}>{value}</p>
  </div>
);

const IdfCycles = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const staff = isStaffAdmin(user);
  const [companyId, setCompanyId] = useState('');
  const cid = staff ? companyId : undefined;
  const [data, setData] = useState(null);
  const [status, setStatus] = useState(null);
  const [selected, setSelected] = useState(null);
  const [starting, setStarting] = useState(false);
  const [adding, setAdding] = useState(null);     // the cycle departments are being added to
  const [pulsing, setPulsing] = useState(false);  // starting a pulse re-score
  const [deleting, setDeleting] = useState(null); // the cycle being deleted
  const mayDelete = canDelete(user);

  const load = useCallback(async () => {
    if (staff && !companyId) return;      // a Sparsh Admin picks the company first
    try {
      const { data: d } = await getIdfCycles(cid);
      setData(d);
      const open = d.cycles.find((c) => c.status === 'Open') || d.cycles[0];
      setSelected((s) => s || open?.id || null);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not load the cycles.');
    }
  }, [staff, companyId, cid, showError]);
  // Fetch on open / company change; state is set only after the request returns.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!selected) return;
    getIdfCycleStatus(selected, cid).then(({ data: d }) => setStatus(d)).catch(() => setStatus(null));
  }, [selected, cid]);
  // Shown only for the cycle currently selected (a stale one is never displayed).
  const shownStatus = status && selected && status.cycle?.id === selected ? status : null;

  const started = (c) => {
    showSuccess(`Cycle started — ${c.pairs.length} department feedback forms; each HOD has a calendar activity and an email.`);
    setStarting(false);
    setSelected(c.id);
    load();
  };

  const added = (c) => {
    showSuccess(`${c.added} feedback form${c.added === 1 ? '' : 's'} added${c.reopened ? ' — the cycle is open again; the MD gets a new report when they are submitted' : ''}. Each new HOD has a calendar activity and an email.`);
    setAdding(null);
    setSelected(c.id);
    setStatus(null);
    load();
  };

  // Stable, so the delete dialog's preview request runs once.
  const closeDelete = useCallback(() => setDeleting(null), []);

  const cancel = async (id) => {
    if (!window.confirm('Cancel this feedback cycle? Pending calendar activities are removed; submitted feedback is kept.')) return;
    try {
      await cancelIdfCycle(id, cid);
      showSuccess('Cycle cancelled.');
      setSelected(null);
      load();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not cancel the cycle.');
    }
  };

  const cycles = data?.cycles || [];
  const hasOpen = cycles.some((c) => c.status === 'Open');

  return (
    <div className="space-y-5">
      <DashboardHero icon={CalendarClock} title="Feedback Cycles" subtitle="Start a cycle and follow submissions — status only">
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
        {data && !hasOpen && <HeroButton icon={Play} onClick={() => setStarting(true)}>Start cycle</HeroButton>}
      </DashboardHero>

      {staff && <div className={`${CARD} p-4`}><CompanyPicker value={companyId} onChange={setCompanyId} /></div>}

      {/* Standard Approach: the rhythm (monthly ×2, then quarterly) and the 30-day pulse re-score. */}
      {data && (data.cadence?.next_due_period || (data.pulse && !data.pulse.started)) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {data.cadence?.next_due_period && (
            <div className={`${CARD} flex items-start gap-3 px-4 py-3`}>
              <span className="rounded-lg p-2 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]"><CalendarRange size={16} /></span>
              <div className="min-w-0">
                <p className="text-[13px] font-black text-[var(--text-main)]">Next cycle due: {monthLabel(data.cadence.next_due_period)}</p>
                <p className="text-[11.5px] text-[var(--text-muted)]">{data.cadence.rule} HR gets a reminder when it is due.</p>
              </div>
            </div>
          )}
          {data.pulse && !data.pulse.started && (
            <div className={`${CARD} flex items-start gap-3 px-4 py-3`} style={{ borderColor: data.pulse.available ? 'var(--accent-red)' : undefined }}>
              <span className={`rounded-lg p-2 ${data.pulse.available ? 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]' : 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}><Repeat size={16} /></span>
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-black text-[var(--text-main)]">
                  {data.pulse.available ? `Pulse re-score due ${day(data.pulse.due_date)}` : `Pulse re-score on ${day(data.pulse.due_date)} (30 days after results)`}
                </p>
                <p className="text-[11.5px] text-[var(--text-muted)] truncate"
                  title={data.pulse.relationships.map((x) => `${x.from} → ${x.to} (${x.pct}%)`).join(', ')}>
                  {data.pulse.relationships.length} Red relationship{data.pulse.relationships.length === 1 ? '' : 's'} from {monthLabel(data.pulse.period)}:{' '}
                  {data.pulse.relationships.map((x) => `${x.from} → ${x.to}`).join(', ')} — same questions, affected departments only.
                </p>
              </div>
              {!hasOpen && (data.pulse.available ? (
                <button type="button" onClick={() => setPulsing(true)}
                  className="shrink-0 inline-flex items-center gap-1 rounded-lg bg-[var(--accent-red)] px-3 py-1.5 text-[11.5px] font-black text-white hover:opacity-90">
                  <Repeat size={12} /> Start pulse re-score
                </button>
              ) : (
                <span title="The pulse re-score opens 30 days after the results"
                  className="shrink-0 inline-flex items-center gap-1 rounded-lg border border-dashed border-[var(--border)] px-3 py-1.5 text-[11.5px] font-bold text-[var(--text-muted)]">
                  <Repeat size={12} /> Opens {day(data.pulse.due_date)}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* KPI cards first — the selected cycle's numbers at a glance. */}
      {shownStatus && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Kpi label="Activities scheduled" value={shownStatus.total} />
          <Kpi label="Submitted" value={shownStatus.completed} tone="var(--accent-green)" />
          <Kpi label="Pending" value={shownStatus.pending} tone="var(--accent-orange)" />
          <Kpi label="Overdue" value={shownStatus.overdue} tone="var(--accent-red)" />
        </div>
      )}

      {data && (
        <div className={`${CARD} overflow-x-auto`}>
          <table className="w-full">
            <thead><tr className="border-b border-[var(--border)]">
              <th className={TH}>Cycle</th><th className={TH}>Start</th><th className={TH}>Deadline</th>
              <th className={TH}>Status</th><th className={TH}>Report to MD</th><th className={`${TH} text-right pr-4`}>Actions</th>
            </tr></thead>
            <tbody>
              {cycles.map((c) => (
                <tr key={c.id} onClick={() => setSelected(c.id)}
                  className={`border-b border-[var(--border)] last:border-0 cursor-pointer hover:bg-[var(--input-bg)] ${selected === c.id ? 'bg-[var(--accent-indigo-bg)]' : ''}`}>
                  <td className={TD}><b>{monthLabel(c.period)}</b>{c.source === 'import' ? <span className="text-[var(--text-muted)]"> · imported</span> : null}
                    {c.cycle_type === 'pulse' && <span className="ml-1.5 rounded px-1.5 py-px text-[10px] font-black uppercase tracking-wide text-[var(--accent-red)] bg-[var(--accent-red-bg)]">Pulse re-score</span>}</td>
                  <td className={TD}>{day(c.start_date)}</td>
                  <td className={TD}>{day(c.deadline)}</td>
                  <td className={TD}><StatusChip status={c.status} /></td>
                  <td className={TD}>{c.report_sent_at ? `Sent ${day(c.report_sent_at)}` : '—'}</td>
                  <td className={`${TD} whitespace-nowrap pr-4`}>
                    {/* Fixed slots, right-aligned: the buttons line up on every row. */}
                    <div className="flex items-center justify-end gap-1.5">
                      {c.source !== 'import' && (c.status === 'Open' || (c.status === 'Completed' && !hasOpen)) && (
                        <button type="button" onClick={(e) => { e.stopPropagation(); setAdding(c); }}
                          title={c.status === 'Completed' ? 'Add more department feedback — reopens this cycle' : 'Add more department feedback to this cycle'}
                          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-2.5 text-[11.5px] font-bold text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
                          <PlusCircle size={13} /> Add departments
                        </button>
                      )}
                      {c.status === 'Open' ? (
                        <button type="button" onClick={(e) => { e.stopPropagation(); cancel(c.id); }} title="Cancel cycle" aria-label="Cancel cycle"
                          className="grid h-8 w-8 place-items-center rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[var(--accent-orange)] hover:border-[var(--accent-orange)] hover:bg-[var(--accent-yellow-bg)]">
                          <Ban size={14} />
                        </button>
                      ) : mayDelete && <span className="h-8 w-8" aria-hidden="true" />}
                      {mayDelete && (
                        <button type="button" onClick={(e) => { e.stopPropagation(); setDeleting(c); }} title="Delete permanently" aria-label="Delete cycle"
                          className="grid h-8 w-8 place-items-center rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[var(--text-muted)] hover:border-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] hover:text-[var(--accent-red)]">
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {!cycles.length && <tr><td className={`${TD} text-center text-[var(--text-muted)]`} colSpan={6}>No cycles yet — start the first one.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {shownStatus && (
        <>
          <div className={`${CARD} px-4 py-3 space-y-2`}>
            <p className="text-[12px] font-black text-[var(--text-main)]">Department-wise submission</p>
            <div className="flex flex-wrap gap-2">
              {shownStatus.departments.map((d) => (
                <span key={d.department} className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11.5px]">
                  <b className="text-[var(--text-main)]">{d.department}</b>
                  <span className="text-[var(--text-muted)]">{d.completed}/{d.total}</span>
                  <span className="font-black tabular-nums" style={{ color: d.percent === 100 ? 'var(--accent-green)' : d.percent ? 'var(--accent-orange)' : 'var(--accent-red)' }}>{d.percent}%</span>
                </span>
              ))}
            </div>
          </div>
          {!!shownStatus.responses?.total && (
            <div className={`${CARD} flex flex-wrap items-center gap-3 px-4 py-3`}>
              <span className="rounded-lg p-2 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]"><MessageSquareReply size={16} /></span>
              <div className="flex-1 min-w-[200px]">
                <p className="text-[13px] font-black text-[var(--text-main)]">
                  You said, we did: {shownStatus.responses.submitted} of {shownStatus.responses.total} departments have answered their raters
                </p>
                <p className="text-[11.5px] text-[var(--text-muted)]">
                  {shownStatus.responses.pending.length ? `Waiting for: ${shownStatus.responses.pending.join(', ')}` : 'Every department has closed the loop.'}
                  {shownStatus.responses.overdue ? ` · ${shownStatus.responses.overdue} overdue (reminded every 3 days)` : ''}
                </p>
              </div>
            </div>
          )}
          <div>
            <div className={`${CARD} overflow-x-auto`}>
              <table className="w-full">
                <thead><tr className="border-b border-[var(--border)]">
                  <th className={TH}>Rater department</th><th className={TH}>Rates</th><th className={TH}>Rater (HOD)</th>
                  <th className={TH}>Status</th><th className={TH}>Emailed link</th><th className={TH}>Submitted</th>
                </tr></thead>
                <tbody>
                  {shownStatus.activities.map((a, i) => (
                    <tr key={i} className="border-b border-[var(--border)] last:border-0">
                      <td className={TD}>{a.giver_name}</td><td className={TD}>{a.receiver_name}</td>
                      <td className={TD}>{a.rater_name || '—'}</td><td className={TD}><StatusChip status={a.status} /></td>
                      <td className={TD}>{a.link_status || '—'}</td>
                      <td className={`${TD} whitespace-nowrap`}>{dayTime(a.submitted_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <p className="text-[11.5px] text-[var(--text-muted)]">
            Reminders go out automatically (before the deadline, then daily while overdue). Scores and comments are visible to the MD only.
          </p>
        </>
      )}

      {starting && <StartCycleDialog cid={cid} onClose={() => setStarting(false)} onStarted={started} showError={showError} />}
      {adding && <StartCycleDialog cid={cid} cycle={adding} onClose={() => setAdding(null)} onStarted={added} showError={showError} />}
      {deleting && <DeleteCycleDialog cycle={deleting} cid={cid} showError={showError} onClose={closeDelete}
        onDeleted={(c) => { setDeleting(null); setSelected(null); setStatus(null); showSuccess(`${monthLabel(c.period)} deleted.`); load(); }} />}
      {pulsing && data?.pulse && <StartCycleDialog cid={cid} pulse={data.pulse} onClose={() => setPulsing(false)}
        onStarted={(c) => { setPulsing(false); started(c); }} showError={showError} />}
    </div>
  );
};

/* Start a cycle: the month, the deadline, and the review mapping — for each department under
   review, which departments give feedback about it. Pre-filled with the last cycle's mapping;
   each department shows its HOD(s) from Team, and one without an HOD is flagged. */
const keyOf = (g, r) => `${g}|${r}`;

// The forms a cycle already has, grouped as review blocks: [{ receiver, givers: Set }].
const reviewsOfCycle = (cycle) => {
  const by = new Map();
  (cycle?.pairs || []).forEach((p) => {
    if (!by.has(p.receiver_dept_id)) by.set(p.receiver_dept_id, new Set());
    by.get(p.receiver_dept_id).add(p.giver_dept_id);
  });
  return [...by.entries()].map(([receiver, givers]) => ({ receiver, givers }));
};

/* `cycle` given = ADD mode: the cycle's existing forms are shown ticked and locked; only the
   new ticks are added (a completed cycle reopens). */
const StartCycleDialog = ({ cid, cycle, pulse, onClose, onStarted, showError }) => {
  const addMode = !!cycle;
  const pulseMode = !addMode && !!pulse;
  const locked = new Set((cycle?.pairs || []).map((p) => keyOf(p.giver_dept_id, p.receiver_dept_id)));
  const isLocked = (g, r) => locked.has(keyOf(g, r));
  const [opts, setOpts] = useState(null);
  const [period, setPeriod] = useState(thisMonth());
  const [deadline, setDeadline] = useState(plusDays(7));
  const [reviews, setReviews] = useState([]);   // [{ receiver, givers: Set }]
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getIdfCycleOptions(cid).then(({ data }) => {
      setOpts(data);
      const fresh = plusDays(data.deadline_days || 7);
      if (cycle) {
        // Keep the cycle's deadline unless it has passed.
        setDeadline(cycle.deadline && cycle.deadline >= plusDays(0) ? cycle.deadline : fresh);
        setReviews(reviewsOfCycle(cycle));
      } else {
        setDeadline(fresh);
        // A pulse re-score: only the Red relationships, same questions.
        const base = pulse ? pulse.reviews : (data.last_reviews || []);
        setReviews(base.map((r) => ({ receiver: r.receiver_dept_id, givers: new Set(r.giver_dept_ids) })));
      }
    }).catch((e) => showError(e?.response?.data?.detail || 'Could not load the departments.'));
  }, [cid, cycle, pulse, showError]);

  const depts = opts?.departments || [];
  const byId = Object.fromEntries(depts.map((d) => [d.id, d]));
  const reviewed = new Set(reviews.map((r) => r.receiver));
  const addReview = (id) => setReviews((rs) => [...rs, { receiver: id, givers: new Set() }]);
  const setGivers = (i, fn) => setReviews((rs) => rs.map((r, j) => (j === i ? { ...r, givers: fn(new Set(r.givers)) } : r)));
  // Only NEW forms count (in add mode the cycle's existing ones are already scheduled).
  const newGivers = (r) => [...r.givers].filter((g) => !isLocked(g, r.receiver));
  const total = reviews.reduce((n, r) => n + newGivers(r).length, 0);
  const missingHod = [...new Set(reviews.flatMap(newGivers).filter((g) => !byId[g]?.heads?.length))].map((g) => byId[g]?.name);
  const lockedOf = (r) => new Set([...r.givers].filter((g) => isLocked(g, r.receiver)));

  const start = async () => {
    setBusy(true);
    try {
      const body = {
        deadline,
        reviews: reviews.filter((r) => r.givers.size).map((r) => ({ receiver_dept_id: r.receiver, giver_dept_ids: [...r.givers] })),
      };
      const { data: c } = addMode ? await addToIdfCycle(cycle.id, body, cid)
        : await startIdfCycle({ ...body, period, ...(pulseMode ? { cycle_type: 'pulse', pulse_of: pulse.cycle_id } : {}) }, cid);
      onStarted(c);
    } catch (e) {
      showError(e?.response?.data?.detail || (addMode ? 'Could not add the departments.' : 'Could not start the cycle.'));
    } finally {
      setBusy(false);
    }
  };

  const addAll = () => setReviews(depts.map((d) => ({ receiver: d.id, givers: new Set(depts.filter((g) => g.id !== d.id).map((g) => g.id)) })));
  const clearAll = () => setReviews(addMode ? reviewsOfCycle(cycle) : []);
  const remaining = depts.filter((d) => !reviewed.has(d.id));

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={() => !busy && onClose()}>
      <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" className="w-full max-w-3xl rounded-2xl bg-[var(--bg-card)] shadow-2xl overflow-hidden flex flex-col max-h-[92vh]">
        <div className="flex items-start gap-3 px-5 py-4 border-b border-[var(--border)]">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]"><CalendarClock size={18} /></span>
          <div className="flex-1">
            <h3 className="text-[15px] font-black text-[var(--text-main)]">
              {addMode ? `Add department feedback — ${monthLabel(cycle.period)}` : pulseMode ? 'Start a pulse re-score' : 'Start a feedback cycle'}
            </h3>
            <p className="text-[11.5px] text-[var(--text-muted)]">
              {addMode
                ? (cycle.status === 'Completed'
                  ? 'This cycle is completed. Adding forms reopens it; the MD gets a new report once they are submitted.'
                  : 'Forms already in this cycle stay as they are — tick the new departments to add.')
                : pulseMode
                  ? `Re-scores the ${monthLabel(pulse.period)} relationships below 60% — only the affected departments, with the same questions.`
                  : 'Choose the month, then decide which departments give feedback about which.'}
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]"><X size={17} /></button>
        </div>

        <div className="px-5 py-4 space-y-5 overflow-y-auto">
          <section className="space-y-2.5">
            <StepTitle n={1} title="Cycle details" />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="space-y-1">
                <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Cycle month</span>
                {addMode
                  ? <p className={`${FIELD} w-full font-bold`}>{monthLabel(cycle.period)}</p>
                  : <input type="month" className={`${FIELD} w-full`} value={period} onChange={(e) => setPeriod(e.target.value)} />}
              </label>
              <label className="space-y-1">
                <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Submission deadline</span>
                <input type="date" className={`${FIELD} w-full`} value={deadline} onChange={(e) => setDeadline(e.target.value)} />
              </label>
            </div>
          </section>

          <section className="space-y-3">
            <div className="flex flex-wrap items-end gap-2">
              <div className="flex-1 min-w-[220px]">
                <StepTitle n={2} title="Departments to review" />
                <p className="mt-1 text-[11.5px] text-[var(--text-muted)]">For each department under review, pick the departments that rate it. Their HOD (from Team) fills the form.</p>
              </div>
              {opts && depts.length > 1 && (
                <div className="flex gap-2">
                  <button type="button" onClick={addAll}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[11.5px] font-bold text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
                    <Users size={13} /> Everyone rates everyone
                  </button>
                  {!!reviews.length && (
                    <button type="button" onClick={clearAll}
                      className="rounded-lg px-3 py-1.5 text-[11.5px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)]">Clear all</button>
                  )}
                </div>
              )}
            </div>

            {!opts && <p className="rounded-xl border border-dashed border-[var(--border)] p-6 text-center text-[12.5px] text-[var(--text-muted)]">Loading departments…</p>}

            {opts && !depts.length && (
              <p className="rounded-xl border border-dashed border-[var(--border)] p-6 text-center text-[12.5px] text-[var(--text-muted)]">
                No departments yet — add them with “+ Add Department” in Team › Add Member.
              </p>
            )}

            {opts && !!depts.length && !reviews.length && (
              <div className="rounded-xl border border-dashed border-[var(--border)] bg-[var(--input-bg)] px-4 py-6 text-center">
                <Building2 size={22} className="mx-auto text-[var(--text-muted)]" />
                <p className="mt-2 text-[13px] font-black text-[var(--text-main)]">No department under review yet</p>
                <p className="text-[11.5px] text-[var(--text-muted)]">Pick a department below, or use “Everyone rates everyone” for the full matrix.</p>
              </div>
            )}

            {reviews.map((r, i) => {
              const recv = byId[r.receiver];
              const others = depts.filter((d) => d.id !== r.receiver);
              return (
                <div key={r.receiver} className="rounded-xl border border-[var(--border)] overflow-hidden">
                  <div className="flex flex-wrap items-center gap-2 bg-[var(--input-bg)] px-3.5 py-2.5">
                    <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--accent-indigo)] text-[12px] font-black text-white">
                      {(recv?.name || '?').charAt(0).toUpperCase()}
                    </span>
                    <div className="flex-1 min-w-[140px]">
                      <p className="text-[13px] font-black text-[var(--text-main)]">Feedback for {recv?.name || '—'}</p>
                      <p className="text-[11px] text-[var(--text-muted)]">
                        {r.givers.size} of {others.length} departments rate it
                        {addMode && !!newGivers(r).length && <b className="text-[var(--accent-indigo)]"> · {newGivers(r).length} new</b>}
                      </p>
                    </div>
                    <button type="button" className="rounded-md px-2 py-1 text-[11.5px] font-bold text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]"
                      onClick={() => setGivers(i, () => new Set(others.map((d) => d.id)))}>Select all</button>
                    <button type="button" className="rounded-md px-2 py-1 text-[11.5px] font-bold text-[var(--text-muted)] hover:bg-[var(--bg-card)]"
                      onClick={() => setGivers(i, () => lockedOf(r))}>Clear</button>
                    {!lockedOf(r).size && (
                      <button type="button" aria-label={`Stop reviewing ${recv?.name || ''}`} title="Remove"
                        className="rounded-md p-1 text-[var(--text-muted)] hover:bg-[var(--accent-red-bg)] hover:text-[var(--accent-red)]"
                        onClick={() => setReviews((rs) => rs.filter((_, j) => j !== i))}><Trash2 size={14} /></button>
                    )}
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 p-3">
                    {others.map((d) => {
                      const on = r.givers.has(d.id);
                      const fixed = isLocked(d.id, r.receiver);
                      const noHod = !d.heads.length && !fixed;
                      return (
                        <button type="button" key={d.id} aria-pressed={on} disabled={fixed}
                          title={fixed ? 'Already in this cycle' : undefined}
                          onClick={() => setGivers(i, (s) => { if (on) s.delete(d.id); else s.add(d.id); return s; })}
                          className={`flex items-start gap-2.5 rounded-lg border px-3 py-2 text-left transition-colors ${
                            fixed ? 'border-[var(--border)] bg-[var(--input-bg)] cursor-not-allowed opacity-75'
                              : on ? (noHod ? 'border-[var(--accent-red)] bg-[var(--accent-red-bg)]' : 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]')
                                : 'border-[var(--border)] hover:border-[var(--accent-indigo)]'}`}>
                          <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                            on ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo)] text-white' : 'border-[var(--border)]'}`}>
                            {on && <Check size={11} strokeWidth={3} />}
                          </span>
                          <span className="min-w-0">
                            <span className="flex items-center gap-1.5 text-[12.5px] font-bold text-[var(--text-main)]">
                              {d.name}
                              {fixed && <span className="inline-flex items-center gap-0.5 rounded px-1.5 py-px text-[9.5px] font-black uppercase tracking-wide text-[var(--text-muted)] bg-[var(--bg-card)] border border-[var(--border)]"><Lock size={9} /> In cycle</span>}
                            </span>
                            <span className={`flex items-center gap-1 text-[11px] ${noHod ? 'font-semibold text-[var(--accent-red)]' : 'text-[var(--text-muted)]'}`}>
                              {noHod ? <AlertTriangle size={11} /> : <UserRound size={11} />}
                              <span className="truncate">{noHod ? 'No HOD in Team' : d.heads.map((h) => h.name).join(', ')}</span>
                            </span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}

            {opts && !!remaining.length && (
              <div className="space-y-1.5">
                <p className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">
                  {reviews.length ? 'Add another department to review' : 'Add a department to review'}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {remaining.map((d) => (
                    <button type="button" key={d.id} onClick={() => addReview(d.id)}
                      className="inline-flex items-center gap-1 rounded-full border border-dashed border-[var(--border)] px-3 py-1 text-[12px] font-bold text-[var(--text-main)] hover:border-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] hover:text-[var(--accent-indigo)]">
                      <Plus size={12} /> {d.name}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </section>

          {!!missingHod.length && (
            <div className="flex items-start gap-2 rounded-lg bg-[var(--accent-red-bg)] px-3 py-2.5 text-[12px] font-semibold text-[var(--accent-red)]">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>No HOD in Team for: {missingHod.join(', ')}. In Team, give the HOD that Department and the HOD designation — or untick these departments.</span>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3.5 border-t border-[var(--border)] bg-[var(--input-bg)]">
          <span className="text-[11.5px] text-[var(--text-muted)]">
            <b className="text-[var(--text-main)]">{reviews.length}</b> department{reviews.length === 1 ? '' : 's'} under review ·{' '}
            <b className="text-[var(--text-main)]">{total}</b> {addMode ? 'new ' : ''}feedback form{total === 1 ? '' : 's'} · each {addMode ? 'new ' : ''}HOD gets a calendar activity and an email
          </span>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] hover:bg-[var(--bg-card)]">Cancel</button>
            <button type="button" onClick={start} disabled={busy || !total || missingHod.length > 0}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-black disabled:opacity-50">
              {addMode
                ? <><PlusCircle size={13} /> {busy ? 'Adding…' : `Add ${total || ''} form${total === 1 ? '' : 's'}`}</>
                : <><Play size={13} /> {busy ? 'Starting…' : 'Start cycle'}</>}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

/* Permanent delete of a cycle (MD, Client Admin, Super Admin): shows what goes, typing DELETE confirms. */
const DeleteCycleDialog = ({ cycle, cid, onClose, onDeleted, showError }) => {
  const [pv, setPv] = useState(null);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    getIdfDeletePreview(cycle.id, cid).then(({ data }) => setPv(data))
      .catch((e) => { showError(e?.response?.data?.detail || 'Could not prepare the delete.'); onClose(); });
  }, [cycle.id, cid, showError, onClose]);

  const go = async () => {
    setBusy(true);
    try {
      await deleteIdfCycle(cycle.id, cid);
      onDeleted(cycle);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not delete the cycle.');
      setBusy(false);
    }
  };

  const rows = pv ? [
    ['Feedback forms', pv.forms], ['Submitted feedback', pv.submissions], ['Calendar activities', pv.calendar_activities],
    ['Personal form links', pv.links], ['Action plan items', pv.actions], ['"You said, we did" entries', pv.responses],
    ['Pulse re-scores', pv.pulse_rescores],
  ].filter(([, n]) => n) : [];

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={() => !busy && onClose()}>
      <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" className="w-full max-w-md rounded-2xl bg-[var(--bg-card)] shadow-2xl overflow-hidden">
        <div className="flex items-start gap-3 px-5 py-4 border-b border-[var(--border)]">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-red-bg)] text-[var(--accent-red)]"><Trash2 size={17} /></span>
          <div className="flex-1 min-w-0">
            <h3 className="text-[15px] font-black text-[var(--text-main)]">Delete {monthLabel(cycle.period)}{cycle.cycle_type === 'pulse' ? ' pulse re-score' : ' cycle'}?</h3>
            <p className="text-[11.5px] text-[var(--text-muted)]">This is permanent and cannot be undone. The deletion is recorded in the audit trail.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]"><X size={17} /></button>
        </div>
        <div className="px-5 py-4 space-y-3">
          {!pv ? <p className="text-[12.5px] text-[var(--text-muted)]">Checking what belongs to this cycle…</p> : (
            <>
              <div className="rounded-xl border border-[var(--border)] divide-y divide-[var(--border)]">
                {rows.length ? rows.map(([label, n]) => (
                  <div key={label} className="flex items-center justify-between px-3 py-1.5 text-[12.5px]">
                    <span className="text-[var(--text-main)]">{label}</span><b className="tabular-nums text-[var(--accent-red)]">{n}</b>
                  </div>
                )) : <p className="px-3 py-2 text-[12.5px] text-[var(--text-muted)]">Nothing else is attached to this cycle.</p>}
              </div>
              {pv.report_sent && (
                <p className="flex items-start gap-1.5 text-[11.5px] font-semibold text-[var(--accent-orange)]">
                  <AlertTriangle size={13} className="mt-px shrink-0" /> The report was already emailed to the MD — that email is not recalled.
                </p>
              )}
              <label className="block space-y-1.5">
                <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Type DELETE to confirm</span>
                <input className={`${FIELD} w-full font-bold tracking-wider`} value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="DELETE" autoFocus />
              </label>
            </>
          )}
        </div>
        <div className="flex justify-end gap-2 px-5 py-3.5 border-t border-[var(--border)] bg-[var(--input-bg)]">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] hover:bg-[var(--bg-card)]">Keep it</button>
          <button type="button" onClick={go} disabled={!pv || busy || typed.trim().toUpperCase() !== 'DELETE'}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-red)] text-white text-[12.5px] font-black disabled:opacity-50">
            <Trash2 size={13} /> {busy ? 'Deleting…' : 'Delete permanently'}
          </button>
        </div>
      </div>
    </div>
  );
};

const StepTitle = ({ n, title }) => (
  <p className="flex items-center gap-2 text-[13px] font-black text-[var(--text-main)]">
    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--accent-indigo)] text-[10.5px] text-white">{n}</span>
    {title}
  </p>
);

export default IdfCycles;
