import React, { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  LayoutDashboard, Users, Briefcase, CheckSquare, 
  Settings, ChevronLeft, ChevronRight, Building2,
  PieChart, MessageSquare, LogOut, Layers, Copy, Calendar
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

const Sidebar = () => {
  const { user, logout } = useAuth();
  const [isCollapsed, setIsCollapsed] = useState(false);

  const links = [
    { name: 'Dashboard', path: '/', icon: LayoutDashboard, roles: ['superadmin', 'admin', 'clientadmin', 'clientuser'] },
    { name: 'Companies', path: '/companies', icon: Building2, roles: ['superadmin'] },
    { name: 'Batches', path: '/batches', icon: Layers, roles: ['superadmin', 'admin'] },
    { name: 'Session Templates', path: '/session-templates', icon: Copy, roles: ['superadmin', 'admin'] },
    { name: 'User Management', path: '/admin/users', icon: Users, roles: ['superadmin', 'admin'] },
    { name: 'Tasks', path: '/tasks', icon: CheckSquare, roles: ['clientadmin', 'clientuser'] },
    { name: 'Calendar', path: '/calendar', icon: Calendar, roles: ['superadmin', 'admin', 'clientadmin', 'clientuser'] },
  ];

  const filteredLinks = links.filter(link => link.roles.includes(user?.role));

  return (
    <motion.aside 
      initial={false}
      animate={{ width: isCollapsed ? 72 : 240 }}
      className="h-screen sticky top-0 bg-[var(--sidebar-bg)] border-r border-[var(--sidebar-border)] flex flex-col z-40 transition-all duration-300"
    >
      <div className={`p-5 py-6 flex items-center ${isCollapsed ? 'justify-center' : 'justify-between'}`}>
        <AnimatePresence mode="wait">
          {!isCollapsed ? (
            <motion.div 
              key="full-logo"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="flex items-center gap-2"
            >
              <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white font-bold text-[10px]" style={{ background: 'var(--avatar-bg)' }}>
                SP
              </div>
              <div className="flex flex-col">
                <span className="text-[13px] font-black text-[var(--text-main)] tracking-tight">Sparsh ERP</span>
                <span className="text-[10px] text-[var(--text-muted)] font-bold tracking-widest mt-0.5 uppercase opacity-60">v2.0 Beta</span>
              </div>
            </motion.div>
          ) : (
            <motion.div 
              key="icon-logo"
              className="w-8 h-8 rounded-lg flex items-center justify-center text-white font-bold text-[10px]"
              style={{ background: 'var(--avatar-bg)' }}
            >
              SP
            </motion.div>
          )}
        </AnimatePresence>
        
        {!isCollapsed && (
          <button 
            onClick={() => setIsCollapsed(true)}
            className="p-1 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] rounded-md transition-all"
          >
            <ChevronLeft size={16} />
          </button>
        )}
      </div>

      <nav className="flex-1 px-3 space-y-1 overflow-y-auto no-scrollbar">
        {filteredLinks.map((link) => (
          <NavLink 
            key={link.path} 
            to={link.path} 
            className={({ isActive }) => `
              group flex items-center gap-3 p-2.5 rounded-lg transition-all relative
              ${isActive 
                ? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] font-bold' 
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
        
        {isCollapsed && (
          <button 
            onClick={() => setIsCollapsed(false)}
            className="w-full mt-2 flex items-center justify-center p-2.5 bg-[var(--btn-primary)] text-white rounded-lg shadow-sm hover:bg-[var(--btn-primary-hover)] transition-all font-bold"
          >
            <ChevronRight size={14} />
          </button>
        )}
      </div>
    </motion.aside>
  );
};

export default Sidebar;
