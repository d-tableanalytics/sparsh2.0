import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  FileSignature, Loader2, CheckCircle2, AlertTriangle,
  Building2, MapPin, CalendarDays, Wallet, Briefcase, UserCog,
} from 'lucide-react';
import { getPublicAppointment, acknowledgePublicAppointment } from '../../services/hrmsApi';
import { inputCls, fmtDate } from '../../components/hrms/hrmsStyles';

// PUBLIC — no authentication. The candidate reaches this with a one-time appointment code, so
// the page renders outside the app shell (no sidebar, no nav): the visitor is a new joiner, not
// a Sparsh user. Deliberately mirrors PublicOffer so the two candidate-facing pages read as one
// family.
//
// The server is state-gated: once acknowledged the link returns 409 rather than letting the
// acknowledgement be rewritten, so a reload shows a clear "already acknowledged" state.

const fmtCtc = (value) => {
  const n = Number(value);
  if (!n) return '—';
  try {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency', currency: 'INR', maximumFractionDigits: 0,
    }).format(n);
  } catch {
    return String(value);
  }
};

const Detail = ({ icon: Icon, label, value }) => (
  <div className="flex items-start gap-3">
    <span className="w-9 h-9 rounded-xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shrink-0">
      <Icon size={16} />
    </span>
    <div className="min-w-0">
      <div className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
        {label}
      </div>
      <div className="text-[13.5px] font-bold text-[var(--text-main)] mt-0.5 break-words">
        {value || '—'}
      </div>
    </div>
  </div>
);

const PublicAppointment = () => {
  const { code } = useParams();

  const [letter, setLetter] = useState(null);
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');
  const [alreadyDone, setAlreadyDone] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await getPublicAppointment(code);
      setLetter(res.data);
    } catch (err) {
      // 409 means it was already acknowledged — a distinct, reassuring state.
      if (err.response?.status === 409) setAlreadyDone(true);
      else setError(err.response?.data?.detail || 'This link is not valid.');
    } finally {
      setLoading(false);
    }
  }, [code]);

  useEffect(() => { load(); }, [load]);

  const acknowledge = async () => {
    setError('');
    setSubmitting(true);
    try {
      const res = await acknowledgePublicAppointment(code, { acknowledged: true, note });
      setDone(res.data?.message || 'Thank you. Your acknowledgement has been recorded.');
    } catch (err) {
      if (err.response?.status === 409) setAlreadyDone(true);
      else setError(err.response?.data?.detail || 'Something went wrong. Please try again.');
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
        title="Acknowledgement recorded"
        body={done}
      />
    );
  }

  if (alreadyDone) {
    return (
      <Centered
        tone={{ bg: 'var(--status-active-bg)', fg: 'var(--status-active-text)' }}
        Icon={CheckCircle2}
        title="Already acknowledged"
        body="You have already acknowledged this appointment letter, so the link can’t be opened again."
      />
    );
  }

  if (!letter) {
    return (
      <Centered
        tone={{ bg: 'var(--accent-red-bg)', fg: 'var(--accent-red)' }}
        Icon={AlertTriangle}
        title="This link isn’t available"
        body={error || 'The letter may have expired or the link may be incorrect.'}
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
              <FileSignature size={20} />
            </span>
            <div>
              <h1 className="text-xl font-black tracking-tight text-[var(--text-main)] leading-tight">
                Your appointment letter
              </h1>
              <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
                Hello {letter.candidateName}
              </p>
            </div>
          </div>
          <p className="text-[13px] font-medium text-[var(--text-muted)] mt-4 leading-relaxed">
            Welcome aboard. Please review the details below and confirm that you have received
            this appointment letter.
          </p>
        </div>

        {/* Letter details */}
        <div className="p-6 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
          <h2 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-4">
            Appointment details
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <Detail icon={Briefcase} label="Designation" value={letter.designation} />
            <Detail icon={Building2} label="Department" value={letter.department} />
            <Detail icon={Wallet} label="Annual CTC" value={fmtCtc(letter.annualCtc)} />
            <Detail icon={CalendarDays} label="Joining date" value={fmtDate(letter.joiningDate)} />
            <Detail icon={MapPin} label="Location" value={letter.location} />
            <Detail icon={UserCog} label="Reporting to" value={letter.reportingTo} />
          </div>
          {letter.terms && (
            <div className="mt-5 pt-5 border-t border-[var(--border)]">
              <div className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] mb-2">
                Terms
              </div>
              <p className="text-[13px] font-medium text-[var(--text-muted)] whitespace-pre-wrap leading-relaxed">
                {letter.terms}
              </p>
            </div>
          )}
        </div>

        {/* Acknowledgement */}
        <div className="p-6 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-col gap-4">
          <h2 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)]">
            Acknowledge receipt
          </h2>
          <textarea rows={3} className={`${inputCls} resize-y`} value={note}
            placeholder="Anything you’d like to add (optional)"
            onChange={(e) => setNote(e.target.value)} />

          {error && (
            <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
              style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
              <AlertTriangle size={15} /> {error}
            </div>
          )}

          <button onClick={acknowledge} disabled={submitting}
            className="flex items-center justify-center gap-2 px-6 py-3 rounded-xl text-white text-[12px] font-black uppercase tracking-widest disabled:opacity-50"
            style={{ backgroundColor: 'var(--accent-green)' }}>
            {submitting ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle2 size={15} />}
            I acknowledge receipt
          </button>
          {letter.validTill && (
            <p className="text-[11.5px] font-semibold text-[var(--text-muted)] text-center">
              Please acknowledge by {fmtDate(letter.validTill)}.
            </p>
          )}
        </div>
      </div>
    </div>
  );
};

export default PublicAppointment;
