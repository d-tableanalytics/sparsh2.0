// TPMS has two audiences:
//   • Internal staff — mirrors Task Management (utils/taskAccess.js).
//   • Client-side users (clientadmin/clientuser) — available by default for every client
//     company (no enable/disable). They share the SMOPS submodules (Dashboard, HOD
//     Activity, Employee Task, Review Report, My Profile) plus the Forms module.
//
// Which panel a user lands on when hitting /tpms:
//   • superadmin / admin → Admin panel  (/tpms/admin)
//   • everyone else      → SMOPS panel  (/tpms/smops)  ← internal SMOPS users + clients
import { canAccessTaskManagement } from '../../utils/taskAccess';

const CLIENT_ROLES = ['clientadmin', 'clientuser'];

/** Is this a client-side user? (TPMS is enabled for all client companies by default) */
export const canAccessTpmsClient = (user) => !!user && CLIENT_ROLES.includes(user.role);

/** Can this user open TPMS at all? (internal staff OR any client-side user) */
export const canAccessTpms = (user) => canAccessTaskManagement(user) || canAccessTpmsClient(user);

/** Does this user get the internal Admin panel? */
export const isTpmsAdmin = (user) => user?.role === 'superadmin' || user?.role === 'admin';

/** The panel this user should land on when hitting /tpms. */
export const tpmsHome = (user) => (isTpmsAdmin(user) ? '/tpms/admin' : '/tpms/smops');
