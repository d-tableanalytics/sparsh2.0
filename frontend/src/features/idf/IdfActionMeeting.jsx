import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CalendarPlus, CalendarCheck, Video, MapPin, Clock, Check, X, Pencil, UserCheck, UserX, HelpCircle, AlertTriangle, ArrowRight } from 'lucide-react';
import { useNotification } from '../../context/NotificationContext';
import { getIdfActionMeeting, scheduleIdfActionMeeting, rsvpIdfActionMeeting, getIdfActionMeetingOptions } from '../../services/idfApi';
import { FIELD } from './idfKit';

/* ─────────────────────────────────────────────────────────────
   Inter-Departmental Feedback ▸ an ACTION PLAN's meeting (Red repair within 7 days, Amber 30-minute
   interface meeting within 15 days, company-wide repair). "Schedule meeting" opens a proposal —
   title, invitees, a date inside the window, the Setup link / venue — to adjust and save.
   Invitees reply; the owner, HR or the MD reschedule. Used in the action dialog and the Calendar.
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

const ScheduleDialog = ({ actionId, companyId, start, people, onClose, onSaved }) => {
  const { showSuccess, showError } = useNotification();
  const [f, setF] = useState({ title: start.title, date: start.date, time: start.time, duration: start.duration,
    meeting_link: start.meeting_link || '', venue: start.venue || '', note: '' });
  const [ids, setIds] = useState(new Set(start.invitee_ids || []));
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const toggle = (id) => setIds((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const save = async () => {
    setBusy(true);
    try {
      const { data } = await scheduleIdfActionMeeting(actionId, { ...f, duration: Number(f.duration), invitee_ids: [...ids] }, companyId);
      showSuccess('Meeting booked — every invitee has it in their calendar and an email.');
      onSaved(data);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not book the meeting.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="fixed inset-0 z-[320] bg-black/40 flex items-center justify-center p-4" onClick={() => !busy && onClose()}>
      <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true"
        className="w-full max-w-xl max-h-[92vh] flex flex-col rounded-2xl bg-[var(--bg-card)] shadow-2xl overflow-hidden">
        <div className="flex items-start gap-3 px-5 py-4 border-b border-[var(--border)]">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]"><CalendarPlus size={17} /></span>
          <div className="flex-1 min-w-0">
            <h3 className="text-[15px] font-black text-[var(--text-main)]">{start.booked ? 'Reschedule the meeting' : 'Schedule the meeting'}</h3>
            <p className="text-[11.5px] text-[var(--text-muted)]">
              Pre-filled from the action plan{start.deadline ? ` — book it before the target date, ${fmtDate(start.deadline)}` : ''}. Invitees get it in their calendar and by email.
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]"><X size={17} /></button>
        </div>
        <div className="px-5 py-4 space-y-3 overflow-y-auto">
          <label className="block space-y-1"><span className={LABEL}>Title</span>
            <input className={`${FIELD} w-full`} value={f.title} onChange={set('title')} /></label>
          <div className="grid grid-cols-3 gap-3">
            <label className="space-y-1"><span className={LABEL}>Date</span>
              <input type="date" className={`${FIELD} w-full`} value={f.date} onChange={set('date')} /></label>
            <label className="space-y-1"><span className={LABEL}>Start (IST)</span>
              <input type="time" className={`${FIELD} w-full`} value={f.time} onChange={set('time')} /></label>
            <label className="space-y-1"><span className={LABEL}>Minutes</span>
              <input type="number" min={15} max={240} step={15} className={`${FIELD} w-full`} value={f.duration} onChange={set('duration')} /></label>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="space-y-1"><span className={LABEL}>Meeting link</span>
              <input className={`${FIELD} w-full`} placeholder="https://meet.google.com/…" value={f.meeting_link} onChange={set('meeting_link')} /></label>
            <label className="space-y-1"><span className={LABEL}>Venue</span>
              <input className={`${FIELD} w-full`} placeholder="e.g. Conference room 1" value={f.venue} onChange={set('venue')} /></label>
          </div>
          <div className="space-y-1.5">
            <span className={LABEL}>Invitees ({ids.size})</span>
            <div className="max-h-44 overflow-y-auto rounded-lg border border-[var(--border)] divide-y divide-[var(--border)]">
              {people.map((p) => (
                <label key={p.id} className="flex items-center gap-2.5 px-3 py-1.5 text-[12.5px] cursor-pointer hover:bg-[var(--input-bg)]">
                  <input type="checkbox" className="accent-[var(--accent-indigo)]" checked={ids.has(p.id)} onChange={() => toggle(p.id)} />
                  <span className="text-[var(--text-main)]">{p.name}</span>
                  {(start.invitee_ids || []).includes(p.id) && <span className="ml-auto text-[10px] font-bold text-[var(--accent-indigo)]">suggested</span>}
                </label>
              ))}
            </div>
          </div>
          <label className="block space-y-1"><span className={LABEL}>Note to the invitees (optional)</span>
            <input className={`${FIELD} w-full`} placeholder="e.g. Please bring the last 3 months' hand-off issues." value={f.note} onChange={set('note')} /></label>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3.5 border-t border-[var(--border)] bg-[var(--input-bg)]">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] hover:bg-[var(--bg-card)]">Cancel</button>
          <button type="button" onClick={save} disabled={busy || !f.date || !f.time || ids.size < 2}
            className="px-5 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-black disabled:opacity-50">
            {busy ? 'Saving…' : start.booked ? 'Save and notify' : 'Book and invite'}
          </button>
        </div>
      </div>
    </div>
  );
};

/** The meeting of one action. In the Calendar (inCalendar): see / reply / reschedule. In the
 *  action plan: its booking status only — meetings are scheduled and managed in the Calendar. */
