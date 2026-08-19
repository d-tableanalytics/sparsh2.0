import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CalendarRange, Plus, RefreshCw, AlertTriangle, CheckCircle2, X, ShieldAlert,
  Users, Lock, Unlock, ArrowRight, Layers,
} from 'lucide-react';
import {
  DashboardHero, HeaderSelect, HeroButton, Section, Th, Td, TableShell, KpiTile, FilterSelect,
} from '../../common/dashboardKit';
import {
  getLeadershipConfig, getLeadershipCycles, createLeadershipCycle, updateLeadershipCycle,
} from '../../../../services/leadershipApi';
import {
  canManage, errText, fmtNum, useAsync, useLeadershipCompany,
} from '../../leadership/leadershipUtils';

/* ─────────────────────────────────────────────────────────────
   Leadership Score ▸ Assessment Cycles.

   "By giving feedback to leaders once in every 2 months."

   A cycle spans two calendar months and owns the degree (180°/360°) and the response
   threshold for every leader enrolled in it. Closing a cycle freezes its scores into
   history, which is why it is a deliberate action rather than a date passing.
   ───────────────────────────────────────────────────────────── */

const MotionDiv = motion.div;

const STATUS_TONE = {
  draft:  { c: 'var(--text-muted)',    bg: 'var(--input-bg)',          bd: 'var(--border)' },
  open:   { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',   bd: 'var(--accent-green-border)' },
  closed: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)',  bd: 'var(--accent-indigo-border)' },
};

const Pill = ({ label, tone = 'draft' }) => {
  const s = STATUS_TONE[tone] || STATUS_TONE.draft;
  return (
    <span className="inline-flex items-center text-[10px] font-bold tracking-wide uppercase px-2.5 py-1 rounded-full border whitespace-nowrap"
      style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      {label}
    </span>
  );
};

const inputCls =
  'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] transition-colors';
const labelCls = 'text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]';

const Field = ({ label, hint, children }) => (
  <label className="flex flex-col gap-1.5">
    <span className={labelCls}>{label}</span>
    {children}
    {hint && <span className="text-[10.5px] text-[var(--text-muted)] font-medium">{hint}</span>}
  </label>
);

/** Open a new 2-month cycle. Mounted only while open, so state seeds cleanly. */
const CycleModal = ({ config, existing, onClose, onSubmit }) => {
  const taken = new Set((existing || []).map((c) => c.cycle));
  const available = (config?.cycles || []).filter((c) => !taken.has(c.code));

  const [cycle, setCycle] = useState(available[0]?.code || '');
  const [degree, setDegree] = useState('360');
  const [minResponses, setMinResponses] = useState('1');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    if (!cycle) { setErr('Choose a cycle.'); return; }
    setSaving(true);
    setErr('');
    try {
      await onSubmit({
        cycle,
        degree,
        min_responses: Math.max(1, Number(minResponses) || 1),
        notes: notes.trim(),
      });
    } catch (ex) {
      setErr(errText(ex, 'Could not create the cycle.'));
      setSaving(false);
    }
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              <Plus size={16} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Open an Assessment Cycle</h3>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={submit} className="px-5 py-4 space-y-4">
          <Field label="Cycle" hint="Leadership feedback runs once every 2 months.">
            <FilterSelect value={cycle} onChange={setCycle}
              options={available.length
                ? available.map((c) => ({ id: c.code, name: c.label }))
                : [{ id: '', name: 'Every recent cycle already exists' }]} />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Feedback degree" hint="360° adds other-department peers and juniors.">
              <FilterSelect value={degree} onChange={setDegree}
                options={[{ id: '360', name: '360° — all relations' },
                          { id: '180', name: '180° — superiors & peers' }]} />
            </Field>
            <Field label="Minimum responses"
              hint="Responses needed before a score is shown. 1 = show as soon as any arrive.">
              <input type="number" min={1} max={8} value={minResponses}
                onChange={(e) => setMinResponses(e.target.value)} className={inputCls} />
            </Field>
          </div>

          <Field label="Notes">
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
              placeholder="Optional note for HR…" className={`${inputCls} resize-y`} />
          </Field>

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} disabled={saving}
              className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
              Cancel
            </button>
            <button type="submit" disabled={saving || !cycle}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
              {saving ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              {saving ? 'Creating…' : 'Open Cycle'}
            </button>
          </div>
        </form>
      </MotionDiv>
    </MotionDiv>
  );
};

