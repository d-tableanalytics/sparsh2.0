import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';
import { useNotification } from '../context/NotificationContext';
import { 
    Layers, ChevronRight, CheckCircle2, Calendar, 
    Target, Bot, UploadCloud, Plus, FileText, 
    Download, ExternalLink, BookOpen, Zap, AlertTriangle, Circle, CheckCircle, Info
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const CompanyPortal = () => {
    const navigate = useNavigate();
    const { user } = useAuth();
    const { showSuccess, showError } = useNotification();
    const companyId = user?.company_id;

    const [trainingPath, setTrainingPath] = useState([]);
    const [fetchingPath, setFetchingPath] = useState(true);
    const [selectedSessionId, setSelectedSessionId] = useState(null);
    const [sessionTasks, setSessionTasks] = useState([]);
    const [fetchingTasks, setFetchingTasks] = useState(false);
    const [expandedBatches, setExpandedBatches] = useState({});
    const [expandedQuarters, setExpandedQuarters] = useState({});

    const [uploading, setUploading] = useState(false);

    useEffect(() => {
        if (companyId) {
            fetchPath();
        }
    }, [companyId]);

    const fetchPath = async () => {
        setFetchingPath(true);
        try {
            const res = await api.get(`/companies/${companyId}/training-path`);
            setTrainingPath(res.data);
            
            // Auto expand first batch/quarter if available
            if (res.data.length > 0) {
                const firstBatch = res.data[0];
                setExpandedBatches({ [firstBatch.id]: true });
                if (firstBatch.quarters?.length > 0) {
                    setExpandedQuarters({ [firstBatch.quarters[0].id]: true });
                }
            }
        } catch (err) {
            showError("Failed to fetch training roadmap");
        } finally {
            setFetchingPath(false);
        }
    };

    const fetchSessionTasks = async (sessionId) => {
        setSelectedSessionId(sessionId);
        setFetchingTasks(true);
        try {
            const res = await api.get(`/companies/${companyId}/sessions/${sessionId}/tasks`);
            setSessionTasks(res.data);
        } catch (err) {
            showError("Failed to fetch session tasks");
        } finally {
            setFetchingTasks(false);
        }
    };

    const handleToggleTask = async (taskIdx) => {
        try {
            await api.patch(`/companies/${companyId}/sessions/${selectedSessionId}/tasks/${taskIdx}/toggle`);
            setSessionTasks(prev => prev.map(t => t.index === taskIdx ? { ...t, is_done: !t.is_done } : t));
            showSuccess("Neural milestone updated!");
        } catch (err) {
            showError("Failed to sync progress");
        }
    };

    const handleLearnerUpload = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        setUploading(true);
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            await api.post(`/calendar/events/${selectedSessionId}/learner-upload`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            showSuccess(`"${file.name}" synchronized with cloud!`);
            fetchPath(); // Refresh path to get new contents
        } catch (err) {
            showError("Cloud synchronization failed");
        } finally {
            setUploading(false);
        }
    };

    const getSession = (sid) => {
        return trainingPath.flatMap(b => b.quarters).flatMap(q => q.sessions).find(s => s.id === sid);
    };

    if (!companyId) return (
        <div className="flex flex-col items-center justify-center py-32 opacity-50 space-y-4">
            <AlertTriangle size={48} />
            <p className="font-black uppercase tracking-widest text-[12px]">No Company Link Detected</p>
        </div>
    );

    return (
        <div className="max-w-7xl mx-auto space-y-8 animate-in fade-in duration-700 pb-20 px-4">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-black text-[var(--text-main)] italic uppercase tracking-tighter leading-none">
                        Corporate <span className="text-[var(--accent-indigo)]">Training Roadmap</span>
                    </h1>
                    <p className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-[0.2em] mt-2">
                        Strategic Batch & Session Tracking for {user?.company_name || 'Your Organization'}
                    </p>
                </div>
                <div className="hidden md:flex items-center gap-3">
                    <div className="px-5 py-2.5 bg-indigo-50 border border-indigo-100 rounded-2xl flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-indigo-500 text-white flex items-center justify-center font-black text-[10px]">
                            {trainingPath.length}
                        </div>
                        <span className="text-[10px] font-black uppercase text-indigo-700 tracking-widest">Active Batches</span>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
                {/* Left Column: Hierarchical List */}
                <div className="lg:col-span-4 space-y-4">
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] overflow-hidden shadow-sm">
                        <div className="p-6 border-b border-[var(--border)] bg-indigo-50/10">
                            <h3 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-[0.15em] flex items-center gap-2">
                                <Layers size={16} className="text-[var(--accent-indigo)]" /> Assigned Neural Paths
                            </h3>
                        </div>
                        
                        <div className="p-3 space-y-2 max-h-[70vh] overflow-y-auto no-scrollbar">
                            {fetchingPath ? (
                                <div className="py-20 flex flex-col items-center gap-2 opacity-40">
                                    <div className="w-6 h-6 border-2 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
                                    <span className="text-[10px] font-black uppercase tracking-widest">Compiling Path...</span>
                                </div>
                            ) : trainingPath.length > 0 ? trainingPath.map(batch => (
                                <div key={batch.id} className="space-y-2">
                                    {/* Batch Level */}
                                    <button 
                                        onClick={() => setExpandedBatches(prev => ({ ...prev, [batch.id]: !prev[batch.id] }))}
                                        className={`w-full flex items-center gap-4 p-4 rounded-2xl transition-all ${expandedBatches[batch.id] ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'hover:bg-[var(--input-bg)] text-[var(--text-muted)]'}`}
                                    >
                                        <Layers size={18} />
                                        <span className="text-[13px] font-black uppercase tracking-tight flex-1 text-left truncate">{batch.name}</span>
                                        <ChevronRight size={16} className={`transition-transform duration-300 ${expandedBatches[batch.id] ? 'rotate-90' : ''}`} />
                                    </button>

                                    {/* Quarters Level */}
                                    <AnimatePresence>
                                        {expandedBatches[batch.id] && (
                                            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="pl-6 overflow-hidden space-y-1 pr-1">
                                                {batch.quarters?.map(quarter => (
                                                    <div key={quarter.id} className="space-y-1">
                                                        <button 
                                                            onClick={() => setExpandedQuarters(prev => ({ ...prev, [quarter.id]: !prev[quarter.id] }))}
                                                            className={`w-full flex items-center gap-3 p-3 rounded-xl transition-all ${expandedQuarters[quarter.id] ? 'text-[var(--accent-orange)]' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}
                                                        >
                                                            <div className="w-1.5 h-1.5 rounded-full bg-[var(--border)]"></div>
                                                            <span className="text-[12px] font-bold uppercase flex-1 text-left truncate">{quarter.name}</span>
                                                            <ChevronRight size={14} className={`transition-transform duration-300 ${expandedQuarters[quarter.id] ? 'rotate-90' : ''}`} />
                                                        </button>

                                                        {/* Sessions Level */}
                                                        <AnimatePresence>
                                                            {expandedQuarters[quarter.id] && (
                                                                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="pl-6 overflow-hidden space-y-1 mb-2">
                                                                    {quarter.sessions?.map(session => (
                                                                        <button 
                                                                            key={session.id}
                                                                            onClick={() => fetchSessionTasks(session.id)}
                                                                            className={`w-full flex items-center gap-3 p-3 rounded-xl transition-all text-left ${selectedSessionId === session.id ? 'bg-white shadow-md border border-[var(--border)] text-[var(--accent-green)] scale-[1.02]' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}`}
                                                                        >
                                                                            <div className={`w-2 h-2 rounded-full ${selectedSessionId === session.id ? 'bg-[var(--accent-green)] animate-pulse' : 'bg-[var(--border)]'}`}></div>
                                                                            <div className="flex-1 min-w-0">
                                                                                <p className="text-[12px] font-black uppercase tracking-tight truncate leading-tight">{session.title}</p>
                                                                                <p className="text-[10px] font-bold opacity-60">
                                                                                    {new Date(session.start).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
                                                                                </p>
                                                                            </div>
                                                                            {session.status === 'completed' && <CheckCircle2 size={14} className="text-[var(--accent-green)]" />}
                                                                        </button>
                                                                    ))}
                                                                </motion.div>
                                                            )}
                                                        </AnimatePresence>
                                                    </div>
                                                ))}
                                            </motion.div>
                                        )}
                                    </AnimatePresence>
                                </div>
                            )) : (
                                <div className="py-20 text-center opacity-30 italic">
                                    <Layers size={40} className="mx-auto mb-4" />
                                    <p className="text-[12px] font-black uppercase tracking-widest">No assigned training paths detected</p>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="bg-indigo-50 border border-indigo-100 rounded-[32px] p-6 flex gap-4">
                        <Zap size={20} className="text-indigo-500 shrink-0 mt-1" />
                        <div>
                            <h4 className="text-[12px] font-black text-indigo-900 uppercase tracking-tight">AI Engine Unlocking</h4>
                            <p className="text-[11px] text-indigo-700 font-bold leading-relaxed mt-1">
                                Complete sessions to unlock associated Neural Knowledge Engines. Access overrides can be granted by coaches for high-priority training modules.
                            </p>
                        </div>
                    </div>
                </div>

                {/* Right Column: Session Details & Actions */}
                <div className="lg:col-span-8">
                    <AnimatePresence mode="wait">
                        {fetchingTasks ? (
                            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[40px] p-40 flex flex-col items-center justify-center gap-4 text-center">
                                <div className="w-12 h-12 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
                                <p className="text-[12px] font-black text-[var(--accent-indigo)] uppercase tracking-widest animate-pulse">Synchronizing Neural data...</p>
                            </motion.div>
                        ) : selectedSessionId ? (
                            <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="space-y-6">
                                {/* Session Header Card */}
                                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[40px] p-10 shadow-sm relative overflow-hidden group">
                                    <div className="absolute top-0 right-0 w-64 h-64 bg-[var(--accent-indigo)] opacity-[0.03] rounded-full -mr-32 -mt-32 group-hover:scale-150 transition-transform duration-[2000ms]"></div>
                                    <div className="relative z-10">
                                        <div className="flex items-center gap-3 mb-6">
                                            <div className="px-4 py-1.5 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] rounded-xl text-[11px] font-black uppercase tracking-widest border border-[var(--accent-indigo-border)]">Strategic Node</div>
                                            <div className={`px-4 py-1.5 rounded-xl text-[11px] font-black uppercase tracking-widest border ${getSession(selectedSessionId)?.status === 'completed' ? 'bg-emerald-50 text-emerald-600 border-emerald-100' : 'bg-amber-50 text-amber-600 border-amber-100'}`}>
                                                {getSession(selectedSessionId)?.status}
                                            </div>
                                        </div>
                                        <div className="flex justify-between items-end gap-6">
                                            <div>
                                                <h2 className="text-4xl font-black text-[var(--text-main)] italic uppercase tracking-tighter leading-none mb-4">
                                                    {getSession(selectedSessionId)?.title}
                                                </h2>
                                                <div className="flex items-center gap-8 text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                                                    <span className="flex items-center gap-3"><Calendar size={16} className="text-indigo-400" /> {new Date(getSession(selectedSessionId)?.start).toLocaleDateString('en-IN', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' })}</span>
                                                    <span className="flex items-center gap-3"><Target size={16} className="text-orange-400" /> Quarter Intelligence Milestone</span>
                                                </div>
                                            </div>
                                            {getSession(selectedSessionId)?.meeting_link && (
                                                <a href={getSession(selectedSessionId)?.meeting_link} target="_blank" rel="noreferrer" className="h-14 px-8 bg-black text-white rounded-[20px] flex items-center gap-3 text-[14px] font-black uppercase tracking-widest hover:scale-105 active:scale-95 transition-all shadow-xl">
                                                    Join Neural Link
                                                </a>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                                    {/* Task Progress Section */}
                                    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[40px] overflow-hidden flex flex-col shadow-sm">
                                        <div className="p-8 border-b border-[var(--border)] flex items-center justify-between bg-emerald-50/10">
                                            <h4 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-widest flex items-center gap-3">
                                                <CheckCircle2 size={18} className="text-[var(--accent-green)]" /> Operational Tasks
                                            </h4>
                                            <div className="text-[11px] font-black text-[var(--accent-green)] bg-[var(--accent-green-bg)] px-3 py-1 rounded-[12px] border border-[var(--accent-green-border)]">
                                                {sessionTasks.filter(t => t.is_done).length}/{sessionTasks.length} DONE
                                            </div>
                                        </div>
                                        <div className="p-5 flex-1 space-y-2 overflow-y-auto no-scrollbar max-h-[400px]">
                                            {sessionTasks.length > 0 ? sessionTasks.map(task => (
                                                <div 
                                                    key={task.index}
                                                    onClick={() => handleToggleTask(task.index)}
                                                    className={`flex items-start gap-4 p-5 rounded-[24px] border transition-all cursor-pointer group ${task.is_done ? 'bg-[var(--accent-green-bg)] border-[var(--accent-green-border)]' : 'bg-[var(--input-bg)] border-transparent hover:border-[var(--accent-indigo)]'}`}
                                                >
                                                    <div className={`mt-0.5 w-6 h-6 rounded-[10px] flex items-center justify-center transition-all ${task.is_done ? 'bg-[var(--accent-green)] text-white' : 'bg-white border-2 border-[var(--border)] group-hover:border-[var(--accent-indigo)]'}`}>
                                                        {task.is_done ? <CheckCircle size={16} /> : <Circle size={16} className="opacity-0 group-hover:opacity-20" />}
                                                    </div>
                                                    <div className="flex-1 min-w-0">
                                                        <p className={`text-[13px] font-black uppercase tracking-tight transition-all ${task.is_done ? 'text-[var(--accent-green)] line-through' : 'text-[var(--text-main)]'}`}>
                                                            {task.label || task.title || 'Neural Milestone'}
                                                        </p>
                                                        {task.description && (
                                                            <p className={`text-[10px] font-bold mt-1.5 leading-relaxed ${task.is_done ? 'opacity-40' : 'text-[var(--text-muted)]'}`}>
                                                                {task.description}
                                                            </p>
                                                        )}
                                                    </div>
                                                </div>
                                            )) : (
                                                <div className="py-20 flex flex-col items-center justify-center opacity-30 italic">
                                                    <Bot size={40} className="mb-3" />
                                                    <p className="text-[11px] font-black uppercase tracking-widest text-center">Standard session • No custom tasks</p>
                                                </div>
                                            )}
                                        </div>
                                    </div>

                                    {/* Content Upload Section */}
                                    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[40px] overflow-hidden flex flex-col shadow-sm">
                                        <div className="p-8 border-b border-[var(--border)] flex items-center justify-between bg-indigo-50/10">
                                            <h4 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-widest flex items-center gap-3">
                                                <UploadCloud size={18} className="text-[var(--accent-indigo)]" /> Shared Submissions
                                            </h4>
                                            <label className={`h-10 px-6 rounded-[14px] flex items-center gap-2.5 text-[11px] font-black uppercase tracking-widest cursor-pointer transition-all ${uploading ? 'bg-gray-100 text-gray-400' : 'bg-black text-white hover:opacity-95'}`}>
                                                {uploading ? 'Uploading...' : <><Plus size={16} /> Submit Work</>}
                                                <input type="file" className="hidden" disabled={uploading} onChange={handleLearnerUpload} />
                                            </label>
                                        </div>
                                        
                                        <div className="p-5 flex-1 space-y-2 overflow-y-auto no-scrollbar max-h-[400px]">
                                            {(getSession(selectedSessionId)?.learner_contents || []).length > 0 ? (
                                                getSession(selectedSessionId)?.learner_contents.map(content => (
                                                    <a 
                                                        href={content.url} 
                                                        target="_blank" 
                                                        rel="noopener noreferrer"
                                                        key={content.id}
                                                        className="flex items-center gap-4 p-5 bg-white border border-[var(--border)] rounded-[24px] hover:border-[var(--accent-indigo)] hover:shadow-lg transition-all group"
                                                    >
                                                        <div className="w-12 h-12 rounded-[18px] bg-[var(--input-bg)] border border-[var(--border)] flex items-center justify-center text-[var(--accent-indigo)] group-hover:scale-110 transition-transform">
                                                            <FileText size={24} />
                                                        </div>
                                                        <div className="flex-1 min-w-0">
                                                            <p className="text-[13px] font-black text-[var(--text-main)] uppercase truncate tracking-tight">{content.name}</p>
                                                            <p className="text-[10px] text-[var(--text-muted)] font-black mt-1">
                                                                BY {content.uploader_name} • {new Date(content.uploaded_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
                                                            </p>
                                                        </div>
                                                        <Download size={16} className="text-[var(--text-muted)] group-hover:text-[var(--accent-indigo)]" />
                                                    </a>
                                                ))
                                            ) : (
                                                <div className="py-20 flex flex-col items-center justify-center opacity-30 italic">
                                                    <UploadCloud size={40} className="mb-3" />
                                                    <p className="text-[11px] font-black uppercase tracking-widest">No submissions captured yet</p>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                {/* Shared Resources List */}
                                {(getSession(selectedSessionId)?.resources?.length > 0 || getSession(selectedSessionId)?.contents?.length > 0) && (
                                    <div className="bg-indigo-50 border border-indigo-100 rounded-[40px] p-10">
                                        <h5 className="text-[12px] font-black text-indigo-900 uppercase tracking-[0.2em] mb-6 flex items-center gap-3">
                                            <BookOpen size={18} className="text-indigo-500" /> Training Resources & Materials
                                        </h5>
                                        <div className="flex flex-wrap gap-3">
                                            {[...(getSession(selectedSessionId)?.resources || []), ...(getSession(selectedSessionId)?.contents || [])].map((r, i) => (
                                                <a key={i} href={r.url} target="_blank" rel="noopener noreferrer" className="px-6 py-3 bg-white border border-indigo-100 rounded-[18px] text-[12px] font-black text-indigo-700 uppercase tracking-tight hover:border-indigo-400 hover:shadow-md transition-all flex items-center gap-3">
                                                    <ExternalLink size={14} /> {r.name}
                                                </a>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </motion.div>
                        ) : (
                            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[40px] p-40 text-center flex flex-col items-center">
                                <div className="w-24 h-24 bg-[var(--input-bg)] border border-[var(--border)] rounded-[32px] flex items-center justify-center mb-8 text-[var(--text-muted)] opacity-20">
                                    <Zap size={48} />
                                </div>
                                <h3 className="text-2xl font-black text-[var(--text-main)] uppercase italic tracking-tighter mb-3">Initialize <span className="text-[var(--accent-indigo)]">Neural Node</span></h3>
                                <p className="text-[12px] text-[var(--text-muted)] font-black uppercase tracking-widest max-w-sm mx-auto opacity-50 leading-relaxed">
                                    Select a session from your Assigned Training Path to synchronize tasks, download intelligence resources, and manage corporate training submissions.
                                </p>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>
            </div>
        </div>
    );
};

export default CompanyPortal;
