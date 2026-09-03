import React from 'react';
// Constants and pure helpers live in the .js sibling, imported from there by both this
// module and every screen. Re-exporting them here would break Fast Refresh again, which
// is the whole reason for the split -- same pairing as analytics/analyticsKit.
import { FIELD, LABEL } from './internalKit';

/**
 * HRMS ▸ internal recruitment track — shared presentation pieces.
 *
 * Five screens land in this phase and they all show the same three things: a list that has
 * to work at 375px, a status chip, and a signature field on every decision. Defining those
 * once keeps the track reading as one surface, and keeps a spacing change to one file — the
 * same reason common/HrmsStates and analytics/analyticsKit exist.
 *
 * Styled entirely with the ERP's CSS variables, so light/dark theming is inherited rather
 * than re-implemented.
 */

const TONES = {
  good: 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]',
  bad: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
  warn: 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]',
  neutral: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  accent: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
};

export const Chip = ({ children, tone = 'neutral', title }) => (
  <span
    title={title}
    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px]
      font-bold whitespace-nowrap ${TONES[tone] || TONES.neutral}`}
  >
    {children}
  </span>
);

/**
 * A responsive record list.
 *
 * Cards below `md`, a real table above it. Not a table squeezed into a phone with horizontal
 * scroll: at 375px a row of eight columns is unreadable however it is scrolled, and the
 * fields that matter differ between the two shapes anyway.
 *
 * `columns` drives the table; `renderCard` draws the small-screen version. Both read the
 * same row object, so the two can show different fields without disagreeing about the data.
 */
export const RecordList = ({ rows, columns, renderCard, keyOf, empty }) => {
  if (!rows?.length) return empty || null;
  return (
    <>
      <div className="md:hidden space-y-2.5">
        {rows.map((row) => (
          <div key={keyOf(row)}
            className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-3.5">
            {renderCard(row)}
          </div>
        ))}
      </div>

      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-[12.5px]">
          <thead>
            <tr className="text-[10.5px] font-bold uppercase tracking-widest
              text-[var(--text-muted)] border-b border-[var(--border)]">
              {columns.map((col) => (
                <th key={col.key}
                  scope="col"
                  className={`py-2 px-2 ${col.align === 'right' ? 'text-right' : 'text-left'}`}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={keyOf(row)}
                className="border-b border-[var(--border)] last:border-0
                  hover:bg-[var(--input-bg)]">
                {columns.map((col) => (
                  <td key={col.key}
                    className={`py-2.5 px-2 align-top
                      ${col.align === 'right' ? 'text-right' : 'text-left'}`}>
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
};

/**
 * The signature field every decision on this track carries.
 *
 * Server-required on scorecard approval, offer approval, probation confirmation and
 * exception decisions — an unsigned sign-off is not one. Asking here rather than after a 422
 * is an affordance; the server is still the control.
 */
export const SignatureField = ({ value, onChange, id, hint }) => (
  <div>
    <label className={LABEL} htmlFor={id}>Your name (signature) *</label>
    <input id={id} required value={value} onChange={(e) => onChange(e.target.value)}
      className={FIELD} placeholder="Type your full name" autoComplete="name" />
    <p className="mt-1 text-[11px] text-[var(--text-muted)]">
      {hint || 'This decision is recorded against your name.'}
    </p>
  </div>
);

/** A short definition list — label above value, wrapping cleanly on a phone. */
export const Facts = ({ items }) => (
  <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2.5">
    {items.filter((i) => i && i.value != null && i.value !== '').map((item) => (
      <div key={item.label} className="min-w-0">
        <dt className="text-[10.5px] font-bold uppercase tracking-widest
          text-[var(--text-muted)]">{item.label}</dt>
        <dd className="mt-0.5 text-[13px] text-[var(--text-main)] break-words">
          {item.value}
        </dd>
      </div>
    ))}
  </dl>
);

/** A modal shell. Labelled for screen readers and closable on Escape. */
export const Modal = ({ title, subtitle, onClose, children, footer, labelledBy }) => (
  <div
    className="fixed inset-0 z-[60] grid place-items-center bg-black/40 backdrop-blur-sm p-4"
    role="dialog" aria-modal="true" aria-labelledby={labelledBy}
    onKeyDown={(e) => { if (e.key === 'Escape') onClose(); }}
  >
    <div className="w-full max-w-lg max-h-[90vh] flex flex-col rounded-2xl
      border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
      <div className="px-5 py-4 border-b border-[var(--border)]">
        <h2 id={labelledBy} className="text-[15px] font-bold text-[var(--text-main)]">
          {title}
        </h2>
        {subtitle && (
          <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">{subtitle}</p>
        )}
      </div>
      <div className="p-5 space-y-3.5 overflow-y-auto">{children}</div>
      {footer && (
        <div className="flex items-center justify-end gap-2 px-5 py-4
          border-t border-[var(--border)]">
          {footer}
        </div>
      )}
    </div>
  </div>
);

export const Btn = ({ tone = 'ghost', children, ...rest }) => {
  const tones = {
    primary: 'bg-[var(--accent-indigo)] text-white',
    danger: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
    ghost: 'border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)]',
  };
  return (
    <button type="button" {...rest}
      className={`h-9 px-4 rounded-lg text-[12px] font-bold inline-flex items-center gap-1.5
        disabled:opacity-50 transition-colors ${tones[tone]}`}>
      {children}
    </button>
  );
};

