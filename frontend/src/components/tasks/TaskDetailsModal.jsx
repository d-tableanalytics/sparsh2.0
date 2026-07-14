import React, { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft, Trash2, Pencil, FileText, History, Info, Users, Layers, Plus,
  Paperclip, MessageSquare, Send, CheckSquare, Square, X, Tags as TagsIcon,
  ShieldCheck, CheckCircle2, RotateCcw, CalendarClock, FileCheck2, Save, Bell,
} from 'lucide-react';
import api from '../../services/api';
import {
  getTaskDetail, updateTaskStatus, updateChecklistItem,
  deleteChecklistItem, addTaskComment, uploadTaskAttachment, softDeleteTask,
  uploadCompletionAttachment, deleteCompletionAttachment, reviseTaskDeadline,
  addTaskFollowUp,
} from '../../services/taskApi';
import { getHolidays } from '../../services/holidayApi';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { STATUS_CONFIG, REASON_REQUIRED_STATUSES } from './statusConfig';
import { getInitials, formatFrequencyLabel, formatDate, formatDateTime } from './taskDisplayUtils';
import TaskFormModal from './TaskFormModal';
import MiniDatePicker from './MiniDatePicker';
import StatusReasonModal from './StatusReasonModal';
import AttachmentItem from './AttachmentItem';

