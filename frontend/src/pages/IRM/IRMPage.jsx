import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Gauge, RefreshCw, SlidersHorizontal, Users, Target, TrendingUp,
  AlertTriangle, ChevronDown, Percent, Info, Calculator,
  Clock, Upload, Download, X, Plus,
} from 'lucide-react';
import {
  DashboardHero, HeaderSelect, HeroButton, Section, Th, Td, TableShell,
  KpiTile, usePaged, Pager,
} from '../../features/tpms/common/dashboardKit';
import {
  getIrmScores, recalculateIrm,
  importIrmAttendance, exportIrmAttendance, getIrmAttendanceTemplate, saveIrmConfig,
} from '../../services/irmApi';
import { createTask } from '../../services/taskApi';
import {
  canEditWeightages, canRecalculate, currentPeriod, errText, fmtNum, fmtPct, periodLabel,
  periodOptions, scoreColor, scoreTone, useAsync, useIrmCompany,
} from './irmUtils';

/* ─────────────────────────────────────────────────────────────
   IRM ▸ scoreboard.

   One row per person, one column per evaluation parameter. Every cell shows the
   achievement % AND what it contributed after weighting, because the whole point of
   the sheet is that those two numbers are different:

       Weighted Score = (Achievement % × Weightage) ÷ 100

   Expanding a row spells the arithmetic out per parameter. Nothing is computed here —
   the backend returns achievement, weightage, weighted_score and final_irm already
   derived from the company's saved weightages, so this page and the API can never
   disagree about a score.
   ───────────────────────────────────────────────────────────── */

const MotionDiv = motion.div;

/** Achievement % as a bar + value. Muted and dashed when the parameter had no data. */
const AchievementBar = ({ value, hasData }) => {
  if (!hasData) {
    return <span className="text-[11.5px] font-bold text-[var(--text-muted)]">No data</span>;
  }
  const c = scoreColor(value);
  return (
    <div className="flex items-center gap-2 min-w-[104px]">
      <div className="h-1.5 flex-1 rounded-full bg-[var(--input-bg)] overflow-hidden">
        <div className="h-full rounded-full transition-all"
          style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: c }} />
      </div>
      <span className="text-[11.5px] font-bold tabular-nums w-[52px] text-right" style={{ color: c }}>
        {fmtPct(value)}
      </span>
    </div>
  );
};

/** "20 / 25" — what the parameter contributed out of what it could have. */
const WeightedCell = ({ p }) => (
  <span className="text-[11px] font-bold tabular-nums text-[var(--text-muted)]">
    {p.has_data ? fmtNum(p.weighted_score) : '0'}
    <span className="opacity-60"> / {fmtNum(p.max_score)}</span>
  </span>
);

/** The final IRM, out of 100. */
const FinalScore = ({ value, hasData }) => {
  const c = hasData ? scoreColor(value) : 'var(--text-muted)';
  return (
    <span className="inline-flex items-baseline gap-1 justify-end">
      <span className="text-[16px] font-extrabold tabular-nums" style={{ color: c }}>
        {hasData ? fmtNum(value) : '—'}
      </span>
      {hasData && <span className="text-[10px] font-bold text-[var(--text-muted)]">/ 100</span>}
    </span>
  );
};

