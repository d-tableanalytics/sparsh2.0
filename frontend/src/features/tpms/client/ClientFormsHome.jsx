import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ClipboardCheck, UserCog, Sparkles, ClipboardList, ChevronRight, LayoutGrid, Clock, CheckCircle2, RefreshCw, AlertTriangle, Inbox } from 'lucide-react';
import { DashboardHero, Section } from '../common/dashboardKit';
import { useAuth } from '../../../context/AuthContext';
import { getMyForms } from '../../../services/tpmsFormsApi';

/**
 * Client TPMS ▸ "My Forms" hub. Schedule-driven: lists the forms the current
 * respondent must fill for each active period (from getMyForms), with a status
 * pill and a deep-link that pre-fills the period on the target form.
 */

// Per form_type: icon + the route base to deep-link into.
const FORM_META = {
  accountability:          { icon: ClipboardCheck, route: '/tpms/forms/accountability' },
  ownership:               { icon: UserCog,        route: '/tpms/forms/ownership' },
  culture:                 { icon: Sparkles,       route: '/tpms/forms/culture' },
  implementation_feedback: { icon: ClipboardList,  route: '/tpms/forms/implementation-feedback' },
};

// 'YYYY-MM' → friendly label, e.g. "July 2026".
const periodLabel = (period) => {
  const m = /^(\d{4})-(\d{2})$/.exec((period || '').trim());
  if (!m) return period || '';
  const d = new Date(Number(m[1]), Number(m[2]) - 1, 1);
  return d.toLocaleString('en-US', { month: 'long', year: 'numeric' });
};

const StatusPill = ({ status }) => {
  const submitted = status === 'submitted';
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[10.5px] font-bold tracking-wide px-2.5 py-1 rounded-full border shrink-0"
      style={{
        color: submitted ? 'var(--accent-green)' : 'var(--accent-orange)',
        background: submitted ? 'var(--accent-green-bg)' : 'var(--accent-yellow-bg)',
        borderColor: submitted ? 'var(--accent-green-border)' : 'var(--accent-yellow-border)',
      }}
    >
      {submitted ? <CheckCircle2 size={12} /> : <Clock size={12} />}
      {submitted ? 'Submitted' : 'To fill'}
    </span>
  );
};

const ClientFormsHome = () => {
  const { user } = useAuth();

  const [forms, setForms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const res = await getMyForms();
        if (!alive) return;
        setForms(res.data?.forms || []);
      } catch (err) {
        if (alive) setError(err.response?.data?.detail || 'Failed to load your forms');
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  // Pending first, then by period (newest first) for a stable, useful order.
  const sorted = [...forms].sort((a, b) => {
    const rank = (f) => (f.status === 'submitted' ? 1 : 0);
    if (rank(a) !== rank(b)) return rank(a) - rank(b);
    return String(b.period || '').localeCompare(String(a.period || ''));
  });

  const pendingCount = forms.filter((f) => f.status !== 'submitted').length;
  const subtitle = loading
    ? 'Loading your assigned forms…'
    : pendingCount > 0
      ? `${pendingCount} form${pendingCount === 1 ? '' : 's'} waiting to be filled.`
      : 'You are all caught up.';

  return (
    <div className="space-y-5">
      <DashboardHero
        icon={LayoutGrid}
        title="My Forms"
        highlight={user?.full_name}
        subtitle={subtitle}
      />

      <Section title="Assigned Forms" icon={ClipboardCheck}>
        {loading && (
          <div className="px-5 py-14 flex items-center justify-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
            <RefreshCw size={15} className="animate-spin" /> Loading…
          </div>
        )}

        {!loading && error && (
          <div className="px-5 py-14 flex flex-col items-center gap-2 text-center">
            <AlertTriangle size={22} className="text-[var(--accent-red)]" />
            <p className="text-[13px] font-bold text-[var(--accent-red)]">{error}</p>
          </div>
        )}

        {!loading && !error && sorted.length === 0 && (
          <div className="px-5 py-14 flex flex-col items-center gap-2 text-center">
            <Inbox size={24} className="text-[var(--text-muted)]" />
            <p className="text-[13px] font-semibold text-[var(--text-muted)]">No forms assigned for you right now.</p>
          </div>
        )}

        {!loading && !error && sorted.length > 0 && (
          <div className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
            {sorted.map((f, i) => {
              const meta = FORM_META[f.form_type] || { icon: ClipboardList, route: '/tpms/forms' };
              const Icon = meta.icon;
              const to = `${meta.route}?period=${encodeURIComponent(f.period || '')}`;
              return (
                <Link
                  key={`${f.form_type}-${f.period || i}`}
                  to={to}
                  className="group flex items-start gap-4 p-4 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] hover:border-[var(--accent-indigo)] hover:shadow-sm transition-all"
                >
                  <div className="w-11 h-11 rounded-xl flex items-center justify-center text-white shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                    <Icon size={20} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="text-[14px] font-bold tracking-tight truncate">{f.title || f.form_type}</h3>
                      <StatusPill status={f.status} />
                    </div>
                    {f.activity && <p className="text-[12px] text-[var(--text-muted)] mt-1 truncate">{f.activity}</p>}
                    <div className="flex items-center justify-between gap-2 mt-2">
                      <span className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-[var(--accent-indigo)]">
                        <Clock size={12} /> {periodLabel(f.period)}
                      </span>
                      <ChevronRight size={16} className="text-[var(--text-muted)] group-hover:text-[var(--accent-indigo)] group-hover:translate-x-0.5 transition-all shrink-0" />
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </Section>
    </div>
  );
};

export default ClientFormsHome;
