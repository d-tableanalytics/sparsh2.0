import React from 'react';
import { Building2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';

/**
 * HRMS ▸ company scope selector.
 *
 * Internal Sparsh staff administer HRMS across clients, so every employee screen needs to
 * know which company it is looking at. Client-side users are pinned server-side and see a
 * static label instead of a control — showing them a disabled dropdown would imply a choice
 * they do not have.
 *
 * -- Why the single-company case is LABELLED, not bare -------------------------------------
 * With one company there is no choice to make, so this used to render the name on its own.
 * Beside the module-off banner that read as a contradiction: "HRMS is switched off for all
 * companies", and directly under it, "People to Process" — which looks like a claim that
 * this one is on.
 *
 * It is not. It answers a different question: WHOSE data these screens are showing. The two
 * only conflict if the second one forgets to say what it is, so it says so. This matters
 * most in exactly the state that exposed it: when nothing is enabled the server picks the
 * scope for you (the company that holds the HRMS records), and being told which one it
 * picked is the whole point.
 */
const HrmsScopeBar = () => {
  const { companies, companyId, setCompanyId, canSwitchCompany, isInternal } = useHrms();

  if (!isInternal || companies.length === 0) return null;

  if (!canSwitchCompany) {
    const only = companies[0];
    // A chip rather than bare text: it sits beside a solid primary button, and unframed
    // text next to one reads as a stray label instead of the scope the screen is showing.
    return (
      <div className="h-10 px-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] flex items-center gap-2 text-[12px]">
        <Building2 size={14} className="text-[var(--text-muted)] shrink-0" />
        {/* The word "Company" is doing real work: without it the name alone reads as a
            status rather than a scope. Matches the visible CLIENT label these screens
            already use for their other selector. */}
        <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] shrink-0">
          Company
        </span>
        <span className="font-bold text-[var(--text-main)] truncate max-w-[180px]">{only?.name}</span>
      </div>
    );
  }

  return (
    <label className="flex items-center gap-2">
      <Building2 size={14} className="text-[var(--text-muted)]" />
      <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
        Company
      </span>
      <select
        value={companyId || ''}
        onChange={(e) => setCompanyId(e.target.value)}
        className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)] max-w-[220px]"
      >
        {companies.map((c) => (
          <option key={c.id} value={c.id}>{c.name}</option>
        ))}
      </select>
    </label>
  );
};

export default HrmsScopeBar;
