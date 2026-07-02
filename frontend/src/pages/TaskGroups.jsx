import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { UsersRound, Plus } from 'lucide-react';
import api from '../services/api';
import { getGroups } from '../services/groupApi';
import GroupList from '../components/groups/GroupList';
import GroupFormModal from '../components/groups/GroupFormModal';
import GroupWorkspace from '../components/groups/GroupWorkspace';

// Two-pane Groups workspace: a searchable list of groups on the left, and the selected
// group's full workspace (header/toolbar/tabs) on the right. Owns the groups list and a
// single shared `/users` fetch so every child component resolves member names/avatars
// from the same userMap instead of each re-fetching independently.
const TaskGroups = () => {
  const [groups, setGroups] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedGroupId, setSelectedGroupId] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingGroup, setEditingGroup] = useState(null);

  const fetchGroups = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getGroups();
      const list = res.data || [];
      setGroups(list);
      setSelectedGroupId(prev => (prev && list.some(g => g.id === prev)) ? prev : (list[0]?.id || null));
    } catch {
      // non-fatal
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchGroups(); }, [fetchGroups]);
  useEffect(() => {
    api.get('/users?active_only=true').then(res => setUsers(res.data || [])).catch(() => {});
  }, []);

  const userMap = useMemo(() => {
    const m = {};
    users.forEach(u => { m[u._id] = u.full_name || u.email; });
    return m;
  }, [users]);

  const filteredGroups = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return groups;
    return groups.filter(g => g.name.toLowerCase().includes(q));
  }, [groups, search]);

  const selectedGroup = groups.find(g => g.id === selectedGroupId) || null;

  return (
    <div className="space-y-5 pb-24">
      <div className="flex items-center gap-3">
        <div className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo)] text-white flex items-center justify-center shadow-lg shadow-[var(--accent-indigo)]/20">
          <UsersRound size={20} />
        </div>
        <div>
          <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight">Groups</h1>
          <p className="text-[12px] text-[var(--text-muted)] font-bold">Organize tasks and teams into dedicated workspaces</p>
        </div>
      </div>

      <div className="flex flex-col md:flex-row gap-5 items-start">
        <GroupList
          groups={filteredGroups} selectedId={selectedGroupId} onSelect={setSelectedGroupId}
          onCreateClick={() => { setEditingGroup(null); setFormOpen(true); }}
          search={search} onSearchChange={setSearch} loading={loading}
        />

        {selectedGroup ? (
          <GroupWorkspace
            group={selectedGroup} users={users} userMap={userMap}
            onGroupChanged={fetchGroups}
            onEditGroup={() => { setEditingGroup(selectedGroup); setFormOpen(true); }}
          />
        ) : (
          <div className="flex-1 w-full flex flex-col items-center justify-center gap-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-16">
            <UsersRound size={40} className="opacity-30" />
            <p className="text-[12px] font-bold text-[var(--text-muted)]">{loading ? 'Loading groups...' : 'No group selected yet.'}</p>
            {!loading && (
              <button onClick={() => { setEditingGroup(null); setFormOpen(true); }}
                className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all">
                <Plus size={14} /> Create Your First Group
              </button>
            )}
          </div>
        )}
      </div>

      <GroupFormModal isOpen={formOpen} onClose={() => setFormOpen(false)} group={editingGroup} staffOptions={users} onSaved={fetchGroups} />
    </div>
  );
};

export default TaskGroups;
