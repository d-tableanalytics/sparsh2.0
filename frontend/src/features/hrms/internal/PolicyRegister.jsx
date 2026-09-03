import React, { useCallback, useEffect, useState } from 'react';
import { BookMarked, Plus } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getPolicies, getPolicy, logPolicyRevision, approvePolicyRevision,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from './internalKit';
import { Btn, Chip, Facts, Modal, RecordList, SignatureField } from './internalKit.jsx';

/**
 * HRMS ▸ the policy register and its review cycle (SOP §14).
 *
 * "This policy shall be reviewed annually... All amendments shall be logged in the
 * Modification History table."
 *
 * The register answers three questions a document in a folder cannot: which version is in
 * force, when it is next due to be looked at, and what changed last time.
 *
 * -- Drafting a revision is not approving it -----------------------------------------------
 * Anybody with `policy.write` can log "v1.1: added a clause about panel composition". Until
 * the MD approves it, the register still says v1.0 governs. The screen shows unapproved
 * revisions as exactly that, so nobody reads a draft as the rule.
 *
 * -- An overdue review is shown, never enforced ---------------------------------------------
 * Nothing in the module is blocked by a lapsed review. Refusing to hire because a policy
 * review slipped would punish the wrong people, and would guarantee the register gets worked
 * around instead of kept.
 */

const reviewTone = (status) => ({
  overdue: 'bad', due_soon: 'warn', current: 'good', unscheduled: 'neutral',
}[status] || 'neutral');

const PolicyRegister = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [counts, setCounts] = useState({ overdue: 0, due_soon: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(false);

  const canWrite = can(CAP.POLICY_WRITE);
  const canApprove = can(CAP.POLICY_APPROVE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getPolicies(scope);
      setRows(data?.policies || []);
      setCounts({ overdue: data?.overdue ?? 0, due_soon: data?.due_soon ?? 0 });
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the policy register.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const openPolicy = async (policyKey) => {
    try {
      const { data } = await getPolicy(policyKey, scope);
      setOpen(data);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not open that policy.');
    }
  };

  const columns = [
    {
      key: 'policy',
      label: 'Policy',
      render: (r) => (
        <>
          <span className="font-semibold text-[var(--text-main)]">{r.title}</span>
          <span className="block text-[11px] text-[var(--text-muted)]">
            {r.policy_key}
          </span>
        </>
      ),
    },
    { key: 'version', label: 'In force', render: (r) => `v${r.version}` },
    { key: 'effective', label: 'Effective', render: (r) => day(r.effective_date) },
    {
      key: 'review',
      label: 'Next review',
      render: (r) => (
        <>
          {day(r.next_review_due)}
          <Chip tone={reviewTone(r.review_status)}>
            {r.review_status.replace('_', ' ')}
          </Chip>
        </>
      ),
    },
    { key: 'owner', label: 'Owner', render: (r) => r.owner_role || '—' },
    {
      key: 'act',
      label: '',
      align: 'right',
      render: (r) => <Btn onClick={() => openPolicy(r.policy_key)}>Open</Btn>,
    },
  ];

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={BookMarked}
        title="Policy register"
        subtitle="Which version governs, when it is next due for review, and what changed last time (SOP section 14)."
      />
      <HrmsScopeBar />

      {(counts.overdue > 0 || counts.due_soon > 0) && (
        <div className={`rounded-xl px-4 py-3 border ${counts.overdue
          ? 'border-[var(--accent-red)]/30 bg-[var(--accent-red-bg)]'
          : 'border-[var(--accent-orange)]/30 bg-[var(--accent-orange-bg)]'}`}>
          <p className={`text-[12.5px] font-semibold ${counts.overdue
            ? 'text-[var(--accent-red)]' : 'text-[var(--accent-orange)]'}`}>
            {counts.overdue > 0 && `${counts.overdue} policy review(s) overdue.`}
            {counts.overdue > 0 && counts.due_soon > 0 && ' '}
            {counts.due_soon > 0 && `${counts.due_soon} due within the month.`}
          </p>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
            Nothing is blocked by this. A lapsed review is a conversation to have, not a
            reason to stop hiring.
          </p>
        </div>
      )}

      {loading && <HrmsLoading label="Loading the register…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && !rows.length && (
        <HrmsEmpty icon={BookMarked} title="The register is empty"
          hint="The two recruitment policies are seeded the first time this screen is opened." />
      )}
      {!loading && !error && !!rows.length && (
        <RecordList
          rows={rows}
          columns={columns}
          keyOf={(r) => r.policy_key}
          renderCard={(r) => (
            <div className="space-y-2.5">
              <div className="flex items-start justify-between gap-3">
                <p className="font-semibold text-[13px] text-[var(--text-main)]">
                  {r.title}
                </p>
                <Chip tone={reviewTone(r.review_status)}>
                  {r.review_status.replace('_', ' ')}
                </Chip>
              </div>
              <Facts items={[
                { label: 'In force', value: `v${r.version}` },
                { label: 'Effective', value: day(r.effective_date) },
                { label: 'Next review', value: day(r.next_review_due) },
              ]} />
              <Btn onClick={() => openPolicy(r.policy_key)}>Open</Btn>
            </div>
          )}
        />
      )}

      {open && (
        <PolicyModal
          policy={open}
          scope={scope}
          busy={busy}
          setBusy={setBusy}
          canWrite={canWrite}
          canApprove={canApprove}
          onClose={() => setOpen(null)}
          onChanged={async () => {
            await openPolicy(open.policy_key);
            load();
          }}
          onSuccess={showSuccess}
          onError={showError}
        />
      )}
    </div>
  );
};

