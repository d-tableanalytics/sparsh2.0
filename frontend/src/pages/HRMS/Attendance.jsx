import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CalendarCheck, LogIn, LogOut, Users, Clock, MapPin, Camera, Loader2,
  AlertTriangle, ChevronLeft, ChevronRight, ShieldCheck, Pencil, Timer,
  X, ImageOff,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import {
  getAttendance, punchAttendance, getTeamAttendance, addManualAttendance,
  getAttendanceSelfie,
} from '../../services/hrmsApi';
import { hasHrmsPermission } from '../../utils/hrmsAccess';
import { Avatar, StatTile, Field } from '../../components/hrms/hrmsUi';
import { inputCls, fmtDate } from '../../components/hrms/hrmsStyles';
import SelfieCaptureModal from '../../components/hrms/SelfieCaptureModal';

// HRMS ▸ Attendance. Tabs follow the reference project (My attendance · Team), with the punch
// toggle as the primary action.
//
// The punch is ONE button: the server owns whether the next tap opens or closes a segment, so
// the UI can never disagree with it about the current state. Everything shown here — first in,
// last out, hours — is derived server-side from the same segments, so a manual correction by HR
// changes the totals automatically.

const TABS = [
  { key: 'mine', label: 'My attendance', icon: CalendarCheck },
  { key: 'team', label: 'Team', icon: Users },
];

const hhmm = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
};

