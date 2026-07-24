import React, { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, CalendarClock, Bell, Building2, Activity as ActivityIcon, Users2,
  UserCog, ClipboardList, RefreshCw, Save, Check, Search, ChevronDown,
} from 'lucide-react';
import api from '../../services/api';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import ReminderModal from './ReminderModal';

/**
 * Schedule Calendar modal — schedule an activity for a company, assign the internal
 * staff (SMOps) driving it and the company-side doers (by department), set a recurrence
 * and reminders. Saves through POST /calendar/events so it reuses the existing
 * recurrence engine, the on-save notification email, and the reminder scheduler.
 */

// No backend Activity catalogue exists yet — this is the editable source of truth.
const ACTIVITIES = [
  'Org Structure Update',
  'DRM & KPI data available',
  'Calendar Discipline',
  'WRM',
  'Monthly Management Review (MMR)',
  'One pager Memo',
  'Action Closure Review',
  'Accountability & Ownership Rating',
  'Culture Rating',
  'RRO',
  'Implementation Update Feedback',
  'Team Engagement Index',
  'Customer Satisfaction Index',
  'Organization Result Matrix',
];

// Client-side departments the doers are grouped by (matches the user.department values).
const DEPARTMENTS = ['HOD', 'MD', 'HR', 'IMPLEMENTOR'];

// Recurrence label → backend `repeat` value (see calendar_event.py / _next_occurrence).
const RECURRENCE = [
  { label: 'One-time', repeat: 'Does not repeat' },
  { label: 'Daily',    repeat: 'Daily' },
  { label: 'Weekly',   repeat: 'Weekly' },
  { label: 'Monthly',  repeat: 'Monthly' },
  { label: 'Yearly',   repeat: 'Annually' },
];

const emptyForm = () => ({
  title: '',
  time: '',
  activity: '',
  companyId: '',
  recurrence: 'One-time',
  planDate: '',
  staffIds: [],
  departments: [],
  doerIds: [],
  comment: '',
  reminders: [],
});

const uid = (u) => String(u?._id || u?.id || '');
const displayName = (u) => u?.full_name || [u?.first_name, u?.last_name].filter(Boolean).join(' ') || u?.email || 'Unknown';

