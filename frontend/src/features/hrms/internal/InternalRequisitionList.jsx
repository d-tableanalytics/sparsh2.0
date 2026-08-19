import React, { useCallback, useEffect, useState } from 'react';
import { Building, Plus, Timer } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import ApprovalDialog from '../recruitment/ApprovalDialog';
import RequisitionFormModal from '../recruitment/RequisitionFormModal';
import {
  getRequisitions, actOnRequisition, getRequisitionSla,
} from '../../../services/hrmsApi';
import { day, toneFor } from './internalKit';
import {
  Btn, Chip, Facts, Modal, RecordList,
} from './internalKit.jsx';

/**
 * HRMS ▸ internal track — requisitions.
 *
 * The same list as the client track, filtered to `track=internal` and showing the gate each
 * requisition is actually sitting at. `RequisitionFormModal` and `ApprovalDialog` are REUSED
 * rather than cloned — the chain differs in its states, not in what an approval dialog is.
 *
 * The screen's job is to answer "what is this waiting on, and can I clear it". So the action
 * offered on each row is derived from the requisition's own state and the caller's
 * capabilities, never from a fixed set of buttons that 403 when pressed.
 */

/** state -> (action, who clears it, capability). One table, so the button, the label and the
 *  gate can never disagree with each other. */
const GATES = {
  'Pending HR Verification': {
    action: 'hr-verify', reject: 'hr-reject', cap: CAP.REQUISITION_REVIEW_HR,
    label: 'Verify', who: 'HR',
    blurb: 'HR checks the role and its justification are complete.',
  },
  'Pending Budget Approval': {
    action: 'budget-approve', reject: 'budget-reject',
    cap: CAP.REQUISITION_APPROVE_BUDGET, label: 'Approve budget',
    who: 'Management or Finance', band: true,
    blurb: 'Nothing may be sourced until the headcount and salary band are approved.',
  },
  'Pending Escalation': {
    action: 'escalate-approve', reject: 'escalate-reject', cap: CAP.REQUISITION_ESCALATE,
    label: 'Clear escalation', who: 'the reporting line',
    blurb: 'Raised above the sanctioned headcount, so it routes up the reporting line.',
  },
  'Pending Scorecard Approval': {
    action: 'scorecard-approve', reject: 'scorecard-reject', cap: CAP.SCORECARD_APPROVE,
    label: 'Approve', who: 'the hiring manager',
    blurb: 'Needs an approved position scorecard before it can be approved.',
  },
};

