import React, { useState, useEffect } from 'react';
import ormService from '../../services/ormService';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { 
  ResponsiveContainer, 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  BarChart, 
  Bar 
} from 'recharts';
import { TrendingUp, Target, Award, AlertCircle, Plus, X } from 'lucide-react';

const ORMLearnerDashboard = () => {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [selectedKpi, setSelectedKpi] = useState(null);
  const [achievementValue, setAchievementValue] = useState('');
  const { showSuccess, showError } = useNotification();
  const { user } = useAuth();

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    try {
      const results = await ormService.getDashboard();
      setData(results);
    } catch (error) {
      console.error('Error fetching dashboard:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmitAchievement = async () => {
    if (!achievementValue || !selectedKpi) {
      showError('Please enter a value');
      return;
    }

    try {
      await ormService.submitAchievement({
        assignment_id: data[0].assignment_id,
        learner_id: user._id,
        kpi_id: selectedKpi.path,
        period: '2026-04', // Dynamic period should be handled
        actual_value: parseFloat(achievementValue),
        target_value: selectedKpi.target_value
      });
      showSuccess('Achievement submitted!');
      setShowSubmitModal(false);
      setAchievementValue('');
      fetchDashboardData();
    } catch (error) {
      showError('Failed to submit achievement');
    }
  };

  const trendData = [
    { month: 'Jan', score: 65 },
    { month: 'Feb', score: 72 },
    { month: 'Mar', score: 85 },
    { month: 'Apr', score: 78 },
    { month: 'May', score: 92 },
  ];

  if (loading) return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600"></div>
    </div>
  );

  return (
    <div className="p-6 bg-slate-50 min-h-screen">
      <div className="max-w-7xl mx-auto">
        <header className="mb-6">
          <h1 className="text-2xl font-bold text-slate-800">My Performance Scorecard</h1>
          <p className="text-slate-500 text-sm">Track your Outcome Result Management (ORM) progress.</p>
        </header>

        {/* Top Summary Cards */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-white p-5 rounded-2xl shadow-sm border border-slate-100">
            <div className="w-10 h-10 bg-indigo-50 rounded-xl flex items-center justify-center text-indigo-600 mb-3">
              <Award size={20} />
            </div>
            <p className="text-xs font-medium text-slate-500">Current Score</p>
            <h2 className="text-3xl font-black text-slate-800 mt-1">{data[0]?.current_score || 0}%</h2>
            <div className="mt-3 flex items-center text-green-500 text-[10px] font-bold uppercase tracking-wider">
              <TrendingUp size={12} className="mr-1" />
              +5.4% from last month
            </div>
          </div>

          <div className="bg-white p-5 rounded-2xl shadow-sm border border-slate-100">
            <div className="w-10 h-10 bg-emerald-50 rounded-xl flex items-center justify-center text-emerald-600 mb-3">
              <Target size={20} />
            </div>
            <p className="text-xs font-medium text-slate-500">Target Achievement</p>
            <h2 className="text-3xl font-black text-slate-800 mt-1">92%</h2>
            <div className="mt-4 bg-slate-100 h-1.5 rounded-full overflow-hidden">
              <div className="bg-emerald-500 h-full w-[92%]"></div>
            </div>
          </div>

          <div className="bg-white p-5 rounded-2xl shadow-sm border border-slate-100">
            <div className="w-10 h-10 bg-amber-50 rounded-xl flex items-center justify-center text-amber-600 mb-3">
              <AlertCircle size={20} />
            </div>
            <p className="text-xs font-medium text-slate-500">Pending Updates</p>
            <h2 className="text-3xl font-black text-slate-800 mt-1">3</h2>
            <p className="text-[10px] text-slate-400 mt-3 font-medium uppercase tracking-wider">Due by 15th May</p>
          </div>

          <div className="bg-slate-900 p-5 rounded-2xl shadow-lg shadow-slate-200 text-white relative overflow-hidden">
             <div className="relative z-10">
               <h3 className="text-sm font-bold mb-1">Performance Insight</h3>
               <p className="text-slate-400 text-[11px] leading-relaxed">Focus on 'Cost Adherence' to hit 95% total score this month.</p>
               <button className="mt-4 bg-white/10 hover:bg-white/20 text-white px-3 py-1.5 rounded-lg text-[10px] font-bold transition-all border border-white/10">
                  Analyze All →
               </button>
             </div>
             <div className="absolute -right-4 -bottom-4 w-20 h-20 bg-indigo-500/10 rounded-full blur-2xl" />
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Chart Area */}
          <div className="lg:col-span-2 space-y-6">
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
              <div className="flex justify-between items-center mb-6">
                <h3 className="text-lg font-bold text-slate-800">Score Trend</h3>
                <select className="bg-slate-50 border-none text-[11px] font-bold text-slate-500 rounded-lg px-3 py-1.5 focus:ring-0">
                  <option>Last 6 Months</option>
                  <option>Last 12 Months</option>
                </select>
              </div>
              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trendData}>
                    <defs>
                      <linearGradient id="colorScore" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#4f46e5" stopOpacity={0.1}/>
                        <stop offset="95%" stopColor="#4f46e5" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                    <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{fill: '#94a3b8', fontSize: 12, fontWeight: 600}} dy={10} />
                    <YAxis axisLine={false} tickLine={false} tick={{fill: '#94a3b8', fontSize: 12, fontWeight: 600}} dx={-10} domain={[0, 100]} />
                    <Tooltip 
                      contentStyle={{borderRadius: '16px', border: 'none', boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1)'}}
                    />
                    <Area type="monotone" dataKey="score" stroke="#4f46e5" strokeWidth={4} fillOpacity={1} fill="url(#colorScore)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Detailed Parameter Breakdown */}
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
              <h3 className="text-lg font-bold text-slate-800 mb-6">Parameter Breakdown</h3>
              <div className="space-y-5">
                {data[0]?.structure?.map((param, idx) => (
                  <div key={idx} className="group">
                    <div className="flex justify-between items-center mb-1.5">
                      <span className="font-bold text-slate-700 text-sm">{param.name}</span>
                      <span className="text-[10px] font-black text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-full uppercase tracking-wider">{param.weightage}% weight</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="flex-1 bg-slate-100 h-2 rounded-full overflow-hidden">
                        <div 
                          className="bg-indigo-500 h-full transition-all duration-1000 group-hover:bg-indigo-600" 
                          style={{ width: `${Math.random() * 60 + 40}%` }}
                        ></div>
                      </div>
                      <span className="text-[11px] font-black text-slate-500 w-10 text-right">85%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right Sidebar: Recent Achievements & Actions */}
          <div className="space-y-6">
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
              <h3 className="text-sm font-black text-slate-400 uppercase tracking-widest mb-4">Input Values</h3>
              <div className="space-y-3">
                {data[0]?.structure?.map((param, idx) => (
                  <button 
                    key={idx}
                    onClick={() => {
                      setSelectedKpi({ name: param.name, path: param.name, target_value: 0 }); // Simplified path
                      setShowSubmitModal(true);
                    }}
                    className="w-full flex items-center justify-between p-3 bg-slate-50 hover:bg-indigo-50 rounded-xl transition-all group border border-transparent hover:border-indigo-100"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-7 h-7 bg-white rounded-lg flex items-center justify-center text-slate-400 group-hover:text-indigo-600 shadow-sm border border-slate-100">
                        <Plus size={14} />
                      </div>
                      <span className="text-[13px] font-bold text-slate-600 group-hover:text-indigo-700">{param.name}</span>
                    </div>
                    <svg className="w-3 h-3 text-slate-300 group-hover:text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7"></path></svg>
                  </button>
                ))}
              </div>
            </div>

            <div className="bg-slate-900 p-6 rounded-2xl shadow-xl text-white">
              <h3 className="text-sm font-bold mb-4 opacity-60">Upcoming Reviews</h3>
              <div className="space-y-4">
                <div className="flex gap-3">
                  <div className="flex-shrink-0 w-10 h-10 bg-white/10 rounded-xl flex flex-col items-center justify-center font-bold">
                    <span className="text-[10px]">MAY</span>
                    <span className="text-sm leading-tight">20</span>
                  </div>
                  <div>
                    <h4 className="font-bold text-sm">Monthly Strategy</h4>
                    <p className="text-[10px] text-white/50">10:30 AM • Coach Vikram</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Submission Modal */}
      {showSubmitModal && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-[2px] flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden animate-in fade-in zoom-in duration-200 border border-slate-200">
            <div className="p-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
              <h3 className="text-base font-bold text-slate-800 uppercase tracking-tight">Update Entry</h3>
              <button onClick={() => setShowSubmitModal(false)} className="text-slate-400 hover:text-slate-600 transition-colors">
                <X size={20} />
              </button>
            </div>
            <div className="p-6">
              <div className="mb-4">
                <p className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1">Parameter</p>
                <h4 className="text-sm font-bold text-slate-800">{selectedKpi?.name}</h4>
              </div>
              
              <div className="mb-6">
                <label className="block text-[11px] font-black text-slate-600 uppercase tracking-widest mb-2">Actual Value Achieved</label>
                <div className="relative">
                  <input 
                    type="number" 
                    value={achievementValue}
                    onChange={(e) => setAchievementValue(e.target.value)}
                    className="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 text-xl font-black text-indigo-600 focus:border-indigo-500 focus:ring-0 transition-all outline-none"
                    placeholder="0.00"
                    autoFocus
                  />
                  <div className="absolute right-4 top-1/2 -translate-y-1/2 text-[10px] font-black text-slate-400">
                    UNIT
                  </div>
                </div>
              </div>

              <button 
                onClick={handleSubmitAchievement}
                className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-3 rounded-xl font-bold shadow-lg shadow-indigo-100 transition-all flex items-center justify-center gap-2 text-sm"
              >
                Save Achievement
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ORMLearnerDashboard;
