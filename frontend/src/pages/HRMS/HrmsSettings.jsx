import React, { useCallback, useEffect, useState } from 'react';
import {
  Settings as SettingsIcon, Wallet, MapPin, CalendarRange, Loader2, AlertTriangle,
  Save, Plus, Trash2, Lock, Info,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import {
  getPayrollConfig, updatePayrollConfig,
  getAttendanceSettings, updateAttendanceSettings,
  getLeaveSettings, updateLeaveSettings,
} from '../../services/hrmsApi';
import { hasHrmsPermission } from '../../utils/hrmsAccess';
import { Field } from '../../components/hrms/hrmsUi';
import { inputCls } from '../../components/hrms/hrmsStyles';

// HRMS ▸ Settings. One screen for the three policy objects the backend already serves but nothing
// consumed: payroll config, attendance policy and leave types. Each tab loads lazily and saves the
// whole object it owns, surfacing the server's `detail` on a rejected value (bounds live server-side).
//
// Permission note: the backend gates payroll config on payroll.read/update, attendance policy on
// attendance.update — and LEAVE settings write on attendance.update too (not a leave grant). The
// Save buttons mirror that exactly, and inputs stay read-only when the caller can't write.

// Payroll config is a flat bag of numbers. Times-of-day are stored as minutes since midnight, so
// those get a time input; everything else is a plain number. Bounds are the server's to enforce.
const PAYROLL_GROUPS = [
  {
    title: 'Salary & shift',
    fields: [
      { key: 'salary_base_days', label: 'Salary base days', kind: 'number', hint: '0 = use the actual number of days in the month' },
      { key: 'shift_start', label: 'Shift start', kind: 'time' },
      { key: 'shift_end', label: 'Shift end', kind: 'time' },
      { key: 'working_hours_per_day', label: 'Working hours / day', kind: 'number' },
    ],
  },
  {
    title: 'Late entry',
    fields: [
      { key: 'late_flat_fine_after', label: 'Flat fine after', kind: 'time' },
      { key: 'late_flat_fine_amount', label: 'Flat fine amount (₹)', kind: 'number' },
      { key: 'late_hour_penalty_after', label: 'Hour penalty after', kind: 'time' },
      { key: 'late_hour_penalty_hours', label: 'Hour penalty (hours)', kind: 'number', step: 0.5 },
    ],
  },
  {
    title: 'Overtime',
    fields: [
      { key: 'ot_eligible_from', label: 'Eligible from', kind: 'time' },
      { key: 'ot_min_minutes', label: 'Minimum minutes', kind: 'number' },
      { key: 'ot_multiplier', label: 'Rate multiplier (×)', kind: 'number', step: 0.1 },
    ],
  },
  {
    title: 'Leave & deductions',
    fields: [
      { key: 'unauthorized_leave_penalty_days', label: 'Unauthorized absence penalty (days)', kind: 'number', step: 0.5 },
      { key: 'paid_leaves_per_year', label: 'Paid leaves / year (days)', kind: 'number', step: 0.5 },
      { key: 'max_monthly_leaves_before_sunday_loss', label: 'Max monthly leaves before Sunday loss', kind: 'number', step: 0.5 },
      { key: 'professional_tax', label: 'Professional tax (₹)', kind: 'number' },
    ],
  },
];
const PAYROLL_FIELDS = PAYROLL_GROUPS.flatMap((g) => g.fields);

// Python weekday(): Mon=0 … Sun=6, matching what the backend stores in weekly_offs.
const WEEKDAYS = [['Mon', 0], ['Tue', 1], ['Wed', 2], ['Thu', 3], ['Fri', 4], ['Sat', 5], ['Sun', 6]];

const EMPTY_LEAVE_TYPE = {
  code: '', name: '', paid: true, annual_quota: 0, allow_half_day: true, active: true,
};

const minToHHMM = (m) => {
  const n = Math.max(0, Math.min(1439, Math.round(Number(m) || 0)));
  return `${String(Math.floor(n / 60)).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}`;
};
const hhmmToMin = (s) => {
  const [h, m] = String(s || '0:0').split(':').map((x) => parseInt(x, 10) || 0);
  return h * 60 + m;
};

// ─── Small shared pieces ──────────────────────────────────────────────────────────
const Toggle = ({ checked, onChange, disabled }) => (
  <button
    type="button" role="switch" aria-checked={checked} disabled={disabled}
    onClick={() => onChange(!checked)}
    className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
      checked ? 'bg-[var(--accent-indigo)]' : 'bg-[var(--border)]'
    }`}
  >
    <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
      checked ? 'translate-x-6' : 'translate-x-1'
    }`} />
  </button>
);