const InternalRequisitionList = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [raising, setRaising] = useState(false);
  const [deciding, setDeciding] = useState(null);
  const [busy, setBusy] = useState(false);
  const [slaFor, setSlaFor] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getRequisitions({ ...scope, track: 'internal', limit: 200 });
      setRows(data?.requisitions || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load internal requisitions.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const gateFor = (row) => {
    const gate = GATES[row.approval_status];
    return gate && can(gate.cap) ? gate : null;
  };

  const act = async (row, action, remarks, _salary, budget) => {
    setBusy(true);
    try {
      await actOnRequisition(row.request_no, { action, remarks, ...(budget || {}) }, scope);
      showSuccess(`${row.request_no} — ${action.replace('-', ' ')}d`);
      setDeciding(null);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the decision.');
    } finally {
      setBusy(false);
    }
  };

  const columns = [
    { key: 'req', label: 'Requisition',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">
            {r.designation_name}
          </span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.request_no} · {r.department_name || '—'}
          </span>
        </>
      ) },
    { key: 'seats', label: 'Seats', align: 'right',
      render: (r) => (
        <>
          <span className="text-[var(--text-main)]">{r.vacancy}</span>
          {r.approved_headcount != null && r.approved_headcount !== r.vacancy && (
            <span className="block text-[11px] text-[var(--text-muted)]">
              {r.approved_headcount} approved
            </span>
          )}
        </>
      ) },
    { key: 'band', label: 'Approved band',
      render: (r) => (
        r.approved_salary_band_min != null ? (
          <span className="text-[var(--text-muted)] tabular-nums">
            {Number(r.approved_salary_band_min).toLocaleString()}
            {' – '}
            {Number(r.approved_salary_band_max).toLocaleString()}
          </span>
        ) : <span className="text-[var(--text-muted)]">not approved</span>
      ) },
    { key: 'stage', label: 'Waiting on',
      render: (r) => {
        const gate = GATES[r.approval_status];
        return (
          <>
            <Chip tone={toneFor(r.approval_status)}>{r.approval_status}</Chip>
            {gate && (
              <span className="block text-[11px] text-[var(--text-muted)] mt-1">
                {gate.who}
              </span>
            )}
          </>
        );
      } },
    { key: 'actions', label: '', align: 'right',
      render: (r) => {
        const gate = gateFor(r);
        return (
          <div className="flex flex-col items-end gap-1.5">
            {gate && (
              <Btn tone="primary" onClick={() => setDeciding({ row: r, gate })}>
                {gate.label}
              </Btn>
            )}
            <Btn tone="ghost" onClick={() => setSlaFor(r)}>
              <Timer size={13} /> SLA
            </Btn>
          </div>
        );
      } },
  ];

  const renderCard = (r) => {
    const gate = gateFor(r);
    return (
      <div className="space-y-2.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-[13px] font-bold text-[var(--text-main)]">
              {r.designation_name}
            </p>
            <p className="text-[11.5px] text-[var(--text-muted)]">{r.request_no}</p>
          </div>
          <Chip tone={toneFor(r.approval_status)}>{r.approval_status}</Chip>
        </div>
        <Facts items={[
          { label: 'Seats', value: r.vacancy },
          { label: 'Band',
            value: r.approved_salary_band_min != null
              ? `${Number(r.approved_salary_band_min).toLocaleString()}–`
                + `${Number(r.approved_salary_band_max).toLocaleString()}`
              : 'not approved' },
          { label: 'Raised', value: day(r.created_at) },
        ]} />
        <div className="flex gap-2 flex-wrap">
          {gate && (
            <Btn tone="primary" onClick={() => setDeciding({ row: r, gate })}>
              {gate.label}
            </Btn>
          )}
          <Btn tone="ghost" onClick={() => setSlaFor(r)}>SLA</Btn>
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Building}
        title="Internal requisitions"
        subtitle="Sparsh Magic's own vacancies — budget approved internally, no client"
        actions={can(CAP.REQUISITION_CREATE) && (
          <Btn tone="primary" onClick={() => setRaising(true)}>
            <Plus size={14} /> Raise
          </Btn>
        )}
      />
      <HrmsScopeBar />

      {loading && <HrmsLoading label="Loading internal requisitions…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && (
        <RecordList
          rows={rows} columns={columns} renderCard={renderCard}
          keyOf={(r) => r.request_no}
          empty={<HrmsEmpty
            icon={Building}
            title="No internal requisitions"
            hint="Raise one and switch the hiring track to Sparsh Magic (internal)."
          />}
        />
      )}

      {raising && (
        <RequisitionFormModal
          onClose={() => setRaising(false)}
          onSaved={() => { setRaising(false); load(); }}
        />
      )}

      {deciding && (
        <ApprovalDialog
          title={`${deciding.gate.label} — ${deciding.row.request_no}`}
          subtitle={deciding.gate.blurb}
          approveLabel={deciding.gate.label}
          requisition={deciding.row}
          showBudgetBand={!!deciding.gate.band}
          busy={busy}
          onApprove={(remarks, salary, budget) =>
            act(deciding.row, deciding.gate.action, remarks, salary, budget)}
          onReject={(remarks) => act(deciding.row, deciding.gate.reject, remarks)}
          onClose={() => setDeciding(null)}
        />
      )}

      {slaFor && (
        <SlaModal row={slaFor} scope={scope} onClose={() => setSlaFor(null)} />
      )}
    </div>
  );
};

/** Milestone targets against actuals. Everything except the actual timestamps is computed
 *  server-side on read, so this renders the answer rather than working one out. */
const SlaModal = ({ row, scope, onClose }) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getRequisitionSla(row.request_no, scope)
      .then(({ data: d }) => setData(d))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load the SLA.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Modal
      title={`SLA — ${row.request_no}`} labelledBy="sla-title"
      subtitle={data?.basis} onClose={onClose}
      footer={<Btn onClick={onClose}>Close</Btn>}
    >
      {error && <HrmsError message={error} />}
      {!data && !error && <HrmsLoading label="Reading milestones…" />}
      {data && (
        <ul className="space-y-2">
          {data.milestones.map((m) => (
            <li key={m.key}
              className="flex items-start justify-between gap-3 rounded-lg
                border border-[var(--border)] px-3 py-2.5">
              <div className="min-w-0">
                <p className="text-[12.5px] font-semibold text-[var(--text-main)]">
                  {m.label}
                </p>
                <p className="text-[11px] text-[var(--text-muted)]">
                  {m.target_working_days != null
                    ? `${m.target_working_days} working days from ${m.measured_from}`
                    : `Due ${day(m.due_on)}`}
                  {m.working_days_taken != null && ` · took ${m.working_days_taken}`}
                </p>
              </div>
              <Chip tone={toneFor(m.status)}>{m.status.replace('_', ' ')}</Chip>
            </li>
          ))}
          {!data.milestones.length && (
            <p className="text-[12.5px] text-[var(--text-muted)]">
              {data.reason || 'No milestones apply.'}
            </p>
          )}
        </ul>
      )}
    </Modal>
  );
};

export default InternalRequisitionList;
