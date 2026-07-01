import api from './api';

// Tasks are calendar_event docs with type:"task" (see backend/app/routes/tasks.py).
// Create/update of the core event fields still goes through /calendar/events so the
// existing recurrence, delegation, conflict-check and notification logic keeps working.

export const getTasks = (params) => api.get('/tasks', { params });
export const getTaskDashboard = (params) => api.get('/tasks/dashboard', { params });
export const updateTaskStatus = (taskId, workflow_status) =>
  api.patch(`/tasks/${taskId}/status`, { workflow_status });
export const softDeleteTask = (taskId) => api.delete(`/tasks/${taskId}`);
export const restoreTask = (taskId) => api.post(`/tasks/${taskId}/restore`);

export const createTask = (payload) => api.post('/calendar/events', { ...payload, type: 'task' });
export const updateTask = (taskId, updates) => api.patch(`/calendar/events/${taskId}`, updates);