const PolicyModal = ({
  policy, scope, busy, setBusy, canWrite, canApprove,
  onClose, onChanged, onSuccess, onError,
}) => {
  const [mode, setMode] = useState('history');
  const [version, setVersion] = useState('');
  const [summary, setSummary] = useState('');
  const [signature, setSignature] = useState('');
  const [approveVersion, setApproveVersion] = useState('');

  const pending = (policy.revisions || []).filter((r) => !r.approved_at);

  const draft = async () => {
    setBusy(true);
    try {
      await logPolicyRevision(policy.policy_key,
        { version, summary_of_change: summary }, scope);
      onSuccess(`v${version} logged. It does not govern until it is approved.`);
      setMode('history');
      setVersion('');
      setSummary('');
      onChanged();
    } catch (err) {
      onError(err?.response?.data?.detail || 'The revision could not be logged.');
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    setBusy(true);
    try {
      await approvePolicyRevision(policy.policy_key,
        { version: approveVersion, signature }, scope);
      onSuccess(`v${approveVersion} is now the version in force.`);
      setMode('history');
      setSignature('');
      onChanged();
    } catch (err) {
      onError(err?.response?.data?.detail || 'The revision could not be approved.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={policy.title}
      subtitle={`v${policy.version} in force from ${day(policy.effective_date)}`}
      labelledBy="policy-open"
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Close</Btn>
          {mode === 'draft' && (
            <Btn tone="primary" disabled={busy || !version.trim() || !summary.trim()}
              onClick={draft}>
              Log revision
            </Btn>
          )}
          {mode === 'approve' && (
            <Btn tone="primary"
              disabled={busy || !approveVersion || !signature.trim()} onClick={approve}>
              Approve
            </Btn>
          )}
        </>
      )}
    >
      <Facts items={[
        { label: 'Key', value: policy.policy_key },
        { label: 'Owner', value: policy.owner_role },
        { label: 'Next review', value: day(policy.next_review_due) },
        { label: 'Status', value: policy.status },
      ]} />
      {policy.review_note && (
        <p className={`text-[12px] ${policy.review_status === 'overdue'
          ? 'text-[var(--accent-red)]' : 'text-[var(--text-muted)]'}`}>
          {policy.review_note}
        </p>
      )}

      {mode === 'history' && (
        <>
          <div className="flex gap-2">
            {canWrite && <Btn onClick={() => setMode('draft')}>
              <Plus size={14} /> Log a revision
            </Btn>}
            {canApprove && !!pending.length && (
              <Btn tone="primary" onClick={() => {
                setMode('approve');
                setApproveVersion(pending[0].version);
              }}>
                Approve a revision
              </Btn>
            )}
          </div>

          <div>
            <p className={LABEL}>Modification history</p>
            {(policy.revisions || []).length ? (
              <ul className="space-y-2.5">
                {policy.revisions.map((r) => (
                  <li key={r.version}
                    className="rounded-lg border border-[var(--border)] p-3">
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-[12.5px] font-semibold text-[var(--text-main)]">
                        v{r.version}
                      </p>
                      <Chip tone={r.approved_at ? 'good' : 'warn'}>
                        {r.approved_at ? 'approved' : 'awaiting approval'}
                      </Chip>
                    </div>
                    <p className="mt-1 text-[12px] text-[var(--text-muted)]">
                      {r.summary_of_change}
                    </p>
                    <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                      Drafted by {r.changed_by_name} on {day(r.changed_at)}
                      {r.approved_at && ` · approved by ${r.approved_by_name} on ${day(r.approved_at)}`}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                No amendments logged yet.
              </p>
            )}
          </div>
        </>
      )}

      {mode === 'draft' && (
        <>
          <div>
            <label className={LABEL} htmlFor="policy-version">New version *</label>
            <input id="policy-version" className={FIELD} value={version}
              onChange={(e) => setVersion(e.target.value)} placeholder="1.1" />
          </div>
          <div>
            <label className={LABEL} htmlFor="policy-summary">What changed *</label>
            <textarea id="policy-summary" rows={4} className={TEXTAREA} value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="A modification history that does not say what was modified is a list of dates." />
          </div>
          <p className="text-[11px] text-[var(--text-muted)]">
            Logging this changes nothing about which version governs. It comes into force
            when the MD approves it.
          </p>
        </>
      )}

      {mode === 'approve' && (
        <>
          <div>
            <label className={LABEL} htmlFor="policy-approve">Version *</label>
            <select id="policy-approve" className={FIELD} value={approveVersion}
              onChange={(e) => setApproveVersion(e.target.value)}>
              {pending.map((r) => (
                <option key={r.version} value={r.version}>
                  v{r.version} — {r.summary_of_change.slice(0, 60)}
                </option>
              ))}
            </select>
          </div>
          <SignatureField
            id="policy-signature"
            value={signature}
            onChange={setSignature}
            hint="This changes which version of the policy the company is held to."
          />
        </>
      )}
    </Modal>
  );
};

export default PolicyRegister;
