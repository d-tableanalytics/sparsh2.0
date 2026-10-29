import React, { useEffect, useState } from 'react';
import { X, UserPlus, AlertTriangle } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import {
  getLinkableUsers, createEmployee, getEmployees, getEmployeeMasterLists, listFieldDefinitions,
  checkEmployeeDuplicates,
} from '../../../services/hrmsApi';
import { CustomFieldInput } from './EmployeeProfile';

/**
 * HRMS ▸ add employee.
 *
 * An employee profile EXTENDS an existing ERP user — it never creates a person. The picker
 * therefore lists only users who do not already have a profile (the server computes that
 * set), which is why there is no name/email field here: identity is owned by the user
 * record and is never duplicated into HRMS.
 *
 * The employee code is left blank by default and minted server-side from an atomic counter.
 *
 * Phase 1 FRD §4: official email and personal mobile are checked against other employees
 * on blur and again on submit. The warning is advisory — the server refuses a real clash
 * with a 409 whose message names the other employee. Mandatory configurable fields are asked
 * for here too, because the server will not create a profile without them.
 */

// Field -> its company list. Empty list = not configured = free text.
const LISTS = [
  ['work_location', 'locations', 'Location'],
  ['grade', 'grades', 'Grade'],
  ['employee_category', 'employee_categories', 'Employee category'],
];

