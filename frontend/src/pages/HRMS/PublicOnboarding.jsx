import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  UserCircle2, Loader2, CheckCircle2, AlertTriangle,
  User, Phone, IdCard, Landmark, Lock,
} from 'lucide-react';
import { getPublicOnboarding, submitPublicOnboarding } from '../../services/hrmsApi';
import { Field } from '../../components/hrms/hrmsUi';
import { inputCls, fmtDate } from '../../components/hrms/hrmsStyles';

// PUBLIC — no authentication. A new joiner reaches this with a one-time code to submit their KYC,
// so it renders outside the app shell (no sidebar, no nav).
//
// The form stays editable after a first submission — the backend accepts resubmissions right up
// until HR verifies the record, after which the link closes for good (a 409 on submit). We keep
// the copy simple: a note that details were received, with the form still open for corrections.

const EMPTY = {
  personal_email: '', phone: '', gender: '', date_of_birth: '', address: '',
  emergency_name: '', emergency_relation: '', emergency_phone: '',
  pan: '', aadhaar: '', passport: '', driving_license: '', uan: '', esic_no: '',
  bank_name: '', bank_account: '', bank_ifsc: '',
};

const SectionHeading = ({ icon: Icon, children }) => (
  <div className="flex items-center gap-2 mb-1">
    <span className="w-7 h-7 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shrink-0">
      <Icon size={14} />
    </span>
    <h2 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)]">
      {children}
    </h2>
  </div>
);

