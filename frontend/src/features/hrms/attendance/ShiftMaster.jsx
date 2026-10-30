import React, { useCallback, useEffect, useState } from 'react';
import { CalendarClock, Plus } from 'lucide-react';
import { CAP } from '../access';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { listShifts, saveShift, getEmployeeMasterLists, getDepartments } from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';
import {
  WEEKDAYS, SATURDAY_CHOICES, saturdayKey, describeWeeklyOff, errorDetail, stamp, todayIso,
} from './attendanceRules';

/**
 * HRMS ▸ Attendance ▸ Shifts (Phase 1 FRD §5, §23, §26).
 *
 * The shift master: named working patterns with their own timing, grace, thresholds and
 * weekly off. Every save is a VERSION with an effective date, never an edit in place — a day
 * is always judged by the version in force on that day, so changing grace "from next month"
 * leaves this month's judged days exactly as they were. That is why the editor asks for an
 * effective date. A back-dated version is allowed only into a month that is not locked and
 * needs a reason (FRD §26): closed months are never rewritten.
 */

// Applicability dimensions, in the order the editor shows them. `list` names the
// employee-master dropdown each one draws its values from.
const APPLICABILITY = [
  { key: 'attendance_policy_groups', label: 'Attendance policy groups', list: 'attendance_policy_groups' },
  { key: 'locations', label: 'Locations', list: 'locations' },
  { key: 'employee_categories', label: 'Employee categories', list: 'employee_categories' },
  { key: 'grades', label: 'Grades', list: 'grades' },
  { key: 'levels', label: 'Levels', list: 'levels' },
];

const RESOLUTION_HELP = (
  <>
    Which shift judges a person is decided in this order: <b>1)</b> the shift set on the
    employee (Employee Master ▸ Work setup), <b>2)</b> the most specific active shift whose
    &ldquo;applies to&rdquo; rules all match the employee, <b>3)</b> the company timing on the
    Settings tab. A shift with no &ldquo;applies to&rdquo; rules is only used when set on an
    employee.
  </>
);

