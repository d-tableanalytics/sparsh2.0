import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../services/api';
import Modal from '../components/common/Modal';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft, User, Mail, Phone, Briefcase, Shield,
  Pencil, Trash2, Save, X,
  BookOpen, CalendarCheck, Clock, Activity,
  CheckCircle2, XCircle, AlertTriangle, Building2,
  TrendingUp, Target, Award, Zap, BarChart3
} from 'lucide-react';
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Area, AreaChart, RadialBarChart, RadialBar
} from 'recharts';

// ─── Theme Colors ───
const CHART_COLORS = ['#6366f1', '#22c55e', '#f97316', '#eab308', '#ec4899', '#06b6d4'];

// ─── Shared Components ───
const InfoCard = ({ icon: Icon, label, value, color }) => (
  <div className="flex items-start gap-3 py-2">
    <div className="p-2 rounded-lg" style={{ background: `var(--accent-${color || 'indigo'}-bg)` }}>
      <Icon size={14} style={{ color: `var(--accent-${color || 'indigo'})` }} />
    </div>
    <div className="flex flex-col">
      <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">{label}</span>
      <span className="text-[13px] font-medium text-[var(--text-main)]">{value || '—'}</span>
    </div>
  </div>
);

const StatCard = ({ icon: Icon, label, value, sub, color }) => (
  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 flex items-center gap-4 hover:border-[var(--accent-indigo-border)] transition-all">
    <div className="p-3 rounded-xl shrink-0" style={{ background: `var(--accent-${color}-bg)` }}>
      <Icon size={20} style={{ color: `var(--accent-${color})` }} />
    </div>
    <div className="min-w-0">
      <p className="text-2xl font-black text-[var(--text-main)] leading-none">{value}</p>
      <p className="text-[11px] text-[var(--text-muted)] font-bold uppercase tracking-wider mt-1">{label}</p>
      {sub && <p className="text-[10px] text-[var(--accent-green)] font-bold mt-0.5">{sub}</p>}
    </div>
  </div>
);

// ─── Mock Data Generators ───
const generateWeeklyScores = () => {
  const weeks = ['W1', 'W2', 'W3', 'W4', 'W5', 'W6', 'W7', 'W8'];
  return weeks.map(w => ({
    week: w,
    score: Math.floor(Math.random() * 25 + 65),
    target: 85,
  }));
};

const generateAttendanceData = () => {
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'];
  return months.map(m => ({
    name: m,
    present: Math.floor(Math.random() * 8 + 12),
    absent: Math.floor(Math.random() * 4 + 1),
  }));
};

const generateLearningProgress = () => [
  { name: 'Leadership', completed: 85, total: 100 },
  { name: 'Strategy', completed: 60, total: 100 },
  { name: 'Operations', completed: 45, total: 100 },
  { name: 'Finance', completed: 92, total: 100 },
  { name: 'HR & People', completed: 70, total: 100 },
];

const generateSkillRadial = () => [
  { name: 'Overall', value: Math.floor(Math.random() * 20 + 70), fill: '#6366f1' },
];

const generateTaskPie = () => [
  { name: 'Completed', value: Math.floor(Math.random() * 15 + 20) },
  { name: 'In Progress', value: Math.floor(Math.random() * 8 + 5) },
  { name: 'Overdue', value: Math.floor(Math.random() * 5 + 1) },
];

const generateActivityTimeline = () => {
  const actions = [
    'Completed "Leadership Basics" module',
    'Attended Core Session #14',
    'Submitted Mid-term Assessment',
    'Missed Support Session #8',
    'Scored 92% on Finance Quiz',
    'Joined Batch "Alpha-Q2"',
    'Updated profile information',
    'Completed "Strategy Planning" assessment',
  ];
  return actions.map((a, i) => ({
    _id: String(i),
    action: a,
    timestamp: new Date(Date.now() - i * 86400000 * Math.floor(Math.random() * 3 + 1)).toISOString(),
    type: ['learning', 'attendance', 'assessment', 'attendance', 'assessment', 'batch', 'profile', 'assessment'][i],
  }));
};

