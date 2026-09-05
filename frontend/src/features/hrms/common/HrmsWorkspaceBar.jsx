import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  UserCog, ClipboardList, ScrollText, Megaphone, UserCircle,
  ClipboardCheck, ListChecks, CalendarDays, FileSignature, UserPlus, PieChart,
  BadgeCheck, Building, Target, PhoneCall, Users2, Phone, Scale,
  Inbox, Share2, ShieldCheck,
} from 'lucide-react';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';

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
 * ── Two strips, not one ──────────────────────────────────────────────────────────────────
 * A user of a client ORGANISATION gets CLIENT_TABS: raise a request, review the candidates
 * sent to them. Everyone Sparsh-side gets the pipeline.
 *
 * This is the fix for §18 of the client brief ("an error appears stating that the user
 * cannot access the required section"). There was no bug in the API — the strip simply drew
 * all twenty internal stages for every viewer, and a client clicking any of them got the
 * 403 the server is right to return. The capability list this component now filters on is
 * the SERVER's own answer (GET /hrms/health), so a tab can no longer promise a screen the
 * API will refuse.
 *
 * Filtering the strip is a UX affordance and NOT the security boundary — routes/hrms.py and
 * utils/hrms_access.py enforce the same rules independently. Hiding a tab prevents a dead
 * end; it does not prevent an attack.
 *
 * Styled entirely with the ERP's CSS variables (--accent-indigo, --border, --text-main …)
 * so it inherits light/dark theming instead of carrying its own palette.
 */

// Sparsh's pipeline. Every entry carries the capability its screen actually needs, so the
// strip and the API agree by construction rather than by somebody remembering to update
// both. `cap: null` means "anyone who can open the module".
const TABS = [
  { label: 'Hiring Req',       to: '/hrms/requisitions', icon: ClipboardList, cap: CAP.REQUISITION_READ },
  { label: 'Job Descriptions', to: '/hrms/jd',           icon: ScrollText,    cap: CAP.JD_READ },
  { label: 'Job Postings',     to: '/hrms/postings',     icon: Megaphone,     cap: CAP.POSTING_READ },
  { label: 'Candidates',       to: '/hrms/candidates',   icon: UserCircle,    cap: CAP.CANDIDATE_READ },
  { label: 'HR Screening',     to: '/hrms/screening',    icon: ClipboardCheck, cap: CAP.CANDIDATE_SCREEN },
  { label: 'Assessments',      to: '/hrms/assessments',  icon: ListChecks,    cap: CAP.ASSESSMENT_READ },
  { label: 'Interviews',       to: '/hrms/interviews',   icon: CalendarDays,  cap: CAP.INTERVIEW_READ },
  { label: 'Offers',           to: '/hrms/offers',       icon: FileSignature, cap: CAP.OFFER_READ },
  // Phase 11-R, Item 3 — between Offers and Onboarding, which is where it sits in the
  // real process: the letter is issued after the offer is accepted and before joining.
  { label: 'Appointments',     to: '/hrms/appointments', icon: BadgeCheck,    cap: CAP.APPOINTMENT_READ },
  { label: 'Onboarding',       to: '/hrms/onboarding',   icon: UserPlus,      cap: CAP.ONBOARDING_READ },
  { label: 'Reports',          to: '/hrms/reports',      icon: PieChart,      cap: CAP.REPORT_READ },
  // ── Internal track ── these three ARE hiring stages, so they belong in the strip beside
  // the others. Probation and Exceptions are governance rather than pipeline and live in
  // the sidebar instead; the two lists must stay disjoint (see Sidebar.jsx).
  { label: 'Internal reqs',    to: '/hrms/internal-requisitions', icon: Building, cap: CAP.REQUISITION_READ },
  { label: 'Scorecards',       to: '/hrms/scorecards',   icon: Target,        cap: CAP.SCORECARD_READ },
  { label: 'References',       to: '/hrms/reference-checks', icon: PhoneCall, cap: CAP.REFERENCE_READ },
  // Phase INT-2: the shortlisting committee (SOP §5). A hiring STAGE -- it sits between
  // screening and the final interview and gates `Selected` -- so it belongs in the strip.
  // Pre-boarding, the talent pool, the salary bands, the communication templates and the
  // policy register are governance and live in the sidebar; the two lists stay disjoint.
  { label: 'Shortlisting',     to: '/hrms/shortlist-reviews', icon: Users2,   cap: CAP.SHORTLIST_READ },
  // Phase INT-4: the telephonic screen (SOP step 5). A hiring STAGE -- it sits between CV
  // screening and the panel, and gates interview scheduling -- so it belongs in the strip.
  { label: 'Phone screen',     to: '/hrms/telephonic-screening', icon: Phone, cap: CAP.TELEPHONIC_READ },
  // Phase INT-10: salary negotiation (SOP step 9) sits between the final interview and the
  // offer -- a hiring stage, so it belongs in the strip.
  { label: 'Negotiation',      to: '/hrms/negotiations', icon: Scale,         cap: CAP.NEGOTIATION_READ },
  // ── Phase 12: the client hiring track ──
  // All three are hiring STAGES on the client flow (a request becomes a requisition, a CV
  // goes to a client, verification gates the offer), so they belong in the strip beside the
  // others rather than in the sidebar. The client's own screens are not here: a client sees
  // CLIENT_TABS below, not Sparsh's pipeline.
  { label: 'Job requests',     to: '/hrms/job-requests', icon: Inbox,         cap: CAP.JOB_REQUEST_REVIEW },
  { label: 'CV sharing',       to: '/hrms/cv-sharing',   icon: Share2,        cap: CAP.SHARE_WRITE },
  { label: 'Verification',     to: '/hrms/background-checks', icon: ShieldCheck, cap: CAP.BACKGROUND_READ },
];

// What a client organisation's user sees instead: the two things §14 of the brief says they
// come here to do. No internal stage, no "For Sparsh Magic" control, no other client.
//
// `Job requests` appears in both lists pointing at the same route, and that is deliberate —
// the screen serves both audiences and the SERVER decides which rows come back (see
// JobRequestBoard). What differs is the capability each side reaches it by: Sparsh reviews
// an inbox (JOB_REQUEST_REVIEW), a client tracks their own asks (JOB_REQUEST_WRITE).
const CLIENT_TABS = [
  { label: 'My hiring requests', to: '/hrms/job-requests', icon: Inbox, cap: CAP.JOB_REQUEST_WRITE },
  { label: 'Candidate review',   to: '/hrms/shared-candidates', icon: Users2, cap: CAP.SHARE_READ },
];

// Prefix match, so a detail route under a stage keeps that stage's tab lit. Anything added
// here whose path is a PREFIX of the others — '/hrms' itself, notably — needs an exact
// match instead, or it silently claims every screen in the module.
const owns = (tab, pathname) => pathname === tab.to || pathname.startsWith(`${tab.to}/`);

const HrmsWorkspaceBar = () => {
  const { pathname } = useLocation();
  const { can, isClientUser, loading } = useHrms();

  // Fails CLOSED while /hrms/health is in flight: `can()` returns false, so the strip is
  // empty rather than briefly showing tabs the answer may take away. Same rule the rest of
  // the module follows.
  const source = isClientUser ? CLIENT_TABS : TABS;
  const tabs = source.filter((t) => !t.cap || can(t.cap));
  const active = tabs.find((t) => owns(t, pathname));

  // Employee and master screens are a different job — they keep their plain page header.
  // A screen the viewer cannot reach any tab for also renders none: the page itself says
  // what went wrong, and a strip of unrelated links above it would only be noise.
  if (loading || !active) return null;

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
            {isClientUser ? 'Your hiring with Sparsh' : 'HR & Recruitment workspace'}
          </p>
        </div>
      </div>

      {/* A rule under the identity row so the strip reads as tabs belonging to this
          workspace, rather than a row of buttons floating in a card. */}
      <nav className="mt-3 pt-2.5 pb-2.5 border-t border-[var(--border)] flex items-center gap-1 overflow-x-auto no-scrollbar">
        {tabs.map((tab) => (
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
