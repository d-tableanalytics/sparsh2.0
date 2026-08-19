import React, { useEffect, useState } from 'react';
import { X, FilePlus2, AlertTriangle } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import {
  createRequisition, updateRequisition, getDepartments, getDesignations, getEmployees,
  getClients, getSanctionedPosition,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ raise / edit a hiring requisition.
 *
 * The requisition and its job description are authored in ONE form because they are
 * approved together — there is no separate JD submission step. The JD section is not
 * optional: a requisition without one cannot be posted, and the server rejects it.
 *
 * Department and designation are pickers over the Phase 2 masters, not free-text boxes.
 * That is the whole point of those masters: the source shipped a department dropdown that
 * disagreed with another dropdown on the same screen.
 */
const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const AREA = 'w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] resize-none';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

const RequisitionFormModal = ({ existing, onClose, onSaved }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const isEdit = !!existing;

  const [departments, setDepartments] = useState([]);
  const [designations, setDesignations] = useState([]);
  const [people, setPeople] = useState([]);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    // ── Which hiring track this vacancy runs on ──
    // Defaults to `client`, so the form behaves exactly as it always has unless somebody
    // deliberately switches it. IMMUTABLE once raised: the server refuses a change, because
    // an approval granted under one track's rules means nothing under the other's.
    requisition_track: existing?.requisition_track || 'client',
    department_id: existing?.department_id || '',
    designation_id: existing?.designation_id || '',
    vacancy: existing?.vacancy ?? 1,
    experience_required: existing?.experience_required || '',
    qualification: existing?.qualification || '',
    essential_skills: existing?.essential_skills || '',
    required_date: existing?.required_date || '',
    assignee_id: existing?.assignee_id || '',
    offering_ctc: existing?.offering_ctc ?? '',
    urgency_level: existing?.urgency_level || 'Medium',
    work_location: existing?.work_location || 'Office',
    gender_preferred: existing?.gender_preferred || 'Any',
    employment_type: existing?.employment_type || 'Full-time',
    notes: existing?.notes || '',
    // ── Phase 11-R, Item 4 ── which client this vacancy is for. Optional: an in-house
    // requisition has no client, and so does every requisition raised before this phase.
    client_id: existing?.client_id || '',
    // ── Phase 11-R, Item 6 ── the two budget figures. Both optional; leaving them empty
    // reproduces the pre-phase behaviour exactly (budget_status reads "Not Set").
    budget_sanctioned_amount: existing?.budget_sanctioned_amount ?? '',
    budget_sanctioned_by: existing?.budget_sanctioned_by || '',
    budget_sanctioned_ref: existing?.budget_sanctioned_ref || '',
    budget_sanctioned_on: existing?.budget_sanctioned_on || '',
    budget_hod_amount: existing?.budget_hod_amount ?? '',
    budget_hod_by: existing?.budget_hod_by || '',
    budget_hod_on: existing?.budget_hod_on || '',
    budget_remarks: existing?.budget_remarks || '',
    // ── Phase 11-R, Item 7 ── replacement vs a genuinely new position.
    requisition_type: existing?.requisition_type || 'New Position',
    replacement_for_user_id: existing?.replacement_for_user_id || '',
    replacement_reason: existing?.replacement_reason || '',
    last_working_day: existing?.last_working_day || '',
  });
  const [clients, setClients] = useState([]);
  // The live sanctioned/actual/available readout for the chosen position.
  const [sanction, setSanction] = useState(null);
  const [jd, setJd] = useState({
    title: existing?.jd?.title || '',
    responsibilities: existing?.jd?.responsibilities || '',
    skills: existing?.jd?.skills || '',
    qualifications: existing?.jd?.qualifications || '',
    experience: existing?.jd?.experience || '',
    ctc: existing?.jd?.ctc || '',
    location: existing?.jd?.location || '',
    benefits: existing?.jd?.benefits || '',
  });

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const setJdField = (k) => (e) => setJd((j) => ({ ...j, [k]: e.target.value }));

  useEffect(() => {
    getDepartments(scope).then(({ data }) => setDepartments((data?.departments || []).filter((d) => d.active))).catch(() => {});
    getDesignations(scope).then(({ data }) => setDesignations((data?.designations || []).filter((d) => d.active))).catch(() => {});
    getEmployees({ ...scope, limit: 500 }).then(({ data }) => setPeople(data?.employees || [])).catch(() => {});
    // Phase 11-R, Item 4. The options are the ERP's Companies — there is no separate client
    // master. Failing quietly is correct: the form works perfectly without a client.
    getClients(scope).then(({ data }) => setClients(data?.clients || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Phase 11-R, Item 7 ── read the live sanction position whenever the department,
  // designation or vacancy count changes, so the raiser is told BEFORE they submit that
  // the request will be escalated. This is a HINT: the server re-evaluates the same figures
  // at raise time and again at each approval step, and its answer is the one that decides.
  useEffect(() => {
    if (!form.department_id || !form.designation_id) {
      setSanction(null);
      return;
    }
    let cancelled = false;
    getSanctionedPosition({
      ...scope,
      department_id: form.department_id,
      designation_id: form.designation_id,
      requested: Number(form.vacancy) || 1,
    })
      .then(({ data }) => { if (!cancelled) setSanction(data); })
      .catch(() => { if (!cancelled) setSanction(null); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.department_id, form.designation_id, form.vacancy]);

  const isReplacement = form.requisition_type === 'Replacement';

  // Derived on the client for display only, from the SAME rule the server applies
  // (models.budget_status). The server's answer is what the chip and the approval gate
  // actually read — this only avoids a round trip while typing.
  const budgetState = (() => {
    const a = form.budget_sanctioned_amount;
    const b = form.budget_hod_amount;
    if (a === '' && b === '') return 'Not Set';
    if (a === '' || b === '') return 'Pending';
    return Number(a) === Number(b) ? 'Matched' : 'Mismatch';
  })();

  const submit = async (e) => {
    e.preventDefault();
    // Mirrors the server rule exactly, so the user is told before a round trip rather than
    // after one. The server still enforces it — this is not the control.
    if (!isEdit && !jd.responsibilities.trim()) {
      showError('Provide a Job Description — enter the key responsibilities.');
      return;
    }
    // Phase 11-R, Item 7. Mirrors the server rule; the server still enforces it.
    if (isReplacement && !form.replacement_for_user_id) {
      showError('Name the employee being replaced, or switch this to a new position.');
      return;
    }
    if (isReplacement && !form.replacement_reason.trim()) {
      showError('Give the reason for the replacement.');
      return;
    }
    setSaving(true);
    try {
      const payload = {
        ...form,
        vacancy: Number(form.vacancy) || 1,
        offering_ctc: form.offering_ctc === '' ? null : Number(form.offering_ctc),
        client_id: form.client_id || null,
        budget_sanctioned_amount:
          form.budget_sanctioned_amount === '' ? null : Number(form.budget_sanctioned_amount),
        budget_hod_amount:
          form.budget_hod_amount === '' ? null : Number(form.budget_hod_amount),
        replacement_for_user_id: form.replacement_for_user_id || null,
      };
      if (isEdit) {
        await updateRequisition(existing.request_no, payload, scope);
        showSuccess(`Requisition ${existing.request_no} updated`);
      } else {
        const { data } = await createRequisition({ ...payload, jd }, scope);
        showSuccess(
          form.requisition_track === 'internal'
            ? `Requisition ${data.request_no} raised — HR verifies it, then Management or `
              + 'Finance approves the budget before sourcing can begin'
            : `Requisition ${data.request_no} raised — routed to HR for review`);
      }
      onSaved();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the requisition.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <FilePlus2 size={17} className="text-[var(--accent-indigo)]" />
            <h2 className="text-[15px] font-bold text-[var(--text-main)]">
              {isEdit ? `Edit ${existing.request_no}` : 'Raise a hiring requisition'}
            </h2>
          </div>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <form onSubmit={submit} className="p-5 space-y-5 overflow-y-auto">
          {/* ── The track ──
              Two radios rather than a dropdown: there are exactly two, and the choice
              changes which approvals the requisition will need, so it deserves to be
              visible rather than folded into a select. Disabled when editing, because the
              server refuses a change and offering one would be a lie. */}
          <fieldset className="rounded-xl border border-[var(--border)] p-3.5">
            <legend className="px-1.5 text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
              Hiring track
            </legend>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {[
                { value: 'client', label: 'For a client',
                  hint: 'The client owns the budget and gives the verdict on CVs.' },
                { value: 'internal', label: 'Sparsh Magic (internal)',
                  hint: 'Budget approved internally. No client, and no CVs shared out.' },
              ].map((option) => (
                <label
                  key={option.value}
                  className={`flex gap-2.5 rounded-lg border p-3 cursor-pointer transition-colors
                    ${form.requisition_track === option.value
                      ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]'
                      : 'border-[var(--border)] hover:bg-[var(--input-bg)]'}
                    ${isEdit ? 'opacity-60 cursor-not-allowed' : ''}`}
                >
                  <input
                    type="radio" name="requisition_track" value={option.value}
                    checked={form.requisition_track === option.value}
                    disabled={isEdit}
                    onChange={() => setForm((f) => ({
                      ...f, requisition_track: option.value,
                      // An internal requisition can never carry a client, so clearing it
                      // here keeps the form from submitting a value the server would refuse.
                      client_id: option.value === 'internal' ? '' : f.client_id,
                    }))}
                    className="mt-0.5 accent-[var(--accent-indigo)]"
                  />
                  <span className="min-w-0">
                    <span className="block text-[13px] font-semibold text-[var(--text-main)]">
                      {option.label}
                    </span>
                    <span className="block text-[11px] text-[var(--text-muted)] mt-0.5">
                      {option.hint}
                    </span>
                  </span>
                </label>
              ))}
            </div>
            {isEdit && (
              <p className="mt-2 text-[11px] text-[var(--text-muted)]">
                The track cannot be changed once a requisition is raised — an approval given
                under one track&rsquo;s rules would not mean the same under the other&rsquo;s.
              </p>
            )}
          </fieldset>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={LABEL} htmlFor="r-dept">Department *</label>
              <select id="r-dept" required value={form.department_id} onChange={set('department_id')} className={FIELD}>
                <option value="">Select…</option>
                {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="r-desig">Designation *</label>
              <select id="r-desig" required value={form.designation_id} onChange={set('designation_id')} className={FIELD}>
                <option value="">Select…</option>
                {designations.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
              {designations.length === 0 && (
                <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                  No designations yet — add one under HRMS ▸ Designations first.
                </p>
              )}
            </div>
            <div>
              <label className={LABEL} htmlFor="r-vac">Vacancies *</label>
              <input id="r-vac" type="number" min="1" required value={form.vacancy} onChange={set('vacancy')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="r-date">Required by *</label>
              <input id="r-date" type="date" required value={form.required_date} onChange={set('required_date')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="r-exp">Experience required *</label>
              <input id="r-exp" required value={form.experience_required} onChange={set('experience_required')}
                placeholder="e.g. 3–5 years" className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="r-qual">Qualification *</label>
              <input id="r-qual" required value={form.qualification} onChange={set('qualification')}
                placeholder="e.g. B.Com" className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="r-assignee">Assignee (recruiter) *</label>
              <select id="r-assignee" required value={form.assignee_id} onChange={set('assignee_id')} className={FIELD}>
                <option value="">Select…</option>
                {people.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="r-ctc">Offered CTC (annual)</label>
              <input id="r-ctc" type="number" min="0" value={form.offering_ctc} onChange={set('offering_ctc')} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="r-urg">Urgency</label>
              <select id="r-urg" value={form.urgency_level} onChange={set('urgency_level')} className={FIELD}>
                {['High', 'Medium', 'Low'].map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="r-loc">Work location</label>
              <select id="r-loc" value={form.work_location} onChange={set('work_location')} className={FIELD}>
                {['Office', 'Factory', 'Remote', 'Hybrid'].map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="r-type">Employment type</label>
              <select id="r-type" value={form.employment_type} onChange={set('employment_type')} className={FIELD}>
                {['Full-time', 'Part-time', 'Contract', 'Intern', 'Consultant'].map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
            <div>
              <label className={LABEL} htmlFor="r-gender">Gender preference</label>
              <select id="r-gender" value={form.gender_preferred} onChange={set('gender_preferred')} className={FIELD}>
                {['Any', 'Male', 'Female'].map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
          </div>

          <div>
            <label className={LABEL} htmlFor="r-skills">Required skills *</label>
            <textarea id="r-skills" rows={2} required value={form.essential_skills}
              onChange={set('essential_skills')} placeholder="Comma-separated" className={AREA} />
          </div>

          {/* ══ Phase 11-R, Item 7 — position & sanction ══ */}
          <div className="pt-4 border-t border-[var(--border)] space-y-3">
            <p className="text-[13px] font-bold text-[var(--text-main)]">Position &amp; sanction</p>

            <div className="flex flex-wrap gap-4">
              {['New Position', 'Replacement'].map((value) => (
                <label key={value} className="flex items-center gap-2 text-[13px] text-[var(--text-main)]">
                  <input
                    type="radio"
                    name="requisition_type"
                    value={value}
                    checked={form.requisition_type === value}
                    onChange={set('requisition_type')}
                  />
                  {value}
                </label>
              ))}
            </div>

            {isReplacement && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className={LABEL} htmlFor="r-repl">Replacing *</label>
                  <select id="r-repl" value={form.replacement_for_user_id}
                    onChange={set('replacement_for_user_id')} className={FIELD}>
                    <option value="">Select…</option>
                    {people.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className={LABEL} htmlFor="r-lwd">Their last working day</label>
                  <input id="r-lwd" type="date" value={form.last_working_day}
                    onChange={set('last_working_day')} className={FIELD} />
                </div>
                <div className="sm:col-span-2">
                  <label className={LABEL} htmlFor="r-reason">Reason for replacement *</label>
                  <input id="r-reason" value={form.replacement_reason}
                    onChange={set('replacement_reason')}
                    placeholder="Resignation, transfer, end of contract…" className={FIELD} />
                </div>
              </div>
            )}

            {sanction && (
              <div className={`rounded-lg border px-3.5 py-3 ${
                sanction.is_over_sanction
                  ? 'border-[var(--accent-amber,var(--accent-red))] bg-[var(--accent-amber-bg,var(--accent-red-bg))]'
                  : 'border-[var(--border)] bg-[var(--input-bg)]'
              }`}>
                <div className="flex flex-wrap gap-x-6 gap-y-1 text-[12.5px]">
                  <span className="text-[var(--text-muted)]">
                    Sanctioned:{' '}
                    <b className="text-[var(--text-main)]">
                      {sanction.has_sanction ? sanction.sanctioned : 'not set'}
                    </b>
                  </span>
                  <span className="text-[var(--text-muted)]">
                    Filled: <b className="text-[var(--text-main)]">{sanction.actual}</b>
                  </span>
                  <span className="text-[var(--text-muted)]">
                    Already committed:{' '}
                    <b className="text-[var(--text-main)]">{sanction.open_requisitions}</b>
                  </span>
                  <span className="text-[var(--text-muted)]">
                    Available:{' '}
                    <b className="text-[var(--text-main)]">
                      {sanction.available ?? '—'}
                    </b>
                  </span>
                </div>
                {sanction.is_over_sanction && (
                  <p className="flex items-start gap-1.5 mt-2 text-[12.5px] font-semibold text-[var(--accent-amber,var(--accent-red))]">
                    <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                    This requisition exceeds the sanctioned strength and will be escalated
                    for approval. MD approval is mandatory.
                  </p>
                )}
              </div>
            )}
          </div>

          {/* ══ Phase 11-R, Items 4 & 6 — client and budget ══ */}
          <div className="pt-4 border-t border-[var(--border)] space-y-3">
            <p className="text-[13px] font-bold text-[var(--text-main)]">Client &amp; budget</p>

            {/* An internal requisition is Sparsh Magic's own vacancy, so it has no client.
                The selector is not disabled, it is ABSENT -- a greyed-out control invites
                the question "why can't I pick one", which the track radio already answered. */}
            {clients.length > 0 && form.requisition_track !== 'internal' && (
              <div>
                <label className={LABEL} htmlFor="r-client">Client</label>
                <select id="r-client" value={form.client_id} onChange={set('client_id')} className={FIELD}>
                  <option value="">In-house / no client</option>
                  {clients.map((c) => (
                    <option key={c.client_id} value={c.client_id}>{c.name}</option>
                  ))}
                </select>
                <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                  From the Companies section. This is what the recruitment dashboard filters
                  by, so a requisition left in-house will not appear under any client.
                </p>
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className={LABEL} htmlFor="r-bsanc">Budget sanctioned by management</label>
                <input id="r-bsanc" type="number" min="0" value={form.budget_sanctioned_amount}
                  onChange={set('budget_sanctioned_amount')} className={FIELD} />
              </div>
              <div>
                <label className={LABEL} htmlFor="r-bhod">Budget approved by HOD</label>
                <input id="r-bhod" type="number" min="0" value={form.budget_hod_amount}
                  onChange={set('budget_hod_amount')} className={FIELD} />
              </div>
              <div>
                <label className={LABEL} htmlFor="r-bref">Sanction reference</label>
                <input id="r-bref" value={form.budget_sanctioned_ref}
                  onChange={set('budget_sanctioned_ref')}
                  placeholder="Approval note or minute number" className={FIELD} />
              </div>
              <div>
                <label className={LABEL} htmlFor="r-bdate">Sanctioned on</label>
                <input id="r-bdate" type="date" value={form.budget_sanctioned_on}
                  onChange={set('budget_sanctioned_on')} className={FIELD} />
              </div>
            </div>

            {budgetState !== 'Not Set' && (
              <div className={`rounded-lg border px-3.5 py-2.5 text-[12.5px] ${
                budgetState === 'Mismatch'
                  ? 'border-[var(--accent-red)] bg-[var(--accent-red-bg)] text-[var(--accent-red)]'
                  : 'border-[var(--border)] bg-[var(--input-bg)] text-[var(--text-muted)]'
              }`}>
                <b>Budget: {budgetState}.</b>{' '}
                {budgetState === 'Mismatch' && (
                  <>The two figures differ by{' '}
                    {Math.abs(Number(form.budget_hod_amount) - Number(form.budget_sanctioned_amount))
                      .toLocaleString('en-IN')}.{' '}
                    This does not block approval, but HR, the MD and you will be notified,
                    and the MD must record a remark when approving.
                  </>
                )}
                {budgetState === 'Pending' && (
                  <>Only one side has been recorded. The other approver will be notified.</>
                )}
              </div>
            )}

            <div>
              <label className={LABEL} htmlFor="r-brem">Budget remarks</label>
              <textarea id="r-brem" rows={2} value={form.budget_remarks}
                onChange={set('budget_remarks')} className={AREA} />
            </div>
          </div>

          {!isEdit && (
            <div className="pt-4 border-t border-[var(--border)] space-y-3">
              <div>
                <p className="text-[13px] font-bold text-[var(--text-main)]">Job description</p>
                <p className="text-[11.5px] text-[var(--text-muted)]">
                  Authored with the requisition and approved together — it is what candidates
                  will see once the role is published.
                </p>
              </div>
              <div>
                <label className={LABEL} htmlFor="j-resp">Key responsibilities *</label>
                <textarea id="j-resp" rows={4} required value={jd.responsibilities}
                  onChange={setJdField('responsibilities')} placeholder="One per line" className={AREA} />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className={LABEL} htmlFor="j-title">JD title</label>
                  <input id="j-title" value={jd.title} onChange={setJdField('title')}
                    placeholder="Defaults to the designation" className={FIELD} />
                </div>
                <div>
                  <label className={LABEL} htmlFor="j-loc">Location</label>
                  <input id="j-loc" value={jd.location} onChange={setJdField('location')} className={FIELD} />
                </div>
              </div>
              <div>
                <label className={LABEL} htmlFor="j-benefits">Benefits</label>
                <textarea id="j-benefits" rows={2} value={jd.benefits} onChange={setJdField('benefits')} className={AREA} />
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="submit" disabled={saving}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Raise for HR review'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default RequisitionFormModal;
