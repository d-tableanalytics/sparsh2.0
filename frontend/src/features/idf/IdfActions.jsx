import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ListChecks, RefreshCw, X, CircleDot, Loader, AlertTriangle, CheckCircle2, CalendarClock, UserRound, ArrowRight, Search, BellRing, Trash2 } from 'lucide-react';
import { DashboardHero, HeroButton } from '../tpms/common/dashboardKit';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { getIdfActions, updateIdfAction, deleteIdfAction } from '../../services/idfApi';
import { BAND_STYLE, CARD, FIELD, day, monthLabel, isStaffAdmin, canDelete } from './idfKit';
import { BandChip, StatusChip, CompanyPicker } from './IdfBits';

/* ─────────────────────────────────────────────────────────────
   Inter-Departmental Feedback ▸ Action Plans (client document §7–§8).

   Generated automatically from the scores: Red (below 60%, and every relationship below 60%)
   → repair; Amber → strengthen; Green → sustain. The MD sees and reshapes all of them, the TPS
   Coordinator (Sparsh Admin) monitors them, an action owner updates their own.
   ───────────────────────────────────────────────────────────── */

const LABEL = 'text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]';
// Amber step 3 (Standard Approach): agree one process fix.
const PROCESS_FIXES = ['Hand-off checklist', 'Standard request format', 'ERP alert', 'Fixed reply time', 'Other'];

const TILES = [
  { key: 'Open', label: 'Open', icon: CircleDot, c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)' },
  { key: 'In Progress', label: 'In progress', icon: Loader, c: 'var(--accent-orange)', bg: 'var(--accent-yellow-bg)' },
  { key: 'overdue', label: 'Overdue', icon: AlertTriangle, c: 'var(--accent-red)', bg: 'var(--accent-red-bg)' },
  { key: 'review_due', label: 'Review due', icon: BellRing, c: 'var(--accent-orange)', bg: 'var(--accent-yellow-bg)' },
  { key: 'Closed', label: 'Closed', icon: CheckCircle2, c: 'var(--accent-green)', bg: 'var(--accent-green-bg)' },
];

