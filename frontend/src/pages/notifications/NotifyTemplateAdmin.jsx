import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RefreshCw, Mail, Plus, Pencil, X, ShieldAlert, CheckCircle2, AlertTriangle,
  MessageCircle, BadgeCheck, Eye, Info, Trash2, Send, ListChecks, Repeat, Clock, Play,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, TableShell, usePaged, Pager,
} from '../../features/tpms/common/dashboardKit';
import TemplateComposer from '../../components/whatsapp/TemplateComposer';
import { EDITABLE_STATUSES, STATUS_TONE } from '../../components/whatsapp/constants';
import {
  getNotifyModules, getNotifyTemplates, upsertNotifyTemplate, setNotifyTemplateStatus,
  deleteNotifyTemplate, testNotifyTemplate,
  checkMetaTemplate, deleteMetaTemplate, getApprovedMetaTemplates, getMetaTemplates,
  saveMetaTemplate, submitMetaTemplate, syncMetaTemplates, testMetaTemplate, getCompanies,
  getReminderSchedule, setReminderSchedule, runReminderSweepNow,
} from '../../services/notifyTemplatesApi';
import { useAuth } from '../../context/AuthContext';

/* ─────────────────────────────────────────────────────────────
   Task Management ▸ Notification Templates.

   The Delegation and Checklist counterpart to TPMS ▸ Templates, and deliberately the same
   screen in shape, because it is the same job:

   · Email / WhatsApp — the *wiring*. Which template fires for which trigger, and which data
     field fills each WhatsApp parameter. Saving is an upsert, so creating and editing hit one
     endpoint.

   · Templates — the WhatsApp template *library*. Definitions authored here and submitted to
     Meta for approval; they live on the WhatsApp Business Account, not in this CRM, and are
     therefore SHARED with TPMS — one business account, one library.

   Where it necessarily differs from TPMS: a task notification is not about a scheduled
   activity, so there is no activity × side × event key. The trigger alone identifies it, and
   the second axis is scope (internal staff vs a client company) — the axis
   notification_templates has always been keyed on.

   Route: /tasks/templates
   ───────────────────────────────────────────────────────────── */

const MotionDiv = motion.div;

const errMsg = (e, fallback) => e?.response?.data?.detail || fallback;

const CHANNELS = [
  { id: 'email', label: 'Email', icon: Mail },
  { id: 'whatsapp', label: 'WhatsApp', icon: MessageCircle },
];

const MODULE_ICON = { delegation: ListChecks, checklist: Repeat };

const SCOPE_OPTIONS = [
  { id: 'staff', name: 'Staff (internal)' },
  { id: 'company', name: 'Company (client)' },
];

/* The library's status filter — the Meta approval lifecycle, left to right. */
const LIBRARY_STATUS_TABS = [
  { id: '', label: 'All' },
  { id: 'DRAFT', label: 'Draft' },
  { id: 'PENDING', label: 'Pending' },
  { id: 'APPROVED', label: 'Approved' },
  { id: 'REJECTED', label: 'Rejected' },
];

const TONE = {
  green:  { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  indigo: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  orange: { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', bd: 'var(--accent-orange-border)' },
  red:    { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
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

/* The four Graph calls the composer makes. Hoisted so its identity is stable across renders. */
const COMPOSER_API = { checkMetaTemplate, saveMetaTemplate, submitMetaTemplate, testMetaTemplate };

const inputCls =
  'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] transition-colors';
const labelCls = 'text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]';

const Field = ({ label, children, required, hint }) => (
  <label className="flex flex-col gap-1.5">
    <span className={labelCls}>{label}{required && <span className="text-[var(--accent-red)]"> *</span>}</span>
    {children}
    {hint && <p className="text-[11px] text-[var(--text-muted)] leading-relaxed">{hint}</p>}
  </label>
);

/**
 * Warns when the Meta connection is missing or incomplete.
 *
 * Deliberately silent on the healthy path — a banner that only ever says "everything is fine"
 * is noise on every visit.
 */
const ConnectionBanner = ({ meta }) => {
  if (!meta || (meta.configured && meta.sending_configured)) return null;
  return (
    <div className="flex items-start gap-2 rounded-2xl border px-4 py-3 text-[12px] leading-relaxed"
      style={{ background: TONE.orange.bg, borderColor: TONE.orange.bd, color: 'var(--text-main)' }}>
      <Info size={15} className="mt-0.5 shrink-0" style={{ color: TONE.orange.c }} />
      <p>
        {meta.configured ? (
          <>
            <b>Sending is not configured.</b> Approved templates cannot be delivered until{' '}
            <b className="font-mono">WHATSAPP_PHONE_NUMBER_ID</b> is set in the backend
            environment. Authoring and submitting to Meta still work.
          </>
        ) : (
          <>
            <b>Not connected.</b> Set <b className="font-mono">WHATSAPP_ACCESS_TOKEN</b> and{' '}
            <b className="font-mono">WHATSAPP_BUSINESS_ACCOUNT_ID</b> in the backend environment
            to submit templates and read their approval status. Drafting still works here.
          </>
        )}
      </p>
    </div>
  );
};

/** The Active / Inactive switch on a wiring row. Confirmed before it applies. */
const StatusToggle = ({ active, onRequest, disabled }) => (
  <button type="button" role="switch" aria-checked={active} disabled={disabled}
    onClick={onRequest} title={active ? 'Active — click to deactivate' : 'Inactive — click to activate'}
    className="relative w-[42px] h-[22px] rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
    style={{ background: active ? 'var(--accent-green)' : 'var(--border)' }}>
    <span className="absolute top-[3px] w-4 h-4 rounded-full bg-white shadow transition-all"
      style={{ left: active ? '22px' : '3px' }} />
  </button>
);

/** Confirmation before deleting a library template — it is removed from the WhatsApp Business
 *  Account too, which cannot be undone. */
const ConfirmModal = ({ title, body, confirmLabel, tone = 'red', busy, onCancel, onConfirm }) => (
  <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
    <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={busy ? undefined : onCancel} />
    <MotionDiv role="dialog" aria-modal="true"
      initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 14, scale: 0.98 }} transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
      className="relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
      <div className="flex items-center gap-2.5 px-5 py-4 border-b border-[var(--border)]">
        <span className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: TONE[tone].bg, color: TONE[tone].c }}>
          <AlertTriangle size={16} />
        </span>
        <h3 className="text-[15px] font-extrabold tracking-tight">{title}</h3>
      </div>
      <div className="px-5 py-4 text-[13px] text-[var(--text-main)] leading-relaxed">{body}</div>
      <div className="px-5 py-3 border-t border-[var(--border)] flex items-center justify-end gap-2">
        <button type="button" onClick={onCancel} disabled={busy}
          className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
          Cancel
        </button>
        <button type="button" onClick={onConfirm} disabled={busy}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-60"
          style={{ background: TONE[tone].c }}>
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
          {busy ? 'Working…' : confirmLabel}
        </button>
      </div>
    </MotionDiv>
  </MotionDiv>
);

