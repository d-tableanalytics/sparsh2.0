import React from 'react';
import { STATUS_TONE, labelCls, initials } from './hrmsStyles';

// Presentational pieces shared across the HRMS screens, so every page renders a status badge /
// avatar / stat tile identically — the reference project repeats these per page and they drift.
//
// Components only: styles, formatters and constants live in hrmsStyles.js, because a module
// exporting both components and plain values breaks React Fast Refresh.

export const StatusBadge = ({ status }) => {
  const tone = STATUS_TONE[status] || STATUS_TONE.Active;
  return (
    <span
      className="inline-block px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest border whitespace-nowrap"
      style={{ color: tone.text, backgroundColor: tone.bg, borderColor: tone.border }}
    >
      {status || 'Active'}
    </span>
  );
};

export const Avatar = ({ name, photoUrl, size = 36 }) => {
  if (photoUrl) {
    return (
      <img
        src={photoUrl}
        alt={name || 'Employee'}
        className="rounded-xl object-cover border border-[var(--border)]"
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <span
      className="rounded-xl flex items-center justify-center font-black text-white shrink-0"
      style={{ width: size, height: size, background: 'var(--avatar-bg)', fontSize: size * 0.34 }}
    >
      {initials(name)}
    </span>
  );
};

export const StatTile = ({ icon: Icon, label, value, loading }) => (
  <div className="p-4 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm flex items-center gap-3.5">
    <span className="w-10 h-10 rounded-xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shrink-0">
      <Icon size={18} />
    </span>
    <div className="min-w-0">
      {/* tabular-nums keeps the tiles from jittering as counts change width. */}
      <div
        className="text-xl font-black text-[var(--text-main)] leading-none"
        style={{ fontVariantNumeric: 'tabular-nums' }}
      >
        {loading ? '—' : value}
      </div>
      <div className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] mt-1 truncate">
        {label}
      </div>
    </div>
  </div>
);

export const Field = ({ label, required, children, className = '' }) => (
  <label className={`flex flex-col gap-1.5 ${className}`}>
    <span className={labelCls}>
      {label}
      {required && <span className="text-[var(--accent-red)]"> *</span>}
    </span>
    {children}
  </label>
);
