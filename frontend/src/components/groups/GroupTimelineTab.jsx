import React, { useCallback, useEffect, useState } from 'react';
import { Activity, ChevronRight } from 'lucide-react';
import { getTaskActivity } from '../../services/taskApi';
import { getInitials } from '../tasks/taskDisplayUtils';
import { metaFor, extractStatusChange, formatDateTime } from '../tasks/activityDisplayUtils';

const PAGE_SIZE = 20;

// Activity feed scoped to this group's tasks (backend filters by metadata.group_id --
// see tasks.py's tasks_activity). Any group member sees the whole group's activity
// uniformly (no admin/non-admin split, unlike the org-wide Activity page).
const GroupTimelineTab = ({ group, period, startDate, endDate, search }) => {
  const [activities, setActivities] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  const fetchActivity = useCallback(async (nextPage = 0, append = false) => {
    append ? setLoadingMore(true) : setLoading(true);
    setError(null);
    try {
      const res = await getTaskActivity({
        groupId: group.id, period, startDate, endDate, search: search || undefined,
        limit: PAGE_SIZE, skip: nextPage * PAGE_SIZE,
      });
      const data = res.data || {};
      setActivities(prev => (append ? [...prev, ...(data.activities || [])] : (data.activities || [])));
      setTotal(data.total || 0);
      setPage(nextPage);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load activity');
    } finally {
      append ? setLoadingMore(false) : setLoading(false);
    }
  }, [group.id, period, startDate, endDate, search]);

  useEffect(() => { fetchActivity(0, false); }, [fetchActivity]);

  const hasMore = activities.length < total;

  return (
    <div className="space-y-4">
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden">
        {loading ? (
          <div className="p-16 text-center text-[var(--text-muted)] text-[12px] font-bold">Loading activity...</div>
        ) : error ? (
          <div className="p-16 text-center text-[var(--accent-red)] text-[12px] font-bold">{error}</div>
        ) : activities.length === 0 ? (
          <div className="p-16 flex flex-col items-center justify-center text-[var(--text-muted)]">
            <Activity size={40} className="mb-3 opacity-30" />
            <p className="text-[12px] font-bold">No activity yet for this group's tasks.</p>
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {activities.map(a => {
              const meta = metaFor(a.action);
              const Icon = meta.icon;
              const statusChange = a.action === 'Update Task Status' ? extractStatusChange(a.details) : null;
              return (
                <div key={a.id} className="flex items-start gap-3.5 px-5 py-4 hover:bg-[var(--input-bg)] transition-colors group">
                  <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 mt-0.5"
                    style={{ background: `color-mix(in srgb, ${meta.color} 14%, transparent)`, color: meta.color }}>
                    <Icon size={16} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[12px] font-black text-[var(--text-main)]">{meta.label}</span>
                      {statusChange && (
                        <span className="px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-wider"
                          style={{ background: 'color-mix(in srgb, var(--accent-green) 14%, transparent)', color: 'var(--accent-green)' }}>
                          → {statusChange}
                        </span>
                      )}
                    </div>
                    {a.details && <p className="text-[12px] font-medium text-[var(--text-muted)] mt-0.5 break-words">{a.details}</p>}
                    <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                      <div className="w-5 h-5 rounded-full flex items-center justify-center text-white font-black text-[8px] shrink-0" style={{ background: 'var(--accent-indigo)' }}>
                        {getInitials(a.updatedByName)}
                      </div>
                      <span className="text-[11px] font-bold text-[var(--text-main)]">{a.updatedByName || 'Unknown'}</span>
                      <span className="text-[10px] font-bold text-[var(--text-muted)]">· {formatDateTime(a.updatedAt)}</span>
                    </div>
                  </div>
                  <ChevronRight size={16} className="text-[var(--text-muted)] opacity-0 group-hover:opacity-60 transition-opacity shrink-0 mt-1" />
                </div>
              );
            })}
          </div>
        )}
      </div>

      {!loading && !error && hasMore && (
        <div className="flex justify-center">
          <button onClick={() => fetchActivity(page + 1, true)} disabled={loadingMore}
            className="px-6 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--accent-indigo)] border border-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] disabled:opacity-50 transition-all">
            {loadingMore ? 'Loading...' : `Load More (${activities.length} of ${total})`}
          </button>
        </div>
      )}
    </div>
  );
};

export default GroupTimelineTab;