const ToggleRow = ({ label, hint, checked, onChange, disabled }) => (
  <div className="flex items-center justify-between gap-3 p-3.5 rounded-xl bg-[var(--input-bg)] border border-[var(--input-border)]">
    <div className="min-w-0">
      <div className="text-[12.5px] font-bold text-[var(--text-main)]">{label}</div>
      {hint && <div className="text-[10.5px] font-medium text-[var(--text-muted)] mt-0.5">{hint}</div>}
    </div>
    <Toggle checked={checked} onChange={onChange} disabled={disabled} />
  </div>
);

const SectionTitle = ({ children }) => (
  <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)]">{children}</h3>
);

const PermissionNote = ({ children }) => (
  <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
    style={{ color: 'var(--text-muted)', backgroundColor: 'var(--input-bg)', borderColor: 'var(--border)' }}>
    <Lock size={15} className="shrink-0" /> {children}
  </div>
);

const ErrorBox = ({ children }) => (
  <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
    style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
    <AlertTriangle size={15} className="shrink-0" /> {children}
  </div>
);

const Spinner = () => (
  <div className="flex items-center justify-center gap-2.5 py-16 text-[var(--text-muted)]">
    <Loader2 size={18} className="animate-spin" />
    <span className="text-[13px] font-bold">Loading…</span>
  </div>
);

const SaveButton = ({ onClick, saving, label }) => (
  <button onClick={onClick} disabled={saving}
    className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] disabled:opacity-50 transition-all">
    {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} {label}
  </button>
);

