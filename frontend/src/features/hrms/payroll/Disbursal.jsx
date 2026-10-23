import React, { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle, Download, Landmark, RotateCcw, FileSpreadsheet, Scale,
} from 'lucide-react';
import { CAP } from '../access';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import {
  listPaymentBatches, generatePaymentBatch, getPaymentBatch, downloadBankFile,
  updatePaymentStatus, importPaymentStatuses,
  exportPaymentBatch, exportPeriodPayments,
  getPayrollReconciliation, exportPayrollReconciliation,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, money, day } from '../internal/internalKit';
import { Btn, Chip, Modal } from '../internal/internalKit.jsx';
import {
  PAYMENT_MODES, PAYMENT_STATUSES, paymentTone, errText, blobErrText, saveBlob, when,
  parseBankResponse, useSubmit,
} from './payrollKit';

/**
 * HRMS ▸ Payroll ▸ salary disbursal (FRD §13).
 *
 * Only from a LOCKED month: generate a payment batch, download its bank file, upload that to
 * the bank yourself, then record what the bank did — one payment at a time or by pasting the
 * bank's response. Failed payments are retried as a NEW batch that points back at the old
 * one, so nothing is paid twice. When every payable employee is Processed the run turns Paid
 * on its own, and the period can be closed.
 *
 * Account numbers are masked everywhere on screen; the full number only ever appears in the
 * bank file, for the holder of payroll approval, and every download is audited server-side.
 */

const retryableIn = (batch) => ['Failed', 'Partially Failed'].includes(batch.status);

