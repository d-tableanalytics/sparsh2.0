import React, { useCallback, useEffect, useState } from 'react';
import { Inbox, Plus, Check, X, ArrowRightLeft, Eye } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getJobRequests, createJobRequest, actOnJobRequest, convertJobRequest,
  withdrawJobRequest, getClients, getDepartments, getDesignations, getLinkableUsers,
} from '../../../services/hrmsApi';
import { FIELD, LABEL, TEXTAREA, day } from '../internal/internalKit';
import { Btn, Chip, Facts, Modal } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ client track — job requests.
 *
 * ONE screen, two audiences. Sparsh sees every client's requests as an inbox to work; a
 * client sees only their own, as a list of what they have asked for.
 *
 * They share a screen because they are looking at the same records and the difference is
 * entirely in what the SERVER returns and which capabilities the viewer holds. Building two
 * screens would mean two places to fix the same bug, and the client half would be the one
 * nobody remembered — which is exactly the half where a mistake leaks another client's data.
 *
 * The distinction the screen keeps visible: a request is what a client ASKED FOR, not work
 * Sparsh has agreed to. Converting it into a requisition is the moment that changes, and it
 * is a deliberate act with its own button.
 */

const TONE = {
  Submitted: 'info',
  'Under Review': 'warn',
  Accepted: 'good',
  Declined: 'bad',
  Withdrawn: 'neutral',
};

