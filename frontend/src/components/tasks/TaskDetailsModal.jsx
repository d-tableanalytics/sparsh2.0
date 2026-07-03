import React, { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft, Trash2, FileText, History, Info, Users, Layers, Plus,
  Paperclip, MessageSquare, Send, CheckSquare, Square, X,
} from 'lucide-react';
import api from '../../services/api';
import {
  getTaskDetail, updateTaskStatus, addChecklistItem, updateChecklistItem,
  deleteChecklistItem, addTaskComment, uploadTaskAttachment, softDeleteTask,
} from '../../services/taskApi';
import { useNotification } from '../../context/NotificationContext';
import { STATUS_CONFIG, WORKFLOW_STATUSES } from './statusConfig';
import { getInitials, formatFrequencyLabel } from './taskDisplayUtils';

// Full single-task view: description, revision (status) history, core info,
// involved parties, sub-tasks/checklist, attachments, and a comment thread.
// Opened from the row menu in TaskListView ("Details").
const TaskDetailsModal = ({ isOpen, onClose, taskId, onChanged }) => {
  const { showSuccess, showError } = useNotification();
  const [task, setTask] = useState(null);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [newSubtask, setNewSubtask] = useState('');
  const [newComment, setNewComment] = useState('');
  const [posting, setPosting] = useState(false);

  const userMap = React.useMemo(() => {
    const m = {};
    users.forEach(u => { m[u._id] = u.full_name || u.email; });
    return m;
  }, [users]);

  const fetchDetail = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    try {
      const res = await getTaskDetail(taskId);
      setTask(res.data);
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to load task details');
    } finally {
      setLoading(false);
    }
  }, [taskId, showError]);

  useEffect(() => {
    if (!isOpen) return;
    fetchDetail();
    api.get('/tasks/assignable-users').then(res => setUsers(res.data || [])).catch(() => {});
  }, [isOpen, fetchDetail]);

  if (!isOpen) return null;

  const handleStatusChange = async (status) => {
    try {
      await updateTaskStatus(taskId, status);
      fetchDetail();
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update status');
    }
  };

  const handleDelete = async () => {
    try {
      await softDeleteTask(taskId);
      showSuccess('Task moved to Deleted Tasks');
      onChanged?.();
      onClose();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to delete task');
    }
  };

  const handleAddSubtask = async () => {
    const title = newSubtask.trim();
    if (!title) return;
    try {
      await addChecklistItem(taskId, title);
      setNewSubtask('');
      fetchDetail();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to add sub task');
    }
  };

  const handleToggleSubtask = async (item) => {
    try {
      await updateChecklistItem(taskId, item.id, { completed: !item.completed });
      fetchDetail();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update sub task');
    }
  };

  const handleRemoveSubtask = async (item) => {
    try {
      await deleteChecklistItem(taskId, item.id);
      fetchDetail();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to remove sub task');
    }
  };

  const handleAttach = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await uploadTaskAttachment(taskId, file);
      fetchDetail();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to attach file');
    } finally {
      e.target.value = '';
    }
  };

  const handleAddComment = async () => {
    const text = newComment.trim();
    if (!text) return;
    setPosting(true);
    try {
      await addTaskComment(taskId, text);
      setNewComment('');
      fetchDetail();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to post comment');
    } finally {
      setPosting(false);
    }
  };

  const cfg = task ? (STATUS_CONFIG[task.status] || STATUS_CONFIG.pending) : null;
  const checklistDone = task ? (task.checklist || []).filter(c => c.completed).length : 0;
  const checklistTotal = task ? (task.checklist || []).length : 0;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[300] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-2xl max-h-[88vh] overflow-y-auto no-scrollbar bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl">

          {/* Header */}
          <div className="px-6 py-4 border-b border-[var(--border)] flex items-center justify-between gap-3 sticky top-0 bg-[var(--bg-card)] z-10 flex-wrap">
            <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-widest">
              <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><ArrowLeft size={16} /></button>
              <span className="text-[var(--text-muted)]">Delegations</span>
              <span className="text-[var(--text-muted)]">/</span>
              <span className="text-[var(--accent-indigo)]">Details</span>
            </div>
            {task && (
              <div className="flex items-center gap-2 flex-wrap">
                <select value={task.status} onChange={e => handleStatusChange(e.target.value)}
                  className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border outline-none cursor-pointer"
                  style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>
                  {WORKFLOW_STATUSES.map(s => <option key={s} value={s}>{STATUS_CONFIG[s].label}</option>)}
                </select>
                {task.verificationRequired && (
                  <span className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]">
                    Verification Required
                  </span>
                )}
                <span className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--input-bg)] text-[var(--text-muted)] border-[var(--border)]">
                  {formatFrequencyLabel(task.frequency)}
                </span>
                {task.isCreator && (
                  <button onClick={handleDelete} className="p-2 rounded-lg text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)]" title="Delete task"><Trash2 size={15} /></button>
                )}
              </div>
            )}
          </div>

          {loading || !task ? (
            <div className="p-16 text-center text-[var(--text-muted)] text-[12px] font-bold">Loading task details...</div>
          ) : (
            <div className="p-6 space-y-5">
              <h2 className="text-xl font-black text-[var(--text-main)]">{task.title}</h2>

              {/* Description */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-2">
                  <FileText size={13} /> Description
                </p>
                <p className="text-[13px] font-medium text-[var(--text-main)]">{task.description || '—'}</p>
              </div>

              {/* Revision History */}
              {task.statusHistory?.length > 0 && (
                <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-3">
                    <History size={13} /> Revision History ({task.statusHistory.length})
                  </p>
                  <div className="space-y-3">
                    {[...task.statusHistory].reverse().map((h, i) => (
                      <div key={i} className="flex items-start justify-between gap-3 border-b border-[var(--border)] last:border-0 pb-3 last:pb-0">
                        <div className="min-w-0">
                          <p className="text-[11px] font-black text-[var(--text-main)]">Revision #{task.statusHistory.length - i}</p>
                          <p className="text-[11px] font-bold text-[var(--text-muted)]">
                            {STATUS_CONFIG[h.old_status]?.label || h.old_status} <span className="mx-1">→</span>
                            <span className="text-[var(--accent-indigo)]">{STATUS_CONFIG[h.new_status]?.label || h.new_status}</span>
                          </p>
                          {h.reason && <p className="mt-1 px-2 py-1 bg-[var(--accent-yellow-bg)] text-[var(--text-muted)] text-[11px] rounded-lg italic">"{h.reason}"</p>}
                          <p className="text-[10px] font-bold text-[var(--text-muted)] opacity-70 mt-1">By {h.changed_by_name || 'Unknown'}</p>
                        </div>
                        <span className="text-[10px] font-black text-[var(--text-muted)] shrink-0">{h.changed_at ? new Date(h.changed_at).toLocaleDateString() : ''}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                {/* Core Information */}
                <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4 space-y-3">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <Info size={13} /> Core Information
                  </p>
                  <div className="grid grid-cols-2 gap-3 text-[12px]">
                    <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Category</p><p className="font-bold text-[var(--text-main)]">{task.category || '—'}</p></div>
                    <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Priority</p><p className="font-bold text-[var(--text-main)]">{task.priority}</p></div>
                    <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Deadline</p><p className="font-bold text-[var(--text-main)]">{task.end ? new Date(task.end).toLocaleString() : '—'}</p></div>
                    <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Evidence</p><p className="font-bold text-[var(--text-main)]">{task.evidenceRequired ? 'Required' : 'Optional'}</p></div>
                    <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Verification</p><p className="font-bold text-[var(--text-main)]">{task.verificationRequired ? 'Required' : 'Not Required'}</p></div>
                  </div>
                </div>

                {/* Involved Parties */}
                <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4 space-y-3">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <Users size={13} /> Involved Parties
                  </p>
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-full flex items-center justify-center text-white font-black text-[10px] shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                      {getInitials(userMap[task.assignedBy])}
                    </div>
                    <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Assigned By</p><p className="text-[12px] font-bold text-[var(--text-main)]">{userMap[task.assignedBy] || 'Unknown'}</p></div>
                  </div>
                  {(task.assignedTo || []).map(id => (
                    <div key={id} className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-full flex items-center justify-center text-white font-black text-[10px] shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                        {getInitials(userMap[id])}
                      </div>
                      <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Assigned To</p><p className="text-[12px] font-bold text-[var(--text-main)]">{userMap[id] || 'Unknown'}</p></div>
                    </div>
                  ))}
                  {task.watchers?.length > 0 && (
                    <div>
                      <p className="text-[9px] font-black text-[var(--text-muted)] uppercase mb-1.5">In Loop</p>
                      <div className="flex flex-wrap gap-1.5">
                        {task.watchers.map(id => (
                          <span key={id} className="flex items-center gap-1 px-2 py-1 bg-[var(--bg-card)] border border-[var(--border)] rounded-full text-[10px] font-black">
                            <span className="w-4 h-4 rounded-full flex items-center justify-center text-white text-[8px]" style={{ background: 'var(--avatar-bg)' }}>{getInitials(userMap[id])}</span>
                            {userMap[id] || 'Unknown'}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="flex items-center justify-between text-[10px] font-black text-[var(--text-muted)] uppercase pt-2 border-t border-[var(--border)]">
                    <span>Created On</span><span>{task.createdAt ? new Date(task.createdAt).toLocaleDateString() : '—'}</span>
                  </div>
                  <div className="flex items-center justify-between text-[10px] font-black text-[var(--text-muted)] uppercase">
                    <span>Delegation ID</span><span className="opacity-60">{task.id?.slice(-8)}</span>
                  </div>
                </div>
              </div>

              {/* Sub Tasks */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-3">
                  <Layers size={13} /> Sub Tasks ({checklistDone}/{checklistTotal})
                </p>
                {checklistTotal === 0 ? (
                  <div className="py-6 flex flex-col items-center justify-center border-2 border-dashed border-[var(--border)] rounded-xl gap-2">
                    <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest opacity-70">No sub tasks yet</p>
                  </div>
                ) : (
                  <div className="space-y-1.5 mb-3">
                    {task.checklist.map(item => (
                      <div key={item.id} className="flex items-center gap-2 bg-[var(--bg-card)] rounded-lg px-3 py-2">
                        <button type="button" onClick={() => handleToggleSubtask(item)} className="text-[var(--accent-indigo)] shrink-0">
                          {item.completed ? <CheckSquare size={16} /> : <Square size={16} />}
                        </button>
                        <span className={`flex-1 text-[12px] font-bold text-[var(--text-main)] ${item.completed ? 'line-through opacity-50' : ''}`}>{item.title}</span>
                        <button type="button" onClick={() => handleRemoveSubtask(item)} className="text-[var(--text-muted)] hover:text-[var(--accent-red)]"><X size={13} /></button>
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <input value={newSubtask} onChange={e => setNewSubtask(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAddSubtask(); } }}
                    placeholder="Add a sub task..."
                    className="flex-1 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
                  <button type="button" onClick={handleAddSubtask} className="p-2 bg-[var(--accent-indigo)] text-white rounded-lg"><Plus size={15} /></button>
                </div>
              </div>

              {/* Attachments */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <Paperclip size={13} /> Attachments ({task.attachments?.length || 0})
                  </p>
                  <label className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent-indigo)] text-white rounded-lg text-[10px] font-black uppercase tracking-widest cursor-pointer">
                    Attach File
                    <input type="file" className="hidden" onChange={handleAttach} />
                  </label>
                </div>
                {(task.attachments || []).length > 0 && (
                  <div className="space-y-1.5">
                    {task.attachments.map(a => (
                      <a key={a.id} href={a.url} target="_blank" rel="noreferrer" className="flex items-center gap-2 text-[11px] font-bold text-[var(--text-main)] hover:text-[var(--accent-indigo)]">
                        <Paperclip size={12} className="text-[var(--text-muted)]" /> {a.name}
                      </a>
                    ))}
                  </div>
                )}
              </div>

              {/* Remark History (Chat) */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-3">
                  <MessageSquare size={13} /> Remark History (Chat)
                </p>
                {(task.remarks || []).length === 0 ? (
                  <div className="py-8 flex flex-col items-center justify-center gap-2">
                    <MessageSquare size={28} className="text-[var(--text-muted)] opacity-30" />
                    <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest opacity-70">No conversation yet</p>
                  </div>
                ) : (
                  <div className="space-y-3 mb-3 max-h-56 overflow-y-auto no-scrollbar">
                    {task.remarks.map(r => (
                      <div key={r.id} className="flex items-start gap-2">
                        <div className="w-7 h-7 rounded-full flex items-center justify-center text-white font-black text-[9px] shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                          {getInitials(r.author_name)}
                        </div>
                        <div className="min-w-0">
                          <p className="text-[11px] font-black text-[var(--text-main)]">{r.author_name}</p>
                          <p className="text-[12px] font-medium text-[var(--text-main)]">{r.text}</p>
                          <p className="text-[9px] font-bold text-[var(--text-muted)] opacity-70">{r.created_at ? new Date(r.created_at).toLocaleString() : ''}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <input value={newComment} onChange={e => setNewComment(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAddComment(); } }}
                    placeholder="Write a remark..."
                    className="flex-1 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
                  <button type="button" onClick={handleAddComment} disabled={posting} className="p-2 bg-[var(--accent-indigo)] text-white rounded-lg disabled:opacity-60"><Send size={15} /></button>
                </div>
              </div>
            </div>
          )}
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default TaskDetailsModal;
