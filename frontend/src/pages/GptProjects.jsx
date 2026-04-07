import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { motion } from 'framer-motion';
import { 
    Sparkles, Plus, Search, Bot, 
    MessageCircle, ArrowRight, Settings2, Trash2 
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const GptProjects = () => {
    const [projects, setProjects] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const { user } = useAuth();
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
        if (!window.confirm("Are you sure you want to delete this assistant?")) return;
        try {
            await api.delete(`/gpt/projects/${id}`);
            fetchProjects();
        } catch (err) {
            alert("Delete failed");
        }
    };

    return (
        <div className="max-w-7xl mx-auto space-y-8 px-4 sm:px-6 lg:px-8">
            {/* Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                    <h1 className="text-2xl font-black text-[var(--text-main)] tracking-tight flex items-center gap-2">
                        <Sparkles className="text-[var(--accent-indigo)]" size={24} /> AI GPT Assistants
                    </h1>
                    <p className="text-[12px] text-[var(--text-muted)] mt-0.5 font-medium italic">Custom project-based intelligences tuned for your business.</p>
                </div>
                
                {user?.role === 'superadmin' && (
                    <button 
                        onClick={() => navigate('/gpt/new')}
                        className="h-12 px-6 bg-[var(--accent-indigo)] text-white rounded-2xl flex items-center gap-2 font-black uppercase text-[12px] tracking-widest hover:opacity-90 active:scale-95 transition-all shadow-lg shadow-indigo-200"
                    >
                        <Plus size={18} /> Create GPT Project
                    </button>
                )}
            </div>

            {/* Search */}
            <div className="relative group">
                <Search className="absolute left-5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] group-focus-within:text-[var(--accent-indigo)] transition-colors" size={20} />
                <input 
                    type="text"
                    placeholder="Search for an assistant (e.g. Sales, Marketing, HR...)"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    className="w-full h-12 pl-14 pr-6 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-sm focus:border-[var(--accent-indigo)] outline-none transition-all font-medium text-[var(--text-main)] placeholder:text-[var(--text-muted)]"
                />
            </div>

            {/* Grid */}
            {loading ? (
                <div className="flex justify-center py-20">
                    <div className="w-10 h-10 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
                </div>
            ) : filteredProjects.length > 0 ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
                    {filteredProjects.map((project) => (
                        <motion.div 
                            key={project.id}
                            whileHover={{ y: -5 }}
                            onClick={() => navigate(`/gpt/chat/${project.id}`)}
                            className="bg-[var(--bg-card)] border border-[var(--border)] rounded-3xl p-6 space-y-4 cursor-pointer hover:shadow-2xl transition-all group relative overflow-hidden text-sm"
                        >
                            <div className="absolute top-0 right-0 w-32 h-32 bg-[var(--accent-indigo)] opacity-[0.03] rounded-full -mr-16 -mt-16"></div>
                            
                            <div className="flex items-start justify-between relative z-10">
                                <div className="w-12 h-12 rounded-xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center shadow-inner">
                                    <Bot size={24} />
                                </div>
                                {user?.role === 'superadmin' && (
                                    <div className="flex gap-1">
                                        <button 
                                            onClick={(e) => { e.stopPropagation(); navigate(`/gpt/edit/${project.id}`); }}
                                            className="p-2 hover:bg-[var(--input-bg)] rounded-xl text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all"
                                        >
                                            <Settings2 size={18} />
                                        </button>
                                        <button 
                                            onClick={(e) => handleDelete(project.id, e)}
                                            className="p-2 hover:bg-red-50 rounded-xl text-[var(--text-muted)] hover:text-red-500 transition-all"
                                        >
                                            <Trash2 size={18} />
                                        </button>
                                    </div>
                                )}
                            </div>

                            <div className="space-y-2 relative z-10">
                                <h3 className="text-xl font-black text-[var(--text-main)] tracking-tight group-hover:text-[var(--accent-indigo)] transition-colors">{project.title}</h3>
                                <p className="text-[13px] text-[var(--text-muted)] leading-relaxed font-medium line-clamp-2">
                                    {project.description || 'Custom intelligence tuned for project-specific goals and strategies.'}
                                </p>
                            </div>

                            <div className="pt-4 border-t border-[var(--border)] flex items-center justify-between relative z-10">
                                <div className="flex items-center gap-2">
                                    <div className="flex -space-x-2">
                                        {[1,2,3].map(i => (
                                            <div key={i} className="w-6 h-6 rounded-full border-2 border-[var(--bg-card)] bg-gray-200"></div>
                                        ))}
                                    </div>
                                    <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Active Now</span>
                                </div>
                                <button className="flex items-center gap-1.5 text-[var(--accent-indigo)] font-black text-[11px] uppercase tracking-widest">
                                    Chat Now <ArrowRight size={14} />
                                </button>
                            </div>
                        </motion.div>
                    ))}
                </div>
            ) : (
                <div className="text-center py-20 bg-[var(--bg-card)] border border-dashed border-[var(--border)] rounded-[40px] space-y-4">
                    <div className="w-20 h-20 rounded-full bg-[var(--input-bg)] flex items-center justify-center mx-auto text-[var(--text-muted)]">
                        <MessageCircle size={40} />
                    </div>
                    <h3 className="text-xl font-black text-[var(--text-main)]">No assistants found</h3>
                    <p className="text-[var(--text-muted)] font-medium max-w-sm mx-auto">Try searching for something else or create a new GPT project if you are an administrator.</p>
                </div>
            )}
        </div>
    );
};

export default GptProjects;
