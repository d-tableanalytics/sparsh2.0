import React, { useCallback, useEffect, useState } from 'react';
import { Clock, Search, Lock, Unlock } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP, HRMS_ROLE } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import BoardTabs from '../common/BoardTabs';
import { useSelfEmployee } from '../common/useSelfEmployee';
import SelfEmployeeChip from '../common/SelfEmployeeChip';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { ProcessGuide } from '../common/ProcessGuide';
import { ATTENDANCE_GUIDE } from '../common/processGuides';
import { SelfPunchCard, OfficeLocationsTab } from './SelfPunch';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getAttendance, markAttendance, getEmployees,
  requestRegularization, getRegularizations, actOnRegularization,
  requestOd, getOdRequests, actOnOd,
  getClosureDashboard, lockPeriod, unlockPeriod,
  getLateComingSummary,
  getShiftPolicy, saveShiftPolicy, getFlexiRequests, requestFlexi, actOnFlexi, importBiometric,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day, attLeaveToneFor } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Attendance (BA/Functional Design §7.8, §7.9, §7.12, §22.9).
 *
 * Four tabs over the same underlying case: the day's raw capture, the regularisation queue
 * it feeds, Outdoor Duty as its own small workflow (§7.8 step 59), and the monthly-closure
 * dashboard HR uses to lock a payroll-ready period. One page rather than four routes because
 * none of these is a "case" with its own detail URL the way a separation is — they are all
 * views onto the same rolling operational data.
 */

// Where a day's punches came from.
const SOURCE_LABEL = {
  biometric: 'Biometric', self: 'Self check-in', manual: 'Marked by HR',
  regularization: 'Regularised', od: 'Outdoor duty', leave: 'Leave',
};

const TABS = ['Attendance', 'Regularizations', 'Outdoor Duty', 'Flexible Timing', 'Late Coming',
  'Monthly Closure', 'Settings'];

const EXCEPTION_TYPES = ['Missing Punch', 'Wrong Time', 'Forgot to Mark', 'System Error', 'Other'];

