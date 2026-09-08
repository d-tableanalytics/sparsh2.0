import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  FileText, Video, Upload, Trash2, Link as LinkIcon, PlayCircle, Eye,
} from 'lucide-react';
import { CAP } from '../access';
import { useHrms } from '../HrmsContext';
import { useNotification } from '../../../context/NotificationContext';
import {
  getCandidateInterviews, attachInterviewMedia, removeInterviewMedia,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from '../internal/internalKit';
import { Btn, Chip, Modal } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ interview evidence — the report and the recording (spec §10).
 *
 * Sparsh's side: attach, replace and remove what a client will read and watch.
 *
 * The distinction this screen has to keep visible is not "two files" but "two different
 * permissions". A client downloads a CV, reads a report, and only ever WATCHES a recording.
 * The upload panel says so, because the person attaching a recording is the one deciding
 * to show it to somebody outside the company and should know the terms.
 *
 * A recording can be a LINK instead of an upload. Most already live in the conferencing
 * tool that made them, and pushing 400 MB into our bucket to hold a second copy helps
 * nobody — but a link's no-download rule is the hosting tool's to keep, not ours, and the
 * form says that too rather than implying a guarantee we do not have.
 */

const KINDS = {
  report: {
    label: 'Interview report',
    icon: FileText,
    accept: '.pdf,.doc,.docx',
    mimes: ['application/pdf', 'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
    maxMb: 25,
    clientRule: 'The client can read this.',
    allowLink: false,
  },
  recording: {
    label: 'Interview recording',
    icon: Video,
    accept: 'video/*,audio/*',
    mimes: ['video/mp4', 'video/webm', 'video/quicktime', 'video/x-matroska',
            'audio/mpeg', 'audio/mp4', 'audio/wav', 'audio/webm'],
    maxMb: 500,
    clientRule: 'The client can watch this, and is given no download.',
    allowLink: true,
  },
};

const InterviewEvidence = ({ uk, candidateName }) => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [attaching, setAttaching] = useState(null);   // {interview, kind}

  const canWrite = can(CAP.INTERVIEW_MEDIA);

  const load = useCallback(async () => {
    if (!companyId || !uk) { setLoading(false); return; }
    setLoading(true);
    try {
      const { data } = await getCandidateInterviews(uk, scope);
      setRows(data?.interviews || []);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not load interviews.');
    } finally {
      setLoading(false);
    }
    // showError is stable enough for this; re-running on it would reload on every toast.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, uk, scope]);

  useEffect(() => { load(); }, [load]);

  const drop = async (interview, kind) => {
    if (!window.confirm(`Remove the ${KINDS[kind].label.toLowerCase()}? `
      + 'Any client who was shown this candidate loses access to it.')) return;
    try {
      await removeInterviewMedia(interview.interview_no, kind, scope);
      showSuccess(`${KINDS[kind].label} removed`);
      await load();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not remove that.');
    }
  };

  if (loading) {
    return <p className="text-[12px] text-[var(--text-muted)]">Loading interviews…</p>;
  }
  if (!rows.length) {
    return (
      <p className="text-[12px] text-[var(--text-muted)]">
        No interviews recorded for {candidateName || 'this candidate'} yet. The report and
        recording attach to an interview, so schedule one first.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {rows.map((iv) => (
        <div key={iv.interview_no}
             className="rounded-lg border border-[var(--border)] p-3 space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-[13px] font-semibold text-[var(--text-main)]">
                {iv.round}
                {iv.outcome ? ` · ${iv.outcome}` : ''}
              </p>
              <p className="text-[11px] text-[var(--text-muted)] font-mono">
                {iv.interview_no} · {day(iv.scheduled_at)}
                {iv.interviewer_name ? ` · ${iv.interviewer_name}` : ''}
              </p>
            </div>
            {iv.average_score != null && (
              <Chip tone="neutral">{Number(iv.average_score).toFixed(1)} / 5</Chip>
            )}
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            {Object.entries(KINDS).map(([kind, spec]) => {
              const item = iv[kind];
              const Icon = spec.icon;
              return (
                <div key={kind}
                     className="rounded border border-[var(--border)] p-2.5 flex flex-col
                                gap-1.5">
                  <div className="flex items-center gap-1.5">
                    <Icon size={13} className="text-[var(--text-muted)]" />
                    <span className="text-[12px] font-semibold text-[var(--text-main)]">
                      {spec.label}
                    </span>
                    {item && (
                      <Chip tone={item.is_external ? 'info' : 'good'}>
                        {item.is_external ? 'linked' : 'stored'}
                      </Chip>
                    )}
                  </div>
                  {item ? (
                    <>
                      <p className="text-[11.5px] text-[var(--text-main)] break-words">
                        {item.name}
                        {item.duration_minutes ? ` · ${item.duration_minutes} min` : ''}
                      </p>
                      <p className="text-[10.5px] text-[var(--text-muted)]">
                        {spec.clientRule}
                      </p>
                      {canWrite && (
                        <div className="flex gap-1.5 mt-0.5">
                          <Btn onClick={() => setAttaching({ interview: iv, kind })}>
                            <Upload size={12} /> Replace
                          </Btn>
                          <Btn tone="danger" onClick={() => drop(iv, kind)}>
                            <Trash2 size={12} />
                          </Btn>
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      <p className="text-[11.5px] text-[var(--text-muted)]">
                        Not attached.
                      </p>
                      {canWrite && (
                        <Btn onClick={() => setAttaching({ interview: iv, kind })}>
                          <Upload size={12} /> Attach
                        </Btn>
                      )}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {attaching && (
        <AttachModal
          scope={scope}
          interview={attaching.interview}
          kind={attaching.kind}
          onClose={() => setAttaching(null)}
          onDone={async (m) => { setAttaching(null); showSuccess(m); await load(); }}
          onError={showError}
        />
      )}
    </div>
  );
};

const AttachModal = ({ scope, interview, kind, onClose, onDone, onError }) => {
  const spec = KINDS[kind];
  const [mode, setMode] = useState('file');      // 'file' | 'link'
  const [file, setFile] = useState(null);
  const [url, setUrl] = useState('');
  const [notes, setNotes] = useState('');
  const [minutes, setMinutes] = useState('');
  const [saving, setSaving] = useState(false);
  const inputRef = useRef(null);

  const pick = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > spec.maxMb * 1024 * 1024) {
      onError(`${spec.label} is too large. The limit is ${spec.maxMb} MB.`);
      e.target.value = '';
      return;
    }
    setFile(f);
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      let body;
      if (mode === 'link') {
        body = { external_url: url.trim(), notes: notes || null,
                 name: 'Recorded interview' };
      } else {
        if (!file) { onError('Choose a file.'); setSaving(false); return; }
        // Read as base64 — the same ingest shape every other HRMS upload uses, so one
        // server-side validator covers all of them.
        const data = await new Promise((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(String(r.result).split(',')[1]);
          r.onerror = rej;
          r.readAsDataURL(file);
        });
        body = { name: file.name, mime_type: file.type, data, notes: notes || null };
      }
      if (kind === 'recording' && minutes) body.duration_minutes = Number(minutes);
      await attachInterviewMedia(interview.interview_no, kind, body, scope);
      await onDone(`${spec.label} attached`);
    } catch (err) {
      onError(err?.response?.data?.detail || `Could not attach the ${kind}.`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`${spec.label} — ${interview.round}`}
      subtitle={interview.interview_no}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" onClick={submit}
               disabled={saving || (mode === 'file' ? !file : !url.trim())}>
            {saving ? 'Uploading…' : 'Attach'}
          </Btn>
        </>
      )}
    >
      <form onSubmit={submit} className="space-y-3">
        <p className="text-[12px] text-[var(--text-muted)] border-l-2
                      border-[var(--border)] pl-2">
          {spec.clientRule}
          {kind === 'recording' && (
            <span className="block mt-1">
              A browser has to receive a video to play it, so this stops casual sharing and
              records who watched — it cannot make the file impossible to keep.
            </span>
          )}
        </p>

        {spec.allowLink && (
          <div className="flex gap-2">
            <Btn tone={mode === 'file' ? 'primary' : 'ghost'}
                 onClick={() => setMode('file')}>
              <Upload size={12} /> Upload a file
            </Btn>
            <Btn tone={mode === 'link' ? 'primary' : 'ghost'}
                 onClick={() => setMode('link')}>
              <LinkIcon size={12} /> Use a link
            </Btn>
          </div>
        )}

        {mode === 'file' ? (
          <div>
            <label className={LABEL} htmlFor="ev-file">
              File * (max {spec.maxMb} MB)
            </label>
            <input id="ev-file" ref={inputRef} type="file" accept={spec.accept}
                   onChange={pick} className={FIELD} />
            {file && (
              <p className="mt-1 text-[11.5px] text-[var(--text-muted)]">
                {file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB
              </p>
            )}
          </div>
        ) : (
          <div>
            <label className={LABEL} htmlFor="ev-url">Recording link *</label>
            <input id="ev-url" className={FIELD} value={url} placeholder="https://…"
                   onChange={(e) => setUrl(e.target.value)} />
            <p className="mt-1 text-[11px] text-[var(--text-muted)]">
              The client opens this in the hosting tool. Whether they can download it there
              is that tool’s setting, not ours — check it before sharing.
            </p>
          </div>
        )}

        {kind === 'recording' && (
          <div>
            <label className={LABEL} htmlFor="ev-min">Duration (minutes)</label>
            <input id="ev-min" type="number" min="0" className={FIELD} value={minutes}
                   onChange={(e) => setMinutes(e.target.value)} />
          </div>
        )}

        <div>
          <label className={LABEL} htmlFor="ev-notes">Notes for the client</label>
          <textarea id="ev-notes" rows={2} className={TEXTAREA} value={notes}
                    onChange={(e) => setNotes(e.target.value)} />
        </div>
      </form>
    </Modal>
  );
};

export default InterviewEvidence;
