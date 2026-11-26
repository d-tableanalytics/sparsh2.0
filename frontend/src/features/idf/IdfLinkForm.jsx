import React, { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { MessagesSquare, CheckCircle2, Ban, Lock, AlertTriangle, CalendarClock } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { openIdfLink } from '../../services/idfApi';
import { CARD, day, monthLabel } from './idfKit';
import IdfFeedbackForm from './IdfFeedbackForm';

/* ─────────────────────────────────────────────────────────────
   Inter-Departmental Feedback ▸ the form an HOD's personal link opens (/idf/f/<token>).

   A separate, full-page form — no sidebar or app menu — like a TPMS form link. The link is
   personal: the server checks it belongs to the signed-in HOD (or another HOD of the same
   department). Once submitted, or once the cycle has ended, it says so instead of a form.
   ───────────────────────────────────────────────────────────── */

const Notice = ({ icon, tone, title, children }) => {
  const Icon = icon;
  return (
    <div className={`${CARD} p-8 text-center space-y-2`}>
      <Icon size={30} className="mx-auto" style={{ color: tone }} />
      <p className="text-[15px] font-black text-[var(--text-main)]">{title}</p>
      <div className="text-[12.5px] text-[var(--text-muted)] space-y-2">{children}</div>
    </div>
  );
};

const IdfLinkForm = () => {
  const { token } = useParams();
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data: d } = await openIdfLink(token);
      setData(d);
    } catch (e) {
      setError(e?.response?.data?.detail || 'This feedback link could not be opened.');
    }
  }, [token]);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  const f = data?.form;
  const state = done ? 'submitted' : data?.state;
  const back = <Link to="/idf/forms" className="font-bold text-[var(--accent-indigo)] hover:underline">Go to My Feedback Forms</Link>;

  return (
    <div className="min-h-screen bg-[var(--bg-main)]">
      <header className="border-b border-[var(--border)] bg-[var(--bg-card)]">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]"><MessagesSquare size={18} /></span>
          <div className="flex-1 min-w-0">
            <p className="text-[14px] font-black text-[var(--text-main)] leading-tight">Inter-Departmental Feedback</p>
            <p className="text-[11px] text-[var(--text-muted)] truncate">Feedback form{user?.full_name ? ` · signed in as ${user.full_name}` : ''}</p>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-6 space-y-4">
        {f && (
          <div className={`${CARD} p-5`}>
            <p className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Feedback for</p>
            <h1 className="text-[22px] font-black text-[var(--text-main)] leading-tight">{f.receiver_name}</h1>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-[var(--text-muted)]">
              <span>From <b className="text-[var(--text-main)]">{f.giver_name}</b></span>
              <span>{monthLabel(data.cycle.period)}</span>
              <span className="inline-flex items-center gap-1"><CalendarClock size={12} /> Submit by <b className="text-[var(--text-main)]">{day(data.cycle.deadline)}</b></span>
            </div>
          </div>
        )}

        {!data && !error && <p className="py-10 text-center text-[12.5px] font-bold text-[var(--text-muted)]">Opening your feedback form…</p>}

        {error && (
          <Notice icon={AlertTriangle} tone="var(--accent-red)" title="This link can't be opened">
            <p>{error}</p>
            <p>{back}</p>
          </Notice>
        )}

        {state === 'submitted' && (
          <Notice icon={CheckCircle2} tone="var(--accent-green)" title={`Feedback for ${f?.receiver_name} has been submitted`}>
            <p>Thank you. It can no longer be changed, and your calendar activity is Completed.</p>
            <p>{back}</p>
          </Notice>
        )}

        {state === 'closed' && (
          <Notice icon={Ban} tone="var(--text-muted)" title={`This feedback cycle is ${String(data.cycle_status).toLowerCase()}`}>
            <p>The link no longer accepts feedback.</p>
          </Notice>
        )}

        {state === 'preview' && (
          <>
            <div className="flex items-start gap-2.5 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-4 py-3 text-[12.5px] font-semibold text-[var(--accent-orange)]">
              <Lock size={15} className="mt-0.5 shrink-0" />
              <span>Preview (Sparsh Admin). Only the HOD this link was sent to can fill and submit it — opening it here changes nothing.</span>
            </div>
            <div className={`${CARD} p-5 space-y-4`}>
              {(data.parameters || []).map((p, i) => (
                <div key={p.code || i} className="space-y-1.5">
                  <p className="text-[13px] font-black text-[var(--text-main)]">{i + 1}. {p.name}</p>
                  <p className="text-[12px] text-[var(--text-muted)]">{p.question.replace(/\b(the department|Department)\b/, f.receiver_name)}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(data.rating_labels || {}).map(([n, label]) => (
                      <span key={n} className="rounded-lg border border-[var(--border)] px-2.5 py-1 text-[11.5px] font-bold text-[var(--text-muted)]">{n} · {label}</span>
                    ))}
                    <span className="rounded-lg border border-dashed border-[var(--border)] px-2.5 py-1 text-[11.5px] font-bold text-[var(--text-muted)]">N/A</span>
                  </div>
                </div>
              ))}
              <p className="border-t border-dashed border-[var(--border)] pt-3 text-[12px] text-[var(--text-muted)]">
                Then: <b className="text-[var(--text-main)]">Strength</b> and <b className="text-[var(--text-main)]">Improvement</b> (mandatory);
                a comment is required for ratings {(data.comment_required_for || []).join(', ')}.
              </p>
            </div>
          </>
        )}

        {state === 'open' && (
          <>
            <div className="flex items-start gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 text-[12.5px] text-[var(--text-muted)]">
              <Lock size={15} className="mt-0.5 shrink-0 text-[var(--accent-indigo)]" />
              <span><b className="text-[var(--text-main)]">Confidential.</b> Reports show departments, never individual raters, and go to the MD only.</span>
            </div>
            <div className={`${CARD} p-5`}>
              <IdfFeedbackForm form={f} parameters={data.parameters} commentRequiredFor={data.comment_required_for}
                ratingLabels={data.rating_labels} onSubmitted={() => setDone(true)} />
            </div>
          </>
        )}
      </main>
    </div>
  );
};

export default IdfLinkForm;
