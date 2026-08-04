import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Save, Loader2, UserPlus, Lock, ChevronDown, Search, Check } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { createEmployee, updateEmployee, getHrmsStaffOptions } from '../../services/hrmsApi';
import { hasHrmsPermission } from '../../utils/hrmsAccess';
import { Field } from './hrmsUi';
import { inputCls, labelCls } from './hrmsStyles';

// Add / edit an employee. One modal for both, so the field set can never diverge between
// creating and editing a record.
//
// The department / designation / location inputs are type-or-pick comboboxes backed by a
// datalist: an existing master value is one click away, and a typed value is upserted into the
// master list by the backend. The lists therefore populate from real use rather than needing to
// be curated before anyone can be added.
//
// Statutory / bank / salary inputs render only for a user with employee-record permission —
// the backend masks them on read and would reject them on write, so showing them would just
// invite a 403.

const EMPTY = {
  full_name: '', display_name: '', gender: '', date_of_birth: '',
  personal_email: '', work_email: '', phone: '', address: '',
  emergency_name: '', emergency_relation: '', emergency_phone: '',
  designation: '', department: '', location: '',
  employment_type: 'Full-time', grade: '', work_mode: 'Office',
  reporting_manager: '', user_id: '',
  status: 'Active', date_of_joining: '', probation_end_date: '', confirmation_date: '',
  pan: '', aadhaar: '', passport: '', driving_license: '', uan: '', esic_no: '',
  bank_name: '', bank_account: '', bank_ifsc: '', ctc_annual: '',
};

// API (camelCase) -> form (snake_case). Only the editable fields; code/timestamps stay server-owned.
const fromEmployee = (e) => ({
  full_name: e.fullName || '', display_name: e.displayName || '', gender: e.gender || '',
  date_of_birth: e.dateOfBirth || '', personal_email: e.personalEmail || '',
  work_email: e.workEmail || '', phone: e.phone || '', address: e.address || '',
  emergency_name: e.emergencyName || '', emergency_relation: e.emergencyRelation || '',
  emergency_phone: e.emergencyPhone || '', designation: e.designation || '',
  department: e.department || '', location: e.location || '',
  employment_type: e.employmentType || 'Full-time', grade: e.grade || '',
  work_mode: e.workMode || 'Office', reporting_manager: e.reportingManager || '',
  user_id: e.userId || '',
  status: e.status || 'Active', date_of_joining: e.dateOfJoining || '',
  probation_end_date: e.probationEndDate || '', confirmation_date: e.confirmationDate || '',
  pan: e.pan || '', aadhaar: e.aadhaar || '', passport: e.passport || '',
  driving_license: e.drivingLicense || '', uan: e.uan || '', esic_no: e.esicNo || '',
  bank_name: e.bankName || '', bank_account: e.bankAccount || '', bank_ifsc: e.bankIfsc || '',
  ctc_annual: e.ctcAnnual ?? '',
});

const SectionTitle = ({ children }) => (
  <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] pt-1">
    {children}
  </h3>
);

