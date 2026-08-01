import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { ClipboardList, Loader2, CheckCircle2, AlertTriangle } from 'lucide-react';
import { getPublicAssessment, submitAssessment } from '../../services/hrmsApi';
import { inputCls } from '../../components/hrms/hrmsStyles';

// PUBLIC — no authentication. The candidate reaches this with a one-time code.
//
// The server is state-gated: opening marks it Opened, and once submitted the link returns 409
// rather than allowing a rewrite. The page mirrors that plainly, so someone who reloads after
// submitting sees a clear "already submitted" rather than an empty form that appears to work.

const PublicAssessment = () => {
  const { code } = useParams();

  const [data, setData] = useState(null);
  const [answers, setAnswers] = useState([]);
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [alreadyDone, setAlreadyDone] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await getPublicAssessment(code);
      setData(res.data);
      setAnswers(new Array((res.data.questions || []).length).fill(''));
    } catch (err) {
      // 409 means it was already submitted — a distinct, reassuring state rather than an error.
      if (err.response?.status === 409) setAlreadyDone(true);
      else setError(err.response?.data?.detail || 'This link is not valid.');
    } finally {
      setLoading(false);
    }
  }, [code]);

  useEffect(() => { load(); }, [load]);

  const submit = async (e) => {
    e.preventDefault();
    if (answers.some((a) => !a.trim())) {
      setError('Please answer every question before submitting.');
      return;
    }
    setError('');
    setSubmitting(true);
    try {
      await submitAssessment(code, { answers, note });
      setDone(true);
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

  if (done || alreadyDone) {
    return (
      <Centered
        tone={{ bg: 'var(--status-active-bg)', fg: 'var(--status-active-text)' }}
        Icon={CheckCircle2}
        title={done ? 'Assessment submitted' : 'Already submitted'}
        body={done
          ? 'Thank you. Our team will review your answers and be in touch.'
          : 'This assessment has already been submitted, so it can’t be opened again.'}
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
        <div className="p-6 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
          <div className="flex items-center gap-3">
            <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              <ClipboardList size={20} />
            </span>
            <div>
              <h1 className="text-xl font-black tracking-tight text-[var(--text-main)] leading-tight">
                {data.title}
              </h1>
              <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
                Hello {data.candidateName}
              </p>
            </div>
          </div>
          {data.instructions && (
            <p className="text-[13px] font-medium text-[var(--text-muted)] mt-4 leading-relaxed">
              {data.instructions}
            </p>
          )}
          <p className="text-[11.5px] font-bold text-[var(--text-muted)] mt-3">
            You can submit once, so please review your answers before sending.
          </p>
        </div>

        <form onSubmit={submit}
          className="p-6 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-col gap-5">
          {error && (
            <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
              style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
              <AlertTriangle size={15} /> {error}
            </div>
          )}

          {(data.questions || []).map((q, i) => (
            <div key={i} className="flex flex-col gap-1.5">
              <span className="text-[13px] font-black text-[var(--text-main)]">
                {i + 1}. {q}
              </span>
              <textarea rows={4} required className={`${inputCls} resize-y`} value={answers[i] || ''}
                onChange={(e) => {
                  const next = [...answers];
                  next[i] = e.target.value;
                  setAnswers(next);
                }} />
            </div>
          ))}

          <div className="flex flex-col gap-1.5">
            <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
              Anything else
            </span>
            <textarea rows={2} className={`${inputCls} resize-y`} value={note}
              onChange={(e) => setNote(e.target.value)} />
          </div>

          <button type="submit" disabled={submitting}
            className="flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-[var(--btn-primary)] text-white text-[12px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.99] disabled:opacity-50 transition-all">
            {submitting && <Loader2 size={15} className="animate-spin" />}
            Submit assessment
          </button>
        </form>
      </div>
    </div>
  );
};

export default PublicAssessment;
