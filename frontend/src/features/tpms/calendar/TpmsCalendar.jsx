import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CalendarDays, Plus, RefreshCw, Inbox, X, Clock, Building2, Tag, Users2,
  UserCog, CheckCircle2, Paperclip, Upload, FileText, RotateCcw, Trash2, Pencil,
} from 'lucide-react';
import { DashboardHero, HeroButton, KpiTile, FilterSelect } from '../common/dashboardKit';
import ScheduleCalendarModal from '../../../components/calendar/ScheduleCalendarModal';
import { useAuth } from '../../../context/AuthContext';
import { useNotification } from '../../../context/NotificationContext';
import {
  getSchedules, getActivities, deleteSchedule, markLearnerDone, confirmCompletion,
  requestReschedule, getRescheduleRequests, decideRescheduleRequest,
  getScheduleUploads, uploadScheduleFile,
} from '../../../services/tpmsApi';

/* ─────────────────────────────────────────────────────────────
   TPMS ▸ Calendar — the module's core screen.

   Month grid of scheduled activities with the full lifecycle inline:
     • doers  → Mark Done / Request Reschedule / upload proof
     • staff  → Confirm Complete, approve or reject reschedule requests
     • admin  → edit / delete

   Completion is deliberately TWO-STEP: a doer marking done only sets
   `learner_done`; internal staff must confirm before the activity counts as
   Completed. See backend tpms_lifecycle_service.py.
   ───────────────────────────────────────────────────────────── */

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const STATUSES = ['Scheduled', 'Rescheduled', 'Cancelled', 'Completed', 'Lapsed'];