/** Searchable single-select: a value button that opens a filterable option list. */
const SearchableSelect = ({ options, value, onChange, placeholder }) => {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const selected = options.find((o) => o.id === value);
  const ql = q.trim().toLowerCase();
  const filtered = options.filter((o) => o.label.toLowerCase().includes(ql));

  return (
    <div ref={ref} className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl bg-gray-50 border border-gray-200 text-[13px] font-semibold outline-none focus:border-indigo-500 transition-all">
        <span className={selected ? 'text-gray-800 truncate' : 'text-gray-400'}>{selected ? selected.label : (placeholder || '— Select —')}</span>
        <ChevronDown size={15} className="text-gray-400 shrink-0" />
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-full rounded-xl bg-white border border-gray-200 shadow-xl overflow-hidden">
          <div className="relative p-2 border-b border-gray-100">
            <Search size={13} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" />
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…"
              className="w-full pl-8 pr-3 py-2 rounded-lg bg-gray-50 border border-gray-200 text-[12px] font-semibold text-gray-800 outline-none focus:border-indigo-500" />
          </div>
          <div className="max-h-52 overflow-y-auto no-scrollbar py-1">
            {filtered.length === 0 && <div className="px-3 py-2 text-[11px] text-gray-400 font-medium">No matches.</div>}
            {filtered.map((o) => (
              <button key={o.id} type="button" onClick={() => { onChange(o.id); setOpen(false); setQ(''); }}
                className={`w-full flex items-center justify-between px-3 py-2 text-[12px] font-semibold hover:bg-gray-50 transition-all ${o.id === value ? 'text-indigo-600' : 'text-gray-700'}`}>
                <span className="truncate">{o.label}</span>
                {o.id === value && <Check size={14} className="text-indigo-600 shrink-0" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

/** Searchable multi-select: selected items as removable chips + a filterable dropdown. */
const SearchableMultiSelect = ({ options, selectedIds, onToggle, placeholder, disabled, accent = 'indigo' }) => {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  if (disabled) {
    return <div className="w-full px-3.5 py-2.5 rounded-xl bg-gray-50 border border-gray-200 text-[13px] font-medium text-gray-400">{placeholder}</div>;
  }

  const selected = options.filter((o) => selectedIds.includes(o.id));
  const ql = q.trim().toLowerCase();
  const filtered = options.filter((o) => o.label.toLowerCase().includes(ql));
  const chipCls = accent === 'violet' ? 'bg-violet-600 border-violet-600' : 'bg-indigo-600 border-indigo-600';
  const checkCls = accent === 'violet' ? 'text-violet-600' : 'text-indigo-600';

  return (
    <div ref={ref} className="relative">
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {selected.map((o) => (
            <span key={o.id} className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-bold text-white border ${chipCls}`}>
              {o.label}
              <X size={11} className="cursor-pointer opacity-80 hover:opacity-100" onClick={() => onToggle(o.id)} />
            </span>
          ))}
        </div>
      )}
      <div className="relative">
        <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          placeholder={selected.length ? 'Add more…' : (placeholder || 'Search…')}
          className="w-full pl-9 pr-8 py-2.5 rounded-xl bg-gray-50 border border-gray-200 text-[13px] font-semibold text-gray-800 outline-none focus:border-indigo-500 transition-all"
        />
        <ChevronDown size={15} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 cursor-pointer" onClick={() => setOpen((o) => !o)} />
      </div>
      {open && (
        <div className="absolute z-30 mt-1 w-full max-h-56 overflow-y-auto no-scrollbar rounded-xl bg-white border border-gray-200 shadow-xl py-1">
          {filtered.length === 0 && <div className="px-3 py-2 text-[11px] text-gray-400 font-medium">No matches.</div>}
          {filtered.map((o) => {
            const on = selectedIds.includes(o.id);
            return (
              <button key={o.id} type="button" onClick={() => onToggle(o.id)}
                className={`w-full flex items-center justify-between px-3 py-2 text-[12px] font-semibold hover:bg-gray-50 transition-all ${on ? checkCls : 'text-gray-700'}`}>
                <span className="truncate">{o.label}</span>
                {on && <Check size={14} className={checkCls} />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

const ScheduleCalendarModal = ({ isOpen, onClose, onSaved }) => {
  const { showSuccess, showError } = useNotification();
  const { user } = useAuth();
  // Client-side users schedule only for their OWN company and don't assign internal staff.
  const isClient = ['clientadmin', 'clientuser'].includes(user?.role);

  const [form, setForm] = useState(emptyForm());
  const [companyName, setCompanyName] = useState('');
  const [companies, setCompanies] = useState([]);
  const [staff, setStaff] = useState([]);
  const [companyUsers, setCompanyUsers] = useState([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [showReminders, setShowReminders] = useState(false);
  const [saving, setSaving] = useState(false);

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  // On open: staff load all companies + the internal-staff picker; client users are
  // locked to their own company (no company list, no staff picker — both are staff-only).
  useEffect(() => {
    if (!isOpen) return;
    const base = emptyForm();
    if (isClient && user?.company_id) base.companyId = String(user.company_id);
    setForm(base);
    setCompanyUsers([]);
    setCompanyName('');
    let alive = true;
    (async () => {
      try {
        if (isClient) {
          if (user?.company_id) {
            const co = await api.get(`/companies/${user.company_id}`);
            if (alive) setCompanyName(co.data?.name || user?.company_name || 'Your Company');
          }
        } else {
          const [coRes, stRes] = await Promise.all([
            api.get('/companies'),
            api.get('/tasks/assignable-users'),
          ]);
          if (!alive) return;
          setCompanies(coRes.data || []);
          setStaff(stRes.data || []);
        }
      } catch (err) {
        if (alive) showError(err.response?.data?.detail || 'Failed to load form data');
      }
    })();
    return () => { alive = false; };
  }, [isOpen, isClient, user, showError]);

  // Load the selected company's users (the doer pool) when the company changes.
  useEffect(() => {
    if (!form.companyId) { setCompanyUsers([]); return; }
    let alive = true;
    (async () => {
      setLoadingUsers(true);
      try {
        const res = await api.get(`/companies/${form.companyId}/users?active_only=true`);
        if (!alive) return;
        setCompanyUsers(res.data || []);
      } catch (err) {
        if (alive) showError(err.response?.data?.detail || 'Failed to load company users');
      } finally {
        if (alive) setLoadingUsers(false);
      }
    })();
    return () => { alive = false; };
  }, [form.companyId, showError]);

  const inDept = (u, dept) => (u?.department || '').toString().toUpperCase() === dept.toUpperCase();

  // Doers available for the currently-selected departments (or all if none chosen).
  const doerPool = useMemo(() => {
    if (!form.departments.length) return companyUsers;
    return companyUsers.filter((u) => form.departments.some((d) => inDept(u, d)));
  }, [companyUsers, form.departments]);

  const toggleStaff = (id) => set({ staffIds: form.staffIds.includes(id) ? form.staffIds.filter((s) => s !== id) : [...form.staffIds, id] });
  const toggleDoer = (id) => set({ doerIds: form.doerIds.includes(id) ? form.doerIds.filter((s) => s !== id) : [...form.doerIds, id] });

  const toggleDept = (dept) => {
    const has = form.departments.includes(dept);
    const nextDepts = has ? form.departments.filter((d) => d !== dept) : [...form.departments, dept];
    const matchIds = companyUsers.filter((u) => inDept(u, dept)).map(uid);
    const nextDoers = has
      ? form.doerIds.filter((id) => !matchIds.includes(id))       // removing dept → drop its doers
      : [...new Set([...form.doerIds, ...matchIds])];             // adding dept → pre-select its doers
    set({ departments: nextDepts, doerIds: nextDoers });
  };

  const buildTimes = () => {
    if (!form.time) {
      const startISO = new Date(`${form.planDate}T00:00:00`).toISOString();
      return { start: startISO, end: startISO, all_day: true };
    }
    const startDt = new Date(`${form.planDate}T${form.time}:00`);
    const endDt = new Date(startDt.getTime() + 60 * 60 * 1000);
    return { start: startDt.toISOString(), end: endDt.toISOString(), all_day: false };
  };

  const handleSave = async () => {
    if (!form.title.trim()) return showError('Enter a title');
    if (!form.activity) return showError('Select an activity');
    if (!form.companyId) return showError('Select a company');
    if (!form.planDate) return showError('Pick a plan date');

    const rec = RECURRENCE.find((r) => r.label === form.recurrence) || RECURRENCE[0];
    const { start, end, all_day } = buildTimes();
    const recurring = rec.repeat !== 'Does not repeat';
    let repeat_end_date = '';
    if (recurring) {
      const d = new Date(form.planDate);
      d.setFullYear(d.getFullYear() + 1);
      repeat_end_date = d.toISOString().slice(0, 10);
    }

    const assigned_member_ids = [...new Set([...form.staffIds, ...form.doerIds])];
    const reminders = (form.reminders || []).map((r) => ({ ...r, parent_type: 'event' }));

    // Snapshot names/company so any assignee can view details without extra lookups.
    const coName = isClient ? companyName : (companies.find((c) => String(c._id || c.id) === form.companyId)?.name || '');
    const smops = staff.filter((u) => form.staffIds.includes(uid(u))).map((u) => ({ id: uid(u), name: displayName(u) }));
    const doers = companyUsers.filter((u) => form.doerIds.includes(uid(u))).map((u) => ({ id: uid(u), name: displayName(u), department: u.department || '' }));

    const payload = {
      title: form.title.trim(),
      type: 'event',
      activity: form.activity,
      company_id: form.companyId,
      company_name: coName,
      session_type: form.activity,
      start, end, all_day,
      status: 'schedule',
      category: 'General',
      repeat: rec.repeat,
      repeat_end_date,
      repeat_interval: 1,
      assigned_departments: form.departments,
      assigned_member_ids,
      additional_details: form.comment,
      reminders,
      activity_meta: { company_name: coName, departments: form.departments, smops, doers },
    };

    setSaving(true);
    try {
      await api.post('/calendar/events', payload);
      showSuccess('Schedule created — invites & reminders will be sent.');
      onSaved?.();
      onClose();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save schedule');
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  const Label = ({ children, req }) => (
    <label className="block text-[11px] font-black text-gray-500 uppercase tracking-wider mb-1.5">
      {children}{req && <span className="text-indigo-500"> *</span>}
    </label>
  );
  const field = 'w-full px-3.5 py-2.5 rounded-xl bg-gray-50 border border-gray-200 text-[13px] font-semibold text-gray-800 outline-none focus:border-indigo-500 transition-all';

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[250] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}
          className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative bg-white w-full max-w-2xl rounded-[28px] shadow-2xl overflow-hidden flex flex-col max-h-[92vh]" style={{ color: '#1a202c' }}>

          {/* Header */}
          <div className="px-6 py-5 flex items-center justify-between text-white bg-gradient-to-r from-indigo-600 to-violet-500">
            <div className="flex items-center gap-2.5">
              <CalendarClock size={20} />
              <h3 className="text-[15px] font-black tracking-tight">Schedule Activity</h3>
            </div>
            <button onClick={onClose} className="p-1.5 hover:bg-white/20 rounded-full transition-all"><X size={20} /></button>
          </div>

          {/* Body */}
          <div className="p-6 overflow-y-auto no-scrollbar space-y-5">
            <div>
              <Label req>Title</Label>
              <input value={form.title} onChange={(e) => set({ title: e.target.value })} placeholder="Enter title" className={field} />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <Label>Time</Label>
                <input type="time" value={form.time} onChange={(e) => set({ time: e.target.value })} className={field} />
              </div>
              <div>
                <Label req><ActivityIcon size={11} className="inline mr-1" />Activity</Label>
                <SearchableSelect
                  options={ACTIVITIES.map((a) => ({ id: a, label: a }))}
                  value={form.activity}
                  onChange={(a) => set({ activity: a, ...(form.title.trim() ? {} : { title: a }) })}
                  placeholder="— Select —"
                />
              </div>
              <div>
                <Label req><Building2 size={11} className="inline mr-1" />Company Name</Label>
                {isClient ? (
                  <div className={`${field} truncate`}>{companyName || 'Your Company'}</div>
                ) : (
                  <SearchableSelect
                    options={companies.map((c) => ({ id: String(c._id || c.id), label: c.name }))}
                    value={form.companyId}
                    onChange={(id) => set({ companyId: id, doerIds: [], departments: [] })}
                    placeholder="— Select —"
                  />
                )}
              </div>
              <div>
                <Label req><RefreshCw size={11} className="inline mr-1" />Recurrence</Label>
                <select value={form.recurrence} onChange={(e) => set({ recurrence: e.target.value })} className={field}>
                  {RECURRENCE.map((r) => <option key={r.label} value={r.label}>{r.label}</option>)}
                </select>
              </div>
              <div>
                <Label req>Plan Date</Label>
                <input type="date" value={form.planDate} onChange={(e) => set({ planDate: e.target.value })} className={field} />
              </div>
              {!isClient && (
                <div>
                  <Label req><UserCog size={11} className="inline mr-1" />Staff Assigner (multi-select)</Label>
                  <SearchableMultiSelect
                    disabled={!form.companyId}
                    placeholder={!form.companyId ? 'Select a company first' : 'Search staff…'}
                    options={staff.map((u) => ({ id: uid(u), label: displayName(u) }))}
                    selectedIds={form.staffIds}
                    onToggle={toggleStaff}
                    accent="indigo"
                  />
                  <p className="text-[10px] text-gray-400 font-medium mt-1">Internal staff who will drive this activity.</p>
                </div>
              )}
            </div>

            {/* Departments */}
            <div>
              <Label req><Users2 size={11} className="inline mr-1" />Departments (multi-select)</Label>
              <div className="flex flex-wrap gap-2">
                {DEPARTMENTS.map((d) => {
                  const on = form.departments.includes(d);
                  return (
                    <button key={d} type="button" onClick={() => toggleDept(d)} disabled={!form.companyId}
                      className={`px-3.5 py-1.5 rounded-xl text-[11px] font-black border transition-all disabled:opacity-40 ${on ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-gray-500 border-gray-200 hover:border-indigo-400'}`}>
                      {d}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Company Assigners (doers) */}
            <div>
              <Label>Company Assigners (doers) (multi-select)</Label>
              <SearchableMultiSelect
                disabled={!form.companyId}
                placeholder={!form.companyId ? 'Select company & departments' : (loadingUsers ? 'Loading…' : 'Search doers…')}
                options={doerPool.map((u) => ({ id: uid(u), label: `${displayName(u)}${u.department ? ` · ${u.department}` : ''}` }))}
                selectedIds={form.doerIds}
                onToggle={toggleDoer}
                accent="violet"
              />
            </div>

            <div>
              <Label>Comment</Label>
              <textarea rows={3} value={form.comment} onChange={(e) => set({ comment: e.target.value })} placeholder="Optional notes…" className={`${field} resize-y`} />
            </div>

            {/* Reminders */}
            <div className="p-4 rounded-2xl border border-dashed border-orange-200 bg-orange-50/40">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Bell size={14} className="text-orange-500" />
                  <span className="text-[10px] font-black uppercase text-orange-600 tracking-widest">Reminders ({form.reminders.length})</span>
                </div>
                <button type="button" onClick={() => setShowReminders(true)}
                  className="px-3 py-1.5 bg-white border border-orange-200 text-orange-600 rounded-lg text-[10px] font-black hover:bg-orange-500 hover:text-white transition-all">
                  {form.reminders.length ? 'MANAGE' : '+ ADD REMINDER'}
                </button>
              </div>
              {form.reminders.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-3">
                  {form.reminders.map((r, i) => (
                    <span key={i} className="px-2 py-1 bg-white border border-gray-100 rounded text-[9px] font-bold text-gray-500">
                      {r.reminder_type === 'whatsapp' ? '💬' : r.reminder_type === 'both' ? '⚡' : '📧'} {r.offset_minutes}m {r.timing_type}
                    </span>
                  ))}
                </div>
              )}
              <p className="text-[10px] text-gray-400 font-medium mt-2">Before/After reminders apply to every occurrence. A schedule email is sent on save; reminder emails at their time.</p>
            </div>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-gray-100 flex items-center justify-end gap-3 bg-gray-50">
            <button onClick={onClose} className="px-5 py-2.5 rounded-xl border border-gray-200 text-gray-600 text-[12px] font-black hover:bg-gray-100 transition-all">Cancel</button>
            <button onClick={handleSave} disabled={saving}
              className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-500 text-white text-[12px] font-black shadow-lg shadow-indigo-500/30 hover:scale-[1.02] active:scale-95 transition-all disabled:opacity-60">
              {saving ? <RefreshCw size={15} className="animate-spin" /> : <Save size={15} />}
              {saving ? 'Saving…' : 'Save Schedule'}
            </button>
          </div>
        </motion.div>
      </div>

      <ReminderModal
        isOpen={showReminders}
        onClose={() => setShowReminders(false)}
        reminders={form.reminders}
        onApply={(reminders) => set({ reminders })}
      />
    </AnimatePresence>
  );
};

export default ScheduleCalendarModal;