const ActionMeetingPanel = ({ actionId, companyId, inCalendar = false }) => {
  const { showSuccess, showError } = useNotification();
  const navigate = useNavigate();
  const [m, setM] = useState(null);
  const [dialog, setDialog] = useState(false);
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await getIdfActionMeeting(actionId, companyId);
      setM(data);
    } catch {
      setM(null);
    }
  }, [actionId, companyId]);
  useEffect(() => { load(); }, [load]);

  const reply = async (response) => {
    setBusy(true);
    try {
      const { data } = await rsvpIdfActionMeeting(actionId, { response, reason: response === 'declined' ? reason : '' });
      setM((x) => ({ ...x, ...data }));
      setDeclining(false); setReason('');
      showSuccess(response === 'attending' ? 'Thanks — you are attending.' : 'Sent — the organiser can find a better time.');
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not send your reply.');
    } finally {
      setBusy(false);
    }
  };

  if (!m || (!m.booked && !m.needed)) return null;

  if (!m.booked) {
    return (
      <div className="flex flex-wrap items-center gap-2.5 rounded-xl border border-dashed border-[var(--border)] px-3 py-2.5">
        <AlertTriangle size={14} className="text-[var(--accent-orange)]" />
        <span className="flex-1 min-w-[160px] text-[12px] text-[var(--text-main)]">
          <b>Meeting not booked yet.</b>{m.proposal?.deadline ? ` Book it before ${fmtDate(m.proposal.deadline)}` : ''}
          {m.can_manage && ' — from Calendar ▸ Schedule Action Plan Meeting.'}
        </span>
        {m.can_manage && (inCalendar ? (
          <button type="button" onClick={() => setDialog(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent-indigo)] px-3 py-1.5 text-[12px] font-black text-white hover:opacity-90">
            <CalendarPlus size={13} /> Schedule meeting
          </button>
        ) : (
          <button type="button" onClick={() => navigate('/calendar')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] font-bold text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
            Open Calendar <ArrowRight size={13} />
          </button>
        ))}
        {dialog && <ScheduleDialog actionId={actionId} companyId={companyId} start={m.proposal} people={m.people || []}
          onClose={() => setDialog(false)} onSaved={(d) => { setDialog(false); setM(d); }} />}
      </div>
    );
  }

  const mine = m.my_response || 'pending';
  return (
    <div className="space-y-2.5 rounded-xl border border-[var(--border)] px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12.5px]">
        <span className="inline-flex items-center gap-1.5 font-black text-[var(--text-main)]"><CalendarCheck size={13} className="text-[var(--accent-indigo)]" /> {m.title}</span>
        <span className="inline-flex items-center gap-1.5 font-bold text-[var(--text-main)]"><Clock size={13} />
          {fmtDate(m.date)}, {fmtTime(m.time)} – {fmtTime(m.time, m.duration)} IST</span>
        {m.venue && <span className="inline-flex items-center gap-1.5 text-[var(--text-muted)]"><MapPin size={13} /> {m.venue}</span>}
        {m.meeting_link && (
          <a href={m.meeting_link} target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent-indigo)] px-3 py-1 text-[11.5px] font-black text-white hover:opacity-90">
            <Video size={12} /> Join meeting
          </a>
        )}
      </div>
      {m.is_invitee && (
        <div className="flex flex-wrap items-center gap-2">
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
      <div className="flex flex-wrap items-center gap-1.5">
        {m.invitees.map((i) => {
          const r = RESP[i.response] || RESP.pending;
          const RIcon = r.icon;
          return (
            <span key={i.id} title={i.reason ? `Reason: ${i.reason}` : r.label}
              className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] px-2 py-0.5 text-[11px]">
              <RIcon size={11} style={{ color: r.c }} /> <b className="text-[var(--text-main)]">{i.name}</b>
            </span>
          );
        })}
        {m.can_manage && (inCalendar ? (
          <button type="button" onClick={() => setDialog(true)}
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1 text-[11.5px] font-bold text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
            <Pencil size={12} /> Reschedule
          </button>
        ) : (
          <button type="button" onClick={() => navigate('/calendar')}
            className="ml-auto inline-flex items-center gap-1 text-[11.5px] font-bold text-[var(--accent-indigo)] hover:underline">
            Manage in Calendar <ArrowRight size={12} />
          </button>
        ))}
      </div>
      {dialog && <ScheduleDialog actionId={actionId} companyId={companyId}
        start={{ ...m, invitee_ids: m.invitees.map((i) => i.id), booked: true }}
        people={m.people || m.invitees.map((i) => ({ id: i.id, name: i.name }))}
        onClose={() => setDialog(false)} onSaved={(d) => { setDialog(false); setM(d); }} />}
    </div>
  );
};

