import api from './api';

// Task Categories/Tags CRUD (backend/app/routes/task_meta.py). Persisted server-side so
// they survive refreshes and are shared across every task list/create view, instead of
// being derived from whatever tasks happen to be loaded in the current scoped list.
// Pass { active_only: true } from task-creation dropdowns so deactivated items (still
// managed in Settings) don't show up as selectable options.
export const getTaskCategories = (params) => api.get('/task-categories', { params });
export const createTaskCategory = (name) => api.post('/task-categories', { name });
export const updateTaskCategory = (id, payload) => api.patch(`/task-categories/${id}`, payload);
export const deleteTaskCategory = (id) => api.delete(`/task-categories/${id}`);

export const getTaskTags = (params) => api.get('/task-tags', { params });
export const createTaskTag = (name) => api.post('/task-tags', { name });
export const updateTaskTag = (id, payload) => api.patch(`/task-tags/${id}`, payload);
export const deleteTaskTag = (id) => api.delete(`/task-tags/${id}`);
