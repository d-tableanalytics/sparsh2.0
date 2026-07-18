// TPMS is an internal-Sparsh-only module. Access mirrors Task Management exactly
// (see utils/taskAccess.js → canAccessTaskManagement): internal staff-side users only;
// client-side users (clientadmin/clientuser) are blocked.
//
// Within TPMS, role decides which panel a user lands on:
//   • superadmin / admin  → Admin panel  (/tpms/admin)
//   • every other internal → SMOPS panel (/tpms/smops)  ← default
import { canAccessTaskManagement } from '../../utils/taskAccess';

/** Can this user open TPMS at all? (internal-only) */
export const canAccessTpms = (user) => canAccessTaskManagement(user);

/** Does this user get the Admin panel? */
export const isTpmsAdmin = (user) => user?.role === 'superadmin' || user?.role === 'admin';

/** The panel this user should land on when hitting /tpms. */
export const tpmsHome = (user) => (isTpmsAdmin(user) ? '/tpms/admin' : '/tpms/smops');
