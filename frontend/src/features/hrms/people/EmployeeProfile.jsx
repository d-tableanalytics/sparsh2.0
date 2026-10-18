import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, UserCircle, Save, Network, LayoutGrid, FileText, X, CalendarClock, AlertTriangle,
  Camera, Trash2,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getEmployee, createEmployee, updateEmployee, getEmployeeHierarchy, getDepartments, getDesignations,
  getAppointments, getEmployees, getEmployeeMasterLists, getEmployeeHistory,
  cancelScheduledEmployeeChange, checkEmployeeDuplicates, listFieldDefinitions,
  getDocuments, getDocumentUrl,
  saveEmployeePhotograph, deleteEmployeePhotograph, getEmployeePhotographUrl,
} from '../../../services/hrmsApi';
import DocumentPanel from '../documents/DocumentPanel';
import AppointmentPaper from '../recruitment/AppointmentPaper';
import GmpPanel from './GmpPanel';
import EmployeeSalaryStructure from '../payroll/EmployeeSalaryStructure';

/**
 * HRMS ▸ employee profile — the Employee Master record (Phase 1 FRD §3-4).
 *
 * One tab per FRD §3 section. Salary appears only when the server included it — the field
 * is absent from the payload without `employee.salary.read`, and bank / identity numbers
 * come back masked ("XXXX1234"), so an unauthorised viewer cannot recover either from the DOM.
 *
 * The login identity (email, mobile) stays READ-ONLY here: it is owned by the ERP user
 * record and edited in User Management. The name parts on the Personal tab are the HR
 * record's own copy, used on letters and payslips.
 *
 * Save sends ONLY the fields that changed. Organisation / reporting / pay-linkage fields are
 * effective-dated: changing one reveals an "Effective from" date and a reason, and a future
 * date SCHEDULES the change rather than applying it (it then shows in the banner and on the
 * History tab until the day arrives).
 */

const TABS = [
  { key: 'job', label: 'Job & Organisation' },
  { key: 'personal', label: 'Personal' },
  { key: 'contact', label: 'Contact & Address' },
  { key: 'reporting', label: 'Reporting' },
  { key: 'work', label: 'Work Setup' },
  { key: 'statutory', label: 'Statutory & Bank' },
  // What payroll pays from — the same panel as Payroll ▸ Salary Structure.
  { key: 'salary', label: 'Salary', cap: 'salary_structure.read' },
  // Phase 11-R, Item 2 — one of the shared DocumentPanel's two mount points.
  { key: 'documents', label: 'Documents' },
  // §22.1 — Group Mediclaim Policy: dependants, coverage and enrolment, restricted to HR
  // write with employee-self read (see GmpPanel).
  { key: 'gmp', label: 'GMP' },
  // FRD §21-22 — fields HR configured under Employee Master Setup.
  { key: 'custom', label: 'Additional fields' },
  { key: 'history', label: 'History', cap: CAP.EMPLOYEE_READ },
];

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] disabled:opacity-60';
const TEXTAREA = 'w-full min-h-[72px] px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] disabled:opacity-60';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';
const HINT = 'mt-1 text-[11px] text-[var(--text-muted)]';

// Every flat (string / date / number) field the form edits. Addresses, the weekly-off
// pattern and custom fields are structured and handled separately in toForm().
const SCALAR_FIELDS = [
  'employee_code', 'employment_status', 'employment_type', 'employee_category',
  'joined_on', 'resigned_on', 'probation_start', 'probation_end', 'confirmation_date',
  'legal_entity', 'business_unit', 'work_location', 'department_id', 'sub_department',
  'designation_id', 'grade', 'level', 'job_title', 'cost_centre', 'base_salary',
  'first_name', 'middle_name', 'last_name', 'display_name', 'gender', 'date_of_birth',
  'marital_status', 'blood_group', 'nationality',
  'personal_mobile', 'official_mobile', 'personal_email', 'official_email',
  'emergency_contact_name', 'emergency_contact_relation', 'emergency_contact_phone',
  'emergency_contact_alt_phone',
  'reporting_manager_id', 'functional_manager_id',
  'shift_code', 'attendance_policy_group', 'holiday_calendar',
  'pan', 'aadhaar', 'uan', 'pf_number', 'esi_number', 'passport', 'driving_license',
  'bank_name', 'bank_branch', 'bank_account_holder', 'bank_account', 'bank_account_type',
  'bank_ifsc', 'bank_effective_from',
  'payroll_group', 'salary_template',
];

// Mirrors EMPLOYEE_TRACKED_FIELDS in models/hrms.py: changing any of these is effective-dated.
const TRACKED_FIELDS = new Set([
  'department_id', 'designation_id', 'sub_department', 'grade', 'level', 'job_title',
  'legal_entity', 'business_unit', 'work_location', 'cost_centre', 'employee_category',
  'employment_type', 'employment_status', 'reporting_manager_id', 'functional_manager_id',
  'payroll_group', 'salary_template', 'shift_code', 'attendance_policy_group',
  'weekly_off_pattern', 'holiday_calendar', 'base_salary',
  'bank_name', 'bank_account', 'bank_ifsc', 'bank_branch', 'bank_account_holder',
  'bank_account_type',
]);

// Values that identify one person (EMPLOYEE_DUPLICATE_FIELDS) — checked on blur.
const DUPLICATE_FIELDS = ['pan', 'aadhaar', 'uan', 'passport', 'personal_email', 'official_email',
  'personal_mobile', 'bank_account'];

// A value the server masked for this viewer. Sending it back is harmless (the server treats
// it as unchanged) but it is never sent unless the user actually typed over it.
const MASKED = /^XXXX/;

// Field -> its company list (MASTER_LIST_FIELDS). Empty list = not configured = free text.
const LIST_FOR = {
  legal_entity: 'legal_entities', business_unit: 'business_units', work_location: 'locations',
  sub_department: 'sub_departments', grade: 'grades', level: 'levels', cost_centre: 'cost_centres',
  employee_category: 'employee_categories', payroll_group: 'payroll_groups',
  salary_template: 'salary_templates', attendance_policy_group: 'attendance_policy_groups',
  holiday_calendar: 'holiday_calendars', shift_code: 'shifts',
};

const ADDRESS_FIELDS = [
  ['line1', 'Address line 1'], ['line2', 'Address line 2'], ['city', 'City'],
  ['district', 'District'], ['state', 'State'], ['pin_code', 'PIN code'], ['country', 'Country'],
];

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const SATURDAY_MODES = [
  ['none', 'No Saturdays off', []],
  ['all', 'Every Saturday', ['Saturday']],
  ['2_4', '2nd & 4th Saturday', ['Saturday#2', 'Saturday#4']],
  ['1_3', '1st & 3rd Saturday', ['Saturday#1', 'Saturday#3']],
];
const ORDINAL = { 1: '1st', 2: '2nd', 3: '3rd', 4: '4th', 5: '5th' };

