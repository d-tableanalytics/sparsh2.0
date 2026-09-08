import React from 'react';
import { Link } from 'react-router-dom';
import { PowerOff, ArrowRight } from 'lucide-react';
import { useAuth } from '../../../context/AuthContext';
import { useHrms } from '../HrmsContext';
import { canToggleHrms } from '../access';

/**
 * HRMS ▸ the module-off states, for internal staff.
 *
 * HRMS is opt-in per company (`companies.hrms_enabled`), and `company_id` is the tenant
 * boundary every endpoint scopes by. Internal staff are deliberately NOT gated by that
 * toggle — they administer the module and support it across clients, so
 * `ensure_hrms_enabled` returns early for them.
 *
 * The company SELECTOR used to be filtered by the toggle anyway, which meant switching
 * HRMS off everywhere put internal staff inside a module with an empty dropdown, and every
 * screen answered `400 — Select a company to work with`. An error telling you to pick from
 * a list that had nothing in it.
 *
 * The server now hands internal staff the companies that actually hold HRMS records when
 * none is enabled, so Sparsh Magic's own hiring keeps working with the module switched off.
 * This component handles the two states that leaves:
 *
 *   1. Every company switched off — a one-line banner. The screens function normally for
 *      internal staff, so this is a statement of fact, not an error; what it is really
 *      there for is the thing that IS off and is invisible from here, namely that no
 *      company's own users -- employees or client contacts -- can reach HRMS at all.
 *
 *   2. No company at all — nothing enabled AND no HRMS records anywhere. A genuinely empty
 *      module, which needs explaining rather than 400ing on every screen.
 *
 * -- The mental model this has to correct ---------------------------------------------------
 * The companies list is mostly CLIENT organisations, so "switch HRMS off for the companies"
 * reads like a client-side decision. It is not, for one of them: Sparsh Magic's own company
 * is in that same list and is the tenant that owns every HRMS record, on both tracks. An
 * internal requisition is a row in the operator's own database with `client_id = null` —
 * internal hiring is not a system that exists outside the companies list. That is exactly
 * why the fallback above is needed: without it, switching the clients off takes Sparsh's own
 * hiring down with them, which is never what anybody meant to do.
 */

/**
 * The banner names no company, and says "all", because it can only ever appear when NO
 * company has the module on: the selector lists enabled companies when there are any, so a
 * single one being on is enough for this never to render. Naming the company it happened to
 * fall back to was both narrower than the truth and implied the others might be on.
 */
const Banner = ({ mayToggle }) => (
  <div
    role="status"
    className="mb-3 rounded-xl border border-[var(--accent-orange)]/40
               bg-[var(--accent-orange-bg)] px-4 py-3 flex flex-wrap items-center gap-3"
  >
    <PowerOff size={16} className="text-[var(--accent-orange)] shrink-0" />
    <p className="min-w-0 flex-1 text-[12.5px] font-bold text-[var(--text-main)]">
      HRMS is switched off for all companies
    </p>
    {mayToggle && (
      <Link
        to="/companies"
        className="shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-lg
                   border border-[var(--accent-orange)]/50 text-[11.5px] font-bold
                   text-[var(--accent-orange)]"
      >
        Switch on <ArrowRight size={13} />
      </Link>
    )}
  </div>
);

const HrmsScopeGuard = ({ children }) => {
  const { user } = useAuth();
  const {
    loading, error, isInternal, companyId, companies, moduleEnabledHere,
  } = useHrms();

  // While the answer is still arriving, let the screens render their own loading states —
  // flashing a banner and then removing it would be worse than a moment of nothing.
  if (loading) return children;

  // A hard failure (403, network) is the provider's to report; it already sets `error` and
  // the route guard handles a revoked toggle. This component is only about the module-off
  // states, which are not errors.
  if (error) return children;

  // Client-side users are pinned to their own company by the server and never see a
  // selector. If their tenant has the module off they are refused at the door with a 403 —
  // a different message, in a different place, and correctly so.
  if (!isInternal) return children;

  const mayToggle = canToggleHrms(user);

  if (!companyId && companies.length === 0) {
    return (
      <div className="py-14 px-4 flex flex-col items-center text-center">
        <div className="h-12 w-12 rounded-2xl bg-[var(--accent-orange-bg)]
                        text-[var(--accent-orange)] grid place-items-center">
          <PowerOff size={22} />
        </div>
        <h1 className="mt-4 text-[17px] font-bold tracking-tight text-[var(--text-main)]">
          There is no company to work in yet
        </h1>
        <p className="mt-2 max-w-xl text-[13px] text-[var(--text-muted)]">
          No company has HRMS switched on, and none holds any HRMS records — so there is
          nothing for these screens to open. Switch the module on for the company that will
          run your recruitment, and both hiring tracks become available in it.
        </p>
        {mayToggle ? (
          <Link
            to="/companies"
            className="mt-5 inline-flex items-center gap-1.5 h-9 px-4 rounded-lg
                       bg-[var(--accent-indigo)] text-white text-[12px] font-bold"
          >
            Open Companies <ArrowRight size={14} />
          </Link>
        ) : (
          <p className="mt-5 text-[12px] text-[var(--text-muted)]">
            Only an Admin or Super Admin can switch the module on.
          </p>
        )}
      </div>
    );
  }

  if (!moduleEnabledHere) {
    return (
      <>
        <Banner mayToggle={mayToggle} />
        {children}
      </>
    );
  }

  return children;
};

export default HrmsScopeGuard;
