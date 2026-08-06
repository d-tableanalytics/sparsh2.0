import React, { useState } from 'react';
import { X, Check, Clock, ShieldCheck, Rocket, Pencil, Trash2 } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { actOnRequisition, deleteRequisition, closeRequisition } from '../../../services/hrmsApi';
import ApprovalDialog from './ApprovalDialog';

/**
 * HRMS ▸ requisition detail drawer.
 *
 * Shows the full record, a 4-step stepper, and — critically — an action bar that appears
 * ONLY at the matching stage and ONLY for the role that owns that stage.
 *
 * Stage actions are driven by the same two capabilities the server enforces
 * (`requisition.review_hr`, `requisition.approve_md`), which are deliberately held by
 * different roles: HR forwards, MD approves. A two-stage approval one person can complete
 * alone is not a control.
 */

const STEPS = ['Raised', 'HR Review', 'MD Approval', 'Approved'];

const stepIndex = (status) => ({
  'Pending HR Review': 1,
  'Pending MD Approval': 2,
  Approved: 4,
  Rejected: -1,
}[status] ?? 0);

const Stepper = ({ status }) => {
  const reached = stepIndex(status);
  const rejected = status === 'Rejected';
  return (
    <div className="flex items-center gap-1">
      {STEPS.map((label, i) => {
        const done = !rejected && reached > i;
        const active = !rejected && reached === i + 1;
        return (
          <React.Fragment key={label}>
            <div className="flex flex-col items-center gap-1 min-w-[62px]">
              <div className={`h-6 w-6 rounded-full grid place-items-center text-[10px] font-bold ${
                rejected ? 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]'
                : done ? 'bg-[var(--accent-indigo)] text-white'
                : active ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] ring-2 ring-[var(--accent-indigo)]'
                : 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}>
                {done ? <Check size={12} /> : i + 1}
              </div>
              <span className={`text-[10px] font-bold text-center leading-tight ${
                active || done ? 'text-[var(--text-main)]' : 'text-[var(--text-muted)]'}`}>
                {label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div className={`h-px flex-1 ${done ? 'bg-[var(--accent-indigo)]' : 'bg-[var(--border)]'}`} />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
};

const Info = ({ label, value }) => (
  <div>
    <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{label}</p>
    <p className="mt-0.5 text-[13px] font-semibold text-[var(--text-main)] break-words">{value || '—'}</p>
  </div>
);

const RequisitionDrawer = ({ requisition: req, onClose, onChanged, onEdit }) => {
  const { can, scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [dialog, setDialog] = useState(null);   // 'hr' | 'md'
  const [busy, setBusy] = useState(false);

  const isPendingHr = req.approval_status === 'Pending HR Review';
  const isPendingMd = req.approval_status === 'Pending MD Approval';
  const canReviewHr = can(CAP.REQUISITION_REVIEW_HR) && isPendingHr;
  const canApproveMd = can(CAP.REQUISITION_APPROVE_MD) && isPendingMd;
  const canEdit = can(CAP.REQUISITION_WRITE) && (isPendingHr || isPendingMd);

  const act = async (action, remarks, salaryChange) => {
    setBusy(true);
    try {
      await actOnRequisition(req.request_no, { action, remarks, salary_change: salaryChange }, scope);
      showSuccess(
        action === 'hr-approve' ? `${req.request_no} forwarded to MD`
        : action === 'md-approve' ? `${req.request_no} approved — posting enabled`
        : `${req.request_no} rejected`);
      setDialog(null);
      onChanged();
    } catch (err) {
      // The server's 409 explains exactly why (wrong stage, or someone else moved it first);
      // surfacing it verbatim beats any message we could invent.
      showError(err?.response?.data?.detail || 'Could not complete that action.');
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete requisition ${req.request_no}? This cannot be undone.`)) return;
    try {
      await deleteRequisition(req.request_no, scope);
      showSuccess(`${req.request_no} deleted`);
      onChanged();
      onClose();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not delete.');
    }
  };

  const setClosing = async (status) => {
    try {
      await closeRequisition(req.request_no, status, scope);
      showSuccess(`${req.request_no} set to ${status}`);
      onChanged();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not update the status.');
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm" onClick={onClose} />
      <aside className="fixed right-0 top-0 h-screen w-full max-w-2xl z-50 bg-[var(--bg-card)] border-l border-[var(--border)] shadow-2xl overflow-y-auto">
        <div className="sticky top-0 bg-[var(--bg-card)] border-b border-[var(--border)] px-5 py-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono text-[12.5px] font-bold text-[var(--text-main)]">{req.request_no}</span>
              <span className="px-2 py-0.5 rounded-md text-[11px] font-bold bg-[var(--input-bg)] text-[var(--text-muted)]">
                {req.approval_status}
              </span>
              <span className="px-2 py-0.5 rounded-md text-[11px] font-bold bg-[var(--input-bg)] text-[var(--text-muted)]">
                {req.closing_status}
              </span>
            </div>
            <h2 className="mt-1 text-[16px] font-bold text-[var(--text-main)] truncate">
              {req.designation_name}
            </h2>
            <p className="text-[12px] text-[var(--text-muted)]">
              {req.department_name} · raised by {req.created_by_name}
            </p>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {canEdit && (
              <button type="button" onClick={() => onEdit(req)} title="Edit"
                className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
                <Pencil size={16} />
              </button>
            )}
            {can(CAP.REQUISITION_WRITE) && req.approval_status !== 'Approved' && (
              <button type="button" onClick={remove} title="Delete"
                className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)]">
                <Trash2 size={16} />
              </button>
            )}
            <button type="button" onClick={onClose}
              className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
              <X size={17} />
            </button>
          </div>
        </div>

        <div className="p-5 space-y-5">
          <Stepper status={req.approval_status} />

          {/* Stage-specific action bars. Each renders only at its matching status AND only
              for the role that owns that stage. */}
          {canReviewHr && (
            <div className="p-3.5 rounded-xl border border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-2 text-[12.5px] font-semibold text-[var(--accent-indigo)]">
                <ShieldCheck size={15} /> Awaiting your HR review
              </div>
              <button type="button" onClick={() => setDialog('hr')}
                className="h-8 px-3.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold">
                Review &amp; forward
              </button>
            </div>
          )}
          {canApproveMd && (
            <div className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-2 text-[12.5px] font-semibold text-[var(--text-main)]">
                <Clock size={15} /> Awaiting your approval
              </div>
              <button type="button" onClick={() => setDialog('md')}
                className="h-8 px-3.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold">
                Approve / Reject
              </button>
            </div>
          )}
          {isPendingHr && !canReviewHr && (
            <div className="p-3 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] text-[12px] text-[var(--text-muted)]">
              Waiting on HR to review this requisition.
            </div>
          )}
          {isPendingMd && !canApproveMd && (
            <div className="p-3 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] text-[12px] text-[var(--text-muted)]">
              Reviewed by {req.hr_reviewed_by_name || 'HR'} — waiting on MD approval.
            </div>
          )}
          {req.approval_status === 'Approved' && (
            <div className="p-3 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] flex items-center gap-2 text-[12.5px] font-semibold text-[var(--text-main)]">
              <Rocket size={15} /> Approved by {req.approved_by_name} — posting enabled.
            </div>
          )}
          {req.approval_status === 'Rejected' && (
            <div className="p-3 rounded-xl border border-[var(--accent-red)]/30 bg-[var(--accent-red-bg)]">
              <p className="text-[12.5px] font-bold text-[var(--accent-red)]">Rejected</p>
              <p className="mt-0.5 text-[12px] text-[var(--accent-red)]">
                {req.md_remarks || req.hr_remarks || 'No reason recorded.'}
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            <Info label="Vacancies" value={req.vacancy} />
            <Info label="Required by" value={req.required_date} />
            <Info label="Urgency" value={req.urgency_level} />
            <Info label="Experience" value={req.experience_required} />
            <Info label="Qualification" value={req.qualification} />
            <Info label="Offered CTC" value={req.offering_ctc != null ? `₹${Number(req.offering_ctc).toLocaleString('en-IN')}` : '—'} />
            <Info label="Work location" value={req.work_location} />
            <Info label="Employment type" value={req.employment_type} />
            <Info label="Assignee" value={req.assignee_name} />
          </div>

          <div>
            <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Required skills</p>
            <p className="mt-1 text-[13px] text-[var(--text-main)] whitespace-pre-wrap">{req.essential_skills}</p>
          </div>

          {req.jd && (
            <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] space-y-3">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <p className="text-[13px] font-bold text-[var(--text-main)]">
                  Job description <span className="font-mono text-[11.5px] text-[var(--text-muted)]">{req.jd.jd_no}</span>
                </p>
                <span className="px-2 py-0.5 rounded-md text-[11px] font-bold bg-[var(--bg-card)] text-[var(--text-muted)]">
                  {req.jd.status}
                </span>
              </div>
              {req.jd.title && <p className="text-[13px] font-semibold text-[var(--text-main)]">{req.jd.title}</p>}
              {req.jd.responsibilities && (
                <div>
                  <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Responsibilities</p>
                  <p className="mt-1 text-[12.5px] text-[var(--text-main)] whitespace-pre-wrap">{req.jd.responsibilities}</p>
                </div>
              )}
              {req.jd.benefits && (
                <div>
                  <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Benefits</p>
                  <p className="mt-1 text-[12.5px] text-[var(--text-main)] whitespace-pre-wrap">{req.jd.benefits}</p>
                </div>
              )}
            </div>
          )}

          {can(CAP.REQUISITION_CLOSE) && req.approval_status === 'Approved' && (
            <div>
              <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">Closing status</p>
              <div className="flex flex-wrap gap-1.5">
                {['Open', 'Hired', 'Hold', 'Closed', 'Cancel'].map((s) => (
                  <button key={s} type="button" onClick={() => setClosing(s)}
                    className={`px-2.5 py-1 rounded-lg text-[11.5px] font-bold border transition-colors ${
                      req.closing_status === s
                        ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                        : 'border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </aside>

      {dialog === 'hr' && (
        <ApprovalDialog
          title={`Forward ${req.request_no} to MD?`}
          subtitle={`${req.designation_name} · ${req.vacancy} vacancy`}
          approveLabel="Forward to MD" busy={busy}
          onApprove={(remarks) => act('hr-approve', remarks)}
          onReject={(remarks) => act('hr-reject', remarks)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'md' && (
        <ApprovalDialog
          title={`Approve ${req.request_no}?`}
          subtitle={req.hr_remarks ? `HR remark: ${req.hr_remarks}` : `${req.designation_name} · ${req.vacancy} vacancy`}
          approveLabel="Approve" showSalary salaryDefault={req.offering_ctc ?? ''} busy={busy}
          onApprove={(remarks, salary) => act('md-approve', remarks, salary)}
          onReject={(remarks) => act('md-reject', remarks)}
          onClose={() => setDialog(null)}
        />
      )}
    </>
  );
};

export default RequisitionDrawer;
