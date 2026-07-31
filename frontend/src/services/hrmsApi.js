import api from './api';

// HRMS API wrappers. Everything lives under /hrms and is internal-staff-only server-side
// (auth_controller.require_hrms_access) — see docs/HRMS_REPLICATION_ROADMAP.md.
//
// Phase 0 exposes the access/permission probes the shell needs. Per-module calls are added as
// each phase lands, so this file stays the one place the HRMS talks to the backend.

// What the caller may do inside the HRMS. 403s a user without the module — use getHrmsAccess
// for a question that must not raise.
export const getHrmsMeta = () => api.get('/hrms/meta');

// Non-throwing access probe, safe for any authenticated user (used by the sidebar).
export const getHrmsAccess = () => api.get('/hrms/access');