const JobRequestBoard = () => {
  const { scope, companyId, can } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [raising, setRaising] = useState(false);
  const [converting, setConverting] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [declining, setDeclining] = useState(null);
  const [busy, setBusy] = useState(false);

  const canReview = can(CAP.JOB_REQUEST_REVIEW);
  const canWrite = can(CAP.JOB_REQUEST_WRITE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getJobRequests(scope);
      setRows(data?.job_requests || []);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load job requests.');
    } finally {
      setLoading(false);
    }
  }, [companyId, scope]);

  useEffect(() => { load(); }, [load]);

  // Declining needs a reason the client will read, so it gets a real form rather than a
  // browser prompt(): a prompt cannot be styled, cannot show the job it refers to, cannot
  // be cancelled cleanly on a phone, and gives no room to say what a good reason looks like.
  const act = async (row, action, remarks = null) => {
    setBusy(true);
    try {
      await actOnJobRequest(row.jbr_no, { action, remarks }, scope);
      showSuccess(`${row.jbr_no} ${action === 'review' ? 'picked up' : `${action}ed`}`);
      await load();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not update that request.');
    } finally {
      setBusy(false);
    }
  };

  const withdraw = async (row) => {
    setBusy(true);
    try {
      await withdrawJobRequest(row.jbr_no, { remarks: '' }, scope);
      showSuccess(`${row.jbr_no} withdrawn`);
      await load();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not withdraw that request.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <HrmsPageHeader
        title={canReview ? 'Client job requests' : 'My job requests'}
        subtitle={canReview
          ? 'What clients have asked for, and what we have agreed to work'
          : 'What you have asked Sparsh to hire for'}
        icon={Inbox}
        actions={canWrite ? (
          <Btn tone="primary" onClick={() => setRaising(true)}>
            <Plus size={14} /> Raise a request
          </Btn>
        ) : null}
      />
      <HrmsScopeBar />

      {loading && <HrmsLoading />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && !rows.length && (
        <HrmsEmpty
          icon={Inbox}
          title="No job requests"
          hint={canReview
            ? 'When a client raises a hiring request it will arrive here.'
            : 'Raise a request and the Sparsh team will pick it up.'}
        />
      )}

      <div className="grid gap-3">
        {rows.map((row) => (
          <div
            key={row.jbr_no}
            className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4
                       space-y-3"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <p className="text-[14px] font-bold text-[var(--text-main)]">
                    {row.job_title}
                  </p>
                  <Chip tone={TONE[row.status] || 'neutral'}>{row.status}</Chip>
                  {row.request_no && (
                    <Chip tone="good" title="Converted into a requisition">
                      {row.request_no}
                    </Chip>
                  )}
                </div>
                <p className="text-[11.5px] text-[var(--text-muted)] font-mono mt-0.5">
                  {row.jbr_no}
                  {canReview && row.client_name ? ` · ${row.client_name}` : ''}
                  {` · raised ${day(row.created_at)}`}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Btn onClick={() => setViewing(row)}><Eye size={13} /> Details</Btn>
                {canReview && row.status === 'Submitted' && (
                  <Btn onClick={() => act(row, 'review')} disabled={busy}>
                    Pick up
                  </Btn>
                )}
                {canReview && row.status === 'Under Review' && (
                  <>
                    <Btn tone="primary" onClick={() => act(row, 'accept')} disabled={busy}>
                      <Check size={13} /> Accept
                    </Btn>
                    <Btn tone="danger" onClick={() => setDeclining(row)} disabled={busy}>
                      <X size={13} /> Decline
                    </Btn>
                  </>
                )}
                {canReview && row.status === 'Accepted' && !row.request_no && (
                  <Btn tone="primary" onClick={() => setConverting(row)} disabled={busy}>
                    <ArrowRightLeft size={13} /> Convert to requisition
                  </Btn>
                )}
                {!canReview && ['Submitted', 'Under Review'].includes(row.status) && (
                  <Btn tone="danger" onClick={() => withdraw(row)} disabled={busy}>
                    Withdraw
                  </Btn>
                )}
              </div>
            </div>

            <Facts items={[
              { label: 'Positions', value: row.positions },
              { label: 'Experience', value: row.experience },
              { label: 'Location', value: row.location },
              { label: 'Budget', value: row.budget_min || row.budget_max
                ? `${row.budget_min?.toLocaleString('en-IN') ?? '—'} – ${
                  row.budget_max?.toLocaleString('en-IN') ?? '—'}`
                : null },
              { label: 'Needed by', value: row.target_date },
            ]} />

            {row.decision_remarks && (
              <p className="text-[12px] text-[var(--text-muted)] border-l-2
                            border-[var(--border)] pl-2">
                <span className="font-semibold">Sparsh:</span> {row.decision_remarks}
              </p>
            )}
          </div>
        ))}
      </div>

      {declining && (
        <DeclineModal
          request={declining}
          busy={busy}
          onClose={() => setDeclining(null)}
          onConfirm={async (reason) => {
            await act(declining, 'decline', reason);
            setDeclining(null);
          }}
        />
      )}
      {raising && (
        <RaiseModal
          scope={scope}
          canChooseClient={canReview}
          onClose={() => setRaising(false)}
          onDone={async (m) => { setRaising(false); showSuccess(m); await load(); }}
          onError={showError}
        />
      )}
      {converting && (
        <ConvertModal
          scope={scope}
          request={converting}
          onClose={() => setConverting(null)}
          onDone={async (m) => { setConverting(null); showSuccess(m); await load(); }}
          onError={showError}
        />
      )}
      {viewing && (
        <Modal
          title={viewing.job_title}
          subtitle={`${viewing.jbr_no} · ${viewing.status}`}
          onClose={() => setViewing(null)}
          footer={<Btn onClick={() => setViewing(null)}>Close</Btn>}
        >
          <div className="space-y-3">
            <Facts items={[
              { label: 'Client', value: viewing.client_name },
              { label: 'Positions', value: viewing.positions },
              { label: 'Experience', value: viewing.experience },
              { label: 'Location', value: viewing.location },
              { label: 'Needed by', value: viewing.target_date },
              { label: 'Raised by', value: viewing.raised_by_name },
              { label: 'Reviewed by', value: viewing.reviewed_by_name },
            ]} />
            {viewing.required_skills && (
              <div>
                <p className={LABEL}>Required skills</p>
                <p className="text-[12.5px] whitespace-pre-wrap text-[var(--text-main)]">
                  {viewing.required_skills}
                </p>
              </div>
            )}
            {viewing.job_description && (
              <div>
                <p className={LABEL}>Job description</p>
                <p className="text-[12.5px] whitespace-pre-wrap text-[var(--text-main)]">
                  {viewing.job_description}
                </p>
              </div>
            )}
            {viewing.other_requirements && (
              <div>
                <p className={LABEL}>Other requirements</p>
                <p className="text-[12.5px] whitespace-pre-wrap text-[var(--text-main)]">
                  {viewing.other_requirements}
                </p>
              </div>
            )}
          </div>
        </Modal>
      )}
    </div>
  );
};

/**
 * Decline a job request.
 *
 * The reason is mandatory on the server, and this is where it is collected — with the job
 * title in view, so the person writing it knows which requirement they are turning down,
 * and with the consequence stated, because the client reads what is typed here.
 */
