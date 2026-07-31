import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Users, Briefcase, CalendarCheck, Wallet, Building2, UserPlus,
  ShieldCheck, Loader2, AlertTriangle,
} from 'lucide-react';
import { getHrmsMeta } from '../../services/hrmsApi';

// HRMS landing screen. Phase 0 (foundation) — the module gate, the permission probe and the
// shell every later phase hangs off. It reports what the BACKEND says this user may do rather
// than deriving it from role names locally, so a role rename can never silently open a section.
//
// The section cards below are the roadmap made visible: each becomes a live page as its phase
// lands (docs/HRMS_REPLICATION_ROADMAP.md).

const SECTIONS = [
  { key: 'employees', label: 'Employees', icon: Users, module: 'hrms',
    blurb: 'Directory, profiles, lifecycle and history', phase: 1 },
  { key: 'org', label: 'Organization', icon: Building2, module: 'hrms',
    blurb: 'Departments, designations, locations, reporting lines', phase: 1 },
  { key: 'attendance', label: 'Attendance', icon: CalendarCheck, module: 'attendance',
    blurb: 'Punch in/out, team view, holidays', phase: 2 },
  { key: 'leave', label: 'Leave', icon: ShieldCheck, module: 'attendance',
    blurb: 'Applications, approvals, balances', phase: 3 },
  { key: 'payroll', label: 'Payroll', icon: Wallet, module: 'payroll',
    blurb: 'Monthly runs, payslips, deductions', phase: 4 },
  { key: 'recruitment', label: 'Recruitment', icon: Briefcase, module: 'recruitment',
    blurb: 'Requisitions, job descriptions, approvals', phase: 5 },
  { key: 'candidates', label: 'Candidates', icon: UserPlus, module: 'recruitment',
    blurb: 'Postings, screening, assessments, interviews', phase: 6 },
];

const StatusPill = ({ granted }) => (
  <span
    className="px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest border"
    style={
      granted
        ? { color: 'var(--status-active-text)', backgroundColor: 'var(--status-active-bg)', borderColor: 'var(--status-active-border)' }
        : { color: 'var(--text-muted)', backgroundColor: 'var(--input-bg)', borderColor: 'var(--border)' }
    }
  >
    {granted ? 'Granted' : 'No access'}
  </span>
);

const HrmsDashboard = () => {
  // Access comes from the backend (/hrms/meta), never from local role names — see hrmsApi.js.
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await getHrmsMeta();
        if (alive) setMeta(res.data);
      } catch (err) {
        if (alive) setError(err.response?.data?.detail || 'Failed to load HRMS access');
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  const canRead = (module) => !!meta?.permissions?.[module]?.read;

  return (
    <div className="p-6 sm:p-8 flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <span className="text-[10px] font-black uppercase tracking-[0.2em] text-[var(--text-muted)]">
            Human Resource Management
          </span>
          <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-[var(--text-main)] mt-1">
            HRMS
          </h1>
          <p className="text-[13px] font-semibold text-[var(--text-muted)] mt-1 max-w-xl">
            Sparsh internal workforce — employees, attendance, leave, payroll and recruitment.
          </p>
        </div>
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)]">
          <ShieldCheck size={16} className="text-[var(--accent-indigo)]" />
          <span className="text-[11px] font-black uppercase tracking-widest text-[var(--accent-indigo)]">
            {meta?.is_superadmin ? 'Super Admin' : 'Internal Staff'}
          </span>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
          style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2.5 py-16 justify-center text-[var(--text-muted)]">
          <Loader2 size={18} className="animate-spin" />
          <span className="text-[13px] font-bold">Loading HRMS…</span>
        </div>
      ) : (
        <>
          {/* Sections */}
          <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
            {SECTIONS.map((s, i) => {
              const granted = canRead(s.module);
              return (
                <motion.div
                  key={s.key}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.04 }}
                  className="p-5 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex flex-col gap-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
                      <s.icon size={19} />
                    </div>
                    <StatusPill granted={granted} />
                  </div>
                  <div>
                    <h3 className="text-[14px] font-black text-[var(--text-main)] tracking-tight">{s.label}</h3>
                    <p className="text-[12px] font-medium text-[var(--text-muted)] mt-0.5">{s.blurb}</p>
                  </div>
                  <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] mt-auto">
                    Phase {s.phase}
                  </span>
                </motion.div>
              );
            })}
          </div>

          {/* Foundation notice — replaced by real KPIs in Phase 9. */}
          <div className="p-5 rounded-2xl border border-dashed border-[var(--border)] bg-[var(--input-bg)]">
            <h3 className="text-[13px] font-black text-[var(--text-main)] tracking-tight">Foundation is live</h3>
            <p className="text-[12px] font-medium text-[var(--text-muted)] mt-1 max-w-2xl">
              The module gate, permissions and routing are in place. Sections light up as their
              phase is built — Employees and Organization come first, then Attendance, Leave and
              Payroll, then Recruitment.
            </p>
          </div>
        </>
      )}
    </div>
  );
};

export default HrmsDashboard;
