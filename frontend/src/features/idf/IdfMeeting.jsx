import React, { useCallback, useEffect, useState } from 'react';
import { CalendarCheck, Video, MapPin, Check, X, Clock, Pencil, UserCheck, UserX, HelpCircle } from 'lucide-react';
import { useNotification } from '../../context/NotificationContext';
import { getIdfMeeting, rescheduleIdfMeeting, rsvpIdfMeeting } from '../../services/idfApi';
import { CARD, FIELD } from './idfKit';

/* ─────────────────────────────────────────────────────────────
   Inter-Departmental Feedback ▸ the results meeting of a cycle: when, the link and venue, who
   is coming. Invitees reply Attending / Can't attend; HR, Client Admin and the MD reschedule it
   or change its link / venue (everyone is emailed). Used on Feedback Cycles and the Calendar.
   ───────────────────────────────────────────────────────────── */

const LABEL = 'text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]';
const fmtDate = (d) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' }) : '—');
const fmtTime = (t, add = 0) => {
  if (!t) return '';
  const [h, m] = t.split(':').map(Number);
  const mins = h * 60 + m + add;
  const hh = Math.floor(mins / 60) % 24; const mm = mins % 60;
  return `${((hh + 11) % 12) + 1}:${String(mm).padStart(2, '0')} ${hh < 12 ? 'am' : 'pm'}`;
};
const RESP = {
  attending: { label: 'Attending', icon: UserCheck, c: 'var(--accent-green)', bg: 'var(--accent-green-bg)' },
  declined: { label: "Can't attend", icon: UserX, c: 'var(--accent-red)', bg: 'var(--accent-red-bg)' },
  pending: { label: 'No reply yet', icon: HelpCircle, c: 'var(--text-muted)', bg: 'var(--input-bg)' },
};

const RescheduleDialog = ({ m, cid, onClose, onSaved }) => {
  const { showSuccess, showError } = useNotification();
  const [f, setF] = useState({ date: m.date, time: m.time, duration: m.duration, mode: m.mode,
    meeting_link: m.meeting_link, venue: m.venue, note: '' });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const { data } = await rescheduleIdfMeeting(m.cycle_id, { ...f, duration: Number(f.duration) }, cid);
      showSuccess('Meeting updated — every invitee has been emailed.');
      onSaved(data);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not update the meeting.');
    } finally {
      setBusy(false);
    }
  };
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="fixed inset-0 z-[310] bg-black/40 flex items-center justify-center p-4" onClick={() => !busy && onClose()}>
      <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" className="w-full max-w-lg rounded-2xl bg-[var(--bg-card)] shadow-2xl overflow-hidden">
        <div className="flex items-start gap-3 px-5 py-4 border-b border-[var(--border)]">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]"><CalendarCheck size={17} /></span>
          <div className="flex-1 min-w-0">
            <h3 className="text-[15px] font-black text-[var(--text-main)]">Reschedule the results meeting</h3>
            <p className="text-[11.5px] text-[var(--text-muted)]">Every invitee is emailed the new details and asked to reply again.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]"><X size={17} /></button>
        </div>
        <div className="px-5 py-4 grid grid-cols-1 sm:grid-cols-3 gap-3">
          <label className="space-y-1 sm:col-span-1"><span className={LABEL}>Date</span>
            <input type="date" className={`${FIELD} w-full`} value={f.date} onChange={set('date')} /></label>
          <label className="space-y-1"><span className={LABEL}>Start (IST)</span>
            <input type="time" className={`${FIELD} w-full`} value={f.time} onChange={set('time')} /></label>
          <label className="space-y-1"><span className={LABEL}>Minutes</span>
            <input type="number" min={15} max={240} step={15} className={`${FIELD} w-full`} value={f.duration} onChange={set('duration')} /></label>
          <label className="space-y-1"><span className={LABEL}>Type</span>
            <select className={`${FIELD} w-full`} value={f.mode} onChange={set('mode')}>
              <option value="online">Online</option><option value="in_person">In person</option><option value="both">Both</option>
            </select></label>
          <label className="space-y-1 sm:col-span-2"><span className={LABEL}>Meeting link</span>
            <input className={`${FIELD} w-full`} placeholder="https://meet.google.com/…" value={f.meeting_link} onChange={set('meeting_link')} /></label>
          <label className="space-y-1 sm:col-span-3"><span className={LABEL}>Venue</span>
            <input className={`${FIELD} w-full`} placeholder="e.g. Conference room 1" value={f.venue} onChange={set('venue')} /></label>
          <label className="space-y-1 sm:col-span-3"><span className={LABEL}>Note to the invitees (optional)</span>
            <input className={`${FIELD} w-full`} placeholder="e.g. Moved so the HR HOD can attend." value={f.note} onChange={set('note')} /></label>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3.5 border-t border-[var(--border)] bg-[var(--input-bg)]">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] hover:bg-[var(--bg-card)]">Cancel</button>
          <button type="button" onClick={save} disabled={busy || !f.date || !f.time}
            className="px-5 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-black disabled:opacity-50">{busy ? 'Saving…' : 'Save and notify'}</button>
        </div>
      </div>
    </div>
  );
};

