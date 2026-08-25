import React, { useEffect, useMemo, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CalendarRange, Plus, RefreshCw, AlertTriangle, CheckCircle2, X, ShieldAlert,
  Users, Lock, Unlock, ArrowRight, Layers, Calculator, Send, Undo2, Trash2, Mail,
} from 'lucide-react';
import {
  DashboardHero, HeaderSelect, HeroButton, Section, Th, Td, TableShell, KpiTile, FilterSelect,
} from '../../common/dashboardKit';
import {
  getLeadershipConfig, getLeadershipCycles, createLeadershipCycle, updateLeadershipCycle,
  getLeadershipQuorum, computeLeadershipCycle, publishLeadershipCycle,
  deleteLeadershipCycle,
} from '../../../../services/leadershipApi';
import { cycleLabel, cycleHint, isScoreReady } from '../../leadership/leadershipStatus';
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
  draft:     { c: 'var(--text-muted)',    bg: 'var(--input-bg)',          bd: 'var(--border)' },
  open:      { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',   bd: 'var(--accent-green-border)' },
  closed:    { c: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)',  bd: 'var(--accent-yellow-border)' },
  computed:  { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)',  bd: 'var(--accent-indigo-border)' },
  published: { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',   bd: 'var(--accent-green-border)' },
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

  // RECOMMENDED_PER_RELATION givers for every relation the degree collects: four at
  // 180° (superiors + same-department peers), eight at 360°. Read from /config so the panel
  // composition stays owned by the server; the literal is only the moment before it lands.
  const panelSizeOf = (code) => {
    const d = (config?.degrees || []).find((x) => String(x.code) === String(code));
    return d?.panel_size || (String(code) === '180' ? 4 : 8);
  };

  const [cycle, setCycle] = useState(available[0]?.code || '');
  const [degree, setDegree] = useState('360');
  const [minResponses, setMinResponses] = useState('3');
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
        // Mirrors both server bounds: MIN_RESPONSES_FLOOR, which raises anything lower
        // to 3, and the degree's panel size, which is the most replies that can ever
        // arrive. Asking 8 of a 180° panel of four is a threshold nobody could reach.
        min_responses: Math.min(Math.max(3, Number(minResponses) || 3), panelSizeOf(degree)),
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
                ? available.map((c) => ({
                    id: c.code,
                    // A past window's feedback links are already expired, so such a cycle
                    // can be created but never dispatched. Say so in the option rather
                    // than letting HR find out at the dispatch step.
                    name: c.expired ? `${c.label} — window closed, cannot collect` : c.label,
                  }))
                : [{ id: '', name: 'Every recent cycle already exists' }]} />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Feedback degree"
              hint={`360° adds other-department peers and juniors — ${panelSizeOf('360')} givers against ${panelSizeOf('180')}.`}>
              <FilterSelect value={degree}
                onChange={(v) => {
                  setDegree(v);
                  // Narrowing to 180° halves the panel, so a threshold picked under 360°
                  // can be left asking for more replies than the cycle now collects.
                  // Bring it down with the degree rather than failing on submit.
                  setMinResponses((m) => String(Math.min(Number(m) || 3, panelSizeOf(v))));
                }}
                options={[{ id: '360', name: `360° — all relations (${panelSizeOf('360')} givers)` },
                          { id: '180', name: `180° — superiors & peers (${panelSizeOf('180')} givers)` }]} />
            </Field>
            <Field label="Minimum responses"
              hint={`3 is the anonymity floor and cannot go lower. A ${degree}° panel is ${panelSizeOf(degree)} givers, so it cannot go higher than that either.`}>
              <input type="number" min={3} max={panelSizeOf(degree)} value={minResponses}
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

/** Destructive confirm for a cycle. Mounted only while a row is pending, so it seeds from
    that row and needs no reset. The server refuses a cycle holding feedback or one already
    published — that failure is shown in here rather than behind the overlay. */
const ConfirmDeleteModal = ({ row, onClose, onConfirm }) => {
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const enrolled = row.subject_count || 0;

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !saving) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [saving, onClose]);

  const go = async () => {
    setSaving(true);
    setErr('');
    try {
      await onConfirm(row);
    } catch (e) {
      setErr(errText(e, 'Could not delete this cycle.'));
      setSaving(false);
    }
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv role="alertdialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-red-bg)] text-[var(--accent-red)]">
              <Trash2 size={16} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Delete this cycle?</h3>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-2.5">
            <span className="block text-[13.5px] font-bold">{row.label || row.cycle}</span>
            <span className="block text-[10.5px] font-mono text-[var(--text-muted)]">{row.cycle}</span>
          </div>

          {enrolled > 0 && (
            <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-yellow)]">
              <AlertTriangle size={14} className="mt-[1px] shrink-0" />
              <span>
                This also un-enrols <b>{enrolled}</b> leader{enrolled === 1 ? '' : 's'} and invalidates
                any feedback links already emailed to their panels.
              </span>
            </div>
          )}

          <p className="text-[12.5px] font-medium text-[var(--text-muted)]">
            The cycle and everything set up under it are removed. This cannot be undone.
          </p>

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose} disabled={saving}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Cancel
          </button>
          <button type="button" onClick={go} disabled={saving} autoFocus
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-red)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
            {saving ? <RefreshCw size={14} className="animate-spin" /> : <Trash2 size={14} />}
            {saving ? 'Deleting…' : 'Delete Cycle'}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