// Full single-task view: description, revision (status) history, core info,
// involved parties, sub-tasks/checklist, attachments, and a comment thread.
// Opened from the row menu in TaskListView ("Details").
const TaskDetailsModal = ({ isOpen, onClose, taskId, onChanged, onEdit }) => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const [task, setTask] = useState(null);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [newComment, setNewComment] = useState('');
  const [posting, setPosting] = useState(false);
  // Real subtasks (child tasks): add-form + nested detail view + taxonomy for the form.
  const [subtaskFormOpen, setSubtaskFormOpen] = useState(false);
  const [subtaskDetailId, setSubtaskDetailId] = useState(null);
  const [metaCats, setMetaCats] = useState([]);
  const [metaTags, setMetaTags] = useState([]);
  const [uploadingEvidence, setUploadingEvidence] = useState(false);
  const [deadlinePickerOpen, setDeadlinePickerOpen] = useState(false);
  const [savingDeadline, setSavingDeadline] = useState(false);
  // Reopen requires the assigner to set a NEW deadline before the task goes back to the assignee.
  const [reopenPickerOpen, setReopenPickerOpen] = useState(false);
  const [reopening, setReopening] = useState(false);
  // Follow-Up (In-Loop members): a nudge + remark.
  const [followUpText, setFollowUpText] = useState('');
  const [postingFollowUp, setPostingFollowUp] = useState(false);
  // In-Loop top controls: which quick-input (Follow Up / Remark) is expanded.
  const [inLoopBox, setInLoopBox] = useState(null); // 'followup' | 'remark' | null
  // Holidays + Sunday weekly-off block selection in the Revision / Reopen / Date-Revision pickers,
  // matching the create form. There is no persisted per-user weekly-off, so Sunday (0) is used.
  const [holidayDates, setHolidayDates] = useState([]);
  const WEEKLY_OFFS = [0];
  // Target status awaiting a Doer Name + Reason (Dependent on Other / Blocked).
  const [reasonStatus, setReasonStatus] = useState(null);
  const [savingReason, setSavingReason] = useState(false);
  // Working copy of the checklist — ticking/removing items edits this locally and only
  // persists when the user clicks Save (so a click no longer auto-saves each toggle).
  const [localChecklist, setLocalChecklist] = useState([]);
  const [savingChecklist, setSavingChecklist] = useState(false);

  const userMap = React.useMemo(() => {
    const m = {};
    users.forEach(u => { m[u._id] = u.full_name || u.email; });
    return m;
  }, [users]);

  // `silent` refetches update the data in place WITHOUT flipping `loading` — so the modal
  // never flashes its "Loading task details..." state after in-modal actions (status
  // change, comment, attach, deadline revise). Only the very first open shows the spinner.
  const fetchDetail = useCallback(async ({ silent = false } = {}) => {
    if (!taskId) return;
    if (!silent) setLoading(true);
    try {
      const res = await getTaskDetail(taskId);
      setTask(res.data);
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to load task details');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [taskId, showError]);

  useEffect(() => {
    if (!isOpen) return;
    fetchDetail();
    api.get('/tasks/assignable-users').then(res => setUsers(res.data || [])).catch(() => {});
    // Categories/tags for the "Add Subtask" form.
    api.get('/task-categories').then(r => setMetaCats((r.data || []).map(c => c.name).filter(Boolean))).catch(() => {});
    api.get('/task-tags').then(r => setMetaTags((r.data || []).map(t => t.name).filter(Boolean))).catch(() => {});
    // Holidays block dates in the Revision / Reopen / Date-Revision pickers.
    getHolidays().then(res => setHolidayDates((res.data || []).map(h => h.holiday_date).filter(Boolean))).catch(() => setHolidayDates([]));
  }, [isOpen, fetchDetail]);

  // Reset the working copy whenever the SERVER checklist changes (open, or after a Save) —
  // keyed on its content signature so unrelated silent refetches (comment/status/attach)
  // don't wipe unsaved local ticks.
  const checklistSig = JSON.stringify(task?.checklist || []);
  useEffect(() => {
    setLocalChecklist((task?.checklist || []).map(c => ({ ...c })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, checklistSig]);

  if (!isOpen) return null;

  // Dependent on Other / Blocked need a Doer Name + Reason first — open the modal and let
  // its submit call doStatusUpdate. Everything else applies immediately.
  const handleStatusChange = (status) => {
    if (REASON_REQUIRED_STATUSES.includes(status)) {
      setReasonStatus(status);
      return;
    }
    doStatusUpdate(status);
  };

  const doStatusUpdate = async (status, { reason, doerName, doerId } = {}) => {
    if (status === 'completed') {
      // Completion rule: a task can't be marked Completed until all check points are done.
      const items = task?.checklist || [];
      const pending = items.filter(c => !c.completed);
      if (pending.length) {
        showError(`Complete all check points first (${items.length - pending.length}/${items.length} done).`);
        return;
      }
      // Evidence Required: block completion until at least one evidence file is uploaded
      // (backend enforces this too — this is just the immediate, friendly message).
      if (task?.evidenceRequired && !(task?.completionAttachments || []).length) {
        showError('Evidence upload is required before completing this task.');
        return;
      }
    }
    if (reasonStatus) setSavingReason(true);
    try {
      await updateTaskStatus(taskId, status, reason, doerName, doerId);
      // Verification-required tasks completed by the assignee are routed to "verification"
      // by the backend — the silent refetch below reflects whatever the server decided.
      if (status === 'completed' && task?.verificationRequired && !canManage) {
        showSuccess('Submitted for verification');
      }
      fetchDetail({ silent: true });
      onChanged?.();
      setReasonStatus(null);
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update status');
    } finally {
      setSavingReason(false);
    }
  };

  // Verification actions — assigner/delegator only (backend also enforces).
  const handleFinalComplete = async () => {
    try {
      await updateTaskStatus(taskId, 'completed');
      showSuccess('Task verified & completed');
      fetchDetail({ silent: true });
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to complete task');
    }
  };

  // Reopen must carry a NEW deadline (spec): open the date picker first; the actual reopen
  // happens in handleReopenWithDeadline once the assigner picks a date.
  const handleReopen = () => setReopenPickerOpen(true);

  const handleReopenWithDeadline = async (iso) => {
    setReopenPickerOpen(false);
    setReopening(true);
    try {
      // Set the new deadline first (assigner-only endpoint), then flip status to Reopened and
      // hand the task back to the assignee. Reuses the existing deadline + status APIs.
      await reviseTaskDeadline(taskId, iso, 'Reopened by assigner');
      await updateTaskStatus(taskId, 'in_progress_reopened');
      showSuccess('Task reopened with a new deadline');
      fetchDetail({ silent: true });
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to reopen task');
    } finally {
      setReopening(false);
    }
  };

  // Follow-Up — In-Loop members (watchers) / participants nudge with a remark.
  const handleAddFollowUp = async () => {
    const remark = followUpText.trim();
    if (!remark) return;
    setPostingFollowUp(true);
    try {
      await addTaskFollowUp(taskId, remark);
      setFollowUpText('');
      showSuccess('Follow-up added');
      fetchDetail({ silent: true });
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to add follow-up');
    } finally {
      setPostingFollowUp(false);
    }
  };

  const handleReviseDeadline = async (iso) => {
    setSavingDeadline(true);
    try {
      await reviseTaskDeadline(taskId, iso);
      showSuccess('Deadline revised');
      fetchDetail({ silent: true });
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to revise deadline');
    } finally {
      setSavingDeadline(false);
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

  // Local-only edits — persisted together by handleSaveChecklist.
  const handleToggleSubtask = (item) => {
    setLocalChecklist(list => list.map(c => (c.id === item.id ? { ...c, completed: !c.completed } : c)));
  };

  const handleRemoveSubtask = (item) => {
    setLocalChecklist(list => list.filter(c => c.id !== item.id));
  };

  const handleSaveChecklist = async () => {
    const orig = task?.checklist || [];
    const localIds = new Set(localChecklist.map(c => c.id));
    const toDelete = orig.filter(o => !localIds.has(o.id));
    const toToggle = localChecklist.filter(l => {
      const o = orig.find(x => x.id === l.id);
      return o && !!o.completed !== !!l.completed;
    });
    if (!toDelete.length && !toToggle.length) return;
    setSavingChecklist(true);
    try {
      await Promise.all([
        ...toDelete.map(o => deleteChecklistItem(taskId, o.id)),
        ...toToggle.map(l => updateChecklistItem(taskId, l.id, { completed: l.completed })),
      ]);
      showSuccess('Check points saved');
      fetchDetail({ silent: true });
      onChanged?.();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save check points');
    } finally {
      setSavingChecklist(false);
    }
  };

  const handleAttach = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await uploadTaskAttachment(taskId, file);
      fetchDetail({ silent: true });
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to attach file');
    } finally {
      e.target.value = '';
    }
  };

  // Completion evidence — uploaded/removed against the separate completion_attachments store.
  const handleEvidenceAttach = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingEvidence(true);
    try {
      await uploadCompletionAttachment(taskId, file);
      fetchDetail({ silent: true });
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to upload evidence');
    } finally {
      setUploadingEvidence(false);
      e.target.value = '';
    }
  };

  const handleRemoveEvidence = async (attachmentId) => {
    try {
      await deleteCompletionAttachment(taskId, attachmentId);
      fetchDetail({ silent: true });
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to remove evidence');
    }
  };

  const handleAddComment = async () => {
    const text = newComment.trim();
    if (!text) return;
    setPosting(true);
    try {
      await addTaskComment(taskId, text);
      setNewComment('');
      fetchDetail({ silent: true });
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to post comment');
    } finally {
      setPosting(false);
    }
  };

  const cfg = task ? (STATUS_CONFIG[task.status] || STATUS_CONFIG.pending) : null;
  // Edit/Delete are available to the creator and to admins (backend enforces the same on
  // update/delete). Assignees / in-loop users can view + change status but not edit/delete.
  const canManage = !!task && (task.isCreator || ['superadmin', 'admin'].includes(user?.role));
  // Counts + progress reflect the local working copy so ticks show instantly (pre-Save).
  const checklistDone = localChecklist.filter(c => c.completed).length;
  const checklistTotal = localChecklist.length;
  // Unsaved changes = an item removed, or a completed-state flipped vs the server copy.
  const origChecklist = task?.checklist || [];
  const localChecklistIds = new Set(localChecklist.map(c => c.id));
  const checklistDirty = origChecklist.some(o => !localChecklistIds.has(o.id))
    || localChecklist.some(l => { const o = origChecklist.find(x => x.id === l.id); return o && !!o.completed !== !!l.completed; });
  // A verification-required task the assignee has submitted is now the assigner's to
  // finalize or reopen — the assignee-side status control is hidden while it's here.
  const isAwaitingVerification = !!task && task.verificationRequired && task.status === 'verification';
  // In-Loop member (watcher) of this task — gets the Follow-Up action. Everyone involved can
  // still see the follow-up count + history; only in-loop members can raise a new follow-up.
  const isInLoop = !!task && (task.watchers || []).includes(user?._id);
  // Assignee-side "Revision": the assignee can set a new deadline (calendar) when they can't
  // finish by the current one. Available while the task is still theirs to work on (not
  // completed, and not handed to the assigner for verification). The assigner keeps the
  // separate "Revise" action (canManage) already shown next to the deadline.
  const isAssignee = !!task && (task.assignedTo || []).includes(user?._id);
  // Self-assigned task (creator is the doer, no other assignees) — the creator works it like an assignee.
  const isSelfTask = !!task && task.isCreator && !(task.assignedTo || []).length;
  // Who drives the working-status dropdown: the assignee, or the creator of a self-task.
  const canWork = isAssignee || isSelfTask;
  // Pure In-Loop member (watcher, not the doer or the assigner) — e.g. a Subscribed task.
  const isPureWatcher = !!task && isInLoop && !isAssignee && !task.isCreator;
  // Editing/deleting the task definition belongs to the assigner (creator) / admins — NOT the
  // assignee (their "My Tasks" view) and NOT a pure watcher (their Subscribed view). So hide
  // Edit + Delete for a doer who isn't also the creator, and for in-loop-only members.
  const canEditOrDelete = canManage && !(isAssignee && !task?.isCreator) && !isPureWatcher;

  // ─── Role-based working dropdown (assignee / dependent-on-other doer) ───
  // "Pending" is surfaced as "In Progress"; "Revision" opens the deadline calendar (no status
  // change). The closed control shows the current status; the options are exactly the role set.
  const REVISION_OPT = '__revision__';
  const curDisplayStatus = task?.status === 'pending' ? 'in_progress' : task?.status;
  const curCfg = (task && (STATUS_CONFIG[curDisplayStatus] || cfg)) || {};
  const curLabel = STATUS_CONFIG[curDisplayStatus]?.label || curDisplayStatus || '';
  // Completed submits for verification when Verification Required is on (assignee, not assigner).
  const completedLabel = (task?.verificationRequired && canWork && !canManage) ? 'Submit for Verification' : 'Completed';
  // Dependent-on-Other doer → Completed, Revision, Dependent on Other, Blocked.
  // Normal assignee → Accept, Dependent on Other, Blocked, Completed, Revision.
  const workingActions = task?.status === 'dependent_on_others'
    ? [['completed', completedLabel], [REVISION_OPT, 'Revision'], ['dependent_on_others', 'Dependent on Other'], ['blocked', 'In Process-Pending']]
    : [['accepted', 'Acknowledged Delegation'], ['dependent_on_others', 'Dependent on Other'], ['blocked', 'In Process-Pending'], ['completed', completedLabel], [REVISION_OPT, 'Revision']];
  // Only show the current status as a separate (disabled) line when it isn't already one of the
  // action options — otherwise it would duplicate it (e.g. two "Accept" entries).
  const showCurrentOpt = !workingActions.some(([v]) => v === curDisplayStatus);
  const handleWorkingSelect = (val) => {
    if (val === REVISION_OPT) { setDeadlinePickerOpen(true); return; }
    handleStatusChange(val);
  };

  return (
    <>
    <AnimatePresence>
      <div className="fixed inset-0 z-[300] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-2xl max-h-[88vh] overflow-y-auto no-scrollbar bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl">

          {/* Header */}
          <div className="px-6 py-4 border-b border-[var(--border)] sticky top-0 bg-[var(--bg-card)] z-10">
            {/* Top row: breadcrumb on the left, close (×) always pinned top-right. */}
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-[11px] font-black uppercase tracking-widest">
                <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><ArrowLeft size={16} /></button>
                <span className="text-[var(--text-muted)]">Delegations</span>
                <span className="text-[var(--text-muted)]">/</span>
                <span className="text-[var(--accent-indigo)]">Details</span>
              </div>
              <button type="button" onClick={onClose} title="Close"
                className="p-1.5 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors shrink-0">
                <X size={18} />
              </button>
            </div>
            {task && (
              <div className="flex items-center gap-2 flex-wrap mt-3">
                {isInLoop && !isAssignee && !task.isCreator ? (
                  // Pure In-Loop member (watcher, not the doer or the assigner) — including admins:
                  // no status changes, only Follow Up, Follow-Up Count, Remark.
                  <div className="flex items-center gap-2 flex-wrap w-full">
                    <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]">
                      <Bell size={12} /> Follow-Ups: {task.followUpCount ?? (task.followUps || []).length}
                    </span>
                    <button type="button" onClick={() => setInLoopBox(b => (b === 'followup' ? null : 'followup'))}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border hover:opacity-90 ${inLoopBox === 'followup' ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)]' : 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]'}`}>
                      <Bell size={13} /> Follow Up
                    </button>
                    {inLoopBox === 'followup' && (
                      <div className="flex items-center gap-2 w-full">
                        <input autoFocus value={followUpText} onChange={e => setFollowUpText(e.target.value)}
                          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAddFollowUp(); } }}
                          placeholder="Add a follow-up remark..."
                          className="flex-1 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
                        <button type="button" onClick={handleAddFollowUp} disabled={postingFollowUp || !followUpText.trim()}
                          className="flex items-center gap-1.5 px-3 py-2 bg-[var(--accent-indigo)] text-white rounded-lg text-[10px] font-black uppercase tracking-widest disabled:opacity-50 shrink-0">
                          <Bell size={13} /> {postingFollowUp ? '...' : 'Follow Up'}
                        </button>
                      </div>
                    )}
                  </div>
                ) : isAwaitingVerification ? (
                  // Verification hand-off: the delegator/assigner gets the Final Complete /
                  // Reopen actions; the assignee only sees a read-only "Pending Verification"
                  // badge (no assignee-side completion controls here).
                  canManage ? (
                    <>
                      <span className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border" style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>
                        {cfg.label}
                      </span>
                      <button onClick={handleFinalComplete}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--accent-green-bg)] text-[var(--accent-green)] border-[var(--accent-green-border)] hover:opacity-90">
                        <CheckCircle2 size={13} /> Final Complete
                      </button>
                      <button onClick={handleReopen} disabled={reopening}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--accent-orange-bg)] text-[var(--accent-orange)] border-[var(--accent-orange-border)] hover:opacity-90 disabled:opacity-50">
                        <RotateCcw size={13} /> {reopening ? 'Reopening…' : 'Reopen (New Deadline)'}
                      </button>
                    </>
                  ) : (
                    <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border" style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.border }}>
                      <ShieldCheck size={13} /> {cfg.label}
                    </span>
                  )
                ) : canWork ? (
                  // Assignee / dependent-on-other doer: role-based working options. The closed
                  // control shows the current status; the list is exactly the role's action set.
                  <select value={curDisplayStatus} onChange={e => handleWorkingSelect(e.target.value)}
                    className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border outline-none cursor-pointer"
                    style={{ background: curCfg.bg, color: curCfg.color, borderColor: curCfg.border }}>
                    {showCurrentOpt && <option value={curDisplayStatus} disabled>{curLabel}</option>}
                    {workingActions.map(([val, label]) => <option key={val} value={val}>{label}</option>)}
                  </select>
                ) : (
                  // Assigner/admin (not the doer): status is read-only here. Their actions are
                  // Final Complete / Reopen (during verification) + Date Revision + Edit/Delete.
                  <span className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border" style={{ background: curCfg.bg, color: curCfg.color, borderColor: curCfg.border }}>
                    {curLabel}
                  </span>
                )}
                {task.verificationRequired && (
                  <span className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)]">
                    Verification Required
                  </span>
                )}
                <span className="px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--input-bg)] text-[var(--text-muted)] border-[var(--border)]">
                  {formatFrequencyLabel(task.frequency)}
                </span>
                {canEditOrDelete && (
                  <>
                    <button onClick={() => onEdit?.(task)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)] hover:opacity-90">
                      <Pencil size={13} /> Edit Task
                    </button>
                    <button onClick={handleDelete}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-wider border bg-[var(--accent-red-bg)] text-[var(--accent-red)] border-[var(--accent-red-border)] hover:opacity-90">
                      <Trash2 size={13} /> Delete Task
                    </button>
                  </>
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
                          {h.doer_name && <p className="mt-1 text-[10px] font-bold text-[var(--text-muted)]">Doer: <span className="text-[var(--text-main)]">{h.doer_name}</span></p>}
                          {h.reason && <p className="mt-1 px-2 py-1 bg-[var(--accent-yellow-bg)] text-[var(--text-muted)] text-[11px] rounded-lg italic">"{h.reason}"</p>}
                          <p className="text-[10px] font-bold text-[var(--text-muted)] opacity-70 mt-1">By {h.changed_by_name || 'Unknown'}</p>
                        </div>
                        <span className="text-[10px] font-black text-[var(--text-muted)] shrink-0">{h.changed_at ? formatDate(h.changed_at) : ''}</span>
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
                    <div className="col-span-2">
                      <p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Deadline</p>
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="font-bold text-[var(--text-main)]">{task.end ? formatDateTime(task.end) : '—'}</p>
                        {/* Date Revision — assigner/delegator (backend-enforced). */}
                        {canManage && (
                          <button type="button" onClick={() => setDeadlinePickerOpen(true)} disabled={savingDeadline}
                            className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[9px] font-black uppercase tracking-wider border bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)] hover:opacity-90 disabled:opacity-50">
                            <CalendarClock size={11} /> {savingDeadline ? 'Saving...' : 'Revise'}
                          </button>
                        )}
                      </div>
                    </div>
                    <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Evidence</p><p className="font-bold text-[var(--text-main)]">{task.evidenceRequired ? 'Required' : 'Optional'}</p></div>
                    <div><p className="text-[9px] font-black text-[var(--text-muted)] uppercase">Verification</p><p className="font-bold text-[var(--text-main)]">{task.verificationRequired ? 'Required' : 'Not Required'}</p></div>
                  </div>
                  {/* Deadline revision history (assigner-only actions, but everyone can see the trail). */}
                  {(task.deadlineHistory || []).length > 0 && (
                    <div className="pt-2 border-t border-[var(--border)]">
                      <p className="flex items-center gap-1.5 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider mb-1.5">
                        <History size={11} /> Deadline Revisions ({task.deadlineHistory.length})
                      </p>
                      <div className="space-y-1.5">
                        {[...task.deadlineHistory].reverse().map((h, i) => (
                          <div key={i} className="text-[10px] font-bold text-[var(--text-muted)]">
                            {h.old_end ? formatDate(h.old_end) : '—'} <span className="mx-1">→</span>
                            <span className="text-[var(--accent-indigo)]">{h.new_end ? formatDate(h.new_end) : '—'}</span>
                            <span className="opacity-70"> · {h.revised_by_name || 'Unknown'}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {/* Tags — mirrors the green pill style used in the task form; shows every tag
                      saved on the task (persists across refresh since it reads task.tags). */}
                  <div>
                    <p className="text-[9px] font-black text-[var(--text-muted)] uppercase mb-1.5">Tags</p>
                    {(task.tags || []).length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {task.tags.map(tag => (
                          <span key={tag} className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[9px] font-black uppercase tracking-wider bg-[var(--accent-green)] text-white border border-[var(--accent-green)]">
                            <TagsIcon size={10} /> {tag}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <p className="text-[12px] font-bold text-[var(--text-main)]">—</p>
                    )}
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
                    <span>Created On</span><span>{task.createdAt ? formatDate(task.createdAt) : '—'}</span>
                  </div>
                  <div className="flex items-center justify-between text-[10px] font-black text-[var(--text-muted)] uppercase">
                    <span>Delegation ID</span><span className="opacity-60">{task.id?.slice(-8)}</span>
                  </div>
                </div>
              </div>

              {/* Check Points (checklist) */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <div className="flex items-center justify-between mb-3">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <CheckSquare size={13} /> Check Points ({checklistDone}/{checklistTotal})
                  </p>
                  {checklistTotal > 0 && (
                    <span className="text-[10px] font-black text-[var(--accent-indigo)]">{Math.round((checklistDone / checklistTotal) * 100)}%</span>
                  )}
                </div>
                {checklistTotal > 0 && (
                  <div className="h-1.5 w-full rounded-full bg-[var(--bg-card)] overflow-hidden mb-3">
                    <div className="h-full rounded-full bg-[var(--accent-indigo)] transition-all duration-300"
                      style={{ width: `${(checklistDone / checklistTotal) * 100}%` }} />
                  </div>
                )}
                {checklistTotal === 0 ? (
                  <div className="py-6 flex flex-col items-center justify-center border-2 border-dashed border-[var(--border)] rounded-xl gap-2 mb-3">
                    <CheckSquare size={24} className="text-[var(--text-muted)] opacity-30" />
                    <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest opacity-70">No check points yet</p>
                  </div>
                ) : (
                  <div className="space-y-1.5 mb-3">
                    {localChecklist.map(item => (
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
                {/* Save appears only when there are unsaved tick/remove changes. */}
                {checklistDirty && (
                  <div className="flex justify-end">
                    <button type="button" onClick={handleSaveChecklist} disabled={savingChecklist}
                      className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-[10px] font-black uppercase tracking-widest bg-[var(--accent-indigo)] text-white shadow-sm hover:opacity-90 disabled:opacity-60">
                      <Save size={13} /> {savingChecklist ? 'Saving...' : 'Save'}
                    </button>
                  </div>
                )}
              </div>

              {/* Subtasks (real child tasks linked by parent_task_id) */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <div className="flex items-center justify-between mb-3">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <Layers size={13} /> Subtasks ({(task.subtasks || []).length})
                  </p>
                  <button type="button" onClick={() => setSubtaskFormOpen(true)}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent-indigo)] text-white rounded-lg text-[10px] font-black uppercase tracking-widest">
                    <Plus size={13} /> Add Subtask
                  </button>
                </div>
                {(task.subtasks || []).length === 0 ? (
                  <button type="button" onClick={() => setSubtaskFormOpen(true)}
                    className="w-full py-6 flex flex-col items-center justify-center border-2 border-dashed border-[var(--border)] rounded-xl gap-2 hover:border-[var(--accent-indigo)] transition-colors">
                    <Layers size={24} className="text-[var(--text-muted)] opacity-30" />
                    <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest opacity-70">No subtasks yet — tap to add</p>
                  </button>
                ) : (
                  <div className="space-y-1.5">
                    {task.subtasks.map(st => {
                      const scfg = STATUS_CONFIG[st.status] || STATUS_CONFIG.pending;
                      return (
                        <button type="button" key={st.id} onClick={() => setSubtaskDetailId(st.id)}
                          className="w-full flex items-center gap-2.5 bg-[var(--bg-card)] rounded-lg px-3 py-2.5 text-left hover:border-[var(--accent-indigo)] border border-transparent transition-all">
                          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: scfg.color }} />
                          <span className="flex-1 min-w-0">
                            <span className="block text-[12px] font-bold text-[var(--text-main)] truncate">{st.title}</span>
                            {(st.assignedTo || []).length > 0 && (
                              <span className="block text-[10px] text-[var(--text-muted)] truncate">{st.assignedTo.map(id => userMap[id] || id).join(', ')}</span>
                            )}
                          </span>
                          <span className="px-2 py-0.5 rounded-lg text-[9px] font-black uppercase tracking-wider shrink-0" style={{ color: scfg.color, background: 'var(--input-bg)' }}>{scfg.label}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Assignment Attachments — files added when the task was created/assigned. */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <Paperclip size={13} /> Assignment Attachments ({task.attachments?.length || 0})
                  </p>
                  <label className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent-indigo)] text-white rounded-lg text-[10px] font-black uppercase tracking-widest cursor-pointer">
                    Attach File
                    <input type="file" className="hidden" onChange={handleAttach} />
                  </label>
                </div>
                {(task.attachments || []).length > 0 ? (
                  <div className="space-y-2">
                    {task.attachments.map(a => (
                      <AttachmentItem key={a.id} attachment={a} />
                    ))}
                  </div>
                ) : (
                  <p className="text-[10px] font-bold text-[var(--text-muted)] opacity-70">No assignment attachments.</p>
                )}
              </div>

              {/* Completion Evidence — files uploaded while completing the task, kept
                  entirely separate from the assignment attachments above (#16). Required
                  before completion when Evidence Required is active (#14). */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                    <FileCheck2 size={13} /> Completion Evidence ({task.completionAttachments?.length || 0})
                    {task.evidenceRequired && (
                      <span className="px-1.5 py-0.5 rounded text-[8px] font-black uppercase tracking-wider bg-[var(--accent-red-bg)] text-[var(--accent-red)] border border-[var(--accent-red-border)]">Required</span>
                    )}
                  </p>
                  <label className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--accent-green)] text-white rounded-lg text-[10px] font-black uppercase tracking-widest cursor-pointer">
                    {uploadingEvidence ? 'Uploading...' : 'Upload Evidence'}
                    <input type="file" className="hidden" onChange={handleEvidenceAttach} disabled={uploadingEvidence} />
                  </label>
                </div>
                {task.evidenceRequired && !(task.completionAttachments || []).length && (
                  <p className="mb-2 text-[10px] font-bold text-[var(--accent-red)]">Evidence upload is required before completing this task.</p>
                )}
                {(task.completionAttachments || []).length > 0 ? (
                  <div className="space-y-2">
                    {task.completionAttachments.map(a => (
                      <AttachmentItem key={a.id} attachment={a} onRemove={() => handleRemoveEvidence(a.id)}
                        icon={FileCheck2} iconClass="text-[var(--accent-green)]" linkHover="hover:text-[var(--accent-green)]" />
                    ))}
                  </div>
                ) : (
                  <p className="text-[10px] font-bold text-[var(--text-muted)] opacity-70">No completion evidence uploaded yet.</p>
                )}
              </div>

              {/* Follow-Ups — raised by In-Loop members (watchers). Count = follow-up list length.
                  Everyone involved sees the count + history; only in-loop members can add one. */}
              <div className="bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-4">
                <p className="flex items-center gap-1.5 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-3">
                  <Bell size={13} /> Follow-Ups ({task.followUpCount ?? (task.followUps || []).length})
                </p>
                {(task.followUps || []).length === 0 ? (
                  <div className="py-6 flex flex-col items-center justify-center gap-2">
                    <Bell size={24} className="text-[var(--text-muted)] opacity-30" />
                    <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest opacity-70">No follow-ups yet</p>
                  </div>
                ) : (
                  <div className="space-y-3 mb-3 max-h-56 overflow-y-auto no-scrollbar">
                    {[...task.followUps].reverse().map(f => (
                      <div key={f.id} className="flex items-start gap-2">
                        <div className="w-7 h-7 rounded-full flex items-center justify-center text-white font-black text-[9px] shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                          {getInitials(f.by_name)}
                        </div>
                        <div className="min-w-0">
                          <p className="text-[11px] font-black text-[var(--text-main)]">{f.by_name}</p>
                          <p className="text-[12px] font-medium text-[var(--text-main)]">{f.remark}</p>
                          <p className="text-[9px] font-bold text-[var(--text-muted)] opacity-70">{f.created_at ? formatDateTime(f.created_at) : ''}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {isInLoop ? (
                  <div className="flex items-center gap-2">
                    <input value={followUpText} onChange={e => setFollowUpText(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleAddFollowUp(); } }}
                      placeholder="Add a follow-up remark..."
                      className="flex-1 px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
                    <button type="button" onClick={handleAddFollowUp} disabled={postingFollowUp || !followUpText.trim()}
                      className="flex items-center gap-1.5 px-3 py-2 bg-[var(--accent-indigo)] text-white rounded-lg text-[10px] font-black uppercase tracking-widest disabled:opacity-50 shrink-0">
                      <Bell size={13} /> {postingFollowUp ? '...' : 'Follow Up'}
                    </button>
                  </div>
                ) : (
                  <p className="text-[10px] font-bold text-[var(--text-muted)] opacity-70">Only In-Loop members can raise a follow-up.</p>
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
                          <p className="text-[9px] font-bold text-[var(--text-muted)] opacity-70">{r.created_at ? formatDateTime(r.created_at) : ''}</p>
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

    {/* Deadline / Date Revision picker — assigner-only (button only shown when canManage). */}
    <MiniDatePicker
      isOpen={deadlinePickerOpen}
      onClose={() => setDeadlinePickerOpen(false)}
      value={task?.end}
      title="Revise Deadline"
      onApply={(iso) => handleReviseDeadline(iso)}
      holidayDates={holidayDates} weeklyOffs={WEEKLY_OFFS} onBlocked={showError}
    />

    {/* Reopen picker — the assigner must set a NEW deadline; only then is the task reopened
        and handed back to the assignee. */}
    <MiniDatePicker
      isOpen={reopenPickerOpen}
      onClose={() => setReopenPickerOpen(false)}
      value={task?.end}
      title="New Deadline for Reopen"
      onApply={(iso) => handleReopenWithDeadline(iso)}
      holidayDates={holidayDates} weeklyOffs={WEEKLY_OFFS} onBlocked={showError}
    />

    {/* Doer Name + Reason capture for Dependent on Other / Blocked. */}
    <StatusReasonModal
      isOpen={!!reasonStatus}
      status={reasonStatus}
      users={users}
      saving={savingReason}
      onClose={() => setReasonStatus(null)}
      onSubmit={({ reason, doerName, doerId }) => doStatusUpdate(reasonStatus, { reason, doerName, doerId })}
    />

    {/* Add Subtask — a real child task linked by parent_task_id */}
    <TaskFormModal
      isOpen={subtaskFormOpen}
      parentId={taskId}
      categories={metaCats}
      tags={metaTags}
      onClose={() => setSubtaskFormOpen(false)}
      onSaved={() => { setSubtaskFormOpen(false); fetchDetail({ silent: true }); onChanged?.(); }}
    />

    {/* Nested subtask detail (its own status / check points / subtasks) */}
    {subtaskDetailId && (
      <TaskDetailsModal
        isOpen
        taskId={subtaskDetailId}
        onClose={() => setSubtaskDetailId(null)}
        onChanged={() => { fetchDetail({ silent: true }); onChanged?.(); }}
        onEdit={onEdit}
      />
    )}
    </>
  );
};

export default TaskDetailsModal;
