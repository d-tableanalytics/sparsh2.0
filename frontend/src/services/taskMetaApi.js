import api from './api';

// Task Categories/Tags CRUD (backend/app/routes/task_meta.py). Persisted server-side so
// they survive refreshes and are shared across every task list/create view, instead of
// being derived from whatever tasks happen to be loaded in the current scoped list.
export const getTaskCategories = () => api.get('/task-categories');
export const createTaskCategory = (name) => api.post('/task-categories', { name });
export const deleteTaskCategory = (id) => api.delete(`/task-categories/${id}`);

export const getTaskTags = () => api.get('/task-tags');
export const createTaskTag = (name) => api.post('/task-tags', { name });
export const deleteTaskTag = (id) => api.delete(`/task-tags/${id}`);
