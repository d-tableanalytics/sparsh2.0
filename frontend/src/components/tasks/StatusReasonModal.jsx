import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Save } from 'lucide-react';
import { STATUS_CONFIG } from './statusConfig';

// Collects the Reason a status change requires before it can be saved (backend enforces the
// same). "Dependent on Other" additionally needs a Doer Name — the task is reassigned to that
// doer — so the doer picker is shown only for that status. "Blocked" needs a reason only.
// Shares the header/footer shape of the module's other small modals (PickerModal / TaskTagsModal).
const StatusReasonModal = ({ isOpen, status, users = [], onClose, onSubmit, saving = false }) => {
  const [doerId, setDoerId] = useState('');
  const [reason, setReason] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    setDoerId('');
    setReason('');
  }, [isOpen]);

  if (!isOpen) return null;

  // Only "Dependent on Other" needs a doer (it reassigns the task); "Blocked" needs a reason only.
  const needsDoer = status === 'dependent_on_others';
  const label = STATUS_CONFIG[status]?.label || status;
  const doerName = users.find(u => u._id === doerId)?.full_name || users.find(u => u._id === doerId)?.email || '';
  const canSave = reason.trim() && (!needsDoer || doerId) && !saving;

  const handleSave = () => {
    if (!canSave) return;
    onSubmit({ doerId: needsDoer ? doerId : '', doerName: needsDoer ? doerName : '', reason: reason.trim() });
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[500] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-sm bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl overflow-hidden">
          <div className="px-5 py-4 border-b border-[var(--border)] flex items-center justify-between">
            <h3 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest">{label}</h3>
            <button onClick={onClose} className="p-1 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><X size={18} /></button>
          </div>

          <div className="px-5 py-4 space-y-3">
            {needsDoer && (
              <div>
                <label className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest">Doer Name *</label>
                <select value={doerId} onChange={e => setDoerId(e.target.value)}
                  className="mt-1 w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]">
                  <option value="">Select a doer...</option>
                  {users.map(u => <option key={u._id} value={u._id}>{u.full_name || u.email}</option>)}
                </select>
              </div>
            )}
            <div>
              <label className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest">Remark *</label>
              <textarea rows={3} value={reason} onChange={e => setReason(e.target.value)}
                placeholder="Why is the task in this status?"
                className="mt-1 w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)] resize-none" />
            </div>
          </div>

          <div className="px-5 py-4 border-t border-[var(--border)] flex items-center justify-between gap-3">
            <button type="button" onClick={onClose} className="text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">Cancel</button>
            <button type="button" onClick={handleSave} disabled={!canSave}
              className="flex items-center gap-1.5 px-5 py-2 bg-[var(--accent-indigo)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest disabled:opacity-40 disabled:cursor-not-allowed">
              <Save size={13} /> {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default StatusReasonModal;
