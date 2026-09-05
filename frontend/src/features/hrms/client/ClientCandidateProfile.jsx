import React, { useState } from 'react';
import {
  Download, FileText, Video, MessageSquarePlus, CornerUpLeft, X, Loader2,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import {
  getShareCv, getShareInterviewReport, getShareInterviewRecording,
  setShareStatus, addShareRemark,
} from '../../../services/hrmsApi';
import { LABEL, TEXTAREA, day } from '../internal/internalKit';
import { Btn, Chip, Facts } from '../internal/internalKit.jsx';
import ShareJourney from './ShareJourney';

/**
 * HRMS ▸ the client's candidate full-information page (brief §11).
 *
 * Everything a client needs about one candidate in one place — information, the CV, the
 * interview record, the history of what has been said — so reviewing somebody is not a tour
 * of four screens.
 *
 * -- It renders a SHARE, not a candidate ---------------------------------------------------
 * Every field here comes from `share.snapshot`: the allow-listed copy the server wrote when
 * Sparsh chose to show this person to this client. The browser never holds a candidate id
 * and could not read a candidate endpoint if it tried — the CLIENT role has no
 * `candidate.read`. That is what makes "a field added to candidates later cannot leak to a
 * client who was sent a CV last month" true, and it is why this component takes a share.
 *
 * -- The three verbs are not the same verb -------------------------------------------------
 * Brief §10 draws a line this component has to make visible:
 *
 *     CV                  Download  — saves to disk
 *     Interview report    View      — opens, rendered in place
 *     Interview recording Watch     — plays, and there is no save control anywhere
 *
 * Each goes through its own server route that re-proves the share and audits the open. The
 * recording player carries `controlsList="nodownload"` and no context menu, and this file
 * deliberately contains no download path for it. What that buys is a product with no way to
 * save the video and a log of everyone who watched — not a guarantee that a determined
 * viewer cannot keep a copy, which no web player can offer. See the note in
 * backend/app/services/hrms_interview_media_service.py.
 *
 * -- Which buttons appear ------------------------------------------------------------------
 * From `share.allowed_statuses`, which the SERVER computes by intersecting the lifecycle
 * graph with what a client may set. Nothing here restates those rules, so a rejected
 * candidate stops offering actions that no longer apply (§12) without this file knowing why.
 */

const TONE = {
  'CV Shared': 'info',
  'Under Review': 'info',
  Shortlisted: 'good',
  'Interview Scheduled': 'info',
  Selected: 'good',
  'Offer in Progress': 'warn',
  Hired: 'good',
  Rejected: 'bad',
  Withdrawn: 'neutral',
};

// The label a client should read on each verdict button. The API's status strings are the
// lifecycle's vocabulary; these are the client's.
const VERDICT_LABEL = {
  'Under Review': 'Mark under review',
  Shortlisted: 'Shortlist',
  'Interview Scheduled': 'Interview scheduled',
  Selected: 'Approve candidate',
  Rejected: 'Reject candidate',
};

const VERDICT_TONE = { Rejected: 'danger', Selected: 'primary' };

const Section = ({ title, children, actions }) => (
  <section className="space-y-2.5">
    <div className="flex items-center justify-between gap-3">
      <h3 className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
        {title}
      </h3>
      {actions}
    </div>
    {children}
  </section>
);

/** Opens a leased link in a new tab. Used for the report only — see the header note. */
const openInTab = (url) => {
  const w = window.open(url, '_blank', 'noopener,noreferrer');
  if (w) w.opener = null;
};

const ClientCandidateProfile = ({ share, onClose, onChanged }) => {
  const { showSuccess, showError } = useNotification();
  // The company scope every HRMS call carries. Taken from the module context rather than
  // passed in: a client user is pinned to it server-side anyway, and threading it through a
  // prop is one more place for the two to disagree.
  const { scope } = useHrms();
  const s = share.snapshot || {};

  const [busy, setBusy] = useState(null);
  const [remarking, setRemarking] = useState(null);   // 'remark' | 'sent_back' | null
  const [remark, setRemark] = useState('');
  // The recording is resolved on demand rather than on mount: the lease is short, and
  // minting one for somebody who only opened the profile to read the CV would put a watch
  // in the audit trail that nobody performed.
  const [recording, setRecording] = useState(null);

  const live = share.status !== 'Withdrawn';
  const allowed = share.allowed_statuses || [];

  const downloadCv = async () => {
    setBusy('cv');
    try {
      const { data } = await getShareCv(share.share_no, scope);
      if (!data?.url) return;
      // A synthetic anchor rather than window.open: the server already sets
      // Content-Disposition, so a new tab would flash and close itself the moment the
      // download starts. `download` is a hint only — it is ignored cross-origin, which is
      // why the header is what actually names the file.
      const a = document.createElement('a');
      a.href = data.url;
      a.download = data.name || 'cv.pdf';
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not download that CV.');
    } finally {
      setBusy(null);
    }
  };

  const viewReport = async () => {
    setBusy('report');
    try {
      const { data } = await getShareInterviewReport(share.share_no, scope);
      if (data?.url) openInTab(data.url);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not open the interview report.');
    } finally {
      setBusy(null);
    }
  };

  const watchRecording = async () => {
    setBusy('recording');
    try {
      const { data } = await getShareInterviewRecording(share.share_no, scope);
      if (!data?.url) return;
      // A file plays inline, in a player with no download control. A LINK is the meeting
      // platform's own page (Zoom, Meet, Teams) and has to open there — it is not media we
      // can embed, and how it behaves is that platform's rules rather than ours.
      if (data.source === 'link') openInTab(data.url);
      else setRecording(data);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not open the recording.');
    } finally {
      setBusy(null);
    }
  };

  const record = async (status) => {
    setBusy(status);
    try {
      await setShareStatus(share.share_no, { status }, scope);
      showSuccess(`${s.candidate_name} marked ${status}`);
      await onChanged?.();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not record that.');
    } finally {
      setBusy(null);
    }
  };

  const submitRemark = async () => {
    if (!remark.trim()) return;
    setBusy('remark');
    try {
      await addShareRemark(share.share_no, {
        remarks: remark.trim(),
        needs_attention: remarking === 'sent_back',
      }, scope);
      showSuccess(remarking === 'sent_back'
        ? 'Sent back to the Sparsh team'
        : 'Remark added');
      setRemark('');
      setRemarking(null);
      await onChanged?.();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not save that remark.');
    } finally {
      setBusy(null);
    }
  };

  // Only entries carrying words. The status ladder is already drawn by <ShareJourney>, so a
  // second list of bare status changes beside it would say the same thing twice.
  const conversation = (share.history || []).filter((h) => h.remarks);

  return (
    <div
      className="fixed inset-0 z-[60] grid place-items-center bg-black/40 backdrop-blur-sm p-4"
      role="dialog" aria-modal="true" aria-labelledby="ccp-title"
      onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}
    >
      <div className="w-full max-w-3xl max-h-[92vh] flex flex-col rounded-2xl
                      border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
        <header className="px-5 py-4 border-b border-[var(--border)] flex items-start
                           justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 id="ccp-title" className="text-[16px] font-bold text-[var(--text-main)]">
                {s.candidate_name}
              </h2>
              <Chip tone={TONE[share.status] || 'neutral'}>{share.status}</Chip>
            </div>
            <p className="mt-0.5 text-[11.5px] font-mono text-[var(--text-muted)]">
              {share.share_no} · shared {day(share.shared_at)}
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
                  className="h-8 w-8 grid place-items-center rounded-lg
                             text-[var(--text-muted)] hover:text-[var(--text-main)]">
            <X size={16} />
          </button>
        </header>

        <div className="p-5 space-y-6 overflow-y-auto">
          <Section title="Candidate information">
            <Facts items={[
              { label: 'Experience', value: s.total_experience },
              { label: 'Qualification', value: s.qualification },
              { label: 'Current company', value: s.current_company },
              { label: 'Location', value: s.current_location },
              { label: 'Notice period', value: s.notice_period },
              { label: 'Expected CTC', value: s.expected_ctc },
              { label: 'Email', value: s.can_email },
              { label: 'Phone', value: s.can_contact },
              { label: 'LinkedIn', value: s.linkedin },
              { label: 'Portfolio', value: s.portfolio },
            ]} />
            {!s.can_email && (
              <p className="text-[11.5px] text-[var(--text-muted)]">
                Contact details for this candidate are held by the Sparsh team.
              </p>
            )}
            {s.cover_note && (
              <div>
                <p className={LABEL}>Cover note</p>
                <p className="text-[12.5px] whitespace-pre-wrap text-[var(--text-main)]">
                  {s.cover_note}
                </p>
              </div>
            )}
          </Section>

          <Section title="Documents & interview record">
            <div className="flex flex-wrap gap-2">
              {s.has_cv ? (
                <Btn tone="primary" onClick={downloadCv} disabled={!!busy || !live}>
                  {busy === 'cv' ? <Loader2 size={13} className="animate-spin" />
                                 : <Download size={13} />} Download CV
                </Btn>
              ) : (
                <span className="text-[12px] text-[var(--text-muted)]">No CV attached.</span>
              )}
              {s.has_interview_report && (
                <Btn onClick={viewReport} disabled={!!busy || !live}>
                  {busy === 'report' ? <Loader2 size={13} className="animate-spin" />
                                     : <FileText size={13} />} View interview report
                </Btn>
              )}
              {s.has_interview_recording && (
                <Btn onClick={watchRecording} disabled={!!busy || !live}>
                  {busy === 'recording' ? <Loader2 size={13} className="animate-spin" />
                                        : <Video size={13} />} Watch interview
                </Btn>
              )}
            </div>

            {s.interview_report_summary && (
              <div className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] p-3">
                <p className={LABEL}>Interview summary</p>
                <p className="mt-1 text-[12.5px] whitespace-pre-wrap text-[var(--text-main)]">
                  {s.interview_report_summary}
                </p>
              </div>
            )}

            {!s.has_interview_report && !s.has_interview_recording && (
              <p className="text-[12px] text-[var(--text-muted)]">
                The interview record will appear here once the Sparsh team has completed and
                filed this candidate&apos;s interview.
              </p>
            )}

            {recording && (
              <div className="space-y-1.5">
                {/* No download control, and the browser's own one suppressed. See the
                    header note on what this does and does not promise. */}
                <video
                  src={recording.url}
                  controls
                  controlsList="nodownload noplaybackrate"
                  disablePictureInPicture
                  onContextMenu={(e) => e.preventDefault()}
                  className="w-full rounded-lg border border-[var(--border)] bg-black"
                >
                  <track kind="captions" />
                </video>
                <p className="text-[11px] text-[var(--text-muted)]">
                  {recording.title || 'Interview recording'}
                  {recording.duration_min ? ` · ${recording.duration_min} min` : ''}
                  {' · viewing only, this recording cannot be downloaded'}
                </p>
              </div>
            )}
          </Section>

          {share.note && (
            <Section title="From the Sparsh team">
              <p className="text-[12.5px] whitespace-pre-wrap text-[var(--text-main)]
                            border-l-2 border-[var(--border)] pl-3">
                {share.note}
              </p>
            </Section>
          )}

          <Section title="Progress">
            <ShareJourney share={share} variant="client" />
          </Section>

          {!!conversation.length && (
            <Section title="Remarks & feedback">
              <ul className="space-y-2.5">
                {conversation.map((h, i) => (
                  <li key={`${h.at}-${i}`}
                      className="rounded-lg border border-[var(--border)] p-3">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <span className="text-[12px] font-bold text-[var(--text-main)]">
                        {h.by_name || 'Unknown'}
                      </span>
                      <span className="text-[11px] text-[var(--text-muted)]">
                        {day(h.at)}{h.kind === 'sent_back' ? ' · sent back' : ''}
                      </span>
                    </div>
                    <p className="mt-1 text-[12.5px] whitespace-pre-wrap
                                  text-[var(--text-main)]">{h.remarks}</p>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {remarking && (
            <Section title={remarking === 'sent_back' ? 'Send back to Sparsh' : 'Add a remark'}>
              <p className="text-[12px] text-[var(--text-muted)]">
                {remarking === 'sent_back'
                  ? 'The Sparsh team is notified straight away. The candidate stays where '
                    + 'they are — this asks a question rather than giving a verdict.'
                  : 'Filed against this candidate. Helps us send you better matches.'}
              </p>
              <textarea
                rows={3} className={TEXTAREA} value={remark} autoFocus
                onChange={(e) => setRemark(e.target.value)}
                placeholder={remarking === 'sent_back'
                  ? 'e.g. Strong technically — could we confirm their notice period?'
                  : 'Your feedback on this candidate'}
              />
              <div className="flex gap-2">
                <Btn tone="primary" onClick={submitRemark} disabled={!remark.trim() || !!busy}>
                  {busy === 'remark' ? 'Sending…' : 'Send'}
                </Btn>
                <Btn onClick={() => { setRemarking(null); setRemark(''); }}>Cancel</Btn>
              </div>
            </Section>
          )}
        </div>

        {/* The action bar. Empty of verdicts once the share reaches a state the client can
            no longer move it from — which is the whole of §12's "do not keep showing actions
            that are no longer applicable", and it needs no rule here because the server
            already answered it in `allowed_statuses`. */}
        <footer className="px-5 py-4 border-t border-[var(--border)] flex flex-wrap
                           items-center justify-between gap-2">
          <div className="flex flex-wrap gap-2">
            {live && (
              <>
                <Btn onClick={() => setRemarking('remark')} disabled={!!busy}>
                  <MessageSquarePlus size={13} /> Add remark
                </Btn>
                <Btn onClick={() => setRemarking('sent_back')} disabled={!!busy}>
                  <CornerUpLeft size={13} /> Send back to Sparsh
                </Btn>
              </>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {live && allowed.map((status) => (
              <Btn key={status} tone={VERDICT_TONE[status] || 'ghost'}
                   onClick={() => record(status)} disabled={!!busy}>
                {busy === status ? 'Saving…' : (VERDICT_LABEL[status] || status)}
              </Btn>
            ))}
            <Btn onClick={onClose}>Close</Btn>
          </div>
        </footer>

        {!live && (
          <p className="px-5 pb-4 -mt-2 text-[12px] text-[var(--text-muted)]">
            This candidate has been withdrawn by the Sparsh team and is no longer available.
          </p>
        )}
      </div>
    </div>
  );
};

export default ClientCandidateProfile;
