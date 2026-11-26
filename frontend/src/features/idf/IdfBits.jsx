import React, { useEffect, useState } from 'react';
import { BAND_STYLE, STATUS_STYLE, bandOf, pctText, FIELD } from './idfKit';
import { getCompanies } from '../../services/tpmsFormsApi';

/* Small shared components for the Inter-Departmental Feedback pages. */

export const BandChip = ({ band }) => {
  if (!band) return <span className="text-[var(--text-muted)]">—</span>;
  const s = BAND_STYLE[band];
  return (
    <span className="inline-block px-2 py-0.5 rounded-full border text-[10.5px] font-black whitespace-nowrap"
      style={{ color: s.c, background: s.bg, borderColor: s.bd }}>{band}</span>
  );
};

export const PctCell = ({ value }) => {
  const b = bandOf(value);
  return (
    <span className="font-bold tabular-nums" style={{ color: b ? BAND_STYLE[b].c : 'var(--text-muted)' }}>
      {pctText(value)}
    </span>
  );
};

export const StatusChip = ({ status }) => {
  const s = STATUS_STYLE[status] || { c: 'var(--text-muted)', bg: 'var(--input-bg)' };
  return (
    <span className="inline-block px-2 py-0.5 rounded-full text-[10.5px] font-black whitespace-nowrap"
      style={{ color: s.c, background: s.bg }}>{status}</span>
  );
};

/** Company picker for Sparsh Admin (TPS Coordinator) — everyone else acts on their own company. */
export const CompanyPicker = ({ value, onChange, className = 'w-full sm:w-80' }) => {
  const [companies, setCompanies] = useState([]);
  useEffect(() => {
    getCompanies().then(({ data }) => {
      const list = Array.isArray(data) ? data : (data?.companies || data?.items || []);
      setCompanies(list.map((c) => ({ id: String(c._id || c.id), name: c.name }))
        .sort((a, b) => (a.name || '').localeCompare(b.name || '')));
    }).catch(() => setCompanies([]));
  }, []);
  return (
    <select className={`${FIELD} ${className}`} value={value} onChange={(e) => onChange(e.target.value)} aria-label="Company">
      <option value="">Select a company…</option>
      {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
    </select>
  );
};
