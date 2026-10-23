import React, { useCallback, useEffect, useState } from 'react';
import { CalendarOff, Plus, Trash2 } from 'lucide-react';
import { CAP } from '../access';
import { HrmsLoading } from '../common/HrmsStates';
import {
  addHrmsHoliday, getEmployeeMasterLists, getHrmsHolidays, removeHrmsHoliday,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, day } from '../internal/internalKit';
import { Btn, Chip } from '../internal/internalKit.jsx';
import { errorDetail } from './attendanceRules';

/**
 * HRMS ▸ Attendance ▸ Holidays (Phase 1 FRD §5 "Holiday Calendar: Holiday Date; Name;
 * Entity/Location applicability").
 *
 * The same company calendar HRMS Settings shows, kept here too because HR maintains the
 * attendance calendar and does not hold the settings capability. A holiday with no calendar
 * and no locations applies to everyone; otherwise it applies only to people whose holiday
 * calendar / work location (Employee Master ▸ Work setup) match. Attendance then marks the
 * day as a Holiday for them, and payroll pays it.
 */
const EMPTY = { holiday_date: '', holiday_name: '', calendar: '', locations: [] };

const HolidayCalendar = ({ scope, companyId, can, showSuccess, showError }) => {
  const canWrite = can(CAP.LEAVE_POLICY_MANAGE) || can(CAP.SETTINGS_WRITE);
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(thisYear);
  const [rows, setRows] = useState(null);
  const [lists, setLists] = useState({ holiday_calendars: [], locations: [] });
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [{ data }, { data: masters }] = await Promise.all([
        getHrmsHolidays({ ...scope, year }),
        getEmployeeMasterLists(scope).catch(() => ({ data: {} })),
      ]);
      setRows(data?.holidays || []);
      setLists({ holiday_calendars: masters?.holiday_calendars || [],
        locations: masters?.locations || [] });
    } catch {
      setRows([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, year]);

  useEffect(() => { load(); }, [load]);

  const add = async () => {
    if (!form.holiday_date || !form.holiday_name.trim()) {
      showError('A holiday needs both a date and a name.');
      return;
    }
    setBusy(true);
    try {
      await addHrmsHoliday({ ...form, calendar: form.calendar || null }, scope);
      setForm(EMPTY);
      showSuccess('Holiday added.');
      load();
    } catch (err) {
      showError(errorDetail(err, 'Could not add that date.'));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (date) => {
    setBusy(true);
    try {
      await removeHrmsHoliday(date, scope);
      showSuccess('Holiday removed.');
      load();
    } catch (err) {
      showError(errorDetail(err, 'Could not remove that date.'));
    } finally {
      setBusy(false);
    }
  };

  const toggleLocation = (loc) => setForm((f) => ({
    ...f,
    locations: f.locations.includes(loc) ? f.locations.filter((x) => x !== loc) : [...f.locations, loc],
  }));

  if (rows === null) return <HrmsLoading />;

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-[14px] font-bold text-[var(--text-main)]">Holiday calendar</h3>
          <p className="mt-1 text-[12px] text-[var(--text-muted)] max-w-3xl">
            A holiday with no calendar and no locations applies to everyone. Pick a holiday
            calendar or locations to limit it to the people assigned to them in the Employee
            Master. Their attendance shows the day as Holiday and payroll pays it.
          </p>
        </div>
        <select aria-label="Calendar year" value={year} onChange={(e) => setYear(Number(e.target.value))}
          className="h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]">
          {[thisYear - 1, thisYear, thisYear + 1].map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>

      {canWrite && (
        <div className="rounded-lg border border-[var(--border)] p-3 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className={LABEL} htmlFor="att-hol-date">Date</label>
              <input id="att-hol-date" type="date" className={FIELD} value={form.holiday_date}
                onChange={(e) => setForm((f) => ({ ...f, holiday_date: e.target.value }))} />
            </div>
            <div>
              <label className={LABEL} htmlFor="att-hol-name">Name</label>
              <input id="att-hol-name" className={FIELD} placeholder="Ganesh Chaturthi" value={form.holiday_name}
                onChange={(e) => setForm((f) => ({ ...f, holiday_name: e.target.value }))} />
            </div>
            <div>
              <label className={LABEL} htmlFor="att-hol-cal">Holiday calendar</label>
              <select id="att-hol-cal" className={FIELD} value={form.calendar}
                onChange={(e) => setForm((f) => ({ ...f, calendar: e.target.value }))}>
                <option value="">Everyone</option>
                {lists.holiday_calendars.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>
          {lists.locations.length > 0 && (
            <div>
              <span className={LABEL}>Only these locations (optional)</span>
              <div className="flex flex-wrap gap-1.5">
                {lists.locations.map((loc) => {
                  const on = form.locations.includes(loc);
                  return (
                    <button key={loc} type="button" aria-pressed={on} onClick={() => toggleLocation(loc)}
                      className={`px-2.5 h-7 rounded-full border text-[11.5px] font-semibold
                        ${on ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo)]/10 text-[var(--accent-indigo)]'
                          : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
                      {loc}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          <div className="flex justify-end">
            <Btn tone="primary" onClick={add} disabled={busy}><Plus size={14} /> Add holiday</Btn>
          </div>
        </div>
      )}

      {rows.length === 0 ? (
        <p className="flex items-center gap-2 text-[12px] text-[var(--text-muted)]">
          <CalendarOff size={14} /> No holidays recorded for {year}.
        </p>
      ) : (
        <ul className="divide-y divide-[var(--border)] rounded-lg border border-[var(--border)]">
          {rows.map((r) => (
            <li key={r.holiday_date} className="flex items-center gap-3 px-3 py-2 text-[12.5px] flex-wrap">
              <span className="font-semibold text-[var(--text-main)] w-28">{day(r.holiday_date)}</span>
              <span className="flex-1 min-w-[8rem] text-[var(--text-main)]">{r.holiday_name}</span>
              {r.calendar ? <Chip tone="accent">{r.calendar}</Chip> : <Chip tone="neutral">Everyone</Chip>}
              {(r.locations || []).map((loc) => <Chip key={loc} tone="neutral">{loc}</Chip>)}
              {canWrite && (
                <button type="button" aria-label={`Remove ${r.holiday_name}`} disabled={busy}
                  onClick={() => remove(r.holiday_date)}
                  className="text-[var(--text-muted)] hover:opacity-70 disabled:opacity-50">
                  <Trash2 size={13} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
};

export default HolidayCalendar;