const initials = (n) => String(n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');

const ActionCard = ({ a, onOpen }) => {
  const band = BAND_STYLE[a.band];
  return (
    <button type="button" onClick={() => onOpen(a)}
      className={`${CARD} group relative w-full overflow-hidden text-left transition-shadow hover:shadow-md`}>
      <span className="absolute inset-y-0 left-0 w-1" style={{ background: band?.c || 'var(--border)' }} />
      <div className="pl-5 pr-4 py-3.5 space-y-2.5">
        <div className="flex flex-wrap items-start gap-x-3 gap-y-1.5">
          <div className="flex-1 min-w-[180px]">
            <p className="text-[14px] font-black text-[var(--text-main)] leading-tight">{a.department}</p>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-[11.5px] text-[var(--text-muted)]">
              <span className="font-bold">{a.type}</span>
              {a.feedback_from && <><span>·</span><span className="inline-flex items-center gap-1">from {a.feedback_from} <ArrowRight size={10} /> {a.department}</span></>}
              {a.parameter && <><span>·</span><span>{a.parameter}</span></>}
              <span>·</span><span>{monthLabel(a.period)}</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            {a.current_score != null && (
              <span className="text-[16px] font-black tabular-nums" style={{ color: band?.c || 'var(--text-main)' }}>{a.current_score}%</span>
            )}
            <BandChip band={a.band} />
          </div>
        </div>

        {a.stage && (
          <p className="text-[11px] font-bold" style={{ color: band?.c || 'var(--text-muted)' }}>
            {a.category || a.band} · Team stage: {a.stage}{a.led_by ? ` · Led by ${a.led_by}` : ''}{a.response_time ? ` · ${a.response_time}` : ''}
          </p>
        )}
        <p className="text-[12.5px] leading-relaxed text-[var(--text-main)] line-clamp-2">{a.improvement_action}</p>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-dashed border-[var(--border)] pt-2.5 text-[11.5px]">
          <span className="inline-flex items-center gap-1.5 text-[var(--text-main)] font-bold">
            <span className="grid h-6 w-6 place-items-center rounded-full bg-[var(--accent-indigo-bg)] text-[9.5px] font-black text-[var(--accent-indigo)]">{initials(a.owner_name)}</span>
            {a.owner_name || 'No owner'}
          </span>
          <span className="inline-flex items-center gap-1 font-semibold" style={{ color: a.overdue ? 'var(--accent-red)' : 'var(--text-muted)' }}>
            <CalendarClock size={12} /> Target {day(a.target_date)}{a.overdue ? ' · overdue' : ''}
          </span>
          {a.status === 'Closed'
            ? <span className="text-[var(--accent-green)] font-semibold">Closed {day(a.closed_at)}{a.closed_by ? ` by ${a.closed_by}` : ''}</span>
            : a.review_date && (
              <span className="inline-flex items-center gap-1 font-semibold" style={{ color: a.review_due ? 'var(--accent-orange)' : 'var(--text-muted)' }}>
                {a.review_due && <BellRing size={11} />}{a.review_due ? 'Review due' : 'Next review'} {day(a.review_date)}
              </span>
            )}
          {a.rescore_pct != null
            ? <span className="font-bold" style={{ color: BAND_STYLE[a.rescore_band]?.c }}>Pulse re-score {a.rescore_pct}% ({a.rescore_band})</span>
            : a.rescore_date && a.status !== 'Closed' && <span className="text-[var(--text-muted)]">Re-score {day(a.rescore_date)}</span>}
          {a.process_fix && <span className="text-[var(--text-muted)]">Fix: <b className="text-[var(--text-main)]">{a.process_fix}</b></span>}
          <span className="ml-auto"><StatusChip status={a.status} /></span>
        </div>
      </div>
    </button>
  );
};

const IdfActions = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const staff = isStaffAdmin(user);
  const [companyId, setCompanyId] = useState('');
  const cid = staff ? companyId : undefined;
  const [data, setData] = useState(null);
  const [tile, setTile] = useState('');
  const [band, setBand] = useState('');
  const [period, setPeriod] = useState('');
  const [dueMonth, setDueMonth] = useState('');   // YYYY-MM: actions whose target date falls in that month
  const [q, setQ] = useState('');
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (staff && !companyId) return;
    try {
      const { data: d } = await getIdfActions(cid ? { company_id: cid } : {});
      setData(d);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not load the action plans.');
    }
  }, [staff, companyId, cid, showError]);
  // Fetch on open / company change; state is set only after the request returns.
  useEffect(() => { load(); }, [load]);

  const all = useMemo(() => data?.actions || [], [data]);
  const periods = useMemo(() => [...new Set(all.map((a) => a.period))].sort().reverse(), [all]);
  const inPeriod = all.filter((a) => (!period || a.period === period)
    && (!dueMonth || String(a.target_date || '').startsWith(dueMonth)));
  const matches = (a, k) => (k === 'overdue' || k === 'review_due' ? a[k] : a.status === k);
  const count = (k) => inPeriod.filter((a) => matches(a, k)).length;
  const actions = inPeriod.filter((a) =>
    (!tile || matches(a, tile))
    && (!band || a.band === band)
    && (!q || `${a.department} ${a.feedback_from || ''} ${a.owner_name || ''} ${a.improvement_action}`.toLowerCase().includes(q.toLowerCase())));
  const order = { Red: 0, Amber: 1, Green: 2 };
  actions.sort((x, y) => (x.status === 'Closed') - (y.status === 'Closed') || (order[x.band] ?? 9) - (order[y.band] ?? 9)
    || String(x.target_date || '').localeCompare(String(y.target_date || '')));

  const isMd = data?.role === 'md';
  const isOwner = data?.role === 'owner';
  const mayDelete = canDelete(user);   // MD, Client Admin, Super Admin
  const remove = async () => {
    if (!window.confirm(`Delete this action for ${editing.department} (${editing.type})? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await deleteIdfAction(editing.id, cid);
      showSuccess('Action deleted.');
      setEditing(null);
      load();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not delete the action.');
    } finally {
      setBusy(false);
    }
  };
  const open = (a) => {
    setEditing(a);
    setForm({ status: a.status, remark: '', improvement_action: a.improvement_action, target_date: a.target_date,
      review_date: a.review_date, owner_user_id: a.owner_user_id || '', process_fix: a.process_fix || '' });
  };
  const save = async () => {
    setBusy(true);
    try {
      const payload = { status: form.status, remark: form.remark };
      if (editing.band === 'Amber' && (form.process_fix || '') !== (editing.process_fix || '')) payload.process_fix = form.process_fix;
      if (isMd) {
        Object.assign(payload, { improvement_action: form.improvement_action, target_date: form.target_date });
        if (form.review_date && form.review_date !== editing.review_date) payload.review_date = form.review_date;
        if ((form.owner_user_id || '') !== (editing.owner_user_id || '')) payload.owner_user_id = form.owner_user_id;
      }
      await updateIdfAction(editing.id, payload, cid);
      showSuccess('Action updated.');
      setEditing(null);
      load();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not update the action.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <DashboardHero icon={ListChecks} title={isOwner ? 'My Actions' : 'Action Plans'}
        subtitle={isOwner ? 'Improvement actions assigned to you — update progress as you go'
          : 'Generated from the feedback scores — Red repair, Amber strengthen, Green sustain'}>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {staff && <div className={`${CARD} p-4`}><CompanyPicker value={companyId} onChange={setCompanyId} /></div>}

      {data && (
        <div className={`${CARD} p-4 sm:p-5 space-y-4`}>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
            {TILES.map((t) => {
              const on = tile === t.key;
              const Icon = t.icon;
              return (
                <button key={t.key} type="button" aria-pressed={on} onClick={() => setTile(on ? '' : t.key)}
                  className="flex items-center gap-3 rounded-xl border px-3.5 py-2.5 text-left transition-all hover:shadow-sm"
                  style={{ borderColor: on ? t.c : 'var(--border)', background: on ? t.bg : 'transparent' }}>
                  <span className="rounded-lg p-2" style={{ color: t.c, background: t.bg }}><Icon size={15} /></span>
                  <span>
                    <span className="block text-[20px] font-black leading-tight tabular-nums text-[var(--text-main)]">{count(t.key)}</span>
                    <span className="block text-[11px] font-bold text-[var(--text-muted)]">{t.label}</span>
                  </span>
                </button>
              );
            })}
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="relative flex-1 min-w-[200px]">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input className={`${FIELD} w-full pl-8`} placeholder="Search department, owner or action" value={q} onChange={(e) => setQ(e.target.value)} />
            </span>
            <select className={FIELD} value={period} onChange={(e) => setPeriod(e.target.value)} aria-label="Feedback cycle month" title="The month the feedback was collected">
              <option value="">All cycle months</option>
              {periods.map((p) => <option key={p} value={p}>Cycle: {monthLabel(p)}</option>)}
            </select>
            <span className="relative inline-flex items-center" title="Actions whose target date falls in this month">
              <span className="pointer-events-none absolute left-3 text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Due</span>
              <input type="month" aria-label="Due month" className={`${FIELD} pl-11 ${dueMonth ? 'pr-8' : ''}`} value={dueMonth}
                onChange={(e) => setDueMonth(e.target.value)} />
              {dueMonth && (
                <button type="button" onClick={() => setDueMonth('')} aria-label="Clear due month"
                  className="absolute right-2 rounded p-0.5 text-[var(--text-muted)] hover:text-[var(--accent-red)]"><X size={13} /></button>
              )}
            </span>
            <select className={FIELD} value={band} onChange={(e) => setBand(e.target.value)} aria-label="Band">
              <option value="">All bands</option><option>Red</option><option>Amber</option><option>Green</option>
            </select>
          </div>
        </div>
      )}

      {data && (
        actions.length ? (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
            {actions.map((a) => <ActionCard key={a.id} a={a} onOpen={open} />)}
          </div>
        ) : (
          <div className={`${CARD} px-6 py-12 text-center`}>
            <ListChecks size={26} className="mx-auto text-[var(--text-muted)]" />
            <p className="mt-2 text-[13.5px] font-black text-[var(--text-main)]">{all.length ? 'No actions match these filters' : 'No action plans yet'}</p>
            <p className="text-[12px] text-[var(--text-muted)]">
              {all.length ? 'Clear a filter to see more.' : 'They are created automatically when a feedback cycle completes.'}
            </p>
          </div>
        )
      )}

      {editing && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={() => !busy && setEditing(null)}>
          <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true"
            className="w-full max-w-xl max-h-[90vh] flex flex-col rounded-2xl bg-[var(--bg-card)] shadow-2xl overflow-hidden">
            <div className="flex items-start gap-3 px-5 py-4 border-b border-[var(--border)]">
              <span className="mt-0.5 h-9 w-1.5 shrink-0 rounded-full" style={{ background: BAND_STYLE[editing.band]?.c || 'var(--border)' }} />
              <div className="flex-1 min-w-0">
                <h3 className="text-[15px] font-black text-[var(--text-main)] leading-tight">{editing.department} — {editing.type}</h3>
                <p className="mt-0.5 text-[11.5px] text-[var(--text-muted)]">
                  {editing.feedback_from ? `From ${editing.feedback_from} · ` : ''}{editing.parameter ? `${editing.parameter} · ` : ''}
                  {editing.current_score != null ? `${editing.current_score}% · ` : ''}{monthLabel(editing.period)}
                </p>
              </div>
              <button type="button" onClick={() => setEditing(null)} aria-label="Close" className="p-1 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]"><X size={17} /></button>
            </div>
            <div className="px-5 py-4 space-y-4 overflow-y-auto">
              {!!(editing.steps || []).length && (
                <div className="space-y-1.5">
                  <span className={LABEL}>Improvement process{editing.stage ? ` · ${editing.category || editing.band} · ${editing.stage}` : ''}</span>
                  <ol className="space-y-1.5 rounded-lg border border-[var(--border)] px-3 py-2.5">
                    {editing.steps.map((s, i) => (
                      <li key={i} className="flex gap-2.5 text-[12.5px] leading-snug text-[var(--text-main)]">
                        <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-black text-white"
                          style={{ background: BAND_STYLE[editing.band]?.c || 'var(--accent-indigo)' }}>{i + 1}</span>
                        <span className="pt-px">{s}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              <label className="block space-y-1.5">
                <span className={LABEL}>{(editing.steps || []).length ? 'Agreed action / notes' : 'Improvement action'}</span>
                {isMd ? <textarea rows={4} className={`${FIELD} w-full`} value={form.improvement_action} onChange={(e) => setForm({ ...form, improvement_action: e.target.value })} />
                  : <p className="rounded-lg bg-[var(--input-bg)] px-3 py-2.5 text-[12.5px] leading-relaxed text-[var(--text-main)]">{editing.improvement_action}</p>}
              </label>
              {editing.band === 'Amber' && (
                <label className="block space-y-1.5">
                  <span className={LABEL}>The one process fix agreed</span>
                  <select className={`${FIELD} w-full`} value={form.process_fix} onChange={(e) => setForm({ ...form, process_fix: e.target.value })}>
                    <option value="">Not agreed yet</option>
                    {PROCESS_FIXES.map((f) => <option key={f}>{f}</option>)}
                  </select>
                </label>
              )}
              {editing.rescore_pct != null && (
                <p className="rounded-lg px-3 py-2 text-[12.5px] font-bold" style={{ color: BAND_STYLE[editing.rescore_band]?.c, background: BAND_STYLE[editing.rescore_band]?.bg }}>
                  Pulse re-score: {editing.current_score}% → {editing.rescore_pct}% ({editing.rescore_band})
                </p>
              )}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label className="space-y-1.5">
                  <span className={LABEL}>Status</span>
                  <select className={`${FIELD} w-full`} value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                    <option>Open</option><option>In Progress</option><option>Closed</option>
                  </select>
                </label>
                <label className="space-y-1.5">
                  <span className={LABEL}>Target date</span>
                  {isMd ? <input type="date" className={`${FIELD} w-full`} value={form.target_date || ''} onChange={(e) => setForm({ ...form, target_date: e.target.value })} />
                    : <p className={`${FIELD} w-full`} style={{ color: editing.overdue ? 'var(--accent-red)' : undefined }}>{day(editing.target_date)}</p>}
                </label>
              </div>
              {isMd ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <label className="space-y-1.5">
                    <span className={LABEL}>Action owner</span>
                    <select className={`${FIELD} w-full`} value={form.owner_user_id} onChange={(e) => setForm({ ...form, owner_user_id: e.target.value })}>
                      {!form.owner_user_id && <option value="">Choose the responsible person…</option>}
                      {(data?.people || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  </label>
                  <label className="space-y-1.5">
                    <span className={LABEL}>Next review ({(editing.review_every_days || 14) <= 7 ? 'weekly' : 'fortnightly'})</span>
                    <input type="date" className={`${FIELD} w-full`} value={form.review_date || ''} onChange={(e) => setForm({ ...form, review_date: e.target.value })} />
                  </label>
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-[var(--text-muted)]">
                  <span className="inline-flex items-center gap-1.5"><UserRound size={13} /> Owner: <b className="text-[var(--text-main)]">{editing.owner_name || 'No owner'}</b></span>
                  {editing.review_date && (
                    <span style={{ color: editing.review_due ? 'var(--accent-orange)' : undefined }}>
                      {editing.review_due ? 'Review due' : 'Next review'}: <b>{day(editing.review_date)}</b> ({(editing.review_every_days || 14) <= 7 ? 'weekly' : 'fortnightly'})
                    </span>
                  )}
                </div>
              )}
              <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-[var(--text-muted)]">
                {editing.rescore_date && <span>Re-score: <b className="text-[var(--text-main)]">{day(editing.rescore_date)}</b></span>}
                {editing.status === 'Closed' && editing.closed_at && (
                  <span className="text-[var(--accent-green)]">Closed {day(editing.closed_at)}{editing.closed_by ? ` by ${editing.closed_by}` : ''}</span>
                )}
              </div>
              <label className="block space-y-1.5">
                <span className={LABEL}>Progress update</span>
                <textarea rows={3} className={`${FIELD} w-full`} placeholder="What was done since the last review?" value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} />
              </label>
              {!!(editing.remarks || []).length && (
                <div className="space-y-2">
                  <p className={LABEL}>History</p>
                  <ol className="space-y-2 border-l-2 border-[var(--border)] pl-3">
                    {[...editing.remarks].reverse().map((r, i) => (
                      <li key={i} className="text-[11.5px]">
                        <span className="text-[var(--text-muted)]">{day(r.at)} · {r.by} · {r.status}</span>
                        <span className="block text-[var(--text-main)]">{r.text}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
            <div className="flex items-center justify-end gap-2 px-5 py-3.5 border-t border-[var(--border)] bg-[var(--input-bg)]">
              {mayDelete && (
                <button type="button" onClick={remove} disabled={busy}
                  className="mr-auto inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12.5px] font-bold text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] disabled:opacity-50">
                  <Trash2 size={13} /> Delete
                </button>
              )}
              <button type="button" onClick={() => setEditing(null)} className="px-4 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] hover:bg-[var(--bg-card)]">Cancel</button>
              <button type="button" onClick={save} disabled={busy} className="px-5 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-black disabled:opacity-50">
                {busy ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default IdfActions;
