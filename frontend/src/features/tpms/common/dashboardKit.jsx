import React from 'react';
import { motion } from 'framer-motion';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

/* Shared entrance transition for cards/sections — subtle fade + rise. */
const RISE = { initial: { opacity: 0, y: 10 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.28, ease: [0.4, 0, 0.2, 1] } };

/* ─────────────────────────────────────────────────────────────
   Shared ERP-grade dashboard primitives for the TPMS dashboards.
   Clean cards, icon chips, subtle shadows, refined typography —
   all colours from Sparsh tokens (theme-aware light & dark).
   ───────────────────────────────────────────────────────────── */

/** On-brand hero gradient for dashboard headers (indigo → violet). */
export const HEADER_GRADIENT = 'linear-gradient(120deg, #4f46e5 0%, #6d28d9 55%, #7c3aed 100%)';

/** Icon-chip / value tones. */
export const TILE = {
  blue:   { bg: 'var(--accent-indigo-bg)', fg: 'var(--accent-indigo)', bd: 'var(--accent-indigo-border)' },
  green:  { bg: 'var(--accent-green-bg)',  fg: 'var(--accent-green)',  bd: 'var(--accent-green-border)' },
  yellow: { bg: 'var(--accent-yellow-bg)', fg: 'var(--accent-orange)', bd: 'var(--accent-yellow-border)' },
  red:    { bg: 'var(--accent-red-bg)',    fg: 'var(--accent-red)',    bd: 'var(--accent-red-border)' },
  plain:  { bg: 'var(--input-bg)',         fg: 'var(--text-main)',     bd: 'var(--border)' },
};

export const Trend = ({ dir }) => {
  const map = {
    up:   { c: 'var(--accent-green)', bg: 'var(--accent-green-bg)', I: TrendingUp,   t: 'Up' },
    down: { c: 'var(--accent-red)',   bg: 'var(--accent-red-bg)',   I: TrendingDown, t: 'Down' },
    flat: { c: 'var(--text-muted)',   bg: 'var(--input-bg)',        I: Minus,        t: 'Flat' },
  }[dir] || {};
  const { c, bg, I, t } = map;
  return (
    <span className="inline-flex items-center gap-1 text-[10.5px] font-bold px-2 py-1 rounded-full" style={{ color: c, background: bg }}>
      <I size={12} /> {t}
    </span>
  );
};

export const StatusBadge = ({ value }) => {
  const risk = value === 'AT-RISK';
  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full border"
      style={{
        color: risk ? 'var(--accent-red)' : 'var(--accent-green)',
        background: risk ? 'var(--accent-red-bg)' : 'var(--accent-green-bg)',
        borderColor: risk ? 'var(--accent-red-border)' : 'var(--accent-green-border)',
      }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: risk ? 'var(--accent-red)' : 'var(--accent-green)' }} />
      {value}
    </span>
  );
};

export const Progress = ({ value }) => {
  const c = value >= 75 ? 'var(--accent-green)' : value >= 55 ? 'var(--accent-indigo)' : 'var(--accent-orange)';
  return (
    <div className="flex items-center gap-2 min-w-[130px]">
      <div className="h-2 flex-1 rounded-full bg-[var(--input-bg)] overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${value}%`, background: c }} />
      </div>
      <span className="text-[11px] font-bold tabular-nums" style={{ color: c }}>{value}%</span>
    </div>
  );
};

/** Fraction cell like 1/1 or 0/1 → a compact met/partial pill. */
export const Fraction = ({ v }) => {
  if (!v) return <span className="text-[var(--text-muted)]">—</span>;
  const [a, b] = v.split('/').map(Number);
  const ok = a >= b;
  const zero = a === 0;
  const c = zero ? 'var(--accent-red)' : ok ? 'var(--accent-green)' : 'var(--accent-orange)';
  const bg = zero ? 'var(--accent-red-bg)' : ok ? 'var(--accent-green-bg)' : 'var(--accent-orange-bg)';
  return (
    <span className="inline-flex items-center justify-center min-w-[34px] text-[11px] font-bold px-1.5 py-0.5 rounded-md tabular-nums" style={{ color: c, background: bg }}>{v}</span>
  );
};

/** ERP KPI stat card — icon chip + value + label + sub, with a tone accent bar. */
export const KpiTile = ({ value, label, sub, tone = 'blue', icon: Icon }) => {
  const t = TILE[tone] || TILE.plain;
  const accent = tone === 'plain' ? 'var(--text-muted)' : t.fg;
  return (
    <motion.div {...RISE} whileHover={{ y: -3 }}
      className="group relative overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-4 transition-shadow hover:shadow-md">
      {/* tone accent bar */}
      <span className="absolute inset-x-0 top-0 h-1 opacity-60 group-hover:opacity-100 transition-opacity" style={{ background: accent }} />
      <div className="flex items-start justify-between">
        {Icon && (
          <span className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: t.bg, color: t.fg }}>
            <Icon size={17} />
          </span>
        )}
      </div>
      <p className="text-[26px] font-extrabold tracking-tight leading-none tabular-nums mt-3" style={{ color: t.fg }}>{value}</p>
      <p className="text-[12.5px] font-bold mt-1.5 leading-tight">{label}</p>
      {sub && <p className="text-[10.5px] text-[var(--text-muted)] mt-0.5">{sub}</p>}
    </motion.div>
  );
};

