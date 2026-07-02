import React, { useState, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard, Users, Briefcase, CheckSquare,
  Settings, Building2,
  PieChart, MessageSquare, LogOut, Layers, Copy, Calendar, Sparkles, PlayCircle, Target, BarChart3, Library, X,
  Forward, Bell, Trash2, ChevronDown, Activity, CalendarDays, UsersRound
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

import logo1 from '../../assets/Sparsh Magic  Logo PNG1.png';
import logo2 from '../../assets/Sparsh Magic  Logo PNG2.png';
import logo3 from '../../assets/Sparsh Magic white  Logo PNG3.png';
import dtableLogo from '../../assets/D-Table_Logo.png';
import dtableFull from '../../assets/D-Table Analytics-Picsart-BackgroundRemover.jpeg';
import { useTheme } from '../../context/ThemeContext';

const Sidebar = ({ isMobileOpen, setIsMobileOpen }) => {
  const { user, logout } = useAuth();
  const { theme } = useTheme();
  const location = useLocation();
  const [isCollapsed, setIsCollapsed] = useState(true);
  const [isMobile, setIsMobile] = useState(false);
  const [isTasksOpen, setIsTasksOpen] = useState(false);

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768);
    };
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

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
    {
      name: 'Task Management', path: '/tasks', icon: CheckSquare,
      roles: ['superadmin', 'admin', 'clientadmin', 'clientuser', 'coach', 'staff'], permissionKey: 'tasks',
      submodules: [
        { name: 'Dashboard', path: '/tasks', icon: LayoutDashboard },
        { name: 'My Tasks', path: '/tasks/my', icon: CheckSquare },
        { name: 'Delegated Tasks', path: '/tasks/delegated', icon: Forward },
        { name: 'Subscribed Tasks', path: '/tasks/subscribed', icon: Bell },
        { name: 'All Tasks', path: '/tasks/all', icon: Layers },
        { name: 'Groups', path: '/tasks/groups', icon: UsersRound },
        { name: 'Holiday', path: '/tasks/holiday', icon: CalendarDays },
        { name: 'Activity', path: '/tasks/activity', icon: Activity },
        { name: 'Deleted Tasks', path: '/tasks/deleted', icon: Trash2 },
      ],
    },
    { name: 'Reports', path: '/admin/reports', icon: BarChart3, roles: ['superadmin', 'admin'] },
    { name: 'Company Settings', path: '/settings', icon: Settings, roles: ['clientadmin'] },
    { name: 'Support Engine', path: '/gpt', icon: Sparkles, roles: ['superadmin', 'admin', 'clientadmin', 'clientuser', 'coach', 'staff'] },
    { name: 'Media Library', path: '/media', icon: Library, roles: ['superadmin', 'admin', 'coach', 'staff'] },
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

  const sidebarWidth = isMobile ? 240 : (isCollapsed ? 72 : 240);
  const isTaskRouteActive = location.pathname.startsWith('/tasks');

  useEffect(() => {
    if (isTaskRouteActive) setIsTasksOpen(true);
  }, [isTaskRouteActive]);

  return (
    <motion.aside
      initial={false}
      animate={{ width: sidebarWidth }}
      transition={{ type: 'spring', stiffness: 400, damping: 40 }}
      onMouseEnter={() => !isMobile && setIsCollapsed(false)}
      onMouseLeave={() => !isMobile && setIsCollapsed(true)}
      className={`h-screen fixed left-0 top-0 bg-[var(--sidebar-bg)] border-r border-[var(--sidebar-border)] flex flex-col z-50 overflow-hidden transform transition-transform duration-300 md:transition-none md:translate-x-0 ${
        isMobileOpen ? 'translate-x-0' : '-translate-x-full'
      }`}
    >
      {/* Logo Header */}
      <div className={`p-5 py-6 flex items-center ${isCollapsed && !isMobile ? 'justify-center' : 'justify-between'}`}>
        <AnimatePresence mode="wait">
          {(!isCollapsed || isMobile) ? (
            <motion.div
              key="full-logo"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="flex items-center gap-3 w-full"
            >
              <div className="flex items-center gap-3">
                <img src={logo1} alt="Logo" className="w-8 h-8 object-contain" />
                <div className="flex flex-col">
                  <img src={theme === 'dark' ? logo3 : logo2} alt="Sparsh ERP" className="h-9 object-contain" />
                </div>
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

      {/* Main Links */}
      <nav className="flex-1 px-3 space-y-1 overflow-y-auto no-scrollbar">
        {filteredLinks.map((link) => {
          if (link.submodules) {
            const groupActive = isTaskRouteActive;
            return (
              <div key={link.path}>
                <button
                  type="button"
                  onClick={() => setIsTasksOpen(o => !o)}
                  className={`
                    group w-full flex items-center gap-3 p-2.5 rounded-lg transition-colors relative
                    ${groupActive
                      ? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] font-bold shadow-sm'
                      : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}
                    ${(isCollapsed && !isMobile) ? 'justify-center' : ''}
                  `}
                >
                  <link.icon size={18} className="transition-transform group-hover:scale-105" />
                  {(!isCollapsed || isMobile) && (
                    <>
                      <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-[13px] tracking-tight font-medium flex-1 text-left">
                        {link.name}
                      </motion.span>
                      <ChevronDown size={14} className={`transition-transform ${isTasksOpen ? 'rotate-180' : ''}`} />
                    </>
                  )}
                  {(isCollapsed && !isMobile) && (
                    <div className="absolute left-full ml-4 px-2.5 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-main)] text-[10px] font-bold uppercase tracking-widest rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 shadow-lg">
                      {link.name}
                    </div>
                  )}
                </button>

                <AnimatePresence initial={false}>
                  {isTasksOpen && (!isCollapsed || isMobile) && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="overflow-hidden pl-4 space-y-1 mt-1"
                    >
                      {link.submodules.map((sub) => (
                        <NavLink
                          key={sub.path}
                          to={sub.path}
                          end={sub.path === '/tasks'}
                          onClick={() => { if (isMobile) setIsMobileOpen(false); }}
                          className={({ isActive }) => `
                            group flex items-center gap-3 pl-3 pr-2.5 py-2 rounded-lg transition-colors text-[12.5px]
                            ${isActive
                              ? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] font-bold shadow-sm'
                              : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}
                          `}
                        >
                          <sub.icon size={15} />
                          <span className="tracking-tight font-medium">{sub.name}</span>
                        </NavLink>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          }

          return (
            <NavLink
              key={link.path}
              to={link.path}
              onClick={() => {
                if (isMobile) {
                  setIsMobileOpen(false);
                }
              }}
              className={({ isActive }) => `
                group flex items-center gap-3 p-2.5 rounded-lg transition-colors relative
                ${isActive
                  ? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] font-bold shadow-sm'
                  : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}
                ${(isCollapsed && !isMobile) ? 'justify-center' : ''}
              `}
            >
              <link.icon size={18} className="transition-transform group-hover:scale-105" />
              {(!isCollapsed || isMobile) && (
                <motion.span
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="text-[13px] tracking-tight font-medium"
                >
                  {link.name}
                </motion.span>
              )}
              {(isCollapsed && !isMobile) && (
                <div className="absolute left-full ml-4 px-2.5 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-main)] text-[10px] font-bold uppercase tracking-widest rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 shadow-lg">
                  {link.name}
                </div>
              )}
            </NavLink>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="p-3 border-t border-[var(--sidebar-border)]">
        <button
          onClick={() => {
            logout();
            if (isMobile) {
              setIsMobileOpen(false);
            }
          }}
          className={`w-full flex items-center gap-3 p-2.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--accent-red-bg)] hover:text-[var(--accent-red)] transition-all ${(isCollapsed && !isMobile) ? 'justify-center' : ''}`}
        >
          <LogOut size={18} />
          {(!isCollapsed || isMobile) && <span className="text-[13px] font-bold tracking-tight">Logout</span>}
        </button>

        <div className={`mt-4 p-2.5 rounded-xl bg-white shadow-sm flex items-center transition-all ${(isCollapsed && !isMobile) ? 'justify-center mx-1' : 'justify-start px-3 gap-2'}`}>
          <img
            src={(isCollapsed && !isMobile) ? dtableLogo : dtableFull}
            alt="D-Table Analytics"
            className={`${(isCollapsed && !isMobile) ? 'w-8 h-8' : 'w-full h-10'} object-contain`}
          />
        </div>
      </div>
    </motion.aside>
  );
};

export default Sidebar;
