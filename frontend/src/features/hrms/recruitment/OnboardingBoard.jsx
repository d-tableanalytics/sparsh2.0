import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  UserPlus, Plus, X, Copy, Check, ShieldCheck, ShieldAlert, BadgeCheck, Search,
  Paperclip, CalendarDays, Link2,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getOnboardings, getOnboardableCandidates, getOnboarding, startOnboarding,
  updateOnboarding, updateOnboardingBg, verifyOnboardingDocuments,
  setOnboardingChecklist, generateEmployeeId, onboardUrlFor,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ onboarding — where a candidate becomes an employee.
 *
 * Two things this screen is careful about:
 *
 *  • **The three system-owned checklist items** (`employee_id`, `documents_verified`,
 *    `bg_cleared`) are rendered as read-only with an explanation. The API refuses to set
 *    them by hand; showing a checkbox that always 409s would be a lie.
 *  • **Generate Employee ID says WHY it is disabled.** The server returns `id_blockers` as
 *    prose, so the button never sits greyed out with no explanation — the single most
 *    common source of "the system is broken" tickets.
 */

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';
const BTN = 'h-9 px-3.5 rounded-lg text-[12.5px] font-bold transition-colors disabled:opacity-50 disabled:cursor-not-allowed';

const STATUS_TONE = {
  'Pre-Onboarding': 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  Onboarding: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Completed: 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
};

const BG_TONE = {
  Pending: 'text-[var(--text-muted)]',
  'In Progress': 'text-[var(--accent-indigo)]',
  Cleared: 'text-[var(--accent-green,var(--accent-indigo))]',
  Flagged: 'text-[var(--accent-red)]',
};

const SYSTEM_ITEMS = new Set(['employee_id', 'documents_verified', 'bg_cleared']);

const fmtDate = (v) => (v ? new Date(v).toLocaleDateString('en-IN', {
  day: '2-digit', month: 'short', year: 'numeric',
}) : '—');

// ── Start modal ───────────────────────────────────────────────
const StartModal = ({ onClose, onStarted }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [people, setPeople] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ uk: '', joining_date: '' });

  useEffect(() => {
    getOnboardableCandidates(scope)
      .then(({ data }) => setPeople(Array.isArray(data) ? data : data?.candidates || []))
      .catch((err) => showError(err?.response?.data?.detail || 'Could not load candidates.'))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    if (!form.uk) return showError('Select a candidate.');
    setSaving(true);
    try {
      const { data } = await startOnboarding(form, scope);
      showSuccess(`Onboarding ${data.onb_no} opened`);
      onStarted(data.onb_no);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not start onboarding.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <h2 className="text-[15px] font-bold text-[var(--text-main)]">Start onboarding</h2>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>
        <div className="p-5 space-y-3">
          <div>
            <label className={LABEL} htmlFor="ob-uk">New hire *</label>
            {loading ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Loading…</p>
            ) : people.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                Nobody is ready to onboard. A candidate becomes onboardable once they have{' '}
                <strong>accepted their offer</strong> — we ask for PAN, Aadhaar and bank
                details, so we do not collect them from someone who may still say no.
              </p>
            ) : (
              <select id="ob-uk" value={form.uk} className={FIELD}
                onChange={(e) => setForm((f) => ({ ...f, uk: e.target.value }))}>
                <option value="">Select a candidate…</option>
                {people.map((p) => (
                  <option key={p.uk} value={p.uk}>{p.candidate_name}</option>
                ))}
              </select>
            )}
          </div>
          <div>
            <label className={LABEL} htmlFor="ob-join">Joining date</label>
            <input id="ob-join" type="date" className={FIELD} value={form.joining_date}
              onChange={(e) => setForm((f) => ({ ...f, joining_date: e.target.value }))} />
            <p className="text-[11.5px] text-[var(--text-muted)] mt-1">
              Leave blank to use the date from the accepted offer.
            </p>
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose}
            className={`${BTN} border border-[var(--border)] text-[var(--text-muted)]`}>
            Cancel
          </button>
          <button type="button" onClick={submit} disabled={saving || people.length === 0}
            className={`${BTN} bg-[var(--accent-indigo)] text-white`}>
            {saving ? 'Starting…' : 'Start onboarding'}
          </button>
        </div>
      </div>
    </div>
  );
};

