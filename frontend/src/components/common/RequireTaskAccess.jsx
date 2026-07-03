import React from 'react';
import { ShieldAlert } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { canAccessTaskManagement, TASK_ACCESS_DENIED_MESSAGE } from '../../utils/taskAccess';

// Route guard for the Task Management / Delegation module. Client-side users who reach a
// task URL directly get an Access Denied panel instead of the page (the backend also 403s
// every task API, so this is the UX layer of a defense-in-depth gate).
const RequireTaskAccess = ({ children }) => {
  const { user } = useAuth();

  if (canAccessTaskManagement(user)) return children;

  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="w-16 h-16 rounded-2xl bg-[var(--accent-red-bg)] flex items-center justify-center text-[var(--accent-red)] mb-4">
        <ShieldAlert size={30} />
      </div>
      <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight mb-1">Access Denied</h1>
      <p className="text-[13px] font-bold text-[var(--text-muted)] max-w-md">{TASK_ACCESS_DENIED_MESSAGE}</p>
      <a href="/" className="mt-6 px-5 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest hover:opacity-90 transition-all">
        Back to Dashboard
      </a>
    </div>
  );
};

export default RequireTaskAccess;
