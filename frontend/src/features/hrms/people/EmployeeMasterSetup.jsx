import React, { useCallback, useEffect, useState } from 'react';
import {
  ListTree, Plus, Pencil, Trash2, X, Save, History, ShieldAlert, ShieldCheck, CheckCircle2, Archive,
  RotateCcw,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import BoardTabs from '../common/BoardTabs';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getEmployeeMasterLists, saveEmployeeMasterLists, listFieldDefinitions, saveFieldDefinition,
  setFieldDefinitionStatus, deleteFieldDefinition, getFieldDefinitionUsage,
  getEmployeeIdFormat, saveEmployeeIdFormat, getDepartments,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ Employee Master Setup (Phase 1 FRD §3, §21-22).
 *
 * Two things HR configures once and the employee profile then reads:
 *
 *   * DROPDOWN LISTS — the company's legal entities, locations, grades, payroll groups, ...
 *     A list left empty means "not configured", and the profile then accepts free text for
 *     that field, so a company that has not set up its locations can still save people.
 *     Removing a value does not touch employees who already carry it.
 *   * CONFIGURABLE FIELDS — extra Employee / Attendance fields without a code change. A new
 *     field starts as Draft and is invisible until activated. A field that holds values is
 *     retired, never deleted, and its data type is then frozen (the server enforces both).
 */

// Mirrors MASTER_LIST_FIELDS in models/hrms.py: [list key, label, hint].
const LIST_META = [
  ['legal_entities', 'Company / legal entity', 'The legal employer named on letters and filings.'],
  ['business_units', 'Business unit / branch'],
  ['locations', 'Location', 'Where the person works.'],
  ['sub_departments', 'Sub-department'],
  ['grades', 'Grade'],
  ['levels', 'Level'],
  ['cost_centres', 'Cost centre', 'Where their cost is booked.'],
  ['employee_categories', 'Employee category', 'e.g. Staff, Worker, Trainee.'],
  ['payroll_groups', 'Payroll group'],
  ['salary_templates', 'Salary structure template'],
  ['attendance_policy_groups', 'Attendance policy group'],
  ['holiday_calendars', 'Holiday calendar'],
];
const LIST_LABEL = Object.fromEntries(LIST_META.map(([k, l]) => [k, l]));

const DATA_TYPES = [
  ['text', 'Text'], ['long_text', 'Long text'], ['number', 'Whole number'], ['decimal', 'Decimal'],
  ['currency', 'Currency'], ['date', 'Date'], ['datetime', 'Date & time'], ['boolean', 'Yes / No'],
  ['single_select', 'Dropdown — one'], ['multi_select', 'Dropdown — many'],
  ['employee_lookup', 'Employee'], ['master_lookup', 'Master list'], ['document', 'Document'],
];
const TYPE_LABEL = Object.fromEntries(DATA_TYPES);
const CHOICE_TYPES = new Set(['single_select', 'multi_select']);
const TEXT_TYPES = new Set(['text', 'long_text']);
const NUMBER_TYPES = new Set(['number', 'decimal', 'currency']);
const CODE_RE = /^[a-z][a-z0-9_]{1,39}$/;

const STATUS_TONE = {
  Draft: 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]',
  Approved: 'bg-[var(--accent-indigo)]/10 text-[var(--accent-indigo)]',
  Active: 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]',
  Retired: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
};

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] disabled:opacity-60';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';
const TH = 'text-left px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest';

const BLANK_FIELD = {
  code: '', label: '', section: '', help_text: '', data_type: 'text', options: [], master_list: '',
  mandatory: false, read_only: false, default_value: '', unique: false, searchable: false,
  filterable: false, exportable: true, show_in_list: false, sensitive: false,
  visible_to_self: true, visible_to_manager: true, visible_to_payroll: false,
  min_length: '', max_length: '', min_value: '', max_value: '', pattern: '', pattern_message: '',
  min_date: '', max_date: '', display_order: 100, applicability: {}, effective_from: '',
  effective_to: '', change_reason: '',
  // FRD §22 dependent validation, flattened for the form (saved as `depends_on`).
  depends_field: '', depends_equals: '', depends_rule: 'required',
  source_column: '',
};

// §22 Applicability: the profile key each restriction is tested against (the server's
// `_applies` compares the record's value with the listed ones). Company is implicit --
// every definition already belongs to one company.
const APPLICABILITY_KEYS = [
  ['legal_entity', 'Companies / legal entities'], ['work_location', 'Locations'], ['grade', 'Grades'], ['level', 'Levels'],
  ['employee_category', 'Employee categories'], ['payroll_group', 'Payroll groups'],
];

// Profile keys a dependent rule may test besides the module's own custom fields.
const PROFILE_DEPENDENCY_KEYS = [
  ['marital_status', 'Marital status'], ['gender', 'Gender'], ['nationality', 'Nationality'],
  ['employee_category', 'Employee category'], ['employment_status', 'Employment status'],
  ['work_location', 'Work location'],
];

const errText = (err, fallback) => err?.response?.data?.detail || fallback;