/** The expanded row — the calculation, parameter by parameter. */
const Breakdown = ({ row, columns }) => (
  <div className="px-4 py-4 bg-[var(--input-bg)]/40 border-t border-[var(--border)]">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {row.parameters.map((p) => (
        <div key={p.code}
          className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-3.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[12px] font-extrabold tracking-tight">{p.name}</span>
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              {fmtNum(p.weightage)}%
            </span>
          </div>

          <dl className="mt-2.5 space-y-1 text-[11.5px]">
            <div className="flex items-center justify-between gap-2">
              <dt className="text-[var(--text-muted)]">
                {p.source === 'form' ? 'Rating points' : 'Achieved / Assigned'}
              </dt>
              <dd className="font-bold tabular-nums">
                {fmtNum(p.achieved, '0')} / {fmtNum(p.assigned, '0')}
                {/* A part-finished checklist earns part of a task, so `achieved` can read
                    3.9 of 5. Spell out the split rather than leaving a puzzling decimal. */}
                {p.source === 'task' && p.partial > 0 && (
                  <span className="text-[10px] font-medium text-[var(--text-muted)]">
                    {' '}({p.completed} done + {p.partial} part-done)
                  </span>
                )}
                {p.source === 'form' && p.ratings > 0 && (
                  <span className="text-[10px] font-medium text-[var(--text-muted)]">
                    {' '}({p.ratings} × {p.scale_max})
                  </span>
                )}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-[var(--text-muted)]">Achievement %</dt>
              <dd className="font-bold tabular-nums" style={{ color: scoreColor(p.achievement) }}>
                {fmtPct(p.achievement, 'No data')}
              </dd>
            </div>
          </dl>

          {/* The formula, with this person's numbers substituted in. */}
          <div className="mt-2.5 pt-2.5 border-t border-[var(--border)]">
            <p className="text-[10.5px] font-mono text-[var(--text-muted)] leading-relaxed break-words">
              {p.has_data
                ? `(${fmtNum(p.achievement)} × ${fmtNum(p.weightage)}) ÷ 100`
                : 'no data → contributes 0'}
            </p>
            <p className="text-[13px] font-extrabold tabular-nums mt-1">
              = {fmtNum(p.weighted_score)}
              <span className="text-[10.5px] font-bold text-[var(--text-muted)]"> of {fmtNum(p.max_score)}</span>
            </p>
          </div>
        </div>
      ))}
    </div>

    {/* The sum, written out. */}
    <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3">
      <Calculator size={14} className="text-[var(--accent-indigo)]" />
      <span className="text-[11.5px] font-bold text-[var(--text-muted)]">Final IRM =</span>
      <span className="text-[11.5px] font-mono tabular-nums">
        {row.parameters.map((p) => fmtNum(p.weighted_score)).join(' + ')}
      </span>
      <span className="text-[13px] font-extrabold tabular-nums" style={{ color: scoreColor(row.final_irm) }}>
        = {fmtNum(row.final_irm)}%
      </span>
      {row.applicable_weightage < row.total_weightage && row.has_data && (
        <span className="text-[10.5px] font-bold text-[var(--text-muted)] w-full sm:w-auto">
          · only {fmtNum(row.applicable_weightage)}% of the weightage had data
          {row.final_irm_applicable !== null && (
            <> — {fmtNum(row.final_irm_applicable)}% on what was scored</>
          )}
        </span>
      )}
    </div>

    {/* Column key for the collapsed row, so the header abbreviations stay readable. */}
    <p className="mt-2 text-[10.5px] text-[var(--text-muted)]">
      {columns.map((c) => `${c.name} ${fmtNum(c.weightage)}%`).join(' · ')}
    </p>
  </div>
);

/** Import punch times, then say exactly what landed.
    A bulk load that half-worked is the worst outcome, so unmatched identifiers are named
    rather than counted — a file whose employee codes are wrong has to fail visibly, not
    score the wrong people. */