/** Pill toggles for a short list of values (the same control the policy register uses). */
const MultiCheck = ({ label, options, value, onChange, optionLabel = (o) => o, optionValue = (o) => o }) => (
  <div>
    <label className={LABEL}>{label}</label>
    <div className="flex flex-wrap gap-1.5">
      {options.map((opt) => {
        const v = optionValue(opt);
        const checked = value.includes(v);
        return (
          <button key={v} type="button" aria-pressed={checked}
            onClick={() => onChange(checked ? value.filter((x) => x !== v) : [...value, v])}
            className={`px-2.5 h-7 rounded-full border text-[11.5px] font-semibold transition-colors
              ${checked
                ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo)]/10 text-[var(--accent-indigo)]'
                : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
            {optionLabel(opt)}
          </button>
        );
      })}
    </div>
    {!options.length && (
      <p className="text-[11px] text-[var(--text-muted)]">
        None configured — add values under Employee Master settings.
      </p>
    )}
  </div>
);

/**
 * Weekly-off editor shared by the company timing and the shift editor.
 *
 * Plain weekdays are checkboxes; Saturday is a choice because "2nd & 4th Saturday" is the
 * usual case. A pattern this editor cannot express (say, only the 3rd Saturday, set over the
 * API) is kept as-is and shown as Custom until someone picks a preset.
 */
export const WeeklyOffEditor = ({ value, onChange, idPrefix }) => {
  const pattern = value || [];
  const sat = saturdayKey(pattern);
  const others = pattern.filter((s) => s.includes('#') && !s.startsWith('Saturday'));
  const toggle = (d) => onChange(pattern.includes(d) ? pattern.filter((x) => x !== d) : [...pattern, d]);
  const setSaturday = (key) => {
    const choice = SATURDAY_CHOICES.find((c) => c.key === key);
    if (!choice) return;
    onChange([...pattern.filter((s) => !s.startsWith('Saturday')), ...choice.entries]);
  };
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-x-4 gap-y-1.5">
        {WEEKDAYS.filter((d) => d !== 'Saturday').map((d) => (
          <label key={d} className="inline-flex items-center gap-1.5 text-[12.5px] text-[var(--text-main)]">
            <input type="checkbox" checked={pattern.includes(d)} onChange={() => toggle(d)} />
            {d}
          </label>
        ))}
      </div>
      <div className="max-w-[260px]">
        <label className="sr-only" htmlFor={`${idPrefix}-sat`}>Saturday</label>
        <select id={`${idPrefix}-sat`} className={FIELD} value={sat}
          onChange={(e) => setSaturday(e.target.value)}>
          {SATURDAY_CHOICES.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          {sat === 'custom' && (
            <option value="custom" disabled>
              Custom ({describeWeeklyOff(pattern.filter((s) => s.startsWith('Saturday')))})
            </option>
          )}
        </select>
      </div>
      {!!others.length && (
        <p className="text-[11px] text-[var(--text-muted)]">Also off: {describeWeeklyOff(others)}</p>
      )}
    </div>
  );
};

// The version the editor starts from: the latest one, so "add a version" begins from the
// rules most recently decided rather than from whatever is in force today.
const latestVersion = (shift) => {
  const versions = [...(shift?.versions || [])].sort((a, b) => a.effective_from.localeCompare(b.effective_from));
  return versions[versions.length - 1] || null;
};

const timing = (v) => (v ? `${v.start} – ${v.end}` : '—');

const appliesTo = (shift, deptName) => {
  const a = shift.applicability || {};
  const parts = [
    ...APPLICABILITY.filter((d) => a[d.key]?.length).map((d) => a[d.key].join(', ')),
    ...(a.department_ids?.length ? [a.department_ids.map((id) => deptName[id] || id).join(', ')] : []),
  ];
  return parts.length ? parts.join(' · ') : 'Set on employees only';
};

// ── Shifts tab ──
export const ShiftsTab = ({ scope, companyId, can, showSuccess, showError }) => {
  const [rows, setRows] = useState([]);
  const [lists, setLists] = useState({});
  const [departments, setDepartments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // `null` closed, `{}` a new shift, otherwise the shift being given a new version.
  const [editing, setEditing] = useState(null);
  const canManage = can(CAP.LEAVE_POLICY_MANAGE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await listShifts(scope);
      setRows(data || []);
    } catch (err) {
      setError(errorDetail(err, 'Could not load the shift master.'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  // Dropdown sources for "applies to" — optional: a company that has not configured them
  // can still create shifts and assign them on the employee.
  useEffect(() => {
    if (!companyId) return;
    getEmployeeMasterLists(scope).then(({ data }) => setLists(data || {})).catch(() => {});
    getDepartments(scope).then(({ data }) => setDepartments(data?.departments || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  const deptName = Object.fromEntries(departments.map((d) => [d.id, d.name]));
  const upcomingNote = (s) => (s.upcoming?.length
    ? `Changes from ${s.upcoming.map((v) => day(v.effective_from)).join(', ')}`
    : null);

  const columns = [
    { key: 'shift', label: 'Shift', render: (s) => (
      <>
        <span className="font-semibold text-[var(--text-main)]">{s.code}</span>
        <span className="block text-[11px] text-[var(--text-muted)]">{s.name}</span>
      </>
    ) },
    { key: 'timing', label: 'Current timing', render: (s) => (
      <>
        <span className="text-[var(--text-main)]">{s.current ? timing(s.current) : 'Not yet in force'}</span>
        {s.current && (
          <span className="block text-[11px] text-[var(--text-muted)]">
            Break {s.current.break_minutes ?? 0}m{s.current.min_hours != null ? ` · min ${s.current.min_hours}h` : ''}
            {s.current.flexible ? ' · flexible' : ''}
          </span>
        )}
      </>
    ) },
    { key: 'grace', label: 'Grace', render: (s) => (
      <span className="text-[12px] text-[var(--text-main)]">
        {s.current ? `Late ${s.current.daily_grace_minutes ?? 0}m · Early ${s.current.early_going_grace_minutes ?? 0}m` : '—'}
      </span>
    ) },
    { key: 'off', label: 'Weekly off', render: (s) => (
      <span className="text-[12px] text-[var(--text-main)]">
        {s.current?.weekly_off_pattern ? describeWeeklyOff(s.current.weekly_off_pattern) : 'Company default'}
      </span>
    ) },
    { key: 'applies', label: 'Applies to', render: (s) => (
      <span className="text-[12px] text-[var(--text-muted)]">{appliesTo(s, deptName)}</span>
    ) },
    { key: 'status', label: 'Status', align: 'right', render: (s) => (
      <div className="flex flex-col items-end gap-1.5">
        <Chip tone={s.active === false ? 'neutral' : 'good'}>{s.active === false ? 'Inactive' : 'Active'}</Chip>
        {upcomingNote(s) && <span className="text-[11px] text-[var(--accent-orange)]">{upcomingNote(s)}</span>}
        {canManage && <Btn onClick={() => setEditing(s)}>Edit / new version</Btn>}
      </div>
    ) },
  ];

  const renderCard = (s) => (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[13px] font-bold text-[var(--text-main)]">{s.code}</p>
          <p className="text-[11.5px] text-[var(--text-muted)] truncate">{s.name}</p>
        </div>
        <Chip tone={s.active === false ? 'neutral' : 'good'}>{s.active === false ? 'Inactive' : 'Active'}</Chip>
      </div>
      <Facts items={[
        { label: 'Timing', value: s.current ? timing(s.current) : 'Not yet in force' },
        { label: 'Grace', value: s.current ? `${s.current.daily_grace_minutes ?? 0}m / ${s.current.early_going_grace_minutes ?? 0}m` : null },
        { label: 'Weekly off', value: s.current?.weekly_off_pattern ? describeWeeklyOff(s.current.weekly_off_pattern) : 'Company default' },
        { label: 'Applies to', value: appliesTo(s, deptName) },
        { label: 'Upcoming', value: upcomingNote(s) },
      ]} />
      {canManage && <Btn onClick={() => setEditing(s)}>Edit / new version</Btn>}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-3xl">{RESOLUTION_HELP}</p>
        {canManage && (
          <Btn tone="primary" onClick={() => setEditing({})}><Plus size={14} /> New shift</Btn>
        )}
      </div>
      {loading && <HrmsLoading label="Loading shifts…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && (
        rows.length ? (
          <RecordList rows={rows} columns={columns} renderCard={renderCard} keyOf={(s) => s.code} />
        ) : (
          <HrmsEmpty icon={CalendarClock} title="No shifts yet"
            hint="Until a shift exists, everyone is judged against the company timing on the Settings tab." />
        )
      )}
      {editing && (
        <ShiftEditorModal shift={editing.code ? editing : null} lists={lists} departments={departments}
          scope={scope} onClose={() => setEditing(null)}
          onDone={() => { setEditing(null); load(); }}
          showSuccess={showSuccess} showError={showError} />
      )}
    </div>
  );
};

const numOrBlank = (v) => (v == null ? '' : String(v));

const ShiftEditorModal = ({ shift, lists, departments, scope, onClose, onDone, showSuccess, showError }) => {
  const base = latestVersion(shift);
  const today = todayIso();
  const [f, setF] = useState(() => ({
    code: shift?.code || '',
    name: shift?.name || '',
    effective_from: today,
    start: base?.start || '09:30',
    end: base?.end || '18:30',
    break_minutes: numOrBlank(base?.break_minutes ?? 0),
    min_hours: numOrBlank(base?.min_hours),
    daily_grace_minutes: numOrBlank(base?.daily_grace_minutes ?? 5),
    early_going_grace_minutes: numOrBlank(base?.early_going_grace_minutes ?? 0),
    half_day_threshold_minutes: numOrBlank(base?.half_day_threshold_minutes ?? 240),
    absent_threshold_minutes: numOrBlank(base?.absent_threshold_minutes),
    monthly_buffer_minutes: numOrBlank(base?.monthly_buffer_minutes ?? 60),
    flexible: !!base?.flexible,
    weekly_off_pattern: base?.weekly_off_pattern || ['Sunday'],
    active: shift ? shift.active !== false : true,
    reason: '',
  }));
  const [applicability, setApplicability] = useState(() => ({
    attendance_policy_groups: [], locations: [], employee_categories: [], grades: [], levels: [],
    department_ids: [],
    ...(shift?.applicability || {}),
  }));
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const setApp = (k) => (vals) => setApplicability((a) => ({ ...a, [k]: vals }));
  // A version on the same date replaces that version; any other date adds one.
  const replacing = (shift?.versions || []).some((v) => v.effective_from === f.effective_from);

  const submit = async () => {
    if (!f.code.trim() || !f.name.trim()) { showError('A shift needs a code and a name.'); return; }
    if (!f.start || !f.end) { showError('Give the start and end time.'); return; }
    if (f.effective_from < today && !f.reason.trim()) {
      showError('A back-dated change needs a reason. Locked months are never changed.');
      return;
    }
    const n = (v) => (v === '' || v == null ? undefined : Number(v));
    setBusy(true);
    try {
      await saveShift({
        code: f.code.trim().toUpperCase(), name: f.name.trim(), effective_from: f.effective_from,
        start: f.start, end: f.end,
        break_minutes: n(f.break_minutes), min_hours: n(f.min_hours),
        daily_grace_minutes: n(f.daily_grace_minutes),
        early_going_grace_minutes: n(f.early_going_grace_minutes),
        half_day_threshold_minutes: n(f.half_day_threshold_minutes),
        absent_threshold_minutes: n(f.absent_threshold_minutes),
        monthly_buffer_minutes: n(f.monthly_buffer_minutes),
        flexible: f.flexible, weekly_off_pattern: f.weekly_off_pattern,
        applicability, active: f.active, reason: f.reason.trim() || undefined,
      }, scope);
      showSuccess(shift
        ? `${f.code.toUpperCase()} saved — the new rules apply from ${day(f.effective_from)}.`
        : `Shift ${f.code.toUpperCase()} created.`);
      onDone();
    } catch (err) {
      showError(errorDetail(err, 'Could not save the shift.'));
    } finally {
      setBusy(false);
    }
  };

  // A value already saved on the shift stays selectable even if it has since been removed
  // from the master list — otherwise saving would silently drop it.
  const optionsFor = (d) => [...new Set([...(lists[d.list] || []), ...(applicability[d.key] || [])])];
  const history = [...(shift?.versions || [])].sort((a, b) => b.effective_from.localeCompare(a.effective_from));

  const num = (key, label, props = {}) => (
    <div>
      <label className={LABEL} htmlFor={`shift-${key}`}>{label}</label>
      <input id={`shift-${key}`} type="number" min="0" className={FIELD}
        value={f[key]} onChange={set(key)} {...props} />
    </div>
  );

  return (
    <Modal wide title={shift ? `Shift ${shift.code} — new version` : 'New shift'} labelledBy="shift-edit-title"
      subtitle={shift
        ? 'Rules change from the effective date; days before it keep the rule they were judged by.'
        : 'Takes effect from the date below. Assign it on employees, or let it apply by the rules at the end.'}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose} disabled={busy}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : replacing ? 'Replace version' : shift ? 'Add version' : 'Create shift'}
          </Btn>
        </>
      )}
    >
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <div>
          <label className={LABEL} htmlFor="shift-code">Code *</label>
          <input id="shift-code" className={FIELD} value={f.code} disabled={!!shift} maxLength={20}
            onChange={set('code')} placeholder="e.g. GEN" />
        </div>
        <div>
          <label className={LABEL} htmlFor="shift-name">Name *</label>
          <input id="shift-name" className={FIELD} value={f.name} maxLength={80}
            onChange={set('name')} placeholder="e.g. General shift" />
        </div>
        <div className="col-span-2 sm:col-span-1">
          <label className={LABEL} htmlFor="shift-eff">Effective from *</label>
          <input id="shift-eff" type="date" className={FIELD} value={f.effective_from}
            onChange={set('effective_from')} />
        </div>
      </div>
      {f.effective_from && f.effective_from < today && (
        <p className="text-[11.5px] text-[var(--accent-orange)]">
          Back-dated: allowed only into a month that is not locked, with a reason. Days already
          recorded keep their values until they are re-marked or regularised.
        </p>
      )}
      {replacing && (
        <p className="text-[11.5px] text-[var(--accent-orange)]">
          A version from {day(f.effective_from)} already exists — saving replaces it.
        </p>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div>
          <label className={LABEL} htmlFor="shift-start">Start *</label>
          <input id="shift-start" type="time" className={FIELD} value={f.start} onChange={set('start')} />
        </div>
        <div>
          <label className={LABEL} htmlFor="shift-end">End *</label>
          <input id="shift-end" type="time" className={FIELD} value={f.end} onChange={set('end')} />
        </div>
        {num('break_minutes', 'Break (min)', { max: 1440 })}
        {/* Overrides the attendance policy's minimum hours for this shift (DEP-06); blank
            keeps the policy's value. */}
        {num('min_hours', 'Min hours (this shift)', { max: 24, step: '0.25', placeholder: 'policy value' })}
        {num('daily_grace_minutes', 'Late grace (min)', { max: 1440 })}
        {num('early_going_grace_minutes', 'Early-going grace', { max: 1440 })}
        {num('half_day_threshold_minutes', 'Half day below (min)', { max: 1440 })}
        {num('absent_threshold_minutes', 'Absent below (min)', { max: 1440, placeholder: 'none' })}
        {num('monthly_buffer_minutes', 'Monthly buffer (min)', { max: 1440 })}
      </div>
      <label className="inline-flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
        <input type="checkbox" checked={f.flexible}
          onChange={(e) => setF((x) => ({ ...x, flexible: e.target.checked }))} />
        Flexible shift
      </label>

      <div>
        <p className={LABEL}>Weekly off</p>
        <WeeklyOffEditor idPrefix="shift-wo" value={f.weekly_off_pattern}
          onChange={(v) => setF((x) => ({ ...x, weekly_off_pattern: v }))} />
      </div>

      <div className="space-y-3 rounded-lg border border-[var(--border)] p-3">
        <p className="text-[12px] text-[var(--text-muted)]">
          <b className="text-[var(--text-main)]">Applies to</b> — every rule you fill in must match
          the employee; the more that match, the more specific the shift. Leave all empty to use
          this shift only where it is set on an employee.
        </p>
        {APPLICABILITY.map((d) => (
          <MultiCheck key={d.key} label={d.label} options={optionsFor(d)}
            value={applicability[d.key] || []} onChange={setApp(d.key)} />
        ))}
        {departments.length > 0 && (
          <MultiCheck label="Departments" options={departments} value={applicability.department_ids || []}
            onChange={setApp('department_ids')} optionValue={(d) => d.id} optionLabel={(d) => d.name} />
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-start">
        <div className="sm:col-span-2">
          <label className={LABEL} htmlFor="shift-reason">Reason for the change</label>
          <textarea id="shift-reason" rows={2} className={TEXTAREA} value={f.reason} onChange={set('reason')}
            placeholder="e.g. Grace raised from 5 to 10 minutes from next month." />
        </div>
        <label className="inline-flex items-center gap-2 text-[12.5px] text-[var(--text-main)] sm:mt-6">
          <input type="checkbox" checked={f.active}
            onChange={(e) => setF((x) => ({ ...x, active: e.target.checked }))} />
          Active
        </label>
      </div>

      {history.length > 0 && (
        <div>
          <p className={LABEL}>Version history</p>
          <ul className="space-y-1.5">
            {history.map((v) => {
              const inForce = shift.current?.effective_from === v.effective_from;
              const upcoming = v.effective_from > today;
              return (
                <li key={v.effective_from}
                  className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2 text-[12px]">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-semibold text-[var(--text-main)]">From {day(v.effective_from)}</span>
                    {inForce && <Chip tone="good">In force</Chip>}
                    {upcoming && <Chip tone="warn">Upcoming</Chip>}
                  </div>
                  <p className="text-[var(--text-muted)]">
                    {timing(v)} · break {v.break_minutes ?? 0}m
                    {v.min_hours != null ? ` · min ${v.min_hours}h` : ''} · grace {v.daily_grace_minutes ?? 0}m
                    {' '}/ early {v.early_going_grace_minutes ?? 0}m · half day &lt; {v.half_day_threshold_minutes ?? '—'}m
                    {v.absent_threshold_minutes != null ? ` · absent < ${v.absent_threshold_minutes}m` : ''}
                    {' '}· off {v.weekly_off_pattern ? describeWeeklyOff(v.weekly_off_pattern) : 'company default'}
                  </p>
                  {(v.reason || v.created_at) && (
                    <p className="text-[11px] text-[var(--text-muted)]">
                      {v.reason ? `“${v.reason}” · ` : ''}saved {stamp(v.created_at)}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Modal>
  );
};
