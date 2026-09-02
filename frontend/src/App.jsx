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
import IRMPage from './pages/IRM/IRMPage';
import IRMSetup from './pages/IRM/IRMSetup';
import MediaLibrary from './pages/MediaLibrary';
import TaskDashboard from './pages/TaskDashboard';
import MyTasks from './pages/MyTasks';
import DelegatedTasks from './pages/DelegatedTasks';
import SubscribedTasks from './pages/SubscribedTasks';
import AllTasks from './pages/AllTasks';
import TaskActivity from './pages/TaskActivity';
import Holiday from './pages/Holiday';
import DeletedTasks from './pages/DeletedTasks';
import NotifyTemplateAdmin from './pages/notifications/NotifyTemplateAdmin';
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
import ActivityManagement from './features/tpms/admin/pages/ActivityManagement';
import DepartmentManagement from './features/tpms/admin/pages/DepartmentManagement';
import ClientActivityCalendar from './features/tpms/admin/pages/ClientActivityCalendar';
import MailTemplateAdmin from './features/tpms/admin/pages/MailTemplateAdmin';
import ReminderRuleAdmin from './features/tpms/admin/pages/ReminderRuleAdmin';
import FormQuestionAdmin from './features/tpms/admin/pages/FormQuestionAdmin';
import FormLinks from './features/tpms/admin/pages/FormLinks';
import ReviewReport from './features/tpms/common/ReviewReport';
// TPMS ▸ Leadership Score (additive — no existing TPMS route is changed).
import LeadershipCycles from './features/tpms/admin/pages/LeadershipCycles';
import LeadershipSubjects from './features/tpms/admin/pages/LeadershipSubjects';
import LeadershipQuestions from './features/tpms/admin/pages/LeadershipQuestions';
import LeadershipTemplate from './features/tpms/admin/pages/LeadershipTemplate';
import LeadershipReport from './features/tpms/common/LeadershipReport';
import LeadershipFormPage from './features/tpms/leadership/LeadershipFormPage';
import { CompanyProvider } from './features/tpms/smops/CompanyContext';
import SmopsDashboard from './features/tpms/smops/pages/SmopsDashboard';
import HodActivity from './features/tpms/smops/pages/HodActivity';
import SmopsEmployeeTask from './features/tpms/smops/pages/SmopsEmployeeTask';
import TpmsGate, { RequireTpms } from './features/tpms/TpmsGate';
import TpmsCalendar from './features/tpms/calendar/TpmsCalendar';
import AssignedFormPage from './features/tpms/forms/AssignedFormPage';
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
      {/* Login owns the post-auth redirect. It must NOT be short-circuited with a Navigate to
          "/" here: the moment auth succeeds this element would re-render and send the user to
          the dashboard, discarding the deep link PrivateRoute stored (e.g. an assigned form at
          /f/<token>). Login redirects an already-signed-in visitor itself, so the behaviour for
          an ordinary /login visit is unchanged. */}
      <Route path="/login" element={<Login />} />

      {/* TPMS assigned form. Authenticated like every other page: an unauthenticated visitor is
          sent to /login and returned here afterwards (PrivateRoute stores the URL, Login reads
          it back). The token selects WHICH of the four forms renders — the backend also checks
          the signed-in user is the assignment's respondent, so a forwarded link opens nothing. */}
      <Route path="/f/:token" element={<PrivateRoute><AssignedFormPage /></PrivateRoute>} />

      {/* TPMS Leadership Score feedback form. Its own route so the existing /f/:token flow
          for the four original forms is untouched. Same two-check security model: the
          token must resolve to a live assignment AND the signed-in user must be its
          feedback giver, so a forwarded link opens nothing. */}
      <Route path="/lf/:token" element={<PrivateRoute><LeadershipFormPage /></PrivateRoute>} />
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
      {/* Delegation & Checklist notification templates. Admin-gated inside the page itself,
          the same way the TPMS templates screen is. */}
      <Route path="/tasks/templates" element={<PrivateRoute><RequireTaskAccess><NotifyTemplateAdmin /></RequireTaskAccess></PrivateRoute>} />
      <Route path="/sessions" element={<PrivateRoute><LearnerSessions /></PrivateRoute>} />
      <Route path="/company-portal" element={<PrivateRoute><CompanyPortal /></PrivateRoute>} />
      <Route path="/my-reports" element={<PrivateRoute><MyReports /></PrivateRoute>} />
      <Route path="/orm" element={<PrivateRoute><OrmGuard><ORMPage /></OrmGuard></PrivateRoute>} />
      <Route path="/orm/setup" element={<PrivateRoute><OrmGuard><ORMSetup /></OrmGuard></PrivateRoute>} />
      <Route path="/orm/sheet" element={<PrivateRoute><OrmGuard><ORMSheet /></OrmGuard></PrivateRoute>} />

      {/* IRM — Individual Result Matrix. Scores are per person; the weightage setup is
          role-guarded inside the page (staff + clientadmin). */}
      <Route path="/irm" element={<PrivateRoute><IRMPage /></PrivateRoute>} />
      <Route path="/irm/setup" element={<PrivateRoute><IRMSetup /></PrivateRoute>} />


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
        <Route path="calendar"       element={<TpmsCalendar />} />
        <Route path="client-calendar" element={<ClientActivityCalendar />} />
        <Route path="activities"     element={<ActivityManagement />} />
        <Route path="departments"    element={<DepartmentManagement />} />
        <Route path="mail-templates" element={<MailTemplateAdmin />} />
        <Route path="reminder-rules" element={<ReminderRuleAdmin />} />
        <Route path="form-questions" element={<FormQuestionAdmin />} />
        <Route path="form-links"     element={<FormLinks />} />
        <Route path="reviews"        element={<ReviewReport />} />
        {/* Leadership Score — additive; the routes above are unchanged. */}
        <Route path="leadership"           element={<LeadershipCycles />} />
        <Route path="leadership/subjects"  element={<LeadershipSubjects />} />
        <Route path="leadership/questions" element={<LeadershipQuestions />} />
        <Route path="leadership/template"  element={<LeadershipTemplate />} />
        <Route path="leadership/report"    element={<LeadershipReport />} />
      </Route>

      {/* TPMS ▸ SMOPS PANEL (any internal user) — rendered inside the main app layout.
          CompanyProvider supplies the shared company selection the SMOPS pages consume. */}
      <Route path="/tpms/smops" element={<PrivateRoute><RequireTpms><CompanyProvider><Outlet /></CompanyProvider></RequireTpms></PrivateRoute>}>
        <Route index                element={<TpmsDashboardIndex />} />
        {/* Calendar is shared by every TPMS audience — internal SMOPS users and
            client-side doers alike; the page itself gates the lifecycle actions by role. */}
        <Route path="calendar"      element={<TpmsCalendar />} />
        <Route path="hod-activity"  element={<HodActivity />} />
        <Route path="tasks"         element={<SmopsEmployeeTask />} />
        <Route path="reviews"       element={<ReviewReport title="Review Report" subtitle="Detailed evaluation and feedback for your companies." />} />
        {/* Leadership Score for the client/SMOPS side. The report is self-scoping: HR sees
            every enrolled leader, a manager their direct reports, a leader only their own. */}
        <Route path="leadership"           element={<LeadershipReport />} />
        <Route path="leadership/cycles"    element={<LeadershipCycles />} />
        <Route path="leadership/subjects"  element={<LeadershipSubjects />} />
        {/* HR and the MD reach the question bank to REVIEW and sign off a level — the
            page itself keeps the wording and weightages editable by staff only. A cycle
            cannot be closed until every level it scores has been signed off. */}
        <Route path="leadership/questions" element={<LeadershipQuestions />} />
        {/* Each company's own invitation wording. Scoped to the caller's company by
            `_company_for`, so a client admin can only ever edit their own. */}
        <Route path="leadership/template"  element={<LeadershipTemplate />} />
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
