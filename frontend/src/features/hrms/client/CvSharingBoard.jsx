import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Send, Share2, Download, Undo2, Users, ChevronDown, ChevronRight, FileVideo,
} from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getShares, shareCandidate, setShareStatus, withdrawShare, getShareCv,
  getCandidates, getClients, getCandidateVerification,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal, RecordList } from '../internal/internalKit.jsx';
import ShareJourney from './ShareJourney';
import InterviewRecordModal from '../recruitment/InterviewRecordModal';

/**
 * HRMS ▸ client track — CV sharing.
 *
 * Sparsh's board: which candidate went to which client, and where each one stands.
 *
 * The screen exists because a candidate's own pipeline stage cannot answer the question
 * this page is for. One CV goes to several clients and each runs their own process — so
 * the row here is the SHARE, not the candidate, and the same person legitimately appears
 * more than once with different statuses. Grouping by candidate is what makes that read as
 * intended rather than as duplicate rows.
 *
 * What the screen deliberately does not do: decide anything. Which statuses a client may
 * set, whether a CV may be shared at all, and what a client is allowed to see are all
 * server rules. This renders their outcome.
 *
 * The interview record (brief §10) is reachable from each candidate's group header, not from
 * a share row: it is filed against the CANDIDATE and every live share of them picks it up.
 * Offering it per client would suggest each client gets a different report, which is exactly
 * what it is not. The same modal is reached from the interview board, where a recruiter files
 * it in the first place — this is the second door, for the moment somebody asks "does this
 * client have everything they need?".
 */

