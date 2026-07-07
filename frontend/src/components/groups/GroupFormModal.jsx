import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Save, Users as UsersIcon } from 'lucide-react';
import { createGroup, updateGroup } from '../../services/groupApi';
import { useNotification } from '../../context/NotificationContext';
import PickerModal from '../tasks/PickerModal';
import { GROUP_ICON_MAP, GROUP_ICON_OPTIONS, GROUP_COLOR_OPTIONS } from './groupIcons';

const emptyForm = { name: '', description: '', icon: 'UsersRound', color: GROUP_COLOR_OPTIONS[0], member_ids: [] };

// Create/edit a task group: name, description, a small fixed icon/color palette (matching
// the app's existing accent-token convention rather than arbitrary hex input), and a
// member picker built on the same PickerModal used for Assignee/In-Loop in TaskFormModal.
const GroupFormModal = ({ isOpen, onClose, onSaved, group = null, staffOptions = [] }) => {
  const { showSuccess, showError } = useNotification();
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [memberPickerOpen, setMemberPickerOpen] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setForm(group ? {
      name: group.name || '',
      description: group.description || '',
      icon: group.icon || 'UsersRound',
      color: group.color || GROUP_COLOR_OPTIONS[0],
      member_ids: group.member_ids || [],
    } : emptyForm);
  }, [isOpen, group]);

  if (!isOpen) return null;

  const staffItems = staffOptions.map(u => ({ id: u._id, primary: u.full_name || u.email, secondary: u.email }));
  const memberNames = form.member_ids.map(id => staffOptions.find(u => u._id === id)?.full_name || staffOptions.find(u => u._id === id)?.email).filter(Boolean);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return showError('Group name is required');

    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        icon: form.icon,
        color: form.color,
        member_ids: form.member_ids,
      };
      if (group) {
        await updateGroup(group.id, payload);
        showSuccess('Group updated');
      } else {
        await createGroup(payload);
        showSuccess('Group created');
      }
      onSaved?.();
      onClose();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save group');
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
    <AnimatePresence>
      <div className="fixed inset-0 z-[400] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-md max-h-[85vh] flex flex-col bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl overflow-hidden">
          <div className="px-5 py-4 border-b border-[var(--border)] flex items-center justify-between shrink-0">
            <h3 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest">{group ? 'Edit Group' : 'Create Group'}</h3>
            <button onClick={onClose} className="p-1 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><X size={18} /></button>
          </div>

          <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto no-scrollbar px-5 py-4 space-y-4">
            <div>
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-1.5 block">Name *</label>
              <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. HR Team"
                className="w-full px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
            </div>

            <div>
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-1.5 block">Description</label>
              <textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} rows={2} placeholder="What is this group for?"
                className="w-full px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)] resize-none" />
            </div>

            <div>
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-1.5 block">Icon</label>
              <div className="flex flex-wrap gap-2">
                {GROUP_ICON_OPTIONS.map(name => {
                  const Icon = GROUP_ICON_MAP[name];
                  const isActive = form.icon === name;
                  return (
                    <button type="button" key={name} onClick={() => setForm(f => ({ ...f, icon: name }))}
                      className={`w-9 h-9 rounded-xl flex items-center justify-center border transition-all ${isActive ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
                      <Icon size={16} />
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-1.5 block">Color</label>
              <div className="flex flex-wrap gap-2">
                {GROUP_COLOR_OPTIONS.map(color => {
                  const isActive = form.color === color;
                  return (
                    <button type="button" key={color} onClick={() => setForm(f => ({ ...f, color }))}
                      className={`w-8 h-8 rounded-full border-2 transition-all ${isActive ? 'border-[var(--text-main)] scale-110' : 'border-transparent'}`}
                      style={{ background: color }} />
                  );
                })}
              </div>
            </div>

            <div>
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-1.5 block">Members</label>
              <button type="button" onClick={() => setMemberPickerOpen(true)}
                className="w-full flex items-center gap-2 px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold text-left">
                <UsersIcon size={14} className="text-[var(--text-muted)] shrink-0" />
                <span className="truncate">{memberNames.length ? memberNames.join(', ') : 'Add members...'}</span>
              </button>
            </div>
          </form>

          <div className="px-5 py-4 border-t border-[var(--border)] flex items-center justify-end gap-3 shrink-0">
            <button type="button" onClick={onClose} className="text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">Cancel</button>
            <button type="button" onClick={handleSubmit} disabled={saving}
              className="flex items-center gap-1.5 px-5 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 disabled:opacity-60 transition-all">
              <Save size={14} /> {saving ? 'Saving...' : (group ? 'Save Changes' : 'Create Group')}
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>

      <PickerModal
        isOpen={memberPickerOpen} onClose={() => setMemberPickerOpen(false)}
        title="Add Members" searchPlaceholder="Search users..." items={staffItems}
        multi selected={form.member_ids} renderAvatar
        onApply={(ids) => setForm(f => ({ ...f, member_ids: ids }))}
      />
    </>
  );
};

export default GroupFormModal;
