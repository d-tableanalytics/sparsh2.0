import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../services/api';
import { motion, AnimatePresence } from 'framer-motion';
import { 
    Send, Sparkles, Bot, User, ArrowLeft, 
    MessageSquare, RefreshCcw, HelpCircle, Info,
    Command, Database, Sidebar, ShieldCheck
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const GptChat = () => {
    const { id } = useParams();
    const navigate = useNavigate();
    const { user } = useAuth();
    const [project, setProject] = useState(null);
    const [loading, setLoading] = useState(true);
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [sending, setSending] = useState(false);
    const scrollRef = useRef(null);

    const fetchData = async () => {
        try {
            const [projRes, histRes] = await Promise.all([
                api.get(`/gpt/projects/${id}`),
                api.get(`/gpt/chat/${id}/history`)
            ]);
            setProject(projRes.data);
            setMessages(histRes.data.messages || []);
        } catch (err) {
            console.error(err);
            alert("Connection error.");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (id) fetchData();
    }, [id]);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages]);

    const handleSend = async (msgOverride) => {
        const message = msgOverride || input;
        if (!message.trim() || sending) return;

        const userMsg = { role: 'user', content: message, timestamp: new Date() };
        setMessages(prev => [...prev, userMsg]);
        setInput('');
        setSending(true);

        try {
            const res = await api.post(`/gpt/chat/${id}/respond`, { message });
            const aiMsg = { role: 'assistant', content: res.data.answer, timestamp: new Date() };
            setMessages(prev => [...prev, aiMsg]);
        } catch (err) {
            console.error(err);
            const errAiMsg = { role: 'assistant', content: "I'm sorry, I encountered a temporary network issue. Please try again in absolute comfort.", error: true };
            setMessages(prev => [...prev, errAiMsg]);
        } finally {
            setSending(false);
        }
    };

    if (loading) return <div className="flex justify-center p-20 animate-pulse text-[var(--accent-indigo)]">Loading Neural Engine...</div>;
    if (!project) return <div>Project not found</div>;

    return (
        <div className="max-w-7xl mx-auto h-[calc(100vh-120px)] flex flex-col gap-4 px-4 pb-4 text-sm">
            
            {/* Header Toolbar */}
            <div className="flex items-center justify-between bg-[var(--bg-card)] border border-[var(--border)] p-3 rounded-2xl shadow-sm">
                <div className="flex items-center gap-4">
                    <button onClick={() => navigate('/gpt')} className="p-2.5 bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] rounded-xl hover:text-[var(--accent-indigo)] transition-all active:scale-95">
                        <ArrowLeft size={18} />
                    </button>
                    <div className="flex flex-col">
                        <h1 className="text-lg font-black text-[var(--text-main)] tracking-tight flex items-center gap-2">
                             {project.title} <span className="px-2 py-0.5 bg-emerald-50 text-emerald-600 border border-emerald-100 rounded-md text-[9px] uppercase font-black tracking-widest italic">Stable v1.0</span>
                        </h1>
                        <div className="flex items-center gap-4 text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest mt-0.5">
                             <span className="flex items-center gap-1"><Database size={10} className="text-amber-500" /> {project.knowledge_files?.length || 0} Knowledge Bases</span>
                             <span className="flex items-center gap-1"><ShieldCheck size={10} className="text-[var(--accent-indigo)]" /> {user?.role} Access </span>
                        </div>
                    </div>
                </div>
                
                <div className="flex gap-2">
                     <button onClick={fetchData} className="p-3 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all bg-[var(--input-bg)] rounded-xl border border-[var(--border)]">
                        <RefreshCcw size={16} />
                    </button>
                    {user?.role === 'superadmin' && (
                         <button onClick={() => navigate(`/gpt/edit/${id}`)} className="h-10 px-4 bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] rounded-xl flex items-center gap-2 font-black uppercase text-[10px] tracking-widest hover:border-[var(--accent-indigo)] transition-all">
                             <Command size={14} /> Tune GPT
                         </button>
                    )}
                </div>
            </div>

            <div className="flex-1 flex gap-4 min-h-0">
                {/* Main Chat Area */}
                <div className="flex-1 bg-[var(--bg-card)] border border-[var(--border)] rounded-3xl flex flex-col shadow-sm overflow-hidden relative">
                    <div className="absolute top-0 left-0 w-48 h-48 bg-[var(--accent-indigo)] opacity-[0.02] rounded-full -ml-24 -mt-24"></div>
                    
                    {/* Message List */}
                    <div ref={scrollRef} className="flex-1 overflow-y-auto p-6 space-y-6 no-scrollbar scroll-smooth">
                        {messages.length === 0 ? (
                            <div className="h-full flex flex-col items-center justify-center text-center space-y-6 opacity-60">
                                <div className="w-20 h-20 rounded-[32px] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center shadow-lg transform -rotate-6">
                                    <Bot size={40} />
                                </div>
                                <div className="space-y-2">
                                     <h2 className="text-2xl font-black text-[var(--text-main)] italic">Welcome to {project.title}!</h2>
                                     <p className="text-[14px] font-medium max-w-sm">How can I assist you with this project knowledge base today?</p>
                                </div>
                                
                                <div className="flex flex-wrap items-center justify-center gap-4 max-w-xl">
                                    {project.conversation_starters?.map((starter, i) => (
                                        <button 
                                            key={i} 
                                            onClick={() => handleSend(starter)}
                                            className="px-5 py-3.5 bg-white border border-[var(--border)] rounded-2xl text-[12px] font-bold text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo)] hover:text-white transition-all active:scale-95 shadow-sm"
                                        >
                                            {starter}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        ) : (
                            <>
                                {messages.map((m, idx) => (
                                    <motion.div 
                                        key={idx}
                                        initial={{ opacity: 0, y: 10 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        className={`flex items-start gap-4 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}
                                    >
                                        <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 shadow-md ${m.role === 'user' ? 'bg-[var(--accent-indigo)] text-white' : 'bg-white border border-[var(--border)] text-[var(--accent-indigo)]'}`}>
                                            {m.role === 'user' ? <User size={18} /> : <Bot size={18} />}
                                        </div>
                                        <div className={`flex flex-col ${m.role === 'user' ? 'items-end' : 'items-start'} max-w-[85%]`}>
                                            <div className={`p-4 rounded-2xl text-[13px] leading-relaxed font-medium shadow-sm transition-all ${m.role === 'user' ? 'bg-[var(--accent-indigo)] text-white font-bold rounded-tr-none' : 'bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] rounded-tl-none whitespace-pre-wrap'}`}>
                                                {m.content}
                                            </div>
                                            <span className="text-[9px] font-black uppercase text-[var(--text-muted)] tracking-widest mt-2">{m.role === 'user' ? 'Sent by you' : `${project.title} Response`}</span>
                                        </div>
                                    </motion.div>
                                ))}
                                {sending && (
                                    <div className="flex items-start gap-4 animate-pulse">
                                        <div className="w-10 h-10 rounded-xl bg-white border border-[var(--border)] text-[var(--accent-indigo)] flex items-center justify-center">
                                            <Bot size={18} />
                                        </div>
                                        <div className="flex gap-2 mt-4">
                                            <div className="w-2 h-2 bg-[var(--text-muted)] rounded-full animate-bounce"></div>
                                            <div className="w-2 h-2 bg-[var(--text-muted)] rounded-full animate-bounce delay-100"></div>
                                            <div className="w-2 h-2 bg-[var(--text-muted)] rounded-full animate-bounce delay-200"></div>
                                        </div>
                                    </div>
                                )}
                            </>
                        )}
                    </div>

                    {/* Chat Input */}
                    <div className="px-6 pb-6 pt-2 bg-[var(--bg-card)]/80 backdrop-blur-md">
                        <form onSubmit={(e) => { e.preventDefault(); handleSend(); }} className="relative group">
                            <input 
                                value={input}
                                onChange={e => setInput(e.target.value)}
                                disabled={sending}
                                placeholder="Message your project assistant..."
                                className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl py-4 pl-6 pr-16 text-[14px] font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)] transition-all shadow-inner placeholder:text-[var(--text-muted)]"
                            />
                            <button 
                                type="submit" 
                                disabled={sending || !input.trim()}
                                className="absolute right-2 top-2 w-10 h-10 bg-[var(--accent-indigo)] text-white rounded-xl flex items-center justify-center hover:opacity-90 active:scale-90 transition-all shadow-xl shadow-indigo-100 disabled:bg-gray-200 disabled:shadow-none"
                            >
                                <Send size={20} />
                            </button>
                        </form>
                        <p className="text-center text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest mt-3 flex items-center justify-center gap-2">
                             <HelpCircle size={12} className="text-amber-500" /> Responses are generated based on project training data.
                        </p>
                    </div>
                </div>

                {/* Info Sidebar (Optional Desktop) */}
                <div className="hidden xl:flex w-72 flex-col gap-4">
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-3xl p-6 space-y-4 shadow-sm">
                        <h4 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest border-b border-[var(--border)] pb-4">Project Scope</h4>
                         <p className="text-[13px] text-[var(--text-muted)] leading-relaxed font-bold">
                             {project.description || "The scope for this assistant combines all uploaded project material with refined AI modeling techniques."}
                         </p>
                         
                         <div className="space-y-3">
                             <div className="flex items-center gap-3 p-3 bg-[var(--input-bg)] rounded-2xl border border-transparent hover:border-[var(--accent-indigo)]/20 transition-all group">
                                 <div className="p-2 bg-white rounded-xl border border-[var(--border)] text-[var(--accent-indigo)]">
                                     <Sparkles size={14} />
                                 </div>
                                 <span className="text-[11px] font-black uppercase tracking-widest text-[var(--text-main)]">Model 4o-tuned</span>
                             </div>
                             <div className="flex items-center gap-3 p-3 bg-[var(--input-bg)] rounded-2xl border border-transparent hover:border-[var(--accent-indigo)]/20 transition-all group">
                                 <div className="p-2 bg-white rounded-xl border border-[var(--border)] text-emerald-500">
                                     <Database size={14} />
                                 </div>
                                 <span className="text-[11px] font-black uppercase tracking-widest text-[var(--text-main)]">RAG Index: Active</span>
                             </div>
                         </div>
                    </div>

                    <div className="flex-1 bg-gradient-to-br from-indigo-50/30 to-purple-50/30 border border-indigo-100 rounded-3xl p-6 flex flex-col items-center justify-center text-center space-y-4">
                        <div className="p-4 bg-white/80 backdrop-blur rounded-3xl shadow-sm">
                             <Command size={32} className="text-[var(--accent-indigo)] animate-pulse" />
                        </div>
                        <h5 className="text-xl font-black text-[var(--text-main)] tracking-tight">Need help?</h5>
                        <p className="text-[12px] font-black text-[var(--text-muted)] uppercase tracking-widest">Consult GPT Documentation in Core Settings.</p>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default GptChat;
