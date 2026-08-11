import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RefreshCw, Mail, Plus, Pencil, X, ShieldAlert, CheckCircle2, AlertTriangle, Filter,
  MessageCircle,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, TableShell, usePaged, Pager,
} from '../../common/dashboardKit';
import {
  getMailTemplates, upsertMailTemplate, getActivities,
  getWhatsappTemplates, upsertWhatsappTemplate, getWhatsappVariables, setTemplateStatus,
} from '../../../../services/tpmsApi';
import { useAuth } from '../../../../context/AuthContext';
import { isTpmsAdmin } from '../../access';

/* ─────────────────────────────────────────────────────────────
   Admin Panel ▸ Mail Template Management (M12).

   Transactional mail templates keyed by (activity, side, event). Saving is an
   upsert — creating and editing hit the same endpoint. The catch-all '*' activity
   is the fallback used when no activity-specific template exists.

   Route: /tpms/admin/mail-templates   (wired separately)
   ───────────────────────────────────────────────────────────── */

// Alias so the animated element is a plain JSX identifier (keeps `motion` counted
// as used by no-unused-vars, which doesn't track `motion.div` member expressions).
const MotionDiv = motion.div;

const SIDE_OPTIONS = ['staff', 'company'];
const EVENT_OPTIONS = ['schedule', 'reminder', 'reschedule', 'cancel', 'completed', 'form_summary', 'form_scorecard'];

// Variables available to the two post-submission form emails (event = form_summary / form_scorecard).
const FORM_SUMMARY_VARS = ['Recipient_Name', 'HOD_Name', 'Company_Name', 'Month', 'Form_Type', 'Submitted_On', 'Total_Ratings', 'Response_Table'];
const FORM_SCORECARD_VARS = ['Recipient_Name', 'Employee_Name', 'Company_Name', 'Month', 'Form_Type', 'Average_Rating', 'Total_Questions', 'Score_Table'];

const errMsg = (e, fallback) => e?.response?.data?.detail || fallback;

/** A blank form — also the shape used to reset the modal. */
const EMPTY_FORM = {
  activity: '*',
  side: 'staff',
  event: 'schedule',
  subject: '',
  body_html: '',
  // WhatsApp-only fields (ignored when authoring an email template):
  meta_template_name: '',
  language: 'en',
  variables: [],
  active: true,
};