/** Quorum shortfall, raised before a freeze. A warning rather than a block — the document
    sets no threshold, so HR is the one who decides whether a thin result is still worth
    freezing. What the browser confirm could not do is offer the remedy it described:
    re-opening the cycle to extend the window is a button here, not a sentence. Mounted only
    while a shortfall is pending, so it seeds from that report and needs no reset. */
const QuorumConfirmModal = ({ report, onClose, onReopen, onConfirm }) => {
  const [saving, setSaving] = useState('');   // '' | 'reopen' | 'freeze'
  const [err, setErr] = useState('');

  const rows = report.rows || [];
  const floor = report.minResponses || 3;
  // Two thresholds sit behind one warning. Below `quorum` a score is still computed, just
  // thin; below the anonymity floor the server computes nothing at all, so "freeze anyway"
  // leaves those leaders with no number rather than a weak one. Worth saying apart.
  const noScore = rows.filter((r) => (r.responses || 0) < floor).length;

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !saving) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [saving, onClose]);

  // Both actions belong to the caller and either may throw. A failure is reported in here
  // rather than behind the overlay, so the dialog stays put and the choice can be retried.
  const run = (kind, fn, fallback) => async () => {
    setSaving(kind);
    setErr('');
    try {
      await fn(report);
    } catch (e) {
      setErr(errText(e, fallback));
      setSaving('');
    }
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv role="alertdialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-yellow-bg)] text-[var(--accent-yellow)] shrink-0">
              <AlertTriangle size={16} />
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-extrabold tracking-tight">Quorum not met</h3>
              <span className="block text-[10.5px] font-bold text-[var(--text-muted)] truncate">
                {report.label || report.cycle}
              </span>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={!!saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
            <b className="text-[var(--text-main)]">
              {rows.length} of {report.subjects || rows.length} leader{(report.subjects || rows.length) === 1 ? '' : 's'}
            </b>{' '}
            {rows.length === 1 ? 'is' : 'are'} under this cycle&rsquo;s quorum of {report.quorum} responses.
          </p>

          <div className="rounded-xl border border-[var(--border)] overflow-hidden max-h-56 overflow-y-auto">
            {rows.map((r, i) => {
              const thin = (r.responses || 0) < floor;
              return (
                <div key={r.subject_id || `${r.subject_name}-${i}`}
                  className="flex items-center justify-between gap-3 bg-[var(--input-bg)] px-3.5 py-2.5 border-b border-[var(--border)] last:border-0">
                  <div className="min-w-0">
                    <span className="block text-[13px] font-bold truncate">{r.subject_name}</span>
                    <span className="block text-[10.5px] font-semibold text-[var(--text-muted)] tabular-nums">
                      {r.responses} of {r.panel_size} panel member{r.panel_size === 1 ? '' : 's'} replied
                    </span>
                  </div>
                  <span className="shrink-0 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-full border whitespace-nowrap"
                    style={thin
                      ? { color: 'var(--accent-red)', background: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }
                      : { color: 'var(--accent-yellow)', background: 'var(--accent-yellow-bg)', borderColor: 'var(--accent-yellow-border)' }}>
                    {thin ? 'no score' : `${r.short_by ?? Math.max(0, report.quorum - r.responses)} more needed`}
                  </span>
                </div>
              );
            })}
          </div>

          {noScore > 0 && (
            <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-yellow)]">
              <AlertTriangle size={14} className="mt-[1px] shrink-0" />
              <span>
                <b>{noScore}</b> of them {noScore === 1 ? 'is' : 'are'} also below the {floor}-response
                anonymity floor, so freezing leaves {noScore === 1 ? 'that leader' : 'them'} with no
                score at all &mdash; not a thin one.
              </span>
            </div>
          )}

          <p className="text-[12.5px] font-medium text-[var(--text-muted)]">
            Re-open the cycle to extend the window and chase the missing responses, or freeze
            these scores as they stand. A freeze can still be undone until you publish.
          </p>

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 flex-wrap px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose} disabled={!!saving}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Cancel
          </button>
          <button type="button" onClick={run('reopen', onReopen, 'Could not re-open this cycle.')} disabled={!!saving}
            title="Extend the window so the missing panel members can still reply"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            {saving === 'reopen' ? <RefreshCw size={14} className="animate-spin" /> : <Unlock size={14} />}
            {saving === 'reopen' ? 'Re-opening…' : 'Re-open Cycle'}
          </button>
          <button type="button" onClick={run('freeze', onConfirm, 'Could not compute this cycle.')} disabled={!!saving} autoFocus
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
            {saving === 'freeze' ? <RefreshCw size={14} className="animate-spin" /> : <Calculator size={14} />}
            {saving === 'freeze' ? 'Freezing…' : 'Freeze Anyway'}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

