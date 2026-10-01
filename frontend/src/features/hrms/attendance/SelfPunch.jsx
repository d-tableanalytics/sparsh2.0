import React, { useCallback, useEffect, useState } from 'react';
import { LogIn, LogOut, MapPin, Crosshair, Plus, Trash2, Loader2 } from 'lucide-react';
import {
  getSelfPunchToday, selfPunch, getOfficeLocations, saveOfficeLocations,
} from '../../../services/hrmsApi';
import { FIELD, LABEL } from '../internal/internalKit';
import { Btn } from '../internal/internalKit.jsx';

/**
 * Attendance ▸ self check-in / check-out, and the offices it is fenced to.
 *
 * The browser supplies the device's location; the SERVER decides whether it is inside one
 * of the company's offices and refuses the punch otherwise. This component only asks for
 * the location and shows the answer.
 */

/** The device's position, or a plain-language reason it could not be read. */
const readLocation = () => new Promise((resolve, reject) => {
  if (!navigator.geolocation) {
    reject(new Error('This browser cannot share its location, so check-in is not possible here.'));
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy }),
    (err) => reject(new Error(err.code === 1
      ? 'Location access is blocked. Allow location for this site in your browser, then try again.'
      : err.code === 3 ? 'Finding your location took too long. Move near a window or turn on GPS, then try again.'
        : 'Your location could not be read. Turn on location / GPS and try again.')),
    { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
});

const time = (hhmm) => hhmm || '—';

/** "Today" card: check in / check out from inside an office. */
export const SelfPunchCard = ({ scope, showSuccess, showError, onPunched }) => {
  const [day, setDay] = useState(null);
  const [problem, setProblem] = useState(null);
  const [working, setWorking] = useState(null);   // 'in' | 'out' | null

  const load = useCallback(async () => {
    try {
      const { data } = await getSelfPunchToday(scope);
      setDay(data); setProblem(null);
    } catch (err) {
      setProblem(err?.response?.data?.detail || null);
      setDay(null);
    }
  }, [scope]);
  useEffect(() => { load(); }, [load]);

  const go = async (action) => {
    setWorking(action);
    try {
      const where = await readLocation();
      const { data } = await selfPunch({ action, ...where }, scope);
      setDay(data);
      showSuccess(data.message);
      onPunched?.();
    } catch (err) {
      showError(err?.response?.data?.detail || err.message || 'Could not record that.');
    } finally {
      setWorking(null);
    }
  };

  if (!day && !problem) return null;
  if (problem) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-4 py-3 text-[12.5px] text-[var(--text-muted)]">
        <b className="text-[var(--text-main)]">Self check-in:</b> {problem}
      </div>
    );
  }
  const done = day.actual_in && day.actual_out;
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 flex flex-wrap items-center gap-4">
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Today · {day.work_date}</p>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-6 gap-y-1">
          <p className="text-[13px] text-[var(--text-main)]">
            In <b className="text-[16px]">{time(day.actual_in)}</b>
            {day.in_office && <span className="text-[11.5px] text-[var(--text-muted)]"> · {day.in_office}</span>}
          </p>
          <p className="text-[13px] text-[var(--text-main)]">
            Out <b className="text-[16px]">{time(day.actual_out)}</b>
            {day.out_office && <span className="text-[11.5px] text-[var(--text-muted)]"> · {day.out_office}</span>}
          </p>
          {day.late_minutes > 0 && (
            <span className="text-[11.5px] font-semibold text-[var(--accent-orange)]">{day.late_minutes} min late</span>
          )}
        </div>
        <p className="mt-1 flex items-center gap-1 text-[11px] text-[var(--text-muted)]">
          <MapPin size={11} />
          {day.offices.length
            ? `Works at: ${day.offices.map((o) => `${o.name} (${o.radius_m} m)`).join(', ')}`
            : 'No office location is set up yet — ask HR.'}
        </p>
      </div>
      <div className="flex gap-2">
        {day.locked ? (
          <span className="text-[12px] text-[var(--text-muted)]">Today is locked.</span>
        ) : done ? (
          <span className="text-[12.5px] font-semibold text-[var(--accent-green,#16a34a)]">Done for today ✓</span>
        ) : day.can_check_out ? (
          <Btn tone="primary" disabled={!!working} onClick={() => go('out')}>
            {working === 'out' ? <Loader2 size={14} className="animate-spin" /> : <LogOut size={14} />}
            {working === 'out' ? 'Finding your location…' : 'Check out'}
          </Btn>
        ) : (
          <Btn tone="primary" disabled={!!working || !day.can_check_in} onClick={() => go('in')}>
            {working === 'in' ? <Loader2 size={14} className="animate-spin" /> : <LogIn size={14} />}
            {working === 'in' ? 'Finding your location…' : 'Check in'}
          </Btn>
        )}
      </div>
    </div>
  );
};