const PublicOnboarding = () => {
  const { code } = useParams();

  const [data, setData] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');          // the server's thank-you message

  const load = useCallback(async () => {
    try {
      const res = await getPublicOnboarding(code);
      setData(res.data);
    } catch (err) {
      // 409 means HR has already verified the record — the link is closed for good.
      setError(err.response?.data?.detail || 'This link is not valid.');
    } finally {
      setLoading(false);
    }
  }, [code]);

  useEffect(() => { load(); }, [load]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      // Only send filled fields, so a blank optional field never overwrites something on file.
      const payload = Object.fromEntries(
        Object.entries(form).filter(([, v]) => String(v).trim() !== ''),
      );
      const res = await submitPublicOnboarding(code, payload);
      setDone(res.data?.message || 'Thank you. Your details have been submitted.');
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const Centered = ({ tone, Icon, title, body }) => (
    <div className="min-h-screen flex items-center justify-center p-6 bg-[var(--bg-main)]">
      <div className="max-w-md text-center">
        <div className="w-14 h-14 mx-auto rounded-2xl flex items-center justify-center mb-4"
          style={{ backgroundColor: tone.bg, color: tone.fg }}>
          <Icon size={26} />
        </div>
        <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight">{title}</h1>
        <p className="text-[13px] font-semibold text-[var(--text-muted)] mt-2">{body}</p>
      </div>
    </div>
  );

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg-main)]">
        <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
          <Loader2 size={18} className="animate-spin" /> Loading…
        </span>
      </div>
    );
  }

  if (done) {
    return (
      <Centered
        tone={{ bg: 'var(--status-active-bg)', fg: 'var(--status-active-text)' }}
        Icon={CheckCircle2}
        title="Details received"
        body={done}
      />
    );
  }

  if (!data) {
    return (
      <Centered
        tone={{ bg: 'var(--accent-red-bg)', fg: 'var(--accent-red)' }}
        Icon={AlertTriangle}
        title="This link isn’t available"
        body={error || 'The link may have expired or be incorrect.'}
      />
    );
  }

  return (
    <div className="min-h-screen bg-[var(--bg-main)] py-10 px-4">
      <div className="max-w-2xl mx-auto flex flex-col gap-5">
        {/* Header */}
        <div className="p-6 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
          <div className="flex items-center gap-3">
            <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              <UserCircle2 size={20} />
            </span>
            <div>
              <h1 className="text-xl font-black tracking-tight text-[var(--text-main)] leading-tight">
                Welcome aboard
              </h1>
              <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
                Hello {data.candidateName}
              </p>
            </div>
          </div>
          {data.message && (
            <p className="text-[13px] font-medium text-[var(--text-muted)] mt-4 leading-relaxed">
              {data.message}
            </p>
          )}
          {data.dueOn && (
            <p className="text-[11.5px] font-bold text-[var(--text-muted)] mt-3">
              Please complete this by {fmtDate(data.dueOn)}.
            </p>
          )}
          {data.alreadySubmitted && (
            <div className="mt-4 flex items-start gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
              style={{ color: 'var(--status-active-text)', backgroundColor: 'var(--status-active-bg)', borderColor: 'var(--status-active-border)' }}>
              <CheckCircle2 size={15} className="mt-px shrink-0" />
              We’ve received your details. You can still update them here until they’re confirmed.
            </div>
          )}
        </div>

        {/* Form */}
        <form onSubmit={submit}
          className="p-6 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-col gap-6">
          {error && (
            <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
              style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
              <AlertTriangle size={15} /> {error}
            </div>
          )}

          {/* Personal */}
          <div className="flex flex-col gap-3.5">
            <SectionHeading icon={User}>Personal</SectionHeading>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              <Field label="Personal email">
                <input type="email" className={inputCls} value={form.personal_email}
                  onChange={set('personal_email')} />
              </Field>
              <Field label="Phone">
                <input className={inputCls} value={form.phone} onChange={set('phone')} />
              </Field>
              <Field label="Gender">
                <input className={inputCls} value={form.gender} onChange={set('gender')} />
              </Field>
              <Field label="Date of birth">
                <input type="date" className={inputCls} value={form.date_of_birth}
                  onChange={set('date_of_birth')} />
              </Field>
            </div>
            <Field label="Address">
              <textarea rows={3} className={`${inputCls} resize-y`} value={form.address}
                onChange={set('address')} />
            </Field>
          </div>

          {/* Emergency contact */}
          <div className="flex flex-col gap-3.5">
            <SectionHeading icon={Phone}>Emergency contact</SectionHeading>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              <Field label="Contact name">
                <input className={inputCls} value={form.emergency_name}
                  onChange={set('emergency_name')} />
              </Field>
              <Field label="Relationship">
                <input className={inputCls} value={form.emergency_relation}
                  onChange={set('emergency_relation')} />
              </Field>
              <Field label="Contact phone">
                <input className={inputCls} value={form.emergency_phone}
                  onChange={set('emergency_phone')} />
              </Field>
            </div>
          </div>

          {/* Statutory IDs */}
          <div className="flex flex-col gap-3.5">
            <SectionHeading icon={IdCard}>Statutory IDs</SectionHeading>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              <Field label="PAN">
                <input className={inputCls} value={form.pan} onChange={set('pan')} />
              </Field>
              <Field label="Aadhaar">
                <input className={inputCls} value={form.aadhaar} onChange={set('aadhaar')} />
              </Field>
              <Field label="Passport">
                <input className={inputCls} value={form.passport} onChange={set('passport')} />
              </Field>
              <Field label="Driving license">
                <input className={inputCls} value={form.driving_license}
                  onChange={set('driving_license')} />
              </Field>
              <Field label="UAN">
                <input className={inputCls} value={form.uan} onChange={set('uan')} />
              </Field>
              <Field label="ESIC number">
                <input className={inputCls} value={form.esic_no} onChange={set('esic_no')} />
              </Field>
            </div>
          </div>

          {/* Bank */}
          <div className="flex flex-col gap-3.5">
            <SectionHeading icon={Landmark}>Bank</SectionHeading>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              <Field label="Bank name">
                <input className={inputCls} value={form.bank_name} onChange={set('bank_name')} />
              </Field>
              <Field label="Account number">
                <input className={inputCls} value={form.bank_account}
                  onChange={set('bank_account')} />
              </Field>
              <Field label="IFSC">
                <input className={inputCls} value={form.bank_ifsc} onChange={set('bank_ifsc')} />
              </Field>
            </div>
          </div>

          <div className="flex items-start gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-semibold"
            style={{ color: 'var(--text-muted)', backgroundColor: 'var(--input-bg)', borderColor: 'var(--border)' }}>
            <Lock size={14} className="mt-px shrink-0 text-[var(--accent-indigo)]" />
            <span>
              Your statutory and bank details are collected securely for your employee record and
              are only visible to HR.
            </span>
          </div>

          <button type="submit" disabled={submitting}
            className="flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-[var(--btn-primary)] text-white text-[12px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.99] disabled:opacity-50 transition-all">
            {submitting && <Loader2 size={15} className="animate-spin" />}
            {data.alreadySubmitted ? 'Update details' : 'Submit details'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default PublicOnboarding;
