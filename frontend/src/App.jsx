import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import Dashboard from './pages/Dashboard';
import Login from './pages/Login';
import CompanyManagement from './pages/CompanyManagement';
import CompanyDetails from './pages/CompanyDetails';
import MemberDashboard from './pages/MemberDashboard';
import BatchManagement from './pages/BatchManagement';
import BatchDetails from './pages/BatchDetails';
import QuarterDetails from './pages/QuarterDetails';
import SessionTemplateManagement from './pages/SessionTemplateManagement';
import SessionTemplateDetails from './pages/SessionTemplateDetails';
import SessionDetails from './pages/SessionDetails';
import ContentViewer from './pages/ContentViewer';
import CalendarPage from './pages/CalendarPage';
import UserManagement from './pages/UserManagement';
import UserDetails from './pages/UserDetails';
import SettingsPage from './pages/SettingsPage';
import GptProjects from './pages/GptProjects';
import GptEditor from './pages/GptEditor';
import GptChat from './pages/GptChat';
import LearnerSessions from './pages/LearnerSessions';
import PrivateRoute from './components/common/PrivateRoute';
import './index.css';
import { useAuth } from './context/AuthContext';

const AppRoutes = () => {
  const { user } = useAuth();

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" /> : <Login />} />

      <Route path="/" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
      <Route path="/dashboard" element={<Navigate to="/" />} />

      <Route path="/companies" element={<PrivateRoute><CompanyManagement /></PrivateRoute>} />
      <Route path="/companies/:companyId" element={<PrivateRoute><CompanyDetails /></PrivateRoute>} />
      <Route path="/members/:userId" element={<PrivateRoute><MemberDashboard /></PrivateRoute>} />
      <Route path="/batches" element={<PrivateRoute><BatchManagement /></PrivateRoute>} />
      <Route path="/batches/:batchId" element={<PrivateRoute><BatchDetails /></PrivateRoute>} />
      <Route path="/quarters/:quarterId" element={<PrivateRoute><QuarterDetails /></PrivateRoute>} />
      <Route path="/session-templates" element={<PrivateRoute><SessionTemplateManagement /></PrivateRoute>} />
      <Route path="/session-templates/:templateId" element={<PrivateRoute><SessionTemplateDetails /></PrivateRoute>} />
      <Route path="/sessions/:sessionId" element={<PrivateRoute><SessionDetails /></PrivateRoute>} />
      <Route path="/sessions/:sessionId/resource/:resourceId" element={<PrivateRoute><ContentViewer /></PrivateRoute>} />
      <Route path="/calendar" element={<PrivateRoute><CalendarPage /></PrivateRoute>} />
      <Route path="/sessions" element={<PrivateRoute><LearnerSessions /></PrivateRoute>} />
      
      {/* Admin Side: Staff Management */}
      <Route path="/admin/users" element={<PrivateRoute><UserManagement /></PrivateRoute>} />
      <Route path="/admin/users/:userId" element={<PrivateRoute><UserDetails /></PrivateRoute>} />
      <Route path="/admin/settings" element={<PrivateRoute><SettingsPage /></PrivateRoute>} />

      {/* GPT Module */}
      <Route path="/gpt" element={<PrivateRoute><GptProjects /></PrivateRoute>} />
      <Route path="/gpt/new" element={<PrivateRoute><GptEditor /></PrivateRoute>} />
      <Route path="/gpt/edit/:id" element={<PrivateRoute><GptEditor /></PrivateRoute>} />
      <Route path="/gpt/chat/:id" element={<PrivateRoute><GptChat /></PrivateRoute>} />

      {/* Catch-all */}
      <Route path="*" element={<Navigate to={user ? "/" : "/login"} />} />
    </Routes>
  );
};

const App = () => {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Router>
          <AppRoutes />
        </Router>
      </AuthProvider>
    </ThemeProvider>
  );
};

export default App;
