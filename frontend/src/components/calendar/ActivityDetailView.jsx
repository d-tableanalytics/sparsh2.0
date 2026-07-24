import React, { useRef, useState } from 'react';
import {
  CalendarDays, Clock, Activity as ActivityIcon, Building2, Users2, UserCog,
  Bell, Pencil, Trash2, Eye, CheckCircle2, Upload, FileText, RefreshCw, Paperclip,
} from 'lucide-react';
import api from '../../services/api';
import { useNotification } from '../../context/NotificationContext';

/**
 * Read-only detail view for a Schedule Activity event, opened from the calendar.
 * Shows the captured fields (activity, company, departments, assigned doers, SMOPS,
 * time, status, reminders). Admin/Super Admin get Edit + Delete; assigned users view only.
 * Field names/company come from the event's `activity_meta` snapshot (no live lookups).
 */

const STATUS_STYLES = {
  completed: { label: 'Completed', cls: 'bg-emerald-100 text-emerald-700 border-emerald-200' },
  canceled:  { label: 'Canceled',  cls: 'bg-rose-100 text-rose-700 border-rose-200' },
  reschedule:{ label: 'Rescheduled', cls: 'bg-amber-100 text-amber-700 border-amber-200' },
  schedule:  { label: 'Scheduled', cls: 'bg-indigo-50 text-indigo-600 border-indigo-100' },
};

const Row = ({ icon: Icon, label, children }) => (
  <div className="flex items-start gap-3 py-2.5 border-b border-dashed border-[var(--border)] last:border-0">
    <Icon size={15} className="text-[var(--accent-indigo)] mt-0.5 shrink-0" />
    <div className="min-w-0 flex-1">
      <div className="text-[9px] font-black text-gray-400 uppercase tracking-widest">{label}</div>
      <div className="text-[13px] font-bold text-[var(--text-main)] break-words">{children}</div>
    </div>
  </div>
);

