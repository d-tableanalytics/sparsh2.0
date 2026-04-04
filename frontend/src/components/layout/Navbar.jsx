import React from 'react';
import { useTheme } from '../../context/ThemeContext';
import { useAuth } from '../../context/AuthContext';
import { Link } from 'react-router-dom';
import { 
  Sun, Moon, Bell, Search, ChevronDown, Settings 
} from 'lucide-react';

const Navbar = () => {
  const { theme, toggleTheme } = useTheme();
  const { user } = useAuth();

  return (
    <nav className="h-14 px-6 flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg-card)] sticky top-0 z-30 transition-all duration-300">
      <div className="flex-1 max-w-sm">
        <div className="relative">
          <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input 
            type="text" 
            placeholder="Search..." 
            className="w-full pl-10 pr-4 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg focus:border-[var(--accent-indigo)] outline-none text-[13px] font-medium text-[var(--text-main)] transition-all placeholder:text-[var(--text-muted)]"
          />
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-1 bg-[var(--input-bg)] p-1 rounded-lg border border-[var(--input-border)]">
          <button 
            onClick={toggleTheme}
            className={`p-1.5 rounded-md transition-all ${theme === 'light' ? 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)] shadow-sm' : 'text-[var(--text-muted)]'}`}
          >
            <Sun size={14} />
          </button>
          <button 
            onClick={toggleTheme}
            className={`p-1.5 rounded-md transition-all ${theme === 'dark' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)]'}`}
          >
            <Moon size={14} />
          </button>
        </div>

        <button className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-orange)] hover:bg-[var(--accent-orange-bg)] rounded-lg transition-all relative">
          <Bell size={18} />
          <span className="absolute top-2 right-2 w-1.5 h-1.5 bg-[var(--accent-red)] border border-[var(--bg-card)] rounded-full"></span>
        </button>

        {user?.role === 'superadmin' && (
          <Link to="/admin/settings" className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] rounded-lg transition-all">
            <Settings size={18} />
          </Link>
        )}

        <div className="h-6 w-px bg-[var(--border)] mx-1"></div>

        <button className="flex items-center gap-2 p-1 pl-1 pr-2 hover:bg-[var(--input-bg)] rounded-lg transition-all group">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white font-bold text-[10px]" style={{ background: 'var(--avatar-bg)' }}>
            {user?.full_name?.charAt(0) || 'U'}
          </div>
          <div className="flex flex-col items-start sr-only sm:not-sr-only">
            <span className="text-[13px] font-bold text-[var(--text-main)] leading-none">{user?.full_name || 'Guest'}</span>
            <span className="text-[10px] text-[var(--accent-indigo)] font-bold uppercase tracking-tight mt-0.5">{user?.role || 'User'}</span>
          </div>
          <ChevronDown size={12} className="text-[var(--text-muted)] ml-1" />
        </button>
      </div>
    </nav>
  );
};

export default Navbar;
