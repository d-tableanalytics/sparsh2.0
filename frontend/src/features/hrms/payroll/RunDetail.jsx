import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, Download, Lock, Send, X, Calculator, Search,
} from 'lucide-react';
import { CAP } from '../access';
import BoardTabs from '../common/BoardTabs';
import { NextStepBanner } from '../common/ProcessGuide';
import { payrollNextStep } from '../common/processGuides';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import {
  getPayrollRun, calculatePayroll, listPayrollRecords, listPayslips,
  submitPayrollRun, checkPayrollRun, decidePayrollRun, actOnPayrollStage, lockPayrollRun, closePayrollRun,
  downloadPayrollRegister,
  adjustPayrollRecord, setPayrollAdjustments, listSalaryComponents, approvePayrollAdjustment,
  importPayrollInputs,
} from '../../../services/hrmsApi';
import Payslip, { PayslipDocument } from './Payslip';
import PostLockAdjustments from './PostLockAdjustments';
import Disbursal from './Disbursal';
import { FIELD, LABEL, TEXTAREA, money, day } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal } from '../internal/internalKit.jsx';
import {
  RUN_STAGES, EDITABLE_RUN_STATUSES, FINAL_RUN_STATUSES, stageIndex, runTone,
  errText, blobErrText, saveBlob, when, signed, useSubmit,
} from './payrollKit';

/**
 * HRMS ▸ Payroll ▸ one month's run (FRD §10-§13, §18, §20).
 *
 * Everything about a single period in one place: where it is in the maker-checker flow, its
 * totals, who did what, every employee's figures, post-lock corrections and — once it is
 * locked — paying it. The buttons shown are the ones the viewer may press at THIS status;
 * the server still enforces every rule (status, capability, maker ≠ checker), so a stale
 * screen gets a clear refusal rather than a silent change.
 *
 * Wider than the shared Modal (max-w-2xl): a payroll register is a table, and at 672px eight
 * money columns do not fit. Below `md` the table becomes cards, the same split RecordList uses.
 */

const RunShell = ({ title, onClose, children }) => (
  <div className="fixed inset-0 z-[60] grid place-items-center bg-black/40 backdrop-blur-sm p-2 sm:p-4"
    role="dialog" aria-modal="true" aria-labelledby="run-detail-title"
    onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}>
    <div className="w-full max-w-5xl max-h-[94vh] flex flex-col rounded-2xl border border-[var(--border)]
      bg-[var(--bg-card)] shadow-xl">
      <div className="px-4 sm:px-5 py-4 border-b border-[var(--border)] flex items-center justify-between gap-3">
        <h2 id="run-detail-title" className="text-[15px] font-bold text-[var(--text-main)]">{title}</h2>
        <button type="button" onClick={onClose} aria-label="Close"
          className="h-8 w-8 shrink-0 rounded-lg border border-[var(--border)] grid place-items-center
            text-[var(--text-muted)] hover:text-[var(--text-main)]">
          <X size={15} />
        </button>
      </div>
      <div className="p-4 sm:p-5 space-y-4 overflow-y-auto">{children}</div>
    </div>
  </div>
);

