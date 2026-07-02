import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Search, Save, Plus } from 'lucide-react';
import { getInitials } from './taskDisplayUtils';

// Shared search + scrollable-list + Cancel/Apply popover, used for the Assignee,
// In Loop and Category pickers (they all share the same header/search/list/footer shape).
const PickerModal = ({
  isOpen, onClose, title, searchPlaceholder = 'Search...', items, multi = true,
  selected, onApply, renderAvatar = false, renderDot = false, allowAddMore = false, addMoreLabel = 'Add More',
}) => {
  const [search, setSearch] = useState('');
  const [pending, setPending] = useState(multi ? [] : null);
  const [newItemName, setNewItemName] = useState('');
  const [addingNew, setAddingNew] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    setPending(multi ? [...(selected || [])] : (selected ?? null));
    setSearch('');
    setAddingNew(false);
    setNewItemName('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  if (!isOpen) return null;

  const filtered = items.filter(it =>
    it.primary?.toLowerCase().includes(search.toLowerCase()) ||
    it.secondary?.toLowerCase().includes(search.toLowerCase())
  );

  const toggle = (id) => {
    if (multi) {
      setPending(p => (p.includes(id) ? p.filter(x => x !== id) : [...p, id]));
    } else {
      setPending(id);
    }
  };

  const handleAddNew = () => {
    const name = newItemName.trim();
    if (!name) return;
    if (multi) {
      // Multiple picks are still pending until Apply Changes, so just stage it like any toggle.
      toggle(name);
      setNewItemName('');
      setAddingNew(false);
    } else {
      // Single-select: the new name isn't in `items` (that list comes from the parent), so
      // there's nothing to visibly highlight as "selected" — apply and close immediately
      // instead of leaving the user to guess whether Add actually did anything.
      setNewItemName('');
      setAddingNew(false);
      onApply(name);
      onClose();
    }
  };

  const handleApply = () => {
    onApply(pending);
    onClose();
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[400] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-sm max-h-[80vh] flex flex-col bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl overflow-hidden">
          <div className="px-5 py-4 border-b border-[var(--border)] flex items-center justify-between shrink-0">
            <h3 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest">{title}</h3>
            <button onClick={onClose} className="p-1 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><X size={18} /></button>
          </div>

          <div className="px-5 pt-4 shrink-0">
            <div className="relative">
              <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder={searchPlaceholder}
                className="w-full pl-9 pr-3 py-2.5 bg-[var(--bg-card)] border-2 border-[var(--accent-indigo)] rounded-full text-[12px] font-bold outline-none" />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto no-scrollbar px-5 py-3 space-y-1">
            {filtered.map(it => {
              const isSelected = multi ? pending.includes(it.id) : pending === it.id;
              return (
                <button type="button" key={it.id} onClick={() => toggle(it.id)}
                  className={`w-full flex items-center gap-3 px-2 py-2.5 rounded-xl text-left transition-all ${isSelected ? 'bg-[var(--accent-indigo-bg)]' : 'hover:bg-[var(--input-bg)]'}`}>
                  {renderAvatar && (
                    <div className="w-9 h-9 rounded-full flex items-center justify-center text-white font-black text-[11px] shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                      {getInitials(it.primary)}
                    </div>
                  )}
                  {renderDot && <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: 'var(--accent-indigo)' }} />}
                  <div className="min-w-0">
                    <p className={`text-[13px] font-bold truncate ${isSelected ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-main)]'}`}>{it.primary}</p>
                    {it.secondary && <p className="text-[11px] font-medium text-[var(--text-muted)] truncate">{it.secondary}</p>}
                  </div>
                </button>
              );
            })}
            {filtered.length === 0 && (
              <p className="text-center text-[11px] font-bold text-[var(--text-muted)] py-6">No matches</p>
            )}
          </div>

          {allowAddMore && addingNew && (
            <div className="px-5 pb-2 shrink-0">
              <div className="flex items-center gap-2">
                <input autoFocus value={newItemName} onChange={e => setNewItemName(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAddNew(); } }}
                  placeholder="New name..."
                  className="flex-1 px-3 py-2 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg text-[12px] font-bold outline-none" />
                <button type="button" onClick={handleAddNew} className="px-3 py-2 bg-[var(--accent-indigo)] text-white rounded-lg text-[11px] font-black">Add</button>
              </div>
            </div>
          )}

          <div className="px-5 py-4 border-t border-[var(--border)] flex items-center justify-between gap-3 shrink-0">
            <button type="button" onClick={onClose} className="text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">Cancel</button>
            <div className="flex items-center gap-2">
              {allowAddMore && !addingNew && (
                <button type="button" onClick={() => setAddingNew(true)} className="flex items-center gap-1.5 px-4 py-2 border border-[var(--accent-indigo)] text-[var(--accent-indigo)] rounded-xl text-[10px] font-black uppercase tracking-widest">
                  <Plus size={13} /> {addMoreLabel}
                </button>
              )}
              <button type="button" onClick={handleApply} className="flex items-center gap-1.5 px-5 py-2 bg-[var(--accent-orange)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest">
                <Save size={13} /> Apply Changes
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default PickerModal;
