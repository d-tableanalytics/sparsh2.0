import React, { lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import { NotificationProvider } from './context/NotificationContext';
import NotificationModal from './components/common/NotificationModal';
import Dashboard from './pages/Dashboard';
import Login from './pages/Login';
import CompanyManagement from './pages/CompanyManagement';
import CompanyDetails from './pages/CompanyDetails';
import MemberPortal from './pages/MemberDashboard';
import TeamManagement from './pages/TeamManagement';
import MemberDetails from './pages/MemberDetails';
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
import ProfilePage from './pages/ProfilePage';
import GptProjects from './pages/GptProjects';
import GptEditor from './pages/GptEditor';
import GptChat from './pages/GptChat';
import GptAccessControl from './pages/GptAccessControl';
import LearnerSessions from './pages/LearnerSessions';
import CompanyPortal from './pages/CompanyPortal';
import AssessmentPlayer from './pages/AssessmentPlayer';
import MyReports from './pages/MyReports';
import MediaLibrary from './pages/MediaLibrary';
import TaskDashboard from './pages/TaskDashboard';
import MyTasks from './pages/MyTasks';
import DelegatedTasks from './pages/DelegatedTasks';
import SubscribedTasks from './pages/SubscribedTasks';
import AllTasks from './pages/AllTasks';
import TaskActivity from './pages/TaskActivity';
import Holiday from './pages/Holiday';
import DeletedTasks from './pages/DeletedTasks';
import ForgotPassword from './pages/ForgotPassword';
import PrivateRoute from './components/common/PrivateRoute';
import AssistantWidget from './features/assistant';
import './index.css';
import { useAuth } from './context/AuthContext';
import { UploadProvider } from './context/UploadContext';

// Admin Reports & Analytics module (superadmin only) — lazy-loaded to keep it out
// of the main bundle since it pulls in extra recharts chart types.
const ReportsDashboard = lazy(() => import('./pages/ReportsDashboard'));
const DoerReportDetails = lazy(() => import('./pages/DoerReportDetails'));
const EmployeeReport = lazy(() => import('./pages/EmployeeReport'));

const RouteFallback = () => (
  <div className="py-20 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading…</div>
);

const AppRoutes = () => {
  const { user } = useAuth();

  return (
    <Suspense fallback={<RouteFallback />}>
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" /> : <Login />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />

      <Route path="/" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
      <Route path="/dashboard" element={<Navigate to="/" />} />

      <Route path="/companies" element={<PrivateRoute><CompanyManagement /></PrivateRoute>} />
      <Route path="/companies/:companyId" element={<PrivateRoute><CompanyDetails /></PrivateRoute>} />
      <Route path="/members/:userId" element={<PrivateRoute><MemberPortal /></PrivateRoute>} />
      <Route path="/team" element={<PrivateRoute><TeamManagement /></PrivateRoute>} />
      <Route path="/batches" element={<PrivateRoute><BatchManagement /></PrivateRoute>} />
      <Route path="/batches/:batchId" element={<PrivateRoute><BatchDetails /></PrivateRoute>} />
      <Route path="/quarters/:quarterId" element={<PrivateRoute><QuarterDetails /></PrivateRoute>} />
      <Route path="/session-templates" element={<PrivateRoute><SessionTemplateManagement /></PrivateRoute>} />
      <Route path="/session-templates/:templateId" element={<PrivateRoute><SessionTemplateDetails /></PrivateRoute>} />
      <Route path="/sessions/:sessionId" element={<PrivateRoute><SessionDetails /></PrivateRoute>} />
      <Route path="/sessions/:sessionId/resource/:resourceId" element={<PrivateRoute><ContentViewer /></PrivateRoute>} />
      <Route path="/calendar" element={<PrivateRoute><CalendarPage /></PrivateRoute>} />

      {/* Task Management Module */}
      <Route path="/tasks" element={<PrivateRoute><TaskDashboard /></PrivateRoute>} />
      <Route path="/tasks/my" element={<PrivateRoute><MyTasks /></PrivateRoute>} />
      <Route path="/tasks/delegated" element={<PrivateRoute><DelegatedTasks /></PrivateRoute>} />
      <Route path="/tasks/subscribed" element={<PrivateRoute><SubscribedTasks /></PrivateRoute>} />
      <Route path="/tasks/all" element={<PrivateRoute><AllTasks /></PrivateRoute>} />
      <Route path="/tasks/activity" element={<PrivateRoute><TaskActivity /></PrivateRoute>} />
      <Route path="/tasks/holiday" element={<PrivateRoute><Holiday /></PrivateRoute>} />
      <Route path="/tasks/deleted" element={<PrivateRoute><DeletedTasks /></PrivateRoute>} />
      <Route path="/sessions" element={<PrivateRoute><LearnerSessions /></PrivateRoute>} />
      <Route path="/company-portal" element={<PrivateRoute><CompanyPortal /></PrivateRoute>} />
      <Route path="/my-reports" element={<PrivateRoute><MyReports /></PrivateRoute>} />
      <Route path="/media" element={<PrivateRoute><MediaLibrary /></PrivateRoute>} />

      {/* Admin Side: Staff Management */}
      <Route path="/admin/users" element={<PrivateRoute><UserManagement /></PrivateRoute>} />
      <Route path="/admin/users/:userId" element={<PrivateRoute><UserDetails /></PrivateRoute>} />

      {/* Admin Reports & Analytics (superadmin only; guarded inside the pages too) */}
      <Route path="/admin/reports" element={<PrivateRoute><ReportsDashboard /></PrivateRoute>} />
      <Route path="/admin/reports/employee/:userId" element={<PrivateRoute><EmployeeReport /></PrivateRoute>} />
      <Route path="/admin/reports/:doerId" element={<PrivateRoute><DoerReportDetails /></PrivateRoute>} />
      <Route path="/admin/settings" element={<Navigate to="/settings" />} />
      <Route path="/settings" element={<PrivateRoute><SettingsPage /></PrivateRoute>} />
      <Route path="/profile" element={<PrivateRoute><ProfilePage /></PrivateRoute>} />

      {/* GPT Module */}
      <Route path="/gpt" element={<PrivateRoute><GptProjects /></PrivateRoute>} />
      <Route path="/gpt/new" element={<PrivateRoute><GptEditor /></PrivateRoute>} />
      <Route path="/gpt/edit/:id" element={<PrivateRoute><GptEditor /></PrivateRoute>} />
      <Route path="/gpt/chat/:id" element={<PrivateRoute><GptChat /></PrivateRoute>} />
      <Route path="/gpt/chat/:id/:sessionId" element={<PrivateRoute><GptChat /></PrivateRoute>} />
      <Route path="/gpt/permissions" element={<PrivateRoute><GptAccessControl /></PrivateRoute>} />

      {/* Assessment Player (Locked/Blank Mode) */}
      <Route path="/assessment/:sessionId/:quizIndex" element={<PrivateRoute hideLayout={true}><AssessmentPlayer /></PrivateRoute>} />

      {/* Catch-all */}
      <Route path="*" element={<Navigate to={user ? "/" : "/login"} />} />
    </Routes>
    </Suspense>
  );
};

const App = () => {
  return (
    <ThemeProvider>
      <AuthProvider>
        <NotificationProvider>
          <UploadProvider>
            <Router>
              <AppRoutes />
            </Router>
            <AssistantWidget />
          </UploadProvider>
          <NotificationModal />
        </NotificationProvider>
      </AuthProvider>
    </ThemeProvider>
  );
};

export default App;
