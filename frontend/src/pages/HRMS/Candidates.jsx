import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  UserPlus, Users, Search, X, Loader2, AlertTriangle, Link2, Copy, Check,
  Send, CalendarPlus, ChevronRight, Megaphone, Plus, ClipboardList, History,
  Award, Mail, UserCheck, Ban, ShieldCheck,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import {
  getCandidates, createCandidate, screenCandidates, sendAssessment, scheduleInterview,
  evaluateInterview, getPostings, createPosting, updatePosting, getRequisitions,
  reviewAssessment, createOffer, withdrawOffer, inviteOnboarding, verifyOnboarding,
  convertCandidate,
} from '../../services/hrmsApi';
import { hasHrmsPermission } from '../../utils/hrmsAccess';
import { StatTile, Field } from '../../components/hrms/hrmsUi';
import { inputCls, fmtDate, fmtDateTime } from '../../components/hrms/hrmsStyles';

// HRMS ▸ Candidates. Two tabs: the pipeline board and the job postings that feed it.
//
// The pipeline is FORWARD-ONLY server-side, so the stage buttons offer only legal moves and a
// bulk action reports what it skipped rather than silently doing less than asked.
//
// Assessment links are shown exactly once, when created. No list response contains one — the
// reference returns every candidate's access code to any logged-in user.

const STAGE_TONE = {
  Applied:     'var(--accent-indigo)',
  Shortlisted: 'var(--accent-yellow)',
  Assessment:  'var(--accent-orange)',
  Interview:   'var(--badge-type-text)',
  Offer:       'var(--accent-green)',
  Hired:       'var(--status-active-text)',
  Rejected:    'var(--accent-red)',
};

const StageChip = ({ stage }) => (
  <span className="inline-block px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest border whitespace-nowrap"
    style={{ color: STAGE_TONE[stage] || 'var(--text-muted)', borderColor: 'currentColor' }}>
    {stage}
  </span>
);

const EMPTY_CANDIDATE = {
  request_no: '', full_name: '', email: '', phone: '', current_company: '',
  experience_years: '', current_ctc: '', expected_ctc: '', notice_period: '', source: 'Direct',
};

const EMPTY_OFFER = {
  designation: '', department: '', annual_ctc: '', joining_date: '', location: '',
  employment_type: 'Full-time', probation_months: 6, notes: '', valid_till: '',
};

// An offer stops being "live" once the candidate has answered or HR pulled it back.
const OFFER_FINAL = ['Accepted', 'Declined', 'Withdrawn'];

const OFFER_TONE = {
  Sent:      'var(--accent-orange)',
  Accepted:  'var(--accent-green)',
  Declined:  'var(--accent-red)',
  Withdrawn: 'var(--text-muted)',
  Draft:     'var(--text-muted)',
};

