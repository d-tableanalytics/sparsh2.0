import React, { useCallback, useEffect, useState } from 'react';
import {
  Download, FileText, PlayCircle, ThumbsUp, ThumbsDown, Undo2, MessageSquare, X,
} from 'lucide-react';
import { CAP } from '../access';
import { useHrms } from '../HrmsContext';
import { useNotification } from '../../../context/NotificationContext';
import {
  getSharedCandidateHub, getShareInterviewMedia, getShareCv, setShareStatus,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal } from '../internal/internalKit.jsx';
import ShareJourney from './ShareJourney';

/**
 * HRMS ▸ the client's candidate hub (spec §11).
 *
 * One place holding everything a client needs about one candidate: profile, CV, interviews,
 * the report, the recording, their own decision history, and the actions still open to them.
 *
 * -- Three artefacts, three different permissions, shown as three different controls -------
 *     CV                  Download   -- a real file, saved to their machine
 *     Interview report    Open       -- rendered, not saved
 *     Interview recording Watch      -- played in place, and there is no download button
 *
 * The buttons differ because the permissions differ. Offering "Download" on all three and
 * failing two of them server-side would be the worse design: a control that exists and does
 * not work teaches people the system is broken rather than that the rule is deliberate.
 *
 * -- Actions follow the status -------------------------------------------------------------
 * §12 asks that a rejected candidate stop offering actions that no longer apply. What is
 * available comes from the server's `can_respond` plus the status, not from a fixed list.
 */

const TONE = {
  'CV Shared': 'info', 'Under Review': 'info', Shortlisted: 'good',
  'Interview Scheduled': 'info', Selected: 'good', 'Offer in Progress': 'warn',
  Hired: 'good', Rejected: 'bad', 'Sent Back to Sparsh': 'warn', Withdrawn: 'neutral',
};

const CandidateHub = ({ shareNo, onClose, onChanged }) => {
  const { scope, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [hub, setHub] = useState(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(null);      // 'Rejected' | 'Sent Back to Sparsh'
  const [watching, setWatching] = useState(null);  // {url, name, mime}

  const canRespond = can(CAP.SHARE_RESPOND);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getSharedCandidateHub(shareNo, scope);
      setHub(data);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not open that candidate.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shareNo, scope]);

  useEffect(() => { load(); }, [load]);

  const downloadCv = async () => {
    try {
      const { data } = await getShareCv(shareNo, scope);
      if (!data?.url) return;
      const a = document.createElement('a');
      a.href = data.url;
      a.download = data.name || 'cv.pdf';
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not download that CV.');
    }
  };

  const openMedia = async (interviewNo, kind) => {
    try {
      const { data } = await getShareInterviewMedia(shareNo, interviewNo, kind, scope);
      if (kind === 'report') {
        // Opened, not saved. A PDF renders in the tab; the browser's own controls are the
        // client's business from there.
        const target = data.external_url || data.stream_url;
        if (target) window.open(target, '_blank', 'noopener');
        return;
      }
      if (data.external_url) {
        window.open(data.external_url, '_blank', 'noopener');
        return;
      }
      setWatching({ url: data.stream_url, name: data.name,
                    mime: data.mime_type, duration: data.duration_minutes });
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not open that.');
    }
  };

  const move = async (status, remarks) => {
    try {
      await setShareStatus(shareNo, { status, remarks: remarks || null }, scope);
      showSuccess(`Recorded: ${status}`);
      setActing(null);
      await load();
      if (onChanged) await onChanged();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not record that.');
    }
  };

  const s = hub?.snapshot || {};
  const live = hub?.can_respond && canRespond;

  return (
    <Modal
      title={s.candidate_name || 'Candidate'}
      subtitle={hub ? `${hub.share_no} · ${hub.status}` : 'Loading…'}
      onClose={onClose}
      footer={<Btn onClick={onClose}>Close</Btn>}
    >
      {loading && <p className="text-[12px] text-[var(--text-muted)]">Loading…</p>}

      {hub && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone={TONE[hub.status] || 'neutral'}>{hub.status}</Chip>
            {s.has_cv && (
              <Btn tone="primary" onClick={downloadCv}>
                <Download size={13} /> Download CV
              </Btn>
            )}
          </div>

          <section>
            <p className={LABEL}>Candidate</p>
            <Facts items={[
              { label: 'Experience', value: s.total_experience },
              { label: 'Qualification', value: s.qualification },
              { label: 'Current company', value: s.current_company },
              { label: 'Location', value: s.current_location },
              { label: 'Notice period', value: s.notice_period },
              { label: 'Expected CTC', value: s.expected_ctc },
              { label: 'Email', value: s.can_email },
              { label: 'Phone', value: s.can_contact },
            ]} />
            {s.cover_note && (
              <p className="mt-2 text-[12.5px] whitespace-pre-wrap text-[var(--text-main)]">
                {s.cover_note}
              </p>
            )}
            {!s.can_email && (
              <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                Contact details are held by the Sparsh team for this candidate.
              </p>
            )}
          </section>

          <section>
            <p className={LABEL}>Interviews</p>
            {!hub.interviews?.length && (
              <p className="text-[12px] text-[var(--text-muted)]">
                No interview has been shared for this candidate yet.
              </p>
            )}
            <div className="space-y-2">
              {(hub.interviews || []).map((iv) => (
                <div key={iv.interview_no}
                     className="rounded-lg border border-[var(--border)] p-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-[12.5px] font-semibold text-[var(--text-main)]">
                      {iv.round}
                      <span className="ml-2 font-normal text-[11.5px]
                                       text-[var(--text-muted)]">
                        {day(iv.scheduled_at)}
                      </span>
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {iv.report && (
                        <Btn onClick={() => openMedia(iv.interview_no, 'report')}>
                          <FileText size={12} /> Report
                        </Btn>
                      )}
                      {iv.recording && (
                        <Btn onClick={() => openMedia(iv.interview_no, 'recording')}>
                          <PlayCircle size={12} /> Watch
                        </Btn>
                      )}
                    </div>
                  </div>
                  {iv.recording?.notes && (
                    <p className="mt-1 text-[11.5px] text-[var(--text-muted)]">
                      {iv.recording.notes}
                    </p>
                  )}
                  {!iv.report && !iv.recording && (
                    <p className="mt-1 text-[11.5px] text-[var(--text-muted)]">
                      No report or recording shared for this round.
                    </p>
                  )}
                </div>
              ))}
            </div>
          </section>

          <section>
            <p className={LABEL}>Progress</p>
            <ShareJourney share={{ ...hub, history: hub.timeline }} variant="client" />
          </section>

          {hub.timeline?.some((t) => t.remarks) && (
            <section>
              <p className={LABEL}>Remarks</p>
              <div className="space-y-1.5">
                {hub.timeline.filter((t) => t.remarks).map((t, i) => (
                  <p key={`${t.status}-${i}`}
                     className="text-[12px] text-[var(--text-main)] border-l-2
                                border-[var(--border)] pl-2">
                    <span className="font-semibold">{t.status}</span>
                    <span className="text-[var(--text-muted)]"> · {day(t.at)}</span>
                    <span className="block">{t.remarks}</span>
                  </p>
                ))}
              </div>
            </section>
          )}

          {live && (
            <section>
              <p className={LABEL}>Your decision</p>
              <div className="flex flex-wrap gap-2">
                <Btn tone="primary" onClick={() => move('Shortlisted')}>
                  <ThumbsUp size={13} /> Shortlist
                </Btn>
                <Btn onClick={() => move('Interview Scheduled')}>
                  Interview scheduled
                </Btn>
                <Btn onClick={() => move('Selected')}>
                  Approve candidate
                </Btn>
                <Btn tone="danger" onClick={() => setActing('Rejected')}>
                  <ThumbsDown size={13} /> Reject
                </Btn>
                {/* §12: handing a candidate back is not a rejection. The client keeps the
                    door open and Sparsh gets the reason. */}
                <Btn onClick={() => setActing('Sent Back to Sparsh')}>
                  <Undo2 size={13} /> Send back to Sparsh
                </Btn>
              </div>
            </section>
          )}
          {!live && (
            <p className="text-[12px] text-[var(--text-muted)]">
              {hub.status === 'Withdrawn'
                ? 'This candidate has been withdrawn by the Sparsh team.'
                : `No further action is open on this candidate (${hub.status}).`}
            </p>
          )}
        </div>
      )}

      {acting && (
        <RemarkModal
          status={acting}
          candidate={s.candidate_name}
          onClose={() => setActing(null)}
          onConfirm={(remarks) => move(acting, remarks)}
        />
      )}
      {watching && (
        <WatchModal media={watching} onClose={() => setWatching(null)} />
      )}
    </Modal>
  );
};