/** HR: the offices a punch is allowed from. */
export const OfficeLocationsTab = ({ scope, companyId, showSuccess, showError }) => {
  const [rows, setRows] = useState(null);
  const [saving, setSaving] = useState(false);
  const [locating, setLocating] = useState(null);

  useEffect(() => {
    if (!companyId) return;
    getOfficeLocations(scope).then(({ data }) => setRows(data?.offices || []))
      .catch((err) => { setRows([]); showError(err?.response?.data?.detail || 'Could not load offices.'); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  const set = (i, k) => (e) => setRows((r) => r.map((o, j) => (j === i ? { ...o, [k]: e.target.value } : o)));
  const here = async (i) => {
    setLocating(i);
    try {
      const { lat, lng, accuracy } = await readLocation();
      setRows((r) => r.map((o, j) => (j === i ? { ...o, lat: lat.toFixed(6), lng: lng.toFixed(6) } : o)));
      showSuccess(`Location filled in (accurate to about ${Math.round(accuracy)} m).`);
    } catch (err) {
      showError(err.message);
    } finally { setLocating(null); }
  };
  const save = async () => {
    setSaving(true);
    try {
      const { data } = await saveOfficeLocations({
        offices: rows.map((o) => ({ ...o, lat: Number(o.lat), lng: Number(o.lng), radius_m: Number(o.radius_m) })),
      }, scope);
      setRows(data.offices);
      showSuccess('Office locations saved. Staff can check in from inside them.');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the offices.');
    } finally { setSaving(false); }
  };

  if (rows === null) return <p className="text-[12.5px] text-[var(--text-muted)]">Loading…</p>;
  return (
    <div className="space-y-3">
      <p className="text-[12.5px] text-[var(--text-muted)]">
        Staff can check themselves in and out only from inside one of these places. Stand in the
        office and press <b>Use my current location</b>, or paste the coordinates from Google Maps.
        The radius is how far from that point still counts as “in the office”.
      </p>
      {!rows.length && (
        <p className="rounded-lg border border-dashed border-[var(--border)] px-4 py-3 text-[12.5px] text-[var(--text-muted)]">
          No office yet — self check-in is switched off until you add one.
        </p>
      )}
      {rows.map((o, i) => (
        <div key={o.id || i} className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-3 grid grid-cols-1 sm:grid-cols-[1.4fr_1fr_1fr_0.8fr_auto] gap-3 items-end">
          <div>
            <label className={LABEL}>Office name</label>
            <input className={FIELD} value={o.name} onChange={set(i, 'name')} placeholder="Pune HQ" />
          </div>
          <div>
            <label className={LABEL}>Latitude</label>
            <input className={FIELD} value={o.lat} onChange={set(i, 'lat')} placeholder="18.520400" inputMode="decimal" />
          </div>
          <div>
            <label className={LABEL}>Longitude</label>
            <input className={FIELD} value={o.lng} onChange={set(i, 'lng')} placeholder="73.856700" inputMode="decimal" />
          </div>
          <div>
            <label className={LABEL}>Radius (m)</label>
            <input className={FIELD} type="number" min="25" max="5000" step="25" value={o.radius_m} onChange={set(i, 'radius_m')} />
          </div>
          <div className="flex gap-1.5">
            <Btn disabled={locating !== null} onClick={() => here(i)} title="Fill from where this device is now">
              {locating === i ? <Loader2 size={13} className="animate-spin" /> : <Crosshair size={13} />} Use my current location
            </Btn>
            <Btn onClick={() => setRows((r) => r.filter((_, j) => j !== i))} title="Remove this office"><Trash2 size={13} /></Btn>
          </div>
          {o.lat && o.lng && (
            <a className="sm:col-span-5 text-[11.5px] font-semibold text-[var(--accent-indigo)] hover:underline"
              href={`https://www.google.com/maps?q=${o.lat},${o.lng}`} target="_blank" rel="noreferrer">
              Check this point on Google Maps →
            </a>
          )}
        </div>
      ))}
      <div className="flex justify-between gap-2">
        <Btn onClick={() => setRows((r) => [...r, { name: '', lat: '', lng: '', radius_m: 200 }])}>
          <Plus size={13} /> Add an office
        </Btn>
        <Btn tone="primary" disabled={saving} onClick={save}>{saving ? 'Saving…' : 'Save offices'}</Btn>
      </div>
    </div>
  );
};
