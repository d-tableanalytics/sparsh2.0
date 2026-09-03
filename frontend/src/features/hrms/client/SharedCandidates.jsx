import React, { useCallback, useEffect, useState } from 'react';
import { Users, Download, ThumbsUp, ThumbsDown } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import { getShares, setShareStatus, getShareCv } from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal } from '../internal/internalKit.jsx';
import ShareJourney from './ShareJourney';

/**
 * HRMS ▸ the client's own screen — candidates Sparsh has shared with them.
 *
 * This is the one page in the module a user from OUTSIDE the tenant sees, so what it does
 * not show matters as much as what it does.
 *
 * It renders the SNAPSHOT the server put on the share, not a candidate record. The browser
 * never holds a candidate id, never calls a candidate endpoint, and could not read one if
 * it tried — the CLIENT role has no `candidate.read`. Everything on screen was chosen,
 * field by field, at the moment Sparsh shared the CV.
 *
 * The statuses offered here are the ones a client may set. Hired is absent on purpose: it
 * is a commercial fact with a fee attached and Sparsh records it. The server enforces that
 * regardless of what this list contains — this just avoids offering a button that 403s.
 */

// What a client may say about a candidate. Mirrors SHARE_CLIENT_SETTABLE on the server.
const CLIENT_STATUSES = [
  'Under Review', 'Shortlisted', 'Interview Scheduled', 'Selected', 'Rejected',
];

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

