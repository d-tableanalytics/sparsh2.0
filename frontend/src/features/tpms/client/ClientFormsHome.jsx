import React from 'react';
import { Link } from 'react-router-dom';
import { ClipboardCheck, UserCog, Sparkles, ClipboardList, ChevronRight, LayoutGrid } from 'lucide-react';
import { DashboardHero } from '../common/dashboardKit';
import { useAuth } from '../../../context/AuthContext';

/**
 * Client TPMS ▸ Forms hub. Lists the forms the current user may fill:
 *   • HOD-only     → Accountability, Ownership (rate their team)
 *   • Everyone     → Culture (self-rating), Implementation Update Feedback
 */
const FORMS = [
  { key: 'accountability',        to: 'accountability',          title: 'Accountability Rating',       desc: 'Rate each of your team members on accountability (0–5).', icon: ClipboardCheck, hodOnly: true },
  { key: 'ownership',             to: 'ownership',               title: 'Ownership Rating',            desc: 'Rate each of your team members on ownership (0–5).',      icon: UserCog,        hodOnly: true },
  { key: 'culture',               to: 'culture',                 title: 'Culture Rating',              desc: 'Rate yourself on the culture criteria (0–5).',           icon: Sparkles,       hodOnly: false },
  { key: 'implementation_feedback', to: 'implementation-feedback', title: 'Implementation Update Feedback', desc: 'Answer the monthly implementation questions (Yes/No).', icon: ClipboardList,  hodOnly: false },
];

const ClientFormsHome = () => {
  const { user } = useAuth();
  const isHod = (user?.department || '').trim().toLowerCase() === 'hod';
  const visible = FORMS.filter((f) => !f.hodOnly || isHod);

  return (
    <div className="space-y-5">
      <DashboardHero
        icon={LayoutGrid}
        title="TPMS Forms"
        highlight={user?.full_name}
        subtitle="Select a form to fill in for the current period."
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {visible.map((f) => (
          <Link
            key={f.key}
            to={f.to}
            className="group flex items-start gap-4 p-5 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] hover:border-[var(--accent-indigo)] hover:shadow-sm transition-all"
          >
            <div className="w-11 h-11 rounded-xl flex items-center justify-center text-white shrink-0" style={{ background: 'var(--avatar-bg)' }}>
              <f.icon size={20} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-[14.5px] font-bold tracking-tight">{f.title}</h3>
                <ChevronRight size={16} className="text-[var(--text-muted)] group-hover:text-[var(--accent-indigo)] group-hover:translate-x-0.5 transition-all shrink-0" />
              </div>
              <p className="text-[12.5px] text-[var(--text-muted)] mt-1">{f.desc}</p>
              {f.hodOnly && <span className="inline-block mt-2 text-[9.5px] font-bold uppercase tracking-widest text-[var(--accent-indigo)]">HOD</span>}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
};

export default ClientFormsHome;
