import React from 'react';
import { Search, Plus } from 'lucide-react';
import { resolveGroupIcon } from './groupIcons';

// Left pane of the Groups workspace: search + create button + scrollable group rows.
const GroupList = ({ groups, selectedId, onSelect, onCreateClick, search, onSearchChange, loading }) => {
  return (
    <div className="w-full md:w-80 shrink-0 flex flex-col bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden">
      <div className="p-3 flex items-center gap-2 border-b border-[var(--border)]">
        <div className="relative flex-1">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={e => onSearchChange(e.target.value)} placeholder="Search Groups..."
            className="w-full pl-8 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
        </div>
        <button onClick={onCreateClick} title="Create Group"
          className="p-2.5 rounded-xl bg-[var(--accent-indigo)] text-white shrink-0 hover:opacity-90 transition-all">
          <Plus size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto no-scrollbar p-2 space-y-1">
        {loading ? (
          <p className="text-center text-[11px] font-bold text-[var(--text-muted)] py-8">Loading groups...</p>
        ) : groups.length === 0 ? (
          <p className="text-center text-[11px] font-bold text-[var(--text-muted)] py-8">No groups yet.</p>
        ) : (
          groups.map(group => {
            const Icon = resolveGroupIcon(group.icon);
            const isActive = group.id === selectedId;
            return (
              <button key={group.id} onClick={() => onSelect(group.id)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left transition-all ${isActive ? 'bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)]' : 'border border-transparent hover:bg-[var(--input-bg)]'}`}>
                <div className="w-9 h-9 rounded-full flex items-center justify-center shrink-0 text-white" style={{ background: group.color || 'var(--accent-indigo)' }}>
                  <Icon size={16} />
                </div>
                <div className="min-w-0">
                  <p className={`text-[13px] font-bold truncate ${isActive ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-main)]'}`}>{group.name}</p>
                  <p className="text-[11px] font-medium text-[var(--text-muted)] truncate">{group.description || `${group.task_count} task${group.task_count === 1 ? '' : 's'}`}</p>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
};

export default GroupList;
