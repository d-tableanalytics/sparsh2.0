import React, { useCallback, useEffect, useState } from 'react';
import { MessagesSquare, RefreshCw, Lock, CheckCircle2, X, ExternalLink, Copy } from 'lucide-react';
import { DashboardHero, HeroButton } from '../tpms/common/dashboardKit';
import { useNotification } from '../../context/NotificationContext';
import { getMyIdfForms } from '../../services/idfApi';
import { CARD, day, dayTime, monthLabel } from './idfKit';
import { StatusChip } from './IdfBits';
import IdfFeedbackForm from './IdfFeedbackForm';
import IdfYouSaid from './IdfYouSaid';

/* ─────────────────────────────────────────────────────────────
   Inter-Departmental Feedback ▸ My Feedback Forms (the department HOD) — every form of the
   open cycle for the caller's department. The emailed link opens the same form directly.
   ───────────────────────────────────────────────────────────── */

const IdfForms = () => {
  const { showSuccess, showError } = useNotification();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data: d } = await getMyIdfForms();
      setData(d);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load your feedback forms.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const copyLink = async (f) => {
    try {
      await navigator.clipboard.writeText(f.link || `${window.location.origin}${f.link_path}`);
      showSuccess(`Your form link for ${f.receiver_name} is copied.`);
    } catch {
      showError('Could not copy the link.');
    }
  };

  const forms = data?.forms || [];
  const pending = forms.filter((f) => f.status !== 'Completed').length;
  const cycle = data?.cycle;

  return (
    <div className="space-y-5">
      <DashboardHero icon={MessagesSquare} title="My Feedback Forms"
        subtitle={cycle ? `${cycle.name} · deadline ${day(cycle.deadline)}` : 'Inter-Departmental Feedback'}>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      <div className="flex items-start gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-4 py-3 text-[12.5px] text-[var(--text-muted)]">
        <Lock size={15} className="mt-0.5 shrink-0 text-[var(--accent-indigo)]" />
        <span><b className="text-[var(--text-main)]">Confidential.</b> Reports show departments, never individual raters,
          and go to the MD only. Rate how well each department supports yours — honestly and specifically.</span>
      </div>

      <div className={`${CARD} overflow-hidden`}>
        <div className="px-4 py-3 border-b border-[var(--border)] text-[13px] font-bold text-[var(--text-main)]">
          {loading ? 'Loading…' : !cycle ? 'No feedback cycle is open right now'
            : forms.length ? (pending ? `${pending} of ${forms.length} still to submit` : `All ${forms.length} submitted — thank you`)
              : 'No forms for you in this cycle'}
        </div>
        {error && <p className="px-5 py-6 text-center text-[12.5px] font-bold text-[var(--accent-red)]">{error}</p>}
        {!loading && !error && cycle && !forms.length && (
          <p className="px-5 py-8 text-center text-[12.5px] text-[var(--text-muted)]">
            {data?.is_hod ? 'Your department is not asked to give feedback in this cycle.'
              : 'Feedback is filled by the HOD of each department.'}
          </p>
        )}
        <div className="divide-y divide-[var(--border)]">
          {forms.map((f) => (
            <div key={`${f.giver_dept_id}-${f.receiver_dept_id}`} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <div className="flex-1 min-w-[220px]">
                <p className="text-[13.5px] font-black text-[var(--text-main)]">Feedback for {f.receiver_name}</p>
                <p className="text-[11.5px] text-[var(--text-muted)]">From {f.giver_name} · {monthLabel(cycle?.period)}</p>
              </div>
              <StatusChip status={f.status} />
              {f.status === 'Completed' ? (
                <span className="inline-flex items-center gap-1 text-[12px] font-bold text-[var(--accent-green)]">
                  <CheckCircle2 size={14} /> Submitted {dayTime(f.submitted_at)}
                </span>
              ) : (
                <div className="flex flex-wrap items-center gap-1.5">
                  {f.link_path && (
                    <>
                      <a href={f.link_path} target="_blank" rel="noopener noreferrer" title="Open your personal form link as a separate page"
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
                        <ExternalLink size={13} /> Open form link
                      </a>
                      <button type="button" title="Copy your form link" onClick={() => copyLink(f)}
                        className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
                        <Copy size={13} />
                      </button>
                    </>
                  )}
                  <button type="button" onClick={() => setOpen(f)}
                    className="px-3.5 py-1.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-black hover:opacity-90">
                    Give feedback
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <IdfYouSaid />

      {open && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={() => setOpen(null)}>
          <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true"
            className="w-full max-w-3xl rounded-2xl bg-[var(--bg-card)] shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-[var(--border)]">
              <div>
                <h3 className="text-[14.5px] font-black text-[var(--text-main)]">Feedback for {open.receiver_name}</h3>
                <p className="text-[11.5px] text-[var(--text-muted)]">From {open.giver_name}</p>
              </div>
              <button type="button" onClick={() => setOpen(null)} className="p-1 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]"><X size={17} /></button>
            </div>
            <div className="px-5 py-4 max-h-[72vh] overflow-y-auto">
              <IdfFeedbackForm form={open} parameters={data?.parameters}
                commentRequiredFor={data?.comment_required_for} ratingLabels={data?.rating_labels}
                onCancel={() => setOpen(null)} onSubmitted={() => { setOpen(null); load(); }} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default IdfForms;
