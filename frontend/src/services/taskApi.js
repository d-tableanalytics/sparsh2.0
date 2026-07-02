import api from './api';

// Tasks are calendar_event docs with type:"task" (see backend/app/routes/tasks.py).
// Create/update of the core event fields still goes through /calendar/events so the
// existing recurrence, delegation, conflict-check and notification logic keeps working.

export const getTasks = (params) => api.get('/tasks', { params });
export const getTaskDashboard = (params) => api.get('/tasks/dashboard', { params });
export const getTaskActivity = (params) => api.get('/tasks/activity', { params });
export const getTaskDetail = (taskId) => api.get(`/tasks/${taskId}`);
export const updateTaskStatus = (taskId, workflow_status, reason) =>
  api.patch(`/tasks/${taskId}/status`, { workflow_status, reason });
export const softDeleteTask = (taskId) => api.delete(`/tasks/${taskId}`);
export const restoreTask = (taskId) => api.post(`/tasks/${taskId}/restore`);

export const createTask = (payload) => api.post('/calendar/events', { ...payload, type: 'task' });
export const updateTask = (taskId, updates) => api.patch(`/calendar/events/${taskId}`, updates);

export const addChecklistItem = (taskId, title) => api.post(`/tasks/${taskId}/checklist`, { title });
export const updateChecklistItem = (taskId, itemId, updates) => api.patch(`/tasks/${taskId}/checklist/${itemId}`, updates);
export const deleteChecklistItem = (taskId, itemId) => api.delete(`/tasks/${taskId}/checklist/${itemId}`);

export const addTaskComment = (taskId, text) => api.post(`/tasks/${taskId}/comments`, { text });

export const uploadTaskAttachment = (taskId, file) => {
  const form = new FormData();
  form.append('file', file);
  return api.post(`/tasks/${taskId}/attachments`, form);
};

export const deleteTaskAttachment = (taskId, attachmentId) => api.delete(`/tasks/${taskId}/attachments/${attachmentId}`);