/** Named rather than counted. "3 leaders are missing a panel" sends HR hunting; the names
    are what they act on, and the list is short by construction. */
const BlockedNames = ({ title, rows, render }) => !rows.length ? null : (
  <div className="space-y-1.5">
    <span className="block text-[10.5px] font-bold uppercase tracking-wide text-[var(--text-muted)]">
      {title}
    </span>
    <div className="rounded-xl border border-[var(--border)] overflow-hidden max-h-40 overflow-y-auto">
      {rows.map((r) => (
        <div key={r.subject_id}
          className="flex items-center justify-between gap-3 bg-[var(--input-bg)] px-3.5 py-2 border-b border-[var(--border)] last:border-0">
          <span className="text-[12.5px] font-bold truncate">{r.subject_name}</span>
          <span className="shrink-0 text-[10.5px] font-semibold text-[var(--text-muted)] tabular-nums">
            {render(r)}
          </span>
        </div>
      ))}
    </div>
  </div>
);

/** Why a draft cycle cannot be opened yet.
    A greyed-out button would be a dead end here: enrolment and dispatch both happen on the
    Leaders screen, which is not visible from this page, so the reason has to name the step
    and offer the way to it. The three steps are the module's actual order of work, shown as
    a checklist so it is obvious which one is outstanding rather than only that something is.
    Mounted only while a row is blocked, so it seeds from that row's readiness report. */
