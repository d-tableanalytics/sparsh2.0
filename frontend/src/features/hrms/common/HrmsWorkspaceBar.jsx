import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  UserCog, ClipboardList, ScrollText, Megaphone, UserCircle,
  ClipboardCheck, ListChecks, CalendarDays, FileSignature, UserPlus, PieChart,
  BadgeCheck, Building, Target, PhoneCall, Users2, Phone,
} from 'lucide-react';

/**
 * HRMS ▸ workspace bar.
 *
 * The module's own chrome: identity + breadcrumb on the left, a tab strip underneath.
 * Purely navigational — every tab points at a route that already exists (see App.jsx), so
 * this is a different way to reach those screens, never a new one.
 *
 * The strip owns the hiring pipeline end to end (raise → post → screen → assess →
 * interview → offer → onboard → report); the sidebar keeps Dashboard, Employees and the
 * masters. Two places listing the same links was what this replaced, so the two lists must
 * stay disjoint — see Sidebar.jsx hrmsSubmodules.
 *
 * Styled entirely with the ERP's CSS variables (--accent-indigo, --border, --text-main …)
 * so it inherits light/dark theming instead of carrying its own palette.
 */

const TABS = [
  { label: 'Hiring Req',       to: '/hrms/requisitions', icon: ClipboardList },
  { label: 'Job Descriptions', to: '/hrms/jd',           icon: ScrollText },
  { label: 'Job Postings',     to: '/hrms/postings',     icon: Megaphone },
  { label: 'Candidates',       to: '/hrms/candidates',   icon: UserCircle },
  { label: 'HR Screening',     to: '/hrms/screening',    icon: ClipboardCheck },
  { label: 'Assessments',      to: '/hrms/assessments',  icon: ListChecks },
  { label: 'Interviews',       to: '/hrms/interviews',   icon: CalendarDays },
  { label: 'Offers',           to: '/hrms/offers',       icon: FileSignature },
  // Phase 11-R, Item 3 — between Offers and Onboarding, which is where it sits in the
  // real process: the letter is issued after the offer is accepted and before joining.
  { label: 'Appointments',     to: '/hrms/appointments', icon: BadgeCheck },
  { label: 'Onboarding',       to: '/hrms/onboarding',   icon: UserPlus },
  { label: 'Reports',          to: '/hrms/reports',      icon: PieChart },
  // ── Internal track ── these three ARE hiring stages, so they belong in the strip beside
  // the others. Probation and Exceptions are governance rather than pipeline and live in
  // the sidebar instead; the two lists must stay disjoint (see Sidebar.jsx).
  { label: 'Internal reqs',    to: '/hrms/internal-requisitions', icon: Building },
  { label: 'Scorecards',       to: '/hrms/scorecards',   icon: Target },
  { label: 'References',       to: '/hrms/reference-checks', icon: PhoneCall },
  // Phase INT-2: the shortlisting committee (SOP §5). A hiring STAGE -- it sits between
  // screening and the final interview and gates `Selected` -- so it belongs in the strip.
  // Pre-boarding, the talent pool, the salary bands, the communication templates and the
  // policy register are governance and live in the sidebar; the two lists stay disjoint.
  { label: 'Shortlisting',     to: '/hrms/shortlist-reviews', icon: Users2 },
  // Phase INT-4: the telephonic screen (SOP step 5). A hiring STAGE -- it sits between CV
  // screening and the panel, and gates interview scheduling -- so it belongs in the strip.
  { label: 'Phone screen',     to: '/hrms/telephonic-screening', icon: Phone },
];

// Prefix match, so a detail route under a stage keeps that stage's tab lit. Anything added
// here whose path is a PREFIX of the others — '/hrms' itself, notably — needs an exact
// match instead, or it silently claims every screen in the module.
const owns = (tab, pathname) => pathname === tab.to || pathname.startsWith(`${tab.to}/`);

const HrmsWorkspaceBar = () => {
  const { pathname } = useLocation();
  const active = TABS.find((t) => owns(t, pathname));

  // Employee and master screens are a different job — they keep their plain page header.
  if (!active) return null;

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] px-4 sm:px-5 pt-3.5">
      <div className="flex items-center gap-3">
        <div className="h-9 w-9 rounded-xl bg-[var(--accent-indigo)] text-white grid place-items-center shrink-0">
          <UserCog size={17} />
        </div>
        <div className="min-w-0">
          <div className="flex items-baseline gap-1.5 flex-wrap">
            <span className="text-[17px] font-bold tracking-tight text-[var(--text-main)]">HRMS</span>
            <span className="text-[14px] text-[var(--text-muted)]">/</span>
            <span className="text-[15px] font-bold tracking-tight text-[var(--accent-indigo)]">
              {active.label}
            </span>
          </div>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
            HR &amp; Recruitment workspace
          </p>
        </div>
      </div>

      {/* A rule under the identity row so the strip reads as tabs belonging to this
          workspace, rather than a row of buttons floating in a card. */}
      <nav className="mt-3 pt-2.5 pb-2.5 border-t border-[var(--border)] flex items-center gap-1 overflow-x-auto no-scrollbar">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) => `
              shrink-0 h-8 px-3.5 rounded-full flex items-center gap-1.5 text-[12px]
              font-bold tracking-tight transition-colors whitespace-nowrap
              ${isActive
                ? 'bg-[var(--accent-indigo)] text-white shadow-sm'
                : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}
            `}
          >
            <tab.icon size={13} />
            {tab.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
};

export default HrmsWorkspaceBar;
