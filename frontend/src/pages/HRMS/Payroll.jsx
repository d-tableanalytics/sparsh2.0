import React, { useCallback, useEffect, useState } from 'react';
import {
  Wallet, Play, Lock, Loader2, AlertTriangle, ChevronLeft, ChevronRight,
  FileText, Users, TrendingDown, ShieldCheck, X, Info,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import {
  getPayroll, runPayroll, lockPayroll, getMyPayslip,
} from '../../services/hrmsApi';
import { hasHrmsPermission } from '../../utils/hrmsAccess';
import { StatTile } from '../../components/hrms/hrmsUi';

// HRMS ▸ Payroll.
//
// The screen mirrors what the backend guarantees: a run is COMPUTED and STORED explicitly, a
// draft can be recomputed, and locking freezes it. Nothing here triggers a calculation by
// merely loading the page — the reference project's payroll GET recomputes and mutates the
// leave ledger, so refreshing could change someone's balance.
//
// Employees without the payroll permission see only their own payslip, and only once the
// period is locked.

const money = (n) => `₹ ${Number(n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const monthLabel = (y, m) =>
  new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });

const Payroll = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();

  const canRead = hasHrmsPermission(user, 'payroll', 'read');
  const canRun = hasHrmsPermission(user, 'payroll', 'update');

  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);

  const [data, setData] = useState(null);
  const [mySlip, setMySlip] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      if (canRead) {
        const res = await getPayroll({ year, month });
        setData(res.data);
      } else {
        const res = await getMyPayslip({ year, month });
        setMySlip(res.data);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load payroll');
    } finally {
      setLoading(false);
    }
  }, [year, month, canRead]);

  useEffect(() => { load(); }, [load]);

  const shift = (delta) => {
    const d = new Date(year, month - 1 + delta, 1);
    setYear(d.getFullYear());
    setMonth(d.getMonth() + 1);
  };

  const doRun = async () => {
    setBusy('run');
    try {
      const res = await runPayroll({ year, month });
      showSuccess(`Computed ${res.data.payslips.length} payslip(s)`);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Payroll run failed');
    } finally {
      setBusy('');
    }
  };

  const doLock = async () => {
    setBusy('lock');
    try {
      await lockPayroll({ year, month });
      showSuccess(`${monthLabel(year, month)} locked`);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to lock');
    } finally {
      setBusy('');
    }
  };

  const run = data?.run;
  const slips = data?.payslips ?? [];
  const totals = run?.totals ?? {};
  const isLocked = run?.status === 'locked';

  return (
    <div className="p-6 sm:p-8 flex flex-col gap-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
            <Wallet size={20} />
          </span>
          <div>
            <h1 className="text-xl sm:text-2xl font-black tracking-tight text-[var(--text-main)] leading-tight">
              Payroll
            </h1>
            <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
              Monthly runs, payslips and deductions
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button onClick={() => shift(-1)}
            className="p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors"
            aria-label="Previous month">
            <ChevronLeft size={15} />
          </button>
          <span className="text-[12.5px] font-black text-[var(--text-main)] min-w-[140px] text-center">
            {monthLabel(year, month)}
          </span>
          <button onClick={() => shift(1)}
            className="p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors"
            aria-label="Next month">
            <ChevronRight size={15} />
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
          style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* ── Employee view: own payslip only ── */}
      {!canRead && (
        loading ? (
          <div className="flex items-center justify-center gap-2.5 py-16 text-[var(--text-muted)]">
            <Loader2 size={18} className="animate-spin" />
            <span className="text-[13px] font-bold">Loading…</span>
          </div>
        ) : mySlip?.payslip ? (
          <PayslipCard slip={mySlip.payslip} />
        ) : (
          <div className="p-8 rounded-2xl bg-[var(--bg-card)] border border-dashed border-[var(--border)] text-center">
            <FileText size={26} className="mx-auto text-[var(--text-muted)] opacity-50 mb-2" />
            <p className="text-[13px] font-bold text-[var(--text-main)]">
              No payslip for {monthLabel(year, month)} yet.
            </p>
            <p className="text-[12px] font-medium text-[var(--text-muted)] mt-1 max-w-md mx-auto">
              Payslips become visible once the month has been finalised by HR.
            </p>
          </div>
        )
      )}

      {/* ── HR view ── */}
      {canRead && (
        <>
          <div className="flex flex-wrap items-center gap-2.5">
            {run ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest border"
                style={isLocked
                  ? { color: 'var(--status-active-text)', backgroundColor: 'var(--status-active-bg)', borderColor: 'var(--status-active-border)' }
                  : { color: 'var(--accent-yellow)', backgroundColor: 'var(--accent-yellow-bg)', borderColor: 'var(--accent-yellow-border)' }}>
                {isLocked ? <><Lock size={11} /> Locked</> : <>Draft</>}
              </span>
            ) : (
              <span className="text-[11.5px] font-bold text-[var(--text-muted)]">Not yet run</span>
            )}

            {canRun && !isLocked && (
              <button onClick={doRun} disabled={busy === 'run'}
                className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] disabled:opacity-50 transition-all">
                {busy === 'run' ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                {run ? 'Recompute' : 'Run payroll'}
              </button>
            )}

            {canRun && run && !isLocked && (
              <button onClick={doLock} disabled={busy === 'lock'}
                className="flex items-center gap-2 px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-main)] disabled:opacity-50 transition-colors">
                {busy === 'lock' ? <Loader2 size={14} className="animate-spin" /> : <Lock size={14} />}
                Lock month
              </button>
            )}

            {run?.computedBy && (
              <span className="text-[11px] font-medium text-[var(--text-muted)]">
                Computed by {run.computedBy}
                {isLocked && run.lockedBy ? ` · locked by ${run.lockedBy}` : ''}
              </span>
            )}
          </div>

          {run && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <StatTile icon={Users} label="Headcount" value={totals.headcount ?? 0} loading={loading} />
              <StatTile icon={Wallet} label="Gross" value={money(totals.gross)} loading={loading} />
              <StatTile icon={TrendingDown} label="Deductions" value={money(totals.deductions)} loading={loading} />
              <StatTile icon={ShieldCheck} label="Net payable" value={money(totals.net)} loading={loading} />
            </div>
          )}

          {/* Data gaps are surfaced, not hidden — a zero payslip is a missing CTC, not a salary. */}
          {run && (totals.missingSalary > 0 || totals.missingLogin > 0) && (
            <div className="flex items-start gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
              style={{ color: 'var(--accent-orange)', backgroundColor: 'var(--accent-orange-bg)', borderColor: 'var(--accent-orange-border)' }}>
              <Info size={15} className="mt-0.5 shrink-0" />
              <span>
                {totals.missingSalary > 0 && `${totals.missingSalary} employee(s) have no annual CTC set — their net is ₹0. `}
                {totals.missingLogin > 0 && `${totals.missingLogin} employee(s) have no linked login, so no attendance was counted.`}
              </span>
            </div>
          )}

          <div className="rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full" style={{ minWidth: 900 }}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    {['Employee', 'Days', 'Earned', 'OT', 'Deductions', 'Net', ''].map((h, i) => (
                      <th key={i}
                        className="text-left px-4 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loading && (
                    <tr><td colSpan={7} className="px-4 py-12 text-center">
                      <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
                        <Loader2 size={16} className="animate-spin" /> Loading…
                      </span>
                    </td></tr>
                  )}
                  {!loading && slips.length === 0 && (
                    <tr><td colSpan={7} className="px-4 py-12 text-center">
                      <p className="text-[13px] font-bold text-[var(--text-main)]">
                        No payroll for {monthLabel(year, month)}.
                      </p>
                      <p className="text-[12px] font-medium text-[var(--text-muted)] mt-1">
                        {canRun ? 'Run payroll to compute this month.' : 'Ask HR to run this month.'}
                      </p>
                    </td></tr>
                  )}
                  {!loading && slips.map((s) => (
                    <tr key={s.employeeCode}
                      className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                      <td className="px-4 py-3">
                        <div className="text-[12.5px] font-black text-[var(--text-main)]">{s.fullName}</div>
                        <div className="text-[11px] font-medium text-[var(--text-muted)]">
                          {s.employeeCode}{s.department ? ` · ${s.department}` : ''}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]"
                        style={{ fontVariantNumeric: 'tabular-nums' }}>
                        {s.workingDays}
                      </td>
                      <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-main)]"
                        style={{ fontVariantNumeric: 'tabular-nums' }}>{money(s.earnedSalary)}</td>
                      <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]"
                        style={{ fontVariantNumeric: 'tabular-nums' }}>
                        {s.overtimeHours ? `${s.overtimeHours}h · ${money(s.overtimeAmount)}` : '—'}
                      </td>
                      <td className="px-4 py-3 text-[12px] font-semibold"
                        style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--accent-red)' }}>
                        {money(s.totalDeductions)}
                      </td>
                      <td className="px-4 py-3 text-[12.5px] font-black text-[var(--text-main)]"
                        style={{ fontVariantNumeric: 'tabular-nums' }}>{money(s.netSalary)}</td>
                      <td className="px-4 py-3 text-right">
                        <button onClick={() => setDetail(s)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--border)] text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] transition-colors">
                          <FileText size={11} /> Breakdown
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* Breakdown */}
      {detail && (
        <div className="fixed inset-0 z-[350] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setDetail(null)} />
          <div className="relative w-full max-w-lg max-h-[88vh] overflow-y-auto rounded-[24px] bg-[var(--bg-card)] border border-[var(--border)] shadow-2xl">
            <div className="sticky top-0 flex items-center justify-between px-5 py-4 border-b border-[var(--border)] bg-[var(--table-header-bg)]">
              <div>
                <h2 className="text-[14px] font-black tracking-tight text-[var(--text-main)]">
                  {detail.fullName}
                </h2>
                <p className="text-[11px] font-bold text-[var(--text-muted)]">
                  {detail.employeeCode} · {monthLabel(year, month)}
                </p>
              </div>
              <button onClick={() => setDetail(null)}
                className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--table-hover)] transition-colors">
                <X size={18} />
              </button>
            </div>
            <div className="p-5">
              <PayslipCard slip={detail} embedded />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// Shared breakdown, used both for an employee's own payslip and HR's per-row detail — so the
// two can never present the same figures differently.
const Line = ({ label, value, tone, bold }) => (
  <div className="flex items-center justify-between py-2 border-b border-[var(--border)] last:border-0">
    <span className={`text-[12px] ${bold ? 'font-black text-[var(--text-main)]' : 'font-semibold text-[var(--text-muted)]'}`}>
      {label}
    </span>
    <span className={`text-[12.5px] ${bold ? 'font-black' : 'font-bold'}`}
      style={{ fontVariantNumeric: 'tabular-nums', color: tone || 'var(--text-main)' }}>
      {value}
    </span>
  </div>
);

const PayslipCard = ({ slip, embedded }) => (
  <div className={embedded ? '' : 'p-5 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm'}>
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
      <div>
        <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-1">
          Earnings
        </h3>
        <Line label="Monthly salary" value={money(slip.monthlySalary)} />
        <Line label={`Earned (${slip.payableDays} payable days)`} value={money(slip.earnedSalary)} />
        <Line label={`Overtime (${slip.overtimeHours}h)`} value={money(slip.overtimeAmount)} />
        <Line label="Total earnings" value={money(slip.totalEarnings)} bold />
      </div>
      <div>
        <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-1 mt-4 sm:mt-0">
          Deductions
        </h3>
        <Line label="Professional tax" value={money(slip.professionalTax)} tone="var(--accent-red)" />
        <Line label="Late entry fine" value={money(slip.lateEntryFine)} tone="var(--accent-red)" />
        <Line label="Late hours" value={money(slip.lateHourDeduction)} tone="var(--accent-red)" />
        <Line label="Unauthorized absence" value={money(slip.unauthorizedLeavePenalty)} tone="var(--accent-red)" />
        <Line label="Total deductions" value={money(slip.totalDeductions)} tone="var(--accent-red)" bold />
      </div>
    </div>

    <div className="mt-4 p-4 rounded-xl bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] flex items-center justify-between">
      <span className="text-[11px] font-black uppercase tracking-widest text-[var(--accent-indigo)]">
        Net payable
      </span>
      <span className="text-lg font-black text-[var(--accent-indigo)]"
        style={{ fontVariantNumeric: 'tabular-nums' }}>
        {money(slip.netSalary)}
      </span>
    </div>

    <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-2">
      {[
        ['Working days', slip.workingDays],
        ['Paid leave', slip.paidLeaves],
        ['Unpaid leave', slip.unpaidLeaves],
        ['Paid Sundays', slip.paidSundays],
      ].map(([label, value]) => (
        <div key={label} className="p-2.5 rounded-lg bg-[var(--input-bg)] border border-[var(--border)]">
          <div className="text-[13px] font-black text-[var(--text-main)]"
            style={{ fontVariantNumeric: 'tabular-nums' }}>{value}</div>
          <div className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)] mt-0.5">
            {label}
          </div>
        </div>
      ))}
    </div>

    {/* The engine explains every non-obvious adjustment rather than leaving a number unexplained. */}
    {(slip.notes || []).length > 0 && (
      <ul className="mt-4 flex flex-col gap-1.5">
        {slip.notes.map((n, i) => (
          <li key={i} className="flex items-start gap-2 text-[11.5px] font-medium text-[var(--text-muted)]">
            <Info size={12} className="mt-0.5 shrink-0" /> {n}
          </li>
        ))}
      </ul>
    )}
  </div>
);

export default Payroll;
