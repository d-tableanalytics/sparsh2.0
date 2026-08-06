import React, { useState } from 'react';
import { X, CheckCircle2, XCircle } from 'lucide-react';

/**
 * HRMS ▸ approval dialog.
 *
 * Shared by both stages of the requisition chain, and reused by assessments, interviews and
 * offers in later phases — which is why the copy, the capability and the action strings are
 * all props rather than baked in.
 *
 * A remark is mandatory to reject and optional to approve: a rejection that does not say why
 * is not actionable by the person who has to fix it. The server enforces the same rule, so
 * this is an affordance, not the control.
 */
const ApprovalDialog = ({
  title,
  subtitle,
  approveLabel = 'Approve',
  rejectLabel = 'Reject',
  showSalary = false,
  salaryLabel = 'Revised CTC (optional)',
  salaryDefault = '',
  busy = false,
  onApprove,
  onReject,
  onClose,
}) => {
  const [remarks, setRemarks] = useState('');
  const [salary, setSalary] = useState(salaryDefault ?? '');
  const [error, setError] = useState('');

  const reject = () => {
    if (!remarks.trim()) {
      setError('A reason is required when rejecting.');
      return;
    }
    onReject(remarks.trim());
  };

  const approve = () => {
    onApprove(remarks.trim(), salary === '' ? null : Number(salary));
  };

  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
        <div className="flex items-start justify-between px-5 py-4 border-b border-[var(--border)]">
          <div>
            <h2 className="text-[15px] font-bold text-[var(--text-main)]">{title}</h2>
            {subtitle && <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">{subtitle}</p>}
          </div>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <div className="p-5 space-y-3">
          {showSalary && (
            <div>
              <label htmlFor="ap-salary" className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">
                {salaryLabel}
              </label>
              <input
                id="ap-salary" type="number" min="0" value={salary}
                onChange={(e) => setSalary(e.target.value)}
                className="w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]"
              />
            </div>
          )}

          <div>
            <label htmlFor="ap-remarks" className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">
              Remarks
            </label>
            <textarea
              id="ap-remarks" rows={3} value={remarks}
              onChange={(e) => { setRemarks(e.target.value); setError(''); }}
              placeholder="Add a note — required if you reject…"
              className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] resize-none"
            />
            {error && <p className="mt-1 text-[11.5px] font-semibold text-[var(--accent-red)]">{error}</p>}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose} disabled={busy}
            className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
            Cancel
          </button>
          <button type="button" onClick={reject} disabled={busy}
            className="h-9 px-4 rounded-lg bg-[var(--accent-red-bg)] text-[var(--accent-red)] text-[12px] font-bold flex items-center gap-1.5 disabled:opacity-50">
            <XCircle size={14} /> {rejectLabel}
          </button>
          <button type="button" onClick={approve} disabled={busy}
            className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5 disabled:opacity-50">
            <CheckCircle2 size={14} /> {busy ? 'Working…' : approveLabel}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ApprovalDialog;
