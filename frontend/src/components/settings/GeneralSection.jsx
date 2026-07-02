import React from 'react';
import { useAuth } from '../../context/AuthContext';
import { User, Mail, Phone, Shield, Briefcase, Building2, BadgeCheck, IdCard } from 'lucide-react';

// Read-only profile / workspace card. Uses existing AuthContext data only — no API call,
// no data mutation. Mirrors the app's ProfileField card styling.
const Field = ({ icon: Icon, label, value }) => (
  <div className="flex items-center gap-4 p-3.5 bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl transition-all hover:border-[var(--accent-indigo-border)]">
    <div className="w-9 h-9 rounded-xl flex items-center justify-center text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] shrink-0">
      <Icon size={15} />
    </div>
    <div className="flex flex-col min-w-0">
      <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{label}</span>
      <span className="text-[13px] font-bold text-[var(--text-main)] truncate">{value || 'Not provided'}</span>
    </div>
  </div>
);

const GeneralSection = () => {
  const { user } = useAuth();
  const fullName = user?.full_name
    || `${user?.first_name || ''} ${user?.last_name || ''}`.trim()
    || user?.email
    || 'User';
  const initial = (fullName.charAt(0) || 'U').toUpperCase();
  const isActive = user?.is_active !== false;

  return (
    <div className="max-w-4xl mx-auto w-full space-y-5">
      {/* Identity header card */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-sm p-6 flex flex-col sm:flex-row sm:items-center gap-5">
        <div className="w-16 h-16 rounded-2xl flex items-center justify-center text-white font-black text-2xl shrink-0" style={{ background: 'var(--avatar-bg)' }}>
          {initial}
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-xl font-black text-[var(--text-main)] tracking-tight truncate">{fullName}</h2>
          <p className="text-[12px] font-bold text-[var(--text-muted)] truncate">{user?.email}</p>
          <div className="flex flex-wrap items-center gap-2 mt-2">
            <span className="px-2.5 py-1 rounded-lg text-[10px] font-black uppercase tracking-widest bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              {user?.role || '—'}
            </span>
            <span
              className="px-2.5 py-1 rounded-lg text-[10px] font-black uppercase tracking-widest"
              style={{
                color: isActive ? 'var(--accent-green)' : 'var(--accent-red)',
                background: 'var(--input-bg)',
              }}
            >
              {isActive ? 'Active' : 'Inactive'}
            </span>
          </div>
        </div>
      </div>

      {/* Detail fields */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-sm p-6">
        <h3 className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-4">Profile Details</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field icon={User} label="First Name" value={user?.first_name} />
          <Field icon={User} label="Last Name" value={user?.last_name} />
          <Field icon={Mail} label="Email" value={user?.email} />
          <Field icon={Phone} label="Primary Mobile" value={user?.mobile} />
          <Field icon={Shield} label="Role" value={user?.role} />
          <Field icon={Briefcase} label="Department" value={user?.department} />
          <Field icon={IdCard} label="Designation" value={user?.designation} />
          <Field icon={BadgeCheck} label="Status" value={isActive ? 'Active' : 'Inactive'} />
        </div>
        <p className="mt-4 text-[10px] font-medium text-[var(--text-muted)] italic flex items-center gap-1.5">
          <Building2 size={11} /> Profile details are read-only here. To edit personal details use your Profile page.
        </p>
      </div>
    </div>
  );
};

export default GeneralSection;