const Candidates = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const navigate = useNavigate();

  const canCreate = hasHrmsPermission(user, 'recruitment', 'create');
  const canUpdate = hasHrmsPermission(user, 'recruitment', 'update');
  // Converting a hire into an employee writes to the core HR module, so it needs hrms.create on
  // top of the recruitment grant — the backend enforces this and 403s otherwise.
  const canConvert = hasHrmsPermission(user, 'hrms', 'create');

  const [tab, setTab] = useState('pipeline');
  const [data, setData] = useState(null);
  const [postings, setPostings] = useState([]);
  const [approvedReqs, setApprovedReqs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [search, setSearch] = useState('');
  const [stageFilter, setStageFilter] = useState('');
  const [selected, setSelected] = useState(new Set());
  const [busy, setBusy] = useState('');

  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState(EMPTY_CANDIDATE);
  const [detail, setDetail] = useState(null);

  // The one place an access code is ever shown.
  const [issuedLink, setIssuedLink] = useState(null);
  const [copied, setCopied] = useState(false);

  const [postingForm, setPostingForm] = useState({ request_no: '', platform: '', expires_on: '', notes: '' });
  const [showPostingForm, setShowPostingForm] = useState(false);

  // Interview scheduling / scoring, inline on the candidate detail panel.
  const [scheduling, setScheduling] = useState(null);
  const [interviewForm, setInterviewForm] = useState({
    round_name: 'Round 1', scheduled_at: '', mode: 'In person', duration_minutes: 45,
  });

  // Offer & onboarding controls, inline on the candidate detail panel (Phase 7).
  // Assessment review is per-assessment, so its form state is keyed by assessment id.
  const [reviewForm, setReviewForm] = useState({});
  const [showOfferForm, setShowOfferForm] = useState(false);
  const [offerForm, setOfferForm] = useState(EMPTY_OFFER);
  const [showOnbForm, setShowOnbForm] = useState(false);
  const [onbForm, setOnbForm] = useState({ message: '', due_on: '' });
  const [showVerify, setShowVerify] = useState(false);
  const [verifyRemarks, setVerifyRemarks] = useState('');
  const [showConvert, setShowConvert] = useState(false);
  const [convertForm, setConvertForm] = useState({ user_id: '', date_of_joining: '' });

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getCandidates({
        search: search || undefined,
        stage: stageFilter || undefined,
      });
      setData(res.data);
      setSelected(new Set());
      if (detail) {
        setDetail(res.data.candidates.find((c) => c.uk === detail.uk) || null);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load candidates');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, stageFilter]);

  useEffect(() => { load(); }, [load]);

  const loadPostings = useCallback(async () => {
    try {
      const [p, r] = await Promise.all([getPostings(), getRequisitions({ approval_status: 'Approved' })]);
      setPostings(p.data || []);
      setApprovedReqs(r.data?.requisitions || []);
    } catch { /* the tab shows its own empty state */ }
  }, []);

  useEffect(() => { if (tab === 'postings') loadPostings(); }, [tab, loadPostings]);

  // Opening (or switching) a candidate resets the inline Phase-7 forms, so one candidate's
  // half-filled offer / onboarding never bleeds onto the next.
  useEffect(() => {
    setShowOfferForm(false);
    setOfferForm(EMPTY_OFFER);
    setShowOnbForm(false);
    setOnbForm({ message: '', due_on: '' });
    setShowVerify(false);
    setVerifyRemarks('');
    setShowConvert(false);
    setConvertForm({ user_id: '', date_of_joining: '' });
    setReviewForm({});
  }, [detail?.uk]);

  const candidates = data?.candidates ?? [];
  const counts = data?.counts ?? {};
  const stages = data?.stages ?? [];

  // Offer / onboarding state for the open candidate. `pendingOffer` is the one live (non-final)
  // offer; `acceptedOffer` gates the whole onboarding block.
  const detailOffers = detail?.offers ?? [];
  const pendingOffer = detailOffers.find((o) => !OFFER_FINAL.includes(o.status)) || null;
  const acceptedOffer = detailOffers.find((o) => o.status === 'Accepted') || null;
  const onboarding = detail?.onboarding || null;

  const toggle = (id) => setSelected((s) => {
    const next = new Set(s);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const move = async (stage) => {
    if (!selected.size) return;
    setBusy('move');
    try {
      const res = await screenCandidates({ candidate_ids: [...selected], stage });
      const { moved, skipped } = res.data;
      if (moved) showSuccess(`${moved} candidate(s) moved to ${stage}`);
      // Skipped rows are surfaced — a bulk action must not appear to have done more than it did.
      if (skipped?.length) {
        showError(`${skipped.length} skipped: ${skipped[0].reason}${skipped.length > 1 ? '…' : ''}`);
      }
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to move candidates');
    } finally {
      setBusy('');
    }
  };

  const addCandidate = async () => {
    if (!form.full_name.trim() || !form.email.trim()) {
      showError('Name and email are required');
      return;
    }
    setBusy('add');
    try {
      await createCandidate(form);
      showSuccess('Candidate added');
      setForm(EMPTY_CANDIDATE);
      setShowAdd(false);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to add candidate');
    } finally {
      setBusy('');
    }
  };

  const issueAssessment = async (c) => {
    setBusy('assess');
    try {
      const res = await sendAssessment(c.uk, {
        title: 'Written assessment',
        instructions: 'Please answer in your own words.',
        questions: ['Tell us about a project you are proud of.'],
      });
      setIssuedLink({
        title: `Assessment link for ${c.fullName}`,
        url: `${window.location.origin}/assess/${res.data.accessCode}`,
      });
      setCopied(false);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to create assessment');
    } finally {
      setBusy('');
    }
  };

  const addInterview = async (c) => {
    if (!interviewForm.scheduled_at) { showError('Choose a date and time'); return; }
    setBusy('interview');
    try {
      await scheduleInterview(c.uk, interviewForm);
      showSuccess(`${interviewForm.round_name} scheduled`);
      setScheduling(null);
      setInterviewForm({ round_name: 'Round 1', scheduled_at: '', mode: 'In person', duration_minutes: 45 });
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to schedule interview');
    } finally {
      setBusy('');
    }
  };

  const scoreInterview = async (c, interviewId, recommendation) => {
    setBusy('score');
    try {
      await evaluateInterview(c.uk, interviewId, { recommendation });
      showSuccess(`Recorded: ${recommendation}`);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to record the scorecard');
    } finally {
      setBusy('');
    }
  };

  // ── Phase 7: assessment review, offers, onboarding, conversion ──
  const submitReview = async (c, a) => {
    const f = reviewForm[a.id] || {};
    if (f.score === undefined || f.score === '') { showError('Enter a score'); return; }
    setBusy(`review-${a.id}`);
    try {
      await reviewAssessment(c.uk, a.id, {
        score: Number(f.score),
        passed: !!f.passed,
        remarks: f.remarks || '',
      });
      showSuccess('Assessment reviewed');
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to review assessment');
    } finally {
      setBusy('');
    }
  };

  const openOfferForm = (c) => {
    // Default the role from the candidate / its requisition so HR rarely retypes it.
    setOfferForm({ ...EMPTY_OFFER, designation: c.designation || '', department: c.department || '' });
    setShowOfferForm(true);
  };

  const submitOffer = async (c) => {
    if (!offerForm.designation.trim()) { showError('Designation is required'); return; }
    if (!(Number(offerForm.annual_ctc) > 0)) { showError('Annual CTC must be greater than zero'); return; }
    setBusy('offer');
    try {
      const res = await createOffer(c.uk, {
        ...offerForm,
        annual_ctc: Number(offerForm.annual_ctc),
        probation_months: offerForm.probation_months === '' ? null : Number(offerForm.probation_months),
      });
      // The offer link is a candidate access code — surfaced once, exactly like assessments.
      setIssuedLink({
        title: `Offer link for ${c.fullName}`,
        url: `${window.location.origin}/offer/${res.data.accessCode}`,
      });
      setCopied(false);
      setShowOfferForm(false);
      setOfferForm(EMPTY_OFFER);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to create offer');
    } finally {
      setBusy('');
    }
  };

  const revokeOffer = async (c, offerId) => {
    setBusy(`withdraw-${offerId}`);
    try {
      await withdrawOffer(c.uk, offerId);
      showSuccess('Offer withdrawn');
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to withdraw offer');
    } finally {
      setBusy('');
    }
  };

  const sendOnboardingInvite = async (c) => {
    setBusy('onb-invite');
    try {
      const res = await inviteOnboarding(c.uk, onbForm);
      setIssuedLink({
        title: `Onboarding link for ${c.fullName}`,
        url: `${window.location.origin}/onboarding/${res.data.accessCode}`,
      });
      setCopied(false);
      setShowOnbForm(false);
      setOnbForm({ message: '', due_on: '' });
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to invite onboarding');
    } finally {
      setBusy('');
    }
  };

  const submitVerify = async (c) => {
    setBusy('verify');
    try {
      await verifyOnboarding(c.uk, { remarks: verifyRemarks });
      showSuccess('Onboarding verified');
      setShowVerify(false);
      setVerifyRemarks('');
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to verify onboarding');
    } finally {
      setBusy('');
    }
  };

  const submitConvert = async (c) => {
    setBusy('convert');
    try {
      const res = await convertCandidate(c.uk, {
        user_id: convertForm.user_id.trim() || undefined,
        date_of_joining: convertForm.date_of_joining || undefined,
      });
      showSuccess(`Employee ${res.data.employeeCode} created`);
      setShowConvert(false);
      setConvertForm({ user_id: '', date_of_joining: '' });
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to convert candidate');
    } finally {
      setBusy('');
    }
  };

  const addPosting = async () => {
    if (!postingForm.request_no || !postingForm.platform.trim()) {
      showError('Choose a requisition and a platform');
      return;
    }
    setBusy('posting');
    try {
      await createPosting(postingForm);
      showSuccess('Posting created');
      setPostingForm({ request_no: '', platform: '', expires_on: '', notes: '' });
      setShowPostingForm(false);
      loadPostings();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to create posting');
    } finally {
      setBusy('');
    }
  };

  const copyLink = async (url) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      showError('Could not copy — select the link and copy it manually.');
    }
  };

  return (
    <div className="p-6 sm:p-8 flex flex-col gap-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
            <Users size={20} />
          </span>
          <div>
            <h1 className="text-xl sm:text-2xl font-black tracking-tight text-[var(--text-main)] leading-tight">
              Candidates
            </h1>
            <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
              Applications, screening, assessments and interviews
            </p>
          </div>
        </div>
        {canCreate && tab === 'pipeline' && (
          <button onClick={() => setShowAdd(true)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[12px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] transition-all">
            <UserPlus size={15} /> Add candidate
          </button>
        )}
        {canCreate && tab === 'postings' && !showPostingForm && (
          <button onClick={() => setShowPostingForm(true)}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[12px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] transition-all">
            <Plus size={15} /> New posting
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {[
          { key: 'pipeline', label: 'Pipeline', icon: ClipboardList },
          { key: 'postings', label: 'Job postings', icon: Megaphone },
        ].map((t) => (
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

      {error && (
        <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
          style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* ── Pipeline ── */}
      {tab === 'pipeline' && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatTile icon={Users} label="Total" value={data?.total ?? 0} loading={loading} />
            <StatTile icon={ClipboardList} label="Applied" value={counts.Applied ?? 0} loading={loading} />
            <StatTile icon={CalendarPlus} label="Interview" value={counts.Interview ?? 0} loading={loading} />
            <StatTile icon={Check} label="Hired" value={counts.Hired ?? 0} loading={loading} />
          </div>

          <div className="flex flex-wrap items-center gap-2.5 p-3 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
            <div className="relative flex-1 min-w-[220px]">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none" />
              <input value={search} onChange={(e) => setSearch(e.target.value)}
                placeholder="Search name, email, code…" className={`${inputCls} pl-9`} />
            </div>
            <select value={stageFilter} onChange={(e) => setStageFilter(e.target.value)}
              className={`${inputCls} w-auto min-w-[150px] cursor-pointer`}>
              <option value="">All stages</option>
              {stages.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            {(search || stageFilter) && (
              <button onClick={() => { setSearch(''); setStageFilter(''); }}
                className="flex items-center gap-1.5 px-3 py-2.5 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                <X size={13} /> Clear
              </button>
            )}
          </div>

          {/* Bulk actions appear only with a selection. */}
          {canUpdate && selected.size > 0 && (
            <div className="flex flex-wrap items-center gap-2 px-4 py-3 rounded-xl bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)]">
              <span className="text-[11px] font-black uppercase tracking-widest text-[var(--accent-indigo)]">
                {selected.size} selected
              </span>
              {['Shortlisted', 'Assessment', 'Interview', 'Offer', 'Hired', 'Rejected'].map((s) => (
                <button key={s} onClick={() => move(s)} disabled={!!busy}
                  className="px-3 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[10px] font-black uppercase tracking-widest disabled:opacity-50 transition-colors"
                  style={{ color: STAGE_TONE[s] }}>
                  → {s}
                </button>
              ))}
            </div>
          )}

          <div className="rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full" style={{ minWidth: 900 }}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    <th className="w-10 px-4 py-3"></th>
                    {['Candidate', 'Role', 'Experience', 'Source', 'Stage', ''].map((h, i) => (
                      <th key={i} className="text-left px-4 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loading && (
                    <tr><td colSpan={7} className="px-4 py-12 text-center">
                      <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
                        <Loader2 size={16} className="animate-spin" /> Loading…
                      </span>
                    </td></tr>
                  )}
                  {!loading && candidates.length === 0 && (
                    <tr><td colSpan={7} className="px-4 py-12 text-center">
                      <p className="text-[13px] font-bold text-[var(--text-main)]">No candidates.</p>
                      <p className="text-[12px] font-medium text-[var(--text-muted)] mt-1">
                        Share a posting link, or add someone directly.
                      </p>
                    </td></tr>
                  )}
                  {!loading && candidates.map((c) => (
                    <tr key={c.uk}
                      className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                      <td className="px-4 py-3">
                        {canUpdate && (
                          <input type="checkbox" checked={selected.has(c.id)}
                            onChange={() => toggle(c.id)}
                            className="w-3.5 h-3.5 accent-[var(--accent-indigo)]" />
                        )}
                      </td>
                      <td className="px-4 py-3 cursor-pointer" onClick={() => setDetail(c)}>
                        <div className="text-[12.5px] font-black text-[var(--text-main)]">{c.fullName}</div>
                        <div className="text-[11px] font-medium text-[var(--text-muted)]">{c.email}</div>
                      </td>
                      <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]">
                        {c.designation || '—'}
                      </td>
                      <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]">
                        {c.experienceYears || '—'}
                      </td>
                      <td className="px-4 py-3 text-[12px] font-medium text-[var(--text-muted)]">
                        {c.platform || c.source || '—'}
                      </td>
                      <td className="px-4 py-3"><StageChip stage={c.stage} /></td>
                      <td className="px-4 py-3 text-right">
                        <button onClick={() => setDetail(c)}
                          className="inline-flex items-center gap-1 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
                          Open <ChevronRight size={12} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ── Postings ── */}
      {tab === 'postings' && (
        <>
          {showPostingForm && (
            <div className="p-5 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-col gap-3.5">
              <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)]">
                New posting
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
                <Field label="Requisition" required>
                  <select className={`${inputCls} cursor-pointer`} value={postingForm.request_no}
                    onChange={(e) => setPostingForm({ ...postingForm, request_no: e.target.value })}>
                    <option value="">Choose an approved requisition</option>
                    {approvedReqs.map((r) => (
                      <option key={r.requestNo} value={r.requestNo}>
                        {r.designation} · {r.requestNo}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Platform" required>
                  <input className={inputCls} value={postingForm.platform}
                    placeholder="LinkedIn, Naukri, Referral…"
                    onChange={(e) => setPostingForm({ ...postingForm, platform: e.target.value })} />
                </Field>
                <Field label="Link expires on">
                  <input type="date" className={inputCls} value={postingForm.expires_on}
                    onChange={(e) => setPostingForm({ ...postingForm, expires_on: e.target.value })} />
                </Field>
              </div>
              {approvedReqs.length === 0 && (
                <p className="text-[11.5px] font-bold" style={{ color: 'var(--accent-orange)' }}>
                  No approved requisitions yet — a role must clear MD approval before it can be posted.
                </p>
              )}
              <div className="flex items-center justify-end gap-2.5">
                <button onClick={() => setShowPostingForm(false)}
                  className="px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                  Cancel
                </button>
                <button onClick={addPosting} disabled={!!busy}
                  className="flex items-center gap-2 px-5 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
                  {busy === 'posting' && <Loader2 size={13} className="animate-spin" />} Create
                </button>
              </div>
            </div>
          )}

          <div className="grid gap-3 grid-cols-1 lg:grid-cols-2">
            {postings.length === 0 && (
              <div className="col-span-full p-8 rounded-2xl bg-[var(--bg-card)] border border-dashed border-[var(--border)] text-center">
                <Megaphone size={24} className="mx-auto text-[var(--text-muted)] opacity-50 mb-2" />
                <p className="text-[13px] font-bold text-[var(--text-main)]">No postings yet.</p>
              </div>
            )}
            {postings.map((p) => {
              const url = `${window.location.origin}/apply/${p.publicCode}`;
              return (
                <div key={p.id} className="p-4 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-col gap-2.5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[13px] font-black text-[var(--text-main)] truncate">
                        {p.designation}
                      </div>
                      <div className="text-[11.5px] font-medium text-[var(--text-muted)]">
                        {p.platform} · {p.department}
                      </div>
                    </div>
                    <span className="px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest border"
                      style={{
                        color: p.status === 'Open' ? 'var(--status-active-text)' : 'var(--text-muted)',
                        borderColor: 'currentColor',
                      }}>
                      {p.status}
                    </span>
                  </div>

                  <div className="flex items-center gap-2 p-2 rounded-lg bg-[var(--input-bg)] border border-[var(--border)]">
                    <Link2 size={13} className="text-[var(--text-muted)] shrink-0" />
                    <span className="text-[11px] font-medium text-[var(--text-muted)] truncate flex-1">{url}</span>
                    <button onClick={() => copyLink(url)}
                      className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-colors"
                      aria-label="Copy link">
                      <Copy size={13} />
                    </button>
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-bold text-[var(--text-muted)]">
                      {p.applications} application(s)
                      {p.expiresOn ? ` · closes ${fmtDate(p.expiresOn)}` : ''}
                    </span>
                    {canUpdate && (
                      <div className="flex gap-1.5">
                        {['Open', 'Paused', 'Closed'].filter((s) => s !== p.status).map((s) => (
                          <button key={s}
                            onClick={() => updatePosting(p.id, { status: s }).then(loadPostings)}
                            className="px-2.5 py-1 rounded-lg border border-[var(--border)] text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors">
                            {s}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Assessment link — shown once, right after creation. */}
      {issuedLink && (
        <div className="fixed inset-0 z-[360] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setIssuedLink(null)} />
          <div className="relative w-full max-w-md rounded-[24px] bg-[var(--bg-card)] border border-[var(--border)] shadow-2xl p-6 flex flex-col gap-3">
            <h2 className="text-[15px] font-black tracking-tight text-[var(--text-main)]">
              {issuedLink.title}
            </h2>
            <p className="text-[12px] font-medium text-[var(--text-muted)]">
              Copy this now and send it to the candidate. For their privacy it is shown only
              once and cannot be retrieved later.
            </p>
            <div className="flex items-center gap-2 p-2.5 rounded-lg bg-[var(--input-bg)] border border-[var(--border)]">
              <span className="text-[11px] font-medium text-[var(--text-main)] truncate flex-1">
                {issuedLink.url}
              </span>
              <button onClick={() => copyLink(issuedLink.url)}
                className="p-1.5 rounded text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-colors">
                {copied ? <Check size={14} style={{ color: 'var(--accent-green)' }} /> : <Copy size={14} />}
              </button>
            </div>
            <button onClick={() => setIssuedLink(null)}
              className="self-end px-5 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest">
              Done
            </button>
          </div>
        </div>
      )}

      {/* Add candidate */}
      {showAdd && (
        <div className="fixed inset-0 z-[350] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setShowAdd(false)} />
          <div className="relative w-full max-w-2xl rounded-[24px] bg-[var(--bg-card)] border border-[var(--border)] shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)] bg-[var(--table-header-bg)]">
              <h2 className="text-[15px] font-black tracking-tight text-[var(--text-main)]">Add candidate</h2>
              <button onClick={() => setShowAdd(false)}
                className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--table-hover)] transition-colors">
                <X size={19} />
              </button>
            </div>
            <div className="px-6 py-5 grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              <Field label="Full name" required>
                <input className={inputCls} value={form.full_name} autoFocus
                  onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
              </Field>
              <Field label="Email" required>
                <input type="email" className={inputCls} value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </Field>
              <Field label="Phone">
                <input className={inputCls} value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })} />
              </Field>
              <Field label="Current company">
                <input className={inputCls} value={form.current_company}
                  onChange={(e) => setForm({ ...form, current_company: e.target.value })} />
              </Field>
              <Field label="Experience">
                <input className={inputCls} placeholder="e.g. 3 years" value={form.experience_years}
                  onChange={(e) => setForm({ ...form, experience_years: e.target.value })} />
              </Field>
              <Field label="Expected CTC">
                <input className={inputCls} value={form.expected_ctc}
                  onChange={(e) => setForm({ ...form, expected_ctc: e.target.value })} />
              </Field>
            </div>
            <div className="flex items-center justify-end gap-2.5 px-6 py-4 border-t border-[var(--border)] bg-[var(--table-header-bg)]">
              <button onClick={() => setShowAdd(false)}
                className="px-5 py-2.5 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                Cancel
              </button>
              <button onClick={addCandidate} disabled={!!busy}
                className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
                {busy === 'add' && <Loader2 size={14} className="animate-spin" />} Add
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Candidate detail */}
      {detail && (
        <div className="fixed inset-0 z-[350] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setDetail(null)} />
          <div className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-[24px] bg-[var(--bg-card)] border border-[var(--border)] shadow-2xl">
            <div className="sticky top-0 flex items-start justify-between px-6 py-4 border-b border-[var(--border)] bg-[var(--table-header-bg)]">
              <div>
                <h2 className="text-[15px] font-black tracking-tight text-[var(--text-main)]">{detail.fullName}</h2>
                <p className="text-[11.5px] font-bold text-[var(--text-muted)]">
                  {detail.uk} · {detail.designation || 'No role'} · {detail.email}
                </p>
              </div>
              <button onClick={() => setDetail(null)}
                className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--table-hover)] transition-colors">
                <X size={19} />
              </button>
            </div>

            <div className="px-6 py-5 flex flex-col gap-4">
              <div className="flex items-center gap-2 flex-wrap">
                <StageChip stage={detail.stage} />
                {detail.platform && (
                  <span className="text-[11px] font-medium text-[var(--text-muted)]">via {detail.platform}</span>
                )}
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {[
                  ['Phone', detail.phone],
                  ['Current company', detail.currentCompany],
                  ['Experience', detail.experienceYears],
                  ['Current CTC', detail.currentCtc],
                  ['Expected CTC', detail.expectedCtc],
                  ['Notice period', detail.noticePeriod],
                ].map(([l, v]) => (
                  <div key={l}>
                    <div className="text-[9.5px] font-black uppercase tracking-widest text-[var(--text-muted)]">{l}</div>
                    <div className="text-[12.5px] font-bold text-[var(--text-main)]">{v || '—'}</div>
                  </div>
                ))}
              </div>

              {canUpdate && detail.stage !== 'Rejected' && detail.stage !== 'Hired' && (
                <div className="flex flex-col gap-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <button onClick={() => issueAssessment(detail)} disabled={!!busy}
                      className="flex items-center gap-2 px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] disabled:opacity-50 transition-colors">
                      <Send size={13} /> Send assessment
                    </button>
                    <button onClick={() => setScheduling(detail)} disabled={!!busy}
                      className="flex items-center gap-2 px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] disabled:opacity-50 transition-colors">
                      <CalendarPlus size={13} /> Schedule interview
                    </button>
                  </div>

                  {scheduling?.uk === detail.uk && (
                    <div className="p-3.5 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] flex flex-col gap-3">
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <Field label="Round">
                          <input className={inputCls} value={interviewForm.round_name}
                            onChange={(e) => setInterviewForm({ ...interviewForm, round_name: e.target.value })} />
                        </Field>
                        <Field label="When" required>
                          <input type="datetime-local" className={inputCls} value={interviewForm.scheduled_at}
                            onChange={(e) => setInterviewForm({ ...interviewForm, scheduled_at: e.target.value })} />
                        </Field>
                        <Field label="Mode">
                          <select className={`${inputCls} cursor-pointer`} value={interviewForm.mode}
                            onChange={(e) => setInterviewForm({ ...interviewForm, mode: e.target.value })}>
                            {['In person', 'Video', 'Phone'].map((m) => <option key={m} value={m}>{m}</option>)}
                          </select>
                        </Field>
                      </div>
                      <div className="flex items-center justify-end gap-2">
                        <button onClick={() => setScheduling(null)}
                          className="px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                          Cancel
                        </button>
                        <button onClick={() => addInterview(detail)} disabled={!!busy}
                          className="flex items-center gap-2 px-5 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
                          {busy === 'interview' && <Loader2 size={13} className="animate-spin" />} Schedule
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {detail.assessments?.length > 0 && (
                <div>
                  <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-2">
                    Assessments
                  </h3>
                  {detail.assessments.map((a) => {
                    const rf = reviewForm[a.id] || {};
                    return (
                      <div key={a.id} className="p-3 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] mb-2">
                        <div className="flex items-center justify-between">
                          <span className="text-[12px] font-black text-[var(--text-main)]">{a.title}</span>
                          <span className="text-[10px] font-black uppercase tracking-widest"
                            style={{ color: a.status === 'Reviewed' ? 'var(--accent-green)' : 'var(--text-muted)' }}>
                            {a.status}
                          </span>
                        </div>
                        {a.submittedAt && (
                          <p className="text-[11px] font-medium text-[var(--text-muted)] mt-1">
                            Submitted {fmtDateTime(a.submittedAt)}
                          </p>
                        )}

                        {/* The candidate's submitted answers, paired with their questions. */}
                        {a.answers?.length > 0 && (
                          <div className="mt-2.5 flex flex-col gap-2">
                            {(a.questions?.length ? a.questions : a.answers).map((q, idx) => (
                              <div key={idx} className="rounded-lg bg-[var(--bg-card)] border border-[var(--border)] px-3 py-2">
                                <div className="text-[10.5px] font-black text-[var(--text-muted)]">
                                  {a.questions?.length ? `Q${idx + 1}. ${q}` : `Answer ${idx + 1}`}
                                </div>
                                <div className="text-[12px] font-semibold text-[var(--text-main)] mt-0.5 whitespace-pre-wrap">
                                  {a.answers[idx] || '—'}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Once reviewed, the outcome is read-only. */}
                        {a.status === 'Reviewed' && (
                          <p className="text-[11px] font-bold mt-2"
                            style={{ color: a.passed ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                            Score {a.score ?? '—'} · {a.passed ? 'Passed' : 'Not passed'}
                            {a.remarks ? ` — ${a.remarks}` : ''}
                          </p>
                        )}

                        {/* A submitted assessment is scored inline by HR. */}
                        {canUpdate && a.status === 'Submitted' && (
                          <div className="mt-2.5 pt-2.5 border-t border-[var(--border)] flex flex-col gap-2.5">
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                              <Field label="Score">
                                <input type="number" className={inputCls} value={rf.score ?? ''}
                                  onChange={(e) => setReviewForm({ ...reviewForm, [a.id]: { ...rf, score: e.target.value } })} />
                              </Field>
                              <label className="flex items-end gap-2 pb-2.5">
                                <input type="checkbox" checked={!!rf.passed}
                                  onChange={(e) => setReviewForm({ ...reviewForm, [a.id]: { ...rf, passed: e.target.checked } })}
                                  className="w-4 h-4 accent-[var(--accent-green)]" />
                                <span className="text-[12px] font-bold text-[var(--text-main)]">Passed</span>
                              </label>
                            </div>
                            <Field label="Remarks">
                              <input className={inputCls} value={rf.remarks || ''}
                                onChange={(e) => setReviewForm({ ...reviewForm, [a.id]: { ...rf, remarks: e.target.value } })} />
                            </Field>
                            <div className="flex justify-end">
                              <button onClick={() => submitReview(detail, a)} disabled={!!busy}
                                className="flex items-center gap-2 px-5 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
                                {busy === `review-${a.id}` && <Loader2 size={13} className="animate-spin" />} Save review
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {detail.interviews?.length > 0 && (
                <div>
                  <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-2">
                    Interviews
                  </h3>
                  {detail.interviews.map((i) => (
                    <div key={i.id} className="p-3 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] mb-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[12px] font-black text-[var(--text-main)]">{i.roundName}</span>
                        <span className="text-[10px] font-black uppercase tracking-widest"
                          style={{ color: i.recommendation === 'Proceed' ? 'var(--accent-green)' : 'var(--text-muted)' }}>
                          {i.recommendation || i.status}
                        </span>
                      </div>
                      <p className="text-[11px] font-medium text-[var(--text-muted)] mt-1">
                        {fmtDateTime(i.scheduledAt)} · {i.mode}
                        {i.interviewerNames?.length ? ` · ${i.interviewerNames.join(', ')}` : ''}
                      </p>
                      {/* A scheduled round can be scored inline — the whole point of a scorecard
                          is that it is filled in right after the conversation. */}
                      {canUpdate && i.status === 'Scheduled' && (
                        <div className="flex items-center gap-1.5 mt-2.5">
                          {['Proceed', 'Hold', 'Reject'].map((rec) => (
                            <button key={rec} onClick={() => scoreInterview(detail, i.id, rec)}
                              disabled={!!busy}
                              className="px-3 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[9px] font-black uppercase tracking-widest disabled:opacity-50 transition-colors"
                              style={{
                                color: rec === 'Proceed' ? 'var(--accent-green)'
                                  : rec === 'Reject' ? 'var(--accent-red)' : 'var(--text-muted)',
                              }}>
                              {rec}
                            </button>
                          ))}
                        </div>
                      )}
                      {i.remarks && (
                        <p className="text-[11px] font-medium text-[var(--text-muted)] mt-1.5">{i.remarks}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* ── Offer (Phase 7) ── */}
              <div>
                <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-2">
                  Offer
                </h3>

                {detailOffers.length === 0 && !showOfferForm && (
                  <p className="text-[11.5px] font-medium text-[var(--text-muted)] mb-2">No offer yet.</p>
                )}

                {detailOffers.map((o) => (
                  <div key={o.id} className="p-3 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] mb-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[12px] font-black text-[var(--text-main)]">
                        {o.designation || '—'}{o.department ? ` · ${o.department}` : ''}
                      </span>
                      <span className="text-[10px] font-black uppercase tracking-widest"
                        style={{ color: OFFER_TONE[o.status] || 'var(--text-muted)' }}>
                        {o.status}
                      </span>
                    </div>
                    <p className="text-[11px] font-medium text-[var(--text-muted)] mt-1">
                      {o.annualCtc ? `CTC ${o.annualCtc.toLocaleString()}` : 'CTC —'}
                      {o.joiningDate ? ` · joins ${fmtDate(o.joiningDate)}` : ''}
                      {o.location ? ` · ${o.location}` : ''}
                      {o.validTill ? ` · valid till ${fmtDate(o.validTill)}` : ''}
                    </p>
                    {o.candidateNote && (
                      <p className="text-[11px] font-medium text-[var(--text-muted)] mt-1">“{o.candidateNote}”</p>
                    )}
                    {canUpdate && !OFFER_FINAL.includes(o.status) && (
                      <button onClick={() => revokeOffer(detail, o.id)} disabled={!!busy}
                        className="inline-flex items-center gap-1.5 mt-2 px-3 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[9px] font-black uppercase tracking-widest disabled:opacity-50 transition-colors"
                        style={{ color: 'var(--accent-red)' }}>
                        {busy === `withdraw-${o.id}` ? <Loader2 size={11} className="animate-spin" /> : <Ban size={11} />} Withdraw
                      </button>
                    )}
                  </div>
                ))}

                {canUpdate && !pendingOffer && !acceptedOffer && detail.stage !== 'Rejected' && (
                  showOfferForm ? (
                    <div className="p-3.5 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] flex flex-col gap-3">
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <Field label="Designation" required>
                          <input className={inputCls} value={offerForm.designation}
                            onChange={(e) => setOfferForm({ ...offerForm, designation: e.target.value })} />
                        </Field>
                        <Field label="Department">
                          <input className={inputCls} value={offerForm.department}
                            onChange={(e) => setOfferForm({ ...offerForm, department: e.target.value })} />
                        </Field>
                        <Field label="Annual CTC" required>
                          <input type="number" className={inputCls} value={offerForm.annual_ctc}
                            onChange={(e) => setOfferForm({ ...offerForm, annual_ctc: e.target.value })} />
                        </Field>
                        <Field label="Joining date">
                          <input type="date" className={inputCls} value={offerForm.joining_date}
                            onChange={(e) => setOfferForm({ ...offerForm, joining_date: e.target.value })} />
                        </Field>
                        <Field label="Location">
                          <input className={inputCls} value={offerForm.location}
                            onChange={(e) => setOfferForm({ ...offerForm, location: e.target.value })} />
                        </Field>
                        <Field label="Employment type">
                          <select className={`${inputCls} cursor-pointer`} value={offerForm.employment_type}
                            onChange={(e) => setOfferForm({ ...offerForm, employment_type: e.target.value })}>
                            {['Full-time', 'Part-time', 'Contract', 'Internship'].map((t) => <option key={t} value={t}>{t}</option>)}
                          </select>
                        </Field>
                        <Field label="Probation (months)">
                          <input type="number" className={inputCls} value={offerForm.probation_months}
                            onChange={(e) => setOfferForm({ ...offerForm, probation_months: e.target.value })} />
                        </Field>
                        <Field label="Valid till">
                          <input type="date" className={inputCls} value={offerForm.valid_till}
                            onChange={(e) => setOfferForm({ ...offerForm, valid_till: e.target.value })} />
                        </Field>
                        <Field label="Notes" className="sm:col-span-2">
                          <input className={inputCls} value={offerForm.notes}
                            onChange={(e) => setOfferForm({ ...offerForm, notes: e.target.value })} />
                        </Field>
                      </div>
                      <div className="flex items-center justify-end gap-2">
                        <button onClick={() => { setShowOfferForm(false); setOfferForm(EMPTY_OFFER); }}
                          className="px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                          Cancel
                        </button>
                        <button onClick={() => submitOffer(detail)} disabled={!!busy}
                          className="flex items-center gap-2 px-5 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
                          {busy === 'offer' && <Loader2 size={13} className="animate-spin" />} Send offer
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button onClick={() => openOfferForm(detail)} disabled={!!busy}
                      className="flex items-center gap-2 px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] disabled:opacity-50 transition-colors">
                      <Award size={13} /> Send offer
                    </button>
                  )
                )}
              </div>

              {/* ── Onboarding (Phase 7) — opens once an offer is accepted ── */}
              {acceptedOffer && (
                <div>
                  <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-2">
                    Onboarding
                  </h3>

                  {!onboarding && (
                    canUpdate ? (
                      showOnbForm ? (
                        <div className="p-3.5 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] flex flex-col gap-3">
                          <Field label="Message to candidate">
                            <input className={inputCls} value={onbForm.message}
                              placeholder="A short note shown on the onboarding form…"
                              onChange={(e) => setOnbForm({ ...onbForm, message: e.target.value })} />
                          </Field>
                          <Field label="Due on">
                            <input type="date" className={inputCls} value={onbForm.due_on}
                              onChange={(e) => setOnbForm({ ...onbForm, due_on: e.target.value })} />
                          </Field>
                          <div className="flex items-center justify-end gap-2">
                            <button onClick={() => { setShowOnbForm(false); setOnbForm({ message: '', due_on: '' }); }}
                              className="px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                              Cancel
                            </button>
                            <button onClick={() => sendOnboardingInvite(detail)} disabled={!!busy}
                              className="flex items-center gap-2 px-5 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
                              {busy === 'onb-invite' && <Loader2 size={13} className="animate-spin" />} Invite
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button onClick={() => setShowOnbForm(true)} disabled={!!busy}
                          className="flex items-center gap-2 px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] disabled:opacity-50 transition-colors">
                          <Mail size={13} /> Invite onboarding
                        </button>
                      )
                    ) : (
                      <p className="text-[11.5px] font-medium text-[var(--text-muted)]">Not started.</p>
                    )
                  )}

                  {onboarding && (
                    <div className="p-3 rounded-xl bg-[var(--input-bg)] border border-[var(--border)]">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[12px] font-black text-[var(--text-main)]">KYC & details</span>
                        <span className="text-[10px] font-black uppercase tracking-widest"
                          style={{ color: ['Verified', 'Converted'].includes(onboarding.status) ? 'var(--accent-green)' : 'var(--text-muted)' }}>
                          {onboarding.status}
                        </span>
                      </div>
                      <p className="text-[11px] font-medium text-[var(--text-muted)] mt-1">
                        {onboarding.invitedAt ? `Invited ${fmtDateTime(onboarding.invitedAt)}` : ''}
                        {onboarding.dueOn ? ` · due ${fmtDate(onboarding.dueOn)}` : ''}
                        {onboarding.submittedAt ? ` · submitted ${fmtDateTime(onboarding.submittedAt)}` : ''}
                      </p>

                      {onboarding.status !== 'Invited' && (
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 mt-2.5">
                          {[
                            ['Personal email', onboarding.personalEmail],
                            ['Phone', onboarding.phone],
                            ['Date of birth', onboarding.dateOfBirth && fmtDate(onboarding.dateOfBirth)],
                            ['Gender', onboarding.gender],
                            ['Emergency', onboarding.emergencyName],
                            ['Emergency phone', onboarding.emergencyPhone],
                          ].filter(([, v]) => v).map(([l, v]) => (
                            <div key={l}>
                              <div className="text-[9.5px] font-black uppercase tracking-widest text-[var(--text-muted)]">{l}</div>
                              <div className="text-[12px] font-bold text-[var(--text-main)]">{v}</div>
                            </div>
                          ))}
                        </div>
                      )}

                      {onboarding.verifiedBy && (
                        <p className="text-[11px] font-medium text-[var(--text-muted)] mt-2">
                          Verified by {onboarding.verifiedBy}{onboarding.remarks ? ` — ${onboarding.remarks}` : ''}
                        </p>
                      )}

                      {/* Verify a submitted KYC. */}
                      {canUpdate && onboarding.status === 'Submitted' && (
                        showVerify ? (
                          <div className="mt-2.5 pt-2.5 border-t border-[var(--border)] flex flex-col gap-2.5">
                            <Field label="Remarks">
                              <input className={inputCls} value={verifyRemarks}
                                onChange={(e) => setVerifyRemarks(e.target.value)} />
                            </Field>
                            <div className="flex items-center justify-end gap-2">
                              <button onClick={() => { setShowVerify(false); setVerifyRemarks(''); }}
                                className="px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                                Cancel
                              </button>
                              <button onClick={() => submitVerify(detail)} disabled={!!busy}
                                className="flex items-center gap-2 px-5 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
                                {busy === 'verify' && <Loader2 size={13} className="animate-spin" />} Verify
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button onClick={() => setShowVerify(true)} disabled={!!busy}
                            className="inline-flex items-center gap-2 mt-2.5 px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-green)] hover:border-[var(--accent-green)] disabled:opacity-50 transition-colors">
                            <ShieldCheck size={13} /> Verify
                          </button>
                        )
                      )}

                      {/* Convert a verified onboarding into an employee record. */}
                      {canConvert && onboarding.status === 'Verified' && (
                        showConvert ? (
                          <div className="mt-2.5 pt-2.5 border-t border-[var(--border)] flex flex-col gap-2.5">
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                              <Field label="Staff login (optional)">
                                <input className={inputCls} value={convertForm.user_id}
                                  placeholder="Staff account id to link"
                                  onChange={(e) => setConvertForm({ ...convertForm, user_id: e.target.value })} />
                              </Field>
                              <Field label="Date of joining (optional)">
                                <input type="date" className={inputCls} value={convertForm.date_of_joining}
                                  onChange={(e) => setConvertForm({ ...convertForm, date_of_joining: e.target.value })} />
                              </Field>
                            </div>
                            <div className="flex items-center justify-end gap-2">
                              <button onClick={() => { setShowConvert(false); setConvertForm({ user_id: '', date_of_joining: '' }); }}
                                className="px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                                Cancel
                              </button>
                              <button onClick={() => submitConvert(detail)} disabled={!!busy}
                                className="flex items-center gap-2 px-5 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
                                {busy === 'convert' && <Loader2 size={13} className="animate-spin" />} Create employee
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button onClick={() => setShowConvert(true)} disabled={!!busy}
                            className="inline-flex items-center gap-2 mt-2.5 px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-green)] hover:border-[var(--accent-green)] disabled:opacity-50 transition-colors">
                            <UserCheck size={13} /> Convert to employee
                          </button>
                        )
                      )}

                      {/* Converted — the handoff is done; jump to the new employee. */}
                      {onboarding.status === 'Converted' && onboarding.employeeCode && (
                        <div className="mt-2.5 pt-2.5 border-t border-[var(--border)] flex items-center justify-between gap-2">
                          <span className="text-[11.5px] font-bold" style={{ color: 'var(--accent-green)' }}>
                            Employee {onboarding.employeeCode}
                          </span>
                          <button onClick={() => navigate(`/hrms/employees/${onboarding.employeeCode}`)}
                            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest">
                            <UserCheck size={13} /> View employee
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {detail.journey?.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <History size={13} className="text-[var(--text-muted)]" />
                    <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                      Journey
                    </span>
                  </div>
                  <ol className="flex flex-col gap-2">
                    {detail.journey.map((j, i) => (
                      <li key={i} className="flex gap-3">
                        <span className="w-1.5 h-1.5 rounded-full mt-2 shrink-0"
                          style={{ backgroundColor: STAGE_TONE[j.to] || 'var(--text-muted)' }} />
                        <div>
                          <div className="text-[12px] font-bold text-[var(--text-main)]">
                            {j.from} → {j.to}
                          </div>
                          <div className="text-[11px] font-medium text-[var(--text-muted)]">
                            {j.actorName} · {fmtDateTime(j.at)}{j.remarks ? ` — ${j.remarks}` : ''}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Candidates;