/** The results meeting card: details, RSVP for an invitee, reschedule for HR / Admin / MD. */
const ResultsMeetingCard = ({ cycleId, companyId, compact = false }) => {
  const { showSuccess, showError } = useNotification();
  const [m, setM] = useState(null);
  const [missing, setMissing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await getIdfMeeting(cycleId, companyId);
      setM(data); setMissing(false);
    } catch {
      setMissing(true);
    }
  }, [cycleId, companyId]);
  // Fetch on open; state is set only after the request returns.
  useEffect(() => { load(); }, [load]);

  const reply = async (response) => {
    setBusy(true);
    try {
      const { data } = await rsvpIdfMeeting(cycleId, { response, reason: response === 'declined' ? reason : '' });
      setM((x) => ({ ...x, ...data }));
      setDeclining(false); setReason('');
      showSuccess(response === 'attending' ? 'Thanks — you are attending.' : 'Sent — the organisers can find a better time.');
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not send your reply.');
    } finally {
      setBusy(false);
    }
  };

  if (missing || !m) return null;
  const isInvitee = !!m.is_invitee;
  const mine = m.my_response || 'pending';

  return (
    <div className={compact ? 'space-y-2.5' : `${CARD} p-4 space-y-3`}>
      {!compact && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-lg p-2 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]"><CalendarCheck size={16} /></span>
          <div className="flex-1 min-w-[200px]">
            <p className="text-[13.5px] font-black text-[var(--text-main)]">Results meeting</p>
            <p className="text-[11.5px] text-[var(--text-muted)]">The MD and all HODs review the results together.</p>
          </div>
          {m.can_manage && (
            <button type="button" onClick={() => setEditing(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] font-bold text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
              <Pencil size={12} /> Reschedule
            </button>
          )}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[12.5px]">
        <span className="inline-flex items-center gap-1.5 font-bold text-[var(--text-main)]"><Clock size={13} />
          {fmtDate(m.date)}, {fmtTime(m.time)} – {fmtTime(m.time, m.duration)} IST</span>
        {m.venue && <span className="inline-flex items-center gap-1.5 text-[var(--text-muted)]"><MapPin size={13} /> {m.venue}</span>}
        {m.meeting_link ? (
          <a href={m.meeting_link} target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent-indigo)] px-3 py-1 text-[11.5px] font-black text-white hover:opacity-90">
            <Video size={12} /> Join meeting
          </a>
        ) : m.mode !== 'in_person' && <span className="text-[11.5px] text-[var(--text-muted)]">No meeting link set{m.can_manage ? ' — add one with Reschedule' : ''}</span>}
      </div>

      {isInvitee && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--border)] px-3 py-2">
          <span className="text-[12px] font-bold text-[var(--text-main)]">Your reply:</span>
          <span className="rounded-full px-2 py-0.5 text-[10.5px] font-black" style={{ color: RESP[mine].c, background: RESP[mine].bg }}>{RESP[mine].label}</span>
          <span className="flex-1" />
          <button type="button" disabled={busy || mine === 'attending'} onClick={() => reply('attending')}
            className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2.5 py-1 text-[11.5px] font-bold text-[var(--accent-green)] hover:bg-[var(--accent-green-bg)] disabled:opacity-50">
            <Check size={12} /> Attending
          </button>
          <button type="button" disabled={busy} onClick={() => setDeclining((d) => !d)}
            className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2.5 py-1 text-[11.5px] font-bold text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] disabled:opacity-50">
            <X size={12} /> Can't attend
          </button>
          {declining && (
            <div className="flex w-full gap-2">
              <input className={`${FIELD} flex-1`} placeholder="Why? e.g. On leave that day" value={reason} onChange={(e) => setReason(e.target.value)} />
              <button type="button" disabled={busy || !reason.trim()} onClick={() => reply('declined')}
                className="rounded-lg bg-[var(--accent-red)] px-3 text-[11.5px] font-black text-white disabled:opacity-50">Send</button>
            </div>
          )}
        </div>
      )}

      {(m.can_manage || !compact) && (
        <div className="flex flex-wrap gap-1.5">
          {m.invitees.map((i) => {
            const r = RESP[i.response] || RESP.pending;
            const RIcon = r.icon;
            return (
              <span key={i.id} title={i.reason ? `Reason: ${i.reason}` : r.label}
                className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] px-2 py-0.5 text-[11px]">
                <RIcon size={11} style={{ color: r.c }} /> <b className="text-[var(--text-main)]">{i.name}</b>
                {i.reason && <span className="text-[var(--text-muted)]">· {i.reason}</span>}
              </span>
            );
          })}
        </div>
      )}
      {compact && m.can_manage && (
        <button type="button" onClick={() => setEditing(true)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[11.5px] font-bold text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
          <Pencil size={12} /> Reschedule
        </button>
      )}
      {editing && <RescheduleDialog m={m} cid={companyId} onClose={() => setEditing(false)}
        onSaved={(d) => { setM(d); setEditing(false); }} />}
    </div>
  );
};

export default ResultsMeetingCard;