// ─── Main Component ───
const MemberDashboard = () => {
  const { userId } = useParams();
  const navigate = useNavigate();

  const [member, setMember] = useState(null);
  const [activity, setActivity] = useState({ learnings: [], attendance: [], activities: [] });
  const [loading, setLoading] = useState(true);
  const [editMode, setEditMode] = useState(false);
  const [editData, setEditData] = useState({});
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [activeTab, setActiveTab] = useState('overview');

  const fetchData = async () => {
    try {
      const [userRes, activityRes] = await Promise.all([
        api.get(`/users/${userId}`),
        api.get(`/users/${userId}/activity`)
      ]);
      setMember(userRes.data);
      setEditData(userRes.data);
      setActivity(activityRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, [userId]);

  const handleSaveEdit = async () => {
    try {
      const { _id, email, password, created_at, company_id, is_active, updated_at, ...fields } = editData;
      await api.put(`/users/${userId}`, fields);
      setEditMode(false);
      fetchData();
    } catch (err) { alert('Update failed'); }
  };

  const handleStatusToggle = async () => {
    try {
      await api.patch(`/users/${userId}/status`, { is_active: !member.is_active });
      fetchData();
    } catch (err) { alert('Status change failed'); }
  };

  const handleDelete = async () => {
    try {
      await api.delete(`/users/${userId}`);
      navigate(-1);
    } catch (err) { alert('Delete failed'); }
  };

  if (loading) return (
    <div className="flex items-center justify-center py-32">
      <div className="w-8 h-8 border-2 border-[var(--accent-indigo-border)] border-t-[var(--accent-indigo)] rounded-full animate-spin"></div>
    </div>
  );

  if (!member) return <div className="text-center py-20 text-[var(--text-muted)]">Member not found</div>;

  // Generate chart data
  const weeklyScores = generateWeeklyScores();
  const attendanceData = generateAttendanceData();
  const learningProgress = generateLearningProgress();
  const skillRadial = generateSkillRadial();
  const taskPie = generateTaskPie();
  const mockTimeline = activity.activities.length > 0 ? activity.activities : generateActivityTimeline();
  const daysSinceJoined = member.created_at ? Math.floor((Date.now() - new Date(member.created_at).getTime()) / 86400000) : 0;
  const totalPresent = attendanceData.reduce((s, d) => s + d.present, 0);
  const totalAbsent = attendanceData.reduce((s, d) => s + d.absent, 0);
  const attendanceRate = Math.round((totalPresent / (totalPresent + totalAbsent)) * 100);

  const tabs = [
    { id: 'overview', label: 'Overview & Analytics', icon: BarChart3 },
    { id: 'learnings', label: 'Learnings', icon: BookOpen },
    { id: 'attendance', label: 'Attendance', icon: CalendarCheck },
    { id: 'history', label: 'Activity Log', icon: Clock },
  ];

  return (
    <div className="space-y-6">
      {/* ─── Header ─── */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate(-1)} className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--accent-indigo-bg)] hover:text-[var(--accent-indigo)] transition-all">
            <ArrowLeft size={18} />
          </button>
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl flex items-center justify-center text-white font-black text-sm" style={{ background: 'var(--avatar-bg)' }}>
              {member.full_name?.charAt(0) || member.email?.charAt(0) || '?'}
            </div>
            <div>
              <h1 className="text-xl font-bold text-[var(--text-main)] tracking-tight">{member.full_name || 'Unnamed User'}</h1>
              <p className="text-[12px] text-[var(--text-muted)]">{member.email} · {member.role}</p>
            </div>
          </div>
          <span className={`px-2.5 py-1 rounded-md text-[11px] font-bold uppercase tracking-wider inline-flex items-center gap-1.5 ${
            member.is_active !== false
              ? 'bg-[var(--status-active-bg)] text-[var(--status-active-text)] border border-[var(--status-active-border)]'
              : 'bg-[var(--accent-red-bg)] text-[var(--accent-red)] border border-[var(--accent-red-border)]'
          }`}>
            {member.is_active !== false ? <><CheckCircle2 size={12} /> Active</> : <><XCircle size={12} /> Inactive</>}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setEditMode(!editMode)} className="h-9 px-4 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)] rounded-lg text-[12px] font-bold flex items-center gap-2 hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)] transition-all">
            <Pencil size={14} /> Edit
          </button>
          <button onClick={handleStatusToggle} className={`h-9 px-4 rounded-lg text-[12px] font-bold flex items-center gap-2 border transition-all ${
            member.is_active !== false
              ? 'bg-[var(--accent-yellow-bg)] border-[var(--accent-yellow-border)] text-[var(--accent-yellow)]'
              : 'bg-[var(--accent-green-bg)] border-[var(--accent-green-border)] text-[var(--accent-green)]'
          }`}>
            {member.is_active !== false ? <><XCircle size={14} /> Deactivate</> : <><CheckCircle2 size={14} /> Activate</>}
          </button>
          <button onClick={() => setShowDeleteConfirm(true)} className="h-9 px-4 bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] text-[var(--accent-red)] rounded-lg text-[12px] font-bold flex items-center gap-2 hover:opacity-80 transition-all">
            <Trash2 size={14} /> Delete
          </button>
        </div>
      </div>

      {/* ─── Edit Panel ─── */}
      <AnimatePresence>
        {editMode && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="bg-[var(--bg-card)] border border-[var(--accent-indigo-border)] rounded-xl p-6 overflow-hidden">
            <h3 className="text-[14px] font-bold text-[var(--text-main)] mb-4">Edit Member</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {[
                { key: 'first_name', label: 'First Name' }, { key: 'last_name', label: 'Last Name' },
                { key: 'mobile', label: 'Mobile' }, { key: 'designation', label: 'Designation' },
              ].map(f => (
                <div key={f.key} className="space-y-1">
                  <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">{f.label}</label>
                  <input value={editData[f.key] || ''} onChange={e => setEditData({ ...editData, [f.key]: e.target.value })}
                    className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md outline-none text-[13px] font-medium text-[var(--text-main)] focus:border-[var(--accent-indigo)]" />
                </div>
              ))}
              <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Role</label>
                <select value={editData.role || ''} onChange={e => setEditData({ ...editData, role: e.target.value })} className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none">
                  <option value="clientadmin">ClientAdmin</option><option value="clientuser">ClientUser</option>
                </select></div>
              <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Session Type</label>
                <select value={editData.session_type || ''} onChange={e => setEditData({ ...editData, session_type: e.target.value })} className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none">
                  <option value="Core">Core</option><option value="Support">Support</option><option value="Both">Both</option><option value="None">None</option>
                </select></div>
              <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Department</label>
                <select value={editData.department || ''} onChange={e => setEditData({ ...editData, department: e.target.value })} className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none">
                  <option value="HOD">HOD</option><option value="Implementor">Implementor</option><option value="EA">EA</option><option value="MD">MD</option><option value="Other">Other</option>
                </select></div>
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={handleSaveEdit} className="h-9 px-6 bg-[var(--accent-green)] text-white rounded-lg text-[12px] font-bold flex items-center gap-2"><Save size={14} /> Save</button>
              <button onClick={() => { setEditMode(false); setEditData(member); }} className="h-9 px-6 bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] rounded-lg text-[12px] font-bold flex items-center gap-2"><X size={14} /> Cancel</button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ─── Tabs ─── */}
      <div className="flex gap-1 bg-[var(--bg-card)] border border-[var(--border)] p-1 rounded-xl w-fit">
        {tabs.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-[12px] font-bold transition-all ${
              activeTab === tab.id ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'
            }`}>
            <tab.icon size={14} /> {tab.label}
          </button>
        ))}
      </div>

      {/* ─── Tab Content ─── */}
      <AnimatePresence mode="wait">

        {/* ════════ OVERVIEW & ANALYTICS ════════ */}
        {activeTab === 'overview' && (
          <motion.div key="overview" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-6">

            {/* Stats */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <StatCard icon={BookOpen} label="Modules Done" value={learningProgress.filter(l => l.completed >= 80).length} sub={`of ${learningProgress.length} total`} color="indigo" />
              <StatCard icon={CalendarCheck} label="Attendance Rate" value={`${attendanceRate}%`} sub={`${totalPresent} sessions`} color="green" />
              <StatCard icon={Target} label="Avg. Score" value={`${Math.round(weeklyScores.reduce((s, d) => s + d.score, 0) / weeklyScores.length)}%`} sub="Last 8 weeks" color="orange" />
              <StatCard icon={Clock} label="Days Active" value={daysSinceJoined} sub="Since onboarding" color="yellow" />
            </div>

            {/* Profile Card */}
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-6">
              <h3 className="text-[14px] font-bold text-[var(--text-main)] mb-3">Member Profile</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-x-8 gap-y-1">
                <InfoCard icon={User} label="Full Name" value={member.full_name} color="indigo" />
                <InfoCard icon={Mail} label="Email" value={member.email} color="orange" />
                <InfoCard icon={Phone} label="Mobile" value={member.mobile} color="green" />
                <InfoCard icon={Shield} label="Role" value={member.role} color="indigo" />
                <InfoCard icon={Briefcase} label="Designation" value={member.designation} color="yellow" />
                <InfoCard icon={Building2} label="Department" value={member.department} color="green" />
                <InfoCard icon={BookOpen} label="Session Type" value={member.session_type} color="orange" />
                <InfoCard icon={Building2} label="Company ID" value={member.company_id} color="indigo" />
              </div>
            </div>

            {/* Charts Row 1 */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Score Trend */}
              <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-[14px] font-bold text-[var(--text-main)]">Assessment Score Trend</h3>
                    <p className="text-[11px] text-[var(--text-muted)]">Weekly performance vs target</p>
                  </div>
                  <TrendingUp size={16} className="text-[var(--accent-green)]" />
                </div>
                <ResponsiveContainer width="100%" height={240}>
                  <AreaChart data={weeklyScores}>
                    <defs>
                      <linearGradient id="memGradIndigo" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="week" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                    <YAxis domain={[50, 100]} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                    <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} />
                    <Area type="monotone" dataKey="score" stroke="#6366f1" fill="url(#memGradIndigo)" strokeWidth={2.5} name="Score %" />
                    <Line type="monotone" dataKey="target" stroke="#ef4444" strokeDasharray="5 5" strokeWidth={1.5} dot={false} name="Target" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              {/* Attendance Chart */}
              <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-[14px] font-bold text-[var(--text-main)]">Attendance Overview</h3>
                    <p className="text-[11px] text-[var(--text-muted)]">Present vs absent by month</p>
                  </div>
                  <CalendarCheck size={16} className="text-[var(--accent-orange)]" />
                </div>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={attendanceData} barGap={4}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                    <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                    <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} />
                    <Bar dataKey="present" fill="#22c55e" radius={[4, 4, 0, 0]} name="Present" />
                    <Bar dataKey="absent" fill="#ef4444" radius={[4, 4, 0, 0]} name="Absent" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Charts Row 2 */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Learning Progress */}
              <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5 lg:col-span-2">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-[14px] font-bold text-[var(--text-main)]">Learning Module Progress</h3>
                    <p className="text-[11px] text-[var(--text-muted)]">Completion % by subject area</p>
                  </div>
                  <BookOpen size={16} className="text-[var(--accent-indigo)]" />
                </div>
                <div className="space-y-4">
                  {learningProgress.map((mod, i) => (
                    <div key={mod.name} className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-[12px] font-bold text-[var(--text-main)]">{mod.name}</span>
                        <span className="text-[12px] font-black" style={{ color: CHART_COLORS[i % CHART_COLORS.length] }}>{mod.completed}%</span>
                      </div>
                      <div className="w-full h-2.5 bg-[var(--input-bg)] rounded-full overflow-hidden">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${mod.completed}%` }}
                          transition={{ duration: 1, delay: i * 0.1 }}
                          className="h-full rounded-full"
                          style={{ background: CHART_COLORS[i % CHART_COLORS.length] }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Task Distribution Pie */}
              <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
                <h3 className="text-[14px] font-bold text-[var(--text-main)] mb-1">Task Status</h3>
                <p className="text-[11px] text-[var(--text-muted)] mb-4">Current task breakdown</p>
                <ResponsiveContainer width="100%" height={180}>
                  <PieChart>
                    <Pie data={taskPie} cx="50%" cy="50%" innerRadius={45} outerRadius={70} dataKey="value" paddingAngle={4} strokeWidth={0}>
                      {taskPie.map((_, i) => (
                        <Cell key={i} fill={['#22c55e', '#f97316', '#ef4444'][i]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex flex-wrap gap-3 justify-center">
                  {taskPie.map((d, i) => (
                    <div key={d.name} className="flex items-center gap-1.5">
                      <div className="w-2 h-2 rounded-full" style={{ background: ['#22c55e', '#f97316', '#ef4444'][i] }}></div>
                      <span className="text-[10px] text-[var(--text-muted)] font-bold">{d.name} ({d.value})</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </motion.div>
        )}

        {/* ════════ LEARNINGS TAB ════════ */}
        {activeTab === 'learnings' && (
          <motion.div key="learnings" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-6">
            {/* Learning Stats */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <StatCard icon={BookOpen} label="Modules Completed" value={learningProgress.filter(l => l.completed >= 80).length} color="green" />
              <StatCard icon={Target} label="Highest Score" value={`${Math.max(...learningProgress.map(l => l.completed))}%`} color="indigo" />
              <StatCard icon={Zap} label="Avg. Completion" value={`${Math.round(learningProgress.reduce((s, l) => s + l.completed, 0) / learningProgress.length)}%`} color="orange" />
            </div>

            {/* Module Table */}
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-[var(--border)]">
                <h3 className="text-[14px] font-bold text-[var(--text-main)]">Learning Modules</h3>
                <p className="text-[11px] text-[var(--text-muted)]">Course progress and completion</p>
              </div>
              <table className="w-full">
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Module</th>
                    <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Progress</th>
                    <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Score</th>
                    <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {learningProgress.map((mod, i) => (
                    <tr key={mod.name} className="hover:bg-[var(--table-hover)] transition-all">
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded-md flex items-center justify-center" style={{ background: `var(--accent-indigo-bg)` }}>
                            <BookOpen size={14} style={{ color: CHART_COLORS[i % CHART_COLORS.length] }} />
                          </div>
                          <span className="text-[13px] font-bold text-[var(--text-main)]">{mod.name}</span>
                        </div>
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-3 w-40">
                          <div className="flex-1 h-2 bg-[var(--input-bg)] rounded-full overflow-hidden">
                            <div className="h-full rounded-full" style={{ width: `${mod.completed}%`, background: CHART_COLORS[i % CHART_COLORS.length] }} />
                          </div>
                          <span className="text-[11px] font-bold text-[var(--text-muted)]">{mod.completed}%</span>
                        </div>
                      </td>
                      <td className="px-5 py-3 text-[13px] font-black" style={{ color: CHART_COLORS[i % CHART_COLORS.length] }}>{mod.completed}</td>
                      <td className="px-5 py-3">
                        <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${
                          mod.completed >= 80 ? 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]' :
                          mod.completed >= 50 ? 'bg-[var(--accent-yellow-bg)] text-[var(--accent-yellow)]' :
                          'bg-[var(--accent-red-bg)] text-[var(--accent-red)]'
                        }`}>
                          {mod.completed >= 80 ? 'Completed' : mod.completed >= 50 ? 'In Progress' : 'Pending'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </motion.div>
        )}

        {/* ════════ ATTENDANCE TAB ════════ */}
        {activeTab === 'attendance' && (
          <motion.div key="attendance" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-6">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <StatCard icon={CalendarCheck} label="Total Present" value={totalPresent} color="green" />
              <StatCard icon={XCircle} label="Total Absent" value={totalAbsent} color="red" />
              <StatCard icon={Award} label="Attendance Rate" value={`${attendanceRate}%`} sub={attendanceRate >= 80 ? 'Excellent' : 'Needs improvement'} color="indigo" />
            </div>

            {/* Monthly Chart */}
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
              <h3 className="text-[14px] font-bold text-[var(--text-main)] mb-1">Monthly Attendance</h3>
              <p className="text-[11px] text-[var(--text-muted)] mb-4">Session-level attendance tracking</p>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={attendanceData} barGap={6}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                  <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                  <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} />
                  <Bar dataKey="present" fill="#22c55e" radius={[4, 4, 0, 0]} name="Present" />
                  <Bar dataKey="absent" fill="#ef4444" radius={[4, 4, 0, 0]} name="Absent" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Attendance Records */}
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-[var(--border)]">
                <h3 className="text-[14px] font-bold text-[var(--text-main)]">Session Records</h3>
              </div>
              {activity.attendance.length > 0 ? (
                <table className="w-full">
                  <thead>
                    <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                      <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Session</th>
                      <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Date</th>
                      <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Type</th>
                      <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border)]">
                    {activity.attendance.map(a => (
                      <tr key={a._id} className="hover:bg-[var(--table-hover)]">
                        <td className="px-5 py-2.5 text-[13px] font-bold text-[var(--text-main)]">{a.session_name || '—'}</td>
                        <td className="px-5 py-2.5 text-[12px] text-[var(--text-muted)]">{a.date ? new Date(a.date).toLocaleDateString() : '—'}</td>
                        <td className="px-5 py-2.5 text-[12px] text-[var(--accent-indigo)] font-medium">{a.type || '—'}</td>
                        <td className="px-5 py-2.5">
                          <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${a.status === 'present' ? 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]' : 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]'}`}>
                            {a.status || '—'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="py-12 text-center">
                  <CalendarCheck size={32} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" />
                  <p className="text-[13px] text-[var(--text-muted)]">No attendance records yet.</p>
                  <p className="text-[11px] text-[var(--text-muted)] opacity-60 mt-1">Data will populate when sessions are scheduled.</p>
                </div>
              )}
            </div>
          </motion.div>
        )}

        {/* ════════ ACTIVITY LOG TAB ════════ */}
        {activeTab === 'history' && (
          <motion.div key="history" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-6">
              <h3 className="text-[14px] font-bold text-[var(--text-main)] mb-1">Activity Timeline</h3>
              <p className="text-[11px] text-[var(--text-muted)] mb-6">Complete history of actions and events</p>
              <div className="space-y-0">
                {mockTimeline.map((act, i) => {
                  const typeColors = {
                    learning: 'indigo', attendance: 'green', assessment: 'orange',
                    batch: 'yellow', profile: 'indigo'
                  };
                  const color = typeColors[act.type] || 'indigo';
                  return (
                    <div key={act._id} className="flex items-start gap-4 group relative">
                      {/* Timeline line */}
                      {i < mockTimeline.length - 1 && (
                        <div className="absolute left-[11px] top-6 w-0.5 h-full bg-[var(--border)]"></div>
                      )}
                      <div className="w-6 h-6 rounded-full flex items-center justify-center shrink-0 z-10 mt-0.5" style={{ background: `var(--accent-${color}-bg)`, border: `2px solid var(--accent-${color})` }}>
                        <div className="w-1.5 h-1.5 rounded-full" style={{ background: `var(--accent-${color})` }}></div>
                      </div>
                      <div className="flex-1 pb-6">
                        <p className="text-[13px] font-medium text-[var(--text-main)]">{act.action || act.description}</p>
                        <div className="flex items-center gap-3 mt-1">
                          <span className="text-[11px] text-[var(--text-muted)]">{act.timestamp ? new Date(act.timestamp).toLocaleString() : '—'}</span>
                          {act.type && (
                            <span className="text-[9px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-md" style={{ background: `var(--accent-${color}-bg)`, color: `var(--accent-${color})` }}>
                              {act.type}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ─── Delete Confirmation ─── */}
      <Modal isOpen={showDeleteConfirm} onClose={() => setShowDeleteConfirm(false)} title="Delete Member">
        <div className="space-y-4 text-center py-4">
          <div className="w-16 h-16 bg-[var(--accent-red-bg)] rounded-xl mx-auto flex items-center justify-center">
            <AlertTriangle size={32} className="text-[var(--accent-red)]" />
          </div>
          <p className="text-[14px] font-bold text-[var(--text-main)]">Delete "{member.full_name || member.email}"?</p>
          <p className="text-[12px] text-[var(--text-muted)]">This will permanently remove this member and all associated data.</p>
          <div className="flex gap-3 justify-center pt-2">
            <button onClick={() => setShowDeleteConfirm(false)} className="px-6 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[13px] font-bold text-[var(--text-muted)]">Cancel</button>
            <button onClick={handleDelete} className="px-6 py-2 bg-[var(--accent-red)] text-white rounded-lg text-[13px] font-bold hover:opacity-90 transition-all">Delete Permanently</button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

export default MemberDashboard;