const fmtValue = (v) => {
  if (v == null || v === '') return '—';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (Array.isArray(v)) {
    return v.length && typeof v[0] === 'object'
      ? v.map((o) => o.label || o.value).join(', ') : (v.join(', ') || '—');
  }
  if (typeof v === 'object') {
    const text = JSON.stringify(v);
    return text === '{}' ? '—' : text.slice(0, 80);
  }
  return String(v);
};

const fmtDateTime = (value) => {
  if (!value) return '';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value)
    : d.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
};

const Check = ({ label, checked, onChange, disabled }) => (
  <label className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
    <input type="checkbox" checked={!!checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
    {label}
  </label>
);

const Group = ({ title, children }) => (
  <fieldset className="space-y-3">
    <legend className="text-[12.5px] font-bold text-[var(--text-main)] mb-2">{title}</legend>
    {children}
  </fieldset>
);

// ─────────────────────────────────────────────────────────────
// Dropdown lists
// ─────────────────────────────────────────────────────────────
const ListsPanel = ({ canWrite }) => {
  const { scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [saved, setSaved] = useState({});
  const [draft, setDraft] = useState({});
  const [inputs, setInputs] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getEmployeeMasterLists(scope);
      setSaved(data || {});
      setDraft(data || {});
    } catch (err) {
      setError(errText(err, 'Could not load the dropdown lists.'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const dirty = LIST_META.map(([k]) => k)
    .filter((k) => JSON.stringify(draft[k] || []) !== JSON.stringify(saved[k] || []));

  const addValue = (key) => {
    const value = (inputs[key] || '').trim();
    if (!value) return;
    if ((draft[key] || []).some((v) => v.toLowerCase() === value.toLowerCase())) {
      showError(`"${value}" is already in ${LIST_LABEL[key]}.`);
      return;
    }
    setDraft((d) => ({ ...d, [key]: [...(d[key] || []), value] }));
    setInputs((i) => ({ ...i, [key]: '' }));
  };

  const removeValue = (key, value) =>
    setDraft((d) => ({ ...d, [key]: (d[key] || []).filter((v) => v !== value) }));

  const save = async () => {
    setSaving(true);
    try {
      // Only the lists that changed — the server merges, so untouched lists are left alone.
      const { data } = await saveEmployeeMasterLists(
        Object.fromEntries(dirty.map((k) => [k, draft[k] || []])), scope);
      setSaved(data || {});
      setDraft(data || {});
      showSuccess(`${dirty.length} ${dirty.length === 1 ? 'list' : 'lists'} saved`);
    } catch (err) {
      showError(errText(err, 'Could not save the lists.'));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <HrmsLoading label="Loading dropdown lists…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[12px] text-[var(--text-muted)] max-w-2xl">
          These feed the dropdowns on the employee profile. A list left empty is treated as not
          configured, and that field then takes free text. Removing a value does not change
          employees who already have it.
        </p>
        {canWrite && (
          <div className="flex items-center gap-2">
            {dirty.length > 0 && (
              <button type="button" onClick={() => setDraft(saved)}
                className="h-9 px-3.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
                Discard
              </button>
            )}
            <button type="button" onClick={save} disabled={saving || dirty.length === 0}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5 disabled:opacity-50">
              <Save size={14} /> {saving ? 'Saving…' : dirty.length ? `Save (${dirty.length})` : 'Save'}
            </button>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {LIST_META.map(([key, label, hint]) => (
          <div key={key} className={`p-4 rounded-xl border bg-[var(--bg-card)] space-y-3 ${
            dirty.includes(key) ? 'border-[var(--accent-indigo)]' : 'border-[var(--border)]'}`}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <h3 className="text-[13px] font-bold text-[var(--text-main)]">{label}</h3>
                {hint && <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">{hint}</p>}
              </div>
              <span className="text-[11px] font-bold text-[var(--text-muted)] tabular-nums shrink-0">
                {(draft[key] || []).length}
              </span>
            </div>
            {(draft[key] || []).length === 0 ? (
              <p className="text-[12px] italic text-[var(--text-muted)]">Not configured — free text allowed.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {(draft[key] || []).map((v) => (
                  <span key={v}
                    className="inline-flex items-center gap-1 pl-2.5 pr-1 py-1 rounded-lg bg-[var(--input-bg)] text-[12px] font-semibold text-[var(--text-main)]">
                    {v}
                    {canWrite && (
                      <button type="button" onClick={() => removeValue(key, v)} title={`Remove "${v}"`}
                        className="p-0.5 rounded text-[var(--text-muted)] hover:text-[var(--accent-red)]">
                        <X size={12} />
                      </button>
                    )}
                  </span>
                ))}
              </div>
            )}
            {canWrite && (
              <div className="flex gap-2">
                <input value={inputs[key] || ''} placeholder={`Add a ${label.toLowerCase()}`}
                  aria-label={`New ${label}`}
                  onChange={(e) => setInputs((i) => ({ ...i, [key]: e.target.value }))}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addValue(key); } }}
                  className={`${FIELD} flex-1 min-w-0`} />
                <button type="button" onClick={() => addValue(key)} disabled={!(inputs[key] || '').trim()}
                  className="h-9 px-3 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--accent-indigo)] flex items-center gap-1 disabled:opacity-50">
                  <Plus size={14} /> Add
                </button>
              </div>
            )}
          </div>
        ))}

        <div className="p-4 rounded-xl border border-dashed border-[var(--border)] bg-[var(--bg-card)] space-y-3">
          <div>
            <h3 className="text-[13px] font-bold text-[var(--text-main)]">Shifts</h3>
            <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
              Read-only here — managed under Attendance ▸ Shifts.
            </p>
          </div>
          {(saved.shifts || []).length === 0 ? (
            <p className="text-[12px] italic text-[var(--text-muted)]">No active shifts.</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {saved.shifts.map((s) => (
                <span key={s} className="px-2.5 py-1 rounded-lg bg-[var(--input-bg)] font-mono text-[12px] text-[var(--text-main)]">{s}</span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────
// Configurable fields
// ─────────────────────────────────────────────────────────────
const toFieldForm = (def) => {
  const f = { ...BLANK_FIELD };
  Object.keys(BLANK_FIELD).forEach((k) => {
    if (def[k] !== undefined && def[k] !== null) f[k] = def[k];
  });
  f.options = (def.options || []).map((o) => ({ value: o.value, label: o.label || '', active: o.active !== false }));
  f.change_reason = '';
  f.depends_field = def.depends_on?.field || '';
  f.depends_equals = (def.depends_on?.equals || []).join(', ');
  f.depends_rule = def.depends_on?.rule || 'required';
  return f;
};

const FieldDefinitionModal = ({ module, initial, sections, siblings = [], onClose, onSaved }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const isNew = !initial;

  const [form, setForm] = useState(() => (initial ? toFieldForm(initial) : { ...BLANK_FIELD }));
  const [codeTouched, setCodeTouched] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [departments, setDepartments] = useState([]);
  useEffect(() => {
    getDepartments(scope).then(({ data }) => setDepartments(data?.departments || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const setApplicability = (key, values) => setForm((f) => {
    const next = { ...(f.applicability || {}) };
    if (values.length) next[key] = values; else delete next[key];
    return { ...f, applicability: next };
  });

  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const bind = (key) => ({ value: form[key] ?? '', onChange: (e) => set(key, e.target.value) });
  const setLabel = (value) => setForm((f) => ({
    ...f, label: value,
    // Suggest a code from the label until the user edits the code themselves.
    code: codeTouched ? f.code
      : value.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^[^a-z]+|_+$/g, '').slice(0, 40),
  }));
  const setOption = (i, key, value) => setForm((f) => ({
    ...f, options: f.options.map((o, j) => (j === i ? { ...o, [key]: value } : o)),
  }));

  const type = form.data_type;

  const submit = async (e) => {
    e.preventDefault();
    const code = form.code.trim().toLowerCase();
    if (!form.label.trim()) return showError('A field label is required.');
    if (!CODE_RE.test(code)) {
      return showError('Code: lowercase letters, digits and _, 2-40 characters, starting with a letter.');
    }
    const options = form.options.filter((o) => String(o.value).trim())
      .map((o) => ({ value: String(o.value).trim(), label: String(o.label || '').trim() || String(o.value).trim(), active: o.active }));
    if (CHOICE_TYPES.has(type) && !options.length) return showError('A dropdown field needs at least one option.');
    if (type === 'master_lookup' && !form.master_list) return showError('Choose which master list to look up.');

    const str = (v) => String(v ?? '').trim() || null;
    const num = (v) => (v === '' || v == null ? null : Number(v));
    const int = (v) => (v === '' || v == null ? null : parseInt(v, 10));
    const payload = {
      module, code, label: form.label.trim(), section: str(form.section), help_text: str(form.help_text),
      data_type: type,
      options: CHOICE_TYPES.has(type) ? options : [],
      master_list: type === 'master_lookup' ? form.master_list : null,
      mandatory: form.mandatory, read_only: form.read_only, default_value: str(form.default_value),
      unique: form.unique, searchable: form.searchable, filterable: form.filterable,
      exportable: form.exportable, show_in_list: form.show_in_list, sensitive: form.sensitive,
      visible_to_self: form.visible_to_self, visible_to_manager: form.visible_to_manager,
      visible_to_payroll: form.visible_to_payroll,
      min_length: int(form.min_length), max_length: int(form.max_length),
      min_value: num(form.min_value), max_value: num(form.max_value),
      pattern: str(form.pattern), pattern_message: str(form.pattern_message),
      min_date: str(form.min_date), max_date: str(form.max_date),
      source_column: module === 'attendance' ? str(form.source_column) : null,
      depends_on: form.depends_field
        ? {
          field: form.depends_field,
          equals: String(form.depends_equals).split(',').map((v) => v.trim()).filter(Boolean),
          rule: form.depends_rule,
        }
        : null,
      display_order: int(form.display_order) ?? 100,
      applicability: form.applicability || {},
      effective_from: str(form.effective_from), effective_to: str(form.effective_to),
      change_reason: str(form.change_reason),
    };
    setSaving(true);
    try {
      const { data } = await saveFieldDefinition(payload, scope);
      showSuccess(isNew ? `"${data.label}" added as Draft — activate it to start using it` : `"${data.label}" saved`);
      onSaved(data);
    } catch (err) {
      showError(errText(err, 'Could not save the field.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold text-[var(--text-main)] truncate">
              {isNew ? 'Add field' : `Edit ${initial.label}`}
            </h2>
            <p className="text-[11.5px] text-[var(--text-muted)]">
              {module === 'employee' ? 'Employee' : 'Attendance'} field
              {!isNew && ` · v${initial.version || 1} · ${initial.status}`}
            </p>
          </div>
          <button type="button" onClick={onClose} className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <form onSubmit={submit} className="p-5 space-y-6 overflow-y-auto">
          <Group title="Identity">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className={LABEL} htmlFor="fd-label">Label *</label>
                <input id="fd-label" value={form.label} onChange={(e) => setLabel(e.target.value)} className={FIELD} required />
              </div>
              <div>
                <label className={LABEL} htmlFor="fd-code">Code *</label>
                <input id="fd-code" value={form.code} disabled={!isNew}
                  onChange={(e) => { setCodeTouched(true); set('code', e.target.value); }}
                  className={`${FIELD} font-mono`} placeholder="e.g. shoe_size" />
                <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                  {isNew ? 'Stored with every value — cannot be changed later.' : 'Fixed once created.'}
                </p>
              </div>
              <div>
                <label className={LABEL} htmlFor="fd-section">Section</label>
                <input id="fd-section" list="fd-sections" {...bind('section')} className={FIELD} placeholder="General" />
                <datalist id="fd-sections">
                  {sections.map((s) => <option key={s} value={s} />)}
                </datalist>
              </div>
              <div>
                <label className={LABEL} htmlFor="fd-order">Display order</label>
                <input id="fd-order" type="number" {...bind('display_order')} className={FIELD} />
              </div>
              <div className="sm:col-span-2">
                <label className={LABEL} htmlFor="fd-help">Help text</label>
                <input id="fd-help" {...bind('help_text')} className={FIELD} placeholder="Shown under the input" />
              </div>
            </div>
          </Group>

          <Group title="Type">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className={LABEL} htmlFor="fd-type">Data type</label>
                <select id="fd-type" {...bind('data_type')} className={FIELD}>
                  {DATA_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                {!isNew && (
                  <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                    Refused once the field holds values — retire it and add a new one instead.
                  </p>
                )}
              </div>
              {type === 'master_lookup' && (
                <div>
                  <label className={LABEL} htmlFor="fd-master">Master list</label>
                  <select id="fd-master" {...bind('master_list')} className={FIELD}>
                    <option value="">Choose…</option>
                    {LIST_META.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                </div>
              )}
            </div>

            {CHOICE_TYPES.has(type) && (
              <div className="space-y-2">
                <p className={LABEL}>Options</p>
                {form.options.map((o, i) => (
                  <div key={i} className="flex flex-wrap sm:flex-nowrap items-center gap-2">
                    <input value={o.value} onChange={(e) => setOption(i, 'value', e.target.value)}
                      placeholder="Value" aria-label={`Option ${i + 1} value`} className={`${FIELD} sm:w-40 font-mono`} />
                    <input value={o.label} onChange={(e) => setOption(i, 'label', e.target.value)}
                      placeholder="Label (optional)" aria-label={`Option ${i + 1} label`} className={`${FIELD} flex-1 min-w-0`} />
                    <Check label="Active" checked={o.active} onChange={(v) => setOption(i, 'active', v)} />
                    <button type="button" title="Remove option"
                      onClick={() => setForm((f) => ({ ...f, options: f.options.filter((_, j) => j !== i) }))}
                      className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)]">
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
                <button type="button"
                  onClick={() => setForm((f) => ({ ...f, options: [...f.options, { value: '', label: '', active: true }] }))}
                  className="h-8 px-3 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--accent-indigo)] flex items-center gap-1">
                  <Plus size={13} /> Add option
                </button>
                {!isNew && (
                  <p className="text-[11px] text-[var(--text-muted)]">
                    Untick Active rather than removing an option people have already chosen.
                  </p>
                )}
              </div>
            )}
          </Group>

          <Group title="Behaviour">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
              <Check label="Mandatory" checked={form.mandatory} onChange={(v) => set('mandatory', v)} />
              <Check label="Read-only once set" checked={form.read_only} onChange={(v) => set('read_only', v)} />
              <Check label="Unique" checked={form.unique} onChange={(v) => set('unique', v)} />
              <Check label="Searchable" checked={form.searchable} onChange={(v) => set('searchable', v)} />
              <Check label="Filterable" checked={form.filterable} onChange={(v) => set('filterable', v)} />
              <Check label="Exportable" checked={form.exportable} onChange={(v) => set('exportable', v)} />
              <Check label="Show in list" checked={form.show_in_list} onChange={(v) => set('show_in_list', v)} />
              <Check label="Sensitive" checked={form.sensitive} onChange={(v) => set('sensitive', v)} />
            </div>
            <div className="sm:w-1/2">
              <label className={LABEL} htmlFor="fd-default">Default value</label>
              <input id="fd-default" {...bind('default_value')} className={FIELD} />
              <p className="mt-1 text-[11px] text-[var(--text-muted)]">Fills a mandatory field left blank.</p>
            </div>
          </Group>

          <Group title="Who can see it">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
              <Check label="The employee" checked={form.visible_to_self} onChange={(v) => set('visible_to_self', v)} />
              <Check label="Their manager" checked={form.visible_to_manager} onChange={(v) => set('visible_to_manager', v)} />
              <Check label="Payroll" checked={form.visible_to_payroll} onChange={(v) => set('visible_to_payroll', v)} />
            </div>
            <p className="text-[11px] text-[var(--text-muted)]">
              HR always sees every field. A sensitive field is shown only to HR and the employee.
            </p>
          </Group>

          {(TEXT_TYPES.has(type) || NUMBER_TYPES.has(type) || type === 'date') && (
            <Group title="Validation">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {TEXT_TYPES.has(type) && (
                  <>
                    <div>
                      <label className={LABEL} htmlFor="fd-minlen">Min length</label>
                      <input id="fd-minlen" type="number" min="0" {...bind('min_length')} className={FIELD} />
                    </div>
                    <div>
                      <label className={LABEL} htmlFor="fd-maxlen">Max length</label>
                      <input id="fd-maxlen" type="number" min="1" {...bind('max_length')} className={FIELD} />
                    </div>
                    <div>
                      <label className={LABEL} htmlFor="fd-pattern">Pattern (regular expression)</label>
                      <input id="fd-pattern" {...bind('pattern')} className={`${FIELD} font-mono`} placeholder="e.g. [A-Z]{2}\d{4}" />
                    </div>
                    <div>
                      <label className={LABEL} htmlFor="fd-pattern-msg">Pattern message</label>
                      <input id="fd-pattern-msg" {...bind('pattern_message')} className={FIELD} placeholder="Shown when it does not match" />
                    </div>
                  </>
                )}
                {NUMBER_TYPES.has(type) && (
                  <>
                    <div>
                      <label className={LABEL} htmlFor="fd-minval">Min value</label>
                      <input id="fd-minval" type="number" step="any" {...bind('min_value')} className={FIELD} />
                    </div>
                    <div>
                      <label className={LABEL} htmlFor="fd-maxval">Max value</label>
                      <input id="fd-maxval" type="number" step="any" {...bind('max_value')} className={FIELD} />
                    </div>
                  </>
                )}
                {type === 'date' && (
                  <>
                    <div>
                      <label className={LABEL} htmlFor="fd-mindate">Earliest date</label>
                      <input id="fd-mindate" type="date" {...bind('min_date')} className={FIELD} />
                    </div>
                    <div>
                      <label className={LABEL} htmlFor="fd-maxdate">Latest date</label>
                      <input id="fd-maxdate" type="date" {...bind('max_date')} className={FIELD} />
                    </div>
                  </>
                )}
              </div>
            </Group>
          )}

          {module === 'attendance' && (
            <Group title="Source mapping">
              <div>
                <label className={LABEL} htmlFor="fd-source">Import file column (optional)</label>
                <input id="fd-source" {...bind('source_column')} className={FIELD}
                  placeholder="e.g. Device ID — filled from the attendance import file" />
              </div>
            </Group>
          )}

          <Group title="Dependent validation">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className={LABEL} htmlFor="fd-dep-rule">This field is</label>
                <select id="fd-dep-rule" {...bind('depends_rule')} className={FIELD}>
                  <option value="required">Required when</option>
                  <option value="only">Allowed only when</option>
                </select>
              </div>
              <div>
                <label className={LABEL} htmlFor="fd-dep-field">Field</label>
                <select id="fd-dep-field" {...bind('depends_field')} className={FIELD}>
                  <option value="">No dependency</option>
                  {siblings.filter((s) => s.code !== form.code).map((s) => (
                    <option key={s.code} value={s.code}>{s.label}</option>
                  ))}
                  {module === 'employee' && PROFILE_DEPENDENCY_KEYS.map(([k, l]) => (
                    <option key={k} value={k}>{l} (profile)</option>
                  ))}
                </select>
              </div>
              <div>
                <label className={LABEL} htmlFor="fd-dep-eq">Is one of</label>
                <input id="fd-dep-eq" {...bind('depends_equals')} className={FIELD}
                  disabled={!form.depends_field} placeholder="e.g. Married, Divorced" />
              </div>
            </div>
          </Group>

          <Group title="In force">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className={LABEL} htmlFor="fd-from">Effective from</label>
                <input id="fd-from" type="date" {...bind('effective_from')} className={FIELD} />
              </div>
              <div>
                <label className={LABEL} htmlFor="fd-to">Effective to</label>
                <input id="fd-to" type="date" {...bind('effective_to')} className={FIELD} />
              </div>
            </div>
          </Group>

          <Group title="Applies to (blank = everyone)">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {APPLICABILITY_KEYS.map(([key, label]) => (
                <div key={key}>
                  <label className={LABEL} htmlFor={`fd-app-${key}`}>{label}</label>
                  <input id={`fd-app-${key}`} className={FIELD} placeholder="comma separated"
                    defaultValue={(form.applicability?.[key] || []).join(', ')}
                    onBlur={(e) => setApplicability(key, e.target.value.split(',')
                      .map((v) => v.trim()).filter(Boolean))} />
                </div>
              ))}
            </div>
            {departments.length > 0 && (
              <div>
                <span className={LABEL}>Departments</span>
                <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                  {departments.map((d) => {
                    const on = (form.applicability?.department_id || []).includes(d.id);
                    return (
                      <label key={d.id} className="flex items-center gap-1.5 text-[12px] text-[var(--text-main)]">
                        <input type="checkbox" checked={on}
                          onChange={() => setApplicability('department_id', on
                            ? form.applicability.department_id.filter((x) => x !== d.id)
                            : [...(form.applicability?.department_id || []), d.id])} />
                        {d.name}
                      </label>
                    );
                  })}
                </div>
              </div>
            )}
          </Group>

          <div>
            <label className={LABEL} htmlFor="fd-reason">Reason for {isNew ? 'adding' : 'change'}</label>
            <input id="fd-reason" {...bind('change_reason')} className={FIELD} placeholder="Recorded in the field's history" />
          </div>

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="submit" disabled={saving}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Saving…' : isNew ? 'Add as Draft' : 'Save field'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

const STATUS_COPY = {
  Approved: { verb: 'Approve', body: 'Signs the field off without switching it on. Someone other than its author approves; it starts taking values once activated.' },
  Active: { verb: 'Activate', body: 'The field appears on records straight away. Activation is recorded as the approval.' },
  Retired: { verb: 'Retire', body: 'The field stops accepting new values. Values already recorded are kept and stay visible.' },
};

/** Lifecycle change with its impact check — retiring shows how many records hold a value first. */
const StatusDialog = ({ def, to, onClose, onDone }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [usage, setUsage] = useState(null);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const copy = STATUS_COPY[to] || STATUS_COPY.Active;
  const verb = to === 'Active' && def.status === 'Retired' ? 'Re-activate' : copy.verb;

  useEffect(() => {
    if (to !== 'Retired') return;
    getFieldDefinitionUsage(def.module, def.code, scope)
      .then(({ data }) => setUsage(data?.records_with_value ?? 0))
      .catch(() => setUsage(-1));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const confirm = async () => {
    setSaving(true);
    try {
      const { data } = await setFieldDefinitionStatus(def.module, def.code,
        { status: to, reason: reason.trim() || null }, scope);
      showSuccess(`"${def.label}" is now ${data?.status || to}`);
      onDone(data);
    } catch (err) {
      showError(errText(err, 'Could not change the field status.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
        <div className="px-5 py-4 border-b border-[var(--border)]">
          <h2 className="text-[15px] font-bold text-[var(--text-main)]">{verb} “{def.label}”</h2>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5 font-mono">{def.module}.{def.code}</p>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-[12.5px] text-[var(--text-muted)]">{copy.body}</p>
          {to === 'Retired' && (
            <p className="p-3 rounded-lg bg-[var(--input-bg)] text-[12.5px] text-[var(--text-main)]">
              {usage === null ? 'Checking how many records use it…'
                : usage < 0 ? 'Could not check how many records use it.'
                : <><b>{usage}</b> {usage === 1 ? 'record holds' : 'records hold'} a value for this field.</>}
            </p>
          )}
          <div>
            <label className={LABEL} htmlFor="fs-reason">Reason</label>
            <input id="fs-reason" value={reason} onChange={(e) => setReason(e.target.value)} className={FIELD}
              placeholder="Recorded in the field's history" />
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose}
            className="h-9 px-3.5 rounded-lg border border-[var(--border)] text-[12.5px] font-bold text-[var(--text-muted)]">
            Cancel
          </button>
          <button type="button" onClick={confirm} disabled={saving || (to === 'Retired' && usage === null)}
            className={`h-9 px-3.5 rounded-lg text-white text-[12.5px] font-bold disabled:opacity-50 ${
              to === 'Retired' ? 'bg-[var(--accent-red)]' : 'bg-[var(--accent-indigo)]'}`}>
            {saving ? 'Saving…' : verb}
          </button>
        </div>
      </div>
    </div>
  );
};

const FieldHistory = ({ def }) => {
  const entries = [...(def.history || [])].reverse();
  return (
    <div className="space-y-2">
      <p className="text-[11.5px] text-[var(--text-muted)]">
        {def.created_by_name && <>Created by {def.created_by_name}. </>}
        {def.approved_by_name && <>Activated by {def.approved_by_name} {fmtDateTime(def.approved_at)}. </>}
        {def.effective_from && <>In force from {def.effective_from}{def.effective_to ? ` to ${def.effective_to}` : ''}.</>}
      </p>
      {entries.length === 0 ? (
        <p className="text-[12px] text-[var(--text-muted)]">No history recorded.</p>
      ) : (
        <ol className="space-y-1.5">
          {entries.map((h, i) => (
            <li key={i} className="text-[12px] text-[var(--text-main)]">
              <span className="text-[var(--text-muted)]">{fmtDateTime(h.at)}{h.by_name ? ` · ${h.by_name}` : ''}: </span>
              {!h.old ? 'Created' : Object.keys(h.new || {}).map((k) => (
                <span key={k} className="mr-2">
                  <b>{k}</b> {fmtValue(h.old?.[k])} → {fmtValue(h.new[k])}
                </span>
              ))}
              {h.reason && <span className="text-[var(--text-muted)]"> — “{h.reason}”</span>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
};

const FieldsPanel = ({ canWrite }) => {
  const { scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [module, setModule] = useState('employee');
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);        // null = closed, 'new', or a definition
  const [statusChange, setStatusChange] = useState(null);
  const [expanded, setExpanded] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await listFieldDefinitions({ ...scope, module });
      setRows(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(errText(err, 'Could not load the configurable fields.'));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, module]);

  useEffect(() => { load(); }, [load]);

  const remove = async (def) => {
    if (!window.confirm(`Delete the draft field "${def.label}"? This cannot be undone.`)) return;
    try {
      await deleteFieldDefinition(def.module, def.code, scope);
      showSuccess(`"${def.label}" deleted`);
      load();
    } catch (err) {
      showError(err?.response?.status === 409
        ? errText(err, 'This field is in use — retire it instead.')
        : errText(err, 'Could not delete the field.'));
    }
  };

  const sections = [...new Set(rows.map((r) => r.section).filter(Boolean))];
  const iconBtn = 'p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <BoardTabs label="Module" value={module} onChange={(m) => { setModule(m); setExpanded(null); }}
          tabs={[{ key: 'employee', label: 'Employee' }, { key: 'attendance', label: 'Attendance' }]} />
        {canWrite && (
          <button type="button" onClick={() => setEditing('new')}
            className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5">
            <Plus size={14} /> Add field
          </button>
        )}
      </div>
      <p className="text-[12px] text-[var(--text-muted)] max-w-3xl">
        A new field starts as <b>Draft</b> and appears on records only once activated. A field that
        holds values cannot be deleted — retire it, and its values stay on the record.
      </p>

      {loading ? (
        <HrmsLoading label="Loading fields…" />
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : rows.length === 0 ? (
        <HrmsEmpty icon={ListTree} title={`No ${module} fields yet`}
          hint={canWrite ? 'Add a field to capture something the standard record does not.' : undefined} />
      ) : (
        <div className="rounded-xl border border-[var(--border)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[760px]">
            <thead className="bg-[var(--input-bg)] text-[var(--text-muted)]">
              <tr>
                <th className={TH}>Field</th>
                <th className={TH}>Code</th>
                <th className={TH}>Type</th>
                <th className={TH}>Section</th>
                <th className={TH}>Mandatory</th>
                <th className={TH}>Status</th>
                <th className={TH}>Ver.</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <React.Fragment key={d.id || d.code}>
                  <tr className="border-t border-[var(--border)]">
                    <td className="px-4 py-2.5">
                      <div className="font-semibold text-[var(--text-main)]">{d.label}</div>
                      {d.help_text && <div className="text-[11.5px] text-[var(--text-muted)] truncate max-w-[240px]">{d.help_text}</div>}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-[12px] text-[var(--text-muted)]">{d.code}</td>
                    <td className="px-4 py-2.5 text-[var(--text-main)]">
                      {TYPE_LABEL[d.data_type] || d.data_type}
                      {d.data_type === 'master_lookup' && d.master_list && (
                        <span className="text-[11.5px] text-[var(--text-muted)]"> · {LIST_LABEL[d.master_list] || d.master_list}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-[var(--text-main)]">{d.section || <span className="text-[var(--text-muted)]">General</span>}</td>
                    <td className="px-4 py-2.5 text-[var(--text-main)]">{d.mandatory ? 'Yes' : '—'}</td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded-md text-[11px] font-bold ${STATUS_TONE[d.status] || STATUS_TONE.Retired}`}>
                        {d.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 tabular-nums text-[var(--text-muted)]">v{d.version || 1}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center justify-end gap-1">
                        <button type="button" title="History" onClick={() => setExpanded(expanded === d.code ? null : d.code)}
                          className={`${iconBtn} ${expanded === d.code ? 'text-[var(--accent-indigo)]' : ''}`}>
                          <History size={15} />
                        </button>
                        {canWrite && (
                          <>
                            <button type="button" title="Edit" onClick={() => setEditing(d)}
                              className={`${iconBtn} hover:text-[var(--accent-indigo)]`}>
                              <Pencil size={15} />
                            </button>
                            {d.status === 'Approved' && (
                              <button type="button" title="Activate" onClick={() => setStatusChange({ def: d, to: 'Active' })}
                                className={`${iconBtn} hover:text-[var(--accent-green)]`}>
                                <CheckCircle2 size={15} />
                              </button>
                            )}
                            {d.status === 'Draft' && (
                              <>
                                <button type="button" title="Approve" onClick={() => setStatusChange({ def: d, to: 'Approved' })}
                                  className={`${iconBtn} hover:text-[var(--accent-indigo)]`}>
                                  <ShieldCheck size={15} />
                                </button>
                                <button type="button" title="Activate" onClick={() => setStatusChange({ def: d, to: 'Active' })}
                                  className={`${iconBtn} hover:text-[var(--accent-green)]`}>
                                  <CheckCircle2 size={15} />
                                </button>
                                <button type="button" title="Delete draft" onClick={() => remove(d)}
                                  className={`${iconBtn} hover:text-[var(--accent-red)]`}>
                                  <Trash2 size={15} />
                                </button>
                              </>
                            )}
                            {d.status === 'Active' && (
                              <button type="button" title="Retire" onClick={() => setStatusChange({ def: d, to: 'Retired' })}
                                className={`${iconBtn} hover:text-[var(--accent-red)]`}>
                                <Archive size={15} />
                              </button>
                            )}
                            {d.status === 'Retired' && (
                              <button type="button" title="Re-activate" onClick={() => setStatusChange({ def: d, to: 'Active' })}
                                className={`${iconBtn} hover:text-[var(--accent-green)]`}>
                                <RotateCcw size={15} />
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                  {expanded === d.code && (
                    <tr className="bg-[var(--input-bg)]">
                      <td colSpan={8} className="px-4 py-3"><FieldHistory def={d} /></td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <FieldDefinitionModal
          module={editing === 'new' ? module : editing.module}
          initial={editing === 'new' ? null : editing}
          sections={sections}
          siblings={rows}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}

      {statusChange && (
        <StatusDialog def={statusChange.def} to={statusChange.to}
          onClose={() => setStatusChange(null)}
          onDone={() => { setStatusChange(null); load(); }} />
      )}
    </div>
  );
};

/** FRD §4: "Employee ID is created according to configured numbering". */
const IdFormatPanel = ({ canWrite }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [fmt, setFmt] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getEmployeeIdFormat(scope).then(({ data }) => setFmt(data)).catch(() => setFmt(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!fmt) return null;
  const year = new Date().getFullYear();
  const example = [String(fmt.prefix || '').toUpperCase(), ...(fmt.include_year ? [year] : []),
    '1'.padStart(Number(fmt.digits) || 3, '0')].join('-');

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await saveEmployeeIdFormat(
        { prefix: fmt.prefix, include_year: fmt.include_year, digits: Number(fmt.digits) }, scope);
      setFmt(data);
      showSuccess(`New employees are numbered like ${data.example}.`);
    } catch (err) {
      showError(errText(err, 'Could not save the employee ID format.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 space-y-3">
      <div>
        <h3 className="text-[13px] font-bold text-[var(--text-main)]">Employee ID format</h3>
        <p className="text-[11.5px] text-[var(--text-muted)]">
          Used when an employee is added without a code. Existing codes never change.
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
        <div>
          <label className={LABEL} htmlFor="idf-prefix">Prefix</label>
          <input id="idf-prefix" className={FIELD} value={fmt.prefix || ''} disabled={!canWrite}
            onChange={(e) => setFmt((f) => ({ ...f, prefix: e.target.value.toUpperCase() }))} />
        </div>
        <div>
          <label className={LABEL} htmlFor="idf-digits">Digits</label>
          <input id="idf-digits" type="number" min="1" max="8" className={FIELD} value={fmt.digits ?? 3}
            disabled={!canWrite} onChange={(e) => setFmt((f) => ({ ...f, digits: e.target.value }))} />
        </div>
        <Check label="Include the year" checked={!!fmt.include_year} disabled={!canWrite}
          onChange={(v) => setFmt((f) => ({ ...f, include_year: v }))} />
        <div className="text-[12px] text-[var(--text-main)]">
          Next looks like <b className="font-mono">{example}</b>
        </div>
      </div>
      {canWrite && (
        <button type="button" onClick={save} disabled={saving}
          className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-60">
          {saving ? 'Saving…' : 'Save format'}
        </button>
      )}
    </div>
  );
};

const EmployeeMasterSetup = () => {
  const { can, companyId } = useHrms();
  const [tab, setTab] = useState('lists');

  const canRead = can(CAP.EMPLOYEE_READ);
  const canWrite = can(CAP.EMPLOYEE_WRITE);

  const header = (
    <HrmsPageHeader
      icon={ListTree}
      title="Employee Master Setup"
      subtitle="Dropdown lists and configurable fields behind the employee record."
      actions={<HrmsScopeBar />}
    />
  );

  if (!canRead) {
    return (
      <div className="space-y-6">
        {header}
        <HrmsEmpty icon={ShieldAlert} title="No access" hint="You need permission to read employee records." />
      </div>
    );
  }
  if (!companyId) {
    return (
      <div className="space-y-6">
        {header}
        <HrmsEmpty icon={ShieldAlert} title="Select a company" hint="Choose a company above to configure it." />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {header}
      <BoardTabs value={tab} onChange={setTab}
        tabs={[{ key: 'lists', label: 'Dropdown lists' }, { key: 'fields', label: 'Configurable fields' }]} />
      {/* Keyed on the company so switching scope reloads rather than showing stale lists. */}
      {tab === 'lists'
        ? (
          <>
            <IdFormatPanel key={`id-${companyId}`} canWrite={canWrite} />
            <ListsPanel key={companyId} canWrite={canWrite} />
          </>
        )
        : <FieldsPanel key={companyId} canWrite={canWrite} />}
    </div>
  );
};

export default EmployeeMasterSetup;
