import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  RefreshCw, Mail, Plus, Pencil, X, ShieldAlert, CheckCircle2, AlertTriangle, Filter,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, HeaderSelect, Section, Th, Td, TableShell,
} from '../../common/dashboardKit';
import { getMailTemplates, upsertMailTemplate, getActivities } from '../../../../services/tpmsApi';
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
const EVENT_OPTIONS = ['schedule', 'reminder', 'reschedule', 'cancel', 'completed'];

const errMsg = (e, fallback) => e?.response?.data?.detail || fallback;

/** A blank form — also the shape used to reset the modal. */
const EMPTY_FORM = {
  activity: '*',
  side: 'staff',
  event: 'schedule',
  subject: '',
  body_html: '',
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
    active: editing.active !== false,
  }
  : EMPTY_FORM);

/**
 * Add / Edit modal — reused for both create and update flows (both upsert).
 * Mounted only while open (via a keyed parent), so state seeds cleanly from
 * props on mount — no effect-driven syncing needed.
 */
const TemplateModal = ({ editing, activityOptions, onClose, onSubmit }) => {
  const [form, setForm] = useState(() => seedForm(editing));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.subject.trim()) { setErr('Subject is required.'); return; }
    setSaving(true);
    setErr('');
    try {
      await onSubmit({
        ...form,
        activity: form.activity.trim() || '*',
        subject: form.subject.trim(),
        body_html: form.body_html,
      });
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

          <Field label="Subject" required>
            <input type="text" value={form.subject} onChange={(e) => set('subject', e.target.value)}
              placeholder="e.g. [Reminder] {Activity} due in 2 days | {Client}" className={inputCls} autoFocus />
          </Field>

          <Field label="Body (HTML)">
            <textarea value={form.body_html} onChange={(e) => set('body_html', e.target.value)}
              placeholder="<p>Hello {Name}, …</p>" rows={7}
              className={`${inputCls} font-mono text-[12px] leading-relaxed resize-y`} />
          </Field>

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

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getMailTemplates(filter || undefined);
      const list = res?.data?.templates;
      setTemplates(Array.isArray(list) ? list : []);
    } catch (e) {
      setError(errMsg(e, 'Failed to load mail templates.'));
    } finally {
      setLoading(false);
    }
  }, [filter]);

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

  const openAdd = () => { setEditing(null); setModalOpen(true); };
  const openEdit = (row) => { setEditing(row); setModalOpen(true); };

  const handleSubmit = async (payload) => {
    await upsertMailTemplate(payload);
    setModalOpen(false);
    setEditing(null);
    await load();
  };

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
      <DashboardHero icon={Mail} title="Mail Templates" subtitle="Transactional mail templates keyed by activity, side & event (M12)">
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
          <TableShell minWidth={920}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th>Activity</Th><Th align="center">Side</Th><Th align="center">Event</Th>
                <Th>Subject</Th><Th align="center">Active</Th><Th align="right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {templates.map((t, i) => {
                const isActive = t.active !== false;
                return (
                  <tr key={t._id || i} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors"
                    style={{ opacity: isActive ? 1 : 0.6 }}>
                    <Td className="font-bold whitespace-nowrap">{t.activity || '*'}</Td>
                    <Td align="center"><Pill label={t.side || '—'} tone={SIDE_TONE[t.side] || 'muted'} /></Td>
                    <Td align="center"><Pill label={t.event || '—'} tone="indigo" /></Td>
                    <Td className="font-medium max-w-[360px] truncate" title={t.subject || ''}>{t.subject || '—'}</Td>
                    <Td align="center"><Pill label={isActive ? 'Active' : 'Inactive'} tone={isActive ? 'green' : 'muted'} /></Td>
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
        )}
      </Section>

      <AnimatePresence>
        {modalOpen && (
          <TemplateModal
            key={editing?._id || 'new'}
            editing={editing}
            activityOptions={formActivityOptions}
            onClose={() => { setModalOpen(false); setEditing(null); }}
            onSubmit={handleSubmit}
          />
        )}
      </AnimatePresence>
    </div>
  );
};

export default MailTemplateAdmin;