const hours = (minutes) => {
  if (!minutes) return '0h 00m';
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`;
};

const shiftMonth = (period, delta) => {
  const [y, m] = period.split('-').map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};

// Punch selfies are stored as PRIVATE S3 keys, never a public URL. Each chip fetches its own
// short-lived signed URL only when clicked, so opening a month view never fans out a request
// per photo. A segment with no key (manual entries, selfie-off policy) renders nothing.
const SelfieChips = ({ segments, onOpen }) => {
  const shots = [];
  (segments || []).forEach((s) => {
    if (s?.inSelfie) shots.push({ key: s.inSelfie, label: `In · ${hhmm(s.in)}` });
    if (s?.outSelfie) shots.push({ key: s.outSelfie, label: `Out · ${hhmm(s.out)}` });
  });
  if (!shots.length) return null;
  return (
    <>
      {shots.map((shot, i) => (
        <button key={`${shot.key}-${i}`} type="button" onClick={() => onOpen(shot.key, shot.label)}
          title={`View selfie (${shot.label})`}
          className="inline-flex items-center justify-center w-6 h-6 rounded-md border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] transition-colors">
          <Camera size={12} />
        </button>
      ))}
    </>
  );
};

const Attendance = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();

  const canSeeTeam = hasHrmsPermission(user, 'attendance', 'read');
  const canEnterManual = hasHrmsPermission(user, 'attendance', 'update');

  const [tab, setTab] = useState('mine');

  // My attendance
  const [month, setMonth] = useState(() => {
    const n = new Date();
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}`;
  });
  const [mine, setMine] = useState(null);
  const [loadingMine, setLoadingMine] = useState(true);
  const [punching, setPunching] = useState(false);
  const [error, setError] = useState('');
  const [selfieOpen, setSelfieOpen] = useState(false);

  // Team
  const [teamDate, setTeamDate] = useState('');
  const [team, setTeam] = useState(null);
  const [loadingTeam, setLoadingTeam] = useState(false);

  // Manual entry
  const [manualFor, setManualFor] = useState(null);
  const [manual, setManual] = useState({ punch_in: '09:00', punch_out: '', note: '' });
  const [savingManual, setSavingManual] = useState(false);

  // Selfie lightbox — { loading, url, label } or null.
  const [selfieView, setSelfieView] = useState(null);

  const openSelfie = async (key, label) => {
    if (!key) return;
    setSelfieView({ loading: true, url: '', label });
    try {
      const res = await getAttendanceSelfie(key);
      setSelfieView({ loading: false, url: res.data?.url || '', label });
    } catch {
      // A dead/expired key shows the graceful "unavailable" state rather than erroring the page.
      setSelfieView({ loading: false, url: '', label });
    }
  };

  const loadMine = useCallback(async () => {
    setLoadingMine(true);
    setError('');
    try {
      const res = await getAttendance({ month });
      setMine(res.data);
      if (!teamDate) setTeamDate(res.data.serverDate);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load attendance');
    } finally {
      setLoadingMine(false);
    }
  }, [month, teamDate]);

  useEffect(() => { loadMine(); }, [loadMine]);

  const loadTeam = useCallback(async () => {
    if (!canSeeTeam || !teamDate) return;
    setLoadingTeam(true);
    try {
      const res = await getTeamAttendance({ date: teamDate });
      setTeam(res.data);
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to load team attendance');
    } finally {
      setLoadingTeam(false);
    }
  }, [canSeeTeam, teamDate, showError]);

  useEffect(() => { if (tab === 'team') loadTeam(); }, [tab, loadTeam]);

  const settings = mine?.settings;
  const today = mine?.today;
  const isOpen = !!today?.open;

  // Geolocation is requested only when policy needs it — asking otherwise trains people to
  // dismiss the browser prompt.
  const getPosition = () =>
    new Promise((resolve) => {
      if (!settings?.geofence_enabled || !navigator.geolocation) return resolve(null);
      navigator.geolocation.getCurrentPosition(
        (pos) => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }),
        () => resolve(null),
        { enableHighAccuracy: true, timeout: 10000 },
      );
    });

  const doPunch = async (selfie) => {
    setPunching(true);
    try {
      const coords = await getPosition();
      const res = await punchAttendance({ ...(coords || {}), selfie: selfie || undefined });
      showSuccess(res.data.action === 'in' ? 'Punched in' : 'Punched out');
      loadMine();
    } catch (err) {
      showError(err.response?.data?.detail || 'Punch failed');
    } finally {
      setPunching(false);
    }
  };

  const onPunchClick = () => {
    if (settings?.selfie_required) setSelfieOpen(true);
    else doPunch(null);
  };

  const submitManual = async () => {
    if (!manual.punch_in) { showError('Punch in time is required'); return; }
    setSavingManual(true);
    try {
      await addManualAttendance({
        user_id: manualFor.userId,
        punch_date: teamDate,
        punch_in: manual.punch_in,
        punch_out: manual.punch_out || null,
        note: manual.note,
      });
      showSuccess(`Attendance recorded for ${manualFor.displayName}`);
      setManualFor(null);
      setManual({ punch_in: '09:00', punch_out: '', note: '' });
      loadTeam();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to record attendance');
    } finally {
      setSavingManual(false);
    }
  };

  const monthStats = useMemo(() => {
    const days = mine?.days ?? [];
    const worked = days.reduce((sum, d) => sum + (d.workedMinutes || 0), 0);
    return {
      present: days.filter((d) => (d.segments || []).length > 0).length,
      minutes: worked,
      avg: days.length ? Math.round(worked / days.length) : 0,
    };
  }, [mine]);

  return (
    <div className="p-6 sm:p-8 flex flex-col gap-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
            <CalendarCheck size={20} />
          </span>
          <div>
            <h1 className="text-xl sm:text-2xl font-black tracking-tight text-[var(--text-main)] leading-tight">
              Attendance
            </h1>
            <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
              Daily punches and worked hours
            </p>
          </div>
        </div>

        {/* Punch toggle — one button; the server decides in vs out. */}
        <button onClick={onPunchClick} disabled={punching || loadingMine}
          className={`flex items-center gap-2 px-6 py-3 rounded-xl text-[12px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] disabled:opacity-50 transition-all text-white ${
            isOpen ? 'bg-[var(--accent-red)]' : 'bg-[var(--accent-green)]'
          }`}>
          {punching ? <Loader2 size={16} className="animate-spin" />
            : isOpen ? <LogOut size={16} /> : <LogIn size={16} />}
          {isOpen ? 'Punch out' : 'Punch in'}
        </button>
      </div>

      {/* Policy strip — say what the rules are before someone hits them. */}
      {settings && (settings.geofence_enabled || settings.selfie_required) && (
        <div className="flex flex-wrap items-center gap-4 px-4 py-2.5 rounded-xl bg-[var(--input-bg)] border border-[var(--border)]">
          {settings.geofence_enabled && (
            <span className="flex items-center gap-1.5 text-[11.5px] font-bold text-[var(--text-muted)]">
              <MapPin size={13} /> Punching allowed within {settings.office_radius_meters} m of the office
            </span>
          )}
          {settings.selfie_required && (
            <span className="flex items-center gap-1.5 text-[11.5px] font-bold text-[var(--text-muted)]">
              <Camera size={13} /> Selfie required
            </span>
          )}
          <span className="flex items-center gap-1.5 text-[11.5px] font-bold text-[var(--text-muted)]">
            <Clock size={13} /> Shift {settings.shift_start}–{settings.shift_end}
          </span>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
          style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {TABS.filter((t) => t.key !== 'team' || canSeeTeam).map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-[11px] font-black uppercase tracking-widest transition-colors border ${
              tab === t.key
                ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]'
                : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)] hover:text-[var(--text-main)]'
            }`}>
            <t.icon size={14} /> {t.label}
          </button>
        ))}
      </div>

      {/* ── My attendance ── */}
      {tab === 'mine' && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatTile icon={Timer} label="Today" value={hours(today?.workedMinutes)} loading={loadingMine} />
            <StatTile icon={LogIn} label="First in today" value={hhmm(today?.firstIn)} loading={loadingMine} />
            <StatTile icon={CalendarCheck} label="Days present" value={monthStats.present} loading={loadingMine} />
            <StatTile icon={Clock} label="Month total" value={hours(monthStats.minutes)} loading={loadingMine} />
          </div>

          {/* Month picker */}
          <div className="flex items-center gap-2">
            <button onClick={() => setMonth((m) => shiftMonth(m, -1))}
              className="p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors"
              aria-label="Previous month">
              <ChevronLeft size={15} />
            </button>
            <span className="text-[12.5px] font-black text-[var(--text-main)] min-w-[130px] text-center">
              {new Date(`${month}-01T00:00:00`).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
            </span>
            <button onClick={() => setMonth((m) => shiftMonth(m, 1))}
              className="p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors"
              aria-label="Next month">
              <ChevronRight size={15} />
            </button>
          </div>

          <div className="rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full" style={{ minWidth: 640 }}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    {['Date', 'First in', 'Last out', 'Punches', 'Worked'].map((h) => (
                      <th key={h}
                        className="text-left px-4 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loadingMine && (
                    <tr><td colSpan={5} className="px-4 py-12 text-center">
                      <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
                        <Loader2 size={16} className="animate-spin" /> Loading…
                      </span>
                    </td></tr>
                  )}
                  {!loadingMine && (mine?.days ?? []).length === 0 && (
                    <tr><td colSpan={5} className="px-4 py-12 text-center">
                      <p className="text-[13px] font-bold text-[var(--text-main)]">No attendance this month.</p>
                    </td></tr>
                  )}
                  {!loadingMine && (mine?.days ?? []).map((d) => (
                    <tr key={d.punchDate}
                      className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                      <td className="px-4 py-3 text-[12.5px] font-bold text-[var(--text-main)]">
                        <span className="flex items-center gap-2">
                          {fmtDate(d.punchDate)}
                          {d.hasManual && (
                            <span className="px-1.5 py-0.5 rounded text-[8px] font-black uppercase tracking-widest border"
                              style={{ color: 'var(--accent-orange)', backgroundColor: 'var(--accent-orange-bg)', borderColor: 'var(--accent-orange-border)' }}>
                              HR entry
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[12.5px] font-semibold text-[var(--text-muted)]"
                        style={{ fontVariantNumeric: 'tabular-nums' }}>{hhmm(d.firstIn)}</td>
                      <td className="px-4 py-3 text-[12.5px] font-semibold text-[var(--text-muted)]"
                        style={{ fontVariantNumeric: 'tabular-nums' }}>
                        {d.open ? <span style={{ color: 'var(--accent-green)' }}>Still in</span> : hhmm(d.lastOut)}
                      </td>
                      <td className="px-4 py-3 text-[12.5px] font-semibold text-[var(--text-muted)]">
                        <span className="flex items-center gap-1.5 flex-wrap">
                          <span style={{ fontVariantNumeric: 'tabular-nums' }}>{(d.segments || []).length}</span>
                          <SelfieChips segments={d.segments} onOpen={openSelfie} />
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[12.5px] font-black text-[var(--text-main)]"
                        style={{ fontVariantNumeric: 'tabular-nums' }}>{hours(d.workedMinutes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ── Team ── */}
      {tab === 'team' && canSeeTeam && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <input type="date" value={teamDate} onChange={(e) => setTeamDate(e.target.value)}
              className={`${inputCls} w-auto`} />
            {team && (
              <div className="flex items-center gap-3 flex-wrap">
                <span className="text-[11.5px] font-black uppercase tracking-widest"
                  style={{ color: 'var(--accent-green)' }}>
                  {team.stats.present} present
                </span>
                <span className="text-[11.5px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                  {team.stats.notPunched} not punched
                </span>
                {team.stats.unlinked > 0 && (
                  <span className="text-[11.5px] font-bold text-[var(--text-muted)]">
                    · {team.stats.unlinked} employee(s) have no login and cannot punch
                  </span>
                )}
              </div>
            )}
          </div>

          <div className="rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full" style={{ minWidth: 760 }}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    {['Employee', 'Department', 'First in', 'Last out', 'Worked', ''].map((h, i) => (
                      <th key={i}
                        className="text-left px-4 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loadingTeam && (
                    <tr><td colSpan={6} className="px-4 py-12 text-center">
                      <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
                        <Loader2 size={16} className="animate-spin" /> Loading…
                      </span>
                    </td></tr>
                  )}
                  {!loadingTeam && (team?.rows ?? []).length === 0 && (
                    <tr><td colSpan={6} className="px-4 py-12 text-center">
                      <p className="text-[13px] font-bold text-[var(--text-main)]">No employees with a linked login.</p>
                      <p className="text-[12px] font-medium text-[var(--text-muted)] mt-1">
                        Link employees to their Sparsh account to track attendance.
                      </p>
                    </td></tr>
                  )}
                  {!loadingTeam && (team?.rows ?? []).map((r) => (
                    <tr key={r.userId}
                      className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3 min-w-0">
                          <Avatar name={r.fullName} photoUrl={r.photoUrl} size={32} />
                          <div className="min-w-0">
                            <div className="text-[12.5px] font-black text-[var(--text-main)] truncate">
                              {r.displayName}
                            </div>
                            <div className="text-[11px] font-medium text-[var(--text-muted)] truncate">
                              {r.designation || r.employeeCode}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]">
                        {r.department || '—'}
                      </td>
                      <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]"
                        style={{ fontVariantNumeric: 'tabular-nums' }}>
                        {r.present ? hhmm(r.attendance.firstIn) : (
                          <span className="text-[10px] font-black uppercase tracking-widest">Not punched</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]"
                        style={{ fontVariantNumeric: 'tabular-nums' }}>
                        {r.present ? (r.attendance.open
                          ? <span style={{ color: 'var(--accent-green)' }}>Still in</span>
                          : hhmm(r.attendance.lastOut)) : '—'}
                      </td>
                      <td className="px-4 py-3 text-[12px] font-black text-[var(--text-main)]"
                        style={{ fontVariantNumeric: 'tabular-nums' }}>
                        {r.present ? hours(r.attendance.workedMinutes) : '—'}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1.5">
                          <SelfieChips segments={r.attendance?.segments} onOpen={openSelfie} />
                          {canEnterManual && (
                            <button onClick={() => setManualFor(r)}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--border)] text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] transition-colors">
                              <Pencil size={11} /> Record
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* Manual entry */}
      {manualFor && (
        <div className="fixed inset-0 z-[350] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setManualFor(null)} />
          <div className="relative w-full max-w-md rounded-[24px] bg-[var(--bg-card)] border border-[var(--border)] shadow-2xl overflow-hidden">
            <div className="px-5 py-4 border-b border-[var(--border)] bg-[var(--table-header-bg)]">
              <h2 className="text-[14px] font-black tracking-tight text-[var(--text-main)]">
                Record attendance
              </h2>
              <p className="text-[11.5px] font-bold text-[var(--text-muted)] mt-0.5">
                {manualFor.displayName} · {fmtDate(teamDate)}
              </p>
            </div>
            <div className="p-5 flex flex-col gap-3.5">
              <div className="grid grid-cols-2 gap-3.5">
                <Field label="Punch in" required>
                  <input type="time" className={inputCls} value={manual.punch_in}
                    onChange={(e) => setManual({ ...manual, punch_in: e.target.value })} />
                </Field>
                <Field label="Punch out">
                  <input type="time" className={inputCls} value={manual.punch_out}
                    onChange={(e) => setManual({ ...manual, punch_out: e.target.value })} />
                </Field>
              </div>
              <Field label="Reason">
                <input className={inputCls} value={manual.note}
                  placeholder="Missed punch, off-site visit…"
                  onChange={(e) => setManual({ ...manual, note: e.target.value })} />
              </Field>
              <p className="flex items-start gap-2 text-[11px] font-medium text-[var(--text-muted)]">
                <ShieldCheck size={13} className="mt-0.5 shrink-0" />
                Recorded against your name and counted by payroll exactly like a self-punch.
              </p>
              <div className="flex items-center justify-end gap-2.5 pt-1">
                <button onClick={() => setManualFor(null)}
                  className="px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                  Cancel
                </button>
                <button onClick={submitManual} disabled={savingManual}
                  className="flex items-center gap-2 px-5 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
                  {savingManual && <Loader2 size={13} className="animate-spin" />} Record
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Selfie viewer — lazily loads the signed URL for the chip that was clicked. */}
      {selfieView && (
        <div className="fixed inset-0 z-[350] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setSelfieView(null)} />
          <div className="relative w-full max-w-sm rounded-[24px] bg-[var(--bg-card)] border border-[var(--border)] shadow-2xl overflow-hidden">
            <div className="px-5 py-4 border-b border-[var(--border)] bg-[var(--table-header-bg)] flex items-center justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-[14px] font-black tracking-tight text-[var(--text-main)]">
                  Punch selfie
                </h2>
                {selfieView.label && (
                  <p className="text-[11.5px] font-bold text-[var(--text-muted)] mt-0.5 truncate">
                    {selfieView.label}
                  </p>
                )}
              </div>
              <button onClick={() => setSelfieView(null)} aria-label="Close"
                className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors shrink-0">
                <X size={15} />
              </button>
            </div>
            <div className="p-5 flex items-center justify-center min-h-[240px]">
              {selfieView.loading && (
                <Loader2 size={22} className="animate-spin text-[var(--text-muted)]" />
              )}
              {!selfieView.loading && selfieView.url && (
                <img src={selfieView.url} alt="Punch selfie"
                  className="max-h-[60vh] w-auto rounded-xl border border-[var(--border)] object-contain" />
              )}
              {!selfieView.loading && !selfieView.url && (
                <span className="flex flex-col items-center gap-2 text-[12px] font-bold text-[var(--text-muted)]">
                  <ImageOff size={20} /> Selfie unavailable
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      <SelfieCaptureModal
        isOpen={selfieOpen}
        onClose={() => setSelfieOpen(false)}
        title={isOpen ? 'Selfie to punch out' : 'Selfie to punch in'}
        onCapture={(shot) => { setSelfieOpen(false); doPunch(shot); }}
      />
    </div>
  );
};

export default Attendance;