const STATUSES = ['Active', 'On Notice', 'Resigned', 'Terminated', 'On Long Leave'];
const EMPLOYMENT_TYPES = ['Full-time', 'Part-time', 'Contract', 'Intern', 'Consultant'];
const MARITAL_STATUSES = ['Single', 'Married', 'Divorced', 'Widowed', 'Separated'];
const ACCOUNT_TYPES = ['Savings', 'Current', 'Salary', 'NRE', 'NRO'];

const HISTORY_TONE = {
  Applied: 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]',
  Scheduled: 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]',
  Cancelled: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
};

const todayIso = () => new Date().toLocaleDateString('en-CA');   // YYYY-MM-DD, local

// Same order as the server's _validate_pattern, so an untouched pattern never reads as changed.
const sortPattern = (list) => [...new Set(list)].sort((a, b) =>
  (WEEKDAYS.indexOf(a.split('#')[0]) - WEEKDAYS.indexOf(b.split('#')[0])) || (a < b ? -1 : a > b ? 1 : 0));

const fmtOff = (entry) => {
  const [day, nth] = String(entry).split('#');
  return nth ? `${ORDINAL[nth] || nth} ${day}` : day;
};

const fmtDateTime = (value) => {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value)
    : d.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
};

const inr = (n) =>
  typeof n === 'number' ? `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—';

const blankAddress = (a) => Object.fromEntries(ADDRESS_FIELDS.map(([k]) => [k, a?.[k] ?? '']));

const toForm = (data) => {
  const f = {};
  SCALAR_FIELDS.forEach((k) => { f[k] = data[k] ?? ''; });
  f.employment_status = data.employment_status || 'Active';
  f.employment_type = data.employment_type || 'Full-time';
  f.current_address = blankAddress(data.current_address);
  f.permanent_address = blankAddress(data.permanent_address);
  f.permanent_same_as_current = !!data.permanent_same_as_current;
  f.weekly_off_pattern = Array.isArray(data.weekly_off_pattern) ? data.weekly_off_pattern : [];
  f.custom_fields = { ...(data.custom_fields || {}) };
  return f;
};

// Form value -> what the API expects. '' means "cleared", sent as null.
const toPayloadValue = (key, value) => {
  if (key === 'current_address' || key === 'permanent_address') {
    return Object.values(value).some((v) => String(v).trim()) ? value : null;
  }
  if (key === 'base_salary') return value === '' ? null : Number(value);
  if (Array.isArray(value) || typeof value === 'boolean' || key === 'custom_fields') return value;
  return value === '' ? null : value;
};

const isEmpty = (v) => v == null || v === '' || (Array.isArray(v) && v.length === 0);

// Configurable-field rules, as the server applies them: in force today, and every
// non-empty applicability list contains this record's value.
const inForce = (d, today) =>
  (!d.effective_from || d.effective_from <= today) && (!d.effective_to || d.effective_to >= today);
const appliesTo = (d, record) => Object.entries(d.applicability || {})
  .every(([field, allowed]) => !allowed?.length || allowed.includes(record[field]));

const Row = ({ children }) => (
  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">{children}</div>
);

const Section = ({ title, hint, children }) => (
  <section className="space-y-3">
    <div>
      <h3 className="text-[13px] font-bold text-[var(--text-main)]">{title}</h3>
      {hint && <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">{hint}</p>}
    </div>
    {children}
  </section>
);

const ReadOnly = ({ label, value }) => (
  <div>
    <span className={LABEL}>{label}</span>
    <p className="text-[13.5px] font-semibold text-[var(--text-main)] break-words">{value || '—'}</p>
  </div>
);

const TextField = ({ id, label, hint, type = 'text', ...input }) => (
  <div>
    <label className={LABEL} htmlFor={id}>{label}</label>
    <input id={id} type={type} className={FIELD} {...input} />
    {hint && <p className={HINT}>{hint}</p>}
  </div>
);

const SelectField = ({ id, label, options, blank = '—', hint, ...input }) => (
  <div>
    <label className={LABEL} htmlFor={id}>{label}</label>
    <select id={id} className={FIELD} {...input}>
      {blank != null && <option value="">{blank}</option>}
      {options.map((o) => {
        const [value, text] = Array.isArray(o) ? o : [o, o];
        return <option key={value} value={value}>{text}</option>;
      })}
    </select>
    {hint && <p className={HINT}>{hint}</p>}
  </div>
);

/** A field backed by a company list: a dropdown once HR configured the list, free text until then. */
const ListField = ({ id, label, values, value, ...input }) => (
  values?.length ? (
    <SelectField id={id} label={label} value={value} {...input}
      options={value && !values.includes(value) ? [...values, [value, `${value} (not in list)`]] : values} />
  ) : (
    <TextField id={id} label={label} value={value} placeholder="No list configured — free text" {...input} />
  )
);

const AddressFields = ({ prefix, value, onChange, disabled }) => (
  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
    {ADDRESS_FIELDS.map(([k, text]) => (
      <div key={k} className={k === 'line1' || k === 'line2' ? 'sm:col-span-2' : ''}>
        <label className={LABEL} htmlFor={`${prefix}-${k}`}>{text}</label>
        <input id={`${prefix}-${k}`} value={value[k]} disabled={disabled}
          onChange={(e) => onChange(k, e.target.value)} className={FIELD}
          inputMode={k === 'pin_code' ? 'numeric' : undefined} />
      </div>
    ))}
  </div>
);

/** Weekday checkboxes, with Saturday as a choice because it is usually "some Saturdays". */
const WeeklyOffEditor = ({ value, onChange, disabled }) => {
  const saturday = value.filter((v) => v.startsWith('Saturday'));
  const rest = value.filter((v) => !v.startsWith('Saturday'));
  const satKey = SATURDAY_MODES.find(([, , p]) =>
    JSON.stringify(sortPattern(p)) === JSON.stringify(sortPattern(saturday)))?.[0] || 'custom';

  const toggle = (day) =>
    onChange(sortPattern(rest.includes(day) ? value.filter((v) => v !== day) : [...value, day]));
  const setSaturday = (key) => {
    const mode = SATURDAY_MODES.find(([k]) => k === key);
    if (mode) onChange(sortPattern([...rest, ...mode[2]]));
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {WEEKDAYS.filter((d) => d !== 'Saturday').map((d) => (
          <label key={d}
            className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]">
            <input type="checkbox" checked={rest.includes(d)} onChange={() => toggle(d)} disabled={disabled} />
            {d.slice(0, 3)}
          </label>
        ))}
      </div>
      <div className="max-w-xs">
        <label className={LABEL} htmlFor="p-sat">Saturday</label>
        <select id="p-sat" value={satKey} onChange={(e) => setSaturday(e.target.value)} disabled={disabled} className={FIELD}>
          {SATURDAY_MODES.map(([k, text]) => <option key={k} value={k}>{text}</option>)}
          {satKey === 'custom' && <option value="custom">Custom: {saturday.map(fmtOff).join(', ')}</option>}
        </select>
      </div>
      <p className="text-[11.5px] text-[var(--text-muted)]">
        Weekly off: <b className="text-[var(--text-main)]">{value.length ? value.map(fmtOff).join(', ') : 'none set'}</b>
      </p>
    </div>
  );
};

/**
 * One input for one configurable field (FRD §22), chosen by its data type. Exported so the
 * Add Employee dialog renders mandatory fields exactly as the profile does.
 */
export const CustomFieldInput = ({ def, id, value, onChange, disabled, people = [], lists = {} }) => {
  const options = (def.options || []).filter((o) => o.active !== false || o.value === value
    || (Array.isArray(value) && value.includes(o.value)));
  const common = { id, disabled, className: FIELD, placeholder: def.default_value || undefined };

  switch (def.data_type) {
    case 'long_text':
      return <textarea {...common} className={TEXTAREA} value={value ?? ''}
        maxLength={def.max_length || undefined} onChange={(e) => onChange(e.target.value)} />;
    case 'number':
    case 'decimal':
    case 'currency':
      return <input {...common} type="number" step={def.data_type === 'number' ? 1 : 0.01}
        min={def.min_value ?? undefined} max={def.max_value ?? undefined}
        value={value ?? ''} onChange={(e) => onChange(e.target.value)} />;
    case 'date':
      return <input {...common} type="date" min={def.min_date || undefined} max={def.max_date || undefined}
        value={value ?? ''} onChange={(e) => onChange(e.target.value)} />;
    case 'datetime':
      return <input {...common} type="datetime-local" value={value ?? ''} onChange={(e) => onChange(e.target.value)} />;
    case 'boolean':
      return (
        <label className="inline-flex items-center gap-2 h-9 text-[13px] text-[var(--text-main)]">
          <input id={id} type="checkbox" disabled={disabled}
            checked={value === true || value === 'true'} onChange={(e) => onChange(e.target.checked)} />
          Yes
        </label>
      );
    case 'single_select':
      return (
        <select {...common} value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
          <option value="">—</option>
          {options.map((o) => <option key={o.value} value={o.value}>{o.label || o.value}</option>)}
        </select>
      );
    case 'multi_select': {
      const chosen = Array.isArray(value) ? value : (value ? [value] : []);
      return (
        <div id={id} className="flex flex-wrap gap-2">
          {options.map((o) => (
            <label key={o.value}
              className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] text-[var(--text-main)]">
              <input type="checkbox" disabled={disabled} checked={chosen.includes(o.value)}
                onChange={(e) => onChange(e.target.checked
                  ? [...chosen, o.value] : chosen.filter((v) => v !== o.value))} />
              {o.label || o.value}
            </label>
          ))}
        </div>
      );
    }
    case 'master_lookup': {
      const values = lists[def.master_list] || [];
      return values.length ? (
        <select {...common} value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
          <option value="">—</option>
          {(value && !values.includes(value) ? [...values, value] : values)
            .map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      ) : <input {...common} value={value ?? ''} onChange={(e) => onChange(e.target.value)} />;
    }
    case 'employee_lookup':
      return (
        <select {...common} value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
          <option value="">—</option>
          {value && !people.some((p) => p.user_id === value) && <option value={value}>{value}</option>}
          {people.map((p) => (
            <option key={p.user_id} value={p.user_id}>
              {p.name}{p.employee_code ? ` (${p.employee_code})` : ''}
            </option>
          ))}
        </select>
      );
    case 'document':
      return <input {...common} value={value ?? ''} placeholder="Document reference or link"
        onChange={(e) => onChange(e.target.value)} />;
    default:
      return <input {...common} value={value ?? ''} maxLength={def.max_length || undefined}
        onChange={(e) => onChange(e.target.value)} />;
  }
};

const EmployeeProfile = () => {
  const { userId } = useParams();
  const navigate = useNavigate();
  const { can, scope } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [employee, setEmployee] = useState(null);
  // FRD §3 Basic Identity: the employee's own photograph, shown through a short-lived
  // signed URL (never stored). §3 lists "Photograph" TWICE — once as an identity attribute
  // and once as a verifiable document — so there are two sources, tried in that order:
  // the profile field, then the latest approved "Photograph" document. The document scan
  // is the fallback rather than the primary because it needs document-read rights, and a
  // manager who may see the person may not see their papers.
  const [photoUrl, setPhotoUrl] = useState(null);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [form, setForm] = useState({});
  // What the server last returned, as a form — the diff against it is what Save sends.
  const [baseline, setBaseline] = useState({});
  const [departments, setDepartments] = useState([]);
  const [designations, setDesignations] = useState([]);
  const [people, setPeople] = useState([]);
  const [lists, setLists] = useState({});
  const [defs, setDefs] = useState([]);
  const [hierarchy, setHierarchy] = useState(null);
  const [history, setHistory] = useState(null);
  const [effective, setEffective] = useState({ from: todayIso(), reason: '' });
  const [duplicates, setDuplicates] = useState([]);
  const [tab, setTab] = useState('job');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [appointmentLetter, setAppointmentLetter] = useState(undefined); // undefined = not checked yet
  const [showLetter, setShowLetter] = useState(false);

  const canWrite = can(CAP.EMPLOYEE_WRITE);
  const canRead = can(CAP.EMPLOYEE_READ);
  const canSeeSalary = employee && 'base_salary' in employee;
  const canSetSalary = can(CAP.EMPLOYEE_SALARY_WRITE);
  const canSeeAppointment = can(CAP.APPOINTMENT_READ);

  const applyEmployee = (data) => {
    const next = toForm(data);
    setEmployee(data);
    setForm(next);
    setBaseline(next);
    setDuplicates([]);
    setEffective({ from: todayIso(), reason: '' });
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await getEmployee(userId, scope);
      applyEmployee(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this employee.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const employeeCode = employee?.employee_code;
  const loadPhoto = useCallback(async () => {
    setPhotoUrl(null);
    if (!userId || !scope.company_id) return;
    try {
      const { data: link } = await getEmployeePhotographUrl(userId, scope);
      if (link?.url) { setPhotoUrl(link.url); return; }
    } catch {
      // No photograph on the profile — fall through to the document store below.
    }
    if (!employeeCode) return;
    try {
      const { data } = await getDocuments({ ...scope, owner_type: 'employee', owner_id: employeeCode });
      const rows = Array.isArray(data) ? data : (data?.documents || []);
      const photo = rows.find((d) => /photo/i.test(d.type_name || '') && d.status !== 'Rejected'
        && (d.latest_version || d.version_count));
      if (!photo) return;
      const { data: link } = await getDocumentUrl(photo.doc_no, scope);
      if (link?.url) setPhotoUrl(link.url);
    } catch {
      // No photograph, or no right to see documents: the plain icon stays.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, employeeCode, scope.company_id]);

  useEffect(() => { loadPhoto(); }, [loadPhoto]);

  /** Read the chosen file as base64 and store it on the profile. */
  const onPickPhoto = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';           // so picking the same file twice still fires
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      showError('The photograph must be 5 MB or smaller.');
      return;
    }
    setPhotoBusy(true);
    try {
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error('unreadable'));
        reader.onload = () => resolve(String(reader.result || '').split(',')[1] || '');
        reader.readAsDataURL(file);
      });
      await saveEmployeePhotograph(
        userId, { name: file.name, mime_type: file.type, data }, scope);
      await loadPhoto();
      await load();
      showSuccess('Photograph saved.');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the photograph.');
    } finally {
      setPhotoBusy(false);
    }
  };

  const onRemovePhoto = async () => {
    setPhotoBusy(true);
    try {
      await deleteEmployeePhotograph(userId, scope);
      await loadPhoto();
      await load();
      showSuccess('Photograph removed.');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not remove the photograph.');
    } finally {
      setPhotoBusy(false);
    }
  };

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    // Depend on the COMPANY ID specifically, not the whole `scope` object: on a cold page
    // load `companyId` resolves asynchronously (HrmsContext fetches it after mount), and an
    // empty-array effect fired before that captured `scope={}` forever, 400ing both calls
    // silently and leaving these dropdowns permanently empty. `company_id` is a stable
    // primitive, so this re-fires exactly once when it actually resolves, not on every render.
    if (!scope.company_id) return;
    getDepartments(scope).then(({ data }) => setDepartments(data?.departments || [])).catch(() => {});
    getDesignations(scope).then(({ data }) => setDesignations(data?.designations || [])).catch(() => {});
    // Company lists, people (manager pickers + name lookups) and configurable fields. All
    // optional: without them the form falls back to free text and raw values.
    getEmployeeMasterLists(scope).then(({ data }) => setLists(data || {})).catch(() => {});
    listFieldDefinitions({ ...scope, module: 'employee' })
      .then(({ data }) => setDefs(Array.isArray(data) ? data : [])).catch(() => {});
    if (canRead) {
      getEmployees({ ...scope, limit: 500 })
        .then(({ data }) => setPeople((data?.employees || []).filter((p) => p.user_id)))
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.company_id, canRead]);

  useEffect(() => {
    if (tab !== 'reporting' || hierarchy) return;
    getEmployeeHierarchy(userId, scope)
      .then(({ data }) => setHierarchy(data))
      .catch((err) => showError(err?.response?.data?.detail || 'Could not load the reporting chain.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, hierarchy]);

  useEffect(() => {
    if (tab !== 'history' || history) return;
    getEmployeeHistory(userId, scope)
      .then(({ data }) => setHistory(data?.history || []))
      .catch((err) => {
        setHistory([]);
        showError(err?.response?.data?.detail || 'Could not load the change history.');
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, history]);

  // BR-028 — the Appointment Letter, if one was ever raised for this person, downloadable
  // from their profile. `uk` narrows the company-wide list to this one employee; an
  // EMPLOYEE-role viewer is additionally self-scoped server-side, so this same call is safe
  // whether HR opened someone else's profile or the employee opened their own.
  useEffect(() => {
    if (!canSeeAppointment || !employee?.source_uk) { setAppointmentLetter(null); return; }
    getAppointments({ ...scope, uk: employee.source_uk })
      .then(({ data }) => setAppointmentLetter(data?.appointments?.[0] || null))
      .catch(() => setAppointmentLetter(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employee?.source_uk, canSeeAppointment]);

  const today = todayIso();
  const personById = useMemo(() => Object.fromEntries(people.map((p) => [p.user_id, p])), [people]);

  // Keys whose value differs from what the server returned. base_salary only counts when
  // this viewer may set it — otherwise it is never sent.
  const changedKeys = useMemo(() => Object.keys(form).filter((k) =>
    (k !== 'base_salary' || canSetSalary)
    && JSON.stringify(form[k]) !== JSON.stringify(baseline[k])), [form, baseline, canSetSalary]);
  const trackedChanged = employee?.has_profile && changedKeys.some((k) => TRACKED_FIELDS.has(k));

  // Active configurable fields that apply to this person today, grouped by section.
  const customDefs = useMemo(() => defs
    .filter((d) => d.status === 'Active' && inForce(d, today) && appliesTo(d, form)
      // Without write, show only what the server let this viewer see.
      && (canWrite || (employee?.custom_fields && d.code in employee.custom_fields)))
    .sort((a, b) => (a.display_order ?? 100) - (b.display_order ?? 100)),
  [defs, form, today, canWrite, employee]);
  const customSections = useMemo(() => {
    const groups = new Map();
    customDefs.forEach((d) => {
      const key = d.section || 'General';
      groups.set(key, [...(groups.get(key) || []), d]);
    });
    return [...groups.entries()];
  }, [customDefs]);
  const retiredWithValues = defs.filter((d) => d.status === 'Retired'
    && !isEmpty(employee?.custom_fields?.[d.code]));

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const bind = (key) => ({ value: form[key] ?? '', onChange: set(key), disabled: !canWrite });
  const bindList = (key) => ({ ...bind(key), values: lists[LIST_FOR[key]] });

  const setAddress = (which, key, value) => setForm((f) => {
    const next = { ...f, [which]: { ...f[which], [key]: value } };
    if (which === 'current_address' && f.permanent_same_as_current) {
      next.permanent_address = { ...next.current_address };
    }
    return next;
  });
  const setSameAsCurrent = (checked) => setForm((f) => ({
    ...f,
    permanent_same_as_current: checked,
    permanent_address: checked ? { ...f.current_address } : f.permanent_address,
  }));
  const setCustom = (code, value) =>
    setForm((f) => ({ ...f, custom_fields: { ...f.custom_fields, [code]: value } }));

  // Resolve a raw history / scheduled value (ids, patterns) to something a person can read.
  const describe = (field, value) => {
    if (isEmpty(value)) return '—';
    if (field === 'department_id') return departments.find((d) => d.id === value)?.name || value;
    if (field === 'designation_id') return designations.find((d) => d.id === value)?.name || value;
    if (field === 'reporting_manager_id' || field === 'functional_manager_id') {
      const p = personById[value];
      return p ? `${p.name}${p.employee_code ? ` (${p.employee_code})` : ''}` : value;
    }
    if (field === 'weekly_off_pattern' && Array.isArray(value)) return value.map(fmtOff).join(', ');
    if (field === 'base_salary' && typeof value === 'number') return inr(value);
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (Array.isArray(value)) return value.join(', ');
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  };

  /** FRD §4 — advisory only: warn before saving; the server re-checks and refuses with a 409. */
  const checkDuplicates = async () => {
    if (!canWrite || !employee) return;
    const values = {};
    DUPLICATE_FIELDS.forEach((k) => {
      const v = String(form[k] ?? '').trim();
      if (v && !MASKED.test(v) && (!employee.has_profile || v !== String(baseline[k] ?? ''))) values[k] = v;
    });
    if (!Object.keys(values).length) { setDuplicates([]); return; }
    try {
      const { data } = await checkEmployeeDuplicates({ ...values, exclude_user_id: userId }, scope);
      setDuplicates(data?.duplicates || []);
    } catch {
      // A failed pre-check is not worth interrupting anyone for.
    }
  };

  const missingMandatory = () => customDefs.find((d) => d.mandatory
    && isEmpty(form.custom_fields?.[d.code]) && isEmpty(d.default_value));

  const save = async () => {
    const creating = !employee.has_profile;
    const customChanged = changedKeys.includes('custom_fields');
    if ((creating || customChanged) && missingMandatory()) {
      setTab('custom');
      showError(`${missingMandatory().label} is required.`);
      return;
    }
    setSaving(true);
    try {
      // No profile yet → this Save CREATES one (the banner above promises exactly that).
      // PATCH only updates an existing profile, so it answered "Employee not found".
      // Blank fields are left out of a create rather than sent as null, so the server's
      // defaults (Active, Full-time, an auto-issued employee code) apply.
      let data;
      if (!creating) {
        const payload = {};
        changedKeys.forEach((k) => { payload[k] = toPayloadValue(k, form[k]); });
        if (trackedChanged) {
          payload.effective_from = effective.from || today;
          if (effective.reason.trim()) payload.change_reason = effective.reason.trim();
        }
        ({ data } = await updateEmployee(userId, payload, scope));
      } else {
        const fresh = {};
        Object.entries(form).forEach(([k, v]) => {
          if (k === 'base_salary' && !canSetSalary) return;
          const value = toPayloadValue(k, v);
          if (isEmpty(value) || value === false) return;
          if (k === 'custom_fields' && !Object.values(value).some((x) => !isEmpty(x))) return;
          fresh[k] = value;
        });
        await createEmployee({ ...fresh, user_id: userId }, scope);
        ({ data } = await getEmployee(userId, scope));
      }
      const scheduledNow = !creating && trackedChanged && effective.from > today;
      applyEmployee(data);
      setHistory(null);
      setHierarchy(null);
      showSuccess(creating ? `Profile created — employee code ${data.employee_code}`
        : scheduledNow ? `Saved — organisation changes scheduled from ${effective.from}`
        : 'Profile saved');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the profile.');
    } finally {
      setSaving(false);
    }
  };

  const cancelScheduled = async (row) => {
    if (!window.confirm(`Cancel the scheduled change to ${row.label} from ${row.effective_from}?`)) return;
    try {
      await cancelScheduledEmployeeChange(row.id, scope);
      showSuccess('Scheduled change cancelled');
      setHistory((h) => (h || []).map((r) => (r.id === row.id ? { ...r, status: 'Cancelled' } : r)));
      setEmployee((e) => ({
        ...e, scheduled_changes: (e.scheduled_changes || []).filter((c) => c.id !== row.id),
      }));
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not cancel the change.');
    }
  };

  if (loading) return <HrmsLoading label="Loading employee…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;
  if (!employee) return null;

  const nothingToSave = employee.has_profile && changedKeys.length === 0;
  const personOptions = (current, currentName) => [
    ...(current && !personById[current] ? [[current, currentName || current]] : []),
    ...people.filter((p) => p.user_id !== userId)
      .map((p) => [p.user_id, `${p.name}${p.employee_code ? ` (${p.employee_code})` : ''}`]),
  ];
  const codeOf = (id, fallback) => personById[id]?.employee_code || fallback;
  const nameOf = (id) => personById[id]?.name;
  const maskedHint = (key) => (MASKED.test(String(form[key] || ''))
    ? 'Masked for you. Type a full new value to replace it.' : undefined);

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={UserCircle}
        avatarUrl={photoUrl}
        title={employee.name}
        subtitle={[employee.designation || employee.legacy_designation,
                   employee.department || employee.legacy_department]
                   .filter(Boolean).join(' · ') || employee.email}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {canWrite && (
              <>
                <label className="h-9 px-3.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)] flex items-center gap-1.5 cursor-pointer"
                  title="JPEG, PNG or WebP, up to 5 MB">
                  <Camera size={14} /> {photoBusy ? 'Working…' : (photoUrl ? 'Change photo' : 'Add photo')}
                  <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only"
                    disabled={photoBusy} onChange={onPickPhoto} />
                </label>
                {employee.photograph && (
                  <button type="button" onClick={onRemovePhoto} disabled={photoBusy}
                    className="h-9 px-3.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)] flex items-center gap-1.5">
                    <Trash2 size={14} /> Remove photo
                  </button>
                )}
              </>
            )}
            <button type="button" onClick={() => navigate('/hrms/employees')}
              className="h-9 px-3.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)] flex items-center gap-1.5">
              <ArrowLeft size={14} /> Directory
            </button>
            <button type="button" onClick={() => navigate(`/hrms/employees/${userId}/360`)}
              className="h-9 px-3.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)] flex items-center gap-1.5">
              <LayoutGrid size={14} /> 360° View
            </button>
            {canWrite && (
              <button type="button" onClick={save} disabled={saving || nothingToSave}
                title={nothingToSave ? 'Nothing has changed' : undefined}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5 disabled:opacity-50">
                <Save size={14} /> {saving ? 'Saving…'
                  : employee.has_profile && changedKeys.length ? `Save (${changedKeys.length})` : 'Save'}
              </button>
            )}
          </div>
        }
      />

      {!employee.has_profile && (
        <div className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] text-[var(--text-muted)]">
          This person has no HR profile yet. Fill in the details below and save to create one.
        </div>
      )}

      {employee.scheduled_changes?.length > 0 && (
        <div className="p-3.5 rounded-xl border border-[var(--accent-orange)]/30 bg-[var(--accent-orange-bg)] space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="flex items-center gap-2 text-[12.5px] font-bold text-[var(--accent-orange)]">
              <CalendarClock size={15} /> Scheduled changes
            </p>
            <button type="button" onClick={() => setTab('history')}
              className="text-[11.5px] font-bold text-[var(--accent-indigo)] hover:underline">
              View history
            </button>
          </div>
          <ul className="space-y-1">
            {employee.scheduled_changes.map((c) => (
              <li key={c.id} className="text-[12.5px] text-[var(--text-main)]">
                <b>{c.label}</b> → {describe(c.field, c.new_value)}
                <span className="text-[var(--text-muted)]"> from {c.effective_from}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {canWrite && trackedChanged && (
        <div className="p-3.5 rounded-xl border border-[var(--accent-indigo)]/30 bg-[var(--accent-indigo-bg)] space-y-3">
          <p className="text-[12px] text-[var(--text-main)]">
            You changed organisation, reporting, work-setup or pay details. They take effect from
            the date below — a <b>future</b> date schedules the change instead of applying it now.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-[200px_1fr] gap-3">
            <TextField id="p-eff-from" label="Effective from" type="date" value={effective.from}
              onChange={(e) => setEffective((s) => ({ ...s, from: e.target.value }))} />
            <TextField id="p-eff-reason" label="Reason for change" value={effective.reason}
              placeholder="e.g. Transfer to Pune office"
              onChange={(e) => setEffective((s) => ({ ...s, reason: e.target.value }))} />
          </div>
        </div>
      )}

      {duplicates.length > 0 && (
        <div className="p-3.5 rounded-xl border border-[var(--accent-red)]/30 bg-[var(--accent-red-bg)] space-y-1.5">
          <p className="flex items-center gap-2 text-[12.5px] font-bold text-[var(--accent-red)]">
            <AlertTriangle size={15} /> Possible duplicate employee
          </p>
          {duplicates.map((d) => (
            <p key={`${d.field}-${d.employee_code}`} className="text-[12.5px] text-[var(--text-main)]">
              {d.label} is already recorded for <b>{d.employee_code}</b>{d.name ? ` (${d.name})` : ''}.
            </p>
          ))}
          <p className="text-[11.5px] text-[var(--text-muted)]">
            Check this is not the same person. The save will be refused while the clash remains.
          </p>
        </div>
      )}

      <div className="flex gap-1 border-b border-[var(--border)] overflow-x-auto">
        {TABS.filter((t) => !t.cap || can(t.cap)).map((t) => (
          <button
            key={t.key} type="button" onClick={() => setTab(t.key)}
            className={`px-3.5 py-2 text-[12.5px] font-bold whitespace-nowrap border-b-2 -mb-px transition-colors ${
              tab === t.key
                ? 'border-[var(--accent-indigo)] text-[var(--accent-indigo)]'
                : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-main)]'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'job' && (
        <div className="space-y-6">
          <Section title="Employment">
            <Row>
              <TextField id="p-code" label="Employee code" {...bind('employee_code')} />
              <SelectField id="p-status" label="Status" options={STATUSES} blank={null} {...bind('employment_status')} />
              <SelectField id="p-type" label="Employment type" options={EMPLOYMENT_TYPES} blank={null} {...bind('employment_type')} />
              <ListField id="p-category" label="Employee category" {...bindList('employee_category')} />
              <TextField id="p-joined" label="Joining date" type="date" {...bind('joined_on')} />
              <TextField id="p-resigned" label="Resignation date" type="date" {...bind('resigned_on')} />
              <TextField id="p-prob-start" label="Probation start" type="date" {...bind('probation_start')} />
              <TextField id="p-prob-end" label="Probation end" type="date" {...bind('probation_end')} />
              <TextField id="p-confirm" label="Confirmation date" type="date" {...bind('confirmation_date')} />
              {canSeeSalary && (
                <div>
                  <label className={LABEL} htmlFor="p-salary">Base salary (monthly)</label>
                  <input id="p-salary" type="number" min="0" value={form.base_salary}
                    onChange={set('base_salary')} disabled={!canSetSalary} className={FIELD} />
                  {!canSetSalary && <p className={HINT}>You can view but not change salary.</p>}
                  <p className={HINT}>
                    For reference only — payroll does not use this. Set what they are paid in the{' '}
                    <button type="button" onClick={() => setTab('salary')}
                      className="font-bold text-[var(--accent-indigo)] hover:underline">Salary tab</button>.
                  </p>
                </div>
              )}
            </Row>
          </Section>

          <Section title="Organisation"
            hint="Dropdowns come from Employee Master Setup; a list nobody has configured yet accepts free text.">
            <Row>
              <ListField id="p-entity" label="Company / legal entity" {...bindList('legal_entity')} />
              <ListField id="p-unit" label="Business unit / branch" {...bindList('business_unit')} />
              <ListField id="p-location" label="Location" {...bindList('work_location')} />
              <SelectField id="p-dept" label="Department" {...bind('department_id')}
                options={departments.map((d) => [d.id, d.name])} />
              <ListField id="p-subdept" label="Sub-department" {...bindList('sub_department')} />
              <SelectField id="p-desig" label="Designation" {...bind('designation_id')}
                options={designations.map((d) => [d.id, d.name])} />
              <ListField id="p-grade" label="Grade" {...bindList('grade')} />
              <ListField id="p-level" label="Level" {...bindList('level')} />
              <TextField id="p-title" label="Job title" {...bind('job_title')} />
              <ListField id="p-cc" label="Cost centre" {...bindList('cost_centre')} />
            </Row>
          </Section>

          {/* BR-028 — downloadable Appointment Letter, surfaced from the employee's own
              profile rather than only the HR-side Appointments board. */}
          {appointmentLetter && (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-3.5">
              <div className="flex items-center gap-2.5 min-w-0">
                <FileText size={16} className="text-[var(--accent-indigo)] shrink-0" />
                <div className="min-w-0">
                  <p className="text-[12.5px] font-semibold text-[var(--text-main)] truncate">
                    Appointment Letter — {appointmentLetter.appointment_no}
                  </p>
                  <p className="text-[11px] text-[var(--text-muted)]">{appointmentLetter.status}</p>
                </div>
              </div>
              <button type="button" onClick={() => setShowLetter(true)}
                className="h-8 px-3 shrink-0 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-main)]">
                View / Print
              </button>
            </div>
          )}
        </div>
      )}

      {tab === 'personal' && (
        <Row>
          <TextField id="p-first" label="First name" {...bind('first_name')} />
          <TextField id="p-middle" label="Middle name" {...bind('middle_name')} />
          <TextField id="p-last" label="Last name" {...bind('last_name')} />
          <TextField id="p-display" label="Display name" {...bind('display_name')}
            hint="Shown across HRMS instead of the login name when set." />
          <SelectField id="p-gender" label="Gender" options={['Male', 'Female', 'Other']} {...bind('gender')} />
          <TextField id="p-dob" label="Date of birth" type="date" {...bind('date_of_birth')} />
          <SelectField id="p-marital" label="Marital status" options={MARITAL_STATUSES} {...bind('marital_status')} />
          <TextField id="p-blood" label="Blood group" placeholder="e.g. O+" {...bind('blood_group')} />
          <TextField id="p-nation" label="Nationality" placeholder="e.g. Indian" {...bind('nationality')} />
        </Row>
      )}

      {tab === 'contact' && (
        <div className="space-y-6">
          <Section title="Contact">
            <Row>
              <ReadOnly label="Login email" value={employee.email} />
              <ReadOnly label="Login mobile" value={employee.mobile} />
              <TextField id="p-pmob" label="Personal mobile" type="tel" {...bind('personal_mobile')} onBlur={checkDuplicates} />
              <TextField id="p-omob" label="Official mobile" type="tel" {...bind('official_mobile')} />
              <TextField id="p-pemail" label="Personal email" type="email" {...bind('personal_email')} onBlur={checkDuplicates} />
              <TextField id="p-oemail" label="Official email" type="email" {...bind('official_email')} onBlur={checkDuplicates} />
            </Row>
          </Section>

          <Section title="Current address">
            {employee.address && !Object.values(form.current_address).some(Boolean) && (
              <p className="text-[11.5px] text-[var(--text-muted)]">
                Previously recorded as a single line: <b className="text-[var(--text-main)]">{employee.address}</b>
              </p>
            )}
            <AddressFields prefix="p-cur" value={form.current_address} disabled={!canWrite}
              onChange={(k, v) => setAddress('current_address', k, v)} />
          </Section>

          <Section title="Permanent address">
            <label className="inline-flex items-center gap-2 text-[12.5px] font-semibold text-[var(--text-main)]">
              <input type="checkbox" checked={form.permanent_same_as_current} disabled={!canWrite}
                onChange={(e) => setSameAsCurrent(e.target.checked)} />
              Same as current address
            </label>
            <AddressFields prefix="p-perm" value={form.permanent_address}
              disabled={!canWrite || form.permanent_same_as_current}
              onChange={(k, v) => setAddress('permanent_address', k, v)} />
          </Section>

          <Section title="Emergency contact">
            <Row>
              <TextField id="p-ecn" label="Name" {...bind('emergency_contact_name')} />
              <TextField id="p-ecr" label="Relationship" {...bind('emergency_contact_relation')} />
              <TextField id="p-ecp" label="Mobile" type="tel" {...bind('emergency_contact_phone')} />
              <TextField id="p-eca" label="Alternate number" type="tel" {...bind('emergency_contact_alt_phone')} />
            </Row>
          </Section>
        </div>
      )}

      {tab === 'work' && (
        <div className="space-y-6">
          <Row>
            <ListField id="p-shift" label="Shift" {...bindList('shift_code')} />
            <ListField id="p-attpol" label="Attendance policy group" {...bindList('attendance_policy_group')} />
            <ListField id="p-holcal" label="Holiday calendar" {...bindList('holiday_calendar')} />
          </Row>
          <p className="text-[11px] text-[var(--text-muted)] -mt-3">
            Shifts are managed under Attendance ▸ Shifts.
          </p>
          <Section title="Weekly off">
            <WeeklyOffEditor value={form.weekly_off_pattern} disabled={!canWrite}
              onChange={(v) => setForm((f) => ({ ...f, weekly_off_pattern: v }))} />
          </Section>
        </div>
      )}

      {tab === 'statutory' && (
        <div className="space-y-6">
          <Section title="Statutory & identity">
            <Row>
              <TextField id="p-pan" label="PAN" placeholder="ABCDE1234F" {...bind('pan')}
                onBlur={checkDuplicates} hint={maskedHint('pan')} />
              <TextField id="p-aadhaar" label="Aadhaar" placeholder="12 digits" {...bind('aadhaar')}
                onBlur={checkDuplicates} hint={maskedHint('aadhaar')} />
              <TextField id="p-uan" label="UAN" placeholder="12 digits" {...bind('uan')} onBlur={checkDuplicates} />
              <TextField id="p-pf" label="PF number" {...bind('pf_number')} />
              <TextField id="p-esi" label="ESI number" {...bind('esi_number')} />
              <TextField id="p-passport" label="Passport" {...bind('passport')}
                onBlur={checkDuplicates} hint={maskedHint('passport')} />
              <TextField id="p-dl" label="Driving licence" {...bind('driving_license')} />
            </Row>
          </Section>
          <Section title="Bank" hint="Bank changes are effective-dated, like organisation changes.">
            <Row>
              <TextField id="p-bank" label="Bank name" {...bind('bank_name')} />
              <TextField id="p-branch" label="Branch" {...bind('bank_branch')} />
              <TextField id="p-holder" label="Account holder" {...bind('bank_account_holder')} />
              <TextField id="p-acct" label="Account number" {...bind('bank_account')}
                onBlur={checkDuplicates} hint={maskedHint('bank_account')} />
              <SelectField id="p-acct-type" label="Account type" options={ACCOUNT_TYPES} {...bind('bank_account_type')} />
              <TextField id="p-ifsc" label="IFSC" placeholder="HDFC0001234" {...bind('bank_ifsc')} />
              <TextField id="p-bank-from" label="Bank details effective from" type="date" {...bind('bank_effective_from')} />
            </Row>
          </Section>
        </div>
      )}

      {/* ── Phase 11-R, Item 2 ── the SAME panel the candidate journey mounts. One
          component, two mount points: two near-identical panels would drift, and the one
          that drifts is the one showing a stale verification status.

          Keyed on `employee_code`, which is what hrms_documents stores as `owner_id` for an
          employee — not the user_id in the URL. */}
      {tab === 'documents' && (
        employee?.employee_code ? (
          <DocumentPanel
            ownerType="employee"
            ownerId={employee.employee_code}
            ownerName={employee.name}
          />
        ) : (
          <p className="text-[13px] text-[var(--text-muted)]">
            This employee has no employee code yet, so documents cannot be filed against
            them. One is issued when their onboarding completes.
          </p>
        )
      )}

      {tab === 'salary' && (
        <div className="space-y-6">
          {employee.salary_summary && (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
              <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-3">
                Current salary structure{employee.salary_summary.status ? ` · ${employee.salary_summary.status}` : ''}
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                <ReadOnly label="Annual CTC" value={inr(employee.salary_summary.annual_ctc)} />
                <ReadOnly label="Monthly gross" value={inr(employee.salary_summary.monthly_gross)} />
                <ReadOnly label="Payroll group" value={employee.salary_summary.payroll_group} />
                <ReadOnly label="Structure template" value={employee.salary_summary.structure_name} />
                <ReadOnly label="Effective from" value={employee.salary_summary.effective_from} />
              </div>
            </div>
          )}
          <Row>
            <ListField id="p-paygroup" label="Payroll group" {...bindList('payroll_group')} />
            <ListField id="p-saltpl" label="Salary structure template" {...bindList('salary_template')} />
          </Row>
          {employee?.employee_code ? (
            <EmployeeSalaryStructure employeeCode={employee.employee_code}
              employeeName={employee.name} employmentStatus={employee.employment_status} />
          ) : (
            <p className="text-[13px] text-[var(--text-muted)]">
              This person has no employee profile yet, so payroll cannot pay them. Fill in the
              Job tab and save to create one — then set their salary here.
            </p>
          )}
        </div>
      )}

      {tab === 'gmp' && (
        employee?.employee_code ? (
          <GmpPanel employeeCode={employee.employee_code} employeeName={employee.name} />
        ) : (
          <p className="text-[13px] text-[var(--text-muted)]">
            This employee has no employee code yet, so a GMP enrolment cannot be filed
            against them.
          </p>
        )
      )}

      {tab === 'custom' && (
        customSections.length === 0 && retiredWithValues.length === 0 ? (
          <HrmsEmpty title="No additional fields"
            hint={canWrite ? 'Add company-specific fields under Employee Master Setup ▸ Configurable fields.' : undefined} />
        ) : (
          <div className="space-y-6">
            {customSections.map(([section, rows]) => (
              <Section key={section} title={section}>
                <Row>
                  {rows.map((d) => {
                    const locked = d.read_only && !isEmpty(baseline.custom_fields?.[d.code]);
                    return (
                      <div key={d.code} className={d.data_type === 'long_text' || d.data_type === 'multi_select' ? 'sm:col-span-2' : ''}>
                        <label className={LABEL} htmlFor={`cf-${d.code}`}>
                          {d.label}{d.mandatory && <span className="text-[var(--accent-red)]"> *</span>}
                        </label>
                        <CustomFieldInput def={d} id={`cf-${d.code}`} value={form.custom_fields?.[d.code]}
                          onChange={(v) => setCustom(d.code, v)} disabled={!canWrite || locked}
                          people={people} lists={lists} />
                        {(d.help_text || locked) && (
                          <p className={HINT}>{[d.help_text, locked && 'Read-only once set.'].filter(Boolean).join(' ')}</p>
                        )}
                      </div>
                    );
                  })}
                </Row>
              </Section>
            ))}
            {retiredWithValues.length > 0 && (
              <Section title="Retired fields" hint="Kept for the record; no longer editable.">
                <Row>
                  {retiredWithValues.map((d) => (
                    <ReadOnly key={d.code} label={d.label} value={describe(d.code, employee.custom_fields[d.code])} />
                  ))}
                </Row>
              </Section>
            )}
          </div>
        )
      )}

      {tab === 'history' && (
        history === null ? (
          <HrmsLoading label="Loading change history…" />
        ) : history.length === 0 ? (
          <HrmsEmpty icon={CalendarClock} title="No recorded changes"
            hint="Organisation, reporting, work-setup and pay changes appear here with their effective dates." />
        ) : (
          <ol className="space-y-2">
            {history.map((h) => (
              <li key={h.id} className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`px-2 py-0.5 rounded-md text-[11px] font-bold ${HISTORY_TONE[h.status] || HISTORY_TONE.Cancelled}`}>
                      {h.status}
                    </span>
                    <span className="text-[13px] font-bold text-[var(--text-main)] truncate">{h.label}</span>
                  </div>
                  <span className="text-[11.5px] text-[var(--text-muted)]">effective {h.effective_from}</span>
                </div>
                <p className="mt-1.5 text-[12.5px] text-[var(--text-main)] break-words">
                  <span className="text-[var(--text-muted)]">{describe(h.field, h.old_value)}</span>
                  {' → '}
                  <b>{describe(h.field, h.new_value)}</b>
                </p>
                <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[11.5px] text-[var(--text-muted)]">
                    {[h.changed_by_name, fmtDateTime(h.changed_at)].filter(Boolean).join(' · ')}
                    {h.reason && <> · “{h.reason}”</>}
                  </p>
                  {h.status === 'Scheduled' && canWrite && (
                    <button type="button" onClick={() => cancelScheduled(h)}
                      className="h-7 px-2.5 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:border-[var(--accent-red)]">
                      Cancel change
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )
      )}

      {showLetter && appointmentLetter && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-start justify-center overflow-y-auto py-8 px-4">
          <div className="w-full max-w-3xl">
            <div className="flex justify-end mb-2 gap-2">
              <button type="button" onClick={() => window.print()}
                className="h-9 px-3.5 rounded-lg bg-white text-[12px] font-bold text-slate-900">
                Print / Save as PDF
              </button>
              <button type="button" onClick={() => setShowLetter(false)}
                className="h-9 w-9 rounded-lg bg-white text-slate-900 flex items-center justify-center">
                <X size={16} />
              </button>
            </div>
            <AppointmentPaper appointment={appointmentLetter} showAcknowledgement={false} />
          </div>
        </div>
      )}

      {tab === 'reporting' && (
        <div className="space-y-6">
          {/* Editable lines for HR; the chain below is the live (saved) structure. */}
          <Row>
            {canWrite ? (
              <>
                <SelectField id="p-rm" label="Reporting manager" {...bind('reporting_manager_id')}
                  options={personOptions(form.reporting_manager_id, employee.reporting_manager)}
                  hint={form.reporting_manager_id
                    ? `Employee code: ${codeOf(form.reporting_manager_id, employee.reporting_manager_code) || '—'}` : undefined} />
                <SelectField id="p-fm" label="Functional manager" {...bind('functional_manager_id')}
                  options={personOptions(form.functional_manager_id, employee.functional_manager)}
                  hint={form.functional_manager_id
                    ? `Employee code: ${codeOf(form.functional_manager_id, employee.functional_manager_code) || '—'}` : undefined} />
              </>
            ) : (
              <>
                <ReadOnly label="Reporting manager" value={employee.reporting_manager
                  && `${employee.reporting_manager}${employee.reporting_manager_code ? ` (${employee.reporting_manager_code})` : ''}`} />
                <ReadOnly label="Functional manager" value={employee.functional_manager
                  && `${employee.functional_manager}${employee.functional_manager_code ? ` (${employee.functional_manager_code})` : ''}`} />
              </>
            )}
          </Row>

          {!hierarchy ? (
            <HrmsLoading label="Loading reporting chain…" />
          ) : (
            <>
              <div>
                <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">
                  Reports up to
                </p>
                {hierarchy.manager_chain.length === 0 ? (
                  <p className="text-[13px] text-[var(--text-muted)]">No reporting manager set.</p>
                ) : (
                  <ol className="space-y-1.5">
                    {hierarchy.manager_chain.map((m, i) => (
                      <li key={m.user_id} className="flex items-center gap-2 text-[13px]">
                        <span className="text-[var(--text-muted)]" style={{ paddingLeft: i * 14 }}>↳</span>
                        <span className={`font-semibold ${m.circular ? 'text-[var(--accent-red)]' : 'text-[var(--text-main)]'}`}>
                          {m.name}
                        </span>
                        {personById[m.user_id]?.employee_code && (
                          <span className="font-mono text-[11px] text-[var(--text-muted)]">{personById[m.user_id].employee_code}</span>
                        )}
                        {m.governance_role && (
                          <span className="text-[11px] text-[var(--text-muted)]">{m.governance_role}</span>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
              </div>

              <div>
                <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">
                  Direct reports ({hierarchy.report_count})
                </p>
                {hierarchy.direct_reports.length === 0 ? (
                  <p className="text-[13px] text-[var(--text-muted)]">No direct reports.</p>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                    {hierarchy.direct_reports.map((r) => (
                      <button
                        key={r.user_id} type="button"
                        onClick={() => navigate(`/hrms/employees/${r.user_id}`)}
                        className="text-left p-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--accent-indigo)] transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <Network size={13} className="text-[var(--text-muted)] shrink-0" />
                          <span className="text-[13px] font-semibold text-[var(--text-main)] truncate">{r.name}</span>
                        </div>
                        <p className="mt-0.5 text-[11.5px] text-[var(--text-muted)] truncate">{r.email}</p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* FRD §3 System — who created / last changed the record, and whether it is live. */}
      {employee.has_profile && (
        <div className="pt-4 border-t border-[var(--border)] flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11.5px] text-[var(--text-muted)]">
          <span className={`px-2 py-0.5 rounded-md text-[11px] font-bold ${employee.active
            ? 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]'
            : 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}>
            {employee.active ? 'Active' : 'Inactive'}
          </span>
          {employee.created_at && (
            <span>Created {fmtDateTime(employee.created_at)}{nameOf(employee.created_by) ? ` by ${nameOf(employee.created_by)}` : ''}</span>
          )}
          {employee.updated_at && (
            <span>Modified {fmtDateTime(employee.updated_at)}{nameOf(employee.updated_by) ? ` by ${nameOf(employee.updated_by)}` : ''}</span>
          )}
        </div>
      )}
    </div>
  );
};

export default EmployeeProfile;
