import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Save, Trash2 } from 'lucide-react';

const COLUMN_LABELS = { todo: 'To Do', in_progress: 'In Progress', done: 'Done' };

// Create/edit a single Ideaboard card: title, description, assignee (scoped to the
// group's members) and which column it's in.
const BoardCardModal = ({ isOpen, onClose, onSave, onDelete, card = null, defaultColumn = 'todo', members = [] }) => {
  const [form, setForm] = useState({ title: '', description: '', assignee_id: '', column: defaultColumn });

  useEffect(() => {
    if (!isOpen) return;
    setForm(card ? {
      title: card.title || '', description: card.description || '',
      assignee_id: card.assignee_id || '', column: card.column || defaultColumn,
    } : { title: '', description: '', assignee_id: '', column: defaultColumn });
  }, [isOpen, card, defaultColumn]);

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!form.title.trim()) return;
    onSave({ ...form, title: form.title.trim(), assignee_id: form.assignee_id || null, description: form.description.trim() || null });
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[400] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-sm bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl overflow-hidden">
          <div className="px-5 py-4 border-b border-[var(--border)] flex items-center justify-between">
            <h3 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest">{card ? 'Edit Card' : 'New Card'}</h3>
            <button onClick={onClose} className="p-1 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><X size={18} /></button>
          </div>

          <form onSubmit={handleSubmit} className="px-5 py-4 space-y-3">
            <input autoFocus value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} placeholder="Card title *"
              className="w-full px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
            <textarea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} rows={3} placeholder="Description (optional)"
              className="w-full px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)] resize-none" />
            <select value={form.assignee_id} onChange={e => setForm(f => ({ ...f, assignee_id: e.target.value }))}
              className="w-full px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none">
              <option value="">Unassigned</option>
              {members.map(u => <option key={u._id} value={u._id}>{u.full_name || u.email}</option>)}
            </select>
            <select value={form.column} onChange={e => setForm(f => ({ ...f, column: e.target.value }))}
              className="w-full px-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none">
              {Object.entries(COLUMN_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>

            <div className="flex items-center justify-between gap-3 pt-1">
              {card ? (
                <button type="button" onClick={() => onDelete(card)} className="flex items-center gap-1.5 text-[11px] font-black uppercase tracking-widest text-[var(--accent-red)]">
                  <Trash2 size={13} /> Delete
                </button>
              ) : <span />}
              <button type="submit" className="flex items-center gap-1.5 px-5 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all">
                <Save size={14} /> Save
              </button>
            </div>
          </form>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default BoardCardModal;
