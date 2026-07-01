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
