import React, { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard, Users, Briefcase, CheckSquare,
  Settings, Building2,
  PieChart, MessageSquare, LogOut, Layers, Copy, Calendar, Sparkles, PlayCircle, Target, BarChart3, TrendingUp, ShieldCheck
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

import logo1 from '../../assets/Sparsh Magic  Logo PNG1.png';
import logo2 from '../../assets/Sparsh Magic  Logo PNG2.png';
import logo3 from '../../assets/Sparsh Magic white  Logo PNG3.png';
import dtableLogo from '../../assets/D-Table_Logo.png';
import dtableFull from '../../assets/D-Table Analytics-Picsart-BackgroundRemover.jpeg';
import { useTheme } from '../../context/ThemeContext';

const Sidebar = () => {
  const { user, logout } = useAuth();
  const { theme } = useTheme();
  const [isCollapsed, setIsCollapsed] = useState(true);

  const links = [
    { name: 'Dashboard', path: '/', icon: LayoutDashboard, roles: ['superadmin', 'admin', 'clientadmin', 'clientuser', 'coach', 'staff'] },
    { name: 'Companies', path: '/companies', icon: Building2, roles: ['superadmin'], permissionKey: 'companies' },
    { name: 'Batches', path: '/batches', icon: Layers, roles: ['superadmin', 'admin', 'coach'], permissionKey: 'batches' },
    { name: 'Session Templates', path: '/session-templates', icon: Copy, roles: ['superadmin', 'admin', 'coach'], permissionKey: 'templates' },
    { name: 'User Management', path: '/admin/users', icon: Users, roles: ['superadmin', 'admin', 'coach'], permissionKey: 'users' },
    { name: 'Training Roadmap', path: '/company-portal', icon: Target, roles: ['clientadmin', 'clientuser'] },
    { name: 'Live Sessions', path: '/sessions', icon: PlayCircle, roles: ['clientadmin', 'clientuser'] },
    { name: 'My Progress', path: '/my-reports', icon: BarChart3, roles: ['clientadmin', 'clientuser'] },
    { name: 'Team', path: '/team', icon: Users, roles: ['clientadmin'] },
    { name: 'Calendar', path: '/calendar', icon: Calendar, roles: ['superadmin', 'admin', 'clientadmin', 'clientuser', 'coach', 'staff'], permissionKey: 'calendar' },
    { name: 'ORM Dashboard', path: '/orm/dashboard', icon: TrendingUp, roles: ['clientadmin', 'clientuser'] },
    { name: 'ORM Configuration', path: '/orm/templates', icon: ShieldCheck, roles: ['clientadmin'] },
    { name: 'Company Settings', path: '/settings', icon: Settings, roles: ['clientadmin'] },
    { name: 'Support Engine', path: '/gpt', icon: Sparkles, roles: ['superadmin', 'admin', 'clientadmin', 'clientuser', 'coach', 'staff'] },
  ];

  const filteredLinks = links.filter(link => {
    const isClientRole = ['clientadmin', 'clientuser'].includes(user?.role);
    const isAdminLink = ['Companies', 'Batches', 'Session Templates', 'User Management'].includes(link.name);

    // If it's a client role, strictly hide admin links regardless of permissions
    if (isClientRole && isAdminLink) return false;

    // Default filtering logic
    const hasRole = link.roles.includes(user?.role);
    const hasPermission = link.permissionKey && user?.permissions?.[link.permissionKey]?.read;

    return hasRole || hasPermission;
  });

  return (
    <motion.aside
      initial={false}
      animate={{ width: isCollapsed ? 72 : 240 }}
      transition={{ type: 'spring', stiffness: 400, damping: 40 }}
      onMouseEnter={() => setIsCollapsed(false)}
      onMouseLeave={() => setIsCollapsed(true)}
      className="h-screen fixed left-0 top-0 bg-[var(--sidebar-bg)] border-r border-[var(--sidebar-border)] flex flex-col z-50 overflow-hidden"
    >
      <div className={`p-5 py-6 flex items-center ${isCollapsed ? 'justify-center' : 'justify-between'}`}>
        <AnimatePresence mode="wait">
          {!isCollapsed ? (
            <motion.div
              key="full-logo"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="flex items-center gap-3"
            >
              <img src={logo1} alt="Logo" className="w-8 h-8 object-contain" />
              <div className="flex flex-col">
                <img src={theme === 'dark' ? logo3 : logo2} alt="Sparsh ERP" className="h-9 object-contain" />
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="icon-logo"
              className="w-10 h-10 flex items-center justify-center p-1"
            >
              <img src={logo1} alt="Logo" className="w-full h-full object-contain" />
            </motion.div>
          )}
        </AnimatePresence>

      </div>

      <nav className="flex-1 px-3 space-y-1 overflow-y-auto no-scrollbar">
        {filteredLinks.map((link) => (
          <NavLink
            key={link.path}
            to={link.path}
            className={({ isActive }) => `
              group flex items-center gap-3 p-2.5 rounded-lg transition-colors relative
              ${isActive
                ? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] font-bold shadow-sm'
                : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}
              ${isCollapsed ? 'justify-center' : ''}
            `}
          >
            <link.icon size={18} className="transition-transform group-hover:scale-105" />
            {!isCollapsed && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-[13px] tracking-tight font-medium"
              >
                {link.name}
              </motion.span>
            )}
            {isCollapsed && (
              <div className="absolute left-full ml-4 px-2.5 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-main)] text-[10px] font-bold uppercase tracking-widest rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 shadow-lg">
                {link.name}
              </div>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="p-3 border-t border-[var(--sidebar-border)]">
        <button
          onClick={logout}
          className={`w-full flex items-center gap-3 p-2.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--accent-red-bg)] hover:text-[var(--accent-red)] transition-all ${isCollapsed ? 'justify-center' : ''}`}
        >
          <LogOut size={18} />
          {!isCollapsed && <span className="text-[13px] font-bold tracking-tight">Logout</span>}
        </button>

        <div className={`mt-4 p-2.5 rounded-xl bg-white shadow-sm flex items-center transition-all ${isCollapsed ? 'justify-center mx-1' : 'justify-start px-3 gap-2'}`}>
          <img
            src={isCollapsed ? dtableLogo : dtableFull}
            alt="D-Table Analytics"
            className={`${isCollapsed ? 'w-8 h-8' : 'w-full h-10'} object-contain`}
          />
        </div>
      </div>
    </motion.aside>
  );
};

export default Sidebar;
