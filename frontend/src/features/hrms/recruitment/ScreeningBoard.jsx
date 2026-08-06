import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ClipboardCheck, Search, X, AlertTriangle, CheckCircle2, PauseCircle, XCircle, Forward,
  Eye, Copy as CopyIcon,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { getCandidates, screenCandidates, getEmployees } from '../../../services/hrmsApi';

/**
 * HRMS ▸ screening board.
 *
 * Triage: shortlist, review, hold, mark duplicate, reject or forward — one candidate or a
 * hundred.
 *
 * The server returns `{moved, skipped}` and this screen shows BOTH. Partial success is the
 * normal case, not an error: a batch of 50 where 3 sit at an incompatible stage should move
 * the 47 and say which 3 blocked and why. Reporting only "done" would hide a real problem.
 */

const TABS = [
  { key: 'to-screen', label: 'To screen',
    statuses: ['Applied', 'Under Review'] },
  { key: 'assigned',  label: 'Assigned to me', statuses: null },
  { key: 'all',       label: 'All applicants', statuses: null },
];

const ACTIONS = [
  { key: 'shortlist', label: 'Shortlist', icon: CheckCircle2 },
  { key: 'review',    label: 'Review',    icon: Eye },
  { key: 'hold',      label: 'Hold',      icon: PauseCircle },
  { key: 'duplicate', label: 'Duplicate', icon: CopyIcon },
  { key: 'forward',   label: 'Forward',   icon: Forward,  needsRecipient: true },
  { key: 'reject',    label: 'Reject',    icon: XCircle,  needsRemark: true },
];

