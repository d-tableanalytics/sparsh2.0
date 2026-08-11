import React, { useCallback, useEffect, useState } from 'react';
import {
  Users2, Search, Plus, LayoutGrid, List as ListIcon, Columns3, X, Route, AlertTriangle,
  Mail, Phone, Save, Trash2,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getCandidates, getCandidate, updateCandidate, deleteCandidate, createCandidate,
  recordClientResponse,
} from '../../../services/hrmsApi';
import { CandidateJourneyModal } from './CandidateJourney';

/**
 * HRMS ▸ candidate pipeline.
 *
 * Three layouts over one dataset and one filter set: Kanban, List and Grid. The columns and
 * their counts come from the server, computed with the same scoping as the rows — so a
 * hiring manager's board totals reflect their own slice, never the company's.
 *
 * Stage changes are made in the drawer from `allowed_next` — the server's own answer for
 * what this candidate may legally become. There is no drag-and-drop: dropping a card into
 * an arbitrary column implies every move is legal, and most are not.
 */

const STAGE_TONE = (status) => {
  if (['Rejected', 'Duplicate', 'Offer Declined', 'Assessment Failed'].includes(status))
    return 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]';
  if (['Selected', 'Offer Accepted', 'Joined', 'Employee Created', 'Assessment Passed'].includes(status))
    return 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]';
  if (status === 'On Hold') return 'bg-[var(--input-bg)] text-[var(--text-muted)]';
  return 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]';
};

const StageBadge = ({ status }) => (
  <span className={`px-2 py-0.5 rounded-md text-[10.5px] font-bold whitespace-nowrap ${STAGE_TONE(status)}`}>
    {status}
  </span>
);

const CandidateCard = ({ candidate: c, onOpen }) => (
  <button type="button" onClick={() => onOpen(c.uk)}
    className="w-full text-left p-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--accent-indigo)] transition-colors">
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        <p className="text-[13px] font-bold text-[var(--text-main)] truncate">{c.candidate_name}</p>
        <p className="font-mono text-[10.5px] text-[var(--text-muted)]">{c.uk}</p>
      </div>
      {c.duplicate_flag && (
        <span title="Shares an email or phone with another candidate"
          className="px-1.5 py-0.5 rounded bg-[var(--accent-red-bg)] text-[var(--accent-red)] text-[9.5px] font-bold shrink-0">
          DUP
        </span>
      )}
    </div>
    {c.can_email && (
      <p className="mt-1.5 text-[11px] text-[var(--text-muted)] truncate">{c.can_email}</p>
    )}
    <div className="mt-2 flex items-center gap-1.5 flex-wrap">
      <StageBadge status={c.application_status} />
      {c.source && (
        <span className="text-[10.5px] text-[var(--text-muted)]">{c.source}</span>
      )}
    </div>
  </button>
);