const HrmsSettings = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();

  const canReadPayroll = hasHrmsPermission(user, 'payroll', 'read');
  const canUpdatePayroll = hasHrmsPermission(user, 'payroll', 'update');
  // Attendance AND leave settings both write under attendance.update, matching the backend gate.
  const canUpdateAttendance = hasHrmsPermission(user, 'attendance', 'update');

  const TABS = [
    { key: 'payroll', label: 'Payroll', icon: Wallet },
    { key: 'attendance', label: 'Attendance', icon: MapPin },
    { key: 'leave', label: 'Leave Types', icon: CalendarRange },
  ];
  const [tab, setTab] = useState(canReadPayroll ? 'payroll' : 'attendance');

  // ── Payroll ──
  const [payroll, setPayroll] = useState(null);
  const [payrollLoading, setPayrollLoading] = useState(false);
  const [payrollErr, setPayrollErr] = useState('');
  const [savingPayroll, setSavingPayroll] = useState(false);

  const loadPayroll = useCallback(async () => {
    if (!canReadPayroll || payroll) return;
    setPayrollLoading(true); setPayrollErr('');
    try {
      const res = await getPayrollConfig();
      setPayroll(res.data);
    } catch (err) {
      setPayrollErr(err.response?.data?.detail || 'Failed to load payroll settings');
    } finally {
      setPayrollLoading(false);
    }
  }, [canReadPayroll, payroll]);

  const savePayroll = async () => {
    const payload = {};
    PAYROLL_FIELDS.forEach((f) => { payload[f.key] = Number(payroll[f.key]); });
    setSavingPayroll(true);
    try {
      const res = await updatePayrollConfig(payload);
      setPayroll(res.data);
      showSuccess('Payroll settings saved');
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save payroll settings');
    } finally {
      setSavingPayroll(false);
    }
  };

  // ── Attendance ──
  const [att, setAtt] = useState(null);
  const [attLoading, setAttLoading] = useState(false);
  const [attErr, setAttErr] = useState('');
  const [savingAtt, setSavingAtt] = useState(false);

  const loadAtt = useCallback(async () => {
    if (att) return;
    setAttLoading(true); setAttErr('');
    try {
      const res = await getAttendanceSettings();
      setAtt(res.data);
    } catch (err) {
      setAttErr(err.response?.data?.detail || 'Failed to load attendance settings');
    } finally {
      setAttLoading(false);
    }
  }, [att]);

  const saveAtt = async () => {
    setSavingAtt(true);
    try {
      const res = await updateAttendanceSettings({
        geofence_enabled: !!att.geofence_enabled,
        office_latitude: Number(att.office_latitude) || 0,
        office_longitude: Number(att.office_longitude) || 0,
        office_radius_meters: Number(att.office_radius_meters) || 0,
        selfie_required: !!att.selfie_required,
        shift_start: att.shift_start,
        shift_end: att.shift_end,
        weekly_offs: att.weekly_offs || [],
      });
      setAtt(res.data);
      showSuccess('Attendance settings saved');
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save attendance settings');
    } finally {
      setSavingAtt(false);
    }
  };

  const toggleWeeklyOff = (num) => setAtt((s) => {
    const on = (s.weekly_offs || []).includes(num);
    return {
      ...s,
      weekly_offs: on
        ? s.weekly_offs.filter((d) => d !== num)
        : [...(s.weekly_offs || []), num].sort((a, b) => a - b),
    };
  });

  // ── Leave ──
  const [leave, setLeave] = useState(null);
  const [leaveLoading, setLeaveLoading] = useState(false);
  const [leaveErr, setLeaveErr] = useState('');
  const [savingLeave, setSavingLeave] = useState(false);

  const loadLeave = useCallback(async () => {
    if (leave) return;
    setLeaveLoading(true); setLeaveErr('');
    try {
      const res = await getLeaveSettings();
      setLeave(res.data);
    } catch (err) {
      setLeaveErr(err.response?.data?.detail || 'Failed to load leave settings');
    } finally {
      setLeaveLoading(false);
    }
  }, [leave]);

  const updateType = (i, patch) =>
    setLeave((s) => ({ ...s, types: s.types.map((t, idx) => (idx === i ? { ...t, ...patch } : t)) }));
  const removeType = (i) =>
    setLeave((s) => ({ ...s, types: s.types.filter((_, idx) => idx !== i) }));
  const addType = () =>
    setLeave((s) => ({ ...s, types: [...(s.types || []), { ...EMPTY_LEAVE_TYPE }] }));

  const saveLeave = async () => {
    const types = (leave.types || []).map((t) => ({
      code: String(t.code || '').trim(),
      name: String(t.name || '').trim(),
      paid: !!t.paid,
      annual_quota: Number(t.annual_quota) || 0,
      allow_half_day: !!t.allow_half_day,
      active: !!t.active,
    }));
    if (types.length === 0) { showError('Add at least one leave type'); return; }
    if (types.some((t) => !t.code || !t.name)) {
      showError('Every leave type needs a code and a name'); return;
    }
    setSavingLeave(true);
    try {
      const res = await updateLeaveSettings({
        types,
        exclude_weekly_offs: !!leave.exclude_weekly_offs,
        exclude_holidays: !!leave.exclude_holidays,
        enforce_balance: !!leave.enforce_balance,
      });
      setLeave(res.data);
      showSuccess('Leave settings saved');
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save leave settings');
    } finally {
      setSavingLeave(false);
    }
  };

  // Load the active tab's data the first time it is shown.
  useEffect(() => {
    if (tab === 'payroll') loadPayroll();
    else if (tab === 'attendance') loadAtt();
    else loadLeave();
  }, [tab, loadPayroll, loadAtt, loadLeave]);

  return (
    <div className="p-6 sm:p-8 flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
          <SettingsIcon size={20} />
        </span>
        <div>
          <h1 className="text-xl sm:text-2xl font-black tracking-tight text-[var(--text-main)] leading-tight">
            HRMS Settings
          </h1>
          <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
            Payroll, attendance and leave policy
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-[11px] font-black uppercase tracking-widest transition-colors border ${
              tab === t.key
                ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]'
                : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'
            }`}>
            <t.icon size={14} /> {t.label}
          </button>
        ))}
      </div>

      {/* ── PAYROLL ── */}
      {tab === 'payroll' && (
        !canReadPayroll ? (
          <PermissionNote>You need the payroll read permission to view these settings.</PermissionNote>
        ) : payrollErr ? (
          <ErrorBox>{payrollErr}</ErrorBox>
        ) : (payrollLoading && !payroll) ? (
          <Spinner />
        ) : payroll ? (
          <>
            {PAYROLL_GROUPS.map((g) => (
              <div key={g.title} className="p-5 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-col gap-3.5">
                <SectionTitle>{g.title}</SectionTitle>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3.5">
                  {g.fields.map((f) => (
                    <Field key={f.key} label={f.label}>
                      {f.kind === 'time' ? (
                        <input type="time" className={inputCls} disabled={!canUpdatePayroll}
                          value={minToHHMM(payroll[f.key])}
                          onChange={(e) => setPayroll({ ...payroll, [f.key]: hhmmToMin(e.target.value) })} />
                      ) : (
                        <input type="number" className={inputCls} disabled={!canUpdatePayroll}
                          step={f.step || 1} value={payroll[f.key] ?? ''}
                          onChange={(e) => setPayroll({ ...payroll, [f.key]: e.target.value })} />
                      )}
                      {f.hint && (
                        <span className="text-[10.5px] font-medium text-[var(--text-muted)]">{f.hint}</span>
                      )}
                    </Field>
                  ))}
                </div>
              </div>
            ))}
            {canUpdatePayroll ? (
              <div className="flex justify-end">
                <SaveButton onClick={savePayroll} saving={savingPayroll} label="Save payroll settings" />
              </div>
            ) : (
              <PermissionNote>Read-only — the payroll update permission is required to change these.</PermissionNote>
            )}
          </>
        ) : null
      )}

      {/* ── ATTENDANCE ── */}
      {tab === 'attendance' && (
        attErr ? (
          <ErrorBox>{attErr}</ErrorBox>
        ) : (attLoading && !att) ? (
          <Spinner />
        ) : att ? (
          <>
            <div className="p-5 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-col gap-3.5">
              <SectionTitle>Geofence & selfie</SectionTitle>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <ToggleRow label="Geofencing" hint="Block a punch made outside the office radius."
                  checked={!!att.geofence_enabled} disabled={!canUpdateAttendance}
                  onChange={(v) => setAtt({ ...att, geofence_enabled: v })} />
                <ToggleRow label="Selfie required" hint="Require a photo at punch time."
                  checked={!!att.selfie_required} disabled={!canUpdateAttendance}
                  onChange={(v) => setAtt({ ...att, selfie_required: v })} />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
                <Field label="Office latitude">
                  <input type="number" step="any" className={inputCls} disabled={!canUpdateAttendance}
                    value={att.office_latitude ?? ''}
                    onChange={(e) => setAtt({ ...att, office_latitude: e.target.value })} />
                </Field>
                <Field label="Office longitude">
                  <input type="number" step="any" className={inputCls} disabled={!canUpdateAttendance}
                    value={att.office_longitude ?? ''}
                    onChange={(e) => setAtt({ ...att, office_longitude: e.target.value })} />
                </Field>
                <Field label="Office radius (metres)">
                  <input type="number" className={inputCls} disabled={!canUpdateAttendance}
                    value={att.office_radius_meters ?? ''}
                    onChange={(e) => setAtt({ ...att, office_radius_meters: e.target.value })} />
                </Field>
              </div>
            </div>

            <div className="p-5 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-col gap-3.5">
              <SectionTitle>Shift & weekly offs</SectionTitle>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                <Field label="Shift start">
                  <input type="time" className={inputCls} disabled={!canUpdateAttendance}
                    value={att.shift_start || '09:00'}
                    onChange={(e) => setAtt({ ...att, shift_start: e.target.value })} />
                </Field>
                <Field label="Shift end">
                  <input type="time" className={inputCls} disabled={!canUpdateAttendance}
                    value={att.shift_end || '17:00'}
                    onChange={(e) => setAtt({ ...att, shift_end: e.target.value })} />
                </Field>
              </div>
              <Field label="Weekly offs">
                <div className="flex flex-wrap gap-1.5">
                  {WEEKDAYS.map(([lbl, num]) => {
                    const on = (att.weekly_offs || []).includes(num);
                    return (
                      <button key={num} type="button" disabled={!canUpdateAttendance}
                        onClick={() => toggleWeeklyOff(num)}
                        className={`px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest border transition-colors disabled:opacity-50 ${
                          on
                            ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]'
                            : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'
                        }`}>
                        {lbl}
                      </button>
                    );
                  })}
                </div>
              </Field>
            </div>

            {canUpdateAttendance ? (
              <div className="flex justify-end">
                <SaveButton onClick={saveAtt} saving={savingAtt} label="Save attendance settings" />
              </div>
            ) : (
              <PermissionNote>Read-only — the attendance update permission is required to change these.</PermissionNote>
            )}
          </>
        ) : null
      )}

      {/* ── LEAVE TYPES ── */}
      {tab === 'leave' && (
        leaveErr ? (
          <ErrorBox>{leaveErr}</ErrorBox>
        ) : (leaveLoading && !leave) ? (
          <Spinner />
        ) : leave ? (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <ToggleRow label="Exclude weekly offs" hint="Don't count weekly-off days in a range."
                checked={!!leave.exclude_weekly_offs} disabled={!canUpdateAttendance}
                onChange={(v) => setLeave({ ...leave, exclude_weekly_offs: v })} />
              <ToggleRow label="Exclude holidays" hint="Skip public holidays in a range."
                checked={!!leave.exclude_holidays} disabled={!canUpdateAttendance}
                onChange={(v) => setLeave({ ...leave, exclude_holidays: v })} />
              <ToggleRow label="Enforce balance" hint="Reject an application over its annual quota."
                checked={!!leave.enforce_balance} disabled={!canUpdateAttendance}
                onChange={(v) => setLeave({ ...leave, enforce_balance: v })} />
            </div>

            <div className="rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full" style={{ minWidth: 780 }}>
                  <thead>
                    <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                      {['Code', 'Name', 'Paid', 'Annual quota', 'Half day', 'Active', ''].map((h, i) => (
                        <th key={i}
                          className="text-left px-3 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(leave.types || []).length === 0 && (
                      <tr><td colSpan={7} className="px-4 py-12 text-center">
                        <p className="text-[13px] font-bold text-[var(--text-main)]">No leave types.</p>
                        <p className="text-[12px] font-medium text-[var(--text-muted)] mt-1">
                          Add at least one so it can be offered on the apply form.
                        </p>
                      </td></tr>
                    )}
                    {(leave.types || []).map((t, i) => (
                      <tr key={i} className="border-b border-[var(--border)] last:border-0">
                        <td className="px-3 py-2.5">
                          <input className={`${inputCls} max-w-[130px]`} value={t.code || ''} placeholder="code"
                            disabled={!canUpdateAttendance}
                            onChange={(e) => updateType(i, { code: e.target.value })} />
                        </td>
                        <td className="px-3 py-2.5">
                          <input className={inputCls} value={t.name || ''} placeholder="Name"
                            disabled={!canUpdateAttendance}
                            onChange={(e) => updateType(i, { name: e.target.value })} />
                        </td>
                        <td className="px-3 py-2.5">
                          <Toggle checked={!!t.paid} disabled={!canUpdateAttendance}
                            onChange={(v) => updateType(i, { paid: v })} />
                        </td>
                        <td className="px-3 py-2.5">
                          <input type="number" step="0.5" className={`${inputCls} max-w-[110px]`}
                            value={t.annual_quota ?? 0} disabled={!canUpdateAttendance || !t.paid}
                            onChange={(e) => updateType(i, { annual_quota: e.target.value })} />
                        </td>
                        <td className="px-3 py-2.5">
                          <Toggle checked={!!t.allow_half_day} disabled={!canUpdateAttendance}
                            onChange={(v) => updateType(i, { allow_half_day: v })} />
                        </td>
                        <td className="px-3 py-2.5">
                          <Toggle checked={!!t.active} disabled={!canUpdateAttendance}
                            onChange={(v) => updateType(i, { active: v })} />
                        </td>
                        <td className="px-3 py-2.5 text-right">
                          <button type="button" disabled={!canUpdateAttendance} onClick={() => removeType(i)}
                            aria-label="Remove leave type"
                            className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] disabled:opacity-40 disabled:hover:bg-transparent transition-colors">
                            <Trash2 size={15} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {canUpdateAttendance && (
              <div>
                <button type="button" onClick={addType}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] transition-colors">
                  <Plus size={14} /> Add leave type
                </button>
              </div>
            )}

            <p className="flex items-start gap-2 text-[11px] font-medium text-[var(--text-muted)]">
              <Info size={13} className="mt-0.5 shrink-0" />
              An unpaid type ignores its quota and never blocks on balance. Configuring leave types uses
              the attendance update permission.
            </p>

            {canUpdateAttendance ? (
              <div className="flex justify-end">
                <SaveButton onClick={saveLeave} saving={savingLeave} label="Save leave settings" />
              </div>
            ) : (
              <PermissionNote>Read-only — the attendance update permission is required to change these.</PermissionNote>
            )}
          </>
        ) : null
      )}
    </div>
  );
};

export default HrmsSettings;
