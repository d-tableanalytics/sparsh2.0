import React, { useCallback, useEffect, useState } from 'react';
import {
  Briefcase, Plus, Loader2, AlertTriangle, Search, X, Check, ShieldCheck,
  Clock, CheckCircle2, XCircle, FileText, History, RotateCcw, Flag,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import {
  getRequisitions, createRequisition, updateRequisition,
  decideRequisition, closeRequisition, getHrmsOptions, getHrmsClientOptions,
} from '../../services/hrmsApi';
import { hasHrmsPermission } from '../../utils/hrmsAccess';
import { StatTile, Field } from '../../components/hrms/hrmsUi';
import { inputCls, fmtDate, fmtDateTime } from '../../components/hrms/hrmsStyles';

// HRMS ▸ Recruitment. A requisition walks one approval chain, whose length depends on whether
// the vacancy sits inside sanctioned headcount:
//     within sanction: Pending HR Review → Pending MD Approval → Approved | Rejected
//     over sanction:   Pending HR Review → Pending HOD Approval → Pending MD Approval → …
// MD approval is compulsory on both paths — the HOD step is inserted before it, never instead.
//
// The buttons say what the person is DOING ("send for approval", "approve"), and the server
// derives the resulting state from where the requisition currently is — so the UI can't skip a
// step or approve twice. The job description is authored in the same form and co-approved;
// there is no separate JD approval to chase.

const APPROVAL_TONE = {
  'Pending HR Review':    { text: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', border: 'var(--accent-indigo-border)', Icon: ShieldCheck, short: 'HR review' },
  'Pending HOD Approval': { text: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', border: 'var(--accent-orange-border)', Icon: AlertTriangle, short: 'HOD approval' },
  'Pending MD Approval':  { text: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)', border: 'var(--accent-yellow-border)', Icon: Clock, short: 'MD approval' },
  Approved:              { text: 'var(--status-active-text)', bg: 'var(--status-active-bg)', border: 'var(--status-active-border)', Icon: CheckCircle2, short: 'Approved' },
  Rejected:              { text: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)', Icon: XCircle, short: 'Rejected' },
};

const CLOSING_TONE = {
  Open:      'var(--accent-indigo)',
  Hired:     'var(--status-active-text)',
  Closed:    'var(--text-muted)',
  Hold:      'var(--accent-orange)',
  Cancelled: 'var(--accent-red)',
};

const ApprovalBadge = ({ status }) => {
  const tone = APPROVAL_TONE[status] || APPROVAL_TONE['Pending HR Review'];
  const Icon = tone.Icon;
  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest border whitespace-nowrap"
      style={{ color: tone.text, backgroundColor: tone.bg, borderColor: tone.border }}>
      <Icon size={11} /> {tone.short}
    </span>
  );
};

const EMPTY = {
  department: '', designation: '', vacancy: 1, experience_required: '', offering_ctc: '',
  qualification: '', essential_skills: '', gender_preferred: 'Any', work_location: '',
  urgency_level: 'Medium', required_date: '', assignee: '', client_company_id: '',
  vacancy_type: 'New position', replacement_for: '',
  budget_sanctioned_by_management: { amount: '', remarks: '' },
  budget_approved_by_hod: { amount: '', remarks: '' },
  jd: { title: '', responsibilities: '', skills: '', qualifications: '', experience: '', ctc: '', location: '', benefits: '', employment_type: 'Full-time' },
};

const Requisitions = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();

  const canCreate = hasHrmsPermission(user, 'recruitment', 'create');
  const canReview = hasHrmsPermission(user, 'recruitment', 'update');

  const [data, setData] = useState(null);
  const [options, setOptions] = useState(null);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [approvalFilter, setApprovalFilter] = useState('');

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const [detail, setDetail] = useState(null);
  const [busy, setBusy] = useState('');
  const [remarks, setRemarks] = useState('');
  const [salaryChange, setSalaryChange] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getRequisitions({
        search: search || undefined,
        approval_status: approvalFilter || undefined,
      });
      setData(res.data);
      // Keep an open detail panel in step with the refreshed list.
      if (detail) {
        const fresh = res.data.requisitions.find((r) => r.requestNo === detail.requestNo);
        setDetail(fresh || null);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load requisitions');
    } finally {
      setLoading(false);
    }
    // `detail` is intentionally excluded — including it would refetch on every panel open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, approvalFilter]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { getHrmsOptions().then((r) => setOptions(r.data)).catch(() => {}); }, []);
  // Client list is a separate call: it comes from the companies collection, not the org masters
  // that /hrms/options serves. A recruiter without the grant simply gets no options.
  useEffect(() => { getHrmsClientOptions().then((r) => setClients(r.data || [])).catch(() => {}); }, []);

  const rows = data?.requisitions ?? [];
  const stats = data?.stats ?? {};
  const canApproveMd = !!data?.canApproveMd;

  const openCreate = () => { setEditing(null); setForm(EMPTY); setShowForm(true); };
  const openEdit = (r) => {
    setEditing(r);
    setForm({
      department: r.department, designation: r.designation, vacancy: r.vacancy,
      experience_required: r.experienceRequired, offering_ctc: r.offeringCtc,
      qualification: r.qualification, essential_skills: r.essentialSkills,
      gender_preferred: r.genderPreferred, work_location: r.workLocation,
      urgency_level: r.urgencyLevel, required_date: r.requiredDate || '', assignee: r.assignee,
      client_company_id: r.clientCompanyId || '',
      vacancy_type: r.vacancyType || 'New position',
      replacement_for: r.replacementFor || '',
      budget_sanctioned_by_management: {
        amount: r.budgetSanctionedByManagement?.amount ?? '',
        remarks: r.budgetSanctionedByManagement?.remarks || '',
      },
      budget_approved_by_hod: {
        amount: r.budgetApprovedByHod?.amount ?? '',
        remarks: r.budgetApprovedByHod?.remarks || '',
      },
      jd: {
        title: r.jd?.title || '', responsibilities: r.jd?.responsibilities || '',
        skills: r.jd?.skills || '', qualifications: r.jd?.qualifications || '',
        experience: r.jd?.experience || '', ctc: r.jd?.ctc || '',
        location: r.jd?.location || '', benefits: r.jd?.benefits || '',
        employment_type: r.jd?.employmentType || 'Full-time',
      },
    });
    setShowForm(true);
  };

  const submit = async () => {
    if (!form.department.trim() || !form.designation.trim()) {
      showError('Department and designation are required');
      return;
    }
    setSaving(true);
    // An empty budget box means "not recorded yet", which the server reads as null and reports
    // as pending — not as zero, which would look like a real sanction of nothing.
    const money = (b) => {
      const amount = String(b?.amount ?? '').trim();
      return { amount: amount === '' ? null : Number(amount), remarks: b?.remarks || '' };
    };
    const payload = {
      ...form,
      budget_sanctioned_by_management: money(form.budget_sanctioned_by_management),
      budget_approved_by_hod: money(form.budget_approved_by_hod),
    };
    try {
      if (editing) {
        await updateRequisition(editing.requestNo, payload);
        showSuccess(`${editing.requestNo} updated`);
      } else {
        const res = await createRequisition(payload);
        showSuccess(`Requisition ${res.data.requestNo} raised`);
      }
      setShowForm(false);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save requisition');
    } finally {
      setSaving(false);
    }
  };

  const decide = async (r, action) => {
    setBusy(`${r.requestNo}:${action}`);
    try {
      await decideRequisition(r.requestNo, {
        action,
        remarks,
        salary_change: action === 'advance' ? salaryChange : '',
      });
      showSuccess(
        action === 'reject' ? `${r.requestNo} rejected`
          : action === 'resubmit' ? `${r.requestNo} resubmitted`
            : `${r.requestNo} moved forward`,
      );
      setRemarks(''); setSalaryChange('');
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update requisition');
    } finally {
      setBusy('');
    }
  };

  const setClosing = async (r, closing_status) => {
    setBusy(`${r.requestNo}:close`);
    try {
      await closeRequisition(r.requestNo, { closing_status });
      showSuccess(`${r.requestNo} marked ${closing_status}`);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update vacancy status');
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="p-6 sm:p-8 flex flex-col gap-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
            <Briefcase size={20} />
          </span>
          <div>
            <h1 className="text-xl sm:text-2xl font-black tracking-tight text-[var(--text-main)] leading-tight">
              Recruitment
            </h1>
            <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
              Hiring requisitions and job descriptions
            </p>
          </div>
        </div>
        {canCreate && (
          <button onClick={openCreate}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[12px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] transition-all">
            <Plus size={15} /> Raise requisition
          </button>
        )}
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <StatTile icon={FileText} label="Total" value={stats.total ?? 0} loading={loading} />
        <StatTile icon={ShieldCheck} label="Awaiting HR" value={stats.pendingHr ?? 0} loading={loading} />
        <StatTile icon={AlertTriangle} label="Awaiting HOD" value={stats.pendingHod ?? 0} loading={loading} />
        <StatTile icon={Clock} label="Awaiting MD" value={stats.pendingMd ?? 0} loading={loading} />
        <StatTile icon={CheckCircle2} label="Approved" value={stats.approved ?? 0} loading={loading} />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2.5 p-3 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search designation, department, number…" className={`${inputCls} pl-9`} />
        </div>
        <select value={approvalFilter} onChange={(e) => setApprovalFilter(e.target.value)}
          className={`${inputCls} w-auto min-w-[170px] cursor-pointer`}>
          <option value="">All stages</option>
          {Object.keys(APPROVAL_TONE).map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {(search || approvalFilter) && (
          <button onClick={() => { setSearch(''); setApprovalFilter(''); }}
            className="flex items-center gap-1.5 px-3 py-2.5 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors">
            <X size={13} /> Clear
          </button>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
          style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* Table */}
      <div className="rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full" style={{ minWidth: 900 }}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                {['Requisition', 'Department', 'Client', 'Vacancy', 'Needed by', 'Stage', 'Vacancy status', ''].map((h, i) => (
                  <th key={i} className="text-left px-4 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={8} className="px-4 py-12 text-center">
                  <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
                    <Loader2 size={16} className="animate-spin" /> Loading…
                  </span>
                </td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={8} className="px-4 py-12 text-center">
                  <p className="text-[13px] font-bold text-[var(--text-main)]">No requisitions.</p>
                  <p className="text-[12px] font-medium text-[var(--text-muted)] mt-1">
                    {canCreate ? 'Raise one to start hiring.' : 'Nothing raised yet.'}
                  </p>
                </td></tr>
              )}
              {!loading && rows.map((r) => (
                <tr key={r.requestNo} onClick={() => setDetail(r)}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors cursor-pointer">
                  <td className="px-4 py-3">
                    <div className="text-[12.5px] font-black text-[var(--text-main)]">{r.designation}</div>
                    <div className="text-[11px] font-medium text-[var(--text-muted)]"
                      style={{ fontVariantNumeric: 'tabular-nums' }}>{r.requestNo}</div>
                  </td>
                  <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]">{r.department}</td>
                  <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]">
                    {r.clientCompanyName || <span className="opacity-50">Internal</span>}
                  </td>
                  <td className="px-4 py-3 text-[12px] font-black text-[var(--text-main)]"
                    style={{ fontVariantNumeric: 'tabular-nums' }}>{r.vacancy}</td>
                  <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]">
                    {fmtDate(r.requiredDate)}
                  </td>
                  <td className="px-4 py-3"><ApprovalBadge status={r.approvalStatus} /></td>
                  <td className="px-4 py-3">
                    <span className="text-[11px] font-black uppercase tracking-widest"
                      style={{ color: CLOSING_TONE[r.closingStatus] || 'var(--text-muted)' }}>
                      {r.closingStatus}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                      Details
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Create / edit */}
      {showForm && (
        <div className="fixed inset-0 z-[350] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setShowForm(false)} />
          <div className="relative w-full max-w-3xl max-h-[90vh] flex flex-col rounded-[24px] bg-[var(--bg-card)] border border-[var(--border)] shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)] bg-[var(--table-header-bg)]">
              <h2 className="text-[15px] font-black tracking-tight text-[var(--text-main)]">
                {editing ? `Edit ${editing.requestNo}` : 'Raise requisition'}
              </h2>
              <button onClick={() => setShowForm(false)}
                className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--table-hover)] transition-colors">
                <X size={19} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-4">
              <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)]">
                The role
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
                <Field label="Designation" required>
                  <input className={inputCls} list="req-designations" value={form.designation}
                    onChange={(e) => setForm({ ...form, designation: e.target.value })} autoFocus />
                  <datalist id="req-designations">
                    {(options?.designations ?? []).map((d) => <option key={d} value={d} />)}
                  </datalist>
                </Field>
                <Field label="Department" required>
                  <input className={inputCls} list="req-departments" value={form.department}
                    onChange={(e) => setForm({ ...form, department: e.target.value })} />
                  <datalist id="req-departments">
                    {(options?.departments ?? []).map((d) => <option key={d} value={d} />)}
                  </datalist>
                </Field>
                <Field label="Vacancies" required>
                  <input type="number" min="1" className={inputCls} value={form.vacancy}
                    onChange={(e) => setForm({ ...form, vacancy: Number(e.target.value) || 1 })} />
                </Field>
                {/* Blank = a Sparsh internal hire, which is what every requisition raised
                    before client linkage existed reads as. */}
                <Field label="Hiring for client">
                  <select className={inputCls} value={form.client_company_id}
                    onChange={(e) => setForm({ ...form, client_company_id: e.target.value })}>
                    <option value="">Sparsh (internal hire)</option>
                    {clients.map((c) => <option key={c._id} value={c._id}>{c.name}</option>)}
                  </select>
                </Field>
                <Field label="Vacancy type">
                  <select className={inputCls} value={form.vacancy_type}
                    onChange={(e) => setForm({ ...form, vacancy_type: e.target.value })}>
                    <option value="New position">New position</option>
                    <option value="Replacement">Replacement</option>
                  </select>
                </Field>
                {form.vacancy_type === 'Replacement' && (
                  <Field label="Replacing">
                    <input className={inputCls} placeholder="Employee code or name"
                      value={form.replacement_for}
                      onChange={(e) => setForm({ ...form, replacement_for: e.target.value })} />
                  </Field>
                )}
                <Field label="Experience required">
                  <input className={inputCls} placeholder="e.g. 2-4 years" value={form.experience_required}
                    onChange={(e) => setForm({ ...form, experience_required: e.target.value })} />
                </Field>
                <Field label="Offered CTC">
                  <input className={inputCls} placeholder="e.g. 6-8 LPA" value={form.offering_ctc}
                    onChange={(e) => setForm({ ...form, offering_ctc: e.target.value })} />
                </Field>
                <Field label="Work location">
                  <input className={inputCls} list="req-locations" value={form.work_location}
                    onChange={(e) => setForm({ ...form, work_location: e.target.value })} />
                  <datalist id="req-locations">
                    {(options?.locations ?? []).map((d) => <option key={d} value={d} />)}
                  </datalist>
                </Field>
                <Field label="Urgency">
                  <select className={`${inputCls} cursor-pointer`} value={form.urgency_level}
                    onChange={(e) => setForm({ ...form, urgency_level: e.target.value })}>
                    {['High', 'Medium', 'Low'].map((u) => <option key={u} value={u}>{u}</option>)}
                  </select>
                </Field>
                <Field label="Needed by">
                  <input type="date" className={inputCls} value={form.required_date || ''}
                    onChange={(e) => setForm({ ...form, required_date: e.target.value })} />
                </Field>
                <Field label="Reports to">
                  <input className={inputCls} value={form.assignee}
                    onChange={(e) => setForm({ ...form, assignee: e.target.value })} />
                </Field>
              </div>

              {/* Budget approval. Both sides are optional at raise time — leaving one blank
                  records it as pending and notifies the stakeholders, rather than blocking. */}
              <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mt-5">
                Budget approval
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                <Field label="Sanctioned by management">
                  <input type="number" min="0" className={inputCls} placeholder="Amount"
                    value={form.budget_sanctioned_by_management.amount}
                    onChange={(e) => setForm({
                      ...form,
                      budget_sanctioned_by_management: {
                        ...form.budget_sanctioned_by_management, amount: e.target.value,
                      },
                    })} />
                </Field>
                <Field label="Approved by HOD">
                  <input type="number" min="0" className={inputCls} placeholder="Amount"
                    value={form.budget_approved_by_hod.amount}
                    onChange={(e) => setForm({
                      ...form,
                      budget_approved_by_hod: {
                        ...form.budget_approved_by_hod, amount: e.target.value,
                      },
                    })} />
                </Field>
              </div>

              <Field label="Essential skills">
                <textarea rows={2} className={`${inputCls} resize-y`} value={form.essential_skills}
                  onChange={(e) => setForm({ ...form, essential_skills: e.target.value })} />
              </Field>

              <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] pt-1">
                Job description
              </h3>
              <p className="text-[11px] font-medium text-[var(--text-muted)] -mt-2">
                Written here and approved together with the requisition — there is no separate
                JD sign-off.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                <Field label="JD title">
                  <input className={inputCls} value={form.jd.title}
                    onChange={(e) => setForm({ ...form, jd: { ...form.jd, title: e.target.value } })} />
                </Field>
                <Field label="Employment type">
                  <select className={`${inputCls} cursor-pointer`} value={form.jd.employment_type}
                    onChange={(e) => setForm({ ...form, jd: { ...form.jd, employment_type: e.target.value } })}>
                    {(options?.employmentTypes ?? ['Full-time']).map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </Field>
              </div>
              <Field label="Responsibilities">
                <textarea rows={3} className={`${inputCls} resize-y`} value={form.jd.responsibilities}
                  onChange={(e) => setForm({ ...form, jd: { ...form.jd, responsibilities: e.target.value } })} />
              </Field>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                <Field label="Skills">
                  <textarea rows={2} className={`${inputCls} resize-y`} value={form.jd.skills}
                    onChange={(e) => setForm({ ...form, jd: { ...form.jd, skills: e.target.value } })} />
                </Field>
                <Field label="Qualifications">
                  <textarea rows={2} className={`${inputCls} resize-y`} value={form.jd.qualifications}
                    onChange={(e) => setForm({ ...form, jd: { ...form.jd, qualifications: e.target.value } })} />
                </Field>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2.5 px-6 py-4 border-t border-[var(--border)] bg-[var(--table-header-bg)]">
              <button onClick={() => setShowForm(false)}
                className="px-5 py-2.5 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                Cancel
              </button>
              <button onClick={submit} disabled={saving}
                className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
                {saving && <Loader2 size={14} className="animate-spin" />}
                {editing ? 'Save changes' : 'Raise requisition'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Detail + approval chain */}
      {detail && (
        <div className="fixed inset-0 z-[350] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setDetail(null)} />
          <div className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-[24px] bg-[var(--bg-card)] border border-[var(--border)] shadow-2xl">
            <div className="sticky top-0 flex items-start justify-between px-6 py-4 border-b border-[var(--border)] bg-[var(--table-header-bg)]">
              <div>
                <h2 className="text-[15px] font-black tracking-tight text-[var(--text-main)]">
                  {detail.designation}
                </h2>
                <p className="text-[11.5px] font-bold text-[var(--text-muted)]"
                  style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {detail.requestNo} · {detail.department} · {detail.vacancy} vacancy
                </p>
              </div>
              <button onClick={() => setDetail(null)}
                className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--table-hover)] transition-colors">
                <X size={19} />
              </button>
            </div>

            <div className="px-6 py-5 flex flex-col gap-4">
              <div className="flex flex-wrap items-center gap-2">
                <ApprovalBadge status={detail.approvalStatus} />
                <span className="text-[11px] font-black uppercase tracking-widest"
                  style={{ color: CLOSING_TONE[detail.closingStatus] }}>
                  {detail.closingStatus}
                </span>
                {detail.urgencyLevel === 'High' && (
                  <span className="inline-flex items-center gap-1 text-[10px] font-black uppercase tracking-widest"
                    style={{ color: 'var(--accent-red)' }}>
                    <Flag size={11} /> Urgent
                  </span>
                )}
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {[
                  ['Experience', detail.experienceRequired],
                  ['Offered CTC', detail.offeringCtc],
                  ['Location', detail.workLocation],
                  ['Needed by', fmtDate(detail.requiredDate)],
                  ['Raised by', detail.createdBy],
                  ['Reports to', detail.assignee],
                ].map(([label, value]) => (
                  <div key={label}>
                    <div className="text-[9.5px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                      {label}
                    </div>
                    <div className="text-[12.5px] font-bold text-[var(--text-main)]">{value || '—'}</div>
                  </div>
                ))}
              </div>

              {detail.jd && (
                <div className="p-4 rounded-xl bg-[var(--input-bg)] border border-[var(--border)]">
                  <div className="flex items-center gap-2 mb-2">
                    <FileText size={13} className="text-[var(--accent-indigo)]" />
                    <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                      Job description · v{detail.jd.version}
                    </span>
                  </div>
                  {detail.jd.responsibilities && (
                    <p className="text-[12px] font-medium text-[var(--text-muted)] whitespace-pre-wrap">
                      {detail.jd.responsibilities}
                    </p>
                  )}
                </div>
              )}

              {/* Sanction position + budget. Shown for every requisition so the reason a
                  requisition escalated is visible next to the decision that acts on it. */}
              <div className="p-4 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] flex flex-col gap-3">
                <div className="flex items-center gap-2">
                  <Flag size={13} className="text-[var(--accent-indigo)]" />
                  <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                    Sanction &amp; budget
                  </span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    ['Vacancy type', detail.vacancyType],
                    ['Sanctioned', detail.sanctionedHeadcount],
                    ['Actual', detail.actualHeadcount],
                    ['Replacing', detail.replacementFor || '—'],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <div className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)]">{label}</div>
                      <div className="text-[12.5px] font-bold text-[var(--text-main)]">{value ?? '—'}</div>
                    </div>
                  ))}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)]">Mgmt sanctioned</div>
                    <div className="text-[12.5px] font-bold text-[var(--text-main)]">
                      {detail.budgetSanctionedByManagement?.amount ?? '—'}
                    </div>
                  </div>
                  <div>
                    <div className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)]">HOD approved</div>
                    <div className="text-[12.5px] font-bold text-[var(--text-main)]">
                      {detail.budgetApprovedByHod?.amount ?? '—'}
                    </div>
                  </div>
                </div>
                {detail.overSanction && (
                  <div className="flex items-start gap-2 text-[11.5px] font-bold"
                    style={{ color: 'var(--accent-orange)' }}>
                    <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                    Over sanctioned headcount — needs HOD approval before MD.
                  </div>
                )}
                {detail.budgetIssue && (
                  <div className="flex items-start gap-2 text-[11.5px] font-bold"
                    style={{ color: 'var(--accent-red)' }}>
                    <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                    {detail.budgetIssue}
                  </div>
                )}
              </div>

              {/* Approval actions — only what is legal from the current state. */}
              {(canReview || canApproveMd) && ['Pending HR Review', 'Pending HOD Approval', 'Pending MD Approval', 'Rejected'].includes(detail.approvalStatus) && (
                <div className="p-4 rounded-xl border border-dashed border-[var(--border)] flex flex-col gap-3">
                  <span className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)]">
                    {detail.approvalStatus === 'Rejected' ? 'Revise' : 'Decision'}
                  </span>
                  <input className={inputCls} value={remarks} placeholder="Remarks (optional)"
                    onChange={(e) => setRemarks(e.target.value)} />
                  {detail.approvalStatus === 'Pending MD Approval' && canApproveMd && (
                    <Field label="Revise offered CTC (optional)">
                      <input className={inputCls} value={salaryChange} placeholder={detail.offeringCtc}
                        onChange={(e) => setSalaryChange(e.target.value)} />
                    </Field>
                  )}
                  <div className="flex flex-wrap items-center gap-2">
                    {detail.approvalStatus === 'Pending HR Review' && canReview && (
                      <button onClick={() => decide(detail, 'advance')} disabled={!!busy}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50"
                        style={{ backgroundColor: 'var(--btn-primary)' }}>
                        {/* Label follows where the server will actually route it, so the
                            reviewer isn't told "MD" and then sees it land with the HOD. */}
                        <Check size={13} /> {detail.overSanction ? 'Escalate to HOD' : 'Send for MD approval'}
                      </button>
                    )}
                    {detail.approvalStatus === 'Pending HOD Approval' && (canReview || canApproveMd) && (
                      <button onClick={() => decide(detail, 'advance')} disabled={!!busy}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50"
                        style={{ backgroundColor: 'var(--accent-orange)' }}>
                        <Check size={13} /> HOD approve — send to MD
                      </button>
                    )}
                    {detail.approvalStatus === 'Pending MD Approval' && canApproveMd && (
                      <button onClick={() => decide(detail, 'advance')} disabled={!!busy}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50"
                        style={{ backgroundColor: 'var(--accent-green)' }}>
                        <CheckCircle2 size={13} /> Approve
                      </button>
                    )}
                    {detail.approvalStatus === 'Rejected' && canReview && (
                      <button onClick={() => decide(detail, 'resubmit')} disabled={!!busy}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50"
                        style={{ backgroundColor: 'var(--btn-primary)' }}>
                        <RotateCcw size={13} /> Resubmit
                      </button>
                    )}
                    {detail.approvalStatus !== 'Rejected' && (canReview || canApproveMd) && (
                      <button onClick={() => decide(detail, 'reject')} disabled={!!busy}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50"
                        style={{ backgroundColor: 'var(--accent-red)' }}>
                        <XCircle size={13} /> Reject
                      </button>
                    )}
                    {canReview && detail.approvalStatus !== 'Approved' && (
                      <button onClick={() => openEdit(detail)}
                        className="px-4 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                        Edit
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* Vacancy status — separate from approval; an approved req stays approved once filled. */}
              {canReview && detail.approvalStatus === 'Approved' && (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                    Vacancy
                  </span>
                  {['Open', 'Hired', 'Hold', 'Closed', 'Cancelled'].map((s) => (
                    <button key={s} onClick={() => setClosing(detail, s)} disabled={!!busy}
                      className={`px-3 py-1.5 rounded-lg border text-[10px] font-black uppercase tracking-widest transition-colors disabled:opacity-50 ${
                        detail.closingStatus === s
                          ? 'bg-[var(--accent-indigo-bg)] border-[var(--accent-indigo-border)]'
                          : 'border-[var(--border)] hover:border-[var(--accent-indigo)]'
                      }`}
                      style={{ color: detail.closingStatus === s ? 'var(--accent-indigo)' : 'var(--text-muted)' }}>
                      {s}
                    </button>
                  ))}
                </div>
              )}

              {/* History — replaces the reference's 27 numbered columns. */}
              {(detail.steps || []).length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <History size={13} className="text-[var(--text-muted)]" />
                    <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                      History
                    </span>
                  </div>
                  <ol className="flex flex-col gap-2.5">
                    {detail.steps.map((s, i) => (
                      <li key={i} className="flex gap-3">
                        <span className="w-1.5 h-1.5 rounded-full mt-2 shrink-0"
                          style={{ backgroundColor: 'var(--accent-indigo)' }} />
                        <div>
                          <div className="text-[12px] font-bold text-[var(--text-main)]">{s.label}</div>
                          <div className="text-[11px] font-medium text-[var(--text-muted)]">
                            {s.actorName} · {fmtDateTime(s.at)}
                            {s.remarks ? ` — ${s.remarks}` : ''}
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

export default Requisitions;