const RemarkModal = ({ status, candidate, onClose, onConfirm }) => {
  const [remarks, setRemarks] = useState('');
  const sendBack = status === 'Sent Back to Sparsh';
  return (
    <Modal
      title={sendBack ? `Send ${candidate} back to Sparsh` : `Reject ${candidate}`}
      subtitle={sendBack
        ? 'They stay available for your other roles.'
        : 'This closes the candidate for this requirement.'}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone={sendBack ? 'primary' : 'danger'}
               onClick={() => onConfirm(remarks.trim())}>
            {sendBack ? 'Send back' : 'Reject'}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <p className="text-[12px] text-[var(--text-muted)]">
          {sendBack
            ? 'Tell the Sparsh team what did not fit. It is what shapes the next CVs they '
              + 'send you, and the candidate is not marked as rejected.'
            : 'Your feedback reaches the Sparsh team. The candidate is not told directly.'}
        </p>
        <div>
          <label className={LABEL} htmlFor="rm-note">
            {sendBack ? 'What should we look for instead?' : 'Reason'}
          </label>
          <textarea id="rm-note" rows={3} className={TEXTAREA} value={remarks}
                    onChange={(e) => setRemarks(e.target.value)}
                    placeholder={sendBack
                      ? 'e.g. Strong technically, but we need someone in Bhopal.'
                      : 'e.g. Not enough depth in Node.js for this role.'} />
        </div>
      </div>
    </Modal>
  );
};

/**
 * The player. No `controlsList="nodownload"` theatre and no right-click blocking: both are
 * trivially bypassed and pretending otherwise is worse than being straight about it. What
 * this does is not offer a download, and the URL behind it expires.
 */
const WatchModal = ({ media, onClose }) => (
  <Modal
    title={media.name || 'Interview recording'}
    subtitle={media.duration ? `${media.duration} minutes` : 'Recorded interview'}
    onClose={onClose}
    footer={<Btn onClick={onClose}><X size={13} /> Close</Btn>}
  >
    <div className="space-y-2">
      {String(media.mime || '').startsWith('audio/') ? (
        <audio src={media.url} controls autoPlay className="w-full">
          <track kind="captions" />
        </audio>
      ) : (
        <video src={media.url} controls autoPlay playsInline
               className="w-full rounded-lg bg-black max-h-[60vh]">
          <track kind="captions" />
        </video>
      )}
      <p className="text-[11px] text-[var(--text-muted)]">
        Shared with you for this candidate. The link expires, and the Sparsh team can see
        that it was opened.
      </p>
    </div>
  </Modal>
);

export default CandidateHub;
