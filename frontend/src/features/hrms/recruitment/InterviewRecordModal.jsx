import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FileText, Video, Trash2, ExternalLink, Loader2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import { useNotification } from '../../../context/NotificationContext';
import {
  getInterviewRecord, fileInterviewReport, fileInterviewRecording,
  getInterviewRecordUrl, removeInterviewRecord,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from '../internal/internalKit';
import { Btn, Modal } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ file the interview record for one candidate (brief §10).
 *
 * Two artifacts, one screen: the written report and the recording of the call. Both are
 * filed against the CANDIDATE rather than against a round — a client reviewing somebody asks
 * "how did they interview", not "how did round two of three go" — which is why this takes a
 * `uk` and not an interview number, even though it is opened from a scheduled round.
 *
 * -- Why the recording takes a link as well as a file ---------------------------------------
 * Zoom, Meet and Teams all hand back a cloud recording and a URL. Requiring a recruiter to
 * download a two-hour call and re-upload it is how a step stops being followed, so a link is
 * a first-class option rather than a fallback. The server accepts one or the other and
 * refuses both together: two sources on one record means nobody can say which was the real
 * call.
 *
 * -- What filing this does ------------------------------------------------------------------
 * It publishes. Every LIVE share of this candidate picks the material up immediately, which
 * is deliberate and is the reason this needs its own capability (`interview.media.write`)
 * rather than riding on `interview.schedule`: the CV usually goes to a client before the
 * interview happens, so a report that only reached future shares would reach almost nobody.
 * The panel's own scorecards are untouched and stay Sparsh-side.
 */

// Mirrors the server's two ceilings. Checked here so a 400 MB file is refused before the
// browser spends a minute base64-ing it into memory — the server re-checks regardless.
const REPORT_MAX_MB = 15;
const RECORDING_MAX_MB = 100;

const REPORT_ACCEPT = '.pdf,.doc,.docx,.jpg,.jpeg,.png,.webp';
const RECORDING_ACCEPT = 'video/*,audio/*';

/** Read a File into the base64 shape the upload endpoints expect. Size checked BEFORE the
 *  read, so an oversized file never reaches memory — the ordering the server also uses. */
const readFile = (file, maxMb) => new Promise((resolve, reject) => {
  if (file.size > maxMb * 1024 * 1024) {
    reject(new Error(`That file is larger than ${maxMb} MB.`));
    return;
  }
  const reader = new FileReader();
  reader.onload = () => resolve({
    name: file.name,
    mime_type: file.type || 'application/octet-stream',
    data: String(reader.result).split(',')[1] || '',
  });
  reader.onerror = () => reject(new Error('That file could not be read.'));
  reader.readAsDataURL(file);
});

const Filed = ({ record, label, onOpen, onRemove, canWrite, busy }) => (
  <div className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] p-3
                  flex items-start justify-between gap-3">
    <div className="min-w-0">
      <p className="text-[12.5px] font-bold text-[var(--text-main)] break-words">
        {record.name || record.title || label}
      </p>
      <p className="text-[11px] text-[var(--text-muted)]">
        {record.source === 'link' ? 'Linked recording' : 'Uploaded file'}
        {record.duration_min ? ` · ${record.duration_min} min` : ''}
        {' · filed '}{day(record.filed_at)}
        {record.filed_by_name ? ` by ${record.filed_by_name}` : ''}
      </p>
    </div>
    <div className="flex items-center gap-1.5 shrink-0">
      <Btn onClick={onOpen} disabled={busy}><ExternalLink size={13} /> Open</Btn>
      {canWrite && (
        <Btn tone="danger" onClick={onRemove} disabled={busy}><Trash2 size={13} /></Btn>
      )}
    </div>
  </div>
);

