import React, { useCallback, useEffect, useState } from 'react';
import { LayoutDashboard, ListChecks, CheckSquare, Lightbulb, Link2, History } from 'lucide-react';
import { getTasks } from '../../services/taskApi';
import GroupHeader from './GroupHeader';
import GroupToolbar from './GroupToolbar';
import GroupDashboardTab from './GroupDashboardTab';
import GroupIdeaboard from './GroupIdeaboard';
import GroupLinksTab from './GroupLinksTab';
import GroupTimelineTab from './GroupTimelineTab';
import TaskListView from '../tasks/TaskListView';

const TABS = [
  { key: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { key: 'tasks', label: 'Tasks', icon: ListChecks },
  { key: 'my', label: 'My Tasks', icon: CheckSquare },
  { key: 'ideaboard', label: 'Ideaboard', icon: Lightbulb },
  { key: 'links', label: 'Links', icon: Link2 },
  { key: 'timeline', label: 'Timeline', icon: History },
];

const emptyFilters = { period: 'all_time', startDate: '', endDate: '', assignedTo: '', frequency: '' };

// Right pane of the Groups workspace: header + persistent toolbar + tab bar + active tab.
// Owns the group-wide task fetch (scope="group") shared by the toolbar's Export button and
// the Dashboard tab -- Tasks/My Tasks tabs instead reuse TaskListView's own independent
// fetch (via its new `groupId`/`embedded` props), since it already manages that fully.
const GroupWorkspace = ({ group, users, userMap, onGroupChanged, onEditGroup }) => {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [filters, setFilters] = useState(emptyFilters);
  const [search, setSearch] = useState('');
  const [tasks, setTasks] = useState([]);
  const [tasksLoading, setTasksLoading] = useState(true);

  const fetchGroupTasks = useCallback(async () => {
    setTasksLoading(true);
    try {
      const res = await getTasks({
        scope: 'group', groupId: group.id,
        period: filters.period,
        startDate: filters.period === 'custom' ? filters.startDate : undefined,
        endDate: filters.period === 'custom' ? filters.endDate : undefined,
        assignedTo: filters.assignedTo || undefined,
        frequency: filters.frequency || undefined,
      });
      setTasks(res.data || []);
    } catch {
      setTasks([]);
    } finally {
      setTasksLoading(false);
    }
  }, [group.id, filters]);

  useEffect(() => { fetchGroupTasks(); }, [fetchGroupTasks]);
  useEffect(() => { setActiveTab('dashboard'); setFilters(emptyFilters); setSearch(''); }, [group.id]);

  return (
    <div className="flex-1 w-full min-w-0 space-y-4">
      <GroupHeader group={group} userMap={userMap} search={search} onSearchChange={setSearch} onEdit={onEditGroup} />
      <GroupToolbar group={group} users={users} userMap={userMap} filters={filters} onFiltersChange={setFilters}
        tasks={tasks} onTaskSaved={fetchGroupTasks} onRefresh={fetchGroupTasks} />

      <div className="flex items-center gap-1 overflow-x-auto pb-1 no-scrollbar">
        {TABS.map(tab => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.key;
          return (
            <button key={tab.key} onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-[11px] font-black uppercase tracking-wider whitespace-nowrap transition-all border ${
                isActive ? 'bg-[var(--accent-indigo-bg)] border-[var(--accent-indigo)] text-[var(--accent-indigo)]' : 'border-transparent text-[var(--text-muted)] hover:bg-[var(--input-bg)]'
              }`}>
              <Icon size={13} /> {tab.label}
            </button>
          );
        })}
      </div>

      {activeTab === 'dashboard' && <GroupDashboardTab tasks={tasks} group={group} userMap={userMap} loading={tasksLoading} />}

      {activeTab === 'tasks' && (
        <TaskListView scope="group" groupId={group.id} embedded allowCreate={false}
          heading="Tasks" subheading="All tasks in this group" emptyMessage="No tasks in this group yet." />
      )}

      {activeTab === 'my' && (
        <TaskListView scope="my" groupId={group.id} embedded allowCreate={false}
          heading="My Tasks" subheading="Your tasks in this group" emptyMessage="No tasks assigned to you in this group." />
      )}

      {activeTab === 'ideaboard' && <GroupIdeaboard group={group} userMap={userMap} staffOptions={users} />}

      {activeTab === 'links' && <GroupLinksTab group={group} onChanged={onGroupChanged} />}

      {activeTab === 'timeline' && (
        <GroupTimelineTab group={group} period={filters.period} startDate={filters.startDate} endDate={filters.endDate} search={search} />
      )}
    </div>
  );
};

export default GroupWorkspace;
