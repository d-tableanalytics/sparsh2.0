import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, CheckSquare, Plus } from 'lucide-react';
import api from '../../services/api';
import { createTask, updateTask } from '../../services/taskApi';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';

const emptyForm = {
  title: '',
  description: '',
  category: '',
  tags: '',
  start: '',
  end: '',
  repeat: 'Does not repeat',
  priority: 'Normal',
  target_staff_id: [],
  watchers: [],
};

// Creates/edits type:"task" calendar_event docs via the existing /calendar/events API
// (same one the Calendar page's "Architect Tasks" panel uses), so tasks made here also
// show up on the Calendar page and vice versa.
const TaskFormModal = ({ isOpen, onClose, onSaved, task = null }) => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const [form, setForm] = useState(emptyForm);
  const [staffOptions, setStaffOptions] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    api.get('/users?active_only=true').then(res => setStaffOptions(res.data || [])).catch(() => setStaffOptions([]));

    if (task) {
      setForm({
        title: task.title || '',
        description: task.description || '',
        category: task.category || '',
        tags: (task.tags || []).join(', '),
        start: task.start ? task.start.slice(0, 16) : '',
        end: task.end ? task.end.slice(0, 16) : '',
        repeat: task.frequency || task.repeat || 'Does not repeat',
        priority: task.priority || 'Normal',
        target_staff_id: task.assignedTo || task.target_staff_id || [],
        watchers: task.watchers || [],
      });
    } else {
      setForm(emptyForm);
    }
  }, [isOpen, task]);

  if (!isOpen) return null;

  const toggleMulti = (field, id) => {
    setForm(f => ({
      ...f,
      [field]: f[field].includes(id) ? f[field].filter(x => x !== id) : [...f[field], id],
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.title.trim() || !form.start) {
      showError('Title and start date are required');
      return;
    }
    setSaving(true);
    try {
      const payload = {
        title: form.title,
        description: form.description,
        category: form.category,
        tags: form.tags.split(',').map(t => t.trim()).filter(Boolean),
        start: new Date(form.start).toISOString(),
        end: form.end ? new Date(form.end).toISOString() : null,
        repeat: form.repeat,
        priority: form.priority,
        assigned_to: form.target_staff_id.length ? 'other' : 'myself',
        target_staff_id: form.target_staff_id,
        watchers: form.watchers,
      };
      if (task) {
        await updateTask(task.id, payload);
        showSuccess('Task updated');
      } else {
        await createTask(payload);
        showSuccess('Task created');
      }
      onSaved?.();
      onClose();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save task');
    } finally {
      setSaving(false);
    }
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[300] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-lg max-h-[85vh] overflow-y-auto no-scrollbar bg-[var(--bg-card)] border border-[var(--border)] rounded-[28px] shadow-2xl"
        >
          <div className="px-7 py-5 border-b border-[var(--border)] flex items-center justify-between sticky top-0 bg-[var(--bg-card)] z-10">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]"><CheckSquare size={18} /></div>
              <h3 className="text-[15px] font-black text-[var(--text-main)] uppercase tracking-tight">{task ? 'Edit Task' : 'New Task'}</h3>
            </div>
            <button onClick={onClose} className="p-1.5 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><X size={20} /></button>
          </div>

          <form onSubmit={handleSubmit} className="p-7 space-y-5">
            <div className="space-y-1.5">
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Task Title</label>
              <input autoFocus value={form.title} onChange={e => setForm({ ...form, title: e.target.value })}
                placeholder="Task name" className="w-full px-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[13px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Start</label>
                <input type="datetime-local" value={form.start} onChange={e => setForm({ ...form, start: e.target.value })}
                  className="w-full px-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
              </div>
              <div className="space-y-1.5">
                <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Due (optional)</label>
                <input type="datetime-local" value={form.end} onChange={e => setForm({ ...form, end: e.target.value })}
                  className="w-full px-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Category</label>
                <input value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}
                  placeholder="e.g. Operations" className="w-full px-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
              </div>
              <div className="space-y-1.5">
                <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Frequency</label>
                <select value={form.repeat} onChange={e => setForm({ ...form, repeat: e.target.value })}
                  className="w-full px-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]">
                  {['Does not repeat', 'Daily', 'Weekly', 'Monthly', 'Yearly'].map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Priority</label>
              <div className="flex gap-2">
                {['Low', 'Normal', 'High'].map(p => (
                  <button type="button" key={p} onClick={() => setForm({ ...form, priority: p })}
                    className={`flex-1 px-3 py-2 rounded-xl text-[11px] font-black uppercase tracking-wider border transition-all ${form.priority === p ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]' : 'bg-[var(--input-bg)] text-[var(--text-muted)] border-[var(--input-border)]'}`}>
                    {p}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Tags (comma separated)</label>
              <input value={form.tags} onChange={e => setForm({ ...form, tags: e.target.value })}
                placeholder="urgent, client-facing" className="w-full px-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Description</label>
              <textarea rows={3} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })}
                className="w-full px-4 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-medium outline-none focus:border-[var(--accent-indigo)]" />
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Delegate To (leave empty to keep for yourself)</label>
              <div className="flex flex-wrap gap-2 max-h-28 overflow-y-auto no-scrollbar p-2 bg-[var(--input-bg)] rounded-xl border border-[var(--input-border)]">
                {staffOptions.filter(u => u._id !== user?._id).map(u => (
                  <button type="button" key={u._id} onClick={() => toggleMulti('target_staff_id', u._id)}
                    className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border transition-all ${form.target_staff_id.includes(u._id) ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)]'}`}>
                    {u.full_name || u.email}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Keep In Loop (subscribers)</label>
              <div className="flex flex-wrap gap-2 max-h-28 overflow-y-auto no-scrollbar p-2 bg-[var(--input-bg)] rounded-xl border border-[var(--input-border)]">
                {staffOptions.filter(u => u._id !== user?._id).map(u => (
                  <button type="button" key={u._id} onClick={() => toggleMulti('watchers', u._id)}
                    className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border transition-all ${form.watchers.includes(u._id) ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--border)]'}`}>
                    {u.full_name || u.email}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button type="button" onClick={onClose} className="px-5 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:bg-[var(--input-bg)]">Cancel</button>
              <button type="submit" disabled={saving} className="flex items-center gap-2 px-6 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-lg hover:opacity-90 disabled:opacity-60 transition-all">
                <Plus size={14} /> {saving ? 'Saving...' : (task ? 'Save Changes' : 'Create Task')}
              </button>
            </div>
          </form>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default TaskFormModal;