export const RunDetailModal = ({ period, scope, can, onClose, onDone, showSuccess, showError }) => {
  const [runInfo, setRunInfo] = useState(null);
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [section, setSection] = useState('Employees');
  const [adjusting, setAdjusting] = useState(null);
  const [viewingPayslip, setViewingPayslip] = useState(null);
  const [allPayslips, setAllPayslips] = useState(null);
  const [loadingAll, setLoadingAll] = useState(false);
  const [exporting, setExporting] = useState(false);
  // The last Calculate refusal stays on screen — "attendance is not locked" is the kind of
  // message a toast shows for three seconds and the maker then cannot find again.
  const [calcError, setCalcError] = useState(null);
  const { busy, run } = useSubmit(showSuccess, showError, () => { load(); onDone(); });

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [{ data: ri }, { data: recs }] = await Promise.all([
        getPayrollRun(period, scope), listPayrollRecords(period, scope),
      ]);
      setRunInfo(ri);
      setRecords(recs || []);
    } catch (err) {
      setError(errText(err, 'Could not load this run.'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  useEffect(() => { load(); }, [load]);

  // A quiet refresh after a payment update elsewhere on this screen: the run may have just
  // become Paid, and the spinner would throw the user out of the Disbursal section.
  const refreshQuietly = useCallback(async () => {
    try {
      const { data } = await getPayrollRun(period, scope);
      setRunInfo(data);
      onDone();
    } catch { /* the next full load shows any error */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  const openAllPayslips = async () => {
    setLoadingAll(true);
    try {
      const { data } = await listPayslips(period, scope);
      setAllPayslips(data || []);
    } catch (err) {
      showError(errText(err, 'Could not load payslips for this run.'));
    } finally {
      setLoadingAll(false);
    }
  };

  const exportRegister = async () => {
    setExporting(true);
    try {
      const { data } = await downloadPayrollRegister(period, scope);
      saveBlob(data, `payroll_register_${period}.csv`);
    } catch (err) {
      showError(await blobErrText(err, 'Could not export the payroll register.'));
    } finally {
      setExporting(false);
    }
  };

  const calculate = () => run(async () => {
    setCalcError(null);
    try {
      await calculatePayroll(period, scope);
    } catch (err) {
      setCalcError(errText(err, 'Payroll could not be calculated.'));
      throw err;
    }
  }, 'Payroll calculated.');

  const status = runInfo?.status;
  const editable = EDITABLE_RUN_STATUSES.includes(status);
  const final = FINAL_RUN_STATUSES.includes(status);
  const canProcess = can(CAP.PAYROLL_PROCESS);
  const blockingAttendance = runInfo?.policy?.require_attendance_lock !== false;
  const flagged = records.filter(hasExceptions).length;

  const sections = [
    { key: 'Employees', count: records.length },
    { key: 'Approval trail', count: runInfo?.approval_trail?.length || 0 },
    'Corrections',
    ...(final ? ['Disbursal'] : []),
  ];
  const shown = sections.some((s) => (s.key || s) === section) ? section : 'Employees';

  return (
    <>
      <RunShell title={`Payroll Run · ${period}`} onClose={onClose}>
        {loading && <HrmsLoading label="Loading run…" />}
        {error && !loading && <HrmsError message={error} onRetry={load} />}
        {!loading && !error && runInfo && (
          <div className="space-y-4">
            <NextStepBanner step={payrollNextStep(runInfo, { canApprove: can(CAP.PAYROLL_APPROVE) })} />
            <RunStepper status={status} />

            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <Chip tone={runTone(status)}>{status}</Chip>
                <span className="text-[11.5px] text-[var(--text-muted)]">
                  {day(runInfo.period_start)} – {day(runInfo.period_end)}
                  {runInfo.payslip_template_version != null
                    && (runInfo.payslip_template_version > 0
                      ? ` · payslip template v${runInfo.payslip_template_version}`
                      : ' · default payslip template')}
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {records.length > 0 && (
                  <Btn disabled={loadingAll} onClick={openAllPayslips}>
                    {loadingAll ? 'Loading…' : 'All Payslips'}
                  </Btn>
                )}
                {records.length > 0 && (
                  <Btn disabled={exporting} onClick={exportRegister}>
                    <Download size={14} /> {exporting ? 'Exporting…' : 'Export register'}
                  </Btn>
                )}
                {canProcess && editable && (
                  <Btn tone="primary" disabled={busy} onClick={calculate}>
                    <Calculator size={14} /> {busy ? 'Working…' : status === 'Draft' ? 'Calculate' : 'Recalculate'}
                  </Btn>
                )}
              </div>
            </div>

            {editable && runInfo.attendance_locked === false && (
              <div className={`rounded-lg px-3.5 py-2.5 flex items-start gap-2 ${blockingAttendance
                ? 'bg-[var(--accent-red-bg)]' : 'bg-[var(--accent-orange-bg)]'}`}>
                <AlertTriangle size={16} className={`shrink-0 mt-0.5 ${blockingAttendance
                  ? 'text-[var(--accent-red)]' : 'text-[var(--accent-orange)]'}`} />
                <p className="text-[12.5px] text-[var(--text-main)]">
                  <span className="font-bold">Attendance for {period} is not locked.</span>{' '}
                  {blockingAttendance
                    ? 'Calculate will be refused until it is locked in Attendance → Monthly Closure.'
                    : 'You can calculate, but the days may still change — recalculate once attendance is locked.'}
                </p>
              </div>
            )}
            {/* FRD §18 — the run was calculated against a locked month that has since
                moved. Shown while they are looking at it, not only when Submit is clicked. */}
            {runInfo.attendance_basis_stale && (
              <div className="rounded-lg px-3.5 py-2.5 flex items-start gap-2 bg-[var(--accent-red-bg)]">
                <AlertTriangle size={16} className="shrink-0 mt-0.5 text-[var(--accent-red)]" />
                <p className="text-[12.5px] text-[var(--text-main)]">
                  <span className="font-bold">This payroll no longer matches attendance.</span>{' '}
                  {runInfo.attendance_basis_stale} Recalculate before submitting it.
                </p>
              </div>
            )}
            {calcError && (
              <div className="rounded-lg px-3.5 py-2.5 flex items-start gap-2 bg-[var(--accent-red-bg)]">
                <AlertTriangle size={16} className="shrink-0 mt-0.5 text-[var(--accent-red)]" />
                <p className="text-[12.5px] text-[var(--accent-red)] font-semibold">{calcError}</p>
              </div>
            )}
            {(status === 'Returned' || status === 'Rejected') && runInfo.decision_remarks && (
              <div className="rounded-lg px-3.5 py-2.5 bg-[var(--accent-orange-bg)] text-[12.5px] text-[var(--text-main)]">
                <span className="font-bold">{status} by {runInfo.decided_by_name || 'the checker'}</span>
                {runInfo.decided_at && ` on ${when(runInfo.decided_at)}`}: {runInfo.decision_remarks}
              </div>
            )}
            {canProcess && editable && status !== 'Draft' && (
              <p className="text-[11.5px] text-[var(--text-muted)]">
                Recalculating re-reads salaries and attendance and keeps everything you typed in with Adjust.
              </p>
            )}
            {/* FRD §24 Imported Input: an incentive sheet or deduction file for this run. */}
            {canProcess && editable && (
              <label className="inline-flex items-center gap-2 text-[11.5px] text-[var(--text-muted)]">
                Imported inputs (Employee Code, Component, Amount):
                <input type="file" accept=".csv,.xlsx" aria-label="Imported inputs file"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = '';
                    if (!file) return;
                    run(async () => {
                      const { data } = await importPayrollInputs(period, file, scope);
                      if (data.errors?.length) {
                        showError(`${data.errors.length} row(s) refused — first: row ${data.errors[0].row}, ${data.errors[0].reason}.`);
                      }
                    }, 'Inputs imported — recalculate to apply them.');
                  }} />
              </label>
            )}

            <RunTotals totals={runInfo.totals} />

            <RunActions key={status} runInfo={runInfo} period={period} scope={scope} can={can}
              busy={busy} run={run} showError={showError} />

            <BoardTabs tabs={sections} value={shown} onChange={setSection} label="Run sections" />

            {shown === 'Employees' && (
              <RecordsSection records={records} runInfo={runInfo} flagged={flagged}
                canAdjust={canProcess && editable}
                onAdjust={setAdjusting} onPayslip={setViewingPayslip}
                onApproveLine={editable && (can(CAP.PAYROLL_CHECK) || can(CAP.PAYROLL_APPROVE))
                  ? (r, i) => run(() => approvePayrollAdjustment(period, r.employee_code, i, scope),
                    'Line approved.')
                  : null} />
            )}
            {shown === 'Approval trail' && <ApprovalTrail trail={runInfo.approval_trail} />}
            {shown === 'Corrections' && (
              <PostLockAdjustments period={period} runStatus={status} records={records}
                scope={scope} can={can} showSuccess={showSuccess} showError={showError} />
            )}
            {shown === 'Disbursal' && (
              <Disbursal period={period} runStatus={status} scope={scope} can={can}
                showSuccess={showSuccess} showError={showError} onChanged={refreshQuietly} />
            )}
          </div>
        )}
      </RunShell>

      {adjusting && (
        <AdjustRecordModal period={period} record={adjusting} scope={scope}
          onClose={() => setAdjusting(null)} onDone={() => { setAdjusting(null); load(); onDone(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {viewingPayslip && (
        <Modal title={`Payslip · ${viewingPayslip.employee_name || viewingPayslip.employee_code}`}
          labelledBy="hr-payslip-title" wide onClose={() => setViewingPayslip(null)}
          footer={<Btn onClick={() => setViewingPayslip(null)}>Close</Btn>}
        >
          <Payslip embedded employeeCode={viewingPayslip.employee_code} initialPeriod={period} />
        </Modal>
      )}
      {allPayslips && (
        <div className="fixed inset-0 z-[70] bg-black/60 overflow-y-auto py-8 px-4">
          <div className="max-w-3xl mx-auto space-y-6 print:space-y-0">
            <div className="flex justify-end gap-2 print:hidden">
              <button type="button" onClick={() => window.print()}
                className="h-9 px-3.5 rounded-lg bg-white text-[12px] font-bold text-slate-900">
                Print / Save all as PDF
              </button>
              <button type="button" onClick={() => setAllPayslips(null)} aria-label="Close"
                className="h-9 w-9 rounded-lg bg-white text-slate-900 flex items-center justify-center">
                <X size={16} />
              </button>
            </div>
            {allPayslips.length === 0 && (
              <p className="text-center text-[13px] text-white">No payslips in this run yet.</p>
            )}
            {allPayslips.map((slip, i) => (
              <div key={slip.employee_code}
                style={i > 0 ? { breakBefore: 'page' } : undefined}>
                <PayslipDocument slip={slip} />
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
};

// ── Status stepper: Calculate → Submit → Check → Lock → Pay → Close ──
const RunStepper = ({ status }) => {
  const at = stageIndex(status);
  const sentBack = status === 'Returned' || status === 'Rejected';
  return (
    <ol className="grid grid-cols-3 sm:grid-cols-6 gap-1.5" aria-label="Payroll stages">
      {RUN_STAGES.map((stage, i) => {
        const done = i < at;
        const here = i === at;
        const tone = here
          ? sentBack
            ? 'border-[var(--accent-orange)] bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]'
            : 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
          : done ? 'border-[var(--border)] text-[var(--accent-green)]'
            : 'border-[var(--border)] text-[var(--text-muted)]';
        return (
          <li key={stage} aria-current={here ? 'step' : undefined}
            className={`rounded-lg border px-2 py-1.5 flex items-center gap-1.5 text-[11.5px] font-bold ${tone}`}>
            {done ? <CheckCircle2 size={13} className="shrink-0" />
              : <span className="h-4 w-4 shrink-0 rounded-full border border-current text-[9.5px] grid place-items-center">{i + 1}</span>}
            <span className="truncate">{stage}</span>
          </li>
        );
      })}
    </ol>
  );
};

// ── Totals cards ──
const RunTotals = ({ totals }) => {
  if (!totals) {
    return (
      <p className="text-[12px] text-[var(--text-muted)]">
        Totals appear here once the run is calculated.
      </p>
    );
  }
  const diff = totals.previous_net ? Math.round((totals.net - totals.previous_net) * 100) / 100 : null;
  const pct = totals.previous_net ? Math.round((diff / totals.previous_net) * 1000) / 10 : null;
  const cards = [
    { label: 'Headcount', value: totals.headcount ?? '—' },
    { label: 'Gross', value: money(totals.gross) },
    { label: 'Deductions', value: money(totals.deductions) },
    { label: 'Employer contrib.', value: money(totals.employer_contributions), hint: 'On top of gross' },
    { label: 'Net pay', value: money(totals.net), strong: true },
    { label: 'vs previous net', value: diff == null ? '—' : signed(diff),
      hint: diff == null ? 'No earlier month to compare' : `${signed(pct)}% · was ${money(totals.previous_net)}` },
  ];
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {cards.map((c) => (
          <div key={c.label} className={`rounded-lg border px-3 py-2.5 min-w-0 ${c.strong
            ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]' : 'border-[var(--border)]'}`}>
            <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] truncate">{c.label}</p>
            <p className="text-[15px] font-bold tabular-nums text-[var(--text-main)] truncate">{c.value}</p>
            {c.hint && <p className="text-[10.5px] text-[var(--text-muted)] truncate" title={c.hint}>{c.hint}</p>}
          </div>
        ))}
      </div>
      {(totals.exceptions > 0 || totals.lop_days > 0) && (
        <p className="text-[11.5px] text-[var(--text-muted)]">
          {totals.critical_exceptions > 0 && (
            <span className="font-bold text-[var(--accent-red)]">{totals.critical_exceptions} critical · </span>
          )}
          {totals.exceptions > 0 && `${totals.exceptions - (totals.critical_exceptions || 0)} warning(s)`}
          {totals.exceptions > 0 && totals.lop_days > 0 && ' · '}
          {totals.lop_days > 0 && `${totals.lop_days} LOP day(s) across the run`}
        </p>
      )}
    </div>
  );
};

// ── The action panel: the one step the viewer can take at this status ──
const RunActions = ({ runInfo, period, scope, can, busy, run, showError }) => {
  const [remarks, setRemarks] = useState('');
  const status = runInfo.status;
  const critical = runInfo.totals?.critical_exceptions || 0;
  const text = remarks.trim() || undefined;
  const act = (fn, msg) => run(async () => { await fn(); setRemarks(''); }, msg);
  const needReason = (fn, msg) => {
    if (!text) { showError('Say why — the maker sees this reason.'); return; }
    act(fn, msg);
  };

  let title; let hint; let buttons; let remarksLabel = 'Remarks (optional)';
  if (status === 'Calculated' && can(CAP.PAYROLL_PROCESS)) {
    title = 'Submit for approval';
    hint = critical
      ? `${critical} critical problem(s) must be fixed and the run recalculated before it can be submitted.`
      : 'A checker — someone other than you — verifies it, then Finance approves it.';
    buttons = (
      <Btn tone="primary" disabled={busy || critical > 0} onClick={() => act(
        () => submitPayrollRun(period, { remarks: text }, scope), 'Payroll submitted for approval.')}>
        <Send size={14} /> {busy ? 'Working…' : 'Submit for approval'}
      </Btn>
    );
  } else if (runInfo.current_stage && can(runInfo.current_stage.cap)) {
    // P1-095 — a CONFIGURED approval chain: whichever stage the run waits on, named as the
    // company named it. Who may act is the stage's own permission (and roles, checked by
    // the server); the maker and anyone who passed an earlier stage are refused there.
    const stage = runInfo.current_stage;
    const last = stage.index === stage.count - 1;
    title = `${stage.name} — stage ${stage.index + 1} of ${stage.count}`;
    hint = `Submitted by ${runInfo.submitted_by_name || 'the maker'}${runInfo.submitted_at ? ` on ${when(runInfo.submitted_at)}` : ''}. `
      + (last
        ? 'This is the final approval. Approving does not lock it — locking is the next step.'
        : 'Passing this stage sends it to the next approver in the chain.');
    remarksLabel = 'Remarks (required to return or reject)';
    buttons = (
      <>
        <Btn disabled={busy} onClick={() => needReason(
          () => actOnPayrollStage(period, { action: 'return', remarks: text }, scope), 'Payroll returned to the maker.')}>
          Return
        </Btn>
        <Btn tone="danger" disabled={busy} onClick={() => needReason(
          () => actOnPayrollStage(period, { action: 'reject', remarks: text }, scope), 'Payroll rejected.')}>
          Reject
        </Btn>
        <Btn tone="primary" disabled={busy} onClick={() => act(
          () => actOnPayrollStage(period, { action: 'approve', remarks: text }, scope),
          last ? 'Payroll approved.' : `${stage.name} passed — sent to the next approver.`)}>
          {busy ? 'Working…' : (last ? 'Approve' : `Pass ${stage.name}`)}
        </Btn>
      </>
    );
  } else if (!runInfo.approval_chain && status === 'Submitted' && can(CAP.PAYROLL_CHECK)) {
    // FRD §12 stage 8 — the Payroll/HR Checker. Verifying is NOT approving: this hands the
    // run on to Finance, which is a different person's decision.
    title = 'Check this payroll';
    hint = `Submitted by ${runInfo.submitted_by_name || 'the maker'}${runInfo.submitted_at ? ` on ${when(runInfo.submitted_at)}` : ''}. `
      + 'Verify the component values, attendance impact and exceptions. Passing the check sends it to Finance for approval — it does not approve or lock it.';
    remarksLabel = 'Remarks (required to return or reject)';
    buttons = (
      <>
        <Btn disabled={busy} onClick={() => needReason(
          () => checkPayrollRun(period, { action: 'return', remarks: text }, scope), 'Payroll returned to the maker.')}>
          Return
        </Btn>
        <Btn tone="danger" disabled={busy} onClick={() => needReason(
          () => checkPayrollRun(period, { action: 'reject', remarks: text }, scope), 'Payroll rejected.')}>
          Reject
        </Btn>
        <Btn tone="primary" disabled={busy} onClick={() => act(
          () => checkPayrollRun(period, { action: 'check', remarks: text }, scope), 'Payroll checked — sent to Finance for approval.')}>
          {busy ? 'Working…' : 'Pass check'}
        </Btn>
      </>
    );
  } else if (!runInfo.approval_chain && status === 'Checked' && can(CAP.PAYROLL_APPROVE)) {
    // FRD §12 stage 9 — Finance / the Authorised Approver.
    title = 'Approve this payroll';
    hint = `Checked by ${runInfo.checked_by_name || 'the checker'}${runInfo.checked_at ? ` on ${when(runInfo.checked_at)}` : ''}. `
      + 'Approve, return it for a correction, or reject it. Approving does not lock it — locking is the next step.';
    remarksLabel = 'Remarks (required to return or reject)';
    buttons = (
      <>
        <Btn disabled={busy} onClick={() => needReason(
          () => decidePayrollRun(period, { action: 'return', remarks: text }, scope), 'Payroll returned to the maker.')}>
          Return
        </Btn>
        <Btn tone="danger" disabled={busy} onClick={() => needReason(
          () => decidePayrollRun(period, { action: 'reject', remarks: text }, scope), 'Payroll rejected.')}>
          Reject
        </Btn>
        <Btn tone="primary" disabled={busy} onClick={() => act(
          () => decidePayrollRun(period, { action: 'approve', remarks: text }, scope), 'Payroll approved.')}>
          {busy ? 'Working…' : 'Approve'}
        </Btn>
      </>
    );
  } else if (status === 'Approved' && can(CAP.PAYROLL_APPROVE)) {
    title = 'Lock payroll';
    hint = 'Locking makes every figure final, releases payslips and freezes the current payslip template for this month. After this, corrections go into a later month.';
    buttons = (
      <Btn tone="primary" disabled={busy} onClick={() => act(
        () => lockPayrollRun(period, { remarks: text }, scope), 'Payroll locked.')}>
        <Lock size={14} /> {busy ? 'Working…' : 'Lock payroll'}
      </Btn>
    );
  } else if ((status === 'Locked' || status === 'Paid') && can(CAP.PAYROLL_APPROVE)) {
    const unpaid = runInfo.payment_summary?.unpaid || 0;
    // DEF-04: failed or bank-pending payments block closing outright — a reason cannot
    // cover them, because a closed period can no longer raise a retry batch.
    const blocking = (runInfo.payment_summary?.failed || 0) + (runInfo.payment_summary?.pending || 0);
    title = 'Close period';
    hint = status === 'Paid'
      ? 'Everyone with pay due has been paid. Closing ends the month.'
      : blocking
        ? `${blocking} payment(s) are failed or still pending with the bank. Retry them or record them as Processed under Disbursal before closing.`
      : unpaid
        ? `${unpaid} employee(s) are not marked paid yet. Record their payments under Disbursal, or give a reason to close anyway.`
        : 'Close once every payment is confirmed under Disbursal. If some are being paid outside a batch, give a reason.';
    remarksLabel = status === 'Paid' ? 'Remarks (optional)' : 'Reason (needed if anyone is unpaid)';
    buttons = (
      <Btn tone={status === 'Paid' ? 'primary' : 'ghost'} disabled={busy || blocking > 0} onClick={() => act(
        () => closePayrollRun(period, { remarks: text }, scope), 'Payroll period closed.')}>
        {busy ? 'Working…' : 'Close period'}
      </Btn>
    );
  } else {
    return null;
  }

  return (
    <div className="rounded-xl border border-[var(--border)] p-3.5 space-y-2.5">
      <div>
        <p className="text-[13px] font-bold text-[var(--text-main)]">{title}</p>
        <p className={`text-[12px] mt-0.5 ${critical && status === 'Calculated'
          ? 'text-[var(--accent-red)] font-semibold' : 'text-[var(--text-muted)]'}`}>{hint}</p>
      </div>
      <div>
        <label className={LABEL} htmlFor="run-action-remarks">{remarksLabel}</label>
        <textarea id="run-action-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
      <div className="flex flex-wrap justify-end gap-2">{buttons}</div>
    </div>
  );
};

// ── Approval trail ──
const STAGE_TONE = { Maker: 'neutral', Checker: 'accent', Approver: 'warn', Finance: 'good' };

const ApprovalTrail = ({ trail }) => {
  if (!trail?.length) {
    return <p className="text-[12px] text-[var(--text-muted)]">Nothing recorded yet.</p>;
  }
  return (
    <ol className="space-y-2">
      {trail.map((t, i) => (
        <li key={`${t.at}-${i}`} className="rounded-lg border border-[var(--border)] px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Chip tone={STAGE_TONE[t.stage] || 'neutral'}>{t.stage}</Chip>
            <span className="text-[12.5px] font-bold text-[var(--text-main)]">{t.action}</span>
            <span className="sm:ml-auto text-[11.5px] text-[var(--text-muted)]">
              {t.by_name || '—'} · {when(t.at)}
            </span>
          </div>
          {t.remarks && <p className="mt-1 text-[12px] text-[var(--text-main)]">{t.remarks}</p>}
        </li>
      ))}
    </ol>
  );
};

// ── Employee records ──
const hasExceptions = (r) => (r.exception_details?.length || r.exceptions?.length || 0) > 0;

/** Severity-tagged exceptions; a record calculated before severities existed has only the
 *  plain message list, which reads as warnings. */
const exceptionsOf = (r) => (r.exception_details?.length
  ? r.exception_details
  : (r.exceptions || []).map((message) => ({ code: null, severity: 'warning', message })));

const EXCEPTION_LABEL = {
  NO_STRUCTURE: 'No salary', NEGATIVE_NET: 'Negative net', ZERO_PAYABLE: 'No payable days',
  UNRECORDED_DAYS: 'Unrecorded days', PENDING_ATTENDANCE: 'Attendance pending',
  NO_BANK: 'No bank details', ATTENDANCE_OPEN: 'Attendance open', VARIANCE: 'Large change',
  SANDWICH: 'Off days as LOP',
};

const ExceptionChips = ({ r }) => {
  const items = exceptionsOf(r);
  if (!items.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {items.map((e, i) => (
        <span key={`${e.code || e.message}-${i}`} title={e.message}
          className={`inline-flex rounded-md px-1.5 py-0.5 text-[10.5px] font-bold ${e.severity === 'critical'
            ? 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]'
            : 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]'}`}>
          {EXCEPTION_LABEL[e.code] || e.message}
        </span>
      ))}
    </div>
  );
};

const VarianceCell = ({ r, threshold }) => {
  if (r.variance_amount == null) {
    return <span className="text-[var(--text-muted)]" title="No earlier month to compare">—</span>;
  }
  const over = threshold > 0 && r.variance_percent != null && Math.abs(r.variance_percent) > threshold;
  return (
    <span className={over ? 'font-bold text-[var(--accent-orange)]' : 'text-[var(--text-main)]'}
      title={over ? `Beyond the ${threshold}% variance threshold` : `Last month ${money(r.previous_net)}`}>
      {signed(r.variance_amount)}
      <span className="block text-[10.5px]">
        {r.variance_percent != null ? `${signed(r.variance_percent)}%` : 'new'}
      </span>
    </span>
  );
};

const RowLink = ({ children, ...rest }) => (
  <button type="button" {...rest}
    className="text-[11.5px] font-bold text-[var(--accent-indigo)] hover:underline disabled:opacity-50">
    {children}
  </button>
);

const RecordsSection = ({ records, runInfo, flagged, canAdjust, onAdjust, onPayslip, onApproveLine }) => {
  const [onlyExceptions, setOnlyExceptions] = useState(false);
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(null);
  const threshold = Number(runInfo.policy?.variance_threshold_percent) || 0;
  const q = search.trim().toLowerCase();
  const rows = records.filter((r) => (!onlyExceptions || hasExceptions(r))
    && (!q || `${r.employee_name || ''} ${r.employee_code}`.toLowerCase().includes(q)));
  const toggle = (code) => setOpen((o) => (o === code ? null : code));

  if (!records.length) {
    return (
      <p className="text-[12px] text-[var(--text-muted)] py-2">
        Nobody in this run yet — click Calculate to add every eligible employee and work out their pay.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} placeholder="Find an employee…" className={`${FIELD} pl-8`}
            aria-label="Find an employee" onChange={(e) => setSearch(e.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-[12px] text-[var(--text-main)]">
          <input type="checkbox" checked={onlyExceptions} onChange={(e) => setOnlyExceptions(e.target.checked)} />
          Only with exceptions ({flagged})
        </label>
        {threshold > 0 && (
          <span className="text-[11px] text-[var(--text-muted)]">
            Variance beyond {threshold}% is highlighted.
          </span>
        )}
      </div>

      {!rows.length && (
        <p className="text-[12px] text-[var(--text-muted)]">No employees match.</p>
      )}

      {/* Phone: one card per person. */}
      <div className="md:hidden space-y-2.5">
        {rows.map((r) => (
          <div key={r.employee_code} className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-3.5 space-y-2">
            <div>
              <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
              <p className="text-[11px] text-[var(--text-muted)]">{r.employee_code}</p>
              <ExceptionChips r={r} />
            </div>
            <Facts items={[
              { label: 'Payable / LOP', value: `${r.payable_days} / ${r.lop_days}` },
              { label: 'Gross', value: money(r.gross_earnings) },
              { label: 'Deductions', value: money(r.total_deductions) },
              { label: 'Employer', value: money(r.total_employer_contributions) },
              { label: 'Net pay', value: money(r.net_pay) },
              { label: 'Variance', value: <VarianceCell r={r} threshold={threshold} /> },
            ]} />
            <div className="flex flex-wrap gap-3">
              <RowLink onClick={() => toggle(r.employee_code)}>
                {open === r.employee_code ? 'Hide details' : 'Details'}
              </RowLink>
              <RowLink onClick={() => onPayslip(r)}>Payslip</RowLink>
              {canAdjust && <RowLink onClick={() => onAdjust(r)}>Adjust</RowLink>}
            </div>
            {open === r.employee_code && <RecordDetail r={r} onApproveLine={onApproveLine} />}
          </div>
        ))}
      </div>

      {/* Tablet and up: the register as a table, a row opens in place. */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-left text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] border-b border-[var(--border)]">
              <th scope="col" className="py-2 pr-2">Employee</th>
              <th scope="col" className="py-2 pr-2">Payable / LOP</th>
              <th scope="col" className="py-2 pr-2 text-right">Gross</th>
              <th scope="col" className="py-2 pr-2 text-right">Deductions</th>
              <th scope="col" className="py-2 pr-2 text-right">Employer</th>
              <th scope="col" className="py-2 pr-2 text-right">Net pay</th>
              <th scope="col" className="py-2 pr-2 text-right">Variance</th>
              <th scope="col" className="py-2"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <React.Fragment key={r.employee_code}>
                <tr className="border-b border-[var(--border)] align-top">
                  <td className="py-2 pr-2 max-w-[260px]">
                    <span className="font-semibold text-[var(--text-main)]">{r.employee_name || r.employee_code}</span>
                    <span className="block text-[10.5px] text-[var(--text-muted)]">{r.employee_code}</span>
                    <ExceptionChips r={r} />
                  </td>
                  <td className="py-2 pr-2 whitespace-nowrap">
                    {r.payable_days}<span className="text-[var(--text-muted)]"> / {r.days_in_period}</span>
                    {r.lop_days > 0 && (
                      <span className="block text-[10.5px] text-[var(--accent-orange)]">{r.lop_days} LOP</span>
                    )}
                  </td>
                  <td className="py-2 pr-2 text-right tabular-nums">{money(r.gross_earnings)}</td>
                  <td className="py-2 pr-2 text-right tabular-nums">{money(r.total_deductions)}</td>
                  <td className="py-2 pr-2 text-right tabular-nums">{money(r.total_employer_contributions)}</td>
                  <td className="py-2 pr-2 text-right tabular-nums font-bold">{money(r.net_pay)}</td>
                  <td className="py-2 pr-2 text-right tabular-nums"><VarianceCell r={r} threshold={threshold} /></td>
                  <td className="py-2">
                    <div className="flex justify-end gap-3 whitespace-nowrap">
                      <RowLink onClick={() => toggle(r.employee_code)} aria-expanded={open === r.employee_code}>
                        {open === r.employee_code ? 'Hide' : 'Details'}
                      </RowLink>
                      <RowLink onClick={() => onPayslip(r)}>Payslip</RowLink>
                      {canAdjust && <RowLink onClick={() => onAdjust(r)}>Adjust</RowLink>}
                    </div>
                  </td>
                </tr>
                {open === r.employee_code && (
                  <tr className="border-b border-[var(--border)]">
                    <td colSpan={8} className="py-2"><RecordDetail r={r} onApproveLine={onApproveLine} /></td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const FIXED_INPUTS = [
  ['pf', 'PF'], ['esi', 'ESI'], ['pt', 'Professional Tax'], ['tds', 'TDS'],
  ['arrears', 'Arrears'], ['reimbursements', 'Reimbursements'], ['bonus', 'Bonus'],
  ['other_earnings', 'Other Earnings'], ['other_deductions', 'Other Deductions'],
  ['notice_recovery', 'Notice Recovery'],
];
/** Rolled up by the server, never typed in — listed so a reader can see where a figure came from. */
const AUTO_INPUTS = [
  ['advance_recovery', 'Salary advance recovery'], ['variable_pay_payout', 'Variable pay'],
];

const RecordDetail = ({ r, onApproveLine }) => {
  const lines = r.lines || [];
  const inputs = [...FIXED_INPUTS, ...AUTO_INPUTS].filter(([k]) => Number(r[k]) > 0);
  const issues = exceptionsOf(r);
  return (
    <div className="rounded-lg bg-[var(--input-bg)] p-3 space-y-3">
      <Facts items={[
        // FRD §10 Salary Basis: which approved structure this month was paid from.
        { label: 'Salary structure', value: r.structure_effective_from
          ? `In force from ${day(r.structure_effective_from)}` : 'None on file' },
        { label: 'Joined', value: r.date_of_joining ? day(r.date_of_joining) : null },
        { label: 'Last working day', value: r.last_working_day ? day(r.last_working_day) : null },
        { label: 'Days in month', value: r.days_in_period },
        { label: 'Working days', value: r.working_days },
        { label: 'Present', value: r.present_days },
        { label: 'Payable', value: r.payable_days },
        { label: 'LOP', value: r.lop_days },
        { label: 'Weekly offs', value: r.weekly_off_days },
        { label: 'Holidays', value: r.holiday_days },
        { label: 'Leave', value: r.leave_days },
        { label: 'Not in service', value: r.out_of_service_days || null },
        { label: 'Unrecorded', value: r.unrecorded_days || null },
      ]} />

      {lines.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[11.5px]">
            <thead>
              <tr className="text-left text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                <th scope="col" className="py-1 pr-2">Component</th>
                <th scope="col" className="py-1 pr-2">Type</th>
                <th scope="col" className="py-1 pr-2 text-right">Full month</th>
                <th scope="col" className="py-1 text-right">Paid</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.code} className="border-t border-[var(--border)]">
                  <td className="py-1 pr-2 text-[var(--text-main)]">
                    {l.name || l.code}
                    {l.prorated && <span className="text-[var(--text-muted)]"> · prorated</span>}
                    {/* DEF-01: the component version (and formula) this line was priced by. */}
                    {l.component_version != null && (
                      <span className="text-[var(--text-muted)]" title={l.formula || undefined}>
                        {' '}· v{l.component_version}{l.formula ? ` · ${l.formula}` : ''}
                      </span>
                    )}
                  </td>
                  <td className="py-1 pr-2 text-[var(--text-muted)]">{l.component_type}</td>
                  <td className="py-1 pr-2 text-right tabular-nums">{money(l.full_amount)}</td>
                  <td className="py-1 text-right tabular-nums font-semibold">{money(l.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {inputs.length > 0 && (
        <div>
          <p className={LABEL}>Monthly inputs</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-[var(--text-main)]">
            {inputs.map(([k, label]) => <span key={k}>{label}: <b>{money(r[k])}</b></span>)}
          </div>
        </div>
      )}

      {r.adjustments?.length > 0 && (
        <div>
          <p className={LABEL}>One-off lines</p>
          <ul className="space-y-1 text-[12px] text-[var(--text-main)]">
            {r.adjustments.map((a, i) => (
              <li key={`${a.code}-${i}`}>
                {a.name || a.code} <span className="text-[var(--text-muted)]">({a.component_type})</span>: <b>{money(a.amount)}</b>
                {a.reason && <span className="text-[var(--text-muted)]"> — {a.reason}</span>}
                {a.reference && <span className="text-[var(--text-muted)]"> · ref {a.reference}</span>}
                {a.carry_forward_id && <span className="ml-1"><Chip tone="accent">Carried in</Chip></span>}
                {a.approval_status === 'Approved' && (
                  <span className="ml-1"><Chip tone="good">Approved{a.approved_by_name ? ` by ${a.approved_by_name}` : ''}</Chip></span>
                )}
                {a.approval_status === 'Pending' && (
                  <span className="ml-1 inline-flex items-center gap-1.5">
                    <Chip tone="warn">Needs approval</Chip>
                    {onApproveLine && (
                      <button type="button" onClick={() => onApproveLine(r, i)}
                        className="text-[11.5px] font-bold text-[var(--accent-indigo)] hover:underline">
                        Approve
                      </button>
                    )}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {issues.length > 0 && (
        <ul className="space-y-1 text-[12px]">
          {issues.map((e, i) => (
            <li key={`${e.code || e.message}-${i}`} className={e.severity === 'critical'
              ? 'text-[var(--accent-red)] font-semibold' : 'text-[var(--accent-orange)]'}>
              {e.severity === 'critical' ? 'Critical: ' : 'Warning: '}{e.message}
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-[var(--text-muted)]">
        <span>Structured gross {money(r.structured_gross)} → prorated {money(r.prorated_gross)}</span>
        <span>Cost to company this month <b className="text-[var(--text-main)]">{money(r.cost_to_company)}</b></span>
        {r.remarks && <span>Remarks: <span className="text-[var(--text-main)]">{r.remarks}</span></span>}
      </div>
    </div>
  );
};

// ── Adjust one employee's inputs ──
const AdjustRecordModal = ({ period, record, scope, onClose, onDone, showSuccess, showError }) => {
  const [values, setValues] = useState(() => Object.fromEntries(
    FIXED_INPUTS.map(([k]) => [k, String(record[k] ?? 0)])));
  const [remarks, setRemarks] = useState(record.remarks || '');
  const [components, setComponents] = useState([]);
  // Lines carried in from a post-lock correction are the server's to keep: shown, never sent.
  const carried = (record.adjustments || []).filter((a) => a.carry_forward_id);
  const [lines, setLines] = useState(() => (record.adjustments || [])
    .filter((a) => !a.carry_forward_id)
    .map((a) => ({ code: a.code, amount: String(a.amount ?? ''), reason: a.reason || '', reference: a.reference || '' })));
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  useEffect(() => {
    listSalaryComponents(scope)
      .then(({ data }) => setComponents((data || []).filter((c) => c.active !== false)))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addLine = () => setLines((l) => [
    ...l, { code: components[0]?.code || '', amount: '', reason: '', reference: '' },
  ]);
  const updateLine = (i, key, value) =>
    setLines((l) => l.map((row, idx) => (idx === i ? { ...row, [key]: value } : row)));
  const removeLine = (i) => setLines((l) => l.filter((_, idx) => idx !== i));

  const submit = () => {
    const nums = Object.fromEntries(FIXED_INPUTS.map(([k]) => [k, Number(values[k]) || 0]));
    if (Object.values(nums).some((n) => n < 0) || lines.some((l) => Number(l.amount) < 0)) {
      showError('Amounts cannot be negative — use a deduction or recovery line instead.');
      return;
    }
    if (lines.some((l) => !l.code || !l.reason.trim())) {
      showError('Every one-off line needs a component and a reason.');
      return;
    }
    run(async () => {
      await adjustPayrollRecord(period, record.employee_code,
        { ...nums, remarks: remarks.trim() || undefined }, scope);
      await setPayrollAdjustments(period, record.employee_code, lines.map((l) => ({
        code: l.code, amount: Number(l.amount) || 0,
        reason: l.reason.trim(), reference: l.reference.trim() || undefined,
      })), scope);
    }, 'Record adjusted.');
  };

  const autos = AUTO_INPUTS.filter(([k]) => Number(record[k]) > 0);

  return (
    <Modal title={`Adjust ${record.employee_name || record.employee_code}`} labelledBy="adjust-title" wide
      subtitle="PF, tax and other monthly amounts are typed in here. They are kept when the run is recalculated."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Btn>
        </>
      )}
    >
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {FIXED_INPUTS.map(([k, label]) => (
          <div key={k}>
            <label className={LABEL} htmlFor={`adj-${k}`}>{label}</label>
            <input id={`adj-${k}`} type="number" min="0" inputMode="decimal" value={values[k]} className={FIELD}
              onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))} />
          </div>
        ))}
      </div>
      {autos.length > 0 && (
        <p className="text-[11.5px] text-[var(--text-muted)]">
          Worked out automatically: {autos.map(([k, label]) => `${label} ${money(record[k])}`).join(' · ')}.
        </p>
      )}

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className={LABEL}>One-off pay items</label>
          <Btn onClick={addLine} disabled={!components.length}>Add line</Btn>
        </div>
        {!lines.length && !carried.length && (
          <p className="text-[12px] text-[var(--text-muted)]">
            Any earning or deduction beyond the fields above — against the same component
            list the salary structure uses. Each line needs a reason.
          </p>
        )}
        <div className="space-y-2">
          {lines.map((row, i) => (
            <div key={i} className="rounded-lg border border-[var(--border)] p-2.5 space-y-2">
              <div className="grid grid-cols-[1fr_100px_auto] sm:grid-cols-[1fr_130px_auto] gap-2 items-center">
                <select className={FIELD} value={row.code} aria-label="Component"
                  onChange={(e) => updateLine(i, 'code', e.target.value)}>
                  {components.map((c) => (
                    <option key={c.code} value={c.code}>{c.name} ({c.component_type})</option>
                  ))}
                </select>
                <input type="number" min="0" inputMode="decimal" className={FIELD} value={row.amount}
                  aria-label="Amount" placeholder="Amount"
                  onChange={(e) => updateLine(i, 'amount', e.target.value)} />
                <button type="button" onClick={() => removeLine(i)} aria-label="Remove line"
                  className="h-9 w-9 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--accent-red)]">
                  ×
                </button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <input className={FIELD} value={row.reason} placeholder="Reason *" aria-label="Reason"
                  onChange={(e) => updateLine(i, 'reason', e.target.value)} />
                <input className={FIELD} value={row.reference} placeholder="Reference (approval, ticket…)"
                  aria-label="Reference" onChange={(e) => updateLine(i, 'reference', e.target.value)} />
              </div>
            </div>
          ))}
        </div>
        {carried.length > 0 && (
          <div className="mt-2 rounded-lg bg-[var(--accent-indigo-bg)] p-2.5 space-y-1">
            <p className="text-[11.5px] font-bold text-[var(--accent-indigo)]">
              Carried in from an earlier month (cannot be changed here)
            </p>
            {carried.map((a, i) => (
              <p key={`${a.carry_forward_id}-${i}`} className="text-[12px] text-[var(--text-main)]">
                {a.name || a.code}: <b>{money(a.amount)}</b>
                {a.reason && <span className="text-[var(--text-muted)]"> — {a.reason}</span>}
              </p>
            ))}
          </div>
        )}
      </div>

      <div>
        <label className={LABEL} htmlFor="adjust-remarks">Remarks</label>
        <textarea id="adjust-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

export default RunDetailModal;
