import React, { useCallback, useEffect, useState } from 'react';
import {
  ShieldCheck, Plus, Inbox, CalendarRange, Loader2, AlertTriangle,
  Check, X, Ban, Clock,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import {
  getLeaves, applyLeave, decideLeave, cancelLeave, getLeaveBalance, getLeaveSettings,
} from '../../services/hrmsApi';
import { hasHrmsPermission } from '../../utils/hrmsAccess';
import { Field } from '../../components/hrms/hrmsUi';
import { inputCls, fmtDate } from '../../components/hrms/hrmsStyles';

// HRMS ▸ Leave. Three views: my requests, my balances, and (for approvers) the pending inbox.
//
// The type dropdown is populated from the server's configured types, so the form can only offer
// something the API will accept. Day counting also happens server-side — the count shown after
// submission already excludes weekly offs and public holidays, using the app's existing Holiday
// module rather than a second calendar.

const STATUS_TONE = {
  Pending:   { text: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)', border: 'var(--accent-yellow-border)' },
  Approved:  { text: 'var(--status-active-text)', bg: 'var(--status-active-bg)', border: 'var(--status-active-border)' },
  Rejected:  { text: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)' },
  Cancelled: { text: 'var(--text-muted)', bg: 'var(--input-bg)', border: 'var(--border)' },
};

const LeaveStatus = ({ status }) => {
  const tone = STATUS_TONE[status] || STATUS_TONE.Pending;
  return (
    <span className="inline-block px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest border whitespace-nowrap"
      style={{ color: tone.text, backgroundColor: tone.bg, borderColor: tone.border }}>
      {status}
    </span>
  );
};

const EMPTY_FORM = { leave_type: '', start_date: '', end_date: '', is_half_day: false, reason: '' };

const Leave = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();

  const canApprove = hasHrmsPermission(user, 'attendance', 'read');

  const [tab, setTab] = useState('mine');
  const [settings, setSettings] = useState(null);
  const [mine, setMine] = useState([]);
  const [pending, setPending] = useState([]);
  const [balances, setBalances] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [showApply, setShowApply] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [deciding, setDeciding] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [mineRes, balRes] = await Promise.all([
        getLeaves({ scope: 'mine' }),
        getLeaveBalance(),
      ]);
      setMine(mineRes.data || []);
      setBalances(balRes.data?.balances || []);
      if (canApprove) {
        const pendRes = await getLeaves({ scope: 'pending' });
        setPending(pendRes.data || []);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load leave');
    } finally {
      setLoading(false);
    }
  }, [canApprove]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    getLeaveSettings()
      .then((r) => {
        setSettings(r.data);
        const first = (r.data.types || []).find((t) => t.active);
        if (first) setForm((f) => ({ ...f, leave_type: f.leave_type || first.code }));
      })
      .catch(() => {});
  }, []);

  const activeTypes = (settings?.types || []).filter((t) => t.active);
  const selectedType = activeTypes.find((t) => t.code === form.leave_type);

  const submit = async () => {
    if (!form.leave_type) { showError('Choose a leave type'); return; }
    if (!form.start_date || !form.end_date) { showError('Choose the dates'); return; }
    if (!form.reason.trim()) { showError('A reason is required'); return; }
    setSaving(true);
    try {
      const res = await applyLeave(form);
      showSuccess(`Applied for ${res.data.days} day(s) of ${res.data.leaveTypeName}`);
      setForm({ ...EMPTY_FORM, leave_type: form.leave_type });
      setShowApply(false);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to apply');
    } finally {
      setSaving(false);
    }
  };

  const decide = async (row, status) => {
    setDeciding(row.id);
    try {
      await decideLeave(row.id, { status });
      showSuccess(`${row.applicantName || 'Request'} — ${status.toLowerCase()}`);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update request');
    } finally {
      setDeciding(null);
    }
  };

  const withdraw = async (row) => {
    setDeciding(row.id);
    try {
      await cancelLeave(row.id);
      showSuccess('Request withdrawn');
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to withdraw');
    } finally {
      setDeciding(null);
    }
  };

  const TABS = [
    { key: 'mine', label: 'My leave', icon: CalendarRange },
    ...(canApprove ? [{ key: 'pending', label: `Approvals${pending.length ? ` (${pending.length})` : ''}`, icon: Inbox }] : []),
  ];

  return (
    <div className="p-6 sm:p-8 flex flex-col gap-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
            <ShieldCheck size={20} />
          </span>
          <div>
            <h1 className="text-xl sm:text-2xl font-black tracking-tight text-[var(--text-main)] leading-tight">
              Leave
            </h1>
            <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
              Applications, approvals and balances
            </p>
          </div>
        </div>
        <button onClick={() => setShowApply((v) => !v)}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[12px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] transition-all">
          <Plus size={15} /> Apply for leave
        </button>
      </div>

      {/* Balances */}
      {balances.length > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {balances.map((b) => (
            <div key={b.leaveType}
              className="p-4 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
              <div className="flex items-baseline gap-1.5">
                <span className="text-xl font-black text-[var(--text-main)] leading-none"
                  style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {b.paid ? b.remaining : '∞'}
                </span>
                {b.paid && (
                  <span className="text-[11px] font-bold text-[var(--text-muted)]"
                    style={{ fontVariantNumeric: 'tabular-nums' }}>
                    / {b.entitled}
                  </span>
                )}
              </div>
              <div className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] mt-1 truncate">
                {b.name}
              </div>
              {b.paid && (
                <div className="mt-2 h-1.5 rounded-full bg-[var(--input-bg)] overflow-hidden">
                  <div className="h-full rounded-full transition-all"
                    style={{
                      width: `${b.entitled ? Math.min(100, (b.used / b.entitled) * 100) : 0}%`,
                      backgroundColor: 'var(--accent-indigo)',
                    }} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Apply form */}
      {showApply && (
        <div className="p-5 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-col gap-3.5">
          <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)]">
            New request
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3.5">
            <Field label="Type" required>
              <select className={`${inputCls} cursor-pointer`} value={form.leave_type}
                onChange={(e) => setForm({ ...form, leave_type: e.target.value, is_half_day: false })}>
                {activeTypes.map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.name}{t.paid ? '' : ' (unpaid)'}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="From" required>
              <input type="date" className={inputCls} value={form.start_date}
                onChange={(e) => setForm({
                  ...form,
                  start_date: e.target.value,
                  // Keep the range valid as you pick: an end before the start is never useful.
                  end_date: form.end_date && form.end_date < e.target.value ? e.target.value : form.end_date,
                })} />
            </Field>
            <Field label="To" required>
              <input type="date" className={inputCls} value={form.end_date} min={form.start_date}
                onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
            </Field>
            <Field label="Half day">
              <label className={`${inputCls} flex items-center gap-2 cursor-pointer ${
                selectedType && !selectedType.allow_half_day ? 'opacity-50' : ''}`}>
                <input type="checkbox" checked={form.is_half_day}
                  disabled={selectedType && !selectedType.allow_half_day}
                  onChange={(e) => setForm({
                    ...form,
                    is_half_day: e.target.checked,
                    // A half day is a single date by definition.
                    end_date: e.target.checked ? form.start_date : form.end_date,
                  })}
                  className="w-3.5 h-3.5 accent-[var(--accent-indigo)]" />
                <span className="text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                  {selectedType && !selectedType.allow_half_day ? 'Not allowed' : 'Half day'}
                </span>
              </label>
            </Field>
          </div>
          <Field label="Reason" required>
            <textarea rows={2} className={`${inputCls} resize-y`} value={form.reason}
              placeholder="Why you need the time off."
              onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          </Field>
          <p className="text-[11px] font-medium text-[var(--text-muted)]">
            Weekly offs and public holidays in the range are not counted.
          </p>
          <div className="flex items-center justify-end gap-2.5">
            <button onClick={() => setShowApply(false)}
              className="px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
              Cancel
            </button>
            <button onClick={submit} disabled={saving}
              className="flex items-center gap-2 px-5 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
              {saving && <Loader2 size={13} className="animate-spin" />} Submit
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
          style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-[11px] font-black uppercase tracking-widest transition-colors border ${
              tab === t.key
                ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]'
                : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'
            }`}>
            <t.icon size={14} /> {t.label}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full" style={{ minWidth: 820 }}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                {(tab === 'pending'
                  ? ['Applicant', 'Type', 'Dates', 'Days', 'Reason', '']
                  : ['Type', 'Dates', 'Days', 'Reason', 'Status', '']
                ).map((h, i) => (
                  <th key={i}
                    className="text-left px-4 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={6} className="px-4 py-12 text-center">
                  <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
                    <Loader2 size={16} className="animate-spin" /> Loading…
                  </span>
                </td></tr>
              )}

              {!loading && tab === 'mine' && mine.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-12 text-center">
                  <p className="text-[13px] font-bold text-[var(--text-main)]">No leave requests yet.</p>
                </td></tr>
              )}

              {!loading && tab === 'mine' && mine.map((r) => (
                <tr key={r.id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <td className="px-4 py-3 text-[12.5px] font-black text-[var(--text-main)]">
                    {r.leaveTypeName}
                    {!r.paid && <span className="ml-1.5 text-[10px] font-bold text-[var(--text-muted)]">unpaid</span>}
                  </td>
                  <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]">
                    {fmtDate(r.startDate)}{r.startDate !== r.endDate ? ` → ${fmtDate(r.endDate)}` : ''}
                  </td>
                  <td className="px-4 py-3 text-[12px] font-black text-[var(--text-main)]"
                    style={{ fontVariantNumeric: 'tabular-nums' }}>{r.days}</td>
                  <td className="px-4 py-3 text-[12px] font-medium text-[var(--text-muted)] max-w-[240px] truncate">
                    {r.reason}
                  </td>
                  <td className="px-4 py-3">
                    <LeaveStatus status={r.status} />
                    {r.remark && (
                      <div className="text-[10.5px] font-medium text-[var(--text-muted)] mt-1">{r.remark}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {(r.status === 'Pending' || r.status === 'Approved') && (
                      <button onClick={() => withdraw(r)} disabled={deciding === r.id}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--border)] text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:border-[var(--accent-red)] disabled:opacity-50 transition-colors">
                        <Ban size={11} /> Withdraw
                      </button>
                    )}
                  </td>
                </tr>
              ))}

              {!loading && tab === 'pending' && pending.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-12 text-center">
                  <p className="text-[13px] font-bold text-[var(--text-main)]">Nothing waiting on you.</p>
                  <p className="text-[12px] font-medium text-[var(--text-muted)] mt-1">
                    Requests appear here when your reports apply for leave.
                  </p>
                </td></tr>
              )}

              {!loading && tab === 'pending' && pending.map((r) => (
                <tr key={r.id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <td className="px-4 py-3 text-[12.5px] font-black text-[var(--text-main)]">
                    {r.applicantName || r.userId}
                  </td>
                  <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]">
                    {r.leaveTypeName}
                  </td>
                  <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]">
                    {fmtDate(r.startDate)}{r.startDate !== r.endDate ? ` → ${fmtDate(r.endDate)}` : ''}
                  </td>
                  <td className="px-4 py-3 text-[12px] font-black text-[var(--text-main)]"
                    style={{ fontVariantNumeric: 'tabular-nums' }}>{r.days}</td>
                  <td className="px-4 py-3 text-[12px] font-medium text-[var(--text-muted)] max-w-[220px] truncate">
                    {r.reason}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1.5">
                      <button onClick={() => decide(r, 'Approved')} disabled={deciding === r.id}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-white text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
                        style={{ backgroundColor: 'var(--accent-green)' }}>
                        <Check size={11} /> Approve
                      </button>
                      <button onClick={() => decide(r, 'Rejected')} disabled={deciding === r.id}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-white text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
                        style={{ backgroundColor: 'var(--accent-red)' }}>
                        <X size={11} /> Reject
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="flex items-start gap-2 text-[11px] font-medium text-[var(--text-muted)]">
        <Clock size={13} className="mt-0.5 shrink-0" />
        Requests route to your reporting manager. Balance is consumed only when a paid request is
        approved, and returned if it is later withdrawn.
      </p>
    </div>
  );
};

export default Leave;