/** ERP section card with a clean header (icon chip + title + optional action). */
export const Section = ({ title, subtitle, icon: Icon, tone = 'navy', action, children }) => {
  const chip = {
    navy:  { bg: 'var(--accent-indigo-bg)', fg: 'var(--accent-indigo)' },
    red:   { bg: 'var(--accent-red-bg)',    fg: 'var(--accent-red)' },
    green: { bg: 'var(--accent-green-bg)',  fg: 'var(--accent-green)' },
  }[tone] || { bg: 'var(--accent-indigo-bg)', fg: 'var(--accent-indigo)' };
  return (
    <motion.div {...RISE} className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-[var(--border)]">
        <div className="flex items-center gap-2.5 min-w-0">
          {Icon && (
            <span className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: chip.bg, color: chip.fg }}>
              <Icon size={16} />
            </span>
          )}
          <div className="min-w-0">
            <h3 className="text-[14px] font-extrabold tracking-tight truncate">{title}</h3>
            {subtitle && <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5 truncate">{subtitle}</p>}
          </div>
        </div>
        {action}
      </div>
      {children}
    </motion.div>
  );
};

export const Th = ({ children, align, className = '' }) => (
  <th className={`px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)] ${align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'} whitespace-nowrap ${className}`}>{children}</th>
);

export const Td = ({ children, align, className = '' }) => (
  <td className={`px-4 py-3.5 text-[12.5px] ${align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'} ${className}`}>{children}</td>
);

/** White pill <select> for the gradient hero header. */
/**
 * Options accept either plain strings (`['All OMs', 'A. Nair']`) or `{id, name}`
 * objects, so a select can submit an id while displaying a label. Mixing is fine —
 * pages backed by the API pass objects, static ones keep passing strings.
 */
const normaliseOptions = (options = []) =>
  options.map((o) => (typeof o === 'object' && o !== null
    ? { value: String(o.id ?? o.value ?? ''), label: String(o.name ?? o.label ?? o.id ?? '') }
    : { value: String(o), label: String(o) }));

export const HeaderSelect = ({ value, onChange, options }) => (
  <select value={value} onChange={(e) => onChange(e.target.value)}
    className="px-3 py-2 rounded-lg bg-white/95 text-slate-800 text-[12.5px] font-bold outline-none border border-white/30 shadow-sm hover:bg-white transition-all cursor-pointer">
    {normaliseOptions(options).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
  </select>
);

/** Plain pill <select> for in-card filter rows. */
export const FilterSelect = ({ value, onChange, options }) => (
  <select value={value} onChange={(e) => onChange(e.target.value)}
    className="px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12.5px] font-bold outline-none focus:border-[var(--accent-indigo)] cursor-pointer">
    {normaliseOptions(options).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
  </select>
);

/** Reusable table shell so every table shares the same header/zebra/hover styling. */
export const TableShell = ({ minWidth = 900, children }) => (
  <div className="overflow-x-auto no-scrollbar">
    <table className="w-full" style={{ minWidth }}>{children}</table>
  </div>
);

/** Polished gradient hero header for dashboards. `children` = filter controls. */
export const DashboardHero = ({ icon: Icon, title, highlight, subtitle, children }) => (
  <div className="rounded-2xl px-5 py-4 sm:px-6 sm:py-5 flex flex-wrap items-center justify-between gap-4 shadow-md relative overflow-hidden" style={{ background: HEADER_GRADIENT }}>
    {/* subtle light bloom */}
    <div className="absolute inset-0 pointer-events-none" style={{ backgroundImage: 'radial-gradient(circle at 88% -30%, rgba(255,255,255,0.35), transparent 45%)' }} />
    <div className="flex items-center gap-3 relative min-w-0">
      {Icon && (
        <span className="w-11 h-11 rounded-2xl bg-white/15 flex items-center justify-center text-white shrink-0 ring-1 ring-white/20">
          <Icon size={20} />
        </span>
      )}
      <div className="min-w-0">
        <h2 className="text-[18px] sm:text-[20px] font-extrabold tracking-tight text-white leading-tight truncate">
          {title}{highlight && <span className="font-medium text-white/75"> — {highlight}</span>}
        </h2>
        {subtitle && <p className="text-[12px] text-white/70 font-medium mt-0.5 truncate">{subtitle}</p>}
      </div>
    </div>
    <div className="flex flex-wrap items-center gap-2 relative">{children}</div>
  </div>
);

/** White pill action button for the hero header. */
export const HeroButton = ({ icon: Icon, children, onClick }) => (
  <button onClick={onClick} className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-white text-[var(--accent-indigo)] text-[12.5px] font-bold shadow-sm hover:bg-white/90 transition-all">
    {Icon && <Icon size={14} />} {children}
  </button>
);