const LeadershipCycles = () => {
  const { user, staff, companyOptions, companyId, setCompanyId } = useLeadershipCompany();
  const manage = canManage(user);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');

  const waiting = staff && !companyId;

  const cfg = useAsync(async () => (await getLeadershipConfig()).data, [], { skip: !manage });
  const load = useMemo(
    () => async () => (await getLeadershipCycles(companyId)).data,
    [companyId],
  );
  const { data, loading, error, setError, reload } = useAsync(load, [companyId],
    { skip: waiting || !manage });

  const cycles = data?.cycles || [];

  const create = async (payload) => {
    await createLeadershipCycle(companyId, payload);
    setAdding(false);
    setNotice(`Cycle opened. Enrol leaders next.`);
    await reload();
  };

  const setStatus = async (cycle, status) => {
    setBusy(cycle);
    setError('');
    setNotice('');
    try {
      await updateLeadershipCycle(companyId, cycle, { status });
      setNotice(status === 'closed'
        ? 'Cycle closed. Its scores are now frozen in history.'
        : 'Cycle is open — feedback links can be sent.');
      await reload();
    } catch (e) {
      setError(errText(e, 'Could not update the cycle.'));
    } finally {
      setBusy('');
    }
  };

  if (!manage) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold">HR and administrators only</p>
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-sm">
          Leadership Score cycles are managed by HR. If you have received feedback, your own
          result is on the Leadership Report page.
        </p>
      </div>
    );
  }

  const open = cycles.filter((c) => c.status === 'open').length;
  const leaders = cycles.reduce((s, c) => s + (c.subject_count || 0), 0);
  const responses = cycles.reduce((s, c) => s + (c.response_count || 0), 0);

  return (
    <div className="space-y-5">
      <DashboardHero icon={CalendarRange} title="Leadership Score — Cycles"
        subtitle="Two-month assessment windows for anonymous leadership feedback">
        {staff && <HeaderSelect value={companyId} onChange={setCompanyId} options={companyOptions} />}
        <HeroButton icon={Plus} onClick={() => setAdding(true)}>Open Cycle</HeroButton>
        <HeroButton icon={RefreshCw} onClick={reload}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}
      {notice && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)]">
          <CheckCircle2 size={15} /> {notice}
        </div>
      )}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        <KpiTile value={cycles.length} label="Cycles" sub="All time" tone="blue" icon={Layers} />
        <KpiTile value={open} label="Open" sub="Collecting feedback" tone={open ? 'green' : 'plain'} icon={Unlock} />
        <KpiTile value={leaders} label="Leaders" sub="Enrolled across cycles" tone="blue" icon={Users} />
        <KpiTile value={responses} label="Responses" sub="Feedback received" tone={responses ? 'green' : 'plain'} icon={CheckCircle2} />
      </div>

      <Section title="Assessment Cycles" icon={CalendarRange}
        subtitle={waiting ? 'Select a company' : `${cycles.length} cycle${cycles.length === 1 ? '' : 's'}`}>
        {waiting ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Select a company to manage its cycles.
          </div>
        ) : loading ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Loading cycles…
          </div>
        ) : cycles.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
              <CalendarRange size={20} />
            </span>
            <p className="text-[13px] font-bold">No cycles yet</p>
            <p className="text-[12px] text-[var(--text-muted)] max-w-sm">
              Open a two-month cycle, enrol the leaders (L4 and above), then assign each of
              them a panel of feedback givers.
            </p>
          </div>
        ) : (
          <TableShell minWidth={940}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th>Cycle</Th><Th align="center">Degree</Th><Th align="center">Min. responses</Th>
                <Th align="center">Leaders</Th><Th align="center">Responses</Th>
                <Th align="center">Status</Th><Th align="right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {cycles.map((c) => (
                <tr key={c.cycle} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td>
                    <span className="font-bold">{c.label}</span>
                    <span className="block text-[10.5px] text-[var(--text-muted)] font-mono">{c.cycle}</span>
                  </Td>
                  <Td align="center" className="font-bold tabular-nums">{c.degree}°</Td>
                  <Td align="center" className="tabular-nums text-[var(--text-muted)]">{fmtNum(c.min_responses)}</Td>
                  <Td align="center" className="tabular-nums font-bold">{c.subject_count ?? 0}</Td>
                  <Td align="center" className="tabular-nums font-bold">{c.response_count ?? 0}</Td>
                  <Td align="center"><Pill label={c.status} tone={c.status} /></Td>
                  <Td align="right">
                    <div className="inline-flex items-center gap-1.5 justify-end flex-wrap">
                      <Link to={`/tpms/admin/leadership/subjects?cycle=${c.cycle}`}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                        Leaders <ArrowRight size={12} />
                      </Link>
                      {c.status === 'draft' && (
                        <button type="button" onClick={() => setStatus(c.cycle, 'open')} disabled={busy === c.cycle}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-green)] bg-[var(--accent-green-bg)] border border-[var(--accent-green-border)] hover:opacity-90 transition-opacity disabled:opacity-50">
                          <Unlock size={12} /> Open
                        </button>
                      )}
                      {c.status === 'open' && (
                        <button type="button" onClick={() => setStatus(c.cycle, 'closed')} disabled={busy === c.cycle}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                          <Lock size={12} /> Close
                        </button>
                      )}
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Section>

      <AnimatePresence>
        {adding && (
          <CycleModal key="add-cycle" config={cfg.data} existing={cycles}
            onClose={() => setAdding(false)} onSubmit={create} />
        )}
      </AnimatePresence>
    </div>
  );
};

export default LeadershipCycles;
