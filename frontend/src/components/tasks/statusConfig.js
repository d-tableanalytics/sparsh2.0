import {
  Clock, CheckCircle2, PlayCircle, Link2, Ban, Eye, CheckCircle, AlertTriangle,
} from 'lucide-react';

// Central status → visual mapping for the Task Management module. Deliberately reuses
// ONLY the project's existing 5 accent tokens (green/orange/red/yellow/indigo, from
// index.css) instead of one-off hex values, so it stays visually consistent with the
// rest of the app. Green is reserved for "done" states to match the module's green
// sidebar branding.
export const STATUS_CONFIG = {
  pending: { label: 'Pending', shortLabel: 'Pending', icon: Clock, color: 'var(--text-muted)', bg: 'var(--input-bg)', border: 'var(--border)' },
  accepted: { label: 'Accepted', shortLabel: 'Accepted', icon: CheckCircle2, color: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', border: 'var(--accent-indigo-border)' },
  in_progress: { label: 'In Progress', shortLabel: 'In Progress', icon: PlayCircle, color: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', border: 'var(--accent-orange-border)' },
  dependent_on_others: { label: 'Dependent on Others', shortLabel: 'Dependent', icon: Link2, color: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)', border: 'var(--accent-yellow-border)' },
  blocked: { label: 'Blocked', shortLabel: 'Blocked', icon: Ban, color: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)' },
  verification: { label: 'Verification', shortLabel: 'Verification', icon: Eye, color: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', border: 'var(--accent-indigo-border)' },
  completed: { label: 'Completed', shortLabel: 'Completed', icon: CheckCircle, color: 'var(--accent-green)', bg: 'var(--accent-green-bg)', border: 'var(--accent-green-border)' },
};

export const EXTRA_CARD_CONFIG = {
  totalTasks: { label: 'Total Tasks', shortLabel: 'Total', icon: CheckCircle2, color: 'var(--text-main)', bg: 'var(--input-bg)', border: 'var(--border)' },
  overdue: { label: 'Overdue', shortLabel: 'Overdue', icon: AlertTriangle, color: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)' },
  inTime: { label: 'In Time', shortLabel: 'In Time', icon: CheckCircle, color: 'var(--accent-green)', bg: 'var(--accent-green-bg)', border: 'var(--accent-green-border)' },
  delayed: { label: 'Delayed', shortLabel: 'Delayed', icon: AlertTriangle, color: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)' },
};

// Maps a summary-card response key to the underlying workflow_status value used for filtering.
export const CARD_KEY_TO_STATUS = {
  pending: 'pending',
  accepted: 'accepted',
  inProgress: 'in_progress',
  dependentOnOthers: 'dependent_on_others',
  blocked: 'blocked',
  verification: 'verification',
  completed: 'completed',
};

// Full 11-card order (Dashboard page): adds In Time / Delayed on top of the workflow states.
export const SUMMARY_CARD_ORDER = [
  ['totalTasks', EXTRA_CARD_CONFIG.totalTasks],
  ['overdue', EXTRA_CARD_CONFIG.overdue],
  ['pending', STATUS_CONFIG.pending],
  ['accepted', STATUS_CONFIG.accepted],
  ['dependentOnOthers', STATUS_CONFIG.dependent_on_others],
  ['blocked', STATUS_CONFIG.blocked],
  ['inProgress', STATUS_CONFIG.in_progress],
  ['verification', STATUS_CONFIG.verification],
  ['completed', STATUS_CONFIG.completed],
  ['inTime', EXTRA_CARD_CONFIG.inTime],
  ['delayed', EXTRA_CARD_CONFIG.delayed],
];

// 9-card order used on the task list pages (My/Delegated/Subscribed/All/Deleted Tasks) —
// matches the reference design (no In Time / Delayed there, those are dashboard-only metrics).
export const LIST_CARD_ORDER = [
  ['totalTasks', EXTRA_CARD_CONFIG.totalTasks],
  ['overdue', EXTRA_CARD_CONFIG.overdue],
  ['pending', STATUS_CONFIG.pending],
  ['accepted', STATUS_CONFIG.accepted],
  ['dependentOnOthers', STATUS_CONFIG.dependent_on_others],
  ['blocked', STATUS_CONFIG.blocked],
  ['inProgress', STATUS_CONFIG.in_progress],
  ['verification', STATUS_CONFIG.verification],
  ['completed', STATUS_CONFIG.completed],
];

export const PRIORITY_CONFIG = {
  Low: { color: 'var(--text-muted)' },
  Normal: { color: 'var(--accent-indigo)' },
  High: { color: 'var(--accent-red)' },
};

export const WORKFLOW_STATUSES = Object.keys(STATUS_CONFIG);
