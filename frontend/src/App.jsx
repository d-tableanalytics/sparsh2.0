import React, { lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, Outlet } from 'react-router-dom';
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
import ORMPage from './pages/ORM/ORMPage';
import ORMSetup from './pages/ORM/ORMSetup';
import ORMSheet from './pages/ORM/ORMSheet';
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
import RequireTaskAccess from './components/common/RequireTaskAccess';
import ModulePlaceholder from './features/tpms/common/ModulePlaceholder';
import AdminView from './features/tpms/admin/pages/AdminView';
import OmSmopsView from './features/tpms/admin/pages/OmSmopsView';
import ImplementationTracker from './features/tpms/admin/pages/ImplementationTracker';
import ClientView from './features/tpms/admin/pages/ClientView';
import Escalations from './features/tpms/admin/pages/Escalations';
import LogsReport from './features/tpms/admin/pages/LogsReport';
import HodView from './features/tpms/admin/pages/HodView';
import EmployeeTasks from './features/tpms/admin/pages/EmployeeTasks';
import ReviewReport from './features/tpms/common/ReviewReport';
import ImplementationFeedback from './features/tpms/admin/pages/forms/ImplementationFeedback';
import Ownership from './features/tpms/admin/pages/forms/Ownership';
import Culture from './features/tpms/admin/pages/forms/Culture';
import Accountability from './features/tpms/admin/pages/forms/Accountability';
import { CompanyProvider } from './features/tpms/smops/CompanyContext';
import SmopsDashboard from './features/tpms/smops/pages/SmopsDashboard';
import HodActivity from './features/tpms/smops/pages/HodActivity';
import SmopsEmployeeTask from './features/tpms/smops/pages/SmopsEmployeeTask';
import TpmsGate, { RequireTpms } from './features/tpms/TpmsGate';
import ClientFormsHome from './features/tpms/client/ClientFormsHome';
import ClientRatingForm from './features/tpms/client/ClientRatingForm';
import ClientFeedbackForm from './features/tpms/client/ClientFeedbackForm';
import ClientDashboard from './features/tpms/client/ClientDashboard';
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

// Blocks client-side users from ORM pages when their company's ORM module is off.
const OrmGuard = ({ children }) => {
  const { user } = useAuth();
  const isStaff = ['superadmin', 'admin'].includes(user?.role);
  if (user && !isStaff && user.orm_enabled === false) {
    return <Navigate to="/" />;
  }
  return children;
};