const Drawer = ({ uk, onClose, onChanged }) => {
  const { can, scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [c, setC] = useState(null);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [journey, setJourney] = useState(false);
  // Phase 11-R, Item 4 — the client-verdict form.
  const [verdict, setVerdict] = useState('');
  const [verdictNote, setVerdictNote] = useState('');

  const canWrite = can(CAP.CANDIDATE_WRITE);

  const load = useCallback(async () => {
    setError(null);
    try {
      const { data } = await getCandidate(uk, scope);
      setC(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this candidate.');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uk]);

  useEffect(() => { load(); }, [load]);

  const move = async (status) => {
    const previous = c.application_status;
    // Optimistic: the move is almost always legal (the options came from the server), so
    // showing it immediately is right — and reverting on failure is cheap.
    setC((prev) => ({ ...prev, application_status: status }));
    setSaving(true);
    try {
      const { data } = await updateCandidate(uk, { application_status: status }, scope);
      setC(data);
      showSuccess(`Moved to ${status}`);
      onChanged();
    } catch (err) {
      setC((prev) => ({ ...prev, application_status: previous }));
      showError(err?.response?.data?.detail || 'Could not change the stage.');
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete ${c.candidate_name} (${uk})? This cannot be undone.`)) return;
    try {
      await deleteCandidate(uk, scope);
      showSuccess('Candidate deleted');
      onChanged();
      onClose();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not delete.');
    }
  };

  // ── Phase 11-R, Item 4 ── record the hiring client's verdict on a shared CV. The stage
  // move that follows is decided SERVER-side from CLIENT_RESPONSE_STATUS and checked
  // against the lifecycle graph, so this only submits the answer.
  const saveVerdict = async () => {
    try {
      await recordClientResponse(
        { uk, status: verdict, remarks: verdictNote.trim() || null }, scope,
      );
      showSuccess(`Client verdict recorded: ${verdict}`);
      setVerdict('');
      setVerdictNote('');
      await load();
      onChanged();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not record the verdict.');
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm" onClick={onClose} />
      <aside className="fixed right-0 top-0 h-screen w-full max-w-lg z-50 bg-[var(--bg-card)] border-l border-[var(--border)] shadow-2xl overflow-y-auto">
        <div className="sticky top-0 bg-[var(--bg-card)] border-b border-[var(--border)] px-5 py-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[16px] font-bold text-[var(--text-main)] truncate">
              {c?.candidate_name || 'Loading…'}
            </h2>
            <p className="font-mono text-[11.5px] text-[var(--text-muted)]">{uk}</p>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {c && (
              <button type="button" onClick={() => setJourney(true)} title="Journey"
                className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
                <Route size={16} />
              </button>
            )}
            {c && canWrite && (
              <button type="button" onClick={remove} title="Delete"
                className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)]">
                <Trash2 size={16} />
              </button>
            )}
            <button type="button" onClick={onClose}
              className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
              <X size={17} />
            </button>
          </div>
        </div>

        {error ? (
          <div className="p-5"><HrmsError message={error} onRetry={load} /></div>
        ) : !c ? (
          <HrmsLoading label="Loading candidate…" />
        ) : (
          <div className="p-5 space-y-5">
            <div className="flex items-center gap-2 flex-wrap">
              <StageBadge status={c.application_status} />
              {c.requires_assessment && (
                <span className="px-2 py-0.5 rounded-md text-[10.5px] font-bold bg-[var(--input-bg)] text-[var(--text-main)]">
                  Assessment required
                </span>
              )}
              {c.duplicate_flag && (
                <span className="px-2 py-0.5 rounded-md text-[10.5px] font-bold bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center gap-1">
                  <AlertTriangle size={11} /> Possible duplicate
                </span>
              )}
            </div>

            {canWrite && (
              <div>
                <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2">
                  Move to stage
                </p>
                {(c.allowed_next || []).length === 0 ? (
                  <p className="text-[12.5px] text-[var(--text-muted)]">
                    This is a final stage — the pipeline ends here.
                  </p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {c.allowed_next.map((s) => (
                      <button key={s} type="button" disabled={saving} onClick={() => move(s)}
                        className="px-2.5 py-1 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)] hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)] disabled:opacity-50">
                        {s}
                      </button>
                    ))}
                  </div>
                )}
                <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">
                  Only stages the lifecycle allows from here are offered.
                </p>
              </div>
            )}

            <div className="space-y-2">
              {c.can_email && (
                <a href={`mailto:${c.can_email}`}
                  className="flex items-center gap-2 text-[13px] text-[var(--accent-indigo)]">
                  <Mail size={14} /> {c.can_email}
                </a>
              )}
              {c.can_contact && (
                <p className="flex items-center gap-2 text-[13px] text-[var(--text-main)]">
                  <Phone size={14} className="text-[var(--text-muted)]" /> {c.can_contact}
                </p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              {[['Source', c.source], ['Requisition', c.request_no],
                ['Experience', c.total_experience], ['Qualification', c.qualification],
                ['Current company', c.current_company], ['Notice period', c.notice_period],
                ['Current CTC', c.current_ctc], ['Expected CTC', c.expected_ctc],
                ['Assigned to', c.assigned_recruiter_name]].map(([label, value]) => (
                <div key={label}>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{label}</p>
                  <p className="text-[12.5px] font-semibold text-[var(--text-main)] break-words">
                    {value || '—'}
                  </p>
                </div>
              ))}
            </div>

            {/* ── Phase 11-R, Item 5 ── the referral block, shown only when there is one. */}
            {c.is_referral && (
              <div className="p-3 rounded-xl border border-[var(--border)] bg-[var(--input-bg)]">
                <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                  Referral
                </p>
                <p className="mt-1 text-[12.5px] text-[var(--text-main)]">
                  {c.referred_by}
                  {c.referral_source && (
                    <span className="text-[var(--text-muted)]"> · {c.referral_source}</span>
                  )}
                </p>
                {c.referrer_name && (
                  <p className="text-[11.5px] text-[var(--text-muted)]">
                    Verified employee: {c.referrer_name}
                    {c.referrer_employee_code && ` (${c.referrer_employee_code})`}
                  </p>
                )}
              </div>
            )}

            {/* ── Phase 11-R, Item 4 ── record the client's verdict on a shared CV.
                Entered by an HRMS user on the client's behalf: there is deliberately no
                public client portal in this phase, which would be a second unauthenticated
                surface with its own credentials and threat model. */}
            {c.client_share?.shared_at && (
              <div className="p-3 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] space-y-2.5">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                    Shared with client
                  </p>
                  <p className="mt-1 text-[12.5px] text-[var(--text-main)]">
                    Verdict: <b>{c.client_share.status || 'Pending'}</b>
                    {c.client_share.client_contact && (
                      <span className="text-[var(--text-muted)]">
                        {' '}· {c.client_share.client_contact}
                      </span>
                    )}
                  </p>
                </div>

                {can(CAP.CANDIDATE_SCREEN) && c.client_share.status === 'Pending' && (
                  <div className="space-y-2">
                    <select
                      value={verdict}
                      onChange={(e) => setVerdict(e.target.value)}
                      className="w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[13px] text-[var(--text-main)]"
                    >
                      <option value="">Record the client&rsquo;s verdict…</option>
                      <option value="Shortlisted">Shortlisted</option>
                      <option value="Rejected">Rejected</option>
                      <option value="On Hold">On hold</option>
                    </select>
                    <textarea
                      value={verdictNote}
                      onChange={(e) => setVerdictNote(e.target.value)}
                      placeholder="The client's remarks (required to reject)"
                      className="w-full h-16 px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[13px] text-[var(--text-main)] resize-none"
                    />
                    <button
                      type="button"
                      disabled={!verdict || (verdict === 'Rejected' && !verdictNote.trim())}
                      onClick={saveVerdict}
                      className="h-8 px-3.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50"
                    >
                      Record verdict
                    </button>
                  </div>
                )}
              </div>
            )}

            {c.cover_note && (
              <div>
                <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Note</p>
                <p className="mt-1 text-[12.5px] text-[var(--text-main)] whitespace-pre-wrap">{c.cover_note}</p>
              </div>
            )}
          </div>
        )}
      </aside>

      {journey && c && (
        <CandidateJourneyModal uk={uk} name={c.candidate_name} onClose={() => setJourney(false)} />
      )}
    </>
  );
};

const AddModal = ({ onClose, onCreated }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [form, setForm] = useState({
    candidate_name: '', can_email: '', can_contact: '', source: 'Referral',
    total_experience: '', qualification: '', expected_ctc: '',
    // ── Phase 11-R, Item 5 ── the SAME referral fields the public form captures, validated
    // by the same server-side resolver. A referral HR types onto a walk-in CV must be as
    // reportable as one an applicant declared, or the referral figures count two things.
    is_referral: false, referred_by: '', referral_source: '',
    referrer_employee_code: '', referral_relation: '',
  });
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
  const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await createCandidate(form, scope);
      showSuccess('Candidate added');
      onCreated();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not add the candidate.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <h2 className="text-[15px] font-bold text-[var(--text-main)]">Add a candidate</h2>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>
        <form onSubmit={submit} className="p-5 space-y-3">
          <p className="text-[12px] text-[var(--text-muted)]">
            For walk-ins, referrals and agency CVs. Candidates who apply through a posting
            arrive automatically.
          </p>
          <div>
            <label className={LABEL} htmlFor="c-name">Full name *</label>
            <input id="c-name" required value={form.candidate_name} onChange={set('candidate_name')} className={FIELD} />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={LABEL} htmlFor="c-email">Email</label>
              <input id="c-email" type="email" value={form.can_email} onChange={set('can_email')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="c-phone">Phone</label>
              <input id="c-phone" value={form.can_contact} onChange={set('can_contact')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="c-source">Source</label>
              <select id="c-source" value={form.source} onChange={set('source')} className={FIELD}>
                {['Referral', 'Walk-in', 'Agency', 'Manual', 'LinkedIn', 'Naukri'].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="c-exp">Experience</label>
              <input id="c-exp" value={form.total_experience} onChange={set('total_experience')} className={FIELD} />
            </div>
          </div>
          <p className="text-[11px] text-[var(--text-muted)]">
            Provide at least an email address or a phone number.
          </p>

          {/* ── Phase 11-R, Item 5 ── collapsed by default, exactly as on the public form. */}
          <div className="pt-2 border-t border-[var(--border)] space-y-3">
            <label className="flex items-center gap-2 text-[12.5px] text-[var(--text-main)]">
              <input
                type="checkbox"
                checked={form.is_referral}
                onChange={(e) => setForm((f) => ({ ...f, is_referral: e.target.checked }))}
              />
              This candidate was referred
            </label>

            {form.is_referral && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className={LABEL} htmlFor="c-refby">Referred by *</label>
                  <input id="c-refby" value={form.referred_by}
                    onChange={set('referred_by')} className={FIELD} />
                </div>
                <div>
                  <label className={LABEL} htmlFor="c-refsrc">Referral source *</label>
                  <select id="c-refsrc" value={form.referral_source}
                    onChange={set('referral_source')} className={FIELD}>
                    <option value="">Choose…</option>
                    {['Employee', 'Ex-Employee', 'Consultant / Agency', 'Job Portal',
                      'Social Media', 'Walk-in', 'Client', 'Other'].map((s) => (
                        <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>
                {form.referral_source === 'Employee' && (
                  <div className="sm:col-span-2">
                    <label className={LABEL} htmlFor="c-refcode">
                      Referring employee code *
                    </label>
                    <input id="c-refcode" value={form.referrer_employee_code}
                      onChange={set('referrer_employee_code')}
                      placeholder="EMP-2026-014" className={FIELD} />
                  </div>
                )}
                <div className="sm:col-span-2">
                  <label className={LABEL} htmlFor="c-refrel">Relationship</label>
                  <input id="c-refrel" value={form.referral_relation}
                    onChange={set('referral_relation')} className={FIELD} />
                </div>
              </div>
            )}
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="submit" disabled={saving || !form.candidate_name.trim()}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Adding…' : 'Add candidate'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

const CandidatePipeline = () => {
  const { can, scope, companyId } = useHrms();

  const [data, setData] = useState({ candidates: [], columns: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [layout, setLayout] = useState('kanban');
  const [openUk, setOpenUk] = useState(null);
  const [showAdd, setShowAdd] = useState(false);

  const canWrite = can(CAP.CANDIDATE_WRITE);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data: res } = await getCandidates({
        ...scope, search: debounced || undefined, limit: 500,
      });
      setData(res);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load candidates.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, debounced]);

  useEffect(() => { load(); }, [load]);

  const byColumn = (statuses) =>
    data.candidates.filter((c) => statuses.includes(c.application_status));

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={Users2}
        title="Candidates"
        subtitle={`${data.total || 0} in the pipeline`}
        actions={
          <div className="flex items-center gap-2">
            <HrmsScopeBar />
            <div className="flex rounded-lg border border-[var(--border)] overflow-hidden">
              {[['kanban', Columns3], ['list', ListIcon], ['grid', LayoutGrid]].map(([key, Icon]) => (
                <button key={key} type="button" onClick={() => setLayout(key)} title={key}
                  className={`h-9 w-9 grid place-items-center ${
                    layout === key ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                                   : 'text-[var(--text-muted)]'}`}>
                  <Icon size={15} />
                </button>
              ))}
            </div>
            {canWrite && (
              <button type="button" onClick={() => setShowAdd(true)}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5">
                <Plus size={14} /> Add
              </button>
            )}
          </div>
        }
      />

      <div className="relative max-w-md">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
        <input value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name, ID, email or phone…"
          className="w-full h-9 pl-9 pr-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]" />
      </div>

      {loading ? (
        <HrmsLoading label="Loading candidates…" />
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : data.candidates.length === 0 ? (
        <HrmsEmpty icon={Users2} title="No candidates"
          hint={search ? 'Try a different search.'
                       : 'Applications from your live postings will appear here.'} />
      ) : layout === 'kanban' ? (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {data.columns.map((col) => {
            const rows = byColumn(col.statuses);
            return (
              <div key={col.key} className="w-[280px] shrink-0">
                <div className="flex items-center justify-between px-1 mb-2">
                  <span className="text-[11.5px] font-bold text-[var(--text-main)]">{col.label}</span>
                  <span className="text-[11px] font-bold text-[var(--text-muted)]">{col.count}</span>
                </div>
                <div className="space-y-2">
                  {rows.length === 0 ? (
                    <p className="p-3 rounded-xl border border-dashed border-[var(--border)] text-[11.5px] text-[var(--text-muted)] text-center">
                      No candidates
                    </p>
                  ) : rows.map((c) => (
                    <CandidateCard key={c.uk} candidate={c} onOpen={setOpenUk} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ) : layout === 'grid' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {data.candidates.map((c) => (
            <CandidateCard key={c.uk} candidate={c} onOpen={setOpenUk} />
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-[var(--border)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[720px]">
            <thead className="bg-[var(--input-bg)] text-[var(--text-muted)]">
              <tr>
                {['Candidate', 'Stage', 'Source', 'Requisition', 'Applied'].map((h) => (
                  <th key={h} className="text-left px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.candidates.map((c) => (
                <tr key={c.uk} onClick={() => setOpenUk(c.uk)}
                  className="border-t border-[var(--border)] cursor-pointer hover:bg-[var(--input-bg)]">
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <span className="font-semibold text-[var(--text-main)]">{c.candidate_name}</span>
                      {c.duplicate_flag && (
                        <span className="px-1 rounded bg-[var(--accent-red-bg)] text-[var(--accent-red)] text-[9.5px] font-bold">DUP</span>
                      )}
                    </div>
                    <span className="text-[11px] text-[var(--text-muted)]">{c.can_email || c.uk}</span>
                  </td>
                  <td className="px-4 py-2.5"><StageBadge status={c.application_status} /></td>
                  <td className="px-4 py-2.5 text-[var(--text-main)]">{c.source || '—'}</td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">{c.request_no || '—'}</td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">
                    {c.applied_at ? new Date(c.applied_at).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openUk && (
        <Drawer uk={openUk} onClose={() => setOpenUk(null)} onChanged={load} />
      )}
      {showAdd && (
        <AddModal onClose={() => setShowAdd(false)}
          onCreated={() => { setShowAdd(false); load(); }} />
      )}
    </div>
  );
};

export default CandidatePipeline;