const ActivityDetailView = ({ event, eventId, isAdmin, isCreator, onEdit, onDelete, onUploaded, formatIST }) => {
  const { showSuccess, showError } = useNotification();
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);

  const contents = event.learner_contents || [];

  const handleUpload = async () => {
    if (!file) return showError('Choose a file first');
    const fd = new FormData();
    fd.append('file', file);
    setUploading(true);
    try {
      const res = await api.post(`/calendar/events/${eventId}/learner-upload`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      showSuccess('File uploaded');
      setFile(null);
      if (fileRef.current) fileRef.current.value = '';
      onUploaded?.(res.data?.content);
    } catch (err) {
      showError(err.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const meta = event.activity_meta || {};
  const smops = meta.smops || [];
  const doers = meta.doers || [];
  const departments = (event.assigned_departments && event.assigned_departments.length ? event.assigned_departments : meta.departments) || [];
  const status = STATUS_STYLES[event.status] || STATUS_STYLES.schedule;
  const reminderCount = event.reminders?.length || 0;

  return (
    <div className="space-y-5 py-2">
      {/* Header */}
      <div className="space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border border-[var(--accent-indigo-border)]">
            <ActivityIcon size={11} /> Activity
          </span>
          {isCreator && (
            <span className="px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest bg-violet-100 text-violet-700 border border-violet-200">You scheduled</span>
          )}
          <span className={`ml-auto px-2.5 py-0.5 rounded-full text-[10px] font-black border ${status.cls}`}>{status.label}</span>
        </div>
        <h2 className="text-2xl font-black text-[var(--text-main)] tracking-tight break-words">{event.title}</h2>
      </div>

      {/* Fields */}
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--input-bg)] px-4">
        <Row icon={Clock} label="Date & Time">
          {new Date(event.start).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}
          {!event.all_day && formatIST ? ` · ${formatIST(event.start)}` : ''}
        </Row>
        <Row icon={ActivityIcon} label="Activity">{event.activity || '—'}</Row>
        <Row icon={Building2} label="Company">{event.company_name || meta.company_name || '—'}</Row>
        <Row icon={Users2} label="Departments">
          {departments.length ? (
            <span className="flex flex-wrap gap-1">
              {departments.map((d) => <span key={d} className="px-2 py-0.5 rounded bg-[var(--bg-card)] border border-[var(--border)] text-[11px]">{d}</span>)}
            </span>
          ) : '—'}
        </Row>
        <Row icon={Users2} label="Assigned Users">
          {doers.length ? (
            <span className="flex flex-wrap gap-1">
              {doers.map((u) => <span key={u.id} className="px-2 py-0.5 rounded bg-violet-50 text-violet-700 border border-violet-100 text-[11px]">{u.name}{u.department ? ` · ${u.department}` : ''}</span>)}
            </span>
          ) : '—'}
        </Row>
        <Row icon={UserCog} label="SMOPS (Staff Assigner)">
          {smops.length ? (
            <span className="flex flex-wrap gap-1">
              {smops.map((u) => <span key={u.id} className="px-2 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-100 text-[11px]">{u.name}</span>)}
            </span>
          ) : '—'}
        </Row>
        <Row icon={Bell} label="Reminders">{reminderCount ? `${reminderCount} reminder(s)` : 'None'}</Row>
        {event.status === 'completed' && event.completed_at && (
          <Row icon={CheckCircle2} label="Completed">{formatIST ? formatIST(event.completed_at) : new Date(event.completed_at).toLocaleString()}</Row>
        )}
      </div>

      {/* Comment */}
      {event.additional_details && (
        <div>
          <div className="text-[9px] font-black text-gray-400 uppercase tracking-widest mb-1.5">Comment</div>
          <div className="text-[12px] font-medium text-gray-600 leading-relaxed bg-[var(--input-bg)] p-4 rounded-xl">{event.additional_details}</div>
        </div>
      )}

      {/* Upload / evidence */}
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--input-bg)] p-4 space-y-3">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2 text-[12px]">
            <Paperclip size={14} className="text-[var(--accent-indigo)]" />
            <span className="font-black text-[var(--text-main)]">Upload for</span>
            <span className="font-bold text-[var(--accent-indigo)]">{event.activity || 'Activity'}</span>
          </div>
          <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-black border ${contents.length ? 'bg-emerald-100 text-emerald-700 border-emerald-200' : 'bg-rose-100 text-rose-700 border-rose-200'}`}>
            {contents.length ? `${contents.length} file(s)` : 'Pending'}
          </span>
        </div>

        {contents.length === 0 ? (
          <p className="text-[11px] font-medium text-gray-400">No files uploaded yet.</p>
        ) : (
          <div className="space-y-1.5">
            {contents.map((c) => (
              <a key={c.id || c.url} href={c.url} target="_blank" rel="noreferrer"
                className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[var(--bg-card)] border border-[var(--border)] text-[12px] font-bold text-[var(--text-main)] hover:border-[var(--accent-indigo)] transition-all">
                <FileText size={14} className="text-[var(--accent-indigo)] shrink-0" />
                <span className="truncate flex-1">{c.name}</span>
                {c.uploader_name && <span className="text-[10px] font-semibold text-gray-400 shrink-0">{c.uploader_name}</span>}
              </a>
            ))}
          </div>
        )}

        <div className="flex items-center gap-2 flex-wrap">
          <input ref={fileRef} type="file" onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="text-[12px] file:mr-3 file:px-3 file:py-1.5 file:rounded-lg file:border file:border-[var(--border)] file:bg-[var(--bg-card)] file:text-[var(--text-main)] file:text-[11px] file:font-black file:cursor-pointer text-[var(--text-muted)]" />
          <button onClick={handleUpload} disabled={uploading || !file}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border border-[var(--accent-indigo)] text-[var(--accent-indigo)] text-[11px] font-black hover:bg-[var(--accent-indigo-bg)] transition-all disabled:opacity-50">
            {uploading ? <RefreshCw size={13} className="animate-spin" /> : <Upload size={13} />}
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
        </div>
      </div>

      {/* Non-admins get a view-only note; admins get Edit/Delete in the modal footer. */}
      {!isAdmin && (
        <div className="flex items-center gap-2 text-[11px] font-bold text-gray-400 pt-1">
          <Eye size={13} /> View only — this activity is managed by your Admin.
        </div>
      )}
    </div>
  );
};

export default ActivityDetailView;
