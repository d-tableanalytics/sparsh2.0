import React, { useCallback, useEffect, useState } from 'react';
import { GitPullRequest, AlertTriangle, CheckCircle2, PlayCircle } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { useNotification } from '../../../context/NotificationContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  listConfigChangeRequests, getConfigChangeRequest, decideConfigChangeRequest,
  activateConfigChangeRequest, getGovernedConfigTypes, setGovernedConfigTypes,
} from '../../../services/hrmsApi';
import { FIELD, LABEL } from '../internal/internalKit';
import { Btn, Chip, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Configuration Approval Inbox (FRD §29, §27).
 *
 * Where a configuration change is reviewed before it reaches live configuration. The flow
 * is Request → Impact Analysis → Simulation → Approval → Activation, and this screen owns
 * the last two: everything before it belongs to whoever drafted the change.
 *
 * Approval and ACTIVATION are deliberately two separate clicks. §27 lists them as separate
 * stages, and they answer different questions — "is this change right?" and "should it take
 * effect now?" — which an administrator may well answer at different times, for a rule
 * approved in advance of its effective date.
 */

const STATUS_TONE = {
  Draft: 'neutral',
  'Impact Analysed': 'neutral',
  Simulated: 'accent',
  'Pending Approval': 'warn',
  Approved: 'accent',
  Active: 'good',
  Rejected: 'bad',
  Returned: 'warn',
  Withdrawn: 'neutral',
};

const when = (value) => (value ? new Date(value).toLocaleString() : '—');

const TYPE_LABEL = {
  policy_version: 'Policy versions — attendance rules, payroll policy',
  salary_component: 'Salary components — formulas, slabs, proration',
  field_definition: 'Custom field definitions — what is mandatory, masked and exported',
};

/**
 * §27 — which kinds of configuration go through this flow at all.
 *
 * The pay-deciding types are shown ticked and DISABLED rather than hidden: an
 * administrator reading this needs to know they are governed, and a box they could untick
 * would be the first thing anyone wanting to skip the flow would reach for. The service
 * adds them back regardless of what is posted, so the lock here is a courtesy to the
 * reader, not the enforcement.
 */
const GovernedTypes = ({ scope, canApprove, showSuccess, showError }) => {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    getGovernedConfigTypes(scope)
      .then(({ data }) => { if (live) setState(data); })
      .catch(() => { if (live) setState(null); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = async (type, on) => {
    const next = on
      ? [...new Set([...(state.governed_config_types || []), type])]
      : (state.governed_config_types || []).filter((t) => t !== type);
    setBusy(true);
    try {
      const { data } = await setGovernedConfigTypes({ entity_types: next }, scope);
      setState(data);
      showSuccess(on ? `${type} changes now need approval.`
        : `${type} changes save directly again.`);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not change that.');
    } finally {
      setBusy(false);
    }
  };

  if (!state) return null;
  const governed = new Set(state.governed_config_types || []);
  const fixed = new Set(state.always_governed || []);

  return (
    <div className="rounded-lg border border-[var(--border)] px-3.5 py-3 space-y-2">
      <div>
        <h3 className="text-[12.5px] font-bold text-[var(--text-main)]">
          What needs approval
        </h3>
        <p className="text-[11.5px] text-[var(--text-muted)]">
          A governed change is drafted, analysed, approved by somebody else and then
          activated. Anything not governed saves straight to live configuration.
        </p>
      </div>
      {(state.known || []).map((type) => (
        <label key={type} className="flex items-start gap-2.5">
          <input type="checkbox" className="mt-0.5" checked={governed.has(type)}
            disabled={!canApprove || busy || fixed.has(type)}
            onChange={(e) => toggle(type, e.target.checked)} />
          <span>
            <span className="block text-[12px] text-[var(--text-main)]">
              {TYPE_LABEL[type] || type}
            </span>
            {fixed.has(type) && (
              <span className="block text-[11px] text-[var(--text-muted)]">
                Always governed — it decides what people are paid.
              </span>
            )}
          </span>
        </label>
      ))}
    </div>
  );
};

const RequestDetail = ({ request, canApprove, busy, onDecide, onActivate }) => {
  const [comments, setComments] = useState('');
  const impact = request.impact || {};
  const change = request.definition_change || {};
  const pending = request.status === 'Pending Approval';
  const approved = request.status === 'Approved';

  return (
    <div className="space-y-4 pt-3">
      <div>
        <p className="text-[12.5px] text-[var(--text-main)]">
          <span className="font-bold">Why: </span>{request.reason || '—'}
        </p>
        <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
          Raised by {request.requested_by_name || 'unknown'} on {when(request.requested_at)}
          {request.effective_from ? ` · effective ${request.effective_from}` : ''}
        </p>
      </div>

      {/* §27 Impact Analysis — what the approver is entitled to see before deciding. */}
      {request.impact ? (
        <div className="rounded-lg border border-[var(--border)] px-3.5 py-2.5 space-y-1.5">
          <h4 className="text-[12px] font-bold text-[var(--text-main)]">Impact</h4>
          <p className="text-[12px] text-[var(--text-main)]">
            Reaches <span className="font-bold">{impact.employees_affected ?? '—'}</span> of{' '}
            {impact.total_employees ?? '—'} employees
            {impact.effective_from ? ` · effective ${impact.effective_from}` : ''}
          </p>
          {(impact.warnings || []).map((w) => (
            <p key={w} className="text-[12px] text-[var(--accent-red)] flex items-start gap-1.5">
              <AlertTriangle size={14} className="shrink-0 mt-0.5" /> {w}
            </p>
          ))}
        </div>
      ) : (
        <p className="text-[12px] text-[var(--text-muted)]">
          No impact analysis has been run yet — this change cannot be submitted for approval
          until it has.
        </p>
      )}

      {request.simulation && (
        <div className="rounded-lg border border-[var(--border)] px-3.5 py-2.5">
          <h4 className="text-[12px] font-bold text-[var(--text-main)]">Simulation</h4>
          <pre className="text-[11.5px] text-[var(--text-muted)] whitespace-pre-wrap break-words mt-1">
            {JSON.stringify(request.simulation, null, 2)}
          </pre>
        </div>
      )}

      {/* §30: the old and new definition, recorded at activation. */}
      {change.new && (
        <div className="rounded-lg border border-[var(--border)] px-3.5 py-2.5 overflow-x-auto">
          <h4 className="text-[12px] font-bold text-[var(--text-main)]">What changed</h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-1.5">
            <div>
              <p className={LABEL}>Was {change.old_version ? `(v${change.old_version})` : ''}</p>
              <pre className="text-[11.5px] text-[var(--text-muted)] whitespace-pre-wrap break-words">
                {change.old ? JSON.stringify(change.old, null, 2) : '— nothing active —'}
              </pre>
            </div>
            <div>
              <p className={LABEL}>Now {change.new_version ? `(v${change.new_version})` : ''}</p>
              <pre className="text-[11.5px] text-[var(--text-main)] whitespace-pre-wrap break-words">
                {JSON.stringify(change.new, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}

      {(request.approvals || []).length > 0 && (
        <div>
          <h4 className="text-[12px] font-bold text-[var(--text-main)] mb-1.5">Decisions</h4>
          <ul className="space-y-1">
            {request.approvals.map((a) => (
              <li key={a.id} className="text-[12px] text-[var(--text-main)]">
                <Chip tone={STATUS_TONE[a.decision] || 'neutral'}>{a.decision}</Chip>{' '}
                {a.approver_name} · {when(a.decided_at)}
                {a.comments && <span className="text-[var(--text-muted)]"> — {a.comments}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {canApprove && (pending || approved) && (
        <div className="space-y-2 pt-1">
          {pending && (
            <div>
              <label className={LABEL} htmlFor={`cmt-${request.request_no}`}>
                Comments (required to reject or return)
              </label>
              <input id={`cmt-${request.request_no}`} value={comments} className={FIELD}
                onChange={(e) => setComments(e.target.value)} />
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {pending && (
              <>
                <Btn disabled={busy}
                  onClick={() => onDecide(request.request_no, 'return', comments)}>
                  Return
                </Btn>
                <Btn tone="danger" disabled={busy}
                  onClick={() => onDecide(request.request_no, 'reject', comments)}>
                  Reject
                </Btn>
                <Btn tone="primary" disabled={busy}
                  onClick={() => onDecide(request.request_no, 'approve', comments)}>
                  <CheckCircle2 size={14} /> Approve
                </Btn>
              </>
            )}
            {approved && (
              <Btn tone="primary" disabled={busy} onClick={() => onActivate(request.request_no)}>
                <PlayCircle size={14} /> Activate — apply this change
              </Btn>
            )}
          </div>
          {approved && (
            <p className="text-[11.5px] text-[var(--text-muted)]">
              Approved, but not yet in force. Activating is what writes it to live
              configuration.
            </p>
          )}
        </div>
      )}
    </div>
  );
};

const ConfigApprovalInbox = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [rows, setRows] = useState([]);
  const [detail, setDetail] = useState(null);
  const [openNo, setOpenNo] = useState(null);
  const [status, setStatus] = useState('Pending Approval');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const canApprove = can(CAP.CONFIG_APPROVE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await listConfigChangeRequests({ ...scope, status: status || undefined });
      setRows(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the change requests.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, status]);

  useEffect(() => { load(); }, [load]);

  const open = async (requestNo) => {
    if (openNo === requestNo) { setOpenNo(null); setDetail(null); return; }
    setOpenNo(requestNo);
    setDetail(null);
    try {
      const { data } = await getConfigChangeRequest(requestNo, scope);
      setDetail(data);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not open that request.');
    }
  };

  const act = async (fn, message, requestNo) => {
    setBusy(true);
    try {
      await fn();
      showSuccess(message);
      const { data } = await getConfigChangeRequest(requestNo, scope);
      setDetail(data);
      await load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'That did not go through.');
    } finally {
      setBusy(false);
    }
  };

  const onDecide = (requestNo, action, comments) => {
    if (action !== 'approve' && !comments.trim()) {
      showError('Say why — the person who raised this sees your comment.');
      return;
    }
    act(() => decideConfigChangeRequest(requestNo, { action, comments }, scope),
      `Change ${action === 'approve' ? 'approved' : `${action}ed`}.`, requestNo);
  };

  const onActivate = (requestNo) =>
    act(() => activateConfigChangeRequest(requestNo, scope),
      'Change activated — it is now live configuration.', requestNo);

  const columns = [
    { key: 'request_no', label: 'Request', render: (r) => (
      <>
        <span className="text-[var(--text-main)] font-mono">{r.request_no}</span>
        {r.title && <span className="block text-[11px] text-[var(--text-muted)]">{r.title}</span>}
      </>
    ) },
    { key: 'entity', label: 'Changes', render: (r) => (
      <span className="text-[var(--text-main)]">
        {r.entity_code}{r.version_no != null ? ` v${r.version_no}` : ''}
      </span>
    ) },
    { key: 'requested_by', label: 'Raised by', render: (r) => (
      <>
        <span className="text-[var(--text-main)]">{r.requested_by_name || '—'}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{when(r.requested_at)}</span>
      </>
    ) },
    { key: 'status', label: 'Status', render: (r) => (
      <Chip tone={STATUS_TONE[r.status] || 'neutral'}>{r.status}</Chip>
    ) },
    { key: 'open', label: '', render: (r) => (
      <Btn tone="ghost" onClick={() => open(r.request_no)}>
        {openNo === r.request_no ? 'Close' : 'Review'}
      </Btn>
    ) },
  ];

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={GitPullRequest}
        title="Configuration Approval Inbox"
        subtitle="Rule changes waiting on a decision, and what each one affects (FRD §27)."
      />
      <HrmsScopeBar />

      <div className="max-w-xs">
        <label className={LABEL} htmlFor="cfg-status">Status</label>
        <select id="cfg-status" value={status} className={FIELD}
          onChange={(e) => setStatus(e.target.value)}>
          <option value="Pending Approval">Pending approval</option>
          <option value="Approved">Approved, not yet active</option>
          <option value="Returned">Returned</option>
          <option value="Active">Active</option>
          <option value="Rejected">Rejected</option>
          <option value="">All</option>
        </select>
      </div>

      <GovernedTypes scope={scope} canApprove={canApprove}
        showSuccess={showSuccess} showError={showError} />

      {loading && <HrmsLoading label="Loading change requests…" />}
      {error && <HrmsError message={error} />}
      {!loading && !error && !rows.length && (
        <HrmsEmpty icon={GitPullRequest} title="Nothing here"
          message={status ? `No change requests are ${status.toLowerCase()}.`
            : 'No configuration changes have been raised yet.'} />
      )}
      {!loading && !error && !!rows.length && (
        <div className="space-y-2">
          <RecordList rows={rows} columns={columns} keyOf={(r) => r.request_no} />
          {openNo && (
            <div className="rounded-lg border border-[var(--border)] px-3.5 py-3">
              {detail
                ? <RequestDetail request={detail} canApprove={canApprove} busy={busy}
                    onDecide={onDecide} onActivate={onActivate} />
                : <HrmsLoading label="Opening…" />}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ConfigApprovalInbox;
