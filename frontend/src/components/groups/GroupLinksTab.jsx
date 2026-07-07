import React, { useState } from 'react';
import { Globe, Plus, Trash2, Link2 } from 'lucide-react';
import ReferenceLinksModal from '../tasks/ReferenceLinksModal';
import { addGroupLink, deleteGroupLink } from '../../services/groupApi';
import { useNotification } from '../../context/NotificationContext';

// Simple shared {name, url} list for the group, addable/removable by any member.
// Reuses ReferenceLinksModal's edit-the-whole-array-then-Apply interaction; since the
// backend is single add/single delete, the Apply handler diffs the returned array
// against the group's current links by id.
const GroupLinksTab = ({ group, onChanged }) => {
  const { showError } = useNotification();
  const [modalOpen, setModalOpen] = useState(false);
  const links = group.links || [];

  const handleApply = async (pending) => {
    const originalIds = new Set(links.map(l => l.id));
    const pendingIds = new Set(pending.map(l => l.id));
    const added = pending.filter(l => !originalIds.has(l.id));
    const removed = links.filter(l => !pendingIds.has(l.id));

    try {
      await Promise.all([
        ...added.map(l => addGroupLink(group.id, { name: l.name, url: l.url })),
        ...removed.map(l => deleteGroupLink(group.id, l.id)),
      ]);
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save links');
    }
  };

  const handleRemove = async (link) => {
    try {
      await deleteGroupLink(group.id, link.id);
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to remove link');
    }
  };

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-5 space-y-4">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
          <Link2 size={13} /> Shared Links ({links.length})
        </p>
        <button onClick={() => setModalOpen(true)}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-[var(--accent-indigo)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest hover:opacity-90 transition-all">
          <Plus size={13} /> Add Link
        </button>
      </div>

      {links.length === 0 ? (
        <div className="py-10 flex flex-col items-center justify-center border-2 border-dashed border-[var(--border)] rounded-xl gap-2">
          <Globe size={24} className="opacity-30" />
          <p className="text-[11px] font-bold text-[var(--text-muted)]">No links shared yet.</p>
        </div>
      ) : (
        <div className="space-y-1.5">
          {links.map(l => (
            <div key={l.id} className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-[var(--input-bg)]">
              <Globe size={13} className="shrink-0 text-[var(--text-muted)]" />
              <a href={l.url} target="_blank" rel="noreferrer" className="flex-1 min-w-0 text-[12px] font-bold text-[var(--text-main)] truncate hover:text-[var(--accent-indigo)]">
                {l.name}
              </a>
              <button onClick={() => handleRemove(l)} className="p-1 text-[var(--text-muted)] hover:text-[var(--accent-red)] shrink-0">
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      )}

      <ReferenceLinksModal isOpen={modalOpen} onClose={() => setModalOpen(false)} links={links} onApply={handleApply} />
    </div>
  );
};

export default GroupLinksTab;
