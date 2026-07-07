import React, { useState } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import Sidebar from '../layout/Sidebar';
import Navbar from '../layout/Navbar';

const PrivateRoute = ({ children, hideLayout = false }) => {
  const { user } = useAuth();
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);

  if (!user) {
    return <Navigate to="/login" />;
  }

  if (hideLayout) {
    return (
      <div className="min-h-screen bg-[var(--bg-main)] text-[var(--text-main)] overflow-x-hidden selection:bg-indigo-100 selection:text-indigo-600">
        {children}
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-[var(--bg-main)] text-[var(--text-main)] overflow-x-hidden selection:bg-indigo-100 selection:text-indigo-600">
      {/* Sidebar - Now fixed/floating */}
      <Sidebar isMobileOpen={isMobileSidebarOpen} setIsMobileOpen={setIsMobileSidebarOpen} />
      
      {/* Backdrop for mobile */}
      {isMobileSidebarOpen && (
        <div 
          className="fixed inset-0 bg-black/40 backdrop-blur-xs z-40 md:hidden animate-in fade-in duration-200"
          onClick={() => setIsMobileSidebarOpen(false)}
        />
      )}
      
      {/* Spacer to prevent content from going under the fixed collapsed sidebar */}
      <div className="w-[72px] h-screen shrink-0 hidden md:block" />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col relative w-full h-screen overflow-y-auto no-scrollbar scroll-smooth">
        {/* Top Navbar */}
        <Navbar onMenuClick={() => setIsMobileSidebarOpen(true)} />

        {/* Page Content */}
        <main className="flex-1 px-4 sm:px-6 py-6 w-full">
          <div className="max-w-[1600px] mx-auto space-y-8">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
};

export default PrivateRoute;
