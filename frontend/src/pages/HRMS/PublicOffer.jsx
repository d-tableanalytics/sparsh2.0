import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  BadgeCheck, Loader2, CheckCircle2, AlertTriangle,
  Building2, MapPin, CalendarDays, Wallet, Briefcase, Hourglass, ShieldCheck,
} from 'lucide-react';
import { getPublicOffer, respondPublicOffer } from '../../services/hrmsApi';
import { inputCls, fmtDate } from '../../components/hrms/hrmsStyles';

// PUBLIC — no authentication. The candidate reaches this with a one-time offer code, so the
// page is rendered outside the app shell (no sidebar, no nav): the visitor is a job candidate,
// not a Sparsh user.
//
// The server is state-gated. Once accepted or declined the link returns 409 rather than letting
// the answer be rewritten, so a reload after responding shows a clear "already responded" state
// instead of an offer that appears re-answerable.

// Indian HRMS (PAN / Aadhaar / IFSC on the onboarding side), so CTC reads as INR.
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

const PublicOffer = () => {
  const { code } = useParams();

  const [offer, setOffer] = useState(null);
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');          // the server's thank-you message
  const [alreadyDone, setAlreadyDone] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await getPublicOffer(code);
      setOffer(res.data);
    } catch (err) {
      // 409 means it was already accepted/declined — a distinct, reassuring state.
      if (err.response?.status === 409) setAlreadyDone(true);
      else setError(err.response?.data?.detail || 'This link is not valid.');
    } finally {
      setLoading(false);
    }
  }, [code]);

  useEffect(() => { load(); }, [load]);

  const respond = async (accept) => {
    setError('');
    setSubmitting(true);
    try {
      const res = await respondPublicOffer(code, { accept, note });
      setDone(res.data?.message || 'Thank you. Your response has been recorded.');
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
        title="Response recorded"
        body={done}
      />
    );
  }

  if (alreadyDone) {
    return (
      <Centered
        tone={{ bg: 'var(--status-active-bg)', fg: 'var(--status-active-text)' }}
        Icon={CheckCircle2}
        title="Already responded"
        body="You have already responded to this offer, so the link can’t be opened again."
      />
    );
  }

  if (!offer) {
    return (
      <Centered
        tone={{ bg: 'var(--accent-red-bg)', fg: 'var(--accent-red)' }}
        Icon={AlertTriangle}
        title="This link isn’t available"
        body={error || 'The offer may have expired or the link may be incorrect.'}
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
              <BadgeCheck size={20} />
            </span>
            <div>
              <h1 className="text-xl font-black tracking-tight text-[var(--text-main)] leading-tight">
                Your offer of employment
              </h1>
              <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
                Hello {offer.candidateName}
              </p>
            </div>
          </div>
          <p className="text-[13px] font-medium text-[var(--text-muted)] mt-4 leading-relaxed">
            We’re delighted to extend the following offer. Please review the details and let us
            know your decision below.
          </p>
        </div>

        {/* Offer details */}
        <div className="p-6 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
          <h2 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-4">
            Offer details
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <Detail icon={Briefcase} label="Designation" value={offer.designation} />
            <Detail icon={Building2} label="Department" value={offer.department} />
            <Detail icon={Wallet} label="Annual CTC" value={fmtCtc(offer.annualCtc)} />
            <Detail icon={CalendarDays} label="Joining date" value={fmtDate(offer.joiningDate)} />
            <Detail icon={MapPin} label="Location" value={offer.location} />
            <Detail icon={ShieldCheck} label="Employment type" value={offer.employmentType} />
            <Detail
              icon={Hourglass}
              label="Probation"
              value={offer.probationMonths != null && offer.probationMonths !== ''
                ? `${offer.probationMonths} month${Number(offer.probationMonths) === 1 ? '' : 's'}`
                : '—'}
            />
            <Detail icon={CalendarDays} label="Valid till" value={fmtDate(offer.validTill)} />
          </div>

          {offer.notes && (
            <div className="mt-5">
              <h3 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-1.5">
                Notes
              </h3>
              <p className="text-[13px] font-medium text-[var(--text-muted)] whitespace-pre-wrap leading-relaxed">
                {offer.notes}
              </p>
            </div>
          )}
        </div>

        {/* Response */}
        <div className="p-6 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-col gap-4">
          <h2 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)]">
            Your response
          </h2>

          {error && (
            <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
              style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
              <AlertTriangle size={15} /> {error}
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
              Anything you’d like to add (optional)
            </span>
            <textarea rows={3} className={`${inputCls} resize-y`} value={note}
              onChange={(e) => setNote(e.target.value)} />
          </div>

          <p className="text-[11.5px] font-bold text-[var(--text-muted)]">
            You can respond once, so please review the details before deciding.
          </p>

          <div className="flex flex-col sm:flex-row gap-3">
            <button type="button" disabled={submitting} onClick={() => respond(true)}
              className="flex-1 flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-[var(--btn-primary)] text-white text-[12px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.99] disabled:opacity-50 transition-all">
              {submitting && <Loader2 size={15} className="animate-spin" />}
              Accept offer
            </button>
            <button type="button" disabled={submitting} onClick={() => respond(false)}
              className="flex-1 flex items-center justify-center gap-2 px-6 py-3 rounded-xl border text-[12px] font-black uppercase tracking-widest active:scale-[0.99] disabled:opacity-50 transition-all"
              style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
              Decline
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default PublicOffer;
