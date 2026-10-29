import React, { useCallback, useEffect, useState } from 'react';
import { History, Search, AlertTriangle, Download } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getConfigAudit, getConfigImpact, exportConfigAudit, exportConfigSnapshot,
  listPolicyVersions, simulateAttendancePolicy, listSalaryComponents, simulateSalaryComponent,
} from '../../../services/hrmsApi';
import { CAP } from '../access';
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
  const { scope, companyId, can } = useHrms();
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // P1-128. The export is gated on config.audit_read specifically, which is the
  // capability an auditor is given — reading the register is a different question.
  const [exporting, setExporting] = useState(false);
  const [entityType, setEntityType] = useState('');
  // P1-143: what the configuration IS today, beside the audit of how it got there.
  const [snapshotting, setSnapshotting] = useState(false);

  const runSnapshot = async () => {
    setSnapshotting(true);
    try {
      await exportConfigSnapshot(scope);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not download the configuration snapshot.');
    } finally {
      setSnapshotting(false);
    }
  };

  const runExport = async () => {
    setExporting(true);
    try {
      await exportConfigAudit({
        ...scope, limit: 1000, entity_type: entityType || undefined,
      });
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not export the configuration audit.');
    } finally {
      setExporting(false);
    }
  };

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

  // Filtered on the client because the list is already capped at 200 rows and a
  // round trip to drop a few of them would be slower than keeping them. The EXPORT
  // passes the filter to the server, where it narrows a thousand.
  const shown = entityType ? rows.filter((r) => r.entity_type === entityType) : rows;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <select value={entityType} aria-label="Configuration type"
          onChange={(e) => setEntityType(e.target.value)}
          className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]">
          <option value="">Every configuration type</option>
          <option value="policy_version">Policy versions</option>
          <option value="salary_component">Salary components</option>
          <option value="field_definition">Field definitions</option>
        </select>
        {can(CAP.CONFIG_AUDIT_READ) && (
          <div className="flex flex-wrap gap-2">
            <Btn onClick={runSnapshot} disabled={snapshotting}>
              <Download size={14} /> {snapshotting ? 'Preparing…' : 'Download configuration snapshot'}
            </Btn>
            <Btn onClick={runExport} disabled={exporting}>
              <Download size={14} /> {exporting ? 'Exporting…' : 'Export'}
            </Btn>
          </div>
        )}
      </div>
      {loading && <HrmsLoading label="Loading the configuration audit…" />}
      {error && <HrmsError message={error} />}
      {!loading && !error && !shown.length && (
        <HrmsEmpty icon={History} title="No configuration changes yet"
          message="Governed rule changes appear here with their requester, approver and reason." />
      )}
      {!loading && !error && !!shown.length && (
        <>
          <RecordList rows={shown} columns={columns} keyOf={(r) => r.request_no} />
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

/**
 * FRD §29 "Rule Simulation": every simulation in one place -- an attendance or payroll
 * policy version against a recorded month (optionally for chosen employees), or a salary
 * component's current definition against the people it pays. Writes nothing; the
 * designers run the same simulations next to the rule being edited.
 */
const SIMULATABLE_POLICIES = [
  ['ATT_DAY', 'Attendance — daily rules'], ['ATT_REGULARISATION', 'Attendance — regularisation'],
  ['ATT_CLOSURE', 'Attendance — monthly closure'], ['PAY_POLICY', 'Payroll policy'],
];

const SimulationTab = () => {
  const { scope, companyId } = useHrms();
  const [kind, setKind] = useState('ATT_DAY');
  const [versions, setVersions] = useState([]);
  const [components, setComponents] = useState([]);
  const [target, setTarget] = useState('');
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [codes, setCodes] = useState('');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const isComponent = kind === 'COMPONENT';

  useEffect(() => {
    setTarget(''); setResult(null); setError(null);
    if (!companyId) return;
    if (isComponent) {
      listSalaryComponents(scope).then(({ data }) => setComponents(Array.isArray(data) ? data : []))
        .catch(() => setComponents([]));
    } else {
      listPolicyVersions(kind, scope).then(({ data }) => setVersions(Array.isArray(data) ? data : []))
        .catch(() => setVersions([]));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, companyId]);

  const run = async () => {
    if (!target) { setError('Choose what to simulate.'); return; }
    setBusy(true); setError(null);
    try {
      const { data } = isComponent
        ? await simulateSalaryComponent(target, {}, scope)
        : await simulateAttendancePolicy(kind, target, {
          ...scope, period, ...(codes.trim() ? { employee_codes: codes.trim() } : {}),
        });
      setResult(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not run that simulation.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
        <div>
          <label className={LABEL} htmlFor="sim-kind">Simulate</label>
          <select id="sim-kind" className={FIELD} value={kind} onChange={(e) => setKind(e.target.value)}>
            {SIMULATABLE_POLICIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            <option value="COMPONENT">Salary component</option>
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="sim-target">{isComponent ? 'Component' : 'Version'}</label>
          <select id="sim-target" className={FIELD} value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Choose…</option>
            {isComponent
              ? components.map((c) => <option key={c.code} value={c.code}>{c.code} — {c.name}</option>)
              : versions.map((v) => (
                <option key={v.version_no} value={v.version_no}>v{v.version_no} · {v.status} · from {v.effective_from}</option>
              ))}
          </select>
        </div>
        {!isComponent && (
          <>
            <div>
              <label className={LABEL} htmlFor="sim-period">Against month</label>
              <input id="sim-period" type="month" className={FIELD} value={period}
                onChange={(e) => setPeriod(e.target.value)} />
            </div>
            <div>
              <label className={LABEL} htmlFor="sim-codes">Employees (optional)</label>
              <input id="sim-codes" className={FIELD} value={codes} placeholder="EMP codes, comma separated"
                onChange={(e) => setCodes(e.target.value)} />
            </div>
          </>
        )}
      </div>
      <Btn tone="primary" onClick={run} disabled={busy}>{busy ? 'Simulating…' : 'Run simulation'}</Btn>
      {error && <p className="text-[12px] text-[var(--accent-red)]">{error}</p>}
      {result && (
        <div className="rounded-lg border border-[var(--border)] px-3.5 py-2.5 space-y-2">
          <p className="text-[12px] text-[var(--text-main)]">
            {['days_changed', 'days_examined', 'employees_affected', 'payable_days_delta',
              'requests_examined', 'would_refuse', 'would_allow', 'pending_requests',
              'records_examined', 'employees_changed', 'net_was', 'net_now', 'left_out']
              .filter((k) => result[k] !== undefined && result[k] !== null)
              .map((k) => `${k.replace(/_/g, ' ')}: ${result[k]}`).join(' · ') || 'Done.'}
          </p>
          {result.note && <p className="text-[11.5px] text-[var(--text-muted)]">{result.note}</p>}
          <pre className="text-[11px] text-[var(--text-muted)] whitespace-pre-wrap break-words max-h-80 overflow-auto">
            {JSON.stringify(result.changes || result.rows || result.employees || result, null, 2)}
          </pre>
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
        <Btn tone={tab === 'simulation' ? 'primary' : 'ghost'} onClick={() => setTab('simulation')}>
          Rule simulation
        </Btn>
      </div>

      {tab === 'audit' && <AuditTab />}
      {tab === 'impact' && <ImpactTab />}
      {tab === 'simulation' && <SimulationTab />}
    </div>
  );
};

export default ConfigAuditViewer;
