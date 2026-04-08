import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { useNotification } from '../context/NotificationContext';
import { motion, AnimatePresence } from 'framer-motion';
import { 
    Sparkles, Plus, Search, Bot, 
    MessageCircle, ArrowRight, Settings2, Trash2,
    LayoutGrid, List, MessageSquare, ExternalLink, ShieldCheck
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const GptProjects = () => {
    const [projects, setProjects] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [viewMode, setViewMode] = useState('grid'); // 'grid' or 'table'
    const { user } = useAuth();
    const { showSuccess, showError } = useNotification();
    const navigate = useNavigate();

    const fetchProjects = async () => {
        try {
            const res = await api.get('/gpt/projects');
            setProjects(res.data);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchProjects();
    }, []);

    const filteredProjects = projects.filter(p => 
        p.title.toLowerCase().includes(search.toLowerCase()) ||
        p.description?.toLowerCase().includes(search.toLowerCase())
    );

    const handleDelete = async (id, e) => {
        e.stopPropagation();
        try {
            await api.delete(`/gpt/projects/${id}`);
            showSuccess("Intelligence Engine deleted");
            fetchProjects();
        } catch (err) {
            showError("Delete failed");
        }
    };

    return (
        <div className="max-w-7xl mx-auto space-y-6 px-4 sm:px-6 lg:px-8 pb-10">
            {/* Header Area */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                    <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight flex items-center gap-2 uppercase italic">
                        <Sparkles className="text-[var(--accent-indigo)]" size={20} /> Neural Engine Hub
                    </h1>
                    <p className="text-[10px] text-[var(--text-muted)] mt-0.5 font-bold uppercase tracking-widest opacity-60">Custom project-based intelligences tuned for your operations.</p>
                </div>
                
                <div className="flex items-center gap-2">
                    {['superadmin', 'admin'].includes(user?.role) && (
                        <>
                            <button 
                                onClick={() => navigate('/gpt/permissions')}
                                className="h-10 px-5 bg-white border border-[var(--border)] text-[var(--text-muted)] rounded-xl flex items-center gap-2 font-black uppercase text-[10px] tracking-widest hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)] transition-all"
                            >
                                <ShieldCheck size={14} /> Access Control
                            </button>
                            <button 
                                onClick={() => navigate('/gpt/new')}
                                className="h-10 px-5 bg-[var(--accent-indigo)] text-white rounded-xl flex items-center gap-2 font-black uppercase text-[10px] tracking-widest hover:opacity-90 active:scale-95 transition-all shadow-lg shadow-indigo-100"
                            >
                                <Plus size={14} /> New GPT
                            </button>
                        </>
                    )}
                </div>
            </div>

            {/* View Controls & Filter */}
            <div className="flex flex-col sm:flex-row gap-4 items-center justify-between bg-[var(--bg-card)] border border-[var(--border)] p-2 rounded-2xl shadow-sm">
                <div className="relative flex-1 w-full max-w-md">
                    <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] opacity-50" size={16} />
                    <input 
                        type="text"
                        placeholder="Search engine knowledge bases..."
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        className="w-full h-10 pl-10 pr-4 bg-[var(--input-bg)] border border-transparent rounded-xl focus:border-[var(--accent-indigo)] outline-none transition-all font-bold text-[12px] placeholder:text-[var(--text-muted)]/50"
                    />
                </div>

                <div className="flex items-center p-1 bg-[var(--input-bg)] rounded-xl border border-[var(--border)]">
                    <button 
                        onClick={() => setViewMode('grid')}
                        className={`p-2 rounded-lg transition-all ${viewMode === 'grid' ? 'bg-white text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}
                    >
                        <LayoutGrid size={18} />
                    </button>
                    <button 
                        onClick={() => setViewMode('table')}
                        className={`p-2 rounded-lg transition-all ${viewMode === 'table' ? 'bg-white text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}
                    >
                        <List size={18} />
                    </button>
                </div>
            </div>

            {/* List/Grid Render */}
            {loading ? (
                <div className="flex justify-center py-20">
                    <div className="w-8 h-8 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
                </div>
            ) : filteredProjects.length > 0 ? (
                viewMode === 'grid' ? (
                    /* COMPACT GRID VIEW */
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                        {filteredProjects.map((project) => (
                            <motion.div 
                                key={project.id}
                                whileHover={project.locked ? {} : { y: -4 }}
                                onClick={() => !project.locked && navigate(`/gpt/chat/${project.id}`)}
                                className={`bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4 space-y-3 transition-all group relative overflow-hidden ${project.locked ? 'opacity-70 cursor-not-allowed grayscale-[0.5]' : 'cursor-pointer hover:shadow-xl'}`}
                            >
                                <div className={`absolute top-0 right-0 w-24 h-24 ${project.locked ? 'bg-gray-400' : 'bg-[var(--accent-indigo)]'} opacity-[0.02] rounded-full -mr-12 -mt-12 group-hover:scale-150 transition-transform duration-700`}></div>
                                
                                <div className="flex items-start justify-between relative z-10">
                                    <div className={`w-10 h-10 rounded-xl flex items-center justify-center shadow-inner transition-transform ${project.locked ? 'bg-gray-100 text-gray-400' : 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] group-hover:scale-110'}`}>
                                        {project.locked ? <Bot size={20} className="opacity-50" /> : <Bot size={20} />}
                                    </div>
                                    <div className="flex items-center gap-1">
                                        {project.locked && (
                                            <div className="p-1.5 bg-amber-50 text-amber-500 rounded-lg" title={project.lock_reason || "Locked until requirement met"}>
                                                <Settings2 size={16} />
                                            </div>
                                        )}
                                        {['superadmin', 'admin'].includes(user?.role) && (
                                            <div className="flex gap-0.5">
                                                <button 
                                                    onClick={(e) => { e.stopPropagation(); navigate(`/gpt/edit/${project.id}`); }}
                                                    className="p-1.5 hover:bg-[var(--input-bg)] rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all"
                                                    title="Edit GPT"
                                                >
                                                    <Settings2 size={16} />
                                                </button>
                                                <button 
                                                    onClick={(e) => handleDelete(project.id, e)}
                                                    className="p-1.5 hover:bg-red-50 rounded-lg text-[var(--text-muted)] hover:text-red-500 transition-all opacity-0 group-hover:opacity-100"
                                                    title="Delete GPT"
                                                >
                                                    <Trash2 size={16} />
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                </div>

                                <div className="space-y-1 relative z-10 pr-2">
                                    <h3 className={`text-sm font-black tracking-tight transition-colors uppercase italic ${project.locked ? 'text-gray-500' : 'text-[var(--text-main)] group-hover:text-[var(--accent-indigo)]'}`}>
                                        {project.title}
                                    </h3>
                                    <div className="relative min-h-[32px]">
                                        <p className="text-[11px] text-[var(--text-muted)] leading-relaxed font-bold line-clamp-2 group-hover:line-clamp-none transition-all duration-300">
                                            {project.locked ? (
                                                <span className="flex items-center gap-1.5 text-amber-600/80 italic">
                                                    🔒 {project.lock_reason || "Access Restricted"}
                                                </span>
                                            ) : (
                                                project.description || 'Custom intelligence tuned for project-specific goals and strategies.'
                                            )}
                                        </p>
                                    </div>
                                </div>

                                <div className="pt-3 border-t border-[var(--border)] flex items-center justify-between relative z-10">
                                    <div className="flex items-center gap-2">
                                        <div className={`w-2 h-2 rounded-full ${project.locked ? 'bg-gray-300' : 'bg-[var(--accent-green)] animate-pulse shadow-[0_0_8px_var(--accent-green)]'}`}></div>
                                        <span className="text-[8px] font-black uppercase tracking-[0.2em] text-[var(--text-muted)]">
                                            {project.locked ? 'Offline' : 'Active Node'}
                                        </span>
                                    </div>
                                    <button 
                                        disabled={project.locked}
                                        className={`flex items-center gap-1.5 font-black text-[9px] uppercase tracking-widest transition-transform ${project.locked ? 'text-gray-400' : 'text-[var(--accent-indigo)] hover:translate-x-1'}`}
                                    >
                                        {project.locked ? 'Locked' : 'Engage'} <ArrowRight size={12} />
                                    </button>
                                </div>
                            </motion.div>
                        ))}
                    </div>
                ) : (
                    /* MODERN TABLE VIEW */
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-sm overflow-hidden overflow-x-auto no-scrollbar">
                        <table className="w-full text-left border-collapse min-w-[700px]">
                            <thead>
                                <tr className="bg-[var(--input-bg)] border-b border-[var(--border)]">
                                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Engine Name</th>
                                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Scope & Knowledge</th>
                                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Status</th>
                                    <th className="px-6 py-4 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] text-right">Operations</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredProjects.map((project) => (
                                    <tr 
                                        key={project.id} 
                                        onClick={() => !project.locked && navigate(`/gpt/chat/${project.id}`)}
                                        className={`border-b border-[var(--border)] last:border-0 transition-all group ${project.locked ? 'bg-gray-50/50 cursor-not-allowed text-gray-400' : 'hover:bg-[var(--accent-indigo-bg)]/20 cursor-pointer'}`}
                                    >
                                        <td className="px-6 py-4">
                                            <div className="flex items-center gap-3">
                                                <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${project.locked ? 'bg-gray-200 text-gray-400' : 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'}`}>
                                                    <Bot size={16} />
                                                </div>
                                                <span className={`text-[13px] font-black italic uppercase ${project.locked ? 'text-gray-400' : 'text-[var(--text-main)]'}`}>{project.title}</span>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4">
                                            <p className={`text-[11px] font-bold max-w-[300px] truncate group-hover:whitespace-normal transition-all ${project.locked ? 'text-gray-400 italic' : 'text-[var(--text-muted)]'}`}>
                                                {project.locked ? `Locked: ${project.lock_reason || "Requirement Pending"}` : project.description || 'No specialized description provided.'}
                                            </p>
                                        </td>
                                        <td className="px-6 py-4">
                                            {project.locked ? (
                                                <div className="flex items-center gap-2 px-2 py-1 bg-amber-50 text-amber-600 border border-amber-100 rounded-lg w-fit">
                                                    <div className="w-1.5 h-1.5 rounded-full bg-amber-500"></div>
                                                    <span className="text-[9px] font-black uppercase tracking-widest">Restricted</span>
                                                </div>
                                            ) : (
                                                <div className="flex items-center gap-2 px-2 py-1 bg-emerald-50 text-emerald-600 border border-emerald-100 rounded-lg w-fit">
                                                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-500"></div>
                                                    <span className="text-[9px] font-black uppercase tracking-widest">Optimized</span>
                                                </div>
                                            )}
                                        </td>
                                        <td className="px-6 py-4 text-right">
                                            <div className="flex items-center justify-end gap-2">
                                                <button 
                                                    disabled={project.locked}
                                                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-black text-[9px] uppercase tracking-widest transition-all ${project.locked ? 'bg-gray-100 text-gray-400' : 'bg-[var(--accent-indigo)] text-white hover:opacity-90 active:scale-95'}`}
                                                >
                                                    {project.locked ? 'Locked' : 'Chat'} <MessageSquare size={12} />
                                                </button>
                                                {['superadmin', 'admin'].includes(user?.role) && (
                                                    <div className="flex items-center gap-1">
                                                         <button 
                                                            onClick={(e) => { e.stopPropagation(); navigate(`/gpt/edit/${project.id}`); }}
                                                            className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-white rounded-lg transition-all"
                                                        >
                                                            <Settings2 size={16} />
                                                        </button>
                                                        <button 
                                                            onClick={(e) => handleDelete(project.id, e)}
                                                            className="p-1.5 text-[var(--text-muted)] hover:text-red-500 hover:bg-white rounded-lg transition-all"
                                                        >
                                                            <Trash2 size={16} />
                                                        </button>
                                                    </div>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )
            ) : (
                <div className="text-center py-20 bg-[var(--bg-card)] border border-dashed border-[var(--border)] rounded-[40px] space-y-4">
                    <div className="w-20 h-20 rounded-full bg-[var(--input-bg)] flex items-center justify-center mx-auto text-[var(--text-muted)]">
                        <MessageSquare size={40} />
                    </div>
                    <h3 className="text-xl font-black text-[var(--text-main)] italic uppercase">Neural Network Silent</h3>
                    <p className="text-[var(--text-muted)] font-bold max-w-sm mx-auto uppercase text-[10px] tracking-widest opacity-60">Initialize your first AI GPT engine to begin project analysis.</p>
                </div>
            )}
        </div>
    );
};

export default GptProjects;