const DeclineModal = ({ request, busy, onClose, onConfirm }) => {
  const [reason, setReason] = useState('');
  return (
    <Modal
      title={`Decline “${request.job_title}”`}
      subtitle={`${request.jbr_no} · ${request.client_name || 'this client'}`}
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="danger" onClick={() => onConfirm(reason.trim())}
               disabled={busy || !reason.trim()}>
            {busy ? 'Declining\u2026' : 'Decline request'}
          </Btn>
        </>
      )}
    >
      <div className="space-y-3">
        <p className="text-[12.5px] text-[var(--text-muted)]">
          The client is told this request was declined, and sees the reason you give. A
          declined request cannot be edited or reopened — they would raise a new one.
        </p>
        <div>
          <label className={LABEL} htmlFor="jr-decline">Reason *</label>
          <textarea id="jr-decline" rows={3} className={TEXTAREA} value={reason} required
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="e.g. Outside our current sourcing capacity for this skill set." />
        </div>
      </div>
    </Modal>
  );
};

const RaiseModal = ({ scope, canChooseClient, onClose, onDone, onError }) => {
  const [clients, setClients] = useState([]);
  const [form, setForm] = useState({
    job_title: '', positions: 1, required_skills: '', experience: '', location: '',
    budget_min: '', budget_max: '', job_description: '', other_requirements: '',
    target_date: '', client_id: '',
  });
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    // Only Sparsh picks a client. A client user's own request takes its client from their
    // engagement server-side, and a value sent from here would be ignored.
    if (canChooseClient) {
      getClients(scope).then(({ data }) => setClients(data?.clients || [])).catch(() => {});
    }
  }, [scope, canChooseClient]);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await createJobRequest({
        ...form,
        positions: Number(form.positions) || 1,
        budget_min: form.budget_min === '' ? null : Number(form.budget_min),
        budget_max: form.budget_max === '' ? null : Number(form.budget_max),
        target_date: form.target_date || null,
        client_id: canChooseClient ? (form.client_id || null) : null,
      }, scope);
      await onDone('Job request raised');
    } catch (err) {
      onError(err?.response?.data?.detail || 'Could not raise that request.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="Raise a job request"
      subtitle="Tell Sparsh what you need. They will review it and start sourcing."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={saving}>
            {saving ? 'Sending…' : 'Send request'}
          </Btn>
        </>
      )}
    >
      <form onSubmit={submit} className="space-y-3">
        {canChooseClient && (
          <div>
            <label className={LABEL} htmlFor="jr-client">Client *</label>
            <select id="jr-client" className={FIELD} value={form.client_id}
                    onChange={set('client_id')} required>
              <option value="">Select a client…</option>
              {clients.map((c) => (
                <option key={c.client_id} value={c.client_id}>{c.name}</option>
              ))}
            </select>
          </div>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="jr-title">Job title *</label>
            <input id="jr-title" className={FIELD} required value={form.job_title}
                   onChange={set('job_title')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="jr-pos">Number of positions *</label>
            <input id="jr-pos" type="number" min="1" className={FIELD} required
                   value={form.positions} onChange={set('positions')} />
          </div>
        </div>
        <div>
          <label className={LABEL} htmlFor="jr-skills">Required skills *</label>
          <textarea id="jr-skills" rows={2} className={TEXTAREA} required
                    value={form.required_skills} onChange={set('required_skills')}
                    placeholder="Comma-separated, or one per line" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="jr-exp">Experience</label>
            <input id="jr-exp" className={FIELD} value={form.experience}
                   onChange={set('experience')} placeholder="e.g. 3–6 years" />
          </div>
          <div>
            <label className={LABEL} htmlFor="jr-loc">Location</label>
            <input id="jr-loc" className={FIELD} value={form.location}
                   onChange={set('location')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="jr-bmin">Budget from</label>
            <input id="jr-bmin" type="number" min="0" className={FIELD}
                   value={form.budget_min} onChange={set('budget_min')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="jr-bmax">Budget to</label>
            <input id="jr-bmax" type="number" min="0" className={FIELD}
                   value={form.budget_max} onChange={set('budget_max')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="jr-date">Needed by</label>
            <input id="jr-date" type="date" className={FIELD} value={form.target_date}
                   onChange={set('target_date')} />
          </div>
        </div>
        <div>
          <label className={LABEL} htmlFor="jr-desc">Job description</label>
          <textarea id="jr-desc" rows={4} className={TEXTAREA} value={form.job_description}
                    onChange={set('job_description')} />
        </div>
        <div>
          <label className={LABEL} htmlFor="jr-other">Other requirements</label>
          <textarea id="jr-other" rows={2} className={TEXTAREA}
                    value={form.other_requirements} onChange={set('other_requirements')} />
        </div>
      </form>
    </Modal>
  );
};

/**
 * Accepted request → requisition.
 *
 * Asks for exactly the three things a client could not supply: which department and
 * designation this maps to in OUR masters, and who runs it. Everything else is carried
 * across from the request server-side, so the two records cannot drift apart at birth.
 */
const ConvertModal = ({ scope, request, onClose, onDone, onError }) => {
  const [departments, setDepartments] = useState([]);
  const [designations, setDesignations] = useState([]);
  const [people, setPeople] = useState([]);
  const [form, setForm] = useState({
    department_id: '', designation_id: '', assignee_id: '',
    required_date: request.target_date || '',
    vacancy: request.positions || 1,
    offering_ctc: request.budget_max || '',
  });
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    getDepartments(scope)
      .then(({ data }) => setDepartments((data?.departments || []).filter((d) => d.active)))
      .catch(() => {});
    getDesignations(scope)
      .then(({ data }) => setDesignations((data?.designations || []).filter((d) => d.active)))
      .catch(() => {});
    getLinkableUsers(scope)
      .then(({ data }) => setPeople(data?.users || data?.employees || [])).catch(() => {});
  }, [scope]);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const { data } = await convertJobRequest(request.jbr_no, {
        ...form,
        vacancy: Number(form.vacancy) || 1,
        offering_ctc: form.offering_ctc === '' ? null : Number(form.offering_ctc),
      }, scope);
      await onDone(`Converted into ${data?.request_no}`);
    } catch (err) {
      onError(err?.response?.data?.detail || 'Could not convert that request.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`Convert ${request.jbr_no}`}
      subtitle="This creates a client-track requisition and starts our own approval chain."
      onClose={onClose}
      footer={(
        <>
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn tone="primary" onClick={submit} disabled={saving}>
            {saving ? 'Converting…' : 'Create requisition'}
          </Btn>
        </>
      )}
    >
      <form onSubmit={submit} className="space-y-3">
        <p className="text-[12px] text-[var(--text-muted)]">
          Title, skills, experience and location carry across from the request. Choose how it
          maps into our structure.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className={LABEL} htmlFor="cv-dept">Department *</label>
            <select id="cv-dept" className={FIELD} required value={form.department_id}
                    onChange={set('department_id')}>
              <option value="">Select…</option>
              {departments.map((d) => (
                <option key={d._id || d.id} value={d._id || d.id}>{d.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={LABEL} htmlFor="cv-desig">Designation *</label>
            <select id="cv-desig" className={FIELD} required value={form.designation_id}
                    onChange={set('designation_id')}>
              <option value="">Select…</option>
              {designations.map((d) => (
                <option key={d._id || d.id} value={d._id || d.id}>{d.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={LABEL} htmlFor="cv-owner">Who will run it *</label>
            <select id="cv-owner" className={FIELD} required value={form.assignee_id}
                    onChange={set('assignee_id')}>
              <option value="">Select…</option>
              {people.map((p) => (
                <option key={p._id || p.user_id} value={p._id || p.user_id}>
                  {p.full_name || p.employee_name || p.email}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={LABEL} htmlFor="cv-date">Required by *</label>
            <input id="cv-date" type="date" className={FIELD} required
                   value={form.required_date} onChange={set('required_date')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="cv-vac">Vacancies</label>
            <input id="cv-vac" type="number" min="1" className={FIELD}
                   value={form.vacancy} onChange={set('vacancy')} />
          </div>
          <div>
            <label className={LABEL} htmlFor="cv-ctc">Offering CTC</label>
            <input id="cv-ctc" type="number" min="0" className={FIELD}
                   value={form.offering_ctc} onChange={set('offering_ctc')} />
          </div>
        </div>
      </form>
    </Modal>
  );
};

export default JobRequestBoard;