/** Which triggers the daily sweep governs — the rest send the moment someone clicks. */
const SWEEP_TRIGGERS = new Set([
  'task_due_reminder_daily', 'task_due_reminder_weekly', 'task_overdue',
  'task_verification_pending_reminder',
]);

const pad = (n) => String(n).padStart(2, '0');
const to12h = (h, m) => `${((h + 11) % 12) + 1}:${pad(m)} ${h < 12 ? 'AM' : 'PM'}`;

/**
 * When the time-driven reminders go out.
 *
 * Its own card rather than a field inside the wiring modal, because it is not a property of any
 * one template: one clock governs every recurring reminder, and burying it in a per-trigger
 * form would imply each could have its own.
 */
const ScheduleCard = ({ schedule, onSaved, onNotice, onError }) => {
  const [hour, setHour] = useState(schedule.hour);
  const [minute, setMinute] = useState(schedule.minute);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const dirty = hour !== schedule.hour || minute !== schedule.minute;

  const save = async () => {
    setSaving(true);
    try {
      const res = await setReminderSchedule(hour, minute);
      onNotice(`Reminders will go out at ${to12h(res.data.hour, res.data.minute)} IST. Takes effect on the next tick — nothing to restart.`);
      onSaved({ ...schedule, hour: res.data.hour, minute: res.data.minute });
    } catch (e) {
      onError(errMsg(e, 'Could not update the reminder time.'));
    } finally {
      setSaving(false);
    }
  };

  const runNow = async () => {
    setRunning(true);
    try {
      const res = await runReminderSweepNow();
      onNotice(res.data.note);
    } catch (e) {
      onError(errMsg(e, 'Could not run the sweep.'));
    } finally {
      setRunning(false);
    }
  };

  return (
    <Section title="Reminder Schedule" icon={Clock}
      subtitle={`Sent once a day at ${to12h(schedule.hour, schedule.minute)} IST · it is ${schedule.now_ist} IST now`}>
      <div className="px-5 py-4 space-y-4">
        <p className="text-[12.5px] text-[var(--text-muted)] leading-relaxed">
          Governs only the four recurring reminders — <b>Daily Due</b>, <b>Weekly Due</b>,{' '}
          <b>Overdue Alert</b> and <b>Verification Chase</b>. Every other trigger sends the moment
          someone acts, and is unaffected by this time. Each reminder goes out <b>once per day</b>
          {' '}at most, whatever happens to the server in between.
        </p>

        <div className="flex flex-wrap items-end gap-3">
          <Field label="Send at (IST)">
            <div className="flex items-center gap-1.5">
              <select value={hour} onChange={(e) => setHour(Number(e.target.value))}
                className={`${inputCls} w-auto cursor-pointer`}>
                {Array.from({ length: 24 }, (_, h) => (
                  <option key={h} value={h}>{to12h(h, 0).replace(':00', '')}</option>
                ))}
              </select>
              <span className="text-[13px] font-bold text-[var(--text-muted)]">:</span>
              <select value={minute} onChange={(e) => setMinute(Number(e.target.value))}
                className={`${inputCls} w-auto cursor-pointer`}>
                {[0, 15, 30, 45].map((m) => <option key={m} value={m}>{pad(m)}</option>)}
              </select>
            </div>
          </Field>
          <button type="button" onClick={save} disabled={!dirty || saving}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-50">
            {saving ? <RefreshCw size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
            {saving ? 'Saving…' : 'Save time'}
          </button>
          <button type="button" onClick={runNow} disabled={running}
            title="Run today's sweep now. A reminder that already went out today will not repeat."
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border border-[var(--border)] text-[12.5px] font-bold text-[var(--text-main)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            {running ? <RefreshCw size={13} className="animate-spin" /> : <Play size={13} />}
            {running ? 'Running…' : 'Send now'}
          </button>
        </div>

        {schedule.overdue_backlog_absorbed && (
          <p className="text-[11.5px] text-[var(--text-muted)] leading-relaxed rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2.5">
            <b>Overdue backlog absorbed.</b> {schedule.overdue_backlog_count ?? 0} task(s) that were
            already past their deadline when this was switched on were marked as alerted without
            being emailed. Overdue Alerts fire only for deadlines missed since then, so turning the
            trigger on cannot dump a backlog on anyone.
          </p>
        )}
      </div>
    </Section>
  );
};

/** Seed the wiring form from a stored row (edit) or a blank (add). */
const seedForm = (editing, trigger, channel) => (editing
  ? {
    trigger: (editing.slug || '').replace(/_(email|whatsapp)$/, ''),
    subject: editing.subject || '',
    body: editing.body || '',
    meta_template_name: editing.meta_template_name || '',
    meta_lang: editing.meta_lang || 'en',
    meta_params: Array.isArray(editing.meta_params) ? editing.meta_params : [],
    meta_header_params: Array.isArray(editing.meta_header_params) ? editing.meta_header_params : [],
    // Stored as {index, field}; the form holds just the field, aligned to the template's
    // variable URL buttons. Bare strings are rows written before the index was recorded.
    meta_button_params: Array.isArray(editing.meta_button_params)
      ? editing.meta_button_params.map((b) => (typeof b === 'string' ? b : b?.field || ''))
      : [],
  }
  : {
    trigger: trigger || '',
    subject: '', body: '',
    meta_template_name: '', meta_lang: 'en',
    meta_params: [], meta_header_params: [], meta_button_params: [],
    channel,
  });

/**
 * Add / Edit wiring modal — one trigger on one channel. Mounted only while open (via a keyed
 * parent), so state seeds cleanly from props on mount, with no effect-driven syncing.
 */
const WiringModal = ({ editing, channel, triggers, variables, approvedTemplates = [],
  onClose, onSubmit }) => {
  const [form, setForm] = useState(() => seedForm(editing, triggers[0]?.slug, channel));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const isWa = channel === 'whatsapp';
  const trigger = triggers.find((t) => t.slug === form.trigger);

  // The approved template this notification points at, and the parameter slots it declares.
  // A row saved before the library existed may name a template approved directly in WhatsApp
  // Manager, so an unknown name is kept and shown rather than silently cleared.
  const selected = approvedTemplates.find((t) => t.name === form.meta_template_name);
  const bodySlots = selected ? selected.body_variables || [] : (form.meta_params || []).map((_, i) => String(i + 1));
  const headerSlots = selected ? selected.header_variables || [] : [];
  const urlButtons = selected ? selected.url_buttons || [] : [];

  /** Adopt a template: keep any mapping that still fits, drop what no longer does, and take
   *  the template's own language so the two can never drift apart. */
  const pickTemplate = (name) => {
    const tpl = approvedTemplates.find((t) => t.name === name);
    setForm((f) => ({
      ...f,
      meta_template_name: name,
      meta_lang: tpl?.language || f.meta_lang,
      meta_params: (tpl?.body_variables || []).map((_, i) => (f.meta_params || [])[i] || ''),
      meta_header_params: (tpl?.header_variables || []).map((_, i) => (f.meta_header_params || [])[i] || ''),
      meta_button_params: (tpl?.url_buttons || []).map((_, i) => (f.meta_button_params || [])[i] || ''),
    }));
  };

  const setSlot = (key, i, value) => set(key, Object.assign([...(form[key] || [])], { [i]: value }));

  // Insert a {{placeholder}} into the email body at the cursor.
  const insertBodyVar = (v) => {
    const token = `{{${v}}}`;
    const ta = document.getElementById('notify-body');
    if (!ta) { set('body', (form.body || '') + token); return; }
    const start = ta.selectionStart ?? (form.body || '').length;
    const end = ta.selectionEnd ?? start;
    set('body', (form.body || '').slice(0, start) + token + (form.body || '').slice(end));
    requestAnimationFrame(() => { ta.focus(); const p = start + token.length; ta.setSelectionRange(p, p); });
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.trigger) { setErr('Choose a trigger.'); return; }
    if (!isWa && !form.subject.trim()) { setErr('Subject is required.'); return; }
    if (!isWa && !form.body.trim()) {
      setErr('Body is required — an empty template sends nothing, because these modules never '
        + 'fall back to a built-in default.');
      return;
    }
    setSaving(true);
    setErr('');
    try {
      const base = { trigger: form.trigger, channel, name: trigger?.label || form.trigger };
      await onSubmit(isWa
        ? {
          ...base,
          body: form.body,
          meta_template_name: form.meta_template_name.trim(),
          meta_lang: (form.meta_lang || 'en').trim() || 'en',
          // Unmapped slots are dropped rather than sent blank — the send layer's "-" fallback
          // then handles them, exactly as it does for TPMS.
          meta_params: (form.meta_params || []).filter(Boolean),
          meta_header_params: (form.meta_header_params || []).filter(Boolean),
          // Send each button's real position in the template, not its position among the
          // variable ones — that is the number Meta substitutes against.
          meta_button_params: urlButtons
            .map((b, i) => ({ index: b.index, field: (form.meta_button_params || [])[i] || '' }))
            .filter((b) => b.field),
        }
        : { ...base, subject: form.subject.trim(), body: form.body });
    } catch (ex) {
      setErr(errMsg(ex, 'Failed to save template. Please try again.'));
      setSaving(false);
    }
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv
        initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }} transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              {editing ? <Pencil size={16} /> : <Plus size={16} />}
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">
              {editing ? 'Edit' : 'Add'} {isWa ? 'WhatsApp' : 'Email'} Template
            </h3>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={submit} className="px-5 py-4 space-y-4 overflow-y-auto">
          <Field label="Trigger" required hint={trigger?.description}>
            <select value={form.trigger} onChange={(e) => set('trigger', e.target.value)}
              disabled={Boolean(editing)} className={`${inputCls} cursor-pointer disabled:opacity-70`}>
              <option value="">— select a trigger —</option>
              {triggers.map((t) => <option key={t.slug} value={t.slug}>{t.label}</option>)}
            </select>
          </Field>

          {!isWa && (
            <>
              <Field label="Subject" required>
                <input type="text" value={form.subject} onChange={(e) => set('subject', e.target.value)}
                  placeholder="e.g. New Task Assigned: {{task_name}}" className={inputCls} />
              </Field>
              <Field label="Body">
                <textarea id="notify-body" value={form.body} onChange={(e) => set('body', e.target.value)}
                  placeholder="Hello {{assigned_user}}, …  — use {{double-brace}} placeholders" rows={8}
                  className={`${inputCls} font-mono text-[12px] leading-relaxed resize-y`} />
              </Field>
            </>
          )}

          {isWa && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="sm:col-span-2">
                  <Field label="Approved Template">
                    <select value={form.meta_template_name} onChange={(e) => pickTemplate(e.target.value)}
                      className={`${inputCls} font-mono cursor-pointer`}>
                      <option value="">— free-form text only (24h window) —</option>
                      {approvedTemplates.map((t) => (
                        <option key={t._id} value={t.name}>{t.name} ({t.language})</option>
                      ))}
                      {/* Approved in WhatsApp Manager before the library existed — keep it
                          selectable so an existing notification is never silently unwired. */}
                      {form.meta_template_name && !selected && (
                        <option value={form.meta_template_name}>{form.meta_template_name} (not in library)</option>
                      )}
                    </select>
                  </Field>
                </div>
                <Field label="Language">
                  <input type="text" value={form.meta_lang} readOnly={Boolean(selected)}
                    onChange={(e) => set('meta_lang', e.target.value)} placeholder="en"
                    title={selected ? 'Taken from the approved template' : undefined}
                    className={`${inputCls} ${selected ? 'opacity-70' : ''}`} />
                </Field>
              </div>

              {approvedTemplates.length === 0 ? (
                <p className="text-[11.5px] text-[var(--text-muted)] leading-relaxed rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2.5">
                  No approved templates yet. Author one in <b>WhatsApp Templates</b> above and
                  submit it to Meta — a business-initiated message can only use an approved
                  template.
                </p>
              ) : selected ? (
                <p className="text-[11.5px] text-[var(--text-muted)] leading-relaxed rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2.5">
                  {selected.body}
                </p>
              ) : null}

              {headerSlots.length > 0 && (
                <div>
                  <label className="block text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wide mb-1.5">
                    Header parameter
                  </label>
                  <div className="space-y-2">
                    {headerSlots.map((v, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="text-[11px] font-black text-[var(--accent-indigo)] w-16 shrink-0 font-mono">{`{{${v}}}`}</span>
                        <select value={(form.meta_header_params || [])[i] || ''}
                          onChange={(e) => setSlot('meta_header_params', i, e.target.value)}
                          className={`${inputCls} flex-1`}>
                          <option value="">— select field —</option>
                          {variables.map((f) => <option key={f} value={f}>{f}</option>)}
                        </select>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <label className="block text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wide mb-1.5">
                  Body parameters {selected ? '(from the approved template)' : '(order = {{1}}, {{2}}…)'}
                </label>
                {bodySlots.length === 0 ? (
                  <p className="text-[11px] text-[var(--text-muted)] italic">
                    {form.meta_template_name
                      ? 'This template takes no parameters — nothing to map.'
                      : 'Select a template to see the parameters it needs.'}
                  </p>
                ) : (
                  <div className="space-y-2">
                    {bodySlots.map((v, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="text-[11px] font-black text-[var(--accent-indigo)] w-16 shrink-0 font-mono">{`{{${v}}}`}</span>
                        <select value={(form.meta_params || [])[i] || ''}
                          onChange={(e) => setSlot('meta_params', i, e.target.value)}
                          className={`${inputCls} flex-1`}>
                          <option value="">— select field —</option>
                          {variables.map((f) => <option key={f} value={f}>{f}</option>)}
                        </select>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {urlButtons.length > 0 && (
                <div>
                  <label className="block text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wide mb-1.5">
                    Button URL parameters
                  </label>
                  <div className="space-y-2">
                    {urlButtons.map((b, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="text-[11px] font-black text-[var(--accent-indigo)] w-16 shrink-0 truncate" title={b.text}>{b.text || `Button ${i + 1}`}</span>
                        <select value={(form.meta_button_params || [])[i] || ''}
                          onChange={(e) => setSlot('meta_button_params', i, e.target.value)}
                          className={`${inputCls} flex-1`}>
                          <option value="">— select field —</option>
                          {variables.map((f) => <option key={f} value={f}>{f}</option>)}
                        </select>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <Field label="Fallback text"
                hint="Sent instead when no approved template is chosen. Meta only delivers free-form text within 24 hours of that number messaging you.">
                <textarea value={form.body} onChange={(e) => set('body', e.target.value)} rows={3}
                  placeholder="Hello {{assigned_user}}, you have a new task: {{task_name}}"
                  className={`${inputCls} font-mono text-[12px] leading-relaxed resize-y`} />
              </Field>
            </>
          )}

          {/* The placeholder palette — the exact keys this module's context provides, so a
              field offered here is guaranteed to resolve rather than print as literal text. */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wide">
                Available placeholders
              </label>
              {!isWa && <span className="text-[11px] text-[var(--text-muted)]">click to add at the cursor</span>}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {variables.map((v) => (
                <button key={v} type="button" disabled={isWa}
                  onClick={isWa ? undefined : () => insertBodyVar(v)}
                  className="font-mono text-[11px] px-2 py-1 rounded-md border border-[var(--border)] bg-[var(--input-bg)] text-[var(--text-main)] enabled:hover:border-[var(--accent-indigo)] transition-colors disabled:cursor-default">
                  {`{{${v}}}`}
                </button>
              ))}
            </div>
          </div>

          {err && (
            <div className="flex items-start gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2.5 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {err}
            </div>
          )}
        </form>

        <div className="px-5 py-3 border-t border-[var(--border)] flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} disabled={saving}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Cancel
          </button>
          <button type="button" onClick={submit} disabled={saving}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-60">
            {saving ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

/** Send one configured trigger to a real handset using its stored mapping. */
const TestModal = ({ target, onClose }) => {
  const [phone, setPhone] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const run = async () => {
    setBusy(true);
    setResult(null);
    try {
      const res = await testNotifyTemplate({
        trigger: (target.slug || '').replace(/_(email|whatsapp)$/, ''),
        scope: target.scope, company_id: target.company_id, phone,
      });
      setResult({ ok: true, message: `Sent to ${res.data.sent_to}. Values in order: ${(res.data.params || []).join(' | ') || 'none'}` });
    } catch (e) {
      setResult({ ok: false, message: errMsg(e, 'Could not send the test.') });
    } finally {
      setBusy(false);
    }
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={busy ? undefined : onClose} />
      <MotionDiv initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }} transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-[var(--border)]">
          <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
            <Send size={16} />
          </span>
          <h3 className="text-[15px] font-extrabold tracking-tight">Test this notification</h3>
        </div>
        <div className="px-5 py-4 space-y-3">
          <p className="text-[12.5px] text-[var(--text-muted)] leading-relaxed">
            Sends <b className="font-mono text-[var(--text-main)]">{target.meta_template_name}</b> using
            this row's real field mapping, with each placeholder filled by its own name — so a
            mis-ordered mapping is obvious on the handset.
          </p>
          <Field label="Phone number" required>
            <input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)}
              placeholder="9876543210" className={inputCls} />
          </Field>
          {result && (
            <div className="flex items-start gap-2 rounded-lg border px-3 py-2.5 text-[12px] font-bold"
              style={{
                background: result.ok ? TONE.green.bg : TONE.red.bg,
                borderColor: result.ok ? TONE.green.bd : TONE.red.bd,
                color: result.ok ? TONE.green.c : TONE.red.c,
              }}>
              {result.ok ? <CheckCircle2 size={14} className="mt-0.5 shrink-0" /> : <AlertTriangle size={14} className="mt-0.5 shrink-0" />}
              {result.message}
            </div>
          )}
        </div>
        <div className="px-5 py-3 border-t border-[var(--border)] flex items-center justify-end gap-2">
          <button type="button" onClick={onClose} disabled={busy}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Close
          </button>
          <button type="button" onClick={run} disabled={busy || !phone.trim()}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-60">
            {busy ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
            {busy ? 'Sending…' : 'Send test'}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

const NotifyTemplateAdmin = () => {
  const { user } = useAuth();
  const admin = ['superadmin', 'admin'].includes((user?.role || '').toLowerCase());

  const [modules, setModules] = useState([]);
  const [meta, setMeta] = useState(null);
  const [moduleKey, setModuleKey] = useState('delegation');
  const [channel, setChannel] = useState('email');
  const [scope, setScope] = useState('staff');
  const [companies, setCompanies] = useState([]);
  const [companyId, setCompanyId] = useState('');

  const [templates, setTemplates] = useState([]);
  const [library, setLibrary] = useState([]);
  const [approved, setApproved] = useState([]);
  const [libStatus, setLibStatus] = useState('');

  const [schedule, setSchedule] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const [modalOpen, setModalOpen] = useState(false);
  const [modalKind, setModalKind] = useState('wiring');   // 'wiring' | 'library'
  const [editing, setEditing] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);      // library row
  const [wiringDeleteTarget, setWiringDeleteTarget] = useState(null);
  const [confirmTarget, setConfirmTarget] = useState(null);   // status flip
  const [testTarget, setTestTarget] = useState(null);
  const [busy, setBusy] = useState(false);

  const isWhatsapp = channel === 'whatsapp';
  const current = useMemo(() => modules.find((m) => m.key === moduleKey), [modules, moduleKey]);
  // Memoised because triggerLabel closes over `triggers`: a fresh [] each render would give the
  // callback a new identity every time and re-render every row that takes it.
  const triggers = useMemo(() => current?.triggers || [], [current]);
  const variables = useMemo(() => current?.variables || [], [current]);

  // ── Catalogue: loaded once, drives every selector on the page ──
  useEffect(() => {
    if (!admin) { setLoading(false); return; }
    (async () => {
      try {
        const res = await getNotifyModules();
        setModules(res.data?.modules || []);
        setMeta(res.data?.meta || null);
      } catch (e) {
        setError(errMsg(e, 'Could not load the template catalogue.'));
      } finally {
        setLoading(false);
      }
    })();
  }, [admin]);

  useEffect(() => {
    if (!admin) return;
    getCompanies().then(({ data }) => setCompanies(data || [])).catch(() => setCompanies([]));
    getReminderSchedule().then(({ data }) => setSchedule(data)).catch(() => setSchedule(null));
  }, [admin]);

  const load = useCallback(async () => {
    if (!admin) return;
    // A company-scoped view is meaningless until a company is chosen; showing the staff rows
    // instead would be actively misleading about what is configured.
    if (scope === 'company' && !companyId) { setTemplates([]); return; }
    try {
      const res = await getNotifyTemplates({
        module: moduleKey, channel, scope,
        company_id: scope === 'company' ? companyId : undefined,
      });
      setTemplates(res.data?.templates || []);
    } catch (e) {
      setError(errMsg(e, 'Could not load templates.'));
    }
  }, [admin, moduleKey, channel, scope, companyId]);

  const loadLibrary = useCallback(async () => {
    if (!admin) return;
    try {
      const [lib, appr] = await Promise.all([
        getMetaTemplates(libStatus),
        getApprovedMetaTemplates(),
      ]);
      setLibrary(lib.data?.templates || []);
      setApproved(appr.data?.templates || []);
      if (lib.data?.meta) setMeta(lib.data.meta);
    } catch (e) {
      setError(errMsg(e, 'Could not load the WhatsApp template library.'));
    }
  }, [admin, libStatus]);

  useEffect(() => { load(); }, [load]);
  // The library is WhatsApp-only. Refetched whenever the tab is opened or its status filter
  // changes, so a template approved a minute ago is selectable without a page reload.
  useEffect(() => { if (isWhatsapp) loadLibrary(); }, [isWhatsapp, loadLibrary]);
  // A notice belongs to the tab that produced it.
  useEffect(() => { setNotice(''); setError(''); }, [channel, moduleKey, scope]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const res = await syncMetaTemplates();
      setNotice(`Synced with Meta — ${res.data.updated} updated, ${res.data.imported} imported.`);
      await loadLibrary();
    } catch (e) {
      setError(errMsg(e, 'Could not reach Meta.'));
    } finally {
      setSyncing(false);
    }
  };

  const handleSubmit = async (payload) => {
    const res = await upsertNotifyTemplate({
      ...payload, scope, company_id: scope === 'company' ? companyId : undefined,
    });
    setModalOpen(false);
    setEditing(null);
    setNotice(res.data?.note || 'Template saved.');
    await load();
  };

  const applyStatusChange = async () => {
    if (!confirmTarget) return;
    setBusy(true);
    try {
      await setNotifyTemplateStatus(confirmTarget._id, confirmTarget.is_active === false);
      setConfirmTarget(null);
      await load();
    } catch (e) {
      setError(errMsg(e, 'Failed to update template status.'));
      setConfirmTarget(null);
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteLibrary = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      await deleteMetaTemplate(deleteTarget._id);
      setDeleteTarget(null);
      setNotice('Template deleted.');
      await loadLibrary();
    } catch (e) {
      setError(errMsg(e, 'Could not delete the template.'));
      setDeleteTarget(null);
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteWiring = async () => {
    if (!wiringDeleteTarget) return;
    setBusy(true);
    try {
      await deleteNotifyTemplate(wiringDeleteTarget._id);
      setWiringDeleteTarget(null);
      setNotice('Template removed — this trigger will not send on this channel until one is configured again.');
      await load();
    } catch (e) {
      setError(errMsg(e, 'Could not remove the template.'));
      setWiringDeleteTarget(null);
    } finally {
      setBusy(false);
    }
  };

  const onComposerSaved = useCallback(async (message) => {
    setModalOpen(false);
    setEditing(null);
    setNotice(message);
    setError('');
    await loadLibrary();
  }, [loadLibrary]);

  const openWiring = (row = null) => { setModalKind('wiring'); setEditing(row); setModalOpen(true); };
  const openLibrary = (row = null) => { setModalKind('library'); setEditing(row); setModalOpen(true); };

  const triggerLabel = useCallback((slug) => {
    const bare = (slug || '').replace(/_(email|whatsapp)$/, '');
    return triggers.find((t) => t.slug === bare)?.label || bare;
  }, [triggers]);

  const companyOptions = useMemo(
    () => [{ id: '', name: '— select a company —' },
      ...companies.map((c) => ({ id: c._id, name: c.name }))],
    [companies],
  );

  const pTemplates = usePaged(templates || [], 10);
  const pLibrary = usePaged(library || [], 10);

  if (!admin) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold text-[var(--text-main)]">Admins only</p>
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-sm">
          Notification templates are managed by Admins and Super Admins.
        </p>
      </div>
    );
  }

  if (loading) {
    return <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading templates…</div>;
  }

  return (
    <div className="space-y-5">
      <DashboardHero icon={Mail} title="Notification Templates"
        subtitle={isWhatsapp
          ? 'Create WhatsApp templates, get them approved by Meta, and wire the approved ones to Delegation & Checklist triggers'
          : 'Email & WhatsApp templates keyed by trigger — switch any notification off without affecting the workflow behind it'}>
        <div className="flex items-center gap-1 bg-white/20 p-1 rounded-lg">
          {modules.map((m) => {
            const Icon = MODULE_ICON[m.key] || ListChecks;
            return (
              <button key={m.key} onClick={() => setModuleKey(m.key)} type="button"
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-bold transition-all ${
                  moduleKey === m.key ? 'bg-white text-[var(--accent-indigo)] shadow-sm' : 'text-white/80 hover:text-white'}`}>
                <Icon size={13} /> {m.label}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-1 bg-white/20 p-1 rounded-lg">
          {CHANNELS.map((c) => (
            <button key={c.id} onClick={() => setChannel(c.id)} type="button"
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-bold transition-all ${
                channel === c.id ? 'bg-white text-[var(--accent-indigo)] shadow-sm' : 'text-white/80 hover:text-white'}`}>
              <c.icon size={13} /> {c.label}
            </button>
          ))}
        </div>
        <HeaderSelect value={scope} onChange={setScope} options={SCOPE_OPTIONS} />
        {scope === 'company' && (
          <HeaderSelect value={companyId} onChange={setCompanyId} options={companyOptions} />
        )}
        {isWhatsapp && <HeroButton icon={Plus} onClick={() => openLibrary()}>New template</HeroButton>}
        <HeroButton icon={RefreshCw} onClick={() => { load(); if (isWhatsapp) loadLibrary(); }}>
          Refresh
        </HeroButton>
      </DashboardHero>

      {isWhatsapp && <ConnectionBanner meta={meta} />}

      {current && (
        <p className="text-[12.5px] text-[var(--text-muted)] leading-relaxed px-1">{current.description}</p>
      )}

      {notice && (
        <div className="flex items-start gap-2 rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)]">
          <CheckCircle2 size={15} className="mt-0.5 shrink-0" /> {notice}
        </div>
      )}
      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* ── The WhatsApp template library. Definitions that live on the WhatsApp Business
             Account, shared with TPMS. Sits above the notifications because a template must
             exist and be approved before anything can be wired to it. ── */}
      {isWhatsapp && (
        <Section
          title="WhatsApp Templates"
          subtitle={library.length
            ? `${library.length} template${library.length === 1 ? '' : 's'} on your business account — shared with TPMS`
            : 'Nothing yet'}
          icon={BadgeCheck}
          action={(
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1 p-1 rounded-lg bg-[var(--input-bg)] border border-[var(--border)]">
                {LIBRARY_STATUS_TABS.map((s) => (
                  <button key={s.id} type="button" onClick={() => setLibStatus(s.id)}
                    className={`px-2.5 py-1.5 rounded-md text-[11.5px] font-bold transition-colors ${
                      libStatus === s.id
                        ? 'bg-[var(--bg-card)] text-[var(--accent-indigo)] shadow-sm'
                        : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
                    {s.label}
                  </button>
                ))}
              </div>
              <button type="button" onClick={handleSync} disabled={syncing}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-main)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                <RefreshCw size={13} className={syncing ? 'animate-spin' : undefined} />
                {syncing ? 'Syncing…' : 'Sync with Meta'}
              </button>
              <button type="button" onClick={() => openLibrary()}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold shadow-sm hover:opacity-90 transition-opacity">
                <Plus size={13} /> New template
              </button>
            </div>
          )}>
          {library.length === 0 ? (
            <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
              <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
                <BadgeCheck size={20} />
              </span>
              <p className="text-[13px] font-bold text-[var(--text-main)]">No templates yet</p>
              <p className="text-[12px] text-[var(--text-muted)] max-w-md">
                {libStatus
                  ? `No ${libStatus.toLowerCase()} templates.`
                  : 'Create your first template and submit it to Meta, or sync to pull in templates already approved on your business account.'}
              </p>
              <button onClick={() => openLibrary()}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity">
                <Plus size={14} /> New template
              </button>
            </div>
          ) : (
            <>
              <TableShell minWidth={860}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    <Th>Name</Th><Th align="center">Category</Th><Th align="center">Language</Th>
                    <Th align="center">Status</Th><Th align="right">Action</Th>
                  </tr>
                </thead>
                <tbody>
                  {pLibrary.pageRows.map((t) => {
                    const rowStatus = (t.status || 'DRAFT').toUpperCase();
                    const editable = EDITABLE_STATUSES.includes(rowStatus);
                    return (
                      <tr key={t._id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors align-top">
                        <Td>
                          <div className="font-bold font-mono text-[12.5px] break-all">{t.name}</div>
                          <div className="text-[11px] text-[var(--text-muted)] mt-0.5 max-w-[320px] truncate" title={t.body || ''}>
                            {t.body || (rowStatus === 'DRAFT' ? 'No body yet' : '—')}
                          </div>
                          {rowStatus === 'REJECTED' && t.rejected_reason && (
                            <div className="text-[11px] text-[var(--accent-red)] mt-1 max-w-[320px]">{t.rejected_reason}</div>
                          )}
                        </Td>
                        <Td align="center"><Pill label={t.meta_category || t.category || '—'} tone="indigo" /></Td>
                        <Td align="center" className="font-medium text-[var(--text-muted)]">{t.language}</Td>
                        <Td align="center"><Pill label={rowStatus} tone={STATUS_TONE[rowStatus] || 'muted'} /></Td>
                        <Td align="right">
                          <div className="inline-flex items-center gap-1.5">
                            <button type="button" onClick={() => openLibrary(t)}
                              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                              {editable ? <><Pencil size={12} /> Edit</> : <><Eye size={12} /> View</>}
                            </button>
                            <button type="button" onClick={() => setDeleteTarget(t)} title="Delete template"
                              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-red)] bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] hover:opacity-90 transition-opacity">
                              <Trash2 size={12} /> Delete
                            </button>
                          </div>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </TableShell>
              <Pager {...pLibrary} label="templates" />
            </>
          )}
        </Section>
      )}

      {/* The clock that governs the recurring reminders. Shown on the module that owns them,
          so it appears next to the triggers it actually affects rather than on every tab. */}
      {schedule && triggers.some((t) => SWEEP_TRIGGERS.has(t.slug)) && (
        <ScheduleCard schedule={schedule} onSaved={setSchedule}
          onNotice={(m) => { setNotice(m); setError(''); }}
          onError={(m) => { setError(m); setNotice(''); }} />
      )}

      {/* ── The wiring: which template fires for which trigger. ── */}
      <Section
        title={`${current?.label || 'Module'} · ${isWhatsapp ? 'WhatsApp' : 'Email'} Notifications`}
        subtitle={templates.length
          ? `${templates.length} of ${triggers.length} trigger${triggers.length === 1 ? '' : 's'} configured`
          : `${triggers.length} trigger${triggers.length === 1 ? '' : 's'} available, none configured`}
        icon={isWhatsapp ? MessageCircle : Mail}
        action={(
          <button type="button" onClick={() => openWiring()}
            disabled={scope === 'company' && !companyId}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-50">
            <Plus size={13} /> Add Template
          </button>
        )}>
        {scope === 'company' && !companyId ? (
          <div className="px-5 py-12 text-center text-[12.5px] text-[var(--text-muted)]">
            Choose a company to see and edit its own overrides. Anything not overridden falls
            back to the staff template.
          </div>
        ) : templates.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
              {isWhatsapp ? <MessageCircle size={20} /> : <Mail size={20} />}
            </span>
            <p className="text-[13px] font-bold text-[var(--text-main)]">Nothing configured yet</p>
            <p className="text-[12px] text-[var(--text-muted)] max-w-md">
              These triggers send nothing until a template exists for them — there is no built-in
              fallback body, which is what makes configuring one here a deliberate switch-on.
            </p>
            <button onClick={() => openWiring()}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity">
              <Plus size={14} /> Add Template
            </button>
          </div>
        ) : (
          <>
            <TableShell minWidth={920}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th>Trigger</Th>
                  <Th>{isWhatsapp ? 'Meta Template' : 'Subject'}</Th>
                  <Th align="center">Active</Th><Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {pTemplates.pageRows.map((t) => {
                  const isActive = t.is_active !== false;
                  return (
                    <tr key={t._id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors"
                      style={{ opacity: isActive ? 1 : 0.6 }}>
                      <Td>
                        <div className="flex items-center gap-1.5">
                          <span className="font-bold whitespace-nowrap">{triggerLabel(t.slug)}</span>
                          {SWEEP_TRIGGERS.has((t.slug || '').replace(/_(email|whatsapp)$/, '')) && (
                            <span title={`Sent by the daily sweep at ${schedule ? to12h(schedule.hour, schedule.minute) : '10:00 AM'} IST`}>
                              <Clock size={12} className="text-[var(--text-muted)]" />
                            </span>
                          )}
                        </div>
                        <div className="text-[11px] font-mono text-[var(--text-muted)] mt-0.5">{t.slug}</div>
                      </Td>
                      <Td className="font-medium max-w-[360px] truncate"
                        title={(isWhatsapp ? t.meta_template_name : t.subject) || ''}>
                        {(isWhatsapp ? t.meta_template_name : t.subject)
                          || (isWhatsapp ? <span className="text-[var(--text-muted)] italic">free-form text</span> : '—')}
                      </Td>
                      <Td align="center">
                        <div className="flex justify-center">
                          <StatusToggle active={isActive} onRequest={() => setConfirmTarget(t)} />
                        </div>
                      </Td>
                      <Td align="right">
                        <div className="inline-flex items-center gap-1.5">
                          {isWhatsapp && t.meta_template_name && (
                            <button type="button" onClick={() => setTestTarget(t)} title="Send a test message"
                              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-green)] bg-[var(--accent-green-bg)] border border-[var(--accent-green-border)] hover:opacity-90 transition-opacity">
                              <Send size={12} /> Test
                            </button>
                          )}
                          <button type="button" onClick={() => openWiring(t)}
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                            <Pencil size={12} /> Edit
                          </button>
                          <button type="button" onClick={() => setWiringDeleteTarget(t)} title="Remove template"
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-red)] bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] hover:opacity-90 transition-opacity">
                            <Trash2 size={12} />
                          </button>
                        </div>
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

      {/* Two different editors: the library authors a template definition and talks to Meta,
          the wiring modal points an existing template at a trigger. */}
      <AnimatePresence>
        {modalOpen && (modalKind === 'library' ? (
          <TemplateComposer
            key={editing?._id || 'new-library'}
            editing={editing}
            api={COMPOSER_API}
            onClose={() => { setModalOpen(false); setEditing(null); }}
            onSaved={onComposerSaved}
          />
        ) : (
          <WiringModal
            key={editing?._id || `new-${channel}`}
            editing={editing}
            channel={channel}
            triggers={triggers}
            variables={variables}
            approvedTemplates={approved}
            onClose={() => { setModalOpen(false); setEditing(null); }}
            onSubmit={handleSubmit}
          />
        ))}

        {deleteTarget && (
          <ConfirmModal
            title="Delete this template?"
            body={<>
              <b className="font-mono">{deleteTarget.name}</b> will be removed from the WhatsApp
              Business Account as well as from here, and that cannot be undone. Any notification
              still pointed at it — in this module or in TPMS — will stop sending.
            </>}
            confirmLabel="Delete" busy={busy}
            onCancel={() => setDeleteTarget(null)} onConfirm={handleDeleteLibrary}
          />
        )}

        {wiringDeleteTarget && (
          <ConfirmModal
            title="Remove this template?"
            body={<>
              <b>{triggerLabel(wiringDeleteTarget.slug)}</b> will stop sending on{' '}
              {isWhatsapp ? 'WhatsApp' : 'email'} until a template is configured for it again.
              The trigger itself is unaffected — the workflow behind it keeps working.
            </>}
            confirmLabel="Remove" busy={busy}
            onCancel={() => setWiringDeleteTarget(null)} onConfirm={handleDeleteWiring}
          />
        )}

        {confirmTarget && (
          <ConfirmModal
            title={confirmTarget.is_active === false ? 'Activate notification?' : 'Deactivate notification?'}
            tone={confirmTarget.is_active === false ? 'green' : 'orange'}
            body={confirmTarget.is_active === false
              ? <><b>{triggerLabel(confirmTarget.slug)}</b> will start being sent again to its usual recipients.</>
              : <><b>{triggerLabel(confirmTarget.slug)}</b> will stop being sent. Everything else keeps
                working exactly as now — tasks still assign, complete and roll forward. Only the
                message is suppressed.</>}
            confirmLabel={confirmTarget.is_active === false ? 'Activate' : 'Deactivate'}
            busy={busy}
            onCancel={() => setConfirmTarget(null)} onConfirm={applyStatusChange}
          />
        )}

        {testTarget && <TestModal target={testTarget} onClose={() => setTestTarget(null)} />}
      </AnimatePresence>
    </div>
  );
};

export default NotifyTemplateAdmin;