const AttendanceModal = ({ companyId, period, onClose, onImported }) => {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [result, setResult] = useState(null);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy, onClose]);

  const doImport = async () => {
    if (!file) { setErr('Choose a file first.'); return; }
    setBusy('import'); setErr(''); setResult(null);
    try {
      const res = await importIrmAttendance(companyId, file);
      setResult(res.data);
      onImported?.();
    } catch (e) {
      setErr(errText(e, 'Could not import that file.'));
    } finally { setBusy(''); }
  };

  // The blob is turned into a click here rather than a plain link: the request needs the
  // auth header the axios instance carries, which an <a href> would not send.
  const download = async (kind, request, filename, failure) => {
    setBusy(kind); setErr('');
    try {
      const res = await request();
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErr(errText(e, failure));
    } finally { setBusy(''); }
  };

  const doTemplate = () => download(
    'template',
    () => getIrmAttendanceTemplate(companyId),
    'irm-attendance-template.xlsx',
    'Could not download the template.',
  );

  const doExport = () => download(
    'export',
    () => exportIrmAttendance(companyId, period),
    `irm-attendance-${period || 'all'}.xlsx`,
    'Could not export attendance.',
  );

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={busy ? undefined : onClose} />
      <MotionDiv role="dialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shrink-0">
              <Clock size={16} />
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-extrabold tracking-tight">Attendance</h3>
              <span className="block text-[10.5px] font-bold text-[var(--text-muted)]">
                {periodLabel(period)} · punch times feed Punctuality
              </span>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={!!busy}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3.5">
          <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
            The file needs a <b className="text-[var(--text-main)]">Date</b> column, an{' '}
            <b className="text-[var(--text-main)]">In Time</b> column, and one of Employee ID,
            Email or Name to match people. Out Time is optional but a day without it cannot
            count as punctual. Re-importing a day replaces it.
          </p>

          {/* Offered before the file picker on purpose: the template carries the roster's
              own Employee IDs, which are exactly what the importer matches on. Starting
              from it is what stops a whole file landing in `unmatched`. */}
          <button type="button" onClick={doTemplate} disabled={!!busy}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-dashed border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[12.5px] font-bold hover:opacity-90 transition-opacity disabled:opacity-50">
            {busy === 'template' ? <RefreshCw size={14} className="animate-spin" /> : <Download size={14} />}
            {busy === 'template' ? 'Preparing…' : 'Download template (with your roster)'}
          </button>

          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">
              Attendance file (.xlsx / .csv)
            </span>
            <input type="file" accept=".xlsx,.xls,.csv" disabled={!!busy}
              onChange={(e) => { setFile(e.target.files?.[0] || null); setResult(null); setErr(''); }}
              className="w-full text-[12px] font-semibold file:mr-3 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:bg-[var(--accent-indigo-bg)] file:text-[var(--accent-indigo)] file:font-bold" />
          </label>

          {result && (
            <div className="rounded-xl border border-[var(--border)] overflow-hidden">
              <div className="grid grid-cols-3 divide-x divide-[var(--border)]">
                {[
                  { label: 'New', value: result.imported, tone: 'var(--accent-green)' },
                  { label: 'Updated', value: result.updated, tone: 'var(--accent-indigo)' },
                  { label: 'Skipped', value: result.skipped, tone: 'var(--text-muted)' },
                ].map((s) => (
                  <div key={s.label} className="px-3 py-2.5 text-center bg-[var(--input-bg)]">
                    <div className="text-[17px] font-black tabular-nums" style={{ color: s.tone }}>{s.value ?? 0}</div>
                    <div className="text-[10px] font-black uppercase tracking-wide text-[var(--text-muted)]">{s.label}</div>
                  </div>
                ))}
              </div>
              {!!result.unmatched_count && (
                <div className="flex items-start gap-2 px-3.5 py-2.5 border-t border-[var(--border)] bg-[var(--accent-yellow-bg)] text-[11.5px] font-semibold text-[var(--accent-yellow)]">
                  <AlertTriangle size={14} className="mt-[1px] shrink-0" />
                  <span>
                    {result.unmatched_count} identifier{result.unmatched_count === 1 ? '' : 's'} matched
                    nobody on the roster: {(result.unmatched || []).map((u) => u.identifier).join(', ')}
                    {result.unmatched_count > (result.unmatched || []).length ? '…' : ''}
                  </span>
                </div>
              )}
            </div>
          )}

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 flex-wrap px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={doExport} disabled={!!busy}
            title="Download what is stored — same columns the importer reads, so it can be corrected and re-loaded"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            {busy === 'export' ? <RefreshCw size={14} className="animate-spin" /> : <Download size={14} />}
            {busy === 'export' ? 'Exporting…' : 'Export'}
          </button>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} disabled={!!busy}
              className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
              Close
            </button>
            <button type="button" onClick={doImport} disabled={!!busy || !file}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
              {busy === 'import' ? <RefreshCw size={14} className="animate-spin" /> : <Upload size={14} />}
              {busy === 'import' ? 'Importing…' : 'Import'}
            </button>
          </div>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

