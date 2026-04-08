import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import api from '../services/api';
import { 
  User, Mail, Shield, Lock, Key, 
  MapPin, Phone, Briefcase, Camera,
  CheckCircle2, AlertCircle, Loader2,
  ChevronRight, LogOut
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const SectionHeader = ({ icon: Icon, title, subtitle }) => (
  <div className="flex items-center gap-3 mb-6">
    <div className="w-10 h-10 rounded-xl bg-[var(--accent-indigo-bg)] flex items-center justify-center text-[var(--accent-indigo)]">
      <Icon size={20} />
    </div>
    <div>
      <h2 className="text-[15px] font-bold text-[var(--text-main)] tracking-tight">{title}</h2>
      <p className="text-[11px] text-[var(--text-muted)] font-medium">{subtitle}</p>
    </div>
  </div>
);

const ProfileField = ({ icon: Icon, label, value, color = "indigo" }) => (
  <div className="flex items-center gap-4 p-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl group transition-all hover:border-[var(--accent-indigo-border)]">
    <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-[var(--accent-${color})] bg-[var(--accent-${color}-bg)]`}>
      <Icon size={14} />
    </div>
    <div className="flex flex-col">
      <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">{label}</span>
      <span className="text-[13px] font-medium text-[var(--text-main)]">{value || 'Not provided'}</span>
    </div>
  </div>
);

const ProfilePage = () => {
  const { user, logout } = useAuth();
  const { showSuccess, showError } = useNotification();
  
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: ''
  });
  const [isChanging, setIsChanging] = useState(false);

  const handlePasswordChange = async (e) => {
    e.preventDefault();
    if (passwordForm.newPassword !== passwordForm.confirmPassword) {
      showError("Passwords do not match");
      return;
    }

    setIsChanging(true);
    try {
      await api.patch('/auth/change-password', {
        current_password: passwordForm.currentPassword,
        new_password: passwordForm.newPassword
      });
      showSuccess("Password updated successfully");
      setPasswordForm({ currentPassword: '', newPassword: '', confirmPassword: '' });
    } catch (error) {
      showError(error.response?.data?.detail || "Failed to update password");
    } finally {
      setIsChanging(false);
    }
  };

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }} 
      animate={{ opacity: 1, y: 0 }}
      className="max-w-4xl mx-auto space-y-6"
    >
      {/* ───── Hero Profile Section ───── */}
      <div className="relative overflow-hidden bg-[var(--bg-card)] border border-[var(--border)] rounded-3xl p-8 shadow-sm">
        <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-to-br from-[var(--accent-indigo-bg)] to-transparent rounded-full -mr-32 -mt-32 opacity-50 blur-3xl"></div>
        
        <div className="relative flex flex-col md:flex-row items-center gap-8">
          <div className="relative group">
            <div className="w-24 h-24 rounded-2xl bg-[var(--avatar-bg)] flex items-center justify-center text-white text-3xl font-black shadow-xl ring-4 ring-[var(--bg-card)]">
              {user?.full_name?.charAt(0) || 'U'}
            </div>
            <button className="absolute -bottom-2 -right-2 p-2 bg-[var(--accent-indigo)] text-white rounded-lg shadow-lg hover:scale-110 transition-all opacity-0 group-hover:opacity-100">
              <Camera size={14} />
            </button>
          </div>

          <div className="flex-1 text-center md:text-left">
            <h1 className="text-2xl font-black text-[var(--text-main)] tracking-tight mb-1">{user?.full_name}</h1>
            <div className="flex flex-wrap justify-center md:justify-start items-center gap-3">
              <span className="px-3 py-1 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[10px] font-black uppercase tracking-widest rounded-full border border-[var(--accent-indigo-border)]">
                {user?.role}
              </span>
              <span className="flex items-center gap-1.5 text-[12px] font-bold text-[var(--text-muted)]">
                <CheckCircle2 size={14} className="text-[var(--accent-green)]" /> Verified Account
              </span>
            </div>
          </div>

          <div className="flex gap-3">
            <button 
              onClick={logout}
              className="px-5 py-2.5 bg-[var(--accent-red-bg)] text-[var(--accent-red)] font-bold text-[13px] rounded-xl flex items-center gap-2 hover:bg-[var(--accent-red)] hover:text-white transition-all shadow-sm"
            >
              <LogOut size={16} /> Sign Out
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* ───── Personal Information ───── */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-6 shadow-sm">
            <SectionHeader 
              icon={User} 
              title="Personal Information" 
              subtitle="Basic identity and contact details managed by HR."
            />
            
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <ProfileField icon={Mail} label="Email Address" value={user?.email} />
              <ProfileField icon={Phone} label="Mobile" value={user?.mobile} color="orange" />
              <ProfileField icon={Shield} label="Account Type" value={user?.role} color="green" />
              <ProfileField icon={Briefcase} label="Designation" value={user?.designation} color="red" />
            </div>
          </div>

          <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-6 shadow-sm">
            <SectionHeader 
              icon={MapPin} 
              title="Work Details" 
              subtitle="Regional configuration and department assignment."
            />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <ProfileField icon={Briefcase} label="Department" value={user?.department} color="indigo" />
              <ProfileField icon={CheckCircle2} label="Session Type" value={user?.session_type} color="orange" />
            </div>
          </div>
        </div>

        {/* ───── Change Password (Interactive Section) ───── */}
        <div className="space-y-6">
          <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-6 shadow-sm sticky top-24">
            <SectionHeader 
              icon={Key} 
              title="Security" 
              subtitle="Manage your credentials."
            />

            <form onSubmit={handlePasswordChange} className="space-y-4">
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest ml-1">Current Password</label>
                <div className="relative group">
                  <Lock size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] group-focus-within:text-[var(--accent-indigo)] transition-all" />
                  <input 
                    type="password"
                    required
                    value={passwordForm.currentPassword}
                    onChange={(e) => setPasswordForm({...passwordForm, currentPassword: e.target.value})}
                    placeholder="••••••••"
                    className="w-full pl-10 pr-4 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl outline-none focus:border-[var(--accent-indigo)] text-[13px] font-medium text-[var(--text-main)] transition-all"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest ml-1">New Password</label>
                <div className="relative group">
                  <Lock size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] group-focus-within:text-[var(--accent-indigo)] transition-all" />
                  <input 
                    type="password"
                    required
                    value={passwordForm.newPassword}
                    onChange={(e) => setPasswordForm({...passwordForm, newPassword: e.target.value})}
                    placeholder="Minimal 8 chars"
                    className="w-full pl-10 pr-4 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl outline-none focus:border-[var(--accent-indigo)] text-[13px] font-medium text-[var(--text-main)] transition-all"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest ml-1">Confirm New Password</label>
                <div className="relative group">
                  <Lock size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] group-focus-within:text-[var(--accent-indigo)] transition-all" />
                  <input 
                    type="password"
                    required
                    value={passwordForm.confirmPassword}
                    onChange={(e) => setPasswordForm({...passwordForm, confirmPassword: e.target.value})}
                    placeholder="Re-type password"
                    className="w-full pl-10 pr-4 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl outline-none focus:border-[var(--accent-indigo)] text-[13px] font-medium text-[var(--text-main)] transition-all"
                  />
                </div>
              </div>

              <button 
                type="submit" 
                disabled={isChanging}
                className="w-full py-2.5 bg-gradient-to-r from-[var(--accent-indigo)] to-[var(--accent-indigo-border)] text-white font-black text-[13px] rounded-xl shadow-lg shadow-indigo-500/20 hover:opacity-90 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {isChanging ? <Loader2 size={16} className="animate-spin" /> : <Lock size={16} />}
                Update Credentials
              </button>
            </form>

            <div className="mt-6 p-4 bg-[var(--accent-orange-bg)] border border-[var(--accent-orange-border)] rounded-xl flex items-start gap-3">
              <AlertCircle size={16} className="text-[var(--accent-orange)] shrink-0 mt-0.5" />
              <p className="text-[11px] font-medium text-[var(--accent-orange)] leading-relaxed">
                Password changes take effect immediately on all sessions. You may need to re-login on other devices.
              </p>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
};

export default ProfilePage;