/** Calendar ▸ Schedule Action Plan Meeting: pick the Red / Amber / company-wide action plan, then
 *  the pre-filled form. The booked meeting stays linked to that action (its status shows there). */
export const ScheduleActionPlanMeeting = ({ date, onClose, onDone }) => {
  const { showError } = useNotification();
  const [opts, setOpts] = useState(null);
  const [picked, setPicked] = useState('');
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    getIdfActionMeetingOptions().then(({ data }) => setOpts(data.actions || []))
      .catch((e) => { showError(e?.response?.data?.detail || 'Could not load the action plans.'); setOpts([]); });
  }, [showError]);

  const next = async () => {
    try {
      const { data } = await getIdfActionMeeting(picked);
      if (data.booked) { showError('This action already has a meeting — reschedule it from the meeting in the Calendar.'); return; }
      const today = new Date().toISOString().slice(0, 10);
      setDetail({ ...data, proposal: { ...data.proposal, ...(date && date >= today ? { date } : {}) } });
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not prepare the meeting.');
    }
  };

  if (detail) {
    return <ScheduleDialog actionId={picked} start={detail.proposal} people={detail.people || []}
      onClose={onClose} onSaved={() => onDone()} />;
  }
  const label = (a) => `${a.band} · ${a.type} — ${a.feedback_from ? `${a.feedback_from} → ` : ''}${a.department}`;
  return (
    <div className="fixed inset-0 z-[320] bg-black/40 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" className="w-full max-w-lg rounded-2xl bg-[var(--bg-card)] shadow-2xl overflow-hidden">
        <div className="flex items-start gap-3 px-5 py-4 border-b border-[var(--border)]">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]"><CalendarPlus size={17} /></span>
          <div className="flex-1 min-w-0">
            <h3 className="text-[15px] font-black text-[var(--text-main)]">Schedule an action plan meeting</h3>
            <p className="text-[11.5px] text-[var(--text-muted)]">Choose the Red, Amber or company-wide action plan this meeting is for. It stays linked to that action.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]"><X size={17} /></button>
        </div>
        <div className="px-5 py-4 space-y-2 max-h-[60vh] overflow-y-auto">
          {!opts && <p className="text-[12.5px] text-[var(--text-muted)]">Loading action plans…</p>}
          {opts && !opts.length && (
            <p className="rounded-lg border border-dashed border-[var(--border)] px-3 py-6 text-center text-[12.5px] text-[var(--text-muted)]">
              No open Red, Amber or company-wide action plans for you to schedule.
            </p>
          )}
          {(opts || []).map((a) => (
            <label key={a.id} className={`flex items-start gap-3 rounded-xl border px-3 py-2.5 ${a.booked ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer hover:border-[var(--accent-indigo)]'}`}
              style={{ borderColor: picked === a.id ? 'var(--accent-indigo)' : 'var(--border)' }}>
              <input type="radio" name="idf-action" disabled={a.booked} checked={picked === a.id} onChange={() => setPicked(a.id)}
                className="mt-1 accent-[var(--accent-indigo)]" />
              <span className="min-w-0">
                <span className="block text-[12.5px] font-black text-[var(--text-main)]">{label(a)}</span>
                <span className="block text-[11px] text-[var(--text-muted)]">
                  Owner {a.owner_name || '—'} · target {fmtDate(a.target_date)}{a.booked ? ' · meeting already booked' : ''}
                </span>
              </span>
            </label>
          ))}
        </div>
        <div className="flex justify-end gap-2 px-5 py-3.5 border-t border-[var(--border)] bg-[var(--input-bg)]">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] hover:bg-[var(--bg-card)]">Cancel</button>
          <button type="button" onClick={next} disabled={!picked}
            className="inline-flex items-center gap-1.5 px-5 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-black disabled:opacity-50">
            Next <ArrowRight size={13} />
          </button>
        </div>
      </div>
    </div>
  );
};

export default ActionMeetingPanel;