const SharedCandidates = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [responding, setResponding] = useState(null);
  const [viewing, setViewing] = useState(null);

  const canRespond = can(CAP.SHARE_RESPOND);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getShares(scope);
      setRows(data?.shares || []);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load your candidates.');
    } finally {
      setLoading(false);
    }
  }, [companyId, scope]);

  useEffect(() => { load(); }, [load]);

  // A real download, not a new tab.
  //
  // The server sets Content-Disposition on the signed link, so the browser saves the file
  // instead of rendering it — but `window.open` would still flash an empty tab that closes
  // itself the moment the download starts. A synthetic anchor click keeps the page still.
  //
  // `download` is set as a hint only: it is ignored cross-origin (the S3 link), which is
  // exactly why the disposition header is what actually names the file.
  const downloadCv = async (share) => {
    try {
      const { data } = await getShareCv(share.share_no, scope);
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

  const quick = async (share, status) => {
    try {
      await setShareStatus(share.share_no, { status }, scope);
      showSuccess(`Marked ${status}`);
      await load();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not record that.');
    }
  };

  return (
    <div className="space-y-4">
      <HrmsPageHeader
        title="Candidates shared with you"
        subtitle="CVs the Sparsh team has sent for your review"
        icon={Users}
      />

      {loading && <HrmsLoading />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && !rows.length && (
        <HrmsEmpty
          icon={Users}
          title="No candidates yet"
          hint="When Sparsh shares a CV with you it will appear here."
        />
      )}

      <div className="grid gap-3">
        {rows.map((share) => {
          const s = share.snapshot || {};
          return (
            <div
              key={share.share_no}
              className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4
                         space-y-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-[14px] font-bold text-[var(--text-main)]">
                      {s.candidate_name}
                    </p>
                    <Chip tone={TONE[share.status] || 'neutral'}>{share.status}</Chip>
                  </div>
                  <p className="text-[11.5px] text-[var(--text-muted)] font-mono mt-0.5">
                    {share.share_no} · shared {day(share.shared_at)}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {s.has_cv && (
                    <Btn tone="primary" onClick={() => downloadCv(share)}>
                      <Download size={13} /> Download CV
                    </Btn>
                  )}
                  <Btn onClick={() => setViewing(share)}>Details</Btn>
                  {canRespond && share.status !== 'Withdrawn' && (
                    <>
                      <Btn onClick={() => quick(share, 'Shortlisted')}>
                        <ThumbsUp size={13} /> Shortlist
                      </Btn>
                      <Btn tone="danger" onClick={() => setResponding(share)}>
                        <ThumbsDown size={13} /> Not a fit
                      </Btn>
                    </>
                  )}
                </div>
              </div>

              <Facts items={[
                { label: 'Experience', value: s.total_experience },
                { label: 'Qualification', value: s.qualification },
                { label: 'Current company', value: s.current_company },
                { label: 'Location', value: s.current_location },
                { label: 'Notice period', value: s.notice_period },
                { label: 'Expected CTC', value: s.expected_ctc },
              ]} />

              {share.note && (
                <p className="text-[12px] text-[var(--text-muted)] border-l-2
                              border-[var(--border)] pl-2">
                  <span className="font-semibold">From Sparsh:</span> {share.note}
                </p>
              )}

              {/* The client's own ladder. It ends the client-facing rungs at Selected and
                  shows one summary rung for our side — see ShareJourney: the isolation rule
                  that governs the data governs the progress indicator too. */}
              <div className="pt-2 border-t border-[var(--border)]">
                <p className="text-[10.5px] font-bold uppercase tracking-widest
                              text-[var(--text-muted)] mb-2">Progress</p>
                <ShareJourney share={share} variant="client" />
              </div>

              {share.status === 'Withdrawn' && (
                <p className="text-[12px] text-[var(--text-muted)]">
                  This CV has been withdrawn and is no longer available.
                </p>
              )}
            </div>
          );
        })}
      </div>

      {viewing && (
        <Modal
          title={viewing.snapshot?.candidate_name}
          subtitle={`${viewing.share_no} · ${viewing.status}`}
          onClose={() => setViewing(null)}
          footer={<Btn onClick={() => setViewing(null)}>Close</Btn>}
        >
          <div className="space-y-3">
            <Facts items={[
              { label: 'Experience', value: viewing.snapshot?.total_experience },
              { label: 'Qualification', value: viewing.snapshot?.qualification },
              { label: 'Current company', value: viewing.snapshot?.current_company },
              { label: 'Location', value: viewing.snapshot?.current_location },
              { label: 'Notice period', value: viewing.snapshot?.notice_period },
              { label: 'Expected CTC', value: viewing.snapshot?.expected_ctc },
              { label: 'Email', value: viewing.snapshot?.can_email },
              { label: 'Phone', value: viewing.snapshot?.can_contact },
              { label: 'LinkedIn', value: viewing.snapshot?.linkedin },
              { label: 'Portfolio', value: viewing.snapshot?.portfolio },
            ]} />
            {viewing.snapshot?.cover_note && (
              <div>
                <p className={LABEL}>Cover note</p>
                <p className="text-[12.5px] whitespace-pre-wrap text-[var(--text-main)]">
                  {viewing.snapshot.cover_note}
                </p>
              </div>
            )}
            {!viewing.snapshot?.can_email && (
              <p className="text-[11.5px] text-[var(--text-muted)]">
                Contact details are held by the Sparsh team for this candidate.
              </p>
            )}
          </div>
        </Modal>
      )}

      {responding && (
        <RespondModal
          scope={scope}
          share={responding}
          onClose={() => setResponding(null)}
          onDone={async (m) => { setResponding(null); showSuccess(m); await load(); }}
          onError={showError}
        />
      )}
    </div>
  );
};

const RespondModal = ({ scope, share, onClose, onDone, onError }) => {
  const [status, setStatus] = useState('Rejected');
  const [remarks, setRemarks] = useState('');
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await setShareStatus(share.share_no, { status, remarks: remarks || null }, scope);
      await onDone(`${share.snapshot?.candidate_name} marked ${status}`);
    } catch (err) {
      onError(err?.response?.data?.detail || 'Could not record that.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`Your verdict — ${share.snapshot?.candidate_name}`}
      subtitle="The Sparsh team is notified as soon as you record this."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={saving}>
            {saving ? 'Saving…' : 'Record'}
          </Btn>
        </>
      )}
    >
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className={LABEL} htmlFor="rs-status">Status</label>
          <select id="rs-status" className={FIELD} value={status}
                  onChange={(e) => setStatus(e.target.value)}>
            {CLIENT_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="rs-remarks">Feedback</label>
          <textarea id="rs-remarks" rows={3} className={TEXTAREA} value={remarks}
                    onChange={(e) => setRemarks(e.target.value)}
                    placeholder="Helps us send you better matches next time." />
        </div>
      </form>
    </Modal>
  );
};

export default SharedCandidates;
