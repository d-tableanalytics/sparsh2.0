import React from 'react';

/** What an employee picker shows to somebody who can only act for themselves. */
const SelfEmployeeChip = ({ me }) => {
  if (me === undefined) {
    return <p className="text-[12px] text-[var(--text-muted)] h-9 flex items-center">Loading your record…</p>;
  }
  if (!me) {
    return (
      <p className="text-[12px] text-[var(--accent-orange)] rounded-lg bg-[var(--accent-orange-bg)] px-3 py-2">
        Your account has no employee profile yet, so this cannot be filed. Ask HR to set one up.
      </p>
    );
  }
  return (
    <div className="flex items-center rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 h-9">
      <span className="text-[13px] text-[var(--text-main)] truncate">
        You — {me.name} <span className="text-[var(--text-muted)]">({me.employee_code})</span>
      </span>
    </div>
  );
};

export default SelfEmployeeChip;