const Disbursal = ({ period, runStatus, scope, can, showSuccess, showError, onChanged }) => {
  const [batches, setBatches] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState('NEFT');
  const [justSkipped, setJustSkipped] = useState(null);
  const [openBatch, setOpenBatch] = useState(null);
  const [downloading, setDownloading] = useState(null);
  // P1-127 / P1-112. `exporting` names WHICH export is running, because three of them
  // share this toolbar and a single boolean would grey out all three.
  const [exporting, setExporting] = useState(null);
  const [recon, setRecon] = useState(null);

  const canPay = can(CAP.PAYROLL_APPROVE);
  const canGenerate = canPay && (runStatus === 'Locked' || runStatus === 'Paid');

  const load = useCallback(async () => {
    setError(null);
    try {
      const { data } = await listPaymentBatches(period, scope);
      setBatches(data?.batches || []);
      setSummary(data?.summary || null);
    } catch (err) {
      setError(errText(err, 'Could not load payment batches.'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  useEffect(() => { load(); }, [load]);

  const refresh = () => { load(); onChanged?.(); };
  const { busy, run } = useSubmit(showSuccess, showError, refresh);

  const generate = (retryOf = null, retryMode = null) => run(async () => {
    const { data } = await generatePaymentBatch(period, {
      payment_mode: retryMode || mode, ...(retryOf ? { retry_of: retryOf } : {}),
    }, scope);
    setJustSkipped(data?.skipped?.length ? { batchNo: data.batch_no, skipped: data.skipped } : null);
  }, retryOf ? `Retry batch generated for ${retryOf}.` : 'Payment batch generated.');

  const download = async (batch) => {
    setDownloading(batch.batch_no);
    try {
      const { data } = await downloadBankFile(batch.batch_no, scope);
      saveBlob(data, `${batch.batch_no}_${period}.csv`);
      load();
    } catch (err) {
      showError(await blobErrText(err, 'Could not download the bank file.'));
    } finally {
      setDownloading(null);
    }
  };

  /** P1-127. A status and reconciliation document, so the account stays masked — the
   *  full numbers are in the bank file, which is gated and audited separately. */
  const exportRows = (key, fn, label) => async () => {
    setExporting(key);
    try {
      const result = await fn();
      showSuccess(`Exported ${result.rows} ${label}.`);
    } catch (err) {
      showError(await blobErrText(err, 'Could not export that.'));
    } finally {
      setExporting(null);
    }
  };

  /** P1-112. Shown before it is downloaded: the figures are the point, and a difference
   *  of zero is the answer somebody wants on screen rather than in a file. */
  const loadRecon = async () => {
    setExporting('recon-view');
    try {
      const { data } = await getPayrollReconciliation(period, scope);
      setRecon(data);
    } catch (err) {
      showError(errText(err, 'Could not reconcile this period.'));
    } finally {
      setExporting(null);
    }
  };

  if (loading) return <HrmsLoading label="Loading payments…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;

  const leftToPay = (summary?.not_in_batch || 0) + (summary?.failed || 0);

  return (
    <div className="space-y-4">
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
          {[
            { label: 'To pay', value: summary.payable, hint: money(summary.payable_amount) },
            { label: 'Paid', value: summary.paid, hint: money(summary.paid_amount), tone: 'good' },
            { label: 'With the bank', value: summary.pending, hint: 'Pending' },
            { label: 'Failed', value: summary.failed, hint: 'Not yet retried', tone: summary.failed ? 'bad' : null },
            { label: 'Not in a batch', value: summary.not_in_batch, hint: `${summary.unpaid} unpaid in all` },
          ].map((c) => (
            <div key={c.label} className="rounded-lg border border-[var(--border)] px-3 py-2.5 min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] truncate">{c.label}</p>
              <p className={`text-[15px] font-bold tabular-nums ${c.tone === 'good' ? 'text-[var(--accent-green)]'
                : c.tone === 'bad' ? 'text-[var(--accent-red)]' : 'text-[var(--text-main)]'}`}>{c.value}</p>
              <p className="text-[10.5px] text-[var(--text-muted)] truncate">{c.hint}</p>
            </div>
          ))}
        </div>
      )}

      {canGenerate && (
        <div className="rounded-xl border border-[var(--border)] p-3.5 space-y-2.5">
          <p className="text-[13px] font-bold text-[var(--text-main)]">Generate a payment batch</p>
          <p className="text-[12px] text-[var(--text-muted)]">
            Takes everyone with pay due who is not already in a pending or paid batch. Bank
            transfers need the employee&apos;s account and IFSC; anyone without them is skipped
            and listed. Cash, Cheque and Manual Advice do not need bank details.
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <div className="w-full sm:w-48">
              <label className={LABEL} htmlFor="pay-mode">Payment mode</label>
              <select id="pay-mode" value={mode} className={FIELD} onChange={(e) => setMode(e.target.value)}>
                {PAYMENT_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
            <Btn tone="primary" disabled={busy || leftToPay === 0} onClick={() => generate()}>
              <Landmark size={14} /> {busy ? 'Working…' : 'Generate batch'}
            </Btn>
          </div>
          {leftToPay === 0 && (
            <p className="text-[11.5px] text-[var(--text-muted)]">Everyone with pay due is already in a batch.</p>
          )}
        </div>
      )}

      {justSkipped && (
        <SkippedBox batchNo={justSkipped.batchNo} skipped={justSkipped.skipped} strong />
      )}

      {/* P1-127 and P1-112, for the PERIOD rather than one batch. */}
      <div className="flex flex-wrap gap-2">
        <Btn disabled={!!exporting}
          onClick={exportRows('period', () => exportPeriodPayments(period, scope),
            'payment row(s) for the period')}>
          <FileSpreadsheet size={14} />
          {exporting === 'period' ? 'Exporting…' : 'Export all payments'}
        </Btn>
        <Btn disabled={!!exporting} onClick={loadRecon}>
          <Scale size={14} />
          {exporting === 'recon-view' ? 'Reconciling…' : 'Reconcile with payroll'}
        </Btn>
        {recon && (
          <Btn disabled={!!exporting}
            onClick={exportRows('recon', () => exportPayrollReconciliation(period, {
              ...scope, fmt: 'csv',
            }), 'reconciliation line(s)')}>
            <Download size={14} />
            {exporting === 'recon' ? 'Exporting…' : 'Export reconciliation'}
          </Btn>
        )}
      </div>

      {recon && (
        <div className="rounded-xl border border-[var(--border)] p-3.5 space-y-2">
          <div className="flex items-start justify-between gap-2">
            <p className="text-[13px] font-bold text-[var(--text-main)]">
              Payroll versus the bank · {period}
            </p>
            <Chip tone={recon.difference_processed === 0 ? 'good' : 'warn'}>
              {recon.difference_processed === 0 ? 'Settled'
                : `${money(recon.difference_processed)} outstanding`}
            </Chip>
          </div>
          {!recon.final && (
            <p className="text-[11.5px] text-[var(--accent-orange)]">
              The run is {recon.run_status}, not final — these figures are provisional.
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-[11.5px]">
              <thead>
                <tr className="text-left text-[var(--text-muted)]">
                  <th className="py-1 pr-3 font-semibold">Measure</th>
                  <th className="py-1 pr-3 font-semibold">Employees</th>
                  <th className="py-1 pr-3 font-semibold">Amount</th>
                  <th className="py-1 font-semibold">Note</th>
                </tr>
              </thead>
              <tbody>
                {(recon.lines || []).map((l) => (
                  <tr key={l.Measure} className="border-t border-[var(--border-subtle)]">
                    <td className="py-1.5 pr-3 text-[var(--text-main)]">{l.Measure}</td>
                    <td className="py-1.5 pr-3 tabular-nums text-[var(--text-main)]">
                      {l.Employees === '' ? '—' : l.Employees}
                    </td>
                    <td className="py-1.5 pr-3 tabular-nums text-[var(--text-main)]">
                      {money(l.Amount)}
                    </td>
                    <td className="py-1.5 text-[var(--text-muted)]">{l.Note || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!batches.length ? (
        <p className="text-[12px] text-[var(--text-muted)]">
          No payment batches yet.{canGenerate ? ' Generate one above to make the bank file.' : ''}
        </p>
      ) : (
        <div className="space-y-2.5">
          {batches.map((b) => (
            <div key={b.batch_no} className="rounded-xl border border-[var(--border)] p-3.5 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[13px] font-bold text-[var(--text-main)]">{b.batch_no}</p>
                  <p className="text-[11.5px] text-[var(--text-muted)]">
                    {b.payment_mode} · {b.employee_count} payment(s) · {money(b.total_amount)}
                    {b.retry_of && ` · retry of ${b.retry_of}`}
                  </p>
                </div>
                <Chip tone={paymentTone(b.status)}>{b.status}</Chip>
              </div>
              <p className="text-[11.5px] text-[var(--text-muted)]">
                Generated by {b.generated_by_name || '—'} · {when(b.generated_at)} ·{' '}
                {b.file_downloaded_at ? `bank file downloaded ${when(b.file_downloaded_at)}` : 'bank file not downloaded yet'}
              </p>
              {b.skipped?.length > 0 && <SkippedBox batchNo={b.batch_no} skipped={b.skipped} />}
              <div className="flex flex-wrap gap-2">
                <Btn onClick={() => setOpenBatch(b.batch_no)}>Open payments</Btn>
                {canPay && (
                  <Btn disabled={downloading === b.batch_no} onClick={() => download(b)}>
                    <Download size={14} /> {downloading === b.batch_no ? 'Downloading…' : 'Bank file'}
                  </Btn>
                )}
                {/* Deliberately available to anyone who can READ payroll, unlike the bank
                    file above: this carries no payable account number. */}
                <Btn disabled={!!exporting}
                  onClick={exportRows(b.batch_no,
                    () => exportPaymentBatch(b.batch_no, scope), 'payment row(s)')}>
                  <FileSpreadsheet size={14} />
                  {exporting === b.batch_no ? 'Exporting…' : 'Export'}
                </Btn>
                {canPay && runStatus !== 'Closed' && retryableIn(b) && (
                  <Btn disabled={busy} onClick={() => generate(b.batch_no, b.payment_mode)}>
                    <RotateCcw size={14} /> Retry failed
                  </Btn>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {openBatch && (
        <BatchModal batchNo={openBatch} period={period} scope={scope} canPay={canPay}
          canRetry={canPay && runStatus !== 'Closed'}
          onRetry={(b) => { setOpenBatch(null); generate(b.batch_no, b.payment_mode); }}
          onClose={() => setOpenBatch(null)} onChanged={refresh}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const SkippedBox = ({ batchNo, skipped, strong = false }) => (
  <div className={`rounded-lg px-3.5 py-2.5 ${strong ? 'bg-[var(--accent-red-bg)]' : 'bg-[var(--accent-orange-bg)]'}`}>
    <p className={`flex items-center gap-1.5 text-[12.5px] font-bold ${strong
      ? 'text-[var(--accent-red)]' : 'text-[var(--accent-orange)]'}`}>
      <AlertTriangle size={14} className="shrink-0" />
      {skipped.length} employee(s) left out of {batchNo} — not paid
    </p>
    <ul className="mt-1 space-y-0.5 text-[12px] text-[var(--text-main)]">
      {skipped.map((s) => (
        <li key={s.employee_code}>
          {s.employee_name || s.employee_code} ({s.employee_code}) — {s.reason}
        </li>
      ))}
    </ul>
    <p className="mt-1 text-[11px] text-[var(--text-muted)]">
      Add their bank details on the employee&apos;s page, then generate another batch — or pay
      them by Cash / Cheque.
    </p>
  </div>
);

const BatchModal = ({
  batchNo, period, scope, canPay, canRetry, onRetry, onClose, onChanged, showSuccess, showError,
}) => {
  const [batch, setBatch] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [paste, setPaste] = useState('');
  const [importResult, setImportResult] = useState(null);
  const [importing, setImporting] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const { data } = await getPaymentBatch(batchNo, scope);
      setBatch(data);
    } catch (err) {
      setError(errText(err, 'Could not load this batch.'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchNo]);

  useEffect(() => { load(); }, [load]);

  const importPaste = async () => {
    const rows = parseBankResponse(paste);
    if (!rows.length) { showError('Paste at least one line: employee_code,status,utr,payment_date,failure_reason'); return; }
    setImporting(true);
    try {
      const { data } = await importPaymentStatuses(batchNo, rows, scope);
      setImportResult({ updated: data?.updated || 0, errors: data?.errors || [] });
      if (data?.batch) setBatch(data.batch);
      if (data?.updated) showSuccess(`${data.updated} payment(s) updated.`);
      if (!data?.errors?.length) setPaste('');
      onChanged();
    } catch (err) {
      showError(errText(err, 'Could not import the bank response.'));
    } finally {
      setImporting(false);
    }
  };

  const payments = batch?.payments || [];
  const retryable = payments.filter((p) => ['Failed', 'Rejected'].includes(p.status) && !p.retry_batch_no).length;

  return (
    <Modal title={`Payments · ${batchNo}`} labelledBy="batch-title" wide
      subtitle={batch ? `${batch.payment_mode} · ${batch.employee_count} payment(s) · ${money(batch.total_amount)} · ${period}` : period}
      onClose={onClose}
      footer={(
        <>
          {canRetry && retryable > 0 && (
            <Btn onClick={() => onRetry(batch)}><RotateCcw size={14} /> Retry {retryable} failed</Btn>
          )}
          <Btn onClick={onClose}>Close</Btn>
        </>
      )}
    >
      {loading && <HrmsLoading label="Loading payments…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && batch && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Chip tone={paymentTone(batch.status)}>{batch.status}</Chip>
            {batch.retry_of && <span className="text-[11.5px] text-[var(--text-muted)]">Retry of {batch.retry_of}</span>}
          </div>

          <div className="space-y-2">
            {payments.map((p) => (
              <div key={p.employee_code} className="rounded-lg border border-[var(--border)] p-3 space-y-1.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-[12.5px] font-bold text-[var(--text-main)]">
                      {p.employee_name || p.employee_code}
                      <span className="font-normal text-[var(--text-muted)]"> · {p.employee_code}</span>
                    </p>
                    <p className="text-[11.5px] text-[var(--text-muted)] break-words">
                      {[p.account_holder, p.bank_name, p.bank_account, p.bank_ifsc].filter(Boolean).join(' · ')
                        || p.payment_mode}
                    </p>
                  </div>
                  <div className="text-right shrink-0 space-y-1">
                    <p className="text-[12.5px] font-bold tabular-nums text-[var(--text-main)]">{money(p.amount)}</p>
                    <Chip tone={paymentTone(p.status)}>{p.status}</Chip>
                  </div>
                </div>
                {p.status === 'Processed' && (
                  <p className="text-[11.5px] text-[var(--accent-green)]">
                    UTR {p.utr} · paid {day(p.payment_date)}
                  </p>
                )}
                {p.failure_reason && (
                  <p className="text-[11.5px] text-[var(--accent-red)]">{p.failure_reason}</p>
                )}
                {p.retry_batch_no && (
                  <p className="text-[11.5px] text-[var(--text-muted)]">Retried in {p.retry_batch_no} — update it there.</p>
                )}
                {canPay && !p.retry_batch_no && (
                  editing === p.employee_code ? (
                    <PaymentStatusForm batchNo={batchNo} payment={p} scope={scope}
                      onCancel={() => setEditing(null)}
                      onSaved={() => { setEditing(null); load(); onChanged(); }}
                      showSuccess={showSuccess} showError={showError} />
                  ) : (
                    <button type="button" onClick={() => setEditing(p.employee_code)}
                      className="text-[11.5px] font-bold text-[var(--accent-indigo)] hover:underline">
                      Update status
                    </button>
                  )
                )}
              </div>
            ))}
          </div>

          {canPay && (
            <div className="rounded-xl border border-[var(--border)] p-3.5 space-y-2.5">
              <div>
                <label className={LABEL} htmlFor="bank-paste">Paste bank response</label>
                <p className="text-[11.5px] text-[var(--text-muted)] mb-1.5">
                  One line per payment: <code>employee_code,status,utr,payment_date,failure_reason</code>.
                  Status is Processed, Failed, Rejected or Pending; dates as YYYY-MM-DD. A Processed
                  line needs its UTR and date, a Failed / Rejected line its reason.
                </p>
                <textarea id="bank-paste" rows={4} value={paste} className={`${TEXTAREA} font-mono text-[12px]`}
                  placeholder={'EMP001,Processed,UTR123456,2026-10-31,\nEMP002,Failed,,,Account closed'}
                  onChange={(e) => setPaste(e.target.value)} />
              </div>
              <div className="flex justify-end">
                <Btn tone="primary" disabled={importing || !paste.trim()} onClick={importPaste}>
                  {importing ? 'Importing…' : 'Import'}
                </Btn>
              </div>
              {importResult && (
                <div className="space-y-1">
                  <p className="text-[12px] text-[var(--text-main)]">
                    {importResult.updated} updated · {importResult.errors.length} not updated
                  </p>
                  {importResult.errors.length > 0 && (
                    <ul className="rounded-lg bg-[var(--accent-red-bg)] px-3 py-2 space-y-0.5 text-[12px] text-[var(--accent-red)]">
                      {importResult.errors.map((e) => (
                        <li key={`${e.row}-${e.employee_code}`}>
                          Line {e.row}{e.employee_code ? ` (${e.employee_code})` : ''}: {typeof e.error === 'string' ? e.error : 'Invalid row'}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
};

const PaymentStatusForm = ({ batchNo, payment, scope, onCancel, onSaved, showSuccess, showError }) => {
  const [status, setStatus] = useState(payment.status === 'Pending' ? 'Processed' : payment.status);
  const [utr, setUtr] = useState(payment.utr || '');
  const [paymentDate, setPaymentDate] = useState(payment.payment_date || new Date().toLocaleDateString('en-CA'));
  const [reason, setReason] = useState(payment.failure_reason || '');
  const { busy, run } = useSubmit(showSuccess, showError, onSaved);
  const failed = status === 'Failed' || status === 'Rejected';

  const submit = () => {
    if (status === 'Processed' && (!utr.trim() || !paymentDate)) {
      showError('A processed payment needs its UTR and the date the bank paid it.');
      return;
    }
    if (failed && !reason.trim()) { showError('Say why the payment failed.'); return; }
    run(() => updatePaymentStatus(batchNo, payment.employee_code, {
      status, utr: utr.trim() || undefined, payment_date: paymentDate || undefined,
      failure_reason: failed ? reason.trim() : undefined,
    }, scope), `${payment.employee_name || payment.employee_code}: ${status}.`);
  };

  const id = `pay-${payment.employee_code}`;
  return (
    <div className="rounded-lg bg-[var(--input-bg)] p-2.5 space-y-2">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <div>
          <label className={LABEL} htmlFor={`${id}-status`}>Status</label>
          <select id={`${id}-status`} value={status} className={FIELD} onChange={(e) => setStatus(e.target.value)}>
            {PAYMENT_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor={`${id}-utr`}>UTR / reference{status === 'Processed' ? ' *' : ''}</label>
          <input id={`${id}-utr`} value={utr} className={FIELD} onChange={(e) => setUtr(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor={`${id}-date`}>Payment date{status === 'Processed' ? ' *' : ''}</label>
          <input id={`${id}-date`} type="date" value={paymentDate} className={FIELD}
            onChange={(e) => setPaymentDate(e.target.value)} />
        </div>
      </div>
      {failed && (
        <div>
          <label className={LABEL} htmlFor={`${id}-reason`}>Failure reason *</label>
          <input id={`${id}-reason`} value={reason} className={FIELD} onChange={(e) => setReason(e.target.value)} />
        </div>
      )}
      <div className="flex justify-end gap-2">
        <Btn onClick={onCancel} disabled={busy}>Cancel</Btn>
        <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Saving…' : 'Save'}</Btn>
      </div>
    </div>
  );
};

export default Disbursal;
