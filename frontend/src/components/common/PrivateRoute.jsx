import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import Sidebar from '../layout/Sidebar';
import Navbar from '../layout/Navbar';

const PrivateRoute = ({ children }) => {
  const { user } = useAuth();

  if (!user) {
    return <Navigate to="/login" />;
  }

  return (
    <div className="flex min-h-screen bg-[var(--bg-main)] text-[var(--text-main)] overflow-x-hidden selection:bg-indigo-100 selection:text-indigo-600">
      {/* Sidebar - Now fixed/floating */}
      <Sidebar />
      {/* Spacer to prevent content from going under the fixed collapsed sidebar */}
      <div className="w-[72px] h-screen shrink-0 hidden md:block" />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col relative w-full h-screen overflow-y-auto no-scrollbar scroll-smooth">
        {/* Top Navbar */}
        <Navbar />

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
