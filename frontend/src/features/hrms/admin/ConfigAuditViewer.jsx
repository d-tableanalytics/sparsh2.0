import React, { useCallback, useEffect, useState } from 'react';
import { History, Search, AlertTriangle } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { getConfigAudit, getConfigImpact } from '../../../services/hrmsApi';
import { FIELD, LABEL } from '../internal/internalKit';
import { Btn, Chip, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Configuration Audit & Impact Viewer (FRD §29, §30).
 *
 * Two screens the FRD lists separately, built as two tabs of one: both answer "what do we
 * know about this piece of configuration", and an administrator looking at a change is
 * usually one click from wanting its dependencies.
 *
 * §30: "Configuration changes are audited with requester, approver, reason, effective date
 * and old/new definition." All five are on the row — the old/new pair is the one that
 * takes work to reconstruct afterwards, so it is recorded at activation rather than
 * derived here.
 */

const when = (value) => (value ? new Date(value).toLocaleString() : '—');

const STATUS_TONE = {
  Draft: 'neutral', 'Impact Analysed': 'neutral', Simulated: 'accent',
  'Pending Approval': 'warn', Approved: 'accent', Active: 'good',
  Rejected: 'bad', Returned: 'warn', Withdrawn: 'neutral',
};

const ENTITY_TYPES = [
  ['salary_component', 'Salary component'],
  ['field_definition', 'Employee / attendance field'],
  ['policy', 'Attendance or payroll policy'],
];

const AuditTab = () => {
  const { scope, companyId } = useHrms();
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getConfigAudit({ ...scope, limit: 200 });
      setRows(data?.changes || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the configuration audit.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'request_no', label: 'Change', render: (r) => (
      <>
        <span className="text-[var(--text-main)] font-mono">{r.request_no}</span>
        {r.title && <span className="block text-[11px] text-[var(--text-muted)]">{r.title}</span>}
      </>
    ) },
    { key: 'what', label: 'What', render: (r) => (
      <span className="text-[var(--text-main)]">
        {r.entity_code}{r.version_no != null ? ` v${r.version_no}` : ''}
      </span>
    ) },
    { key: 'who', label: 'Requested / approved', render: (r) => (
      <>
        <span className="text-[var(--text-main)]">{r.requested_by_name || '—'}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">
          {r.decided_by_name ? `approved by ${r.decided_by_name}` : 'not yet decided'}
        </span>
      </>
    ) },
    { key: 'effective', label: 'Effective', render: (r) => (
      <span className="text-[var(--text-main)]">
        {r.impact?.effective_from || r.effective_from || '—'}
      </span>
    ) },
    { key: 'status', label: 'Status', render: (r) => (
      <Chip tone={STATUS_TONE[r.status] || 'neutral'}>{r.status}</Chip>
    ) },
    { key: 'open', label: '', render: (r) => (
      <Btn tone="ghost" onClick={() => setOpen(open === r.request_no ? null : r.request_no)}>
        {open === r.request_no ? 'Close' : 'Detail'}
      </Btn>
    ) },
  ];

  const current = rows.find((r) => r.request_no === open);

  return (
    <div className="space-y-3">
      {loading && <HrmsLoading label="Loading the configuration audit…" />}
      {error && <HrmsError message={error} />}
      {!loading && !error && !rows.length && (
        <HrmsEmpty icon={History} title="No configuration changes yet"
          message="Governed rule changes appear here with their requester, approver and reason." />
      )}
      {!loading && !error && !!rows.length && (
        <>
          <RecordList rows={rows} columns={columns} keyOf={(r) => r.request_no} />
          {current && (
            <div className="rounded-lg border border-[var(--border)] px-3.5 py-3 space-y-3">
              <p className="text-[12.5px] text-[var(--text-main)]">
                <span className="font-bold">Reason: </span>{current.reason || '—'}
              </p>
              <p className="text-[11.5px] text-[var(--text-muted)]">
                Raised {when(current.requested_at)}
                {current.decided_at && ` · decided ${when(current.decided_at)}`}
                {current.activated_at && ` · activated ${when(current.activated_at)}`}
              </p>
              {current.definition_change?.new && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <p className={LABEL}>Was</p>
                    <pre className="text-[11.5px] text-[var(--text-muted)] whitespace-pre-wrap break-words">
                      {current.definition_change.old
                        ? JSON.stringify(current.definition_change.old, null, 2)
                        : '— nothing active —'}
                    </pre>
                  </div>
                  <div>
                    <p className={LABEL}>Now</p>
                    <pre className="text-[11.5px] text-[var(--text-main)] whitespace-pre-wrap break-words">
                      {JSON.stringify(current.definition_change.new, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};

const ImpactTab = () => {
  const { scope, companyId } = useHrms();
  const [entityType, setEntityType] = useState('salary_component');
  const [code, setCode] = useState('');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const look = async () => {
    if (!code.trim() || !companyId) return;
    setBusy(true); setError(null); setResult(null);
    try {
      const { data } = await getConfigImpact(entityType, code.trim(), scope);
      setResult(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not check that.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[14rem]">
          <label className={LABEL} htmlFor="imp-type">What kind</label>
          <select id="imp-type" value={entityType} className={FIELD}
            onChange={(e) => { setEntityType(e.target.value); setResult(null); }}>
            {ENTITY_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <div className="min-w-[12rem]">
          <label className={LABEL} htmlFor="imp-code">Code</label>
          <input id="imp-code" value={code} className={FIELD} placeholder="e.g. BASIC"
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') look(); }} />
        </div>
        <Btn tone="primary" onClick={look} disabled={busy || !code.trim()}>
          <Search size={14} /> {busy ? 'Checking…' : 'Check'}
        </Btn>
      </div>

      {error && <HrmsError message={error} />}

      {result && (
        <div className="space-y-3">
          <div className={`rounded-lg px-3.5 py-2.5 flex items-start gap-2 ${
            result.can_retire ? 'bg-[var(--accent-green-bg)]' : 'bg-[var(--accent-orange-bg)]'}`}>
            {!result.can_retire && (
              <AlertTriangle size={16} className="shrink-0 mt-0.5 text-[var(--accent-orange)]" />
            )}
            <p className="text-[12.5px] text-[var(--text-main)] font-semibold">
              {result.summary}
            </p>
          </div>

          <div>
            <h4 className="text-[12px] font-bold text-[var(--text-main)]">
              References — these break if it goes
            </h4>
            {result.references?.length ? (
              <ul className="mt-1 space-y-1">
                {result.references.map((r, i) => (
                  <li key={`${r.kind}-${r.name}-${i}`} className="text-[12px] text-[var(--text-main)]">
                    <Chip tone="warn">{r.kind}</Chip> {r.name}
                    {r.detail && <span className="text-[var(--text-muted)]"> — {r.detail}</span>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[12px] text-[var(--text-muted)] mt-1">Nothing.</p>
            )}
          </div>

          <div>
            <h4 className="text-[12px] font-bold text-[var(--text-main)]">
              History — why it is retired rather than deleted
            </h4>
            {result.history?.length ? (
              <ul className="mt-1 space-y-1">
                {result.history.map((r, i) => (
                  <li key={`${r.kind}-${r.name}-${i}`} className="text-[12px] text-[var(--text-main)]">
                    <Chip tone="neutral">{r.kind}</Chip> {r.name}
                    {r.detail && <span className="text-[var(--text-muted)]"> — {r.detail}</span>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[12px] text-[var(--text-muted)] mt-1">
                Never used in a closed period.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

const ConfigAuditViewer = () => {
  const [tab, setTab] = useState('audit');
  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={History}
        title="Configuration Audit & Impact"
        subtitle="Who changed which rule, why, and what still depends on it (FRD §29, §30)."
      />
      <HrmsScopeBar />

      <div className="flex gap-2">
        <Btn tone={tab === 'audit' ? 'primary' : 'ghost'} onClick={() => setTab('audit')}>
          Change history
        </Btn>
        <Btn tone={tab === 'impact' ? 'primary' : 'ghost'} onClick={() => setTab('impact')}>
          Dependency check
        </Btn>
      </div>

      {tab === 'audit' ? <AuditTab /> : <ImpactTab />}
    </div>
  );
};

export default ConfigAuditViewer;