/** Create a task from the scoreboard, weighted.
    Two different weights meet on this form and are kept visibly apart:
      • the TASK weight — how much this one task counts inside the Task parameter;
      • the PERSON column — how the five parameters trade off for this person.
    The second is optional and edits the same per-person override IRM Setup writes, so
    nothing here is a second source of truth for it. */
/** The `start` a task created from this board should carry.
    IRM buckets a task by the month its `start` falls in (report_service.fetch_tasks filters
    on exactly that field), so it is anchored to the period being VIEWED rather than to the
    clock: a task created while looking at August must not land in September and vanish from
    the board that made it. Midday UTC on the 1st keeps it inside the month whichever way the
    viewer's timezone leans. */
const startForPeriod = (period) => {
  const now = new Date();
  const thisMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  if (!period || period === thisMonth) return now.toISOString();
  const [year, month] = String(period).split('-').map(Number);
  if (!year || !month) return now.toISOString();
  return new Date(Date.UTC(year, month - 1, 1, 12, 0, 0)).toISOString();
};

const CreateTaskModal = ({ companyId, period, people, columns, onClose, onCreated }) => {
  const [form, setForm] = useState({ title: '', person: '', end: '', weight: '1' });
  const [tuning, setTuning] = useState(false);
  // Edits are stored PER PERSON rather than as one column reset by an effect: switching
  // person then reads its own seed straight away, and nobody's typed figures leak onto
  // somebody else's sheet.
  const [edits, setEdits] = useState({});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const person = people.find((p) => p.person_id === form.person);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !saving) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [saving, onClose]);

  // Seeded from the person's CURRENT weightages, so opening the editor shows what they are
  // on today rather than an empty form that would silently reset them. Derived, not stored:
  // a state seeded from an effect re-renders twice and drifts when the scores reload.
  const column = useMemo(() => {
    const stored = person?.weightages || {};
    const seed = Object.fromEntries(
      columns.map((c) => [c.code, String(stored[c.code] ?? c.weightage ?? 0)]));
    return { ...seed, ...(edits[form.person] || {}) };
  }, [person, columns, edits, form.person]);

  const setCell = (code, value) => setEdits((prev) => ({
    ...prev, [form.person]: { ...(prev[form.person] || {}), [code]: value },
  }));

  const columnTotal = Math.round(
    columns.reduce((s, c) => s + (Number(column[c.code]) || 0), 0) * 100) / 100;
  const columnValid = Math.abs(columnTotal - 100) < 0.01;

  const submit = async (e) => {
    e.preventDefault();
    if (!form.title.trim()) { setErr('Give the task a title.'); return; }
    if (!form.person) { setErr('Choose who it is for.'); return; }
    if (tuning && !columnValid) { setErr(`This person's column must total 100% (currently ${columnTotal}%).`); return; }

    setSaving(true);
    setErr('');
    try {
      // The ordinary task API — deliberately not a new endpoint, so a task made here is
      // the same object Task & Delegation manages, notifications and all.
      await createTask({
        title: form.title.trim(),
        // Required by CalendarEventBase, and it is what decides the task's IRM month.
        start: startForPeriod(period),
        end: form.end ? new Date(form.end).toISOString() : null,
        priority: 'Normal',
        assigned_to: 'other',
        target_staff_id: [form.person],
        irm_weight: Number(form.weight) || 1,
      });
      if (tuning) {
        await saveIrmConfig(
          companyId,
          columns.map((c) => ({ code: c.code, weightage: Number(column[c.code]) || 0 })),
          form.person,
        );
      }
      onCreated?.(person?.name || 'that person', tuning);
    } catch (ex) {
      setErr(errText(ex, 'Could not create the task.'));
      setSaving(false);
    }
  };

  const field = 'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-semibold outline-none focus:border-[var(--accent-indigo)] transition-colors';

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv role="dialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)] shrink-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shrink-0">
              <Plus size={16} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Create Task</h3>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={submit} className="px-5 py-4 space-y-3.5 overflow-y-auto">
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Title</span>
            <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="What needs doing?" className={field} />
          </label>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">For</span>
              <select value={form.person} onChange={(e) => setForm({ ...form, person: e.target.value })}
                className={field}>
                <option value="">Choose a person…</option>
                {people.map((p) => (
                  <option key={p.person_id} value={p.person_id}>{p.name}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Deadline</span>
              <input type="date" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })}
                className={field} />
            </label>
          </div>

          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">
              Task weight
            </span>
            <input type="number" min={0.1} max={10} step={0.1} value={form.weight}
              onChange={(e) => setForm({ ...form, weight: e.target.value })} className={field} />
            <span className="text-[10.5px] font-semibold text-[var(--text-muted)]">
              How much this one task counts inside the Task parameter. 1 is normal; 3 counts
              for three ordinary tasks. It does not change the person&rsquo;s IRM column.
            </span>
          </label>

          <p className="text-[11px] font-semibold text-[var(--text-muted)]">
            Counts toward <b className="text-[var(--text-main)]">{periodLabel(period)}</b> — the
            period this board is showing.
          </p>

          {/* The other kind of weight, kept behind a toggle so the two are never confused. */}
          <div className="rounded-xl border border-[var(--border)] overflow-hidden">
            <button type="button" onClick={() => setTuning((t) => !t)} disabled={!form.person}
              className="w-full flex items-center justify-between gap-2 px-3.5 py-2.5 bg-[var(--input-bg)] text-left disabled:opacity-50">
              <span className="text-[12px] font-bold">
                Also adjust {person?.name || 'this person'}&rsquo;s IRM column
              </span>
              <ChevronDown size={14} className={`transition-transform ${tuning ? 'rotate-180' : ''}`} />
            </button>
            {tuning && form.person && (
              <div className="px-3.5 py-3 space-y-2.5">
                <p className="text-[11px] font-semibold text-[var(--text-muted)]">
                  Saved as this person&rsquo;s own column — everyone else stays on the company
                  default. Must total 100%.
                </p>
                {columns.map((c) => (
                  <div key={c.code} className="flex items-center justify-between gap-3">
                    <span className="text-[12px] font-bold truncate">{c.name}</span>
                    <input type="number" min={0} max={100} step={1} value={column[c.code] ?? ''}
                      onChange={(e) => setCell(c.code, e.target.value)}
                      className="w-24 px-2.5 py-1.5 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-bold text-right tabular-nums outline-none focus:border-[var(--accent-indigo)]" />
                  </div>
                ))}
                <div className="flex items-center justify-between pt-1.5 border-t border-[var(--border)]">
                  <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Total</span>
                  <span className="text-[14px] font-extrabold tabular-nums"
                    style={{ color: columnValid ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                    {columnTotal}%
                  </span>
                </div>
              </div>
            )}
          </div>

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
            <button type="submit" disabled={saving}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
              {saving ? <RefreshCw size={14} className="animate-spin" /> : <Plus size={14} />}
              {saving ? 'Creating…' : 'Create Task'}
            </button>
          </div>
        </form>
      </MotionDiv>
    </MotionDiv>
  );
};