// The spec's list, in process order, so the filter chips read as a pipeline rather than an
// alphabetical set.
const STATUSES = [
  'CV Shared', 'Under Review', 'Shortlisted', 'Interview Scheduled',
  'Selected', 'Offer in Progress', 'Hired', 'Rejected', 'Withdrawn',
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

const CvSharingBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState('');
  const [sharing, setSharing] = useState(false);
  const [busy, setBusy] = useState(false);
  // Which share's ladder is open, and the verification behind it. Fetched on expand
  // rather than for every row: the board lists every share in the company, and one
  // verification call per row would be dozens of requests for information nobody has
  // asked to see yet.
  const [openShare, setOpenShare] = useState(null);
  const [verifications, setVerifications] = useState({});

  const canWrite = can(CAP.SHARE_WRITE);
  const [recordFor, setRecordFor] = useState(null);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getShares({ ...scope, ...(status ? { status } : {}) });
      setRows(data?.shares || []);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load the sharing board.');
    } finally {
      setLoading(false);
    }
  }, [companyId, scope, status]);

  useEffect(() => { load(); }, [load]);

  /**
   * Expand or collapse one share's stage ladder.
   *
   * The handler the state, the import and the JSX above were all written for but which was
   * never added — clicking "Stages" threw a ReferenceError, so the ladder could not be
   * opened at all. Fixed here rather than left, because the stage view is what the brief
   * (§19) asks to be visible on this board.
   *
   * Verification is fetched on FIRST expand and then cached. Per-row on mount would be one
   * request per share for information nobody has asked to see, and re-fetching on every
   * toggle would repeat it; caching by `uk` also means a candidate shared with four clients
   * costs one call, not four, since the verification is the candidate's and not the share's.
   *
   * A failed fetch is deliberately not surfaced as an error toast: the ladder still renders
   * from the share itself and simply shows the verification rung as unknown, which is a
   * better outcome than refusing to open a panel because one of its two sources is down.
   */
  const toggleJourney = async (share) => {
    if (openShare === share.share_no) { setOpenShare(null); return; }
    setOpenShare(share.share_no);
    if (!share.uk || verifications[share.uk] !== undefined) return;
    try {
      const { data } = await getCandidateVerification(share.uk, scope);
      setVerifications((prev) => ({ ...prev, [share.uk]: data }));
    } catch {
      // Cached as null so a candidate whose verification cannot be read is not re-requested
      // on every open.
      setVerifications((prev) => ({ ...prev, [share.uk]: null }));
    }
  };

  // Grouped by candidate: the whole point of the page is seeing one person's several
  // clients together, which a flat list buries.
  const grouped = useMemo(() => {
    const byUk = new Map();
    rows.forEach((r) => {
      const key = r.uk || r.candidate_name;
      if (!byUk.has(key)) byUk.set(key, { name: r.candidate_name, uk: r.uk, shares: [] });
      byUk.get(key).shares.push(r);
    });
    return [...byUk.values()];
  }, [rows]);

  const move = async (share, next) => {
    setBusy(true);
    try {
      await setShareStatus(share.share_no, { status: next }, scope);
      showSuccess(`${share.candidate_name} → ${next} for ${share.client_name}`);
      await load();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not update that share.');
    } finally {
      setBusy(false);
    }
  };

  const pull = async (share) => {
    setBusy(true);
    try {
      await withdrawShare(share.share_no, { remarks: '' }, scope);
      showSuccess(`Withdrawn from ${share.client_name}`);
      await load();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not withdraw that CV.');
    } finally {
      setBusy(false);
    }
  };

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

  return (
    <div className="space-y-4">
      <HrmsPageHeader
        title="CV sharing"
        subtitle="Which candidate went to which client, and where each one stands"
        icon={Share2}
        actions={canWrite ? (
          <Btn tone="primary" onClick={() => setSharing(true)}>
            <Send size={14} /> Share a CV
          </Btn>
        ) : null}
      />
      <HrmsScopeBar />

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setStatus('')}
          className={`h-7 px-3 rounded-full text-[11.5px] font-semibold border ${
            status === ''
              ? 'bg-[var(--accent-indigo)] text-white border-transparent'
              : 'border-[var(--border)] text-[var(--text-muted)]'}`}
        >
          All
        </button>
        {STATUSES.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setStatus(s)}
            className={`h-7 px-3 rounded-full text-[11.5px] font-semibold border ${
              status === s
                ? 'bg-[var(--accent-indigo)] text-white border-transparent'
                : 'border-[var(--border)] text-[var(--text-muted)]'}`}
          >
            {s}
          </button>
        ))}
      </div>

      {loading && <HrmsLoading />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && !grouped.length && (
        <HrmsEmpty
          icon={Share2}
          title="Nothing shared yet"
          hint={canWrite
            ? 'Share a candidate’s CV with one or more clients to start tracking their response.'
            : 'No CVs have been shared with a client yet.'}
        />
      )}

      {!loading && !error && grouped.map((group) => (
        <div
          key={group.uk || group.name}
          className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 space-y-3"
        >
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <Users size={15} className="text-[var(--text-muted)]" />
              <p className="text-[13.5px] font-bold text-[var(--text-main)]">{group.name}</p>
              <Chip tone="neutral">
                {group.shares.length} client{group.shares.length === 1 ? '' : 's'}
              </Chip>
            </div>
            {group.uk && (
              <Btn onClick={() => setRecordFor(group)}>
                <FileVideo size={13} /> Interview record
              </Btn>
            )}
          </div>

          <div className="grid gap-2">
            {group.shares.map((share) => (
              <div
                key={share.share_no}
                className="rounded-lg border border-[var(--border)] p-3 flex flex-wrap
                           items-center justify-between gap-3"
              >
                <div className="min-w-[200px]">
                  <p className="text-[13px] font-semibold text-[var(--text-main)]">
                    {share.client_name}
                  </p>
                  <p className="text-[11.5px] text-[var(--text-muted)] font-mono">
                    {share.share_no} · shared {day(share.shared_at)}
                  </p>
                </div>
                <Chip tone={TONE[share.status] || 'neutral'}>{share.status}</Chip>
                <div className="flex flex-wrap gap-2">
                  <Btn onClick={() => toggleJourney(share)}
                       aria-expanded={openShare === share.share_no}>
                    {openShare === share.share_no
                      ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                    Stages
                  </Btn>
                  <Btn onClick={() => downloadCv(share)}>
                    <Download size={13} /> CV
                  </Btn>
                  {canWrite && share.status !== 'Withdrawn' && share.status !== 'Hired' && (
                    <>
                      <select
                        aria-label={`Set status for ${share.client_name}`}
                        className={FIELD}
                        style={{ width: 'auto', minWidth: 170 }}
                        value=""
                        disabled={busy}
                        onChange={(e) => e.target.value && move(share, e.target.value)}
                      >
                        <option value="">Move to…</option>
                        {STATUSES.filter((s) => s !== share.status && s !== 'Withdrawn')
                          .map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                      <Btn tone="danger" onClick={() => pull(share)} disabled={busy}>
                        <Undo2 size={13} /> Withdraw
                      </Btn>
                    </>
                  )}
                </div>
                {openShare === share.share_no && (
                  <div className="w-full mt-1 pt-3 border-t border-[var(--border)]">
                    <p className="text-[10.5px] font-bold uppercase tracking-widest
                                  text-[var(--text-muted)] mb-2">
                      Hiring stages — {share.client_name}
                    </p>
                    <ShareJourney
                      share={share}
                      variant="sparsh"
                      verification={verifications[share.uk]}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}

      {sharing && (
        <ShareModal
          scope={scope}
          onClose={() => setSharing(false)}
          onDone={async (msg) => { setSharing(false); showSuccess(msg); await load(); }}
          onError={showError}
        />
      )}
      {recordFor && (
        <InterviewRecordModal
          uk={recordFor.uk}
          candidateName={recordFor.name}
          onClose={() => setRecordFor(null)}
          // Filing publishes to every live share, so the board's own rows are stale the
          // moment it happens.
          onSaved={load}
        />
      )}
    </div>
  );
};

/**
 * Share one CV with one or more clients.
 *
 * Multi-select rather than one client at a time, because the requirement is explicitly
 * plural and doing it in one act is what makes the audit read as one decision.
 *
 * The result is reported per client: the server allows partial success (a client who
 * already has this CV is skipped, the rest still go), and hiding that would leave the user
 * believing five shares happened when four did.
 */
const ShareModal = ({ scope, onClose, onDone, onError }) => {
  const [candidates, setCandidates] = useState([]);
  const [clients, setClients] = useState([]);
  const [uk, setUk] = useState('');
  const [chosen, setChosen] = useState([]);
  const [note, setNote] = useState('');
  const [includeContact, setIncludeContact] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getCandidates({ ...scope, limit: 200 })
      .then(({ data }) => setCandidates(data?.candidates || [])).catch(() => {});
    getClients(scope)
      .then(({ data }) => setClients(data?.clients || [])).catch(() => {});
  }, [scope]);

  const toggle = (id) =>
    setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));

  const submit = async (e) => {
    e.preventDefault();
    if (!uk || !chosen.length) return;
    setSaving(true);
    try {
      const { data } = await shareCandidate({
        uk, client_ids: chosen, note: note || null, include_contact: includeContact,
      }, scope);
      const skipped = (data?.skipped || []).length;
      await onDone(
        `Shared with ${data?.count || 0} client(s)`
        + (skipped ? ` — ${skipped} skipped (already shared)` : ''),
      );
    } catch (err) {
      onError(err?.response?.data?.detail || 'Could not share that CV.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="Share a CV"
      subtitle="One candidate, one or more clients. Each client tracks their own status."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={saving || !uk || !chosen.length}>
            {saving ? 'Sharing…' : `Share with ${chosen.length || 0} client(s)`}
          </Btn>
        </>
      )}
    >
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className={LABEL} htmlFor="sh-cand">Candidate *</label>
          <select id="sh-cand" className={FIELD} value={uk}
                  onChange={(e) => setUk(e.target.value)} required>
            <option value="">Select a candidate…</option>
            {candidates.map((c) => (
              <option key={c.uk} value={c.uk}>
                {c.candidate_name} ({c.uk})
              </option>
            ))}
          </select>
          <p className="mt-1 text-[11px] text-[var(--text-muted)]">
            A candidate with no CV on file cannot be shared — upload one first.
          </p>
        </div>

        <div>
          <span className={LABEL}>Clients *</span>
          <div className="mt-1 max-h-48 overflow-y-auto rounded-lg border
                          border-[var(--border)] divide-y divide-[var(--border)]">
            {clients.map((c) => (
              <label
                key={c.client_id}
                className="flex items-center gap-2 px-3 py-2 text-[12.5px] cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={chosen.includes(c.client_id)}
                  onChange={() => toggle(c.client_id)}
                />
                <span className="text-[var(--text-main)]">{c.name}</span>
              </label>
            ))}
            {!clients.length && (
              <p className="px-3 py-2 text-[12px] text-[var(--text-muted)]">
                No clients on record yet.
              </p>
            )}
          </div>
        </div>

        <div>
          <label className={LABEL} htmlFor="sh-note">Covering note</label>
          <textarea id="sh-note" rows={3} className={TEXTAREA} value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Shown to every client this CV goes to." />
        </div>

        <label className="flex items-start gap-2 text-[12px] text-[var(--text-main)]">
          <input type="checkbox" checked={includeContact} className="mt-0.5"
                 onChange={(e) => setIncludeContact(e.target.checked)} />
          <span>
            Share the candidate’s contact details
            <span className="block text-[11px] text-[var(--text-muted)]">
              Off by default. A client who can contact the candidate directly can hire them
              around us — so this is a decision, not a default.
            </span>
          </span>
        </label>
      </form>
    </Modal>
  );
};

export default CvSharingBoard;