const OpenBlockedModal = ({ row, panelBase, onClose }) => {
  const rd = row.open_readiness || {};
  const enrolled = rd.subjects || 0;
  const noPanel = rd.panels_missing || [];
  const unmailed = rd.mail_pending || [];

  const steps = [
    { icon: Users, label: 'Leaders enrolled', done: enrolled > 0,
      detail: enrolled > 0
        ? `${enrolled} leader${enrolled === 1 ? '' : 's'} in this cycle`
        : 'Nobody is enrolled yet' },
    { icon: Layers, label: 'Feedback panels assigned', done: enrolled > 0 && !noPanel.length,
      detail: noPanel.length
        ? `${noPanel.length} still without a panel`
        : (enrolled > 0 ? 'Every leader has a panel' : 'Enrol a leader first') },
    { icon: Mail, label: 'Invitations sent to feedback givers',
      done: enrolled > 0 && !noPanel.length && !unmailed.length,
      detail: unmailed.length
        ? `${unmailed.length} leader${unmailed.length === 1 ? '' : 's'} still have unsent invitations`
        : (enrolled > 0 && !noPanel.length ? 'All invitations delivered' : 'Not reached yet') },
  ];

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <MotionDiv role="alertdialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-yellow-bg)] text-[var(--accent-yellow)] shrink-0">
              <Lock size={16} />
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-extrabold tracking-tight">Not ready to open</h3>
              <span className="block text-[10.5px] font-bold text-[var(--text-muted)] truncate">
                {row.label || row.cycle}
              </span>
            </div>
          </div>
          <button type="button" onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3.5">
          <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
            Opening a cycle is what declares it to be collecting. Until the invitations are
            out, it would be collecting from nobody.
          </p>

          <div className="space-y-2">
            {steps.map((s, i) => (
              <div key={s.label} className="flex items-start gap-2.5">
                <span className="w-6 h-6 rounded-lg shrink-0 flex items-center justify-center border"
                  style={s.done
                    ? { color: 'var(--accent-green)', background: 'var(--accent-green-bg)', borderColor: 'var(--accent-green-border)' }
                    : { color: 'var(--text-muted)', background: 'var(--input-bg)', borderColor: 'var(--border)' }}>
                  {s.done ? <CheckCircle2 size={13} /> : <s.icon size={13} />}
                </span>
                <div className="min-w-0 pt-[2px]">
                  <span className={`block text-[12.5px] font-bold ${s.done ? 'text-[var(--text-muted)] line-through' : ''}`}>
                    {i + 1}. {s.label}
                  </span>
                  <span className="block text-[11px] font-semibold text-[var(--text-muted)]">{s.detail}</span>
                </div>
              </div>
            ))}
          </div>

          <BlockedNames title="No panel yet" rows={noPanel} render={() => 'panel not assigned'} />
          <BlockedNames title="Invitations not sent" rows={unmailed}
            render={(r) => (r.failed
              ? `${r.failed} failed of ${r.panel_size}`
              : `${r.pending} unsent of ${r.panel_size}`)} />

          {unmailed.some((r) => r.failed) && (
            <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-red)]">
              <AlertTriangle size={14} className="mt-[1px] shrink-0" />
              <span>
                Some invitations failed to send. Resend them from the leader&rsquo;s panel, or
                swap in a different giver if the address is wrong.
              </span>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 flex-wrap px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors">
            Close
          </button>
          <Link to={`${panelBase}/leadership/subjects?cycle=${row.cycle}`} onClick={onClose}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity">
            Go to Leaders <ArrowRight size={14} />
          </Link>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

const LeadershipCycles = () => {
  const { user, staff, companyOptions, companyId, setCompanyId } = useLeadershipCompany();
  const manage = canManage(user);
  // This page is mounted on BOTH panels — /tpms/admin/leadership for internal staff and
  // /tpms/smops/leadership/cycles for HR and the client admin — so "Leaders →" must stay on
  // whichever panel the visitor is already in. Hardcoding /tpms/admin sent a client-side user
  // into a route guarded by `RequireTpms admin`, which bounced them to their dashboard.
  const panelBase = useLocation().pathname.startsWith('/tpms/admin') ? '/tpms/admin' : '/tpms/smops';
  const [adding, setAdding] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [quorumWarn, setQuorumWarn] = useState(null);
  const [openBlocked, setOpenBlocked] = useState(null);
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
      setNotice({
        open: 'Cycle is open — feedback links can be sent.',
        closed: 'Window closed. No further feedback is accepted; compute when you are ready.',
      }[status] || 'Cycle updated.');
      await reload();
    } catch (e) {
      setError(errText(e, 'Could not update the cycle.'));
    } finally {
      setBusy('');
    }
  };

  // Delete a cycle opened by mistake. The server refuses once any feedback exists, or
  // once the cycle is published, so the dialog is about intent rather than safety — the
  // panel links it invalidates are the part worth naming before it happens. Failures are
  // left to throw: ConfirmDeleteModal reports them without dismissing itself.
  const removeCycle = async (row) => {
    setBusy(row.cycle);
    setError('');
    setNotice('');
    try {
      const res = await deleteLeadershipCycle(companyId, row.cycle);
      const r = res.data?.removed || {};
      setNotice(`${res.data?.label || row.cycle} deleted`
        + (r.subjects || r.links
          ? ` — ${r.subjects || 0} leader(s) and ${r.links || 0} feedback link(s) removed.`
          : '.'));
      setPendingDelete(null);
      await reload();
    } finally {
      setBusy('');
    }
  };

  // Freeze the scores. Refused until every level this cycle scores has been signed off by
  // HR + MD — a frozen number is what a leader is shown and a manager discusses at RRO, so
  // it must not come from a rubric nobody has approved.
  //
  // Quorum is a warning, not a block: the document sets no threshold, so HR decides
  // whether a thin result is still worth freezing. They just should not do it unknowingly,
  // which is why a shortfall opens QuorumConfirmModal instead of freezing straight away.
  const compute = async (row) => {
    setBusy(row.cycle); setError(''); setNotice('');
    try {
      const q = await getLeadershipQuorum(companyId, row.cycle);
      const short = q.data?.below_quorum || [];
      if (short.length) {
        setQuorumWarn({
          cycle: row.cycle,
          label: row.label,
          quorum: q.data?.quorum,
          subjects: q.data?.subjects,
          // The quorum and the anonymity floor say different things about what a freeze
          // produces, so both travel with the report. Preferred over the row's stored
          // value, which the degree may have capped: a 180° cycle holding 6 collects
          // from four people and is scored against 4.
          minResponses: q.data?.min_responses || row.min_responses,
          rows: short,
        });
        return;
      }
      await freeze(row.cycle);
    } catch (e) {
      setError(errText(e, 'Could not compute this cycle.'));
    } finally { setBusy(''); }
  };

  // The freeze itself, split out so QuorumConfirmModal can invoke it after HR has seen who
  // is short. Left to throw: the modal reports the failure without dismissing itself.
  const freeze = async (cycle) => {
    await computeLeadershipCycle(companyId, cycle);
    setQuorumWarn(null);
    setNotice('Scores frozen. Review them, then publish to release them to leaders.');
    await reload();
  };

  // The other way out of a quorum shortfall — extend the window rather than freeze a thin
  // result. Same transition as the Re-open button on a closed row, offered where the
  // shortfall is actually being read.
  const reopenForQuorum = async ({ cycle }) => {
    setBusy(cycle); setError(''); setNotice('');
    try {
      await updateLeadershipCycle(companyId, cycle, { status: 'open' });
      setQuorumWarn(null);
      setNotice('Cycle re-opened — feedback links work again until you close it.');
      await reload();
    } finally { setBusy(''); }
  };

  // The moment a leader can first see their own score. Irreversible for collection: once
  // people have been shown a number, changing the inputs behind it would rewrite a
  // conversation that has already happened.
  const publish = async (cycle) => {
    if (!window.confirm(
      'Publishing releases these scores to every leader and their reporting manager, and sends the notification.'
      + `\n\nA published cycle cannot be re-opened. Continue?`
    )) return;
    setBusy(cycle); setError(''); setNotice('');
    try {
      await publishLeadershipCycle(companyId, cycle);
      setNotice('Published. Leaders and their managers have been notified.');
      await reload();
    } catch (e) {
      setError(errText(e, 'Could not publish this cycle.'));
    } finally { setBusy(''); }
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
  // Closed cycles whose scores are frozen. Surfaced as a count, not as a fifth status.
  const ready = cycles.filter((c) => isScoreReady(c.status)).length;
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
        <KpiTile value={ready} label="Ready to publish" sub="Closed, scores calculated"
          tone={ready ? 'indigo' : 'plain'} icon={Calculator} />
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
                  {/* `computed` is not a user-facing state — it reads as Closed, and the
                      action column is what says the scores are ready to release. */}
                  <Td align="center" title={cycleHint(c.status)}>
                    <Pill label={cycleLabel(c.status)} tone={c.status} />
                    {isScoreReady(c.status) && (
                      <span className="block text-[9.5px] font-bold text-[var(--accent-indigo)] mt-1 whitespace-nowrap">
                        scores ready
                      </span>
                    )}
                  </Td>
                  <Td align="right">
                    <div className="inline-flex items-center gap-1.5 justify-end flex-wrap">
                      <Link to={`${panelBase}/leadership/subjects?cycle=${c.cycle}`}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                        Leaders <ArrowRight size={12} />
                      </Link>
                      {/* Create -> enrol -> assign panels -> mail -> Open. `can_open` is
                          server-computed (leadership_service.open_readiness) and mirrors
                          exactly what assert_openable enforces, so the button and the API
                          cannot disagree. Blocked draws as its own control rather than a
                          greyed Open: the remedy is on another screen, and a dead button
                          would not say which one. */}
                      {c.status === 'draft' && (
                        c.can_open === false ? (
                          <button type="button" onClick={() => setOpenBlocked(c)} disabled={busy === c.cycle}
                            title={c.open_blocked_reason || 'Enrol leaders and send their invitations first'}
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-yellow)] bg-[var(--accent-yellow-bg)] border border-[var(--accent-yellow-border)] hover:opacity-90 transition-opacity disabled:opacity-50">
                            <Lock size={12} /> Set-up incomplete
                          </button>
                        ) : (
                          <button type="button" onClick={() => setStatus(c.cycle, 'open')} disabled={busy === c.cycle}
                            title="Start collecting — the feedback links already mailed go live"
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-green)] bg-[var(--accent-green-bg)] border border-[var(--accent-green-border)] hover:opacity-90 transition-opacity disabled:opacity-50">
                            <Unlock size={12} /> Open
                          </button>
                        )
                      )}
                      {c.status === 'open' && (
                        <button type="button" onClick={() => setStatus(c.cycle, 'closed')} disabled={busy === c.cycle}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                          <Lock size={12} /> Close
                        </button>
                      )}
                      {/* closed → computed → published. Splitting these is what stops a
                          leader watching their own score move during collection. */}
                      {c.status === 'closed' && (
                        <>
                          <button type="button" onClick={() => setStatus(c.cycle, 'open')} disabled={busy === c.cycle}
                            title="Extend the window — the remedy when quorum is not met"
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                            <Unlock size={12} /> Re-open
                          </button>
                          <button type="button" onClick={() => compute(c)} disabled={busy === c.cycle}
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity disabled:opacity-50">
                            <Calculator size={12} /> Compute
                          </button>
                        </>
                      )}
                      {c.status === 'computed' && (
                        <>
                          {/* Back to closed. The backend has always allowed this, but no
                              control offered it — so a cycle computed too early could only
                              go forward to Publish, which is terminal. */}
                          <button type="button" onClick={() => setStatus(c.cycle, 'closed')} disabled={busy === c.cycle}
                            title="Undo the freeze — reopen collection or recompute before releasing"
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                            <Undo2 size={12} /> Un-compute
                          </button>
                          <button type="button" onClick={() => publish(c.cycle)} disabled={busy === c.cycle}
                            title="Release the scores to leaders and their reporting managers. This cannot be undone."
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-green)] bg-[var(--accent-green-bg)] border border-[var(--accent-green-border)] hover:opacity-90 transition-opacity disabled:opacity-50">
                            <Send size={12} /> Publish
                          </button>
                        </>
                      )}
                      {/* Offered only while it can actually succeed: the server refuses a
                          cycle holding feedback or one already published, and a button
                          that always errors is worse than no button. */}
                      {!c.response_count && c.status !== 'published' && (
                        <button type="button" onClick={() => setPendingDelete(c)} disabled={busy === c.cycle}
                          title="Delete this cycle and anything set up under it"
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-red)] bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] hover:opacity-90 transition-opacity disabled:opacity-50">
                          <Trash2 size={12} />
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
        {pendingDelete && (
          <ConfirmDeleteModal key="delete-cycle" row={pendingDelete}
            onClose={() => setPendingDelete(null)} onConfirm={removeCycle} />
        )}
        {quorumWarn && (
          <QuorumConfirmModal key="quorum-warning" report={quorumWarn}
            onClose={() => setQuorumWarn(null)}
            onReopen={reopenForQuorum}
            onConfirm={({ cycle }) => freeze(cycle)} />
        )}
        {openBlocked && (
          <OpenBlockedModal key="open-blocked" row={openBlocked} panelBase={panelBase}
            onClose={() => setOpenBlocked(null)} />
        )}
      </AnimatePresence>
    </div>
  );
};

export default LeadershipCycles;