const IRMPage = () => {
  const { user, staff, companies, companyId, setCompanyId } = useIrmCompany();
  const [period, setPeriod] = useState(currentPeriod());
  const [expanded, setExpanded] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [showAttendance, setShowAttendance] = useState(false);
  const [showCreateTask, setShowCreateTask] = useState(false);

  // Editing weightages is Super Admin only; refreshing the snapshot is not an edit.
  const canEdit = canEditWeightages(user);
  const canRefresh = canRecalculate(user);
  const periods = useMemo(() => periodOptions(12), []);
  const waitingForCompany = staff && !companyId;
  // A placeholder entry is how StyledSelect shows "nothing chosen yet" (see SelectField).
  const companyOptions = useMemo(
    () => (companies.length ? companies : [{ id: '', name: 'Loading companies…' }]),
    [companies],
  );

  const load = useCallback(
    async () => (await getIrmScores(companyId, period)).data,
    [companyId, period],
  );
  const { data, loading, error, setError, reload } = useAsync(load, [companyId, period], {
    skip: waitingForCompany,
  });

  const rows = data?.rows || [];
  const columns = data?.parameters || [];
  const paged = usePaged(rows, 12);

  const recalc = async () => {
    setBusy(true);
    setNotice('');
    setError('');
    try {
      const res = await recalculateIrm(companyId, period);
      setNotice(`Snapshot refreshed for ${res.data?.recalculated ?? 0} people.`);
      await reload();
    } catch (e) {
      setError(errText(e, 'Could not recalculate IRM.'));
    } finally {
      setBusy(false);
    }
  };

  const summary = data?.summary || {};
  const kpis = [
    { value: summary.people ?? 0, label: 'People', sub: 'On the roster', tone: 'blue', icon: Users },
    { value: summary.scored ?? 0, label: 'Scored', sub: 'With data this period', tone: summary.scored ? 'green' : 'plain', icon: Target },
    { value: fmtNum(summary.average_irm), label: 'Average IRM', sub: 'Out of 100', tone: scoreTone(summary.average_irm), icon: Gauge },
    { value: fmtNum(summary.highest), label: 'Highest IRM', sub: 'Top performer', tone: scoreTone(summary.highest), icon: TrendingUp },
  ];

  return (
    <div className="space-y-5">
      <DashboardHero
        icon={Gauge}
        title="Individual Result Matrix (IRM)"
        subtitle={`Weighted performance score per person · ${periodLabel(period)}`}
      >
        {staff && (
          <HeaderSelect value={companyId} onChange={setCompanyId} options={companyOptions} />
        )}
        <HeaderSelect value={period} onChange={setPeriod} options={periods} />
        {/* Attendance is the Punctuality parameter's only input, and a task is what the
            Task parameter counts — both belong beside the scoreboard they move. */}
        {canRefresh && !waitingForCompany && (
          <HeroButton icon={Clock} onClick={() => setShowAttendance(true)}>Attendance</HeroButton>
        )}
        {canRefresh && !waitingForCompany && (
          <HeroButton icon={Plus} onClick={() => setShowCreateTask(true)}>Create Task</HeroButton>
        )}
        {canRefresh && <HeroButton icon={RefreshCw} onClick={recalc}>{busy ? 'Working…' : 'Recalculate'}</HeroButton>}
        <HeroButton icon={RefreshCw} onClick={reload}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}
      {notice && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)]">
          <Info size={15} /> {notice}
        </div>
      )}

      {/* The weightage column from the sheet, read-only here — editable in Setup. */}
      {columns.length > 0 && (
        <Section
          title="Weightage"
          subtitle={canEdit
            ? "Each parameter's share of the 100-point score"
            : "Each parameter's share of the 100-point score · set by your Sparsh administrator"}
          icon={Percent}
          action={canEdit && (
            <Link to="/irm/setup"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
              <SlidersHorizontal size={13} /> Edit Weightages
            </Link>
          )}
        >
          <div className="flex flex-wrap items-center gap-2.5 px-5 py-4">
            {columns.map((c) => (
              <span key={c.code}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                <span className="text-[12px] font-bold">{c.name}</span>
                <span className="text-[12px] font-extrabold tabular-nums text-[var(--accent-indigo)]">
                  {fmtNum(c.weightage)}%
                </span>
              </span>
            ))}
            <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border"
              style={{
                background: data?.is_valid_weightage ? 'var(--accent-green-bg)' : 'var(--accent-red-bg)',
                borderColor: data?.is_valid_weightage ? 'var(--accent-green-border)' : 'var(--accent-red-border)',
                color: data?.is_valid_weightage ? 'var(--accent-green)' : 'var(--accent-red)',
              }}>
              <span className="text-[11px] font-bold uppercase tracking-wide">Grand Total</span>
              <span className="text-[12px] font-extrabold tabular-nums">{fmtNum(data?.total_weightage)}%</span>
            </span>
          </div>
          {data && !data.is_valid_weightage && (
            <p className="px-5 pb-4 -mt-1 text-[11.5px] font-bold text-[var(--accent-red)]">
              Weightages total {fmtNum(data.total_weightage)}%, not 100% — scores are not out of 100
              until an administrator corrects this in Setup.
            </p>
          )}
        </Section>
      )}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      <Section
        title="Individual Scores"
        subtitle={waitingForCompany ? 'Select a company' : `${rows.length} ${rows.length === 1 ? 'person' : 'people'} · ${periodLabel(period)}`}
        icon={Users}
      >
        {waitingForCompany ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Select a company to view its IRM.
          </div>
        ) : loading ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Calculating IRM…
          </div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
              <Users size={20} />
            </span>
            <p className="text-[13px] font-bold">No people to score</p>
            <p className="text-[12px] text-[var(--text-muted)]">
              This company has no active members on its roster.
            </p>
          </div>
        ) : (
          <>
            <TableShell minWidth={1080}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th>Person</Th>
                  {columns.map((c) => (
                    <Th key={c.code}>
                      {c.name}
                      <span className="ml-1 opacity-70">({fmtNum(c.weightage)}%)</span>
                    </Th>
                  ))}
                  <Th align="right">Final IRM</Th>
                  <Th align="center"> </Th>
                </tr>
              </thead>
              <tbody>
                {paged.pageRows.map((row) => {
                  const open = expanded === row.person_id;
                  return (
                    <React.Fragment key={row.person_id}>
                      <tr
                        className="border-b border-[var(--border)] hover:bg-[var(--table-hover)] transition-colors cursor-pointer"
                        onClick={() => setExpanded(open ? null : row.person_id)}
                      >
                        <Td>
                          <span className="font-bold">{row.name}</span>
                          {(row.designation || row.department) && (
                            <span className="block text-[10.5px] text-[var(--text-muted)]">
                              {[row.designation, row.department].filter(Boolean).join(' · ')}
                            </span>
                          )}
                        </Td>
                        {columns.map((c) => {
                          const p = row.parameters.find((x) => x.code === c.code) || {};
                          return (
                            <Td key={c.code}>
                              <AchievementBar value={p.achievement} hasData={p.has_data} />
                              <span className="block mt-1"><WeightedCell p={p} /></span>
                            </Td>
                          );
                        })}
                        <Td align="right">
                          <FinalScore value={row.final_irm} hasData={row.has_data} />
                        </Td>
                        <Td align="center">
                          <ChevronDown size={15}
                            className={`inline text-[var(--text-muted)] transition-transform ${open ? 'rotate-180' : ''}`} />
                        </Td>
                      </tr>
                      <AnimatePresence initial={false}>
                        {open && (
                          <tr>
                            <td colSpan={columns.length + 3} className="p-0">
                              <MotionDiv
                                initial={{ height: 0, opacity: 0 }}
                                animate={{ height: 'auto', opacity: 1 }}
                                exit={{ height: 0, opacity: 0 }}
                                className="overflow-hidden"
                              >
                                <Breakdown row={row} columns={columns} />
                              </MotionDiv>
                            </td>
                          </tr>
                        )}
                      </AnimatePresence>
                    </React.Fragment>
                  );
                })}
              </tbody>
            </TableShell>
            <Pager {...paged} label="people" />
          </>
        )}
      </Section>

      <AnimatePresence>
        {showAttendance && (
          <AttendanceModal key="attendance" companyId={companyId} period={period}
            onClose={() => setShowAttendance(false)}
            onImported={() => { setNotice('Attendance imported. Punctuality is recomputed on the next read.'); reload(); }} />
        )}
        {showCreateTask && (
          <CreateTaskModal key="create-task" companyId={companyId} period={period}
            people={rows} columns={columns}
            onClose={() => setShowCreateTask(false)}
            onCreated={(name, tuned) => {
              setShowCreateTask(false);
              setNotice(`Task created for ${name}${tuned ? ', and their IRM column saved' : ''}.`);
              reload();
            }} />
        )}
      </AnimatePresence>
    </div>
  );
};

export default IRMPage;
