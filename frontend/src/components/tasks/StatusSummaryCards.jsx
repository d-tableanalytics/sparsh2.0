import React from 'react';
import { motion } from 'framer-motion';

// Dot + uppercase-label + big colored number card, matching the reference design.
// `cardOrder` is an array of [responseKey, config] pairs from statusConfig.js.
const StatusSummaryCards = ({ cardOrder, summary, activeKey, onSelect, columnsClass }) => (
  <div className={columnsClass || 'grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-9 gap-3'}>
    {cardOrder.map(([key, cfg]) => {
      const isActive = activeKey === key;
      const selectable = !!onSelect;
      const Wrapper = selectable ? motion.button : motion.div;
      return (
        <Wrapper
          key={key}
          type={selectable ? 'button' : undefined}
          onClick={selectable ? () => onSelect(isActive ? null : key) : undefined}
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          className={`text-left bg-[var(--bg-card)] px-4 py-3 rounded-2xl border transition-all ${selectable ? 'hover:shadow-md cursor-pointer' : ''}`}
          style={{ borderColor: isActive ? cfg.color : 'var(--border)', borderWidth: isActive ? 2 : 1 }}
        >
          <div className="flex items-center gap-1.5 mb-1.5">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ background: cfg.color }} />
            <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider truncate">{cfg.shortLabel || cfg.label}</span>
          </div>
          <p className="text-2xl font-black" style={{ color: cfg.color }}>{summary ? (summary[key] ?? 0) : '—'}</p>
        </Wrapper>
      );
    })}
  </div>
);

export default StatusSummaryCards;
