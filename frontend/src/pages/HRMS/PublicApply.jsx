import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Briefcase, Upload, Loader2, CheckCircle2, AlertTriangle, FileText } from 'lucide-react';
import { getPublicPosting, submitApplication } from '../../services/hrmsApi';
import { Field } from '../../components/hrms/hrmsUi';
import { inputCls } from '../../components/hrms/hrmsStyles';

// PUBLIC — no authentication. Rendered outside the app shell (no sidebar, no nav), because the
// visitor is a job applicant, not a Sparsh user.
//
// Everything the server rejects is surfaced as plain guidance rather than an error code: an
// applicant can't be expected to interpret a 409. The page shows only the role — no internal
// identifiers, no requisition number, no application counts.

const MAX_MB = 5;
const ACCEPT = '.pdf,.doc,.docx';

const PublicApply = () => {
  const { code } = useParams();

  const [posting, setPosting] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [fileName, setFileName] = useState('');

  const [form, setForm] = useState({
    full_name: '', email: '', phone: '', current_company: '',
    experience_years: '', current_ctc: '', expected_ctc: '', notice_period: '',
    cover_note: '', resume: null,
  });

  const load = useCallback(async () => {
    try {
      const res = await getPublicPosting(code);
      setPosting(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'This link is not valid.');
    } finally {
      setLoading(false);
    }
  }, [code]);

  useEffect(() => { load(); }, [load]);

  const onFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Checked here for a fast, friendly message; the server enforces the same limit and the
    // same type allow-list, since a client check is only a convenience.
    if (file.size > MAX_MB * 1024 * 1024) {
      setError(`That file is larger than ${MAX_MB} MB. Please attach a smaller one.`);
      e.target.value = '';
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setForm((f) => ({ ...f, resume: reader.result }));
      setFileName(file.name);
      setError('');
    };
    reader.onerror = () => setError('That file could not be read. Please try another.');
    reader.readAsDataURL(file);
  };

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await submitApplication(code, form);
      setDone(true);
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg-main)]">
        <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
          <Loader2 size={18} className="animate-spin" /> Loading…
        </span>
      </div>
    );
  }

  if (!posting) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-[var(--bg-main)]">
        <div className="max-w-md text-center">
          <div className="w-14 h-14 mx-auto rounded-2xl flex items-center justify-center mb-4"
            style={{ backgroundColor: 'var(--accent-red-bg)', color: 'var(--accent-red)' }}>
            <AlertTriangle size={26} />
          </div>
          <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight">
            This link isn’t available
          </h1>
          <p className="text-[13px] font-semibold text-[var(--text-muted)] mt-2">
            {error || 'The role may have closed, or the link may be incorrect.'}
          </p>
        </div>
      </div>
    );
  }

  if (done) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-[var(--bg-main)]">
        <div className="max-w-md text-center">
          <div className="w-14 h-14 mx-auto rounded-2xl flex items-center justify-center mb-4"
            style={{ backgroundColor: 'var(--status-active-bg)', color: 'var(--status-active-text)' }}>
            <CheckCircle2 size={26} />
          </div>
          <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight">
            Application received
          </h1>
          <p className="text-[13px] font-semibold text-[var(--text-muted)] mt-2">
            Thank you for applying for {posting.designation}. If your profile matches what we
            are looking for, our team will be in touch.
          </p>
        </div>
      </div>
    );
  }

  const jd = posting.jd;

  return (
    <div className="min-h-screen bg-[var(--bg-main)] py-10 px-4">
      <div className="max-w-2xl mx-auto flex flex-col gap-5">
        {/* Role */}
        <div className="p-6 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
          <div className="flex items-center gap-3 mb-3">
            <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              <Briefcase size={20} />
            </span>
            <div>
              <h1 className="text-xl font-black tracking-tight text-[var(--text-main)] leading-tight">
                {posting.designation}
              </h1>
              <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
                {posting.department}
                {jd?.location ? ` · ${jd.location}` : ''}
                {jd?.employmentType ? ` · ${jd.employmentType}` : ''}
              </p>
            </div>
          </div>

          {jd?.responsibilities && (
            <div className="mt-4">
              <h2 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-1.5">
                About the role
              </h2>
              <p className="text-[13px] font-medium text-[var(--text-muted)] whitespace-pre-wrap leading-relaxed">
                {jd.responsibilities}
              </p>
            </div>
          )}
          {jd?.skills && (
            <div className="mt-4">
              <h2 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-1.5">
                What we’re looking for
              </h2>
              <p className="text-[13px] font-medium text-[var(--text-muted)] whitespace-pre-wrap leading-relaxed">
                {jd.skills}
              </p>
            </div>
          )}
        </div>

        {/* Form */}
        <form onSubmit={submit}
          className="p-6 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-col gap-4">
          <h2 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)]">
            Your details
          </h2>

          {error && (
            <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
              style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
              <AlertTriangle size={15} /> {error}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            <Field label="Full name" required>
              <input className={inputCls} required value={form.full_name}
                onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
            </Field>
            <Field label="Email" required>
              <input type="email" className={inputCls} required value={form.email}
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
            <Field label="Total experience">
              <input className={inputCls} placeholder="e.g. 4 years" value={form.experience_years}
                onChange={(e) => setForm({ ...form, experience_years: e.target.value })} />
            </Field>
            <Field label="Notice period">
              <input className={inputCls} placeholder="e.g. 30 days" value={form.notice_period}
                onChange={(e) => setForm({ ...form, notice_period: e.target.value })} />
            </Field>
            <Field label="Current CTC">
              <input className={inputCls} value={form.current_ctc}
                onChange={(e) => setForm({ ...form, current_ctc: e.target.value })} />
            </Field>
            <Field label="Expected CTC">
              <input className={inputCls} value={form.expected_ctc}
                onChange={(e) => setForm({ ...form, expected_ctc: e.target.value })} />
            </Field>
          </div>

          <Field label="Anything you’d like us to know">
            <textarea rows={3} className={`${inputCls} resize-y`} value={form.cover_note}
              onChange={(e) => setForm({ ...form, cover_note: e.target.value })} />
          </Field>

          <div>
            <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
              Résumé
            </span>
            <label className="mt-1.5 flex items-center gap-2.5 px-4 py-3 rounded-xl border border-dashed border-[var(--border)] bg-[var(--input-bg)] cursor-pointer hover:border-[var(--accent-indigo)] transition-colors">
              {fileName ? <FileText size={16} className="text-[var(--accent-indigo)]" />
                : <Upload size={16} className="text-[var(--text-muted)]" />}
              <span className="text-[12.5px] font-bold text-[var(--text-muted)] truncate">
                {fileName || `Attach a PDF or Word file (up to ${MAX_MB} MB)`}
              </span>
              <input type="file" accept={ACCEPT} onChange={onFile} className="hidden" />
            </label>
          </div>

          <button type="submit" disabled={submitting}
            className="mt-1 flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-[var(--btn-primary)] text-white text-[12px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.99] disabled:opacity-50 transition-all">
            {submitting && <Loader2 size={15} className="animate-spin" />}
            Submit application
          </button>
        </form>
      </div>
    </div>
  );
};

export default PublicApply;