// The /tpms/smops Dashboard is shared: client-side users get the real ClientDashboard
// (their own company's Success-Measure scorecard); internal users keep the SMOPS view.
const TpmsDashboardIndex = () => {
  const { user } = useAuth();
  const isClient = ['clientadmin', 'clientuser'].includes(user?.role);
  return isClient ? <ClientDashboard /> : <SmopsDashboard />;
};

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

      {/* Task Management Module — internal-Sparsh-only (RequireTaskAccess) */}
      <Route path="/tasks" element={<PrivateRoute><RequireTaskAccess><TaskDashboard /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/my" element={<PrivateRoute><RequireTaskAccess><MyTasks /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/delegated" element={<PrivateRoute><RequireTaskAccess><DelegatedTasks /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/subscribed" element={<PrivateRoute><RequireTaskAccess><SubscribedTasks /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/all" element={<PrivateRoute><RequireTaskAccess><AllTasks /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/activity" element={<PrivateRoute><RequireTaskAccess><TaskActivity /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/holiday" element={<PrivateRoute><RequireTaskAccess><Holiday /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/tasks/deleted" element={<PrivateRoute><RequireTaskAccess><DeletedTasks /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/sessions" element={<PrivateRoute><LearnerSessions /></PrivateRoute>} />
      <Route path="/company-portal" element={<PrivateRoute><CompanyPortal /></PrivateRoute>} />
      <Route path="/my-reports" element={<PrivateRoute><MyReports /></PrivateRoute>} />
      <Route path="/orm" element={<PrivateRoute><OrmGuard><ORMPage /></OrmGuard></PrivateRoute>} />
      <Route path="/orm/setup" element={<PrivateRoute><OrmGuard><ORMSetup /></OrmGuard></PrivateRoute>} />
      <Route path="/orm/sheet" element={<PrivateRoute><OrmGuard><ORMSheet /></OrmGuard></PrivateRoute>} />
      
      <Route path="/media" element={<PrivateRoute><MediaLibrary /></PrivateRoute>} />

      {/* Admin Side: Staff Management */}
      <Route path="/admin/users" element={<PrivateRoute><UserManagement /></PrivateRoute>} />
      <Route path="/admin/users/:userId" element={<PrivateRoute><UserDetails /></PrivateRoute>} />

      {/* Admin Reports & Analytics (superadmin only; guarded inside the pages too) */}
      <Route path="/admin/reports" element={<PrivateRoute><ReportsDashboard /></PrivateRoute>} />
      <Route path="/admin/reports/employee/:userId" element={<PrivateRoute><EmployeeReport /></PrivateRoute>} />
      <Route path="/admin/reports/:doerId" element={<PrivateRoute><DoerReportDetails /></PrivateRoute>} />
      {/* ===================  TPMS  ===================
          Dynamic entry: /tpms auto-routes by role (admin → admin panel,
          everyone else → SMOPS). Panels are role-guarded via RequireTpms. */}
      <Route path="/tpms" element={<PrivateRoute><TpmsGate /></PrivateRoute>} />

      {/* TPMS ▸ ADMIN PANEL (superadmin / admin only) — rendered inside the main app
          layout; navigation is driven by the main Sidebar's TPMS dropdown. */}
      <Route path="/tpms/admin" element={<PrivateRoute><RequireTpms admin><Outlet /></RequireTpms></PrivateRoute>}>
        <Route index                 element={<AdminView />} />
        <Route path="om"             element={<OmSmopsView />} />
        <Route path="implementation" element={<ImplementationTracker />} />
        <Route path="clients"        element={<ClientView />} />
        <Route path="escalations"    element={<Escalations />} />
        <Route path="logs"           element={<LogsReport />} />
        <Route path="hod"            element={<HodView />} />
        <Route path="employee-tasks" element={<EmployeeTasks />} />
        {/* Forms sub-module: Implementation Feedback / Ownership / Culture / Accountability */}
        <Route path="forms" element={<Outlet />}>
          <Route index element={<Navigate to="implementation-feedback" replace />} />
          <Route path="implementation-feedback" element={<ImplementationFeedback />} />
          <Route path="ownership"                element={<Ownership />} />
          <Route path="culture"                  element={<Culture />} />
          <Route path="accountability"           element={<Accountability />} />
        </Route>
        <Route path="reviews"        element={<ReviewReport />} />
      </Route>

      {/* TPMS ▸ SMOPS PANEL (any internal user) — rendered inside the main app layout.
          CompanyProvider supplies the shared company selection the SMOPS pages consume. */}
      <Route path="/tpms/smops" element={<PrivateRoute><RequireTpms><CompanyProvider><Outlet /></CompanyProvider></RequireTpms></PrivateRoute>}>
        <Route index                element={<TpmsDashboardIndex />} />
        <Route path="hod-activity"  element={<HodActivity />} />
        <Route path="tasks"         element={<SmopsEmployeeTask />} />
        <Route path="reviews"       element={<ReviewReport title="Review Report" subtitle="Detailed evaluation and feedback for your companies." />} />
      </Route>

      {/* TPMS ▸ CLIENT FORMS PANEL (client-side users) — rendered inside the main app layout.
          Each client fills their own forms; HODs additionally rate their team. Available to
          every client company by default; guarded via RequireTpms client. */}
      <Route path="/tpms/forms" element={<PrivateRoute><RequireTpms><Outlet /></RequireTpms></PrivateRoute>}>
        <Route index                          element={<ClientFormsHome />} />
        <Route path="accountability"          element={<ClientRatingForm formType="accountability" />} />
        <Route path="ownership"               element={<ClientRatingForm formType="ownership" />} />
        <Route path="culture"                 element={<ClientRatingForm formType="culture" />} />
        <Route path="implementation-feedback" element={<ClientFeedbackForm formType="implementation_feedback" />} />
      </Route>

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
