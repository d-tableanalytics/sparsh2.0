import React from 'react';
import { Layers } from 'lucide-react';

const pct = (count, total) => (total === 0 ? 0 : Math.round((count / total) * 100));

// Per-employee task breakdown, matching the reference screenshot's nested header:
// Employee Name | Total | NOT COMPLETED (Overdue, Pending, In-Progress) | COMPLETED (In Time, Delayed).
const EmployeeBreakdownTable = ({ tasks, members, userMap }) => {
  const rows = members.map(id => {
    const memberTasks = tasks.filter(t => (t.assignedTo || []).includes(id));
    const total = memberTasks.length;
    const overdue = memberTasks.filter(t => t.isOverdue).length;
    const pending = memberTasks.filter(t => t.status === 'pending').length;
    const inProgress = memberTasks.filter(t => t.status === 'in_progress').length;
    const inTime = memberTasks.filter(t => t.completionTiming === 'in_time').length;
    const delayed = memberTasks.filter(t => t.completionTiming === 'delayed').length;
    return { id, name: userMap[id] || id, total, overdue, pending, inProgress, inTime, delayed };
  });

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-left min-w-[720px]">
          <thead>
            <tr className="border-b border-[var(--border)]">
              <th rowSpan={2} className="px-5 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest align-bottom">Employee Name</th>
              <th rowSpan={2} className="px-5 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest align-bottom">Total</th>
              <th colSpan={3} className="px-5 py-2 text-[10px] font-black text-[var(--accent-red)] uppercase tracking-widest text-center border-l border-[var(--border)]">Not Completed</th>
              <th colSpan={2} className="px-5 py-2 text-[10px] font-black text-[var(--accent-green)] uppercase tracking-widest text-center border-l border-[var(--border)]">Completed</th>
            </tr>
            <tr className="border-b border-[var(--border)]">
              <th className="px-4 py-2 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider text-center border-l border-[var(--border)]">Overdue</th>
              <th className="px-4 py-2 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider text-center">Pending</th>
              <th className="px-4 py-2 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider text-center">In-Progress</th>
              <th className="px-4 py-2 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider text-center border-l border-[var(--border)]">In Time</th>
              <th className="px-4 py-2 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider text-center">Delayed</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-5 py-10 text-center text-[12px] font-bold text-[var(--text-muted)]">
                  <Layers size={24} className="mx-auto mb-2 opacity-30" /> No members in this group yet.
                </td>
              </tr>
            ) : rows.map(row => (
              <tr key={row.id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors">
                <td className="px-5 py-3.5 text-[13px] font-bold text-[var(--text-main)]">{row.name}</td>
                <td className="px-5 py-3.5 text-[13px] font-black text-[var(--text-main)]">{row.total}</td>
                <td className="px-4 py-3.5 text-[12px] font-bold text-[var(--accent-red)] text-center border-l border-[var(--border)]">{row.overdue} <span className="text-[10px] font-medium opacity-70">({pct(row.overdue, row.total)}%)</span></td>
                <td className="px-4 py-3.5 text-[12px] font-bold text-[var(--accent-yellow)] text-center">{row.pending} <span className="text-[10px] font-medium opacity-70">({pct(row.pending, row.total)}%)</span></td>
                <td className="px-4 py-3.5 text-[12px] font-bold text-[var(--accent-orange)] text-center">{row.inProgress} <span className="text-[10px] font-medium opacity-70">({pct(row.inProgress, row.total)}%)</span></td>
                <td className="px-4 py-3.5 text-[12px] font-bold text-[var(--accent-green)] text-center border-l border-[var(--border)]">{row.inTime} <span className="text-[10px] font-medium opacity-70">({pct(row.inTime, row.total)}%)</span></td>
                <td className="px-4 py-3.5 text-[12px] font-bold text-[var(--accent-red)] text-center">{row.delayed} <span className="text-[10px] font-medium opacity-70">({pct(row.delayed, row.total)}%)</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default EmployeeBreakdownTable;