const AddEmployeeModal = ({ departments, designations, onClose, onCreated }) => {
  const { scope, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [users, setUsers] = useState([]);
  const [people, setPeople] = useState([]);
  const [lists, setLists] = useState({});
  const [defs, setDefs] = useState([]);
  const [duplicates, setDuplicates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    user_id: '', department_id: '', designation_id: '',
    employment_status: 'Active', employment_type: 'Full-time',
    joined_on: '', base_salary: '',
    official_email: '', personal_mobile: '', work_location: '', grade: '',
    employee_category: '', reporting_manager_id: '',
  });
  const [custom, setCustom] = useState({});

  const canSetSalary = can(CAP.EMPLOYEE_SALARY_WRITE);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  useEffect(() => {
    getLinkableUsers(scope)
      .then(({ data }) => setUsers(data?.users || []))
      .catch((err) => showError(err?.response?.data?.detail || 'Could not load users.'))
      .finally(() => setLoading(false));
    // Optional extras — without them the fields below fall back to free text / no picker.
    getEmployees({ ...scope, limit: 500 })
      .then(({ data }) => setPeople((data?.employees || []).filter((p) => p.user_id))).catch(() => {});
    getEmployeeMasterLists(scope).then(({ data }) => setLists(data || {})).catch(() => {});
    listFieldDefinitions({ ...scope, module: 'employee' })
      .then(({ data }) => setDefs(Array.isArray(data) ? data : [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Mandatory configurable fields that would apply to this new record today, with no default
  // to fall back on — the same test the server makes before it creates the profile.
  const today = new Date().toLocaleDateString('en-CA');
  const requiredDefs = defs.filter((d) => d.status === 'Active' && d.mandatory
    && (d.default_value == null || d.default_value === '')
    && (!d.effective_from || d.effective_from <= today) && (!d.effective_to || d.effective_to >= today)
    && Object.entries(d.applicability || {})
      .every(([field, allowed]) => !allowed?.length || allowed
        .map((v) => String(v ?? '').trim().toLowerCase())
        .includes(String(form[field] ?? '').trim().toLowerCase())))
    .sort((a, b) => (a.display_order ?? 100) - (b.display_order ?? 100));

  const checkDuplicates = async () => {
    const values = {};
    ['official_email', 'personal_mobile'].forEach((k) => { if (form[k].trim()) values[k] = form[k].trim(); });
    if (!Object.keys(values).length) { setDuplicates([]); return []; }
    try {
      const { data } = await checkEmployeeDuplicates(
        { ...values, exclude_user_id: form.user_id || undefined }, scope);
      setDuplicates(data?.duplicates || []);
      return data?.duplicates || [];
    } catch {
      return [];   // advisory only — the server re-checks on create
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.user_id) return showError('Select a user.');
    const missing = requiredDefs.find((d) => {
      const v = custom[d.code];
      return v == null || v === '' || (Array.isArray(v) && v.length === 0);
    });
    if (missing) return showError(`${missing.label} is required.`);
    setSaving(true);
    try {
      await checkDuplicates();
      const payload = { user_id: form.user_id };
      // Send only what was filled — an empty string is not "clear this field", it is
      // "untouched", and the server treats a present key as an instruction.
      ['department_id', 'designation_id', 'employment_status', 'employment_type', 'joined_on',
        'official_email', 'personal_mobile', 'work_location', 'grade', 'employee_category',
        'reporting_manager_id']
        .forEach((k) => { if (form[k]) payload[k] = typeof form[k] === 'string' ? form[k].trim() : form[k]; });
      if (canSetSalary && form.base_salary !== '') payload.base_salary = Number(form.base_salary);
      if (Object.keys(custom).length) payload.custom_fields = custom;

      await createEmployee(payload, scope);
      showSuccess('Employee profile created');
      onCreated();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not create the employee profile.');
    } finally {
      setSaving(false);
    }
  };

  const field = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
  const label = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <UserPlus size={17} className="text-[var(--accent-indigo)]" />
            <h2 className="text-[15px] font-bold text-[var(--text-main)]">Add employee</h2>
          </div>
          <button type="button" onClick={onClose} className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <form onSubmit={submit} className="p-5 space-y-4 overflow-y-auto">
          <div>
            <label className={label} htmlFor="emp-user">User *</label>
            {loading ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">Loading users…</p>
            ) : users.length === 0 ? (
              <p className="text-[12.5px] text-[var(--text-muted)]">
                Every user in this company already has an employee profile.
              </p>
            ) : (
              <select id="emp-user" value={form.user_id} onChange={set('user_id')} className={field} required>
                <option value="">Select a user…</option>
                {users.map((u) => (
                  <option key={u.user_id} value={u.user_id}>
                    {u.name}{u.email ? ` — ${u.email}` : ''}
                  </option>
                ))}
              </select>
            )}
            <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">
              Employee records extend existing company users. To add a new person, create the
              user first in User Management.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={label} htmlFor="emp-dept">Department</label>
              <select id="emp-dept" value={form.department_id} onChange={set('department_id')} className={field}>
                <option value="">—</option>
                {departments.filter((d) => d.active).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label className={label} htmlFor="emp-desig">Designation</label>
              <select id="emp-desig" value={form.designation_id} onChange={set('designation_id')} className={field}>
                <option value="">—</option>
                {designations.filter((d) => d.active).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label className={label} htmlFor="emp-status">Status</label>
              <select id="emp-status" value={form.employment_status} onChange={set('employment_status')} className={field}>
                {['Active', 'On Notice', 'Resigned', 'Terminated', 'On Long Leave']
                  .map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className={label} htmlFor="emp-type">Employment type</label>
              <select id="emp-type" value={form.employment_type} onChange={set('employment_type')} className={field}>
                {['Full-time', 'Part-time', 'Contract', 'Intern', 'Consultant']
                  .map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className={label} htmlFor="emp-joined">Joining date</label>
              <input id="emp-joined" type="date" value={form.joined_on} onChange={set('joined_on')} className={field} />
            </div>
            {canSetSalary && (
              <div>
                <label className={label} htmlFor="emp-salary">Base salary (monthly)</label>
                <input id="emp-salary" type="number" min="0" step="1" value={form.base_salary}
                  onChange={set('base_salary')} placeholder="e.g. 30000" className={field} />
              </div>
            )}
            {LISTS.map(([key, listKey, text]) => (
              <div key={key}>
                <label className={label} htmlFor={`emp-${key}`}>{text}</label>
                {lists[listKey]?.length ? (
                  <select id={`emp-${key}`} value={form[key]} onChange={set(key)} className={field}>
                    <option value="">—</option>
                    {lists[listKey].map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                ) : (
                  <input id={`emp-${key}`} value={form[key]} onChange={set(key)} className={field}
                    placeholder="Free text — no list configured" />
                )}
              </div>
            ))}
            <div>
              <label className={label} htmlFor="emp-rm">Reporting manager</label>
              <select id="emp-rm" value={form.reporting_manager_id} onChange={set('reporting_manager_id')} className={field}>
                <option value="">—</option>
                {people.filter((p) => p.user_id !== form.user_id).map((p) => (
                  <option key={p.user_id} value={p.user_id}>
                    {p.name}{p.employee_code ? ` (${p.employee_code})` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={label} htmlFor="emp-oemail">Official email</label>
              <input id="emp-oemail" type="email" value={form.official_email} onChange={set('official_email')}
                onBlur={checkDuplicates} className={field} placeholder="Blank = use the login email" />
            </div>
            <div>
              <label className={label} htmlFor="emp-pmob">Personal mobile</label>
              <input id="emp-pmob" type="tel" value={form.personal_mobile} onChange={set('personal_mobile')}
                onBlur={checkDuplicates} className={field} />
            </div>
          </div>

          {requiredDefs.length > 0 && (
            <div className="space-y-3 pt-1">
              <p className="text-[12px] font-bold text-[var(--text-main)]">Required by your company</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {requiredDefs.map((d) => (
                  <div key={d.code} className={d.data_type === 'long_text' || d.data_type === 'multi_select' ? 'sm:col-span-2' : ''}>
                    <label className={label} htmlFor={`emp-cf-${d.code}`}>
                      {d.label}<span className="text-[var(--accent-red)]"> *</span>
                    </label>
                    <CustomFieldInput def={d} id={`emp-cf-${d.code}`} value={custom[d.code]}
                      onChange={(v) => setCustom((c) => ({ ...c, [d.code]: v }))} people={people} lists={lists} />
                    {d.help_text && <p className="mt-1 text-[11px] text-[var(--text-muted)]">{d.help_text}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {duplicates.length > 0 && (
            <div className="p-3 rounded-xl border border-[var(--accent-red)]/30 bg-[var(--accent-red-bg)] space-y-1">
              <p className="flex items-center gap-2 text-[12px] font-bold text-[var(--accent-red)]">
                <AlertTriangle size={14} /> Possible duplicate
              </p>
              {duplicates.map((d) => (
                <p key={`${d.field}-${d.employee_code}`} className="text-[12px] text-[var(--text-main)]">
                  {d.label} is already recorded for <b>{d.employee_code}</b>{d.name ? ` (${d.name})` : ''}.
                </p>
              ))}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="submit" disabled={saving || !form.user_id}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Creating…' : 'Create profile'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default AddEmployeeModal;
