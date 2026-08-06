import React, { useEffect, useState } from 'react';
import { X, FilePlus2 } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { createRequisition, updateRequisition, getDepartments, getDesignations, getEmployees }
  from '../../../services/hrmsApi';

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
  });
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    // Mirrors the server rule exactly, so the user is told before a round trip rather than
    // after one. The server still enforces it — this is not the control.
    if (!isEdit && !jd.responsibilities.trim()) {
      showError('Provide a Job Description — enter the key responsibilities.');
      return;
    }
    setSaving(true);
    try {
      const payload = {
        ...form,
        vacancy: Number(form.vacancy) || 1,
        offering_ctc: form.offering_ctc === '' ? null : Number(form.offering_ctc),
      };
      if (isEdit) {
        await updateRequisition(existing.request_no, payload, scope);
        showSuccess(`Requisition ${existing.request_no} updated`);
      } else {
        const { data } = await createRequisition({ ...payload, jd }, scope);
        showSuccess(`Requisition ${data.request_no} raised — routed to HR for review`);
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
