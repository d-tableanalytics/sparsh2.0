import { useEffect, useState } from 'react';
import { useHrms } from '../HrmsContext';
import { getMyEmployeeProfile } from '../../../services/hrmsApi';

/**
 * HRMS ▸ "this form is for me".
 *
 * Every Sparsh staff member is an employee and applies for their OWN leave, attendance
 * corrections, C-Off and advances. They cannot search the staff directory (and must not),
 * so an employee picker has nothing to offer them — it pre-selects their own record instead.
 *
 * Roles that act on other people's records keep the search: HR / MD / owner for anybody, a
 * manager for their team. The server enforces the same split (hrms_access.sees_all_people,
 * `_assert_self_or_privileged`), so this only decides what the form shows.
 */
export const ACTS_FOR_OTHERS = ['admin', 'hr', 'md', 'manager'];

export function useSelfEmployee(value, onChange, { others = ACTS_FOR_OTHERS } = {}) {
  const { role } = useHrms();
  const selfOnly = !!role && !others.includes(role);
  const [me, setMe] = useState(undefined);          // undefined = loading, null = no profile

  useEffect(() => {
    if (!selfOnly) return undefined;
    let live = true;
    getMyEmployeeProfile()
      .then(({ data }) => {
        if (!live) return;
        setMe(data?.employee_code ? {
          user_id: data.user_id, employee_code: data.employee_code, name: data.name,
          designation: data.designation, employment_status: data.employment_status,
        } : null);
      })
      .catch(() => { if (live) setMe(null); });
    return () => { live = false; };
  }, [selfOnly]);

  useEffect(() => {
    if (selfOnly && me && !value) onChange(me);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selfOnly, me, value]);

  return { selfOnly, me };
}
