import api from './api';

// Self-service profile (backend/app/routes/user.py) — PATCH /users/me only touches safe
// fields; role/permissions stay admin-only via PUT /users/{id}.
export const getMyProfile = () => api.get('/users/me');
export const updateMyProfile = (payload) => api.patch('/users/me', payload);
// Which profile fields the signed-in user may edit themselves (HR-controlled fields are
// read-only for an employee login). Callers fail closed: on error nothing is editable.
export const getMyEditableFields = () => api.get('/users/me/editable-fields');

// Per-user notification preferences (backend/app/routes/notification.py).
export const getNotificationPrefs = () => api.get('/notifications/preferences');
export const updateNotificationPrefs = (payload) => api.put('/notifications/preferences', payload);