// TPMS status → ERP accent tokens. No hex literals: dark mode comes free.
const TONE = {
  Scheduled:   { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  Rescheduled: { c: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)', bd: 'var(--accent-yellow-border)' },
  Completed:   { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  Cancelled:   { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
  Lapsed:      { c: 'var(--text-muted)',    bg: 'var(--input-bg)',         bd: 'var(--border)' },
};
const toneOf = (s) => TONE[s] || TONE.Scheduled;

const ymd = (y, m, d) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;

const Badge = ({ status }) => {
  const t = toneOf(status);
  return (
    <span className="inline-flex items-center text-[10px] font-bold px-2 py-0.5 rounded-full border whitespace-nowrap"
      style={{ color: t.c, background: t.bg, borderColor: t.bd }}>
      {status}
    </span>
  );
};

/** Proof-of-work panel, shown only for activities the catalogue flags upload_required. */
const UploadBlock = ({ eventId, canUpload }) => {
  const [files, setFiles] = useState(null);
  const [busy, setBusy] = useState(false);
  const { showError, showSuccess } = useNotification();

  const load = useCallback(async () => {
    try {
      const { data } = await getScheduleUploads(eventId);
      setFiles(data.uploads || []);
    } catch { setFiles([]); }
  }, [eventId]);

  useEffect(() => { load(); }, [load]);

  const onPick = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 25 * 1024 * 1024) return showError('Max file size 25 MB');
    setBusy(true);
    try {
      await uploadScheduleFile(eventId, file);
      showSuccess('Uploaded');
      await load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Upload failed');
    } finally {
      setBusy(false);
      e.target.value = '';
    }
  };

  return (
    <div className="mt-3 rounded-xl border border-dashed border-[var(--border)] bg-[var(--input-bg)] p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11.5px] font-black text-[var(--text-main)] inline-flex items-center gap-1.5">
          <Paperclip size={12} /> Proof of work
        </span>
        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full border"
          style={files?.length
            ? { color: 'var(--accent-green)', background: 'var(--accent-green-bg)', borderColor: 'var(--accent-green-border)' }
            : { color: 'var(--accent-red)', background: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
          {files === null ? '…' : files.length ? `${files.length} file(s)` : 'Pending'}
        </span>
      </div>
      {files?.length > 0 && (
        <div className="space-y-1 mb-2">
          {files.map((f) => (
            <a key={f._id} href={f.url} target="_blank" rel="noreferrer"
              className="flex items-center gap-1.5 text-[11.5px] font-semibold text-[var(--accent-indigo)] hover:underline">
              <FileText size={12} /> {f.file_name}
              <span className="text-[10px] text-[var(--text-muted)] font-medium">
                {f.uploaded_by_name}{f.uploaded_at ? ` · ${String(f.uploaded_at).slice(0, 10)}` : ''}
              </span>
            </a>
          ))}
        </div>
      )}
      {canUpload && (
        <label className="inline-flex items-center gap-1.5 text-[11.5px] font-black text-[var(--accent-indigo)] cursor-pointer hover:underline">
          <Upload size={12} /> {busy ? 'Uploading…' : 'Upload file'}
          <input type="file" className="hidden" onChange={onPick} disabled={busy} />
        </label>
      )}
    </div>
  );
};

const TpmsCalendar = () => {
  const { user } = useAuth();
  const { showError, showSuccess } = useNotification();

  const role = (user?.role || '').toLowerCase();
  const isClient = role === 'clientadmin' || role === 'clientuser';
  const isAdmin = role === 'superadmin' || role === 'admin';
  const isStaffSide = !isClient;

  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);   // 1-12
  const [events, setEvents] = useState([]);
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);

  const [fActivity, setFActivity] = useState('');
  const [fStatus, setFStatus] = useState('');

  const [openDay, setOpenDay] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [requests, setRequests] = useState([]);
  const [showRequests, setShowRequests] = useState(false);
  const [rr, setRr] = useState(null);        // reschedule-request form target

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getSchedules({ year, month });
      setEvents(data.events || []);
    } catch (e) {
      showError(e.response?.data?.detail || 'Failed to load calendar');
    } finally {
      setLoading(false);
    }
  }, [year, month, showError]);

  const loadRequests = useCallback(async () => {
    if (!isStaffSide) return;
    try {
      const { data } = await getRescheduleRequests('Pending');
      setRequests(data.requests || []);
    } catch { /* non-fatal — the badge just stays empty */ }
  }, [isStaffSide]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadRequests(); }, [loadRequests]);
  useEffect(() => {
    getActivities().then(({ data }) => setActivities(data.activities || [])).catch(() => {});
  }, []);

  const filtered = useMemo(() => events.filter((e) =>
    (!fActivity || e.activity === fActivity) && (!fStatus || e.status === fStatus)), [events, fActivity, fStatus]);

  const byDate = useMemo(() => {
    const map = {};
    filtered.forEach((e) => { (map[e.date] ||= []).push(e); });
    return map;
  }, [filtered]);

  const stats = useMemo(() => {
    const s = { total: filtered.length };
    STATUSES.forEach((k) => { s[k] = filtered.filter((e) => e.status === k).length; });
    return s;
  }, [filtered]);

  const changeMonth = (delta) => {
    let m = month + delta, y = year;
    if (m < 1) { m = 12; y -= 1; }
    if (m > 12) { m = 1; y += 1; }
    setMonth(m); setYear(y);
  };

  const act = async (fn, okMsg) => {
    try {
      await fn();
      showSuccess(okMsg);
      setOpenDay(null);
      await load();
      await loadRequests();
    } catch (e) {
      showError(e.response?.data?.detail || 'Action failed');
    }
  };

  const submitReschedule = async () => {
    if (!rr?.new_date) return showError('Choose a new date');
    await act(() => requestReschedule(rr.id, {
      new_date: rr.new_date, new_time: rr.new_time, reason: rr.reason,
    }), 'Request sent — staff will review it');
    setRr(null);
  };

  /* ── grid ── */
  const firstDow = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();
  const todayStr = ymd(today.getFullYear(), today.getMonth() + 1, today.getDate());

  const kpis = [
    { value: stats.total,        label: 'Total',       sub: 'This month',   tone: 'plain',  icon: CalendarDays },
    { value: stats.Scheduled,    label: 'Scheduled',   sub: 'Upcoming',     tone: 'indigo', icon: Clock },
    { value: stats.Rescheduled,  label: 'Rescheduled', sub: 'Moved',        tone: 'yellow', icon: RotateCcw },
    { value: stats.Completed,    label: 'Completed',   sub: 'Done',         tone: 'green',  icon: CheckCircle2 },
    { value: stats.Cancelled,    label: 'Cancelled',   sub: 'Dropped',      tone: 'red',    icon: X },
    { value: stats.Lapsed,       label: 'Lapsed',      sub: 'Auto-lapsed',  tone: 'plain',  icon: Clock },
  ];

  return (
    <div className="space-y-5">
      <DashboardHero icon={CalendarDays} title="Calendar" subtitle="Scheduled activities, reminders & completion">
        {isStaffSide && (
          <HeroButton icon={Inbox} onClick={() => setShowRequests(true)}>
            Requests{requests.length ? ` (${requests.length})` : ''}
          </HeroButton>
        )}
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
        <HeroButton icon={Plus} onClick={() => setShowModal(true)}>Schedule</HeroButton>
      </DashboardHero>

      <div className="grid grid-cols-3 xl:grid-cols-6 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
        {/* month nav + filters */}
        <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <button onClick={() => changeMonth(-1)}
              className="px-3 py-1.5 rounded-lg border border-[var(--border)] text-[12px] font-black text-[var(--text-muted)] hover:bg-[var(--table-hover)]">‹</button>
            <span className="text-[14px] font-black text-[var(--text-main)] min-w-[150px] text-center">
              {MONTHS[month - 1]} {year}
            </span>
            <button onClick={() => changeMonth(1)}
              className="px-3 py-1.5 rounded-lg border border-[var(--border)] text-[12px] font-black text-[var(--text-muted)] hover:bg-[var(--table-hover)]">›</button>
          </div>
          <div className="flex-1" />
          <FilterSelect value={fActivity} onChange={setFActivity}
            options={[{ id: '', name: 'All Activities' }, ...activities.map((a) => ({ id: a.name, name: a.name }))]} />
          <FilterSelect value={fStatus} onChange={setFStatus}
            options={[{ id: '', name: 'All Status' }, ...STATUSES.map((s) => ({ id: s, name: s }))]} />
        </div>

        <div className="grid grid-cols-7 gap-px bg-[var(--border)]">
          {DOW.map((d) => (
            <div key={d} className="bg-[var(--table-header-bg)] px-2 py-2 text-center text-[11px] font-black text-[var(--text-muted)]">{d}</div>
          ))}
          {Array.from({ length: firstDow }).map((_, i) => <div key={`e${i}`} className="bg-[var(--bg-card)] min-h-[104px]" />)}
          {Array.from({ length: daysInMonth }).map((_, i) => {
            const day = i + 1;
            const ds = ymd(year, month, day);
            const evs = byDate[ds] || [];
            const isToday = ds === todayStr;
            return (
              <button key={ds} onClick={() => evs.length && setOpenDay(ds)}
                className={`bg-[var(--bg-card)] min-h-[104px] p-1.5 text-left align-top hover:bg-[var(--table-hover)] transition-colors ${evs.length ? 'cursor-pointer' : 'cursor-default'}`}>
                <div className={`text-[11.5px] font-black mb-1 ${isToday
                  ? 'inline-flex items-center justify-center w-6 h-6 rounded-full bg-[var(--accent-indigo)] text-white'
                  : 'text-[var(--text-muted)]'}`}>{day}</div>
                <div className="space-y-1">
                  {evs.slice(0, 3).map((e) => {
                    const t = toneOf(e.status);
                    return (
                      <div key={e.id} title={`${e.title} — ${e.status}`}
                        className="truncate text-[10px] font-bold px-1.5 py-0.5 rounded border"
                        style={{ color: t.c, background: t.bg, borderColor: t.bd }}>
                        {e.mine ? '📌 ' : ''}{e.time ? `${e.time} ` : ''}{e.title}
                      </div>
                    );
                  })}
                  {evs.length > 3 && (
                    <div className="text-[10px] font-bold text-[var(--text-muted)] px-1.5">+{evs.length - 3} more</div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
        {loading && <div className="px-5 py-3 text-[12px] font-bold text-[var(--text-muted)]">Loading…</div>}
      </div>

      {/* ── Day drawer ── */}
      {openDay && (
        <Overlay onClose={() => setOpenDay(null)} title={`Activities on ${openDay}`}>
          {(byDate[openDay] || []).map((e) => {
            const canAct = !['Completed', 'Cancelled', 'Lapsed'].includes(e.status);
            return (
              <div key={e.id} className="rounded-xl border border-[var(--border)] p-3 mb-2.5">
                <div className="flex items-start justify-between gap-2 mb-1.5">
                  <h4 className="text-[13.5px] font-black text-[var(--text-main)]">{e.title}</h4>
                  <div className="flex items-center gap-1.5">
                    {e.reschedule_count > 0 && (
                      <span className="text-[10px] font-bold text-[var(--text-muted)]">↻ {e.reschedule_count}</span>
                    )}
                    <Badge status={e.status} />
                  </div>
                </div>
                <div className="text-[11.5px] text-[var(--text-muted)] font-semibold space-y-0.5">
                  {e.time && <div className="flex items-center gap-1.5"><Clock size={11} /> {e.time}</div>}
                  {e.activity && <div className="flex items-center gap-1.5"><Tag size={11} /> {e.activity}</div>}
                  {e.company && <div className="flex items-center gap-1.5"><Building2 size={11} /> {e.company}</div>}
                  {!!e.departments?.length && <div className="flex items-center gap-1.5"><Users2 size={11} /> {e.departments.join(', ')}</div>}
                  {!!e.staff_ids?.length && <div className="flex items-center gap-1.5"><UserCog size={11} /> {e.staff_ids.length} staff assigned</div>}
                </div>

                {e.learner_done && e.status !== 'Completed' && (
                  <div className="mt-2 rounded-lg px-2.5 py-1.5 text-[11px] font-bold"
                    style={{ color: 'var(--accent-green)', background: 'var(--accent-green-bg)' }}>
                    ✅ Marked done by the doer — awaiting staff confirmation
                  </div>
                )}

                {e.upload_required && <UploadBlock eventId={e.id} canUpload={canAct} />}

                <div className="flex flex-wrap gap-2 mt-3">
                  {isClient && canAct && !e.learner_done && (
                    <>
                      <Btn onClick={() => act(() => markLearnerDone(e.id), 'Marked done — staff will confirm')}>✅ Mark Done</Btn>
                      <Btn ghost onClick={() => setRr({ id: e.id, title: e.title, new_date: e.date, new_time: e.time, reason: '' })}>
                        🔄 Request Reschedule
                      </Btn>
                    </>
                  )}
                  {isStaffSide && e.learner_done && canAct && (
                    <Btn onClick={() => act(() => confirmCompletion(e.id), 'Completed')}>✔ Confirm Complete</Btn>
                  )}
                  {isAdmin && (
                    <Btn danger ghost onClick={() => {
                      if (window.confirm('Delete this activity and everything derived from it?')) {
                        act(() => deleteSchedule(e.id), 'Deleted');
                      }
                    }}><Trash2 size={12} /> Delete</Btn>
                  )}
                </div>
              </div>
            );
          })}
        </Overlay>
      )}

      {/* ── Reschedule request (doer) ── */}
      {rr && (
        <Overlay onClose={() => setRr(null)} title="Request Reschedule" narrow>
          <p className="text-[12.5px] font-bold text-[var(--text-main)] mb-3">{rr.title}</p>
          <Field label="New Date">
            <input type="date" value={rr.new_date} onChange={(e) => setRr({ ...rr, new_date: e.target.value })} className={inputCls} />
          </Field>
          <Field label="New Time">
            <input type="time" value={rr.new_time || ''} onChange={(e) => setRr({ ...rr, new_time: e.target.value })} className={inputCls} />
          </Field>
          <Field label="Reason">
            <textarea rows={3} value={rr.reason} onChange={(e) => setRr({ ...rr, reason: e.target.value })}
              placeholder="Why reschedule?" className={inputCls} />
          </Field>
          <p className="text-[11px] text-[var(--text-muted)] font-semibold mb-3">
            Requests must be raised at least 12 hours before the activity. Staff will approve or reject.
          </p>
          <div className="flex justify-end gap-2">
            <Btn ghost onClick={() => setRr(null)}>Cancel</Btn>
            <Btn onClick={submitReschedule}>Send Request</Btn>
          </div>
        </Overlay>
      )}

      {/* ── Pending requests (staff) ── */}
      {showRequests && (
        <Overlay onClose={() => setShowRequests(false)} title="Reschedule Requests" narrow>
          {requests.length === 0
            ? <p className="text-[12.5px] font-bold text-[var(--text-muted)]">No pending requests.</p>
            : requests.map((r) => (
              <div key={r._id} className="rounded-xl border border-[var(--border)] p-3 mb-2.5">
                <h4 className="text-[13px] font-black text-[var(--text-main)]">{r.title || r.activity}</h4>
                <div className="text-[11.5px] text-[var(--text-muted)] font-semibold mb-1.5">{r.activity} · {r.company_name}</div>
                <div className="text-[12px] font-bold text-[var(--text-main)]">
                  📅 {r.old_date} {r.old_time} → <span className="text-[var(--accent-indigo)]">{r.new_date} {r.new_time}</span>
                </div>
                <div className="text-[11.5px] text-[var(--text-muted)] font-semibold mt-1">
                  🙋 {r.requested_by_name}{r.reason ? ` — ${r.reason}` : ''}
                </div>
                <div className="flex gap-2 mt-2.5">
                  <Btn onClick={() => act(() => decideRescheduleRequest(r._id, true), 'Approved')}>✔ Approve</Btn>
                  <Btn danger ghost onClick={() => {
                    const note = window.prompt('Reason for rejection (optional):') || '';
                    act(() => decideRescheduleRequest(r._id, false, note), 'Rejected');
                  }}>✕ Reject</Btn>
                </div>
              </div>
            ))}
        </Overlay>
      )}

      <ScheduleCalendarModal
        mode="tpms"
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        onSaved={() => { load(); }}
      />
    </div>
  );
};

/* ── small local primitives ── */
const inputCls = 'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12.5px] font-semibold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]';

const Field = ({ label, children }) => (
  <div className="mb-3">
    <label className="block text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wide mb-1">{label}</label>
    {children}
  </div>
);

const Btn = ({ children, onClick, ghost, danger }) => (
  <button onClick={onClick}
    className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-[11.5px] font-black transition-all active:scale-95 ${
      ghost
        ? `border ${danger ? 'border-[var(--accent-red-border)] text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)]'
                          : 'border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--table-hover)]'}`
        : 'bg-[var(--accent-indigo)] text-white hover:opacity-90'}`}>
    {children}
  </button>
);

const Overlay = ({ title, children, onClose, narrow }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={onClose}>
    <div onClick={(e) => e.stopPropagation()}
      className={`w-full ${narrow ? 'max-w-md' : 'max-w-2xl'} rounded-2xl bg-[var(--bg-card)] shadow-2xl overflow-hidden`}>
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-[var(--border)]">
        <h3 className="text-[14px] font-black text-[var(--text-main)]">{title}</h3>
        <button onClick={onClose} className="p-1 rounded-lg text-[var(--text-muted)] hover:bg-[var(--table-hover)]"><X size={17} /></button>
      </div>
      <div className="px-5 py-4 max-h-[65vh] overflow-y-auto">{children}</div>
    </div>
  </div>
);

export default TpmsCalendar;
