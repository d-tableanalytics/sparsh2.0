import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import { 
  Users, Building2, Calendar, Target, 
  TrendingUp, Activity, Plus, Clock, 
  ChevronRight, ArrowUpRight, Zap 
} from 'lucide-react';
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid, 
  Tooltip, ResponsiveContainer, BarChart, Bar,
  PieChart, Pie, Cell, Legend
} from 'recharts';
import { motion } from 'framer-motion';

const Dashboard = () => {
  const { user } = useAuth();
  const [stats, setStats] = useState({
    companies: 0,
    batches: 0,
    activeLearners: 0,
    sessionsThisWeek: 0
  });
  const [upcomingEvents, setUpcomingEvents] = useState([]);
  const [loading, setLoading] = useState(true);

  // Mock data for charts (would be aggregated from actual history in production)
  const areaData = [
    { name: 'Mon', sessions: 4 }, { name: 'Tue', sessions: 7 },
    { name: 'Wed', sessions: 5 }, { name: 'Thu', sessions: 9 },
    { name: 'Fri', sessions: 12 }, { name: 'Sat', sessions: 3 },
    { name: 'Sun', sessions: 2 }
  ];

  const pieData = [
    { name: 'Core', value: 45, color: 'var(--accent-indigo)' },
    { name: 'Support', value: 30, color: 'var(--accent-green)' },
    { name: 'Review', value: 25, color: 'var(--accent-orange)' }
  ];

  const fetchData = async () => {
    try {
      const role = user?.role?.toLowerCase();
      const isAdmin = ['superadmin', 'admin'].includes(role);
      
      const [compRes, batchRes, eventRes] = await Promise.all([
        isAdmin ? api.get('/companies').catch(() => ({ data: [] })) : Promise.resolve({ data: [] }),
        api.get('/batches').catch(() => ({ data: [] })),
        api.get('/calendar/events').catch(() => ({ data: [] }))
      ]);
      
      setStats({
        companies: compRes.data.length,
        batches: batchRes.data.length,
        activeLearners: 128, // Placeholder
        sessionsThisWeek: eventRes.data.filter(e => {
            const date = new Date(e.start);
            const now = new Date();
            const diffTime = Math.abs(now - date);
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
            return diffDays <= 7;
        }).length
      });

      setUpcomingEvents(eventRes.data
        .filter(e => new Date(e.start) >= new Date())
        .sort((a, b) => new Date(a.start) - new Date(b.start))
        .slice(0, 5)
      );

    } catch (err) {
      console.error("Dashboard fetch error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const role = user?.role?.toLowerCase();
  const isAdmin = ['superadmin', 'admin', 'coach'].includes(role);

  const statsTiles = [
    { label: isAdmin ? 'Registered Entities' : 'Active Programs', value: stats.companies || 1, icon: Building2, color: 'var(--accent-indigo)', trend: '+12%', sub: isAdmin ? 'vs last month' : 'curated oversight' },
    { label: isAdmin ? 'Active Batches' : 'My Learning Batches', value: stats.batches, icon: Zap, color: 'var(--accent-orange)', trend: '+5%', sub: isAdmin ? 'across regions' : 'operational active' },
    { label: isAdmin ? 'Strategic Learners' : 'Program Collaborators', value: stats.activeLearners, icon: Users, color: 'var(--accent-green)', trend: '+18%', sub: isAdmin ? 'onboarded' : 'peer network' },
    { label: 'Session Velocity', value: stats.sessionsThisWeek, icon: Activity, color: 'var(--accent-red)', trend: 'High', sub: 'scheduled this week' }
  ];

  return (
    <div className="space-y-8 pb-10">
      {/* Header section */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black text-[var(--text-main)] tracking-tight">Executive Overview</h1>
          <p className="text-[14px] text-[var(--text-muted)] font-bold">Welcome back, {user?.full_name}. Here is your organizational pulse.</p>
        </div>
        <div className="flex items-center gap-3">
            <button className="flex items-center gap-2 px-5 py-2.5 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl text-[13px] font-black hover:border-[var(--accent-indigo)] transition-all">
                <Calendar size={16}/> Schedule
            </button>
            <button className="flex items-center gap-2 px-6 py-2.5 bg-[var(--btn-primary)] text-white rounded-2xl text-[13px] font-black shadow-lg shadow-indigo-500/20 hover:opacity-90 transition-all">
                <Plus size={16}/> New Entry
            </button>
        </div>
      </div>

      {/* KPI Tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        {statsTiles.map((tile, i) => (
          <motion.div 
            initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.1 }}
            key={tile.label} className="bg-[var(--bg-card)] p-6 rounded-3xl border border-[var(--border)] shadow-sm hover:shadow-xl hover:-translate-y-1 transition-all group"
          >
            <div className="flex items-start justify-between mb-4">
              <div className="p-3 rounded-2xl bg-[var(--input-bg)] text-[var(--text-main)] group-hover:bg-[var(--accent-indigo-bg)] group-hover:text-[var(--accent-indigo)] transition-colors">
                <tile.icon size={24} />
              </div>
              <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-[var(--accent-green-bg)] text-[var(--accent-green)] text-[10px] font-black uppercase tracking-widest">
                <ArrowUpRight size={12}/> {tile.trend}
              </div>
            </div>
            <div className="space-y-1">
                <h3 className="text-3xl font-black text-[var(--text-main)]">{tile.value}</h3>
                <p className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wider">{tile.label}</p>
                <p className="text-[10px] text-[var(--text-muted)] opacity-60 font-bold">{tile.sub}</p>
            </div>
          </motion.div>
        ))}
      </div>

      {/* Middle Row: Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-8 shadow-sm flex flex-col h-[400px]">
          <div className="flex items-center justify-between mb-8">
            <div>
              <h3 className="text-xl font-black text-[var(--text-main)]">Operational Pulse</h3>
              <p className="text-[12px] text-[var(--text-muted)] font-bold">Session activity across all branches (7-day trend)</p>
            </div>
            <select className="bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-4 py-2 text-[12px] font-black outline-none focus:border-[var(--accent-indigo)]">
              <option>This Week</option><option>Last Month</option>
            </select>
          </div>
          <div className="flex-1 w-full min-h-0">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={areaData}>
                <defs>
                  <linearGradient id="colorSessions" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--accent-indigo)" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="var(--accent-indigo)" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" opacity={0.5} />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{fill: 'var(--text-muted)', fontSize: 11, fontWeight: 700}} dy={10} />
                <YAxis axisLine={false} tickLine={false} tick={{fill: 'var(--text-muted)', fontSize: 11, fontWeight: 700}} />
                <Tooltip 
                  contentStyle={{ borderRadius: '16px', border: '1px solid var(--border)', background: 'var(--bg-card)', boxShadow: '0 10px 30px rgba(0,0,0,0.1)' }}
                  itemStyle={{ fontSize: '12px', fontWeight: 900, color: 'var(--accent-indigo)' }}
                />
                <Area type="monotone" dataKey="sessions" stroke="var(--accent-indigo)" strokeWidth={4} fillOpacity={1} fill="url(#colorSessions)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-8 shadow-sm flex flex-col h-[400px]">
          <div className="mb-6">
            <h3 className="text-xl font-black text-[var(--text-main)]">Session Mix</h3>
            <p className="text-[12px] text-[var(--text-muted)] font-bold">Distribution by Coaching Type</p>
          </div>
          <div className="flex-1 w-full flex items-center justify-center">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={pieData} innerRadius={70} outerRadius={100} paddingAngle={8} dataKey="value" stroke="none">
                  {pieData.map((entry, index) => <Cell key={`cell-${index}`} fill={entry.color} />)}
                </Pie>
                <Tooltip />
                <Legend layout="vertical" align="right" verticalAlign="middle" iconType="circle" />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Bottom Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-8 shadow-sm">
            <div className="flex items-center justify-between mb-6">
                <h3 className="text-xl font-black text-[var(--text-main)] flex items-center gap-2"><Clock size={22} className="text-[var(--accent-indigo)]"/> Upcoming Shedule</h3>
                <button className="text-[12px] font-black text-[var(--accent-indigo)] uppercase tracking-wider hover:underline">View All</button>
            </div>
            <div className="space-y-4">
                {upcomingEvents.length > 0 ? upcomingEvents.map((ev, i) => (
                    <div key={ev.id} className="flex items-center justify-between p-4 bg-[var(--input-bg)] rounded-2xl hover:bg-[var(--bg-main)] border border-transparent hover:border-[var(--border)] transition-all group">
                         <div className="flex items-center gap-4">
                             <div className="w-12 h-12 flex flex-col items-center justify-center bg-[var(--bg-card)] rounded-xl border border-[var(--border)] group-hover:border-[var(--accent-indigo)] transition-all">
                                 <span className="text-[10px] font-black text-[var(--accent-indigo)] uppercase">{new Date(ev.start).toLocaleString('en-US', { month: 'short' })}</span>
                                 <span className="text-[16px] font-black text-[var(--text-main)]">{new Date(ev.start).getDate()}</span>
                             </div>
                             <div>
                                 <h4 className="text-[14px] font-black text-[var(--text-main)] group-hover:text-[var(--accent-indigo)] transition-all">{ev.title}</h4>
                                 <p className="text-[11px] font-bold text-[var(--text-muted)] flex items-center gap-1"><Clock size={12}/> {new Date(ev.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} • {ev.type}</p>
                             </div>
                         </div>
                         <ChevronRight size={18} className="text-[var(--text-muted)] opacity-0 group-hover:opacity-100 transition-all translate-x-2 group-hover:translate-x-0" />
                    </div>
                )) : (
                    <div className="py-10 text-center space-y-2 opacity-50">
                        <Calendar size={32} className="mx-auto" />
                        <p className="font-bold">No sessions scheduled for today.</p>
                    </div>
                )}
            </div>
        </div>

        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-8 shadow-sm flex flex-col justify-center text-center space-y-6 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-32 h-32 bg-[var(--accent-indigo-bg)] rounded-full -translate-y-1/2 translate-x-1/2 blur-3xl" />
            <div className="absolute bottom-0 left-0 w-32 h-32 bg-[var(--accent-orange-bg)] rounded-full translate-y-1/2 -translate-x-1/2 blur-3xl" />
            
            <TrendingUp size={48} className="mx-auto text-[var(--accent-indigo)] animate-bounce" />
            <div className="space-y-2">
                <h3 className="text-2xl font-black text-[var(--text-main)]">Intelligence Report</h3>
                <p className="text-[13px] text-[var(--text-muted)] font-bold max-w-[300px] mx-auto">AI Analysis: You have 3 learners falling behind this week. High engagement on Tuesday review sessions.</p>
            </div>
            <button className="px-8 py-3 bg-[var(--text-main)] text-white rounded-2xl text-[13px] font-black hover:opacity-90 transition-all shadow-xl shadow-black/10">Download Insights</button>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
