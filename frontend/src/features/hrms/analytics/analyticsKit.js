// HRMS ▸ analytics layout constants and pure helpers.
//
// Deliberately a .js file with NO components, exactly like components/reports/chartKit.js.
// Keeping constants and components in one module trips react-refresh/only-export-components
// and, more to the point, means a styling tweak invalidates the component module too.

export const GRID_KPI = 'grid grid-cols-2 lg:grid-cols-4 gap-3';
export const GRID_TWO = 'grid grid-cols-1 lg:grid-cols-2 gap-4';

export const CARD =
  'rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4';

export const SECTION_TITLE =
  'text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]';

/** Indian-format thousands separators; anything non-numeric renders as an em dash rather
 *  than "undefined" or a bare 0, which would read as a real measurement. */
export const nf = (n) => (typeof n === 'number' ? n.toLocaleString('en-IN') : '—');
