import React, { useCallback, useEffect, useState } from 'react';
import { UserPlus, RefreshCw, Download } from 'lucide-react';
import DateRangeFilter from '../tasks/DateRangeFilter';
import TaskFormModal from '../tasks/TaskFormModal';
import { getTaskCategories, getTaskTags } from '../../services/taskMetaApi';
import { exportTasksToCsv } from '../tasks/taskDisplayUtils';

const FREQUENCIES = ['Does not repeat', 'Daily', 'Weekly', 'Monthly', 'Yearly'];

// Persistent toolbar shown above the tab bar (matches the reference screenshot, where the
// toolbar sits above Dashboard/Tasks/My Tasks/etc.) -- Assign Task is always reachable
// regardless of which tab is active, and its filters drive the Dashboard tab's task fetch.
const GroupToolbar = ({ group, users, userMap, filters, onFiltersChange, tasks, onTaskSaved, onRefresh }) => {
  const [modalOpen, setModalOpen] = useState(false);
  const [categories, setCategories] = useState([]);
  const [tags, setTags] = useState([]);

  const fetchTaxonomy = useCallback(async () => {
    try {
      const [catRes, tagRes] = await Promise.all([getTaskCategories(), getTaskTags()]);
      setCategories((catRes.data || []).map(c => c.name));
      setTags((tagRes.data || []).map(t => t.name));
    } catch {
      // non-fatal
    }
  }, []);

  useEffect(() => { fetchTaxonomy(); }, [fetchTaxonomy]);

  const memberUsers = users.filter(u => (group.member_ids || []).includes(u._id));

  const setFilter = (key, value) => onFiltersChange({ ...filters, [key]: value });

  return (
    <div className="flex flex-wrap items-center gap-2.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-3">
      <button onClick={() => setModalOpen(true)}
        className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all">
        <UserPlus size={14} /> Assign Task
      </button>

      <DateRangeFilter variant="dropdown" period={filters.period} onPeriodChange={v => setFilter('period', v)}
        startDate={filters.startDate} endDate={filters.endDate}
        onCustomChange={(field, value) => setFilter(field, value)} />

      <select value={filters.assignedTo} onChange={e => setFilter('assignedTo', e.target.value)}
        className="px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none">
        <option value="">Assigned To</option>
        {memberUsers.map(u => <option key={u._id} value={u._id}>{u.full_name || u.email}</option>)}
      </select>

      <select value={filters.frequency} onChange={e => setFilter('frequency', e.target.value)}
        className="px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none">
        <option value="">Frequency</option>
        {FREQUENCIES.map(f => <option key={f} value={f}>{f}</option>)}
      </select>

      <button onClick={() => exportTasksToCsv(tasks, userMap, `${group.name.toLowerCase().replace(/\s+/g, '-')}-tasks.csv`)}
        className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all">
        <Download size={14} /> Export
      </button>

      <button onClick={onRefresh} title="Refresh" className="p-2.5 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-all">
        <RefreshCw size={15} />
      </button>

      <TaskFormModal isOpen={modalOpen} onClose={() => setModalOpen(false)} groupId={group.id} onSaved={onTaskSaved}
        categories={categories} tags={tags} onTaxonomyChanged={fetchTaxonomy} />
    </div>
  );
};

export default GroupToolbar;
