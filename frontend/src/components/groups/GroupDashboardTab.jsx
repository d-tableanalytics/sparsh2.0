import React, { useMemo } from 'react';
import StatusSummaryCards from '../tasks/StatusSummaryCards';
import EmployeeBreakdownTable from './EmployeeBreakdownTable';
import { GROUP_DASHBOARD_CARD_ORDER } from '../tasks/statusConfig';

// Purely presentational -- GroupWorkspace owns the single group-wide task fetch (shared
// with the toolbar's Export) and passes it straight through here.
const GroupDashboardTab = ({ tasks, group, userMap, loading }) => {
  const summary = useMemo(() => {
    const s = { overdue: 0, pending: 0, inProgress: 0, completed: 0, inTime: 0, delayed: 0 };
    tasks.forEach(t => {
      if (t.isOverdue) s.overdue += 1;
      if (t.status === 'pending') s.pending += 1;
      if (t.status === 'in_progress') s.inProgress += 1;
      if (t.status === 'completed') s.completed += 1;
      if (t.completionTiming === 'in_time') s.inTime += 1;
      if (t.completionTiming === 'delayed') s.delayed += 1;
    });
    return s;
  }, [tasks]);

  if (loading) {
    return <div className="p-16 text-center text-[var(--text-muted)] text-[12px] font-bold bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px]">Loading dashboard...</div>;
  }

  return (
    <div className="space-y-5">
      <StatusSummaryCards cardOrder={GROUP_DASHBOARD_CARD_ORDER} summary={summary} activeKey={null}
        columnsClass="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4" />
      <EmployeeBreakdownTable tasks={tasks} members={group.member_ids || []} userMap={userMap} />
    </div>
  );
};

export default GroupDashboardTab;
