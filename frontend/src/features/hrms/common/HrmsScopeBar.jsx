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
 * Renders nothing at all when there is only one company and no choice to make.
 */
const HrmsScopeBar = () => {
  const { companies, companyId, setCompanyId, canSwitchCompany, isInternal } = useHrms();

  if (!isInternal || companies.length === 0) return null;

  if (!canSwitchCompany) {
    const only = companies[0];
    return (
      <div className="flex items-center gap-2 text-[12px] text-[var(--text-muted)]">
        <Building2 size={14} />
        <span className="font-bold text-[var(--text-main)]">{only?.name}</span>
      </div>
    );
  }

  return (
    <label className="flex items-center gap-2">
      <span className="sr-only">Company</span>
      <Building2 size={14} className="text-[var(--text-muted)]" />
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