const InterviewRecordModal = ({ uk, candidateName, onClose, onSaved }) => {
  const { scope, can, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [record, setRecord] = useState({ report: null, recording: null });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(null);
  const [summary, setSummary] = useState('');
  // A link and a file are mutually exclusive on the server, so the form makes you pick one
  // rather than accepting both and letting the API say no.
  const [mode, setMode] = useState('file');
  const [url, setUrl] = useState('');
  const [title, setTitle] = useState('');
  const [duration, setDuration] = useState('');
  const reportInput = useRef(null);
  const recordingInput = useRef(null);

  const canWrite = can(CAP.INTERVIEW_MEDIA_WRITE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    try {
      const { data } = await getInterviewRecord(uk, scope);
      setRecord({ report: data?.report || null, recording: data?.recording || null });
      setSummary(data?.report?.summary || '');
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not load the interview record.');
    } finally {
      setLoading(false);
    }
    // showError is stable enough in practice and including it re-runs this on every toast.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uk, companyId, scope]);

  useEffect(() => { load(); }, [load]);

  const done = async (message) => {
    showSuccess(message);
    await load();
    await onSaved?.();
  };

  const uploadReport = async (file) => {
    if (!file) return;
    setBusy('report');
    try {
      const payload = await readFile(file, REPORT_MAX_MB);
      await fileInterviewReport(uk, { file: payload, summary: summary || null }, scope);
      await done('Interview report filed');
    } catch (e) {
      showError(e?.response?.data?.detail || e.message || 'Could not file that report.');
    } finally {
      setBusy(null);
      if (reportInput.current) reportInput.current.value = '';
    }
  };

  const uploadRecording = async (file) => {
    if (!file) return;
    setBusy('recording');
    try {
      const payload = await readFile(file, RECORDING_MAX_MB);
      await fileInterviewRecording(uk, {
        file: payload,
        title: title || null,
        duration_min: duration === '' ? null : Number(duration),
      }, scope);
      setTitle(''); setDuration('');
      await done('Interview recording filed');
    } catch (e) {
      showError(e?.response?.data?.detail || e.message || 'Could not file that recording.');
    } finally {
      setBusy(null);
      if (recordingInput.current) recordingInput.current.value = '';
    }
  };

  const linkRecording = async () => {
    if (!url.trim()) return;
    setBusy('recording');
    try {
      await fileInterviewRecording(uk, {
        url: url.trim(),
        title: title || null,
        duration_min: duration === '' ? null : Number(duration),
      }, scope);
      setUrl(''); setTitle(''); setDuration('');
      await done('Recording link saved');
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not save that link.');
    } finally {
      setBusy(null);
    }
  };

  const open = async (kind) => {
    setBusy(kind);
    try {
      const { data } = await getInterviewRecordUrl(uk, kind, scope);
      if (!data?.url) return;
      const w = window.open(data.url, '_blank', 'noopener,noreferrer');
      if (w) w.opener = null;
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not open that.');
    } finally {
      setBusy(null);
    }
  };

  const remove = async (kind) => {
    // A confirm rather than a quiet delete: unpublishing pulls material back from clients who
    // may already be looking at it.
    if (!window.confirm(
      `Remove the interview ${kind} for ${candidateName}? Clients it was shared with will `
      + 'no longer be able to open it.')) return;
    setBusy(kind);
    try {
      await removeInterviewRecord(uk, kind, scope);
      await done(`Interview ${kind} removed`);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not remove that.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal
      title={`Interview record — ${candidateName}`}
      subtitle="Filed against the candidate. Clients this CV was shared with see it immediately."
      labelledBy="irm-title"
      onClose={onClose}
      footer={<Btn onClick={onClose}>Close</Btn>}
    >
      {loading ? (
        <p className="text-[12.5px] text-[var(--text-muted)]">Loading…</p>
      ) : (
        <div className="space-y-5">
          {/* ── Report ── */}
          <section className="space-y-2.5">
            <h3 className="text-[10.5px] font-bold uppercase tracking-widest
                           text-[var(--text-muted)] flex items-center gap-1.5">
              <FileText size={12} /> Interview report
            </h3>
            {record.report ? (
              <Filed record={record.report} label="Interview report" busy={!!busy}
                     canWrite={canWrite} onOpen={() => open('report')}
                     onRemove={() => remove('report')} />
            ) : (
              <p className="text-[12px] text-[var(--text-muted)]">Nothing filed yet.</p>
            )}

            {canWrite && (
              <>
                <div>
                  <label className={LABEL} htmlFor="irm-summary">
                    Summary the client reads first
                  </label>
                  <textarea id="irm-summary" rows={2} className={TEXTAREA} value={summary}
                            onChange={(e) => setSummary(e.target.value)}
                            placeholder="e.g. Strong on system design; needs support on delivery pace." />
                </div>
                <input ref={reportInput} type="file" accept={REPORT_ACCEPT} className="hidden"
                       onChange={(e) => uploadReport(e.target.files?.[0])} />
                <Btn onClick={() => reportInput.current?.click()} disabled={!!busy}>
                  {busy === 'report' ? <Loader2 size={13} className="animate-spin" />
                                     : <FileText size={13} />}
                  {record.report ? 'Replace report' : 'Upload report'}
                </Btn>
                <p className="text-[11px] text-[var(--text-muted)]">
                  PDF, Word or an image, up to {REPORT_MAX_MB} MB. The summary is saved with
                  the file, so write it before uploading.
                </p>
              </>
            )}
          </section>

          {/* ── Recording ── */}
          <section className="space-y-2.5 pt-4 border-t border-[var(--border)]">
            <h3 className="text-[10.5px] font-bold uppercase tracking-widest
                           text-[var(--text-muted)] flex items-center gap-1.5">
              <Video size={12} /> Interview recording
            </h3>
            {record.recording ? (
              <Filed record={record.recording} label="Interview recording" busy={!!busy}
                     canWrite={canWrite} onOpen={() => open('recording')}
                     onRemove={() => remove('recording')} />
            ) : (
              <p className="text-[12px] text-[var(--text-muted)]">Nothing filed yet.</p>
            )}

            {canWrite && (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className={LABEL} htmlFor="irm-title">Label (optional)</label>
                    <input id="irm-title" className={FIELD} value={title}
                           onChange={(e) => setTitle(e.target.value)}
                           placeholder="e.g. Technical round" />
                  </div>
                  <div>
                    <label className={LABEL} htmlFor="irm-dur">Length in minutes</label>
                    <input id="irm-dur" type="number" min="1" className={FIELD}
                           value={duration} onChange={(e) => setDuration(e.target.value)} />
                  </div>
                </div>

                <div className="flex gap-1.5">
                  {['file', 'link'].map((m) => (
                    <button
                      key={m} type="button" onClick={() => setMode(m)}
                      className={`h-8 px-3 rounded-lg text-[11.5px] font-bold transition-colors
                        ${mode === m
                          ? 'bg-[var(--accent-indigo)] text-white'
                          : 'border border-[var(--border)] text-[var(--text-muted)]'}`}
                    >
                      {m === 'file' ? 'Upload a file' : 'Paste a link'}
                    </button>
                  ))}
                </div>

                {mode === 'file' ? (
                  <>
                    <input ref={recordingInput} type="file" accept={RECORDING_ACCEPT}
                           className="hidden"
                           onChange={(e) => uploadRecording(e.target.files?.[0])} />
                    <Btn onClick={() => recordingInput.current?.click()} disabled={!!busy}>
                      {busy === 'recording' ? <Loader2 size={13} className="animate-spin" />
                                            : <Video size={13} />}
                      {record.recording ? 'Replace recording' : 'Upload recording'}
                    </Btn>
                    <p className="text-[11px] text-[var(--text-muted)]">
                      MP4, WebM, MOV or audio, up to {RECORDING_MAX_MB} MB. For a longer call,
                      paste the meeting platform&apos;s link instead.
                    </p>
                  </>
                ) : (
                  <>
                    <div>
                      <label className={LABEL} htmlFor="irm-url">Recording link</label>
                      <input id="irm-url" className={FIELD} value={url} type="url"
                             onChange={(e) => setUrl(e.target.value)}
                             placeholder="https://…" />
                    </div>
                    <Btn tone="primary" onClick={linkRecording} disabled={!url.trim() || !!busy}>
                      {busy === 'recording' ? 'Saving…' : 'Save link'}
                    </Btn>
                    <p className="text-[11px] text-[var(--text-muted)]">
                      The client opens this on the platform that hosts it, so make sure the
                      link is shared with them there — access is that platform&apos;s to
                      control, not ours.
                    </p>
                  </>
                )}
              </>
            )}
          </section>

          {!canWrite && (
            <p className="text-[11.5px] text-[var(--text-muted)]">
              You can read this record but not change it. Filing an interview report or
              recording needs the interview-record permission.
            </p>
          )}
        </div>
      )}
    </Modal>
  );
};

export default InterviewRecordModal;