// ── Detail panel ──────────────────────────────────────────────
const Detail = ({ onbNo, onClose, onChanged }) => {
  const { scope, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [row, setRow] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const mayWrite = can(CAP.ONBOARDING_WRITE);
  const mayGenerate = can(CAP.ONBOARDING_GENERATE_ID);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await getOnboarding(onbNo, scope);
      setRow(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this onboarding.');
    } finally {
      setLoading(false);
    }
  }, [onbNo, scope]);

  useEffect(() => { load(); }, [load]);

  const run = async (fn, okMessage) => {
    setBusy(true);
    try {
      const { data } = await fn();
      setRow(data);
      if (okMessage) showSuccess(okMessage);
      onChanged();
    } catch (err) {
      showError(err?.response?.data?.detail || 'That could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  const copyLink = () => {
    navigator.clipboard?.writeText(onboardUrlFor(row.access_code));
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const blockers = row?.id_blockers || [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm">
      <div className="w-full max-w-2xl h-full bg-[var(--bg-card)] border-l border-[var(--border)] shadow-xl flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)] shrink-0">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold text-[var(--text-main)] truncate">
              {row?.candidate_name || onbNo}
            </h2>
            <p className="text-[11.5px] text-[var(--text-muted)]">
              {onbNo}{row?.designation ? ` · ${row.designation}` : ''}
            </p>
          </div>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {loading && <HrmsLoading label="Loading onboarding…" />}
          {error && !loading && <HrmsError message={error} onRetry={load} />}

          {row && !loading && (
            <>
              {/* Employee ID — the headline once issued */}
              {row.employee_id && (
                <div className="rounded-xl border border-[var(--border)] bg-[var(--accent-indigo-bg)] px-4 py-3 flex items-center gap-3">
                  <BadgeCheck size={20} className="text-[var(--accent-indigo)] shrink-0" />
                  <div>
                    <p className="text-[13px] font-bold text-[var(--text-main)]">
                      Employee ID {row.employee_id}
                    </p>
                    <p className="text-[11.5px] text-[var(--text-muted)]">
                      They now appear in the employee directory. Link a login account from
                      there once it exists.
                    </p>
                  </div>
                </div>
              )}

              {/* The pre-onboarding link */}
              <section className="space-y-2">
                <p className={LABEL}>Pre-onboarding form</p>
                <div className="flex items-center gap-2">
                  <input readOnly value={row.access_code ? onboardUrlFor(row.access_code) : ''}
                    className={`${FIELD} font-mono text-[11.5px]`} />
                  <button type="button" onClick={copyLink}
                    className={`${BTN} border border-[var(--border)] text-[var(--text-muted)] shrink-0 flex items-center gap-1.5`}>
                    {copied ? <Check size={14} /> : <Copy size={14} />}
                    {copied ? 'Copied' : 'Copy'}
                  </button>
                </div>
                <p className="text-[11.5px] text-[var(--text-muted)]">
                  Status: <strong>{row.pre_status}</strong>
                  {row.submitted_at ? ` · submitted ${fmtDate(row.submitted_at)}` : ''}
                </p>
                {row.pre_status === 'Submitted' && mayWrite && (
                  <button type="button" disabled={busy}
                    onClick={() => run(() => verifyOnboardingDocuments(onbNo, scope),
                      'Documents verified')}
                    className={`${BTN} bg-[var(--accent-indigo)] text-white flex items-center gap-1.5`}>
                    <ShieldCheck size={14} /> Mark documents verified
                  </button>
                )}
              </section>

              {/* Joining details */}
              <section className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className={LABEL} htmlFor="d-join">Joining date</label>
                  <input id="d-join" type="date" className={FIELD} disabled={!mayWrite || busy}
                    value={row.joining_date || ''}
                    onChange={(e) => run(
                      () => updateOnboarding(onbNo, { joining_date: e.target.value }, scope))} />
                </div>
                <div>
                  <label className={LABEL} htmlFor="d-bg">Background verification</label>
                  <select id="d-bg" className={FIELD} disabled={!mayWrite || busy}
                    value={row.bg_verification || 'Pending'}
                    onChange={(e) => run(
                      () => updateOnboardingBg(onbNo, { bg_verification: e.target.value }, scope),
                      'Background check updated')}>
                    {['Pending', 'In Progress', 'Cleared', 'Flagged'].map((v) => (
                      <option key={v} value={v}>{v}</option>
                    ))}
                  </select>
                  {row.bg_verification === 'Flagged' && (
                    <p className="text-[11.5px] text-[var(--accent-red)] mt-1 flex items-center gap-1">
                      <ShieldAlert size={12} /> An Employee ID cannot be issued while flagged.
                    </p>
                  )}
                </div>
              </section>

              {/* Documents */}
              <section>
                <p className={LABEL}>Documents ({(row.documents || []).length})</p>
                {(row.documents || []).length === 0 ? (
                  <p className="text-[12.5px] text-[var(--text-muted)]">
                    Nothing uploaded yet.
                  </p>
                ) : (
                  <ul className="space-y-1.5">
                    {row.documents.map((d, i) => (
                      <li key={`${d.name}-${i}`}
                        className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
                        <Paperclip size={13} className="text-[var(--text-muted)] shrink-0" />
                        <span className="truncate">{d.name}</span>
                        <span className="text-[11px] text-[var(--text-muted)] shrink-0">
                          {d.source === 'hr' ? 'added by HR' : 'from candidate'}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Checklist */}
              <section>
                <div className="flex items-center justify-between mb-2">
                  <p className={`${LABEL} mb-0`}>Joining checklist</p>
                  <p className="text-[11.5px] font-bold text-[var(--text-muted)]">
                    {row.progress?.done ?? 0}/{row.progress?.total ?? 0}
                  </p>
                </div>
                <div className="h-1.5 rounded-full bg-[var(--input-bg)] overflow-hidden mb-3">
                  <div className="h-full bg-[var(--accent-indigo)] transition-all"
                    style={{ width: `${row.progress?.percent ?? 0}%` }} />
                </div>
                <ul className="space-y-1">
                  {(row.checklist || []).map((item) => {
                    const owned = SYSTEM_ITEMS.has(item.key);
                    return (
                      <li key={item.key}
                        className="flex items-start gap-2.5 py-1.5 px-2 rounded-lg hover:bg-[var(--input-bg)]">
                        <input type="checkbox" checked={!!item.done}
                          disabled={owned || !mayWrite || busy}
                          onChange={(e) => run(() => setOnboardingChecklist(
                            onbNo, { key: item.key, done: e.target.checked }, scope))}
                          className="mt-0.5 accent-[var(--accent-indigo)] disabled:opacity-60"
                          aria-label={item.label} />
                        <div className="min-w-0">
                          <p className={`text-[12.5px] ${item.done ? 'text-[var(--text-muted)] line-through' : 'text-[var(--text-main)]'}`}>
                            {item.label}
                          </p>
                          {owned && (
                            <p className="text-[11px] text-[var(--text-muted)]">
                              Set automatically — it follows the action that achieves it.
                            </p>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>

              {/* The handover */}
              {mayGenerate && !row.employee_id && (
                <section className="rounded-xl border border-[var(--border)] p-4 space-y-2">
                  <p className="text-[13px] font-bold text-[var(--text-main)]">
                    Create the employee record
                  </p>
                  <p className="text-[11.5px] text-[var(--text-muted)]">
                    Issues the Employee ID and adds them to the directory. This cannot be
                    undone.
                  </p>
                  {blockers.length > 0 && (
                    <ul className="text-[11.5px] text-[var(--accent-red)] space-y-0.5">
                      {blockers.map((b) => <li key={b}>• {b}</li>)}
                    </ul>
                  )}
                  <button type="button" disabled={busy || blockers.length > 0}
                    onClick={() => run(() => generateEmployeeId(onbNo, scope),
                      'Employee ID issued')}
                    className={`${BTN} bg-[var(--accent-indigo)] text-white flex items-center gap-1.5`}>
                    <BadgeCheck size={14} /> Generate Employee ID
                  </button>
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

// ── Board ─────────────────────────────────────────────────────
const OnboardingBoard = () => {
  const { scope, can, companyId } = useHrms();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [starting, setStarting] = useState(false);
  const [open, setOpen] = useState(null);

  const mayWrite = can(CAP.ONBOARDING_WRITE);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await getOnboardings({ ...scope, status: status || undefined }, scope);
      setRows(Array.isArray(data) ? data : data?.onboardings || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load onboarding.');
    } finally {
      setLoading(false);
    }
  }, [companyId, status]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return rows;
    return rows.filter((r) => [r.candidate_name, r.onb_no, r.employee_id]
      .some((v) => (v || '').toLowerCase().includes(term)));
  }, [rows, search]);

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={UserPlus}
        title="Onboarding"
        subtitle="Where a candidate becomes an employee"
        actions={mayWrite && (
          <button type="button" onClick={() => setStarting(true)}
            className={`${BTN} bg-[var(--accent-indigo)] text-white flex items-center gap-1.5`}>
            <Plus size={15} /> Start onboarding
          </button>
        )}
      />
      <HrmsScopeBar />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name, ONB number or Employee ID"
            className={`${FIELD} pl-9`} aria-label="Search onboarding" />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className={`${FIELD} w-auto min-w-[160px]`} aria-label="Filter by status">
          <option value="">All statuses</option>
          {['Pre-Onboarding', 'Onboarding', 'Completed'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {loading && <HrmsLoading label="Loading onboarding…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && visible.length === 0 && (
        <HrmsEmpty
          icon={UserPlus}
          title="Nobody is being onboarded"
          hint="Onboarding opens once a candidate accepts their offer."
        />
      )}

      {!loading && !error && visible.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {visible.map((r) => (
            <button key={r.onb_no} type="button" onClick={() => setOpen(r.onb_no)}
              className="text-left rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 hover:border-[var(--accent-indigo)] transition-colors">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[13.5px] font-bold text-[var(--text-main)] truncate">
                    {r.candidate_name}
                  </p>
                  <p className="text-[11.5px] text-[var(--text-muted)]">
                    {r.onb_no}{r.designation ? ` · ${r.designation}` : ''}
                  </p>
                </div>
                <span className={`px-2 py-0.5 rounded-md text-[10.5px] font-bold shrink-0 ${STATUS_TONE[r.status] || ''}`}>
                  {r.status}
                </span>
              </div>

              <div className="mt-3 h-1.5 rounded-full bg-[var(--input-bg)] overflow-hidden">
                <div className="h-full bg-[var(--accent-indigo)]"
                  style={{ width: `${r.progress?.percent ?? 0}%` }} />
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px]">
                <span className="flex items-center gap-1 text-[var(--text-muted)]">
                  <CalendarDays size={12} /> {fmtDate(r.joining_date)}
                </span>
                <span className={`flex items-center gap-1 ${BG_TONE[r.bg_verification] || ''}`}>
                  <ShieldCheck size={12} /> {r.bg_verification}
                </span>
                {r.employee_id && (
                  <span className="flex items-center gap-1 font-bold text-[var(--accent-indigo)]">
                    <Link2 size={12} /> {r.employee_id}
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}

      {starting && (
        <StartModal onClose={() => setStarting(false)}
          onStarted={(no) => { setStarting(false); load(); setOpen(no); }} />
      )}
      {open && (
        <Detail onbNo={open} onClose={() => setOpen(null)} onChanged={load} />
      )}
    </div>
  );
};

export default OnboardingBoard;
