import React, { useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  ArrowLeft, Pencil, Mail, Phone, MapPin, Building2, Briefcase, CalendarDays,
  ShieldCheck, History, Loader2, AlertTriangle, Lock, Plus, User,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import {
  getEmployee, getEmployeeEvents, addEmployeeEvent, getHrmsOptions,
} from '../../services/hrmsApi';
import { hasHrmsPermission } from '../../utils/hrmsAccess';
import { StatusBadge, Avatar, Field } from '../../components/hrms/hrmsUi';
import { inputCls, fmtDate, fmtDateTime } from '../../components/hrms/hrmsStyles';
import EmployeeFormModal from '../../components/hrms/EmployeeFormModal';

// HRMS ▸ Employee profile.
//
// Tabs mirror the reference project (Personal · Job · Statutory · Timeline). The Statutory tab
// is the reason the API masks server-side: a reader without employee-record permission gets
// masked identifiers and no bank/salary at all, and the tab says so rather than showing blanks.
//
// The Timeline is the piece a single mutable row can't give you — a chronology of what actually
// happened to this record, written by the backend on every change.

const TABS = [
  { key: 'personal', label: 'Personal', icon: User },
  { key: 'job', label: 'Job', icon: Briefcase },
  { key: 'statutory', label: 'Statutory', icon: ShieldCheck },
  { key: 'timeline', label: 'Timeline', icon: History },
];

const EVENT_TYPES = [
  { value: 'note', label: 'Note' },
  { value: 'promotion', label: 'Promotion' },
  { value: 'transfer', label: 'Transfer' },
  { value: 'confirmation', label: 'Confirmation' },
];

const EVENT_TONE = {
  created: 'var(--accent-indigo)',
  updated: 'var(--text-muted)',
  status_change: 'var(--accent-yellow)',
  exit: 'var(--accent-red)',
  promotion: 'var(--accent-green)',
  transfer: 'var(--accent-orange)',
  confirmation: 'var(--accent-green)',
  note: 'var(--text-muted)',
};

const Row = ({ label, value, mono }) => (
  <div className="flex flex-col gap-1 py-2.5 border-b border-[var(--border)] last:border-0">
    <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
      {label}
    </span>
    <span
      className="text-[13px] font-semibold text-[var(--text-main)] break-words"
      style={mono ? { fontVariantNumeric: 'tabular-nums' } : undefined}
    >
      {value || '—'}
    </span>
  </div>
);

const EmployeeProfile = () => {
  const { employeeCode } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();

  const canEdit = hasHrmsPermission(user, 'hrms', 'update');

  const [employee, setEmployee] = useState(null);
  const [events, setEvents] = useState([]);
  const [options, setOptions] = useState(null);
  const [tab, setTab] = useState('personal');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showEdit, setShowEdit] = useState(false);

  // Manual timeline entry.
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteType, setNoteType] = useState('note');
  const [noteText, setNoteText] = useState('');
  const [noteDate, setNoteDate] = useState('');
  const [savingNote, setSavingNote] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [empRes, evRes] = await Promise.all([
        getEmployee(employeeCode),
        getEmployeeEvents(employeeCode),
      ]);
      setEmployee(empRes.data);
      setEvents(evRes.data || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load employee');
    } finally {
      setLoading(false);
    }
  }, [employeeCode]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    getHrmsOptions().then((r) => setOptions(r.data)).catch(() => {});
  }, []);

  const submitNote = async () => {
    if (!noteText.trim()) { showError('Add some detail for the entry'); return; }
    setSavingNote(true);
    try {
      await addEmployeeEvent(employeeCode, {
        event_type: noteType,
        detail: noteText.trim(),
        effective_date: noteDate || null,
      });
      setNoteText(''); setNoteDate(''); setNoteType('note'); setNoteOpen(false);
      showSuccess('Timeline entry added');
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to add entry');
    } finally {
      setSavingNote(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2.5 py-24 text-[var(--text-muted)]">
        <Loader2 size={18} className="animate-spin" />
        <span className="text-[13px] font-bold">Loading employee…</span>
      </div>
    );
  }

  if (error || !employee) {
    return (
      <div className="p-6 sm:p-8">
        <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
          style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
          <AlertTriangle size={15} /> {error || 'Employee not found'}
        </div>
        <button onClick={() => navigate('/hrms/employees')}
          className="mt-5 flex items-center gap-2 text-[12px] font-black uppercase tracking-widest text-[var(--accent-indigo)]">
          <ArrowLeft size={15} /> Back to employees
        </button>
      </div>
    );
  }

  const e = employee;

  return (
    <div className="p-6 sm:p-8 flex flex-col gap-5">
      {/* Back */}
      <button onClick={() => navigate('/hrms/employees')}
        className="flex items-center gap-2 text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors w-fit">
        <ArrowLeft size={14} /> Employees
      </button>

      {/* Header card */}
      <div className="p-5 sm:p-6 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-4 min-w-0">
          <Avatar name={e.fullName} photoUrl={e.photoUrl} size={60} />
          <div className="min-w-0">
            <div className="flex items-center gap-2.5 flex-wrap">
              <h1 className="text-xl sm:text-2xl font-black tracking-tight text-[var(--text-main)]">
                {e.displayName || e.fullName}
              </h1>
              <StatusBadge status={e.status} />
            </div>
            <p className="text-[13px] font-semibold text-[var(--text-muted)] mt-0.5">
              {e.designation || 'No designation'}
              {e.department ? ` · ${e.department}` : ''}
            </p>
            <p className="text-[11.5px] font-bold text-[var(--text-muted)] mt-1"
              style={{ fontVariantNumeric: 'tabular-nums' }}>
              {e.employeeCode}
            </p>
          </div>
        </div>
        {canEdit && (
          <button onClick={() => setShowEdit(true)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] transition-all">
            <Pencil size={14} /> Edit
          </button>
        )}
      </div>

      {/* Quick facts */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { icon: Mail, label: 'Work email', value: e.workEmail },
          { icon: Phone, label: 'Phone', value: e.phone },
          { icon: Building2, label: 'Location', value: e.location },
          { icon: CalendarDays, label: 'Joined', value: fmtDate(e.dateOfJoining) },
        ].map((f) => (
          <div key={f.label}
            className="p-3.5 rounded-xl bg-[var(--bg-card)] border border-[var(--border)] flex items-center gap-3">
            <span className="w-9 h-9 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shrink-0">
              <f.icon size={16} />
            </span>
            <div className="min-w-0">
              <div className="text-[9.5px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                {f.label}
              </div>
              <div className="text-[12.5px] font-bold text-[var(--text-main)] truncate">
                {f.value || '—'}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {TABS.map((t) => (
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

      {/* Tab body */}
      <div className="p-5 sm:p-6 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
        {tab === 'personal' && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
            <div>
              <Row label="Full name" value={e.fullName} />
              <Row label="Gender" value={e.gender} />
              <Row label="Date of birth" value={fmtDate(e.dateOfBirth)} />
              <Row label="Personal email" value={e.personalEmail} />
            </div>
            <div>
              <Row label="Address" value={e.address} />
              <Row label="Emergency contact" value={e.emergencyName} />
              <Row label="Relation" value={e.emergencyRelation} />
              <Row label="Emergency phone" value={e.emergencyPhone} />
            </div>
          </div>
        )}

        {tab === 'job' && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
            <div>
              <Row label="Designation" value={e.designation} />
              <Row label="Department" value={e.department} />
              <Row label="Location" value={e.location} />
              <Row label="Grade" value={e.grade} />
              <Row label="Employment type" value={e.employmentType} />
            </div>
            <div>
              <Row label="Work mode" value={e.workMode} />
              <Row label="Status" value={e.status} />
              <Row label="Date of joining" value={fmtDate(e.dateOfJoining)} />
              <Row label="Probation ends" value={fmtDate(e.probationEndDate)} />
              <Row label="Confirmation date" value={fmtDate(e.confirmationDate)} />
              {e.exitDate && <Row label="Exit date" value={fmtDate(e.exitDate)} />}
              {e.exitReason && <Row label="Exit reason" value={e.exitReason} />}
            </div>
          </div>
        )}

        {tab === 'statutory' && (
          <>
            {!e.sensitiveVisible && (
              <div className="flex items-center gap-2 px-4 py-3 mb-4 rounded-xl bg-[var(--input-bg)] border border-dashed border-[var(--border)]">
                <Lock size={14} className="text-[var(--text-muted)]" />
                <span className="text-[11.5px] font-bold text-[var(--text-muted)]">
                  Identifiers are masked and bank / salary details are hidden. Employee-record
                  permission is required to view them.
                </span>
              </div>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
              <div>
                <Row label="PAN" value={e.pan} mono />
                <Row label="Aadhaar" value={e.aadhaar} mono />
                <Row label="UAN" value={e.uan} mono />
                <Row label="ESIC number" value={e.esicNo} mono />
              </div>
              <div>
                <Row label="Passport" value={e.passport} mono />
                <Row label="Driving licence" value={e.drivingLicense} mono />
                {e.sensitiveVisible && (
                  <>
                    <Row label="Bank" value={e.bankName} />
                    <Row label="Account number" value={e.bankAccount} mono />
                    <Row label="IFSC" value={e.bankIfsc} mono />
                    <Row label="Annual CTC"
                      value={e.ctcAnnual ? `₹ ${Number(e.ctcAnnual).toLocaleString('en-IN')}` : '—'} mono />
                  </>
                )}
              </div>
            </div>
          </>
        )}

        {tab === 'timeline' && (
          <div className="flex flex-col gap-4">
            {canEdit && (
              <div>
                {!noteOpen ? (
                  <button onClick={() => setNoteOpen(true)}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] transition-colors">
                    <Plus size={14} /> Add entry
                  </button>
                ) : (
                  <div className="p-4 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] flex flex-col gap-3">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <Field label="Type">
                        <select className={`${inputCls} cursor-pointer`} value={noteType}
                          onChange={(ev) => setNoteType(ev.target.value)}>
                          {EVENT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                        </select>
                      </Field>
                      <Field label="Effective date">
                        <input type="date" className={inputCls} value={noteDate}
                          onChange={(ev) => setNoteDate(ev.target.value)} />
                      </Field>
                    </div>
                    <Field label="Detail" required>
                      <textarea rows={3} className={`${inputCls} resize-y`} value={noteText}
                        onChange={(ev) => setNoteText(ev.target.value)}
                        placeholder="What happened, and why it matters." />
                    </Field>
                    <div className="flex items-center justify-end gap-2">
                      <button onClick={() => setNoteOpen(false)}
                        className="px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                        Cancel
                      </button>
                      <button onClick={submitNote} disabled={savingNote}
                        className="flex items-center gap-2 px-5 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
                        {savingNote && <Loader2 size={13} className="animate-spin" />} Add
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {events.length === 0 ? (
              <p className="text-[12.5px] font-bold text-[var(--text-muted)] py-6 text-center">
                No history yet.
              </p>
            ) : (
              <ol className="flex flex-col">
                {events.map((ev, i) => (
                  <motion.li key={ev.id}
                    initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: Math.min(i * 0.03, 0.3) }}
                    className="flex gap-3.5 pb-4 last:pb-0">
                    {/* Rail */}
                    <div className="flex flex-col items-center">
                      <span className="w-2.5 h-2.5 rounded-full mt-1.5 shrink-0"
                        style={{ backgroundColor: EVENT_TONE[ev.eventType] || 'var(--text-muted)' }} />
                      {i < events.length - 1 && (
                        <span className="w-px flex-1 mt-1" style={{ backgroundColor: 'var(--border)' }} />
                      )}
                    </div>
                    <div className="min-w-0 pb-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-[10px] font-black uppercase tracking-widest"
                          style={{ color: EVENT_TONE[ev.eventType] || 'var(--text-muted)' }}>
                          {String(ev.eventType || '').replace(/_/g, ' ')}
                        </span>
                        <span className="text-[11px] font-bold text-[var(--text-muted)]">
                          {fmtDateTime(ev.createdAt)}
                        </span>
                      </div>
                      <p className="text-[13px] font-semibold text-[var(--text-main)] mt-0.5">
                        {ev.detail}
                      </p>
                      <p className="text-[11px] font-medium text-[var(--text-muted)] mt-0.5">
                        {ev.actorName || 'System'}
                        {ev.effectiveDate ? ` · effective ${fmtDate(ev.effectiveDate)}` : ''}
                      </p>
                    </div>
                  </motion.li>
                ))}
              </ol>
            )}
          </div>
        )}
      </div>

      <EmployeeFormModal
        isOpen={showEdit}
        onClose={() => setShowEdit(false)}
        employee={employee}
        options={options}
        onSaved={() => { setShowEdit(false); showSuccess('Employee updated'); load(); }}
        onError={showError}
      />
    </div>
  );
};

export default EmployeeProfile;
