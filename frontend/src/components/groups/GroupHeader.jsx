import React from 'react';
import { Search, Pencil, UsersRound } from 'lucide-react';
import { GROUP_ICON_MAP } from './groupIcons';
import { getInitials } from '../tasks/taskDisplayUtils';

const MAX_VISIBLE_AVATARS = 4;

// Group workspace header: icon/name/description, a search box (scoped to the Tasks/My
// Tasks/Timeline tabs -- see GroupWorkspace), and a stacked avatar row for the team.
const GroupHeader = ({ group, userMap, search, onSearchChange, onEdit }) => {
  const Icon = GROUP_ICON_MAP[group.icon] || UsersRound;
  const memberIds = group.member_ids || [];
  const visible = memberIds.slice(0, MAX_VISIBLE_AVATARS);
  const overflow = memberIds.length - visible.length;

  return (
    <div className="flex flex-wrap items-center justify-between gap-4 bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-4">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-11 h-11 rounded-2xl flex items-center justify-center text-white shrink-0" style={{ background: group.color || 'var(--accent-indigo)' }}>
          <Icon size={20} />
        </div>
        <div className="min-w-0">
          <p className="text-[15px] font-black text-[var(--text-main)] truncate flex items-center gap-1.5">
            {group.name}
            <button onClick={onEdit} title="Edit group" className="p-1 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]">
              <Pencil size={12} />
            </button>
          </p>
          <p className="text-[12px] text-[var(--text-muted)] font-bold truncate">{group.description || 'No description'}</p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="relative">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={e => onSearchChange(e.target.value)} placeholder="Search..."
            className="pl-8 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)] w-40" />
        </div>

        <div className="flex items-center">
          <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest mr-2">Team</span>
          <div className="flex -space-x-2">
            {visible.map(id => (
              <div key={id} title={userMap[id] || id}
                className="w-8 h-8 rounded-full border-2 border-[var(--bg-card)] flex items-center justify-center text-white font-black text-[10px]"
                style={{ background: 'var(--avatar-bg)' }}>
                {getInitials(userMap[id] || '?')}
              </div>
            ))}
            {overflow > 0 && (
              <div className="w-8 h-8 rounded-full border-2 border-[var(--bg-card)] flex items-center justify-center bg-[var(--input-bg)] text-[var(--text-muted)] font-black text-[10px]">
                +{overflow}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default GroupHeader;