const EmployeePicker = ({ scope, value, onChange }) => {
  // An employee acts for themselves only (and cannot search the directory): lock to "You".
  const self = useSelfEmployee(value, onChange);
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [options, setOptions] = useState([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    // No early setOptions([]) here: once `value` is set the component returns the
    // selected-chip view below and never reaches the dropdown, so stale options are
    // unreachable rather than merely hidden — nothing to clear.
    if (!debounced.trim() || value) return;
    let live = true;
    // Deferred a microtask, not called synchronously in the effect body: the react-hooks
    // set-state-in-effect rule flags a bare synchronous setState here, the same way it
    // already tolerates the setOptions/setSearching calls below inside the promise chain.
    Promise.resolve().then(() => { if (live) setSearching(true); });
    getEmployees({ ...scope, search: debounced, limit: 8 })
      .then(({ data }) => { if (live) setOptions(data?.employees || []); })
      .catch(() => { if (live) setOptions([]); })
      .finally(() => { if (live) setSearching(false); });
    return () => { live = false; };
  }, [debounced, value, scope]);

  if (self.selfOnly) return <SelfEmployeeChip me={self.me} />;
  if (value) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-lg border
        border-[var(--border)] bg-[var(--input-bg)] px-3 h-9">
        <span className="text-[13px] text-[var(--text-main)] truncate">
          {value.name} <span className="text-[var(--text-muted)]">({value.employee_code})</span>
        </span>
        <button type="button" onClick={() => { onChange(null); setSearch(''); }}
          className="text-[11px] font-bold text-[var(--accent-indigo)] shrink-0">
          Change
        </button>
      </div>
    );
  }
  return (
    <div className="relative">
      <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
      <input value={search} placeholder="Search by name or employee code…"
        className={`${FIELD} pl-8`} onChange={(e) => setSearch(e.target.value)} />
      {(searching || options.length > 0) && (
        <div className="absolute z-10 mt-1 w-full max-h-48 overflow-y-auto rounded-lg
          border border-[var(--border)] bg-[var(--bg-card)] shadow-lg">
          {searching && <p className="px-3 py-2 text-[12px] text-[var(--text-muted)]">Searching…</p>}
          {!searching && options.map((o) => (
            <button key={o.user_id} type="button" disabled={!o.employee_code}
              onClick={() => { onChange(o); setOptions([]); }}
              className="block w-full text-left px-3 py-2 text-[12.5px] hover:bg-[var(--input-bg)] disabled:opacity-60 disabled:cursor-not-allowed disabled:hover:bg-transparent">
              <span className="text-[var(--text-main)]">{o.name}</span>
              <span className="block text-[11px] text-[var(--text-muted)]">
                {o.employee_code
                  ? `${o.employee_code} · ${o.designation || '—'} · ${o.employment_status || '—'}`
                  : 'No employee profile yet — open them on the Employees page to create one.'}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const useSubmit = (showSuccess, showError, onDone) => {
  const [busy, setBusy] = useState(false);
  const run = async (fn, successMsg) => {
    setBusy(true);
    try {
      const res = await fn();
      if (successMsg) showSuccess(successMsg);
      onDone(res);
    } catch (err) {
      showError(err?.response?.data?.detail || 'That action could not be completed.');
    } finally {
      setBusy(false);
    }
  };
  return { busy, run };
};

const AttendanceBoard = () => {
  const { scope, companyId, can, role } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [tab, setTab] = useState('Attendance');
  const tabs = TABS.filter((t) => (t !== 'Monthly Closure' || can(CAP.ATTENDANCE_CLOSURE_READ))
    && (t !== 'Settings' || can(CAP.LEAVE_POLICY_MANAGE)));
  // Re-reads the attendance list after a self punch (the tab remounts on a new key).
  const [punchTick, setPunchTick] = useState(0);

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={Clock}
        title="Attendance"
        subtitle="Who came in each day, corrections, field work, and locking the month."
      />
      <HrmsScopeBar />
      {role === HRMS_ROLE.MD && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-4 py-3 text-[12.5px] text-[var(--text-main)]">
          <span className="font-bold">Review-only.</span> You can see everything here. Changes are made by
          {' '}{'HR (attendance, closure) and managers (approvals)'}.
        </div>
      )}
      {can(CAP.ATTENDANCE_SELF_PUNCH) && (
        <SelfPunchCard scope={scope} showSuccess={showSuccess} showError={showError}
          onPunched={() => setPunchTick((n) => n + 1)} />
      )}
      <ProcessGuide guide={ATTENDANCE_GUIDE} />

      <BoardTabs tabs={tabs} value={tab} onChange={setTab} label="Attendance sections" />

      {tab === 'Attendance' && (
        <AttendanceTab key={punchTick} scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Regularizations' && (
        <RegularizationsTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Outdoor Duty' && (
        <OdTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Late Coming' && (
        <LateComingTab scope={scope} companyId={companyId} />
      )}
      {tab === 'Settings' && (
        <div className="space-y-5">
          <TimingRulesCard scope={scope} companyId={companyId}
            showSuccess={showSuccess} showError={showError} />
          <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 space-y-3">
            <h3 className="text-[14px] font-bold text-[var(--text-main)]">Office locations (for self check-in)</h3>
            <OfficeLocationsTab scope={scope} companyId={companyId}
              showSuccess={showSuccess} showError={showError} />
          </section>
        </div>
      )}
      {tab === 'Flexible Timing' && (
        <FlexiTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
      {tab === 'Monthly Closure' && (
        <ClosureTab scope={scope} companyId={companyId} can={can}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

// ── Late Coming tab (§22.9) ──
const LateComingTab = ({ scope, companyId }) => {
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [focusEmployee, setFocusEmployee] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const [year, month] = period.split('-').map(Number);
      const lastDay = new Date(year, month, 0).getDate();
      const { data } = await getLateComingSummary({
        ...scope, start_date: `${period}-01`, end_date: `${period}-${String(lastDay).padStart(2, '0')}`,
      });
      setSummary(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the late-coming summary.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, period]);

  useEffect(() => { load(); setFocusEmployee(null); }, [load]);

  const dates = summary?.dates || [];
  const shown = focusEmployee ? dates.filter((d) => d.employee_code === focusEmployee) : dates;
  const lateByDate = shown.reduce((acc, d) => {
    (acc[d.work_date] = acc[d.work_date] || []).push(d);
    return acc;
  }, {});
  // Per person: how many late days, and how many minutes late in total — the second is the
  // number a lateness conversation is actually about (three 1-minute slips vs one hour).
  const byEmployee = dates.reduce((acc, d) => {
    const e = acc[d.employee_code] || { count: 0, minutes: 0, name: d.employee_name };
    e.count += 1;
    e.minutes += d.late_minutes || 0;
    acc[d.employee_code] = e;
    return acc;
  }, {});
  const employeeRows = Object.entries(byEmployee)
    .sort((a, b) => b[1].count - a[1].count || b[1].minutes - a[1].minutes);
  const nameOf = (code) => byEmployee[code]?.name || code;
  const lateLabel = (m) => (m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`);
  const byDepartment = dates.reduce((acc, d) => {
    const key = d.department || 'Unassigned';
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const departmentRows = Object.entries(byDepartment).sort((a, b) => b[1] - a[1]);

  const [year, month] = period.split('-').map(Number);
  const firstWeekday = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const cells = [...Array(firstWeekday).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1)];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3 justify-between">
        <div>
          <label className={LABEL} htmlFor="late-period">Period</label>
          <input id="late-period" type="month" value={period} className={`${FIELD} max-w-[200px]`}
            onChange={(e) => setPeriod(e.target.value)} />
        </div>
        {focusEmployee && (
          <Btn onClick={() => setFocusEmployee(null)}>Clear filter ({nameOf(focusEmployee)})</Btn>
        )}
      </div>

      {loading && <HrmsLoading label="Loading late-coming data…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && summary && (
        <div className="space-y-4">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
              Total Late-Coming Days{focusEmployee ? ` · ${nameOf(focusEmployee)}` : ''}
            </p>
            <p className="mt-1 text-[24px] font-bold text-[var(--text-main)]">
              {focusEmployee ? shown.length : summary.total_late_days}
            </p>
          </div>

          {/* Calendar grid — each late date highlighted, clickable for the day's detail. */}
          <div>
            <p className={LABEL}>Calendar</p>
            <div className="grid grid-cols-7 gap-1.5 text-center">
              {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => (
                <div key={d} className="text-[10.5px] font-bold text-[var(--text-muted)] pb-1">{d}</div>
              ))}
              {cells.map((day, i) => {
                if (!day) return <div key={`blank-${i}`} />;
                const dateStr = `${period}-${String(day).padStart(2, '0')}`;
                const hits = lateByDate[dateStr];
                return (
                  <div key={dateStr} title={hits ? hits.map((h) => `${h.employee_name || h.employee_code}: ${lateLabel(h.late_minutes)} late`).join(', ') : undefined}
                    className={`h-14 rounded-lg border text-[11.5px] flex flex-col items-center justify-center gap-0.5
                      ${hits
                        ? 'border-[var(--accent-red)]/40 bg-[var(--accent-red-bg)] text-[var(--accent-red)] font-bold'
                        : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                    <span>{day}</span>
                    {hits && <span className="text-[10px]">{hits.length} late</span>}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Late Coming Analytics — by department and by employee, for whoever can see
              more than their own record. */}
          {departmentRows.length > 1 && (
            <div>
              <p className={LABEL}>By Department</p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {departmentRows.map(([dept, count]) => (
                  <div key={dept} className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2">
                    <p className="text-[11.5px] font-semibold text-[var(--text-main)] truncate">{dept}</p>
                    <p className="text-[10.5px] text-[var(--text-muted)]">{count} late day(s)</p>
                  </div>
                ))}
              </div>
            </div>
          )}
          {employeeRows.length > 0 && (
            <div>
              <p className={LABEL}>
                By Employee · grace {summary.grace_minutes ?? 0} min/day · buffer {summary.buffer_minutes ?? 0} min/month
              </p>
              <div className="space-y-1.5">
                {employeeRows.map(([code, { count, minutes, name }]) => (
                  <button key={code} type="button" onClick={() => setFocusEmployee(code)}
                    title="Show only this person's late days"
                    className="w-full flex items-center justify-between gap-3 rounded-lg border border-[var(--border)]
                      bg-[var(--bg-card)] px-3 py-2 text-left hover:border-[var(--accent-indigo)]">
                    <span className="min-w-0">
                      <span className="block text-[12.5px] font-semibold text-[var(--text-main)] truncate">{name || code}</span>
                      <span className="block text-[11px] text-[var(--text-muted)]">
                        {name ? `${code} · ` : ''}{lateLabel(minutes)} late in total
                      </span>
                    </span>
                    <span className="flex items-center gap-1.5 shrink-0">
                      {(() => {
                        const m = (summary.monthly || []).find((x) => x.employee_code === code && x.month === period);
                        if (!m) return null;
                        return m.beyond_buffer > 0
                          ? <Chip tone="bad" title={`${m.within_buffer} min within the ${m.buffer_minutes}-min buffer`}>{m.beyond_buffer} min beyond buffer</Chip>
                          : <Chip tone="good" title={`Buffer ${m.buffer_minutes} min`}>within buffer</Chip>;
                      })()}
                      <Chip tone={count >= 5 ? 'bad' : count >= 2 ? 'warn' : 'neutral'}>{count} day(s)</Chip>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {!dates.length && (
            <HrmsEmpty icon={Clock} title="No late-coming days in this period" />
          )}
        </div>
      )}
    </div>
  );
};

// ── Attendance tab ──
const AttendanceTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [marking, setMarking] = useState(false);
  const [regularizing, setRegularizing] = useState(false);
  const [importing, setImporting] = useState(false);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getAttendance({ ...scope, limit: 100 });
      setRows(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load attendance.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'who', label: 'Employee', render: (r) => (
      <>
        <span className="font-semibold text-[var(--text-main)]">{r.employee_code}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{day(r.work_date)}</span>
      </>
    ) },
    { key: 'time', label: 'In / Out', render: (r) => (
      <span className="text-[var(--text-main)]">
        {r.actual_in || '—'} – {r.actual_out || '—'}
      </span>
    ) },
    { key: 'late', label: 'Late', render: (r) => (
      <span className="text-[var(--text-main)]">{r.late_minutes ? `${r.late_minutes}m` : '—'}</span>
    ) },
    { key: 'source', label: 'Source', render: (r) => (
      <span className="text-[11.5px] text-[var(--text-muted)]" title={r.flexi_no ? `Judged against flexible timing ${r.flexi_no}` : undefined}>
        {SOURCE_LABEL[r.source] || r.source || '—'}{r.flexi_no ? ' · flexi' : ''}
      </span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <Chip tone={attLeaveToneFor(r.status)}>{r.status}{r.locked ? ' · Locked' : ''}</Chip>
    ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_code}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{day(r.work_date)}</p>
        </div>
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
      </div>
      <Facts items={[
        { label: 'In / Out', value: `${r.actual_in || '—'} – ${r.actual_out || '—'}` },
        { label: 'Late', value: r.late_minutes ? `${r.late_minutes}m` : '—' },
        { label: 'Locked', value: r.locked ? 'Yes' : 'No' },
      ]} />
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 justify-end">
        {can(CAP.ATTENDANCE_REGULARIZE_REQUEST) && (
          <Btn onClick={() => setRegularizing(true)}>Request Regularisation</Btn>
        )}
        {can(CAP.ATTENDANCE_IMPORT) && (
          <Btn onClick={() => setImporting(true)}>Import biometric file</Btn>
        )}
        {can(CAP.ATTENDANCE_MARK) && (
          <Btn tone="primary" onClick={() => setMarking(true)}>
            <Clock size={14} /> Mark Attendance
          </Btn>
        )}
      </div>
      {loading && <HrmsLoading label="Loading attendance…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns} renderCard={renderCard}
            keyOf={(r) => `${r.employee_code}:${r.work_date}`} />
        ) : (
          <HrmsEmpty icon={Clock} title="No attendance captured yet"
            hint="Mark a day's attendance to get started." />
        )
      )}
      {marking && (
        <MarkModal scope={scope} onClose={() => setMarking(false)}
          onDone={() => { setMarking(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {importing && (
        <BiometricImportModal scope={scope} onClose={() => setImporting(false)}
          onDone={load} showSuccess={showSuccess} showError={showError} />
      )}
      {regularizing && (
        <RegularizeModal scope={scope} onClose={() => setRegularizing(false)}
          onDone={() => { setRegularizing(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const MarkModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [employee, setEmployee] = useState(null);
  const [workDate, setWorkDate] = useState(new Date().toISOString().slice(0, 10));
  const [actualIn, setActualIn] = useState('');
  const [actualOut, setActualOut] = useState('');
  const [overrideStatus, setOverrideStatus] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!employee) { showError('Select an employee.'); return; }
    run(() => markAttendance({
      employee_code: employee.employee_code, work_date: workDate,
      actual_in: actualIn || undefined, actual_out: actualOut || undefined,
      override_status: overrideStatus || undefined,
    }, scope), 'Attendance marked.');
  };

  return (
    <Modal title="Mark Attendance" labelledBy="att-mark-title"
      subtitle="Present, absent and late are worked out from the company's shift timings."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !employee}>
            {busy ? 'Working…' : 'Mark'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL}>Employee *</label>
        <EmployeePicker scope={scope} value={employee} onChange={setEmployee} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="att-date">Work Date *</label>
          <input id="att-date" type="date" value={workDate} className={FIELD}
            onChange={(e) => setWorkDate(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="att-override">Override Status</label>
          <select id="att-override" value={overrideStatus} className={FIELD}
            onChange={(e) => setOverrideStatus(e.target.value)}>
            <option value="">— derive from punches —</option>
            <option value="Weekly Off">Weekly Off</option>
            <option value="Holiday">Holiday</option>
          </select>
        </div>
      </div>
      {!overrideStatus && (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="att-in">Actual In</label>
            <input id="att-in" type="time" value={actualIn} className={FIELD}
              onChange={(e) => setActualIn(e.target.value)} />
          </div>
          <div>
            <label className={LABEL} htmlFor="att-out">Actual Out</label>
            <input id="att-out" type="time" value={actualOut} className={FIELD}
              onChange={(e) => setActualOut(e.target.value)} />
          </div>
        </div>
      )}
    </Modal>
  );
};

const RegularizeModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [employee, setEmployee] = useState(null);
  const [workDate, setWorkDate] = useState(new Date().toISOString().slice(0, 10));
  const [exceptionType, setExceptionType] = useState(EXCEPTION_TYPES[0]);
  const [proposedIn, setProposedIn] = useState('');
  const [proposedOut, setProposedOut] = useState('');
  const [reason, setReason] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!employee || !reason.trim()) {
      showError('Select the employee and describe the reason.');
      return;
    }
    run(() => requestRegularization({
      employee_code: employee.employee_code, work_date: workDate,
      exception_type: exceptionType, proposed_in: proposedIn || undefined,
      proposed_out: proposedOut || undefined, reason: reason.trim(),
    }, scope), 'Regularisation requested.');
  };

  return (
    <Modal title="Request Regularisation" labelledBy="att-reg-title"
      subtitle="Goes to the reporting manager first, then HR for the final approval."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !employee}>
            {busy ? 'Working…' : 'Submit'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL}>Employee *</label>
        <EmployeePicker scope={scope} value={employee} onChange={setEmployee} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="reg-date">Work Date *</label>
          <input id="reg-date" type="date" value={workDate} className={FIELD}
            onChange={(e) => setWorkDate(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="reg-type">Exception Type *</label>
          <select id="reg-type" value={exceptionType} className={FIELD}
            onChange={(e) => setExceptionType(e.target.value)}>
            {EXCEPTION_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={LABEL} htmlFor="reg-in">Proposed In</label>
          <input id="reg-in" type="time" value={proposedIn} className={FIELD}
            onChange={(e) => setProposedIn(e.target.value)} />
        </div>
        <div>
          <label className={LABEL} htmlFor="reg-out">Proposed Out</label>
          <input id="reg-out" type="time" value={proposedOut} className={FIELD}
            onChange={(e) => setProposedOut(e.target.value)} />
        </div>
      </div>
      <div>
        <label className={LABEL} htmlFor="reg-reason">Reason *</label>
        <textarea id="reg-reason" rows={2} value={reason} className={TEXTAREA}
          onChange={(e) => setReason(e.target.value)} />
      </div>
    </Modal>
  );
};

// ── Regularizations tab ──
const RegularizationsTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [acting, setActing] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getRegularizations({ ...scope, limit: 100 });
      setRows(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load regularisations.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'who', label: 'Employee', render: (r) => (
      <>
        <span className="font-semibold text-[var(--text-main)]">{r.employee_name || r.employee_code}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{r.req_no} · {day(r.work_date)}</span>
      </>
    ) },
    { key: 'type', label: 'Exception', render: (r) => (
      <span className="text-[var(--text-main)]">{r.exception_type}</span>
    ) },
    { key: 'proposed', label: 'Proposed', render: (r) => (
      <span className="text-[var(--text-main)]">{r.proposed_in || '—'} – {r.proposed_out || '—'}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
        {can(CAP.ATTENDANCE_REGULARIZE_APPROVE) &&
          (r.status === 'Pending' || r.status === 'Manager Approved') && (
          <Btn tone="ghost" onClick={() => setActing(r)}>Act</Btn>
        )}
      </div>
    ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{r.req_no} · {day(r.work_date)}</p>
        </div>
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
      </div>
      <Facts items={[
        { label: 'Exception', value: r.exception_type },
        { label: 'Proposed', value: `${r.proposed_in || '—'} – ${r.proposed_out || '—'}` },
        { label: 'Reason', value: r.reason },
      ]} />
      {can(CAP.ATTENDANCE_REGULARIZE_APPROVE) &&
        (r.status === 'Pending' || r.status === 'Manager Approved') && (
        <Btn tone="ghost" onClick={() => setActing(r)}>Act</Btn>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      {loading && <HrmsLoading label="Loading regularisations…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns} renderCard={renderCard} keyOf={(r) => r.req_no} />
        ) : (
          <HrmsEmpty icon={Clock} title="No regularisation requests"
            hint="Requests raised from the Attendance tab appear here." />
        )
      )}
      {acting && (
        <RegularizeActionModal row={acting} scope={scope} onClose={() => setActing(null)}
          onDone={() => { setActing(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const RegularizeActionModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const nextStep = row.status === 'Pending' ? 'Manager Approved' : 'Approved';

  const act = (decision) => run(
    () => actOnRegularization(row.req_no, { decision, remarks: remarks.trim() || undefined }, scope),
    `${row.req_no} ${decision.toLowerCase()}.`);

  return (
    <Modal title={`Act on ${row.req_no}`} labelledBy="reg-act-title"
      subtitle={row.status === 'Pending'
        ? 'Manager step — HR still gives the final sign-off after this.'
        : 'HR-final step — approving now recalculates the attendance record.'}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="danger" onClick={() => act('Rejected')} disabled={busy}>Reject</Btn>
          <Btn onClick={() => act('Returned')} disabled={busy}>Return</Btn>
          <Btn tone="primary" onClick={() => act(nextStep)} disabled={busy}>
            {busy ? 'Working…' : nextStep}
          </Btn>
        </>
      )}
    >
      <Facts items={[
        { label: 'Employee', value: row.employee_name || row.employee_code },
        { label: 'Work Date', value: day(row.work_date) },
        { label: 'Exception', value: row.exception_type },
        { label: 'Reason', value: row.reason },
      ]} />
      <div>
        <label className={LABEL} htmlFor="reg-act-remarks">Remarks</label>
        <textarea id="reg-act-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

// ── Outdoor Duty tab ──
const OdTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [requesting, setRequesting] = useState(false);
  const [acting, setActing] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getOdRequests({ ...scope, limit: 100 });
      setRows(data || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load OD requests.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'who', label: 'Employee', render: (r) => (
      <>
        <span className="font-semibold text-[var(--text-main)]">{r.employee_name || r.employee_code}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{r.od_no} · {day(r.od_date)}</span>
      </>
    ) },
    { key: 'purpose', label: 'Purpose', render: (r) => (
      <span className="text-[var(--text-main)]">{r.purpose}{r.location ? ` · ${r.location}` : ''}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
        {can(CAP.OD_APPROVE) && r.status === 'Pending' && (
          <Btn tone="ghost" onClick={() => setActing(r)}>Act</Btn>
        )}
      </div>
    ) },
  ];

  const renderCard = (r) => (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
          <p className="text-[11.5px] text-[var(--text-muted)]">{r.od_no} · {day(r.od_date)}</p>
        </div>
        <Chip tone={attLeaveToneFor(r.status)}>{r.status}</Chip>
      </div>
      <Facts items={[{ label: 'Purpose', value: r.purpose }, { label: 'Location', value: r.location }]} />
      {can(CAP.OD_APPROVE) && r.status === 'Pending' && (
        <Btn tone="ghost" onClick={() => setActing(r)}>Act</Btn>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        {can(CAP.OD_REQUEST) && <Btn tone="primary" onClick={() => setRequesting(true)}>Request OD</Btn>}
      </div>
      {loading && <HrmsLoading label="Loading OD requests…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns} renderCard={renderCard} keyOf={(r) => r.od_no} />
        ) : (
          <HrmsEmpty icon={Clock} title="No Outdoor Duty requests" />
        )
      )}
      {requesting && (
        <OdModal scope={scope} onClose={() => setRequesting(false)}
          onDone={() => { setRequesting(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
      {acting && (
        <OdActionModal row={acting} scope={scope} onClose={() => setActing(null)}
          onDone={() => { setActing(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const OdModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [employee, setEmployee] = useState(null);
  const [odDate, setOdDate] = useState(new Date().toISOString().slice(0, 10));
  const [purpose, setPurpose] = useState('');
  const [location, setLocation] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);

  const submit = () => {
    if (!employee || !purpose.trim()) { showError('Select the employee and describe the purpose.'); return; }
    run(() => requestOd({
      employee_code: employee.employee_code, od_date: odDate,
      purpose: purpose.trim(), location: location.trim() || undefined,
    }, scope), 'Outdoor Duty requested.');
  };

  return (
    <Modal title="Request Outdoor Duty" labelledBy="od-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy || !employee}>
            {busy ? 'Working…' : 'Submit'}
          </Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL}>Employee *</label>
        <EmployeePicker scope={scope} value={employee} onChange={setEmployee} />
      </div>
      <div>
        <label className={LABEL} htmlFor="od-date">OD Date *</label>
        <input id="od-date" type="date" value={odDate} className={FIELD}
          onChange={(e) => setOdDate(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="od-purpose">Purpose *</label>
        <input id="od-purpose" value={purpose} className={FIELD}
          onChange={(e) => setPurpose(e.target.value)} />
      </div>
      <div>
        <label className={LABEL} htmlFor="od-location">Location</label>
        <input id="od-location" value={location} className={FIELD}
          onChange={(e) => setLocation(e.target.value)} />
      </div>
    </Modal>
  );
};

const OdActionModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const act = (approved) => run(
    () => actOnOd(row.od_no, { approved, remarks: remarks.trim() || undefined }, scope),
    `${row.od_no} ${approved ? 'approved' : 'rejected'}.`);

  return (
    <Modal title={`Act on ${row.od_no}`} labelledBy="od-act-title" onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="danger" onClick={() => act(false)} disabled={busy}>Reject</Btn>
          <Btn tone="primary" onClick={() => act(true)} disabled={busy}>
            {busy ? 'Working…' : 'Approve'}
          </Btn>
        </>
      )}
    >
      <Facts items={[
        { label: 'Employee', value: row.employee_name || row.employee_code },
        { label: 'OD Date', value: day(row.od_date) },
        { label: 'Purpose', value: row.purpose },
      ]} />
      <div>
        <label className={LABEL} htmlFor="od-act-remarks">Remarks</label>
        <textarea id="od-act-remarks" rows={2} value={remarks} className={TEXTAREA}
          onChange={(e) => setRemarks(e.target.value)} />
      </div>
    </Modal>
  );
};

// ── Monthly Closure tab ──
const ClosureTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const [dash, setDash] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [unlocking, setUnlocking] = useState(false);
  const { busy, run } = useSubmit(showSuccess, showError, () => load());

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getClosureDashboard(period, scope);
      setDash(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the closure dashboard.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, period]);

  useEffect(() => { load(); }, [load]);

  if (!can(CAP.ATTENDANCE_CLOSURE_READ)) {
    return <HrmsEmpty icon={Lock} title="Monthly closure is managed by HR" />;
  }
  const canLock = can(CAP.ATTENDANCE_LOCK);

  return (
    <div className="space-y-4">
      <div>
        <label className={LABEL} htmlFor="closure-period">Period</label>
        <input id="closure-period" type="month" value={period} className={`${FIELD} max-w-[200px]`}
          onChange={(e) => setPeriod(e.target.value)} />
      </div>
      {loading && <HrmsLoading label="Loading closure dashboard…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && dash && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              ['Missing Punches', dash.missing_punches],
              ['Pending Regularisations', dash.pending_regularizations],
              ['Pending OD', dash.pending_od],
              ['Unexplained Absence', dash.unexplained_absence],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl border border-[var(--border)]
                bg-[var(--bg-card)] p-3.5">
                <p className="text-[10.5px] font-bold uppercase tracking-widest
                  text-[var(--text-muted)]">{label}</p>
                <p className="mt-1 text-[20px] font-bold text-[var(--text-main)]">{value}</p>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between rounded-xl border
            border-[var(--border)] bg-[var(--bg-card)] p-4">
            <div>
              <Chip tone={attLeaveToneFor(dash.status)}>{dash.status}</Chip>
              {dash.status === 'Locked' && (
                <p className="mt-1 text-[11.5px] text-[var(--text-muted)]">
                  Locked {day(dash.locked_at)}
                </p>
              )}
            </div>
            {!canLock ? null : dash.status === 'Locked' ? (
              <Btn onClick={() => setUnlocking(true)}><Unlock size={14} /> Unlock</Btn>
            ) : (
              <Btn tone="primary" disabled={busy || !dash.ready_to_lock}
                onClick={() => run(() => lockPeriod(period, scope), `${period} locked.`)}>
                <Lock size={14} /> {busy ? 'Working…' : 'Lock Period'}
              </Btn>
            )}
          </div>
          {!dash.ready_to_lock && dash.status !== 'Locked' && (
            <p className="text-[11.5px] text-[var(--text-muted)]">
              Resolve every exception above before this period can be locked.
            </p>
          )}
        </div>
      )}
      {unlocking && (
        <UnlockModal period={period} scope={scope} onClose={() => setUnlocking(false)}
          onDone={() => { setUnlocking(false); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const UnlockModal = ({ period, scope, onClose, onDone, showSuccess, showError }) => {
  const [reason, setReason] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const submit = () => {
    if (!reason.trim()) { showError('A reason is required to reopen a locked period.'); return; }
    run(() => unlockPeriod(period, reason.trim(), scope), `${period} reopened.`);
  };
  return (
    <Modal title={`Unlock ${period}`} labelledBy="unlock-title"
      subtitle="Once a month is locked, changing it means an authorised person reopens it and gives a reason."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>{busy ? 'Working…' : 'Unlock'}</Btn>
        </>
      )}
    >
      <div>
        <label className={LABEL} htmlFor="unlock-reason">Reason *</label>
        <textarea id="unlock-reason" rows={2} value={reason} className={TEXTAREA}
          onChange={(e) => setReason(e.target.value)} />
      </div>
    </Modal>
  );
};

// ── Settings: office timing, grace, buffer (the shift policy) ──
const TimingRulesCard = ({ scope, companyId, showSuccess, showError }) => {
  const [p, setP] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!companyId) return;
    getShiftPolicy(scope).then(({ data }) => setP(data)).catch(() => setP({}));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);
  if (!p) return <HrmsLoading label="Loading timing rules…" />;
  const set = (k) => (e) => setP((x) => ({ ...x, [k]: e.target.value }));
  const save = async () => {
    setSaving(true);
    try {
      const { data } = await saveShiftPolicy({
        shift_start: p.shift_start, shift_end: p.shift_end,
        daily_grace_minutes: Number(p.daily_grace_minutes),
        monthly_buffer_minutes: Number(p.monthly_buffer_minutes),
        half_day_threshold_minutes: Number(p.half_day_threshold_minutes),
      }, scope);
      setP(data);
      showSuccess('Timing rules saved. New punches are judged against them.');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the timing rules.');
    } finally { setSaving(false); }
  };
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 space-y-3">
      <div>
        <h3 className="text-[14px] font-bold text-[var(--text-main)]">Office timing, grace & buffer</h3>
        <p className="text-[12px] text-[var(--text-muted)]">
          Every punch — biometric, self check-in or marked by HR — is judged against these. An
          approved flexible timing replaces the office hours for that person on those dates.
        </p>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <div><label className={LABEL}>Office opens</label>
          <input type="time" className={FIELD} value={p.shift_start || ''} onChange={set('shift_start')} /></div>
        <div><label className={LABEL}>Office closes</label>
          <input type="time" className={FIELD} value={p.shift_end || ''} onChange={set('shift_end')} /></div>
        <div><label className={LABEL}>Daily grace (min)</label>
          <input type="number" min="0" max="120" className={FIELD} value={p.daily_grace_minutes ?? ''} onChange={set('daily_grace_minutes')} /></div>
        <div><label className={LABEL}>Monthly buffer (min)</label>
          <input type="number" min="0" max="1000" className={FIELD} value={p.monthly_buffer_minutes ?? ''} onChange={set('monthly_buffer_minutes')} /></div>
        <div><label className={LABEL}>Half day below (min)</label>
          <input type="number" min="0" max="720" className={FIELD} value={p.half_day_threshold_minutes ?? ''} onChange={set('half_day_threshold_minutes')} /></div>
      </div>
      <p className="text-[11.5px] text-[var(--text-muted)]">
        <b>Grace</b>: minutes after opening before a day counts as late. <b>Buffer</b>: total late
        minutes a person may use in a month; the Late Coming view shows what goes beyond it.
      </p>
      <div className="flex justify-end">
        <Btn tone="primary" disabled={saving} onClick={save}>{saving ? 'Saving…' : 'Save timing rules'}</Btn>
      </div>
    </section>
  );
};

// ── Flexible timing ──
const FLEXI_TONE = { Pending: 'warn', Approved: 'good', Rejected: 'bad', Cancelled: 'neutral' };
const FlexiTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [requesting, setRequesting] = useState(false);
  const [acting, setActing] = useState(null);
  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await getFlexiRequests(scope);
      setRows(data?.requests || []);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load flexible timing.');
    } finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);
  useEffect(() => { load(); }, [load]);

  const columns = [
    { key: 'who', label: 'Employee', render: (r) => (
      <>
        <span className="font-semibold text-[var(--text-main)]">{r.employee_name || r.employee_code}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{r.flexi_no}</span>
      </>
    ) },
    { key: 'dates', label: 'Dates', render: (r) => (
      <span className="text-[var(--text-main)]">{day(r.from_date)}{r.to_date !== r.from_date ? ` – ${day(r.to_date)}` : ''}</span>
    ) },
    { key: 'hours', label: 'Hours', render: (r) => (
      <span className="font-semibold text-[var(--text-main)]">{r.shift_start} – {r.shift_end}</span>
    ) },
    { key: 'why', label: 'Reason', render: (r) => (
      <span className="text-[12px] text-[var(--text-muted)]">{r.reason}{r.remarks ? ` · “${r.remarks}”` : ''}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (r) => (
      <div className="flex items-center justify-end gap-2">
        <Chip tone={FLEXI_TONE[r.status] || 'neutral'}>{r.status}</Chip>
        {r.status === 'Pending' && can(CAP.ATTENDANCE_FLEXI_APPROVE) && (
          <Btn onClick={() => setActing(r)}>Decide</Btn>
        )}
      </div>
    ) },
  ];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[12.5px] text-[var(--text-muted)]">
          Different working hours for some dates (e.g. 10:30–19:30). Once approved, those days are
          judged against the approved hours instead of the office timing.
        </p>
        {can(CAP.ATTENDANCE_FLEXI_REQUEST) && (
          <Btn tone="primary" onClick={() => setRequesting(true)}>Request flexible timing</Btn>
        )}
      </div>
      {loading && <HrmsLoading label="Loading flexible timing…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (rows.length ? (
        <RecordList rows={rows} columns={columns} keyOf={(r) => r.flexi_no}
          renderCard={(r) => (
            <div className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <p className="text-[13px] font-bold text-[var(--text-main)]">{r.employee_name || r.employee_code}</p>
                <Chip tone={FLEXI_TONE[r.status] || 'neutral'}>{r.status}</Chip>
              </div>
              <Facts items={[
                { label: 'Dates', value: `${day(r.from_date)} – ${day(r.to_date)}` },
                { label: 'Hours', value: `${r.shift_start} – ${r.shift_end}` },
              ]} />
              {r.status === 'Pending' && can(CAP.ATTENDANCE_FLEXI_APPROVE) && (
                <Btn onClick={() => setActing(r)}>Decide</Btn>
              )}
            </div>
          )} />
      ) : <HrmsEmpty icon={Clock} title="No flexible timing requests" />)}
      {requesting && (
        <FlexiModal scope={scope} onClose={() => setRequesting(false)}
          onDone={() => { setRequesting(false); load(); }} showSuccess={showSuccess} showError={showError} />
      )}
      {acting && (
        <FlexiActionModal row={acting} scope={scope} onClose={() => setActing(null)}
          onDone={() => { setActing(null); load(); }} showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const FlexiModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const today = new Date().toISOString().slice(0, 10);
  const [employee, setEmployee] = useState(null);
  const [f, setF] = useState({ from_date: today, to_date: today, shift_start: '10:30', shift_end: '19:30', reason: '' });
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const submit = () => {
    if (!employee || !f.reason.trim()) { showError('Select the employee and give the reason.'); return; }
    run(() => requestFlexi({ employee_code: employee.employee_code, ...f, reason: f.reason.trim() }, scope),
      'Flexible timing requested — it goes to the manager / HR.');
  };
  return (
    <Modal title="Request flexible timing" labelledBy="flexi-title" onClose={onClose}
      footer={(<>
        <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
        <Btn tone="primary" onClick={submit} disabled={busy || !employee}>{busy ? 'Working…' : 'Submit'}</Btn>
      </>)}>
      <div><label className={LABEL}>Employee *</label>
        <EmployeePicker scope={scope} value={employee} onChange={setEmployee} /></div>
      <div className="grid grid-cols-2 gap-3">
        <div><label className={LABEL}>From *</label><input type="date" className={FIELD} value={f.from_date} onChange={set('from_date')} /></div>
        <div><label className={LABEL}>To *</label><input type="date" className={FIELD} value={f.to_date} onChange={set('to_date')} /></div>
        <div><label className={LABEL}>Start *</label><input type="time" className={FIELD} value={f.shift_start} onChange={set('shift_start')} /></div>
        <div><label className={LABEL}>End *</label><input type="time" className={FIELD} value={f.shift_end} onChange={set('shift_end')} /></div>
      </div>
      <div><label className={LABEL}>Reason *</label>
        <textarea rows={2} className={TEXTAREA} value={f.reason} onChange={set('reason')}
          placeholder="e.g. Hospital visits this week; will cover the full hours." /></div>
    </Modal>
  );
};

const FlexiActionModal = ({ row, scope, onClose, onDone, showSuccess, showError }) => {
  const [remarks, setRemarks] = useState('');
  const { busy, run } = useSubmit(showSuccess, showError, onDone);
  const decide = (approved) => {
    if (!approved && !remarks.trim()) { showError('Say why it is not approved.'); return; }
    run(() => actOnFlexi(row.flexi_no, { approved, remarks: remarks.trim() || undefined }, scope),
      approved ? 'Approved — those days are now judged against the flexible hours.' : 'Not approved.');
  };
  return (
    <Modal title={`Flexible timing — ${row.employee_name || row.employee_code}`} labelledBy="flexi-act" onClose={onClose}
      footer={(<>
        <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
        <Btn tone="danger" onClick={() => decide(false)} disabled={busy}>Reject</Btn>
        <Btn tone="primary" onClick={() => decide(true)} disabled={busy}>Approve</Btn>
      </>)}>
      <Facts items={[
        { label: 'Dates', value: `${day(row.from_date)} – ${day(row.to_date)}` },
        { label: 'Hours', value: `${row.shift_start} – ${row.shift_end}` },
        { label: 'Reason', value: row.reason },
      ]} />
      <div><label className={LABEL}>Remarks {''}(required to reject)</label>
        <textarea rows={2} className={TEXTAREA} value={remarks} onChange={(e) => setRemarks(e.target.value)} /></div>
    </Modal>
  );
};

// ── Biometric import ──
const BiometricImportModal = ({ scope, onClose, onDone, showSuccess, showError }) => {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);
  const go = async () => {
    setBusy(true);
    try {
      const { data } = await importBiometric(file, scope);
      setReport(data);
      showSuccess(`Imported: ${data.days_created} new day(s), ${data.days_updated} updated.`);
      onDone();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not import that file.');
    } finally { setBusy(false); }
  };
  const template = () => {
    const blob = new Blob(['Employee Code,Date,Time\nEMP-2026-007,2026-10-01,09:28\nEMP-2026-007,2026-10-01,18:36\n'], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'biometric-template.csv';
    document.body.appendChild(a); a.click(); a.remove();
  };
  return (
    <Modal title="Import the biometric file" labelledBy="bio-title" onClose={onClose}
      footer={(<>
        <Btn onClick={onClose} disabled={busy}>{report ? 'Close' : 'Cancel'}</Btn>
        {!report && <Btn tone="primary" onClick={go} disabled={busy || !file}>{busy ? 'Importing…' : 'Import'}</Btn>}
      </>)}>
      <p className="text-[12.5px] text-[var(--text-muted)]">
        Upload the machine's export (CSV or Excel). For each person and day the <b>first punch is
        check-in</b> and the <b>last is check-out</b>. Columns: <b>Employee Code</b> (or Biometric ID),
        <b> Date</b>, and <b>Time</b> — or <b>In Time</b> / <b>Out Time</b>, or one <b>Date Time</b> column.
        Locked days, leave, OD, holidays and regularised days are never overwritten.
      </p>
      <button type="button" onClick={template} className="text-[12px] font-semibold text-[var(--accent-indigo)] hover:underline">
        Download a sample file
      </button>
      {!report && (
        <input type="file" accept=".csv,.xlsx,.xlsm,.txt" onChange={(e) => setFile(e.target.files?.[0] || null)}
          className="block w-full text-[12.5px] text-[var(--text-main)]" />
      )}
      {report && (
        <div className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] p-3 text-[12.5px] space-y-1">
          <p><b>{report.days_created}</b> new day(s), <b>{report.days_updated}</b> updated.</p>
          {!!report.skipped?.length && (
            <p className="text-[var(--accent-orange)]">{report.skipped.length} skipped: {report.skipped.slice(0, 6).map((s) => `${s.employee_code} ${s.work_date} (${s.reason})`).join('; ')}{report.skipped.length > 6 ? '…' : ''}</p>
          )}
          {!!report.unknown_codes?.length && (
            <p className="text-[var(--accent-red)]">Unknown code(s): {report.unknown_codes.join(', ')} — add them to the employee's Biometric ID or check the code.</p>
          )}
          {!!report.unreadable_rows?.length && (
            <p className="text-[var(--text-muted)]">{report.unreadable_rows.length} unreadable row(s), e.g. row {report.unreadable_rows[0].row}.</p>
          )}
        </div>
      )}
    </Modal>
  );
};

export default AttendanceBoard;
