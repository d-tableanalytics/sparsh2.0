export const getInitials = (name) => {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].charAt(0).toUpperCase();
  return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
};

export const formatRelativeTime = (dateStr) => {
  if (!dateStr) return '';
  const then = new Date(dateStr).getTime();
  if (Number.isNaN(then)) return '';
  const diffMs = Date.now() - then;
  const diffDays = Math.floor(Math.abs(diffMs) / 86400000);
  const suffix = diffMs >= 0 ? 'ago' : 'left';
  if (diffDays === 0) {
    const diffHours = Math.floor(Math.abs(diffMs) / 3600000);
    if (diffHours === 0) return 'just now';
    return `${diffHours}h ${suffix}`;
  }
  return `${diffDays}d ${suffix}`;
};

export const formatFrequencyLabel = (repeat) => {
  if (!repeat || repeat === 'Does not repeat') return 'One Time';
  return repeat;
};

// A "Daily/Weekly/..." task with a deadline is materialized on the backend as one document
// per occurrence (so each day can be tracked/completed independently), all sharing the same
// recurringGroupId. List views collapse those into a single row so a 6-day daily task reads
// as "one task", while still letting the individual occurrences be expanded and tracked.
export const groupTasksByRecurrence = (tasks) => {
  const order = [];
  const groups = new Map();
  tasks.forEach(t => {
    const key = t.recurringGroupId || t.id;
    if (!groups.has(key)) { groups.set(key, []); order.push(key); }
    groups.get(key).push(t);
  });
  return order.map(key => {
    const items = groups.get(key).sort((a, b) => new Date(a.start || 0) - new Date(b.start || 0));
    // Prefer the next occurrence that isn't finished yet; fall back to the earliest one.
    const primary = items.find(t => t.status !== 'completed') || items[0];
    return { key, primary, items };
  });
};

// No dedicated CSV/export library is installed anywhere in the project, so this uses
// the plain Blob + anchor-download browser API rather than pulling in a new dependency.
export const exportTasksToCsv = (tasks, userMap, filename = 'tasks.csv') => {
  const headers = ['Title', 'Category', 'Assigned To', 'Status', 'Frequency', 'Priority', 'Due Date'];
  const rows = tasks.map(t => [
    t.title || '',
    t.category || '',
    (t.assignedTo || []).map(id => userMap[id] || id).join('; ') || 'Myself',
    t.status || '',
    formatFrequencyLabel(t.frequency),
    t.priority || 'Normal',
    t.end || t.start || '',
  ]);
  const escape = (v) => `"${String(v).replace(/"/g, '""')}"`;
  const csv = [headers, ...rows].map(r => r.map(escape).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};