const TONE = {
  green:  { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  indigo: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  orange: { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  muted:  { c: 'var(--text-muted)',    bg: 'var(--input-bg)',         bd: 'var(--border)' },
};

const Pill = ({ label, tone = 'muted' }) => {
  const s = TONE[tone] || TONE.muted;
  return (
    <span className="inline-flex items-center text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border whitespace-nowrap"
      style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      {label}
    </span>
  );
};

const SIDE_TONE = { staff: 'indigo', company: 'orange' };

const CHANNELS = [
  { id: 'mail', label: 'Email', icon: Mail },
  { id: 'whatsapp', label: 'WhatsApp', icon: MessageCircle },
];

/**
 * Active/Inactive switch for one template row — the same control the ERP module toggles use.
 * Purely presentational: the parent owns the confirmation step, so a stray click can never
 * change a notification's status on its own.
 */
const StatusToggle = ({ active, disabled, onRequest }) => (
  <button
    type="button"
    role="switch"
    aria-checked={active}
    aria-label={`Notification ${active ? 'active' : 'inactive'}`}
    disabled={disabled}
    onClick={onRequest}
    title={disabled ? 'Only Admin / Super Admin can change notification status'
      : active ? 'Deactivate this notification' : 'Activate this notification'}
    className="inline-flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
  >
    <span className="relative inline-flex w-9 h-5 rounded-full transition-colors shrink-0"
      style={{ background: active ? 'var(--accent-green)' : 'var(--border)' }}>
      <span className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all"
        style={{ left: active ? '18px' : '2px' }} />
    </span>
    <span className="text-[10px] font-bold uppercase tracking-widest w-12 text-left"
      style={{ color: active ? 'var(--accent-green)' : 'var(--text-muted)' }}>
      {active ? 'Active' : 'Inactive'}
    </span>
  </button>
);

/** Confirmation step required before any status change (both directions). */
const ConfirmStatusModal = ({ target, channelLabel, busy, onCancel, onConfirm }) => {
  const turningOff = target.active !== false;
  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={busy ? undefined : onCancel} />
      <MotionDiv
        role="dialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-[var(--border)]">
          <span className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={turningOff
              ? { background: 'var(--accent-orange-bg)', color: 'var(--accent-orange)' }
              : { background: 'var(--accent-green-bg)', color: 'var(--accent-green)' }}>
            {turningOff ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
          </span>
          <h3 className="text-[15px] font-extrabold tracking-tight">
            {turningOff ? 'Deactivate notification?' : 'Activate notification?'}
          </h3>
        </div>
        <div className="px-5 py-4 space-y-3">
          <div className="rounded-lg bg-[var(--input-bg)] border border-[var(--border)] px-3.5 py-2.5 text-[12.5px]">
            <div className="font-bold">{target.activity || '*'}</div>
            <div className="text-[var(--text-muted)] mt-0.5">
              {channelLabel} · {target.side || '—'} · {target.event || '—'}
            </div>
          </div>
          <p className="text-[13px] text-[var(--text-main)] leading-relaxed">
            {turningOff
              ? `This ${channelLabel} notification will stop being sent. Everything else keeps working exactly as now — activities still schedule, complete and escalate, scores still calculate. Only the message is suppressed.`
              : `This ${channelLabel} notification will start being sent again to its usual recipients.`}
          </p>
        </div>
        <div className="px-5 py-3 border-t border-[var(--border)] flex items-center justify-end gap-2">
          <button type="button" onClick={onCancel} disabled={busy}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Cancel
          </button>
          <button type="button" onClick={onConfirm} disabled={busy}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-60"
            style={{ background: turningOff ? 'var(--accent-orange)' : 'var(--accent-green)' }}>
            {busy ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
            {busy ? 'Saving…' : turningOff ? 'Deactivate' : 'Activate'}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

/* Shared field styles for the modal. */
const inputCls =
  'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] transition-colors';
const labelCls = 'text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]';

const Field = ({ label, children, required }) => (
  <label className="flex flex-col gap-1.5">
    <span className={labelCls}>{label}{required && <span className="text-[var(--accent-red)]"> *</span>}</span>
    {children}
  </label>
);

const Select = ({ value, onChange, options }) => (
  <select value={value} onChange={(e) => onChange(e.target.value)} className={`${inputCls} cursor-pointer`}>
    {options.map((o) => <option key={o} value={o}>{o}</option>)}
  </select>
);

/** Seed the form from a template row (edit) or a blank (add). */
const seedForm = (editing) => (editing
  ? {
    activity: editing.activity || '*',
    side: SIDE_OPTIONS.includes(editing.side) ? editing.side : 'staff',
    event: EVENT_OPTIONS.includes(editing.event) ? editing.event : 'schedule',
    subject: editing.subject || '',
    body_html: editing.body_html || '',
    meta_template_name: editing.meta_template_name || editing.name || '',
    language: editing.language || 'en',
    variables: Array.isArray(editing.variables) ? editing.variables : [],
    active: editing.active !== false,
  }
  : EMPTY_FORM);

/**
 * Add / Edit modal — reused for both create and update flows (both upsert).
 * Mounted only while open (via a keyed parent), so state seeds cleanly from
 * props on mount — no effect-driven syncing needed.
 */
const TemplateModal = ({ editing, activityOptions, channel = 'mail', variableFields = [], onClose, onSubmit }) => {
  const [form, setForm] = useState(() => seedForm(editing));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const isWa = channel === 'whatsapp';
  // The two post-submission form emails expose their own variable set (Response_Table, etc.).
  const isForm = form.event === 'form_summary' || form.event === 'form_scorecard';
  const paletteVars = form.event === 'form_summary' ? FORM_SUMMARY_VARS
    : form.event === 'form_scorecard' ? FORM_SCORECARD_VARS
    : variableFields;
  const addVar = () => set('variables', [...(form.variables || []), '']);
  const setVar = (i, v) => set('variables', (form.variables || []).map((x, j) => (j === i ? v : x)));
  const delVar = (i) => set('variables', (form.variables || []).filter((_, j) => j !== i));

  // Insert a {{placeholder}} into the email body at the cursor.
  const insertBodyVar = (v) => {
    const token = `{{${v}}}`;
    const ta = document.getElementById('mail-body');
    if (!ta) { set('body_html', (form.body_html || '') + token); return; }
    const start = ta.selectionStart ?? (form.body_html || '').length;
    const end = ta.selectionEnd ?? start;
    set('body_html', (form.body_html || '').slice(0, start) + token + (form.body_html || '').slice(end));
    requestAnimationFrame(() => { ta.focus(); const p = start + token.length; ta.setSelectionRange(p, p); });
  };

  const submit = async (e) => {
    e.preventDefault();
    if (isWa && !form.meta_template_name.trim()) { setErr('Meta template name is required.'); return; }
    if (!isWa && !form.subject.trim()) { setErr('Subject is required.'); return; }
    setSaving(true);
    setErr('');
    try {
      const base = { ...form, activity: form.activity.trim() || '*' };
      await onSubmit(isWa
        ? { ...base, meta_template_name: form.meta_template_name.trim(),
            language: (form.language || 'en').trim() || 'en',
            variables: (form.variables || []).filter(Boolean) }
        : { ...base, subject: form.subject.trim(), body_html: form.body_html });
    } catch (ex) {
      setErr(errMsg(ex, 'Failed to save template. Please try again.'));
      setSaving(false);
    }
  };

  return (
    <MotionDiv
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden max-h-[90vh] flex flex-col">
        {/* header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              {editing ? <Pencil size={16} /> : <Plus size={16} />}
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">{editing ? 'Edit Template' : 'Add Template'}</h3>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={submit} className="px-5 py-4 space-y-4 overflow-y-auto">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Field label="Activity" required>
              <Select value={form.activity} onChange={(v) => set('activity', v)} options={activityOptions} />
            </Field>
            <Field label="Side" required>
              <Select value={form.side} onChange={(v) => set('side', v)} options={SIDE_OPTIONS} />
            </Field>
            <Field label="Event" required>
              <Select value={form.event} onChange={(v) => set('event', v)} options={EVENT_OPTIONS} />
            </Field>
          </div>

          {!isWa && (
            <>
              <Field label="Subject" required>
                <input type="text" value={form.subject} onChange={(e) => set('subject', e.target.value)}
                  placeholder="e.g. [Reminder] {{Activity}} due in 2 days | {{Company_Name}}" className={inputCls} autoFocus />
              </Field>

              <Field label="Body (HTML)">
                <textarea id="mail-body" value={form.body_html} onChange={(e) => set('body_html', e.target.value)}
                  placeholder="<p>Hello {{Recipient_Name}}, …</p>  — use {{double-brace}} placeholders" rows={7}
                  className={`${inputCls} font-mono text-[12px] leading-relaxed resize-y`} />
              </Field>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wide">Insert a variable</label>
                  <span className="text-[11px] text-[var(--text-muted)]">click to add at the cursor</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {paletteVars.map((v) => (
                    <button key={v} type="button" onClick={() => insertBodyVar(v)}
                      className={`font-mono text-[11px] px-2 py-1 rounded-md border transition-colors ${(v === 'Form_Link' || v === 'Response_Table' || v === 'Score_Table')
                        ? 'border-[var(--accent-indigo-border)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] font-bold'
                        : 'border-[var(--border)] bg-[var(--input-bg)] text-[var(--text-main)] hover:border-[var(--accent-indigo)]'}`}>
                      {`{{${v}}}`}
                    </button>
                  ))}
                </div>
                {isForm ? (
                  <p className="text-[11.5px] text-[var(--text-muted)] mt-2 leading-relaxed">
                    This mail is sent <b>after a form is submitted</b>.
                    {form.event === 'form_summary'
                      ? <> Use <b style={{ color: 'var(--accent-indigo)' }}>{'{{Response_Table}}'}</b> for the full ratings grid (HOD/MD summary).</>
                      : <> Use <b style={{ color: 'var(--accent-indigo)' }}>{'{{Score_Table}}'}</b> and <b style={{ color: 'var(--accent-indigo)' }}>{'{{Average_Rating}}'}</b> for the employee's scorecard.</>}
                    &nbsp;Leave the body empty to use the built-in default layout.
                  </p>
                ) : (
                  <p className="text-[11.5px] text-[var(--text-muted)] mt-2 leading-relaxed">
                    <b style={{ color: 'var(--accent-indigo)' }}>{'{{Form_Link}}'}</b> = the recipient's own unique,
                    single-use link (valid for that month only). For a <b>two-form</b> activity like
                    Accountability&nbsp;&amp;&nbsp;Ownership, use <b style={{ color: 'var(--accent-indigo)' }}>{'{{Form_Link_2}}'}</b>
                    for the second form, or <b style={{ color: 'var(--accent-indigo)' }}>{'{{Form_Links}}'}</b> to drop a
                    ready-made block of <em>all</em> the recipient's links at once. Put these in the <b>schedule</b> email.
                  </p>
                )}
              </div>
            </>
          )}

          {isWa && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="sm:col-span-2">
                  <Field label="Meta Template Name" required>
                    <input type="text" value={form.meta_template_name}
                      onChange={(e) => set('meta_template_name', e.target.value)}
                      placeholder="e.g. tpms_schedule_staff" className={`${inputCls} font-mono`} autoFocus />
                  </Field>
                </div>
                <Field label="Language">
                  <input type="text" value={form.language}
                    onChange={(e) => set('language', e.target.value)} placeholder="en" className={inputCls} />
                </Field>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wide">Body Parameters (order = {'{{1}}, {{2}}…'})</label>
                  <button type="button" onClick={addVar} className="text-[11px] font-bold text-[var(--accent-indigo)] hover:underline">+ Add Parameter</button>
                </div>
                {(form.variables || []).length === 0 && (
                  <p className="text-[11px] text-[var(--text-muted)] italic">No parameters mapped — add one per {'{{n}}'} in your Meta-approved template.</p>
                )}
                <div className="space-y-2">
                  {(form.variables || []).map((v, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="text-[11px] font-black text-[var(--accent-indigo)] w-9 shrink-0 font-mono">{`{{${i + 1}}}`}</span>
                      <select value={v} onChange={(e) => setVar(i, e.target.value)} className={`${inputCls} flex-1`}>
                        <option value="">— select field —</option>
                        {variableFields.map((f) => <option key={f} value={f}>{f}</option>)}
                      </select>
                      <button type="button" onClick={() => delVar(i)} className="text-[var(--text-muted)] hover:text-[var(--accent-red)] p-1"><X size={15} /></button>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          <Field label="Active">
            <button type="button" onClick={() => set('active', !form.active)}
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-bold transition-colors hover:border-[var(--accent-indigo)] w-fit">
              <span className="relative inline-flex w-9 h-5 rounded-full transition-colors"
                style={{ background: form.active ? 'var(--accent-green)' : 'var(--border)' }}>
                <span className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all"
                  style={{ left: form.active ? '18px' : '2px' }} />
              </span>
              <span style={{ color: form.active ? 'var(--accent-green)' : 'var(--text-muted)' }}>
                {form.active ? 'Active' : 'Inactive'}
              </span>
            </button>
          </Field>

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} disabled={saving}
              className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
              Cancel
            </button>
            <button type="submit" disabled={saving}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-60">
              {saving ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              {saving ? 'Saving…' : editing ? 'Save Changes' : 'Save Template'}
            </button>
          </div>
        </form>
      </MotionDiv>
    </MotionDiv>
  );
};

const MailTemplateAdmin = () => {
  const { user } = useAuth();
  const admin = isTpmsAdmin(user);

  const [templates, setTemplates] = useState([]);
  const [activities, setActivities] = useState([]);
  const [filter, setFilter] = useState(''); // '' = all, '*' = catch-all, else activity name
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  // Which channel's templates are listed. Email is authored here; WhatsApp is listed so its
  // Active switch has a home (authoring against Meta-approved names stays out of scope).
  const [channel, setChannel] = useState('mail');
  // The row awaiting confirmation before its status flips. null = no dialog open.
  const [confirmTarget, setConfirmTarget] = useState(null);
  const [statusSaving, setStatusSaving] = useState(false);
  // Fields a WhatsApp template's positional params can map to (loaded once, on demand).
  const [variableFields, setVariableFields] = useState([]);

  const channelLabel = channel === 'whatsapp' ? 'WhatsApp' : 'Email';

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const fetcher = channel === 'whatsapp' ? getWhatsappTemplates : getMailTemplates;
      const res = await fetcher(filter || undefined);
      const list = res?.data?.templates;
      setTemplates(Array.isArray(list) ? list : []);
    } catch (e) {
      setError(errMsg(e, `Failed to load ${channel === 'whatsapp' ? 'WhatsApp' : 'mail'} templates.`));
    } finally {
      setLoading(false);
    }
  }, [filter, channel]);

  /** Apply the confirmed status change, then refresh so the row reflects the stored value. */
  const applyStatusChange = useCallback(async () => {
    if (!confirmTarget) return;
    setStatusSaving(true);
    try {
      await setTemplateStatus(channel, confirmTarget._id, confirmTarget.active === false);
      setConfirmTarget(null);
      await load();
    } catch (e) {
      setError(errMsg(e, 'Failed to update notification status.'));
      setConfirmTarget(null);
    } finally {
      setStatusSaving(false);
    }
  }, [confirmTarget, channel, load]);

  const loadActivities = useCallback(async () => {
    try {
      const res = await getActivities();
      const list = res?.data?.activities;
      setActivities(Array.isArray(list) ? list.map((a) => a.name).filter(Boolean) : []);
    } catch {
      setActivities([]);
    }
  }, []);

  useEffect(() => { if (admin) load(); }, [admin, load]);
  useEffect(() => { if (admin) loadActivities(); }, [admin, loadActivities]);

  // Filter dropdown: All + catch-all '*' + every activity.
  const filterOptions = useMemo(
    () => [{ id: '', name: 'All activities' }, { id: '*', name: '*  (catch-all)' },
      ...activities.map((a) => ({ id: a, name: a }))],
    [activities],
  );

  // Form activity dropdown: catch-all '*' first, then every activity.
  const formActivityOptions = useMemo(() => ['*', ...activities], [activities]);

  const pTemplates = usePaged(templates || [], 10);

  const openAdd = () => { setEditing(null); setModalOpen(true); };
  const openEdit = (row) => { setEditing(row); setModalOpen(true); };

  const handleSubmit = async (payload) => {
    await (channel === 'whatsapp' ? upsertWhatsappTemplate(payload) : upsertMailTemplate(payload));
    setModalOpen(false);
    setEditing(null);
    await load();
  };

  // Available {{placeholders}} for both channels — powers the email insert palette and the
  // WhatsApp parameter dropdowns. Loaded once for any admin.
  useEffect(() => {
    if (admin && variableFields.length === 0) {
      getWhatsappVariables().then(({ data }) => setVariableFields(data.fields || [])).catch(() => {});
    }
  }, [admin, variableFields.length]);

  if (!admin) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold text-[var(--text-main)]">Admins only</p>
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-sm">
          Mail Template Management is restricted to TPMS administrators.
        </p>
      </div>
    );
  }

  if (loading && templates.length === 0) {
    return <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading templates…</div>;
  }

  return (
    <div className="space-y-5">
      <DashboardHero icon={Mail} title="Notification Templates"
        subtitle="Email & WhatsApp templates keyed by activity, side & event — switch any notification off without affecting the workflow behind it">
        <div className="flex items-center gap-1 bg-white/20 p-1 rounded-lg">
          {CHANNELS.map((c) => (
            <button key={c.id} onClick={() => setChannel(c.id)} type="button"
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-bold transition-all ${
                channel === c.id ? 'bg-white text-[var(--accent-indigo)] shadow-sm' : 'text-white/80 hover:text-white'}`}>
              <c.icon size={13} /> {c.label}
            </button>
          ))}
        </div>
        <HeaderSelect value={filter} onChange={setFilter} options={filterOptions} />
        <HeroButton icon={Plus} onClick={openAdd}>Add Template</HeroButton>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      <Section
        title="Mail Templates"
        subtitle={templates.length ? `${templates.length} template${templates.length === 1 ? '' : 's'}` : 'Nothing yet'}
        icon={Filter}>
        {templates.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
              <Mail size={20} />
            </span>
            <p className="text-[13px] font-bold text-[var(--text-main)]">No templates found</p>
            <p className="text-[12px] text-[var(--text-muted)]">
              {filter ? 'No templates match this filter.' : 'Add your first mail template to get started.'}
            </p>
            <button onClick={openAdd}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity">
              <Plus size={14} /> Add Template
            </button>
          </div>
        ) : (
          <>
          <TableShell minWidth={920}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th>Activity</Th><Th align="center">Side</Th><Th align="center">Event</Th>
                <Th>{channel === 'whatsapp' ? 'Meta Template' : 'Subject'}</Th><Th align="center">Active</Th><Th align="right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {pTemplates.pageRows.map((t, i) => {
                const isActive = t.active !== false;
                return (
                  <tr key={t._id || i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors"
                    style={{ opacity: isActive ? 1 : 0.6 }}>
                    <Td className="font-bold whitespace-nowrap">{t.activity || '*'}</Td>
                    <Td align="center"><Pill label={t.side || '—'} tone={SIDE_TONE[t.side] || 'muted'} /></Td>
                    <Td align="center"><Pill label={t.event || '—'} tone="indigo" /></Td>
                    <Td className="font-medium max-w-[360px] truncate" title={(channel === 'whatsapp' ? (t.meta_template_name || t.name) : t.subject) || ''}>{(channel === 'whatsapp' ? (t.meta_template_name || t.name) : t.subject) || '—'}</Td>
                    <Td align="center">
                      <div className="flex justify-center">
                        <StatusToggle
                          active={isActive}
                          disabled={!admin}
                          onRequest={() => setConfirmTarget(t)}
                        />
                      </div>
                    </Td>
                    <Td align="right">
                      <button type="button" onClick={() => openEdit(t)}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                        <Pencil size={12} /> Edit
                      </button>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </TableShell>
          <Pager {...pTemplates} label="templates" />
          </>
        )}
      </Section>

      <AnimatePresence>
        {modalOpen && (
          <TemplateModal
            key={editing?._id || 'new'}
            editing={editing}
            activityOptions={formActivityOptions}
            channel={channel}
            variableFields={variableFields}
            onClose={() => { setModalOpen(false); setEditing(null); }}
            onSubmit={handleSubmit}
          />
        )}
      </AnimatePresence>

      {/* Status changes always go through a confirmation step, in both directions. */}
      <AnimatePresence>
        {confirmTarget && (
          <ConfirmStatusModal
            key={confirmTarget._id}
            target={confirmTarget}
            channelLabel={channelLabel}
            busy={statusSaving}
            onCancel={() => setConfirmTarget(null)}
            onConfirm={applyStatusChange}
          />
        )}
      </AnimatePresence>
    </div>
  );
};

export default MailTemplateAdmin;
