import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  UserCog, ClipboardList, ScrollText, Megaphone, UserCircle,
  ClipboardCheck, ListChecks, CalendarDays, FileSignature, UserPlus, PieChart,
  BadgeCheck, Building, Target, PhoneCall, Users2, Phone, Scale,
  Inbox, Share2, ShieldCheck, Briefcase, LayoutDashboard,
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
 * -- Why the strip is grouped ---------------------------------------------------------------
 * The module runs two hiring tracks. Sparsh Magic recruits FOR a client, and Sparsh Magic
 * recruits FOR ITSELF, and the SOPs differ: only the internal track has a position
 * scorecard, a mandatory reference check and a probation; only the client track shares a CV
 * outward and waits on somebody else's verdict.
 *
 * Twenty tabs in one undifferentiated row said none of that. A recruiter could not tell
 * which of them applied to the requisition actually in front of them, and the screens that
 * exist for one track looked like screens they had forgotten to use on the other. So the
 * strip is now three labelled groups, and the breadcrumb names the group — the reader can
 * always see which track they are working in, which is the whole of that requirement.
 *
 * The grouping is presentational. It adds no route, hides nothing, and gates nothing:
 * capability filtering stays where it belongs, on the screens and the API.
 */

const GROUPS = [
  {
    key: 'both',
    label: 'Both tracks',
    // The shared spine. A candidate, an interview and an offer work the same way whoever
    // the vacancy belongs to, which is exactly why there is one HRMS and not two.
    hint: 'The shared pipeline — same screens whoever the vacancy belongs to.',
    tabs: [
      { label: 'Hiring Req',       to: '/hrms/requisitions', icon: ClipboardList },
      { label: 'Job Descriptions', to: '/hrms/jd',           icon: ScrollText },
      { label: 'Job Postings',     to: '/hrms/postings',     icon: Megaphone },
      { label: 'Candidates',       to: '/hrms/candidates',   icon: UserCircle },
      { label: 'HR Screening',     to: '/hrms/screening',    icon: ClipboardCheck },
      { label: 'Assessments',      to: '/hrms/assessments',  icon: ListChecks },
      { label: 'Interviews',       to: '/hrms/interviews',   icon: CalendarDays },
      { label: 'Offers',           to: '/hrms/offers',       icon: FileSignature },
      // Between Offers and Onboarding, which is where it sits in the real process: the
      // letter is issued after the offer is accepted and before joining.
      { label: 'Appointments',     to: '/hrms/appointments', icon: BadgeCheck },
      { label: 'Onboarding',       to: '/hrms/onboarding',   icon: UserPlus },
      { label: 'Reports',          to: '/hrms/reports',      icon: PieChart },
    ],
  },
  {
    key: 'internal',
    label: 'Internal hiring',
    hint: "Sparsh Magic's own vacancies, governed by the Internal Recruitment SOP.",
    tabs: [
      // The way in: what is waiting on whom, across every open internal position.
      { label: 'Overview',         to: '/hrms/internal-hiring', icon: LayoutDashboard },
      { label: 'Internal reqs',    to: '/hrms/internal-requisitions', icon: Building },
      { label: 'Scorecards',       to: '/hrms/scorecards',   icon: Target },
      // The telephonic screen (SOP step 5) sits between CV screening and the panel, and
      // gates interview scheduling.
      { label: 'Phone screen',     to: '/hrms/telephonic-screening', icon: Phone },
      // The shortlisting committee (SOP §5) sits between screening and the final
      // interview, and gates `Selected`.
      { label: 'Shortlisting',     to: '/hrms/shortlist-reviews', icon: Users2 },
      { label: 'References',       to: '/hrms/reference-checks', icon: PhoneCall },
      // Salary negotiation (SOP step 9) sits between the final interview and the offer.
      { label: 'Negotiation',      to: '/hrms/negotiations', icon: Scale },
    ],
  },
  {
    key: 'client',
    label: 'Client hiring',
    hint: 'Vacancies raised by a client company, filled by Sparsh Magic.',
    tabs: [
      // A request becomes a requisition, a CV goes to a client, verification gates the
      // offer. The client's OWN screens are not here: a client sees its own navigation,
      // not Sparsh's pipeline.
      { label: 'Job requests',     to: '/hrms/job-requests', icon: Inbox },
      { label: 'CV sharing',       to: '/hrms/cv-sharing',   icon: Share2 },
      { label: 'Verification',     to: '/hrms/background-checks', icon: ShieldCheck },
    ],
  },
];

// Prefix match, so a detail route under a stage keeps that stage's tab lit. Anything added
// here whose path is a PREFIX of the others — '/hrms' itself, notably — needs an exact
// match instead, or it silently claims every screen in the module.
const owns = (tab, pathname) => pathname === tab.to || pathname.startsWith(`${tab.to}/`);

const GROUP_TONE = {
  both: 'text-[var(--text-muted)]',
  internal: 'text-[var(--accent-indigo)]',
  client: 'text-[var(--accent-orange)]',
};

const HrmsWorkspaceBar = () => {
  const { pathname } = useLocation();

  let active = null;
  let activeGroup = null;
  for (const group of GROUPS) {
    const hit = group.tabs.find((t) => owns(t, pathname));
    if (hit) { active = hit; activeGroup = group; break; }
  }

  // Employee and master screens are a different job — they keep their plain page header.
  if (!active) return null;

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] px-4 sm:px-5 pt-3.5">
      <div className="flex items-center gap-3">
        <div className="h-9 w-9 rounded-xl bg-[var(--accent-indigo)] text-white grid place-items-center shrink-0">
          {activeGroup.key === 'internal' ? <Briefcase size={17} /> : <UserCog size={17} />}
        </div>
        <div className="min-w-0">
          {/* The breadcrumb names the TRACK, not just the screen. On a module that runs two
              hiring processes side by side, "which one am I in" is the question the header
              has to answer before anything else. */}
          <div className="flex items-baseline gap-1.5 flex-wrap">
            <span className="text-[17px] font-bold tracking-tight text-[var(--text-main)]">HRMS</span>
            <span className="text-[14px] text-[var(--text-muted)]">/</span>
            <span className={`text-[13px] font-bold tracking-tight ${GROUP_TONE[activeGroup.key]}`}>
              {activeGroup.label}
            </span>
            <span className="text-[14px] text-[var(--text-muted)]">/</span>
            <span className="text-[15px] font-bold tracking-tight text-[var(--accent-indigo)]">
              {active.label}
            </span>
          </div>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
            {activeGroup.hint}
          </p>
        </div>
      </div>

      {/* A rule under the identity row so the strip reads as tabs belonging to this
          workspace, rather than a row of buttons floating in a card. */}
      <nav className="mt-3 pt-2.5 pb-2.5 border-t border-[var(--border)] flex items-center gap-1 overflow-x-auto no-scrollbar">
        {GROUPS.map((group, gi) => (
          <React.Fragment key={group.key}>
            {gi > 0 && (
              <span aria-hidden="true"
                className="shrink-0 self-stretch w-px bg-[var(--border)] mx-1.5 my-0.5" />
            )}
            <span className={`shrink-0 pl-1 pr-1.5 text-[10px] font-bold uppercase
              tracking-widest ${GROUP_TONE[group.key]}`}>
              {group.label}
            </span>
            {group.tabs.map((tab) => (
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
          </React.Fragment>
        ))}
      </nav>
    </div>
  );
};

export default HrmsWorkspaceBar;