const ScreeningBoard = () => {
  const { can, scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('to-screen');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState(() => new Set());
  const [modal, setModal] = useState(null);      // {action, needsRemark, needsRecipient}
  const [remarks, setRemarks] = useState('');
  const [recipient, setRecipient] = useState('');
  const [people, setPeople] = useState([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const canScreen = can(CAP.CANDIDATE_SCREEN);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getCandidates({ ...scope, limit: 500 });
      setRows(data?.candidates || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load applicants.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!companyId) return;
    getEmployees({ ...scope, limit: 500 })
      .then(({ data }) => setPeople(data?.employees || []))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  const visible = useMemo(() => {
    const tabDef = TABS.find((t) => t.key === tab);
    let out = rows;
    if (tabDef?.statuses) {
      out = out.filter((c) => tabDef.statuses.includes(c.application_status));
    } else if (tab === 'assigned') {
      out = out.filter((c) => !!c.assigned_recruiter_id);
    }
    const q = search.trim().toLowerCase();
    if (q) {
      out = out.filter((c) =>
        [c.candidate_name, c.uk, c.can_email, c.can_contact]
          .some((v) => (v || '').toLowerCase().includes(q)));
    }
    return out;
  }, [rows, tab, search]);

  const toggle = (uk) => setSelected((s) => {
    const next = new Set(s);
    if (next.has(uk)) next.delete(uk); else next.add(uk);
    return next;
  });

  const toggleAll = () => setSelected((s) =>
    s.size === visible.length ? new Set() : new Set(visible.map((c) => c.uk)));

  const openAction = (action) => {
    const def = ACTIONS.find((a) => a.key === action);
    setRemarks('');
    setRecipient('');
    setResult(null);
    if (def.needsRemark || def.needsRecipient) setModal(def);
    else run(action);
  };

  const run = async (action, extra = {}) => {
    setBusy(true);
    try {
      const { data } = await screenCandidates({
        uks: Array.from(selected), action, ...extra,
      }, scope);
      // Show both halves — a silent partial success is how a recruiter loses track of
      // candidates that did not actually move.
      if (data.skipped_count) {
        setResult(data);
      } else {
        showSuccess(`${data.moved_count} candidate(s) updated`);
        setModal(null);
      }
      setSelected(new Set());
      await load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'That action could not be completed.');
    } finally {
      setBusy(false);
    }
  };

  const stats = useMemo(() => ({
    toScreen: rows.filter((c) => ['Applied', 'Under Review'].includes(c.application_status)).length,
    shortlisted: rows.filter((c) => c.application_status === 'Shortlisted').length,
    hold: rows.filter((c) => c.application_status === 'On Hold').length,
    rejected: rows.filter((c) => ['Rejected', 'Duplicate'].includes(c.application_status)).length,
  }), [rows]);

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={ClipboardCheck}
        title="Screening"
        subtitle="Triage incoming applicants — one at a time or in bulk."
        actions={<HrmsScopeBar />}
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[['To screen', stats.toScreen], ['Shortlisted', stats.shortlisted],
          ['On hold', stats.hold], ['Not proceeding', stats.rejected]].map(([label, value]) => (
          <div key={label} className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
            <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{label}</p>
            <p className="mt-1.5 text-[20px] font-bold text-[var(--text-main)]">{value}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-[var(--border)] overflow-hidden">
          {TABS.map((t) => (
            <button key={t.key} type="button" onClick={() => { setTab(t.key); setSelected(new Set()); }}
              className={`h-9 px-3.5 text-[12px] font-bold ${
                tab === t.key ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                              : 'text-[var(--text-muted)]'}`}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="relative flex-1 min-w-[200px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search applicants…"
            className="w-full h-9 pl-9 pr-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]" />
        </div>
      </div>

      {loading ? (
        <HrmsLoading label="Loading applicants…" />
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : visible.length === 0 ? (
        <HrmsEmpty icon={ClipboardCheck} title="Nothing to screen"
          hint={tab === 'to-screen'
            ? 'No applicants are waiting to be screened.'
            : 'Try another tab or clear the search.'} />
      ) : (
        <div className="rounded-xl border border-[var(--border)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[760px]">
            <thead className="bg-[var(--input-bg)] text-[var(--text-muted)]">
              <tr>
                <th className="px-3 py-2.5 w-10">
                  {canScreen && (
                    <input type="checkbox" aria-label="Select all"
                      checked={selected.size > 0 && selected.size === visible.length}
                      onChange={toggleAll} />
                  )}
                </th>
                {['Candidate', 'Role / Requisition', 'Source', 'Stage', 'Assigned'].map((h) => (
                  <th key={h} className="text-left px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((c) => (
                <tr key={c.uk} className="border-t border-[var(--border)]">
                  <td className="px-3 py-2.5">
                    {canScreen && (
                      <input type="checkbox" aria-label={`Select ${c.candidate_name}`}
                        checked={selected.has(c.uk)} onChange={() => toggle(c.uk)} />
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <span className="font-semibold text-[var(--text-main)]">{c.candidate_name}</span>
                      {c.duplicate_flag && (
                        <span title="Shares an email or phone with another applicant"
                          className="px-1 rounded bg-[var(--accent-red-bg)] text-[var(--accent-red)] text-[9.5px] font-bold">
                          DUP
                        </span>
                      )}
                    </div>
                    <span className="text-[11px] text-[var(--text-muted)]">
                      {c.can_email || c.can_contact || c.uk}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">{c.request_no || '—'}</td>
                  <td className="px-4 py-2.5 text-[var(--text-main)]">{c.source || '—'}</td>
                  <td className="px-4 py-2.5 text-[var(--text-main)]">{c.application_status}</td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">
                    {c.assigned_recruiter_name || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {canScreen && selected.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-[var(--text-main)] shadow-2xl">
          <span className="text-[12px] font-bold text-[var(--bg-card)]">{selected.size} selected</span>
          <span className="w-px h-5 bg-white/20" />
          {ACTIONS.map((a) => (
            <button key={a.key} type="button" disabled={busy} onClick={() => openAction(a.key)}
              className="px-2.5 py-1 rounded-lg bg-white/10 text-[var(--bg-card)] text-[11.5px] font-bold flex items-center gap-1 hover:bg-white/20 disabled:opacity-50">
              <a.icon size={12} /> {a.label}
            </button>
          ))}
          <button type="button" onClick={() => setSelected(new Set())}
            className="p-1 rounded-lg text-white/60 hover:text-white">
            <X size={14} />
          </button>
        </div>
      )}

      {(modal || result) && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
              <h2 className="text-[15px] font-bold text-[var(--text-main)]">
                {result ? 'Partly applied' : `${modal.label} ${selected.size} candidate(s)`}
              </h2>
              <button type="button" onClick={() => { setModal(null); setResult(null); }}
                className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
                <X size={17} />
              </button>
            </div>

            {result ? (
              <div className="p-5 space-y-3">
                <p className="text-[13px] text-[var(--text-main)]">
                  <strong>{result.moved_count}</strong> updated,{' '}
                  <strong>{result.skipped_count}</strong> skipped.
                </p>
                <div className="p-3 rounded-lg bg-[var(--input-bg)] max-h-48 overflow-y-auto space-y-1">
                  {result.skipped.map((s) => (
                    <p key={s.uk} className="text-[11.5px] text-[var(--text-muted)]">
                      <span className="font-mono">{s.uk}</span> — {s.reason}
                    </p>
                  ))}
                </div>
                <p className="text-[11.5px] text-[var(--text-muted)] flex items-start gap-1.5">
                  <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                  Skipped candidates were at a stage this action cannot be applied from.
                </p>
                <div className="flex justify-end">
                  <button type="button" onClick={() => { setModal(null); setResult(null); }}
                    className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold">
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <div className="p-5 space-y-3">
                {modal.needsRecipient && (
                  <div>
                    <label htmlFor="s-to" className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">
                      Forward to *
                    </label>
                    <select id="s-to" value={recipient} onChange={(e) => setRecipient(e.target.value)}
                      className="w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]">
                      <option value="">Select a colleague…</option>
                      {people.map((p) => (
                        <option key={p.user_id} value={p.user_id}>{p.name}</option>
                      ))}
                    </select>
                    <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                      Forwarding assigns an owner — it does not change the candidate&apos;s stage.
                    </p>
                  </div>
                )}
                <div>
                  <label htmlFor="s-remarks" className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">
                    {modal.needsRemark ? 'Reason *' : 'Note'}
                  </label>
                  <textarea id="s-remarks" rows={3} value={remarks}
                    onChange={(e) => setRemarks(e.target.value)}
                    placeholder={modal.needsRemark ? 'Why is this candidate not proceeding?' : 'Optional'}
                    className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] resize-none" />
                </div>
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={() => setModal(null)}
                    className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
                    Cancel
                  </button>
                  <button type="button" disabled={busy
                      || (modal.needsRemark && !remarks.trim())
                      || (modal.needsRecipient && !recipient)}
                    onClick={() => run(modal.key, {
                      remarks: remarks.trim() || null,
                      forward_to_id: recipient || null,
                    })}
                    className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
                    {busy ? 'Working…' : `Confirm ${modal.label.toLowerCase()}`}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ScreeningBoard;
