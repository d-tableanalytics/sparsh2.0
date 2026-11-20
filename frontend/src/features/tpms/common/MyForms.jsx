import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ClipboardList, RefreshCw, ExternalLink, CheckCircle2, Clock, Ban } from 'lucide-react';
import { DashboardHero, HeroButton } from './dashboardKit';
import { getMyFormAssignments } from '../../../services/tpmsFormsApi';

/* ─────────────────────────────────────────────────────────────
   TPMS ▸ My Forms — every form link emailed to the signed-in user.

   The links normally arrive only by email; when that email is missed or lost the person had
   no way back to their form. This lists the SAME links (opened in-app at /f/<token>, the page
   the email link opens) with each one's status. The server returns only the caller's own.
   ───────────────────────────────────────────────────────────── */

const STATUS = {
  sent:      { label: 'Pending',   icon: Clock,        c: 'var(--accent-orange)', bg: 'var(--accent-yellow-bg)', bd: 'var(--accent-yellow-border)' },
  pending:   { label: 'Pending',   icon: Clock,        c: 'var(--accent-orange)', bg: 'var(--accent-yellow-bg)', bd: 'var(--accent-yellow-border)' },
  opened:    { label: 'Started',   icon: Clock,        c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  submitted: { label: 'Submitted', icon: CheckCircle2, c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  expired:   { label: 'Expired',   icon: Ban,          c: 'var(--text-muted)',    bg: 'var(--input-bg)',         bd: 'var(--border)' },
};
const statusOf = (s) => STATUS[s] || STATUS.sent;

const day = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—'
    : d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
};

const MyForms = () => {
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await getMyFormAssignments();
      setRows(data?.forms || []);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load your forms. Please try again.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const pending = useMemo(() => rows.filter((r) => r.can_open), [rows]);
  const shown = showAll ? rows : pending;

  return (
    <div className="space-y-5">
      <DashboardHero icon={ClipboardList} title="My Forms"
        subtitle="Every form sent to you by email — open and submit them here too">
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-[var(--border)]">
          <p className="text-[13px] font-bold text-[var(--text-main)]">
            {pending.length
              ? `${pending.length} form${pending.length === 1 ? '' : 's'} waiting for you`
              : 'Nothing waiting — you are all caught up'}
          </p>
          <div className="flex items-center gap-1 rounded-lg bg-[var(--input-bg)] p-1">
            {[[false, `Pending (${pending.length})`], [true, `All (${rows.length})`]].map(([all, label]) => (
              <button key={label} type="button" onClick={() => setShowAll(all)}
                className={`px-3 py-1.5 rounded-md text-[12px] font-bold transition-colors ${showAll === all
                  ? 'bg-[var(--bg-card)] text-[var(--accent-indigo)] shadow-sm'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
                {label}
              </button>
            ))}
          </div>
        </div>

        {loading && <p className="px-5 py-8 text-center text-[12.5px] font-bold text-[var(--text-muted)]">Loading your forms…</p>}
        {!loading && error && (
          <div className="px-5 py-8 text-center space-y-2">
            <p className="text-[12.5px] font-bold text-[var(--accent-red)]">{error}</p>
            <button type="button" onClick={load} className="text-[12px] font-bold text-[var(--accent-indigo)] hover:underline">Try again</button>
          </div>
        )}
        {!loading && !error && shown.length === 0 && (
          <p className="px-5 py-10 text-center text-[12.5px] font-semibold text-[var(--text-muted)]">
            {showAll ? 'No forms have been sent to you yet.' : 'No pending forms. Switch to All to see past ones.'}
          </p>
        )}

        {!loading && !error && shown.length > 0 && (
          <div className="divide-y divide-[var(--border)]">
            {shown.map((r) => {
              const st = statusOf(r.status);
              return (
                <div key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <div className="flex-1 min-w-[200px]">
                    <p className="text-[13.5px] font-black text-[var(--text-main)]">{r.form_title}</p>
                    <p className="text-[11.5px] font-semibold text-[var(--text-muted)]">
                      {[r.period_label || r.period, r.activity, r.company_name].filter(Boolean).join(' · ')}
                    </p>
                  </div>
                  <span className="text-[11.5px] text-[var(--text-muted)] w-[120px]">
                    Sent {day(r.sent_at)}
                  </span>
                  <span className="inline-flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded-full border whitespace-nowrap"
                    style={{ color: st.c, background: st.bg, borderColor: st.bd }}>
                    <st.icon size={11} /> {st.label}
                  </span>
                  <div className="w-[130px] flex justify-end">
                    {r.can_open ? (
                      <button type="button" onClick={() => navigate(r.path)}
                        className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-black hover:opacity-90">
                        <ExternalLink size={13} /> Open form
                      </button>
                    ) : (
                      <span className="text-[11.5px] font-semibold text-[var(--text-muted)]"
                        title={r.status === 'expired' ? 'The month for this form has closed, so it can no longer be filled.' : undefined}>
                        {r.status === 'submitted'
                          ? `Submitted ${r.submitted_at ? day(r.submitted_at) : ''}`.trim()
                          : r.status === 'expired' ? 'Month closed' : '—'}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default MyForms;