// Searchable dropdown over the internal-staff list, backing the 'linked account' and
// 'reporting manager' pickers (both store a staff _id). Kept inline so the modal owns its own
// field set, and styled off inputCls so it matches every other control here. A "— None —" row
// clears the link; the value is always the option's _id (or '' for none).
const StaffSelectField = ({ label, value, options, onChange }) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const ref = useRef(null);

  // Close on an outside click while open.
  useEffect(() => {
    if (!open) return undefined;
    const onDocClick = (ev) => {
      if (ref.current && !ref.current.contains(ev.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  const selected = options.find((o) => o._id === value) || null;
  const q = query.trim().toLowerCase();
  const filtered = q
    ? options.filter((o) =>
      `${o.full_name || ''} ${o.designation || ''} ${o.role || ''} ${o.email || ''}`
        .toLowerCase().includes(q))
    : options;

  const pick = (id) => { onChange(id); setOpen(false); setQuery(''); };

  return (
    <div className="flex flex-col gap-1.5" ref={ref}>
      <span className={labelCls}>{label}</span>
      <div className="relative">
        <button type="button" onClick={() => setOpen((v) => !v)}
          className={`${inputCls} flex items-center justify-between gap-2 text-left cursor-pointer`}>
          <span className={`truncate ${selected ? '' : 'text-[var(--text-muted)]'}`}>
            {selected ? selected.full_name : (value || '— None —')}
          </span>
          <ChevronDown size={15} className="text-[var(--text-muted)] shrink-0" />
        </button>
        {open && (
          <div className="absolute z-30 mt-1.5 w-full rounded-xl bg-[var(--bg-card)] border border-[var(--border)] shadow-xl overflow-hidden">
            <div className="relative p-2 border-b border-[var(--border)]">
              <Search size={13} className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none" />
              <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder="Search staff…"
                className="w-full pl-7 pr-2 py-1.5 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12px] font-semibold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]" />
            </div>
            <div className="max-h-52 overflow-y-auto py-1">
              <button type="button" onClick={() => pick('')}
                className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left hover:bg-[var(--table-hover)] transition-colors">
                <span className="text-[12.5px] font-semibold text-[var(--text-muted)]">— None —</span>
                {!value && <Check size={14} className="text-[var(--accent-indigo)] shrink-0" />}
              </button>
              {filtered.map((o) => (
                <button key={o._id} type="button" onClick={() => pick(o._id)}
                  className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left hover:bg-[var(--table-hover)] transition-colors">
                  <span className="min-w-0">
                    <span className="block text-[12.5px] font-bold text-[var(--text-main)] truncate">
                      {o.full_name}
                    </span>
                    {(o.designation || o.role) && (
                      <span className="block text-[10.5px] font-medium text-[var(--text-muted)] truncate">
                        {[o.designation, o.role].filter(Boolean).join(' · ')}
                      </span>
                    )}
                  </span>
                  {value === o._id && <Check size={14} className="text-[var(--accent-indigo)] shrink-0" />}
                </button>
              ))}
              {filtered.length === 0 && (
                <p className="px-3 py-3 text-[11.5px] font-semibold text-[var(--text-muted)] text-center">
                  No matches.
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const EmployeeFormModal = ({ isOpen, onClose, onSaved, onError, options, employee = null }) => {
  const { user } = useAuth();
  const isEdit = !!employee;
  const canSeeSensitive = hasHrmsPermission(user, 'hrms', 'update');

  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [staff, setStaff] = useState([]);

  // Seed on open. Keyed on the employee so reopening for someone else re-seeds rather than
  // carrying the previous person's values.
  useEffect(() => {
    if (!isOpen) return;
    setForm(employee ? { ...EMPTY, ...fromEmployee(employee) } : EMPTY);
  }, [isOpen, employee]);

  // Staff logins for the linked-account / reporting-manager pickers — fetched on open so the
  // list is fresh, and only while the modal is mounted.
  useEffect(() => {
    if (!isOpen) return;
    getHrmsStaffOptions().then((r) => setStaff(r.data || [])).catch(() => {});
  }, [isOpen]);

  if (!isOpen) return null;

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  const handleSave = async () => {
    if (!form.full_name.trim()) {
      onError?.('Full name is required');
      return;
    }
    setSaving(true);
    try {
      // Empty strings are meaningful on create (a blank field) but ambiguous on PATCH, where
      // the backend skips nulls — so send only what the user actually filled in when editing.
      const payload = { ...form };
      if (payload.ctc_annual === '') delete payload.ctc_annual;
      else payload.ctc_annual = Number(payload.ctc_annual) || 0;
      if (!canSeeSensitive) {
        ['pan', 'aadhaar', 'passport', 'driving_license', 'uan', 'esic_no',
          'bank_name', 'bank_account', 'bank_ifsc', 'ctc_annual'].forEach((k) => delete payload[k]);
      }
      const res = isEdit
        ? await updateEmployee(employee.employeeCode, payload)
        : await createEmployee(payload);
      onSaved?.(res.data);
    } catch (err) {
      onError?.(err.response?.data?.detail || `Failed to ${isEdit ? 'update' : 'create'} employee`);
    } finally {
      setSaving(false);
    }
  };

  const statuses = options?.statuses ?? ['Active'];
  const employmentTypes = options?.employmentTypes ?? ['Full-time'];
  const workModes = options?.workModes ?? ['Office'];

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[300] flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
          className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        />
        <motion.div
          initial={{ opacity: 0, scale: 0.96, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-3xl max-h-[90vh] flex flex-col rounded-[24px] bg-[var(--bg-card)] border border-[var(--border)] shadow-2xl overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)] bg-[var(--table-header-bg)]">
            <div className="flex items-center gap-2.5">
              <span className="w-9 h-9 rounded-xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
                <UserPlus size={17} />
              </span>
              <div>
                <h2 className="text-[15px] font-black tracking-tight text-[var(--text-main)]">
                  {isEdit ? 'Edit Employee' : 'Add Employee'}
                </h2>
                {isEdit && (
                  <p className="text-[11px] font-bold text-[var(--text-muted)]"
                    style={{ fontVariantNumeric: 'tabular-nums' }}>
                    {employee.employeeCode}
                  </p>
                )}
              </div>
            </div>
            <button onClick={onClose}
              className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--table-hover)] transition-colors"
              aria-label="Close">
              <X size={19} />
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-4">
            <SectionTitle>Identity</SectionTitle>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              <Field label="Full name" required>
                <input className={inputCls} value={form.full_name}
                  onChange={(e) => set({ full_name: e.target.value })} autoFocus />
              </Field>
              <Field label="Display name">
                <input className={inputCls} value={form.display_name}
                  onChange={(e) => set({ display_name: e.target.value })} />
              </Field>
              <Field label="Gender">
                <select className={`${inputCls} cursor-pointer`} value={form.gender}
                  onChange={(e) => set({ gender: e.target.value })}>
                  <option value="">Not specified</option>
                  <option value="Female">Female</option>
                  <option value="Male">Male</option>
                  <option value="Other">Other</option>
                </select>
              </Field>
              <Field label="Date of birth">
                <input type="date" className={inputCls} value={form.date_of_birth || ''}
                  onChange={(e) => set({ date_of_birth: e.target.value })} />
              </Field>
              <Field label="Work email">
                <input type="email" className={inputCls} value={form.work_email}
                  onChange={(e) => set({ work_email: e.target.value })} />
              </Field>
              <Field label="Personal email">
                <input type="email" className={inputCls} value={form.personal_email}
                  onChange={(e) => set({ personal_email: e.target.value })} />
              </Field>
              <Field label="Phone">
                <input className={inputCls} value={form.phone}
                  onChange={(e) => set({ phone: e.target.value })} />
              </Field>
              <Field label="Address" className="sm:col-span-1">
                <input className={inputCls} value={form.address}
                  onChange={(e) => set({ address: e.target.value })} />
              </Field>
            </div>

            <SectionTitle>Position</SectionTitle>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              {/* Type-or-pick: the datalist offers existing masters, a new value is upserted. */}
              <Field label="Designation">
                <input className={inputCls} list="hrms-designations" value={form.designation}
                  onChange={(e) => set({ designation: e.target.value })} />
                <datalist id="hrms-designations">
                  {(options?.designations ?? []).map((d) => <option key={d} value={d} />)}
                </datalist>
              </Field>
              <Field label="Department">
                <input className={inputCls} list="hrms-departments" value={form.department}
                  onChange={(e) => set({ department: e.target.value })} />
                <datalist id="hrms-departments">
                  {(options?.departments ?? []).map((d) => <option key={d} value={d} />)}
                </datalist>
              </Field>
              <Field label="Location">
                <input className={inputCls} list="hrms-locations" value={form.location}
                  onChange={(e) => set({ location: e.target.value })} />
                <datalist id="hrms-locations">
                  {(options?.locations ?? []).map((d) => <option key={d} value={d} />)}
                </datalist>
              </Field>
              <Field label="Grade">
                <input className={inputCls} value={form.grade}
                  onChange={(e) => set({ grade: e.target.value })} />
              </Field>
              <Field label="Employment type">
                <select className={`${inputCls} cursor-pointer`} value={form.employment_type}
                  onChange={(e) => set({ employment_type: e.target.value })}>
                  {employmentTypes.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </Field>
              <Field label="Work mode">
                <select className={`${inputCls} cursor-pointer`} value={form.work_mode}
                  onChange={(e) => set({ work_mode: e.target.value })}>
                  {workModes.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </Field>
              {/* Both reference a Sparsh staff account; the linked account is what lets this
                  person punch attendance and receive a payslip. */}
              <StaffSelectField label="Reporting manager" value={form.reporting_manager}
                options={staff} onChange={(id) => set({ reporting_manager: id })} />
              <StaffSelectField label="Linked staff account" value={form.user_id}
                options={staff} onChange={(id) => set({ user_id: id })} />
            </div>

            <SectionTitle>Lifecycle</SectionTitle>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              <Field label="Status">
                <select className={`${inputCls} cursor-pointer`} value={form.status}
                  onChange={(e) => set({ status: e.target.value })}>
                  {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </Field>
              <Field label="Date of joining">
                <input type="date" className={inputCls} value={form.date_of_joining || ''}
                  onChange={(e) => set({ date_of_joining: e.target.value })} />
              </Field>
              <Field label="Probation ends">
                <input type="date" className={inputCls} value={form.probation_end_date || ''}
                  onChange={(e) => set({ probation_end_date: e.target.value })} />
              </Field>
              <Field label="Confirmation date">
                <input type="date" className={inputCls} value={form.confirmation_date || ''}
                  onChange={(e) => set({ confirmation_date: e.target.value })} />
              </Field>
            </div>

            <SectionTitle>Emergency contact</SectionTitle>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
              <Field label="Name">
                <input className={inputCls} value={form.emergency_name}
                  onChange={(e) => set({ emergency_name: e.target.value })} />
              </Field>
              <Field label="Relation">
                <input className={inputCls} value={form.emergency_relation}
                  onChange={(e) => set({ emergency_relation: e.target.value })} />
              </Field>
              <Field label="Phone">
                <input className={inputCls} value={form.emergency_phone}
                  onChange={(e) => set({ emergency_phone: e.target.value })} />
              </Field>
            </div>

            {canSeeSensitive ? (
              <>
                <SectionTitle>Statutory &amp; bank</SectionTitle>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
                  <Field label="PAN">
                    <input className={inputCls} value={form.pan}
                      onChange={(e) => set({ pan: e.target.value })} />
                  </Field>
                  <Field label="Aadhaar">
                    <input className={inputCls} value={form.aadhaar}
                      onChange={(e) => set({ aadhaar: e.target.value })} />
                  </Field>
                  <Field label="UAN">
                    <input className={inputCls} value={form.uan}
                      onChange={(e) => set({ uan: e.target.value })} />
                  </Field>
                  <Field label="ESIC number">
                    <input className={inputCls} value={form.esic_no}
                      onChange={(e) => set({ esic_no: e.target.value })} />
                  </Field>
                  <Field label="Passport">
                    <input className={inputCls} value={form.passport}
                      onChange={(e) => set({ passport: e.target.value })} />
                  </Field>
                  <Field label="Driving licence">
                    <input className={inputCls} value={form.driving_license}
                      onChange={(e) => set({ driving_license: e.target.value })} />
                  </Field>
                  <Field label="Bank name">
                    <input className={inputCls} value={form.bank_name}
                      onChange={(e) => set({ bank_name: e.target.value })} />
                  </Field>
                  <Field label="Account number">
                    <input className={inputCls} value={form.bank_account}
                      onChange={(e) => set({ bank_account: e.target.value })} />
                  </Field>
                  <Field label="IFSC">
                    <input className={inputCls} value={form.bank_ifsc}
                      onChange={(e) => set({ bank_ifsc: e.target.value })} />
                  </Field>
                  <Field label="Annual CTC">
                    <input type="number" min="0" className={inputCls} value={form.ctc_annual}
                      onChange={(e) => set({ ctc_annual: e.target.value })} />
                  </Field>
                </div>
              </>
            ) : (
              <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-[var(--input-bg)] border border-dashed border-[var(--border)]">
                <Lock size={14} className="text-[var(--text-muted)]" />
                <span className="text-[11.5px] font-bold text-[var(--text-muted)]">
                  Statutory, bank and salary fields need employee-record permission.
                </span>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2.5 px-6 py-4 border-t border-[var(--border)] bg-[var(--table-header-bg)]">
            <button onClick={onClose}
              className="px-5 py-2.5 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors">
              Cancel
            </button>
            <button onClick={handleSave} disabled={saving}
              className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] disabled:opacity-50 transition-all">
              {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
              {isEdit ? 'Save changes' : 'Create employee'}
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default EmployeeFormModal;
