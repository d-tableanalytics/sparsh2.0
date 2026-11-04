import React from 'react';
import { Trash2, RotateCcw, Bell, Repeat } from 'lucide-react';

/**
 * "Are you sure?" for deleting or restoring tasks — one task or a whole selection, one-time or
 * recurring. Styled like the Delete Task confirmation in TaskDetailsModal, so every destructive
 * task action asks the same way.
 *
 * `tasks` are the task rows being acted on (occurrences, for a recurring series). The dialog
 * says how many, names the first few, and counts recurring series separately, because a series
 * row stands for many occurrences and "Delete 1 task" would understate what is about to happen.
 */
const ConfirmActionModal = ({ action, tasks = [], busy, onConfirm, onCancel }) => {
  if (!action) return null;
  const deleting = action === 'delete';
  const series = new Map();
  const single = [];
  tasks.forEach((t) => {
    if (t.recurringGroupId) {
      const s = series.get(t.recurringGroupId) || { title: t.title, count: 0 };
      s.count += 1;
      series.set(t.recurringGroupId, s);
    } else {
      single.push(t);
    }
  });
  const names = [
    ...[...series.values()].map((s) => `${s.title} (recurring, ${s.count} occurrence${s.count === 1 ? '' : 's'})`),
    ...single.map((t) => t.title),
  ];
  const total = tasks.length;
  const noun = total === 1 ? 'this task' : `these ${total} tasks`;

  return (
    <div className="fixed inset-0 z-[600] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={busy ? undefined : onCancel} />
      <div role="alertdialog" aria-modal="true"
        className="relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center gap-2.5 px-5 py-4 border-b border-[var(--border)]">
          <span className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${deleting
            ? 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]' : 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'}`}>
            {deleting ? <Trash2 size={16} /> : <RotateCcw size={16} />}
          </span>
          <h3 className="text-[15px] font-extrabold tracking-tight">
            {deleting ? `Delete ${noun}?` : `Restore ${noun}?`}
          </h3>
        </div>

        <div className="px-5 py-4 space-y-3">
          <ul className="max-h-40 overflow-y-auto space-y-1 text-[12.5px] font-bold">
            {names.slice(0, 8).map((n) => (
              <li key={n} className="flex items-start gap-1.5">
                {n.includes('(recurring') && <Repeat size={12} className="mt-1 shrink-0 text-[var(--accent-indigo)]" />}
                <span className="truncate">{n}</span>
              </li>
            ))}
            {names.length > 8 && (
              <li className="text-[var(--text-muted)] font-medium">…and {names.length - 8} more</li>
            )}
          </ul>
          {series.size > 0 && (
            <p className="text-[12px] font-semibold text-[var(--text-muted)]">
              Includes {series.size} recurring series — every selected occurrence is {deleting ? 'deleted' : 'restored'}.
            </p>
          )}
          <p className="text-[12.5px] font-medium text-[var(--text-muted)]">
            {deleting ? (
              <>{total === 1 ? 'It moves' : 'They move'} to <b className="text-[var(--text-main)]">Deleted Tasks</b> and can be restored from there.</>
            ) : (
              <>{total === 1 ? 'It goes' : 'They go'} back to the task lists with the status {total === 1 ? 'it' : 'they'} had when deleted.</>
            )}
          </p>
          {deleting && (
            <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-yellow)]">
              <Bell size={14} className="mt-[1px] shrink-0" />
              <span>The assignees and everyone in the loop are emailed that {total === 1 ? 'it was' : 'they were'} deleted. That notification cannot be recalled.</span>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onCancel} disabled={busy}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Cancel
          </button>
          <button type="button" onClick={onConfirm} disabled={busy}
            className={`px-4 py-2 rounded-lg text-[13px] font-bold text-white transition-opacity disabled:opacity-60 ${deleting ? 'bg-[var(--accent-red)]' : 'bg-[var(--accent-indigo)]'}`}>
            {busy ? (deleting ? 'Deleting…' : 'Restoring…') : (deleting ? `Yes, delete ${total === 1 ? '' : total}` : `Yes, restore ${total === 1 ? '' : total}`).trim()}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmActionModal;
