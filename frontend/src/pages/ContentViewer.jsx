import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { 
    ArrowLeft, 
    MessageSquare, 
    FileText, 
    StickyNote, 
    Send, 
    Eye, 
    Users, 
    Sparkles, 
    Clock, 
    Download, 
    AlertCircle, 
    ChevronRight
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import api from '../services/api';

const ContentViewer = () => {
    const { sessionId, resourceId } = useParams();
    const navigate = useNavigate();
    const [loading, setLoading] = useState(true);
    const [resource, setResource] = useState(null);
    const [activeTab, setActiveTab] = useState('AI'); // AI, Transcript
    const [chatInput, setChatInput] = useState('');
    const [chatHistory, setChatHistory] = useState([]);
    const [askingAI, setAskingAI] = useState(false);
    const videoRef = useRef(null);

    useEffect(() => {
        fetchResourceDetails();
        trackView();
    }, [resourceId]);

    const fetchResourceDetails = async () => {
        try {
            const res = await api.get(`/calendar/events/${sessionId}/resources/${resourceId}`);
            setResource(res.data);
        } catch (err) {
            console.error("Error fetching resource:", err);
        } finally {
            setLoading(false);
        }
    };

    const trackView = async () => {
        try {
            await api.post(`/calendar/events/${sessionId}/resources/${resourceId}/view`);
        } catch (err) {
            console.error("Error tracking view:", err);
        }
    };

    const handleAskAI = async (e) => {
        e.preventDefault();
        if (!chatInput.trim()) return;

        const userMsg = chatInput;
        setChatInput('');
        setChatHistory(prev => [...prev, { role: 'user', content: userMsg }]);
        setAskingAI(true);

        try {
            const res = await api.post(`/calendar/events/${sessionId}/resources/${resourceId}/chat`, {
                question: userMsg
            });
            setChatHistory(prev => [...prev, { role: 'ai', content: res.data.answer }]);
        } catch (err) {
            setChatHistory(prev => [...prev, { role: 'ai', content: "Sorry, I'm having trouble connecting right now." }]);
        } finally {
            setAskingAI(false);
        }
    };

    const seekToTimestamp = (timestamp) => {
        // Simple regex or similar to find timestamps like 12:34
        if (videoRef.current) {
            // This is just a placeholder logic to show how it would work
            // Actual implementation would need timestamp markers in the transcript
            // videoRef.current.currentTime = seconds;
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center min-h-screen bg-[var(--bg-main)]">
                <div className="w-12 h-12 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
            </div>
        );
    }

    if (!resource) {
        return (
            <div className="flex flex-col items-center justify-center min-h-screen bg-[var(--bg-main)] text-[var(--text-muted)] p-4">
                <AlertCircle size={64} className="mb-4 opacity-20" />
                <h2 className="text-2xl font-black mb-2">Resource Not Found</h2>
                <button onClick={() => navigate(-1)} className="px-6 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl font-bold">Go Back</button>
            </div>
        );
    }

    const isVideo = resource.file_type?.startsWith('video/') || resource.system_type === 'video';
    const isAudio = resource.file_type?.startsWith('audio/') || resource.system_type === 'audio';

    return (
        <div className="min-h-screen bg-[var(--bg-main)] flex flex-col lg:flex-row">
            
            {/* Left Section: Content Player */}
            <div className="flex-1 overflow-y-auto no-scrollbar p-6 lg:p-10 space-y-8">
                <div className="flex items-center justify-between mb-2">
                    <button onClick={() => navigate(-1)} className="flex items-center gap-2 text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors font-bold text-sm">
                        <ArrowLeft size={18} /> Back to Session
                    </button>
                    <div className="px-3 py-1 bg-[var(--input-bg)] border border-[var(--border)] rounded-full text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                        {resource.system_type} Mode
                    </div>
                </div>

                {/* Media Container */}
                <div className="bg-black rounded-[32px] overflow-hidden shadow-2xl aspect-video flex items-center justify-center relative group">
                    {isVideo ? (
                        <video 
                            ref={videoRef}
                            src={resource.url} 
                            controls 
                            crossOrigin="anonymous"
                            controlsList="nodownload"
                            onContextMenu={(e) => e.preventDefault()}
                            className="w-full h-full object-contain"
                        />
                    ) : isAudio ? (
                        <div className="w-full h-full flex flex-col items-center justify-center space-y-6 bg-gradient-to-br from-gray-900 to-black p-10">
                            <div className="w-24 h-24 rounded-full bg-[var(--accent-indigo)] flex items-center justify-center shadow-lg shadow-indigo-500/20">
                                <Sparkles size={40} className="text-white animate-pulse" />
                            </div>
                            <audio 
                                ref={videoRef} 
                                src={resource.url} 
                                controls 
                                crossOrigin="anonymous" 
                                controlsList="nodownload"
                                onContextMenu={(e) => e.preventDefault()}
                                className="w-full max-w-md accent-indigo-500" 
                            />
                        </div>
                    ) : (
                        <div className="text-white flex flex-col items-center gap-4">
                            <FileText size={80} className="opacity-20" />
                            <p className="font-bold text-lg">Document Viewer</p>
                            <div className="px-6 py-2 bg-white/10 border border-white/20 text-white rounded-full font-black text-xs uppercase cursor-default">Non-Downloadable Resource</div>
                        </div>
                    )}
                </div>

                {/* Meta Info */}
                <div className="flex flex-col md:flex-row md:items-start justify-between gap-6 pb-20">
                    <div className="space-y-4 max-w-2xl">
                        <h1 className="text-3xl font-black text-[var(--text-main)] tracking-tight">{resource.name}</h1>
                        <div className="space-y-2">
                            <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Description</label>
                            <p className="text-[14px] leading-relaxed text-[var(--text-muted)]">
                                No specific description provided for this resource. Use the AI Companion to summarize and understand the core topics discussed.
                            </p>
                        </div>
                    </div>

                    <div className="flex gap-4">
                        <div className="bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-2xl flex items-center gap-4 shadow-sm min-w-[140px]">
                            <div className="w-10 h-10 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center">
                                <Eye size={20} />
                            </div>
                            <div>
                                <p className="text-[10px] font-black text-gray-400 uppercase">Total Views</p>
                                <p className="text-xl font-black">{resource.views || 0}</p>
                            </div>
                        </div>
                        <div className="bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-2xl flex items-center gap-4 shadow-sm min-w-[160px]">
                            <div className="w-10 h-10 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center">
                                <Users size={20} />
                            </div>
                            <div>
                                <p className="text-[10px] font-black text-gray-400 uppercase">Unique Viewers</p>
                                <p className="text-xl font-black">1</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Right Section: AI Companion & Transcript */}
            <div className="w-full lg:w-[450px] bg-[var(--bg-card)] border-l border-[var(--border)] flex flex-col h-screen overflow-hidden">
                
                {/* Header */}
                <div className="p-6 border-b border-[var(--border)] flex items-center justify-between bg-[var(--bg-card)]/80 backdrop-blur-md sticky top-0 z-10">
                    <h2 className="text-lg font-black text-[var(--text-main)] flex items-center gap-2">
                        <Sparkles size={20} className="text-[var(--accent-indigo)]" /> AI Companion
                    </h2>
                </div>

                {/* Tabs */}
                <div className="flex border-b border-[var(--border)] px-4 bg-[var(--bg-card)]/30">
                    {['AI', 'Transcript'].map(tab => (
                        <button 
                            key={tab}
                            onClick={() => setActiveTab(tab)}
                            className={`px-4 py-4 text-[11px] font-black uppercase tracking-widest relative transition-all ${activeTab === tab ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}
                        >
                            {tab}
                            {activeTab === tab && (
                                <motion.div layoutId="activeTab" className="absolute bottom-0 left-0 right-0 h-1 bg-[var(--accent-indigo)] rounded-t-full" />
                            )}
                        </button>
                    ))}
                </div>

                {/* Content Area */}
                <div className="flex-1 overflow-y-auto p-6 no-scrollbar">
                    <AnimatePresence mode="wait">
                        {activeTab === 'Transcript' && (
                            <motion.div 
                                initial={{ opacity: 0, x: 10 }} 
                                animate={{ opacity: 1, x: 0 }} 
                                exit={{ opacity: 0, x: -10 }}
                                className="space-y-6"
                            >
                                {resource.transcription ? (
                                    <div className="space-y-4">
                                        <div className="flex items-center gap-2 text-[var(--accent-indigo)] mb-4 bg-[var(--accent-indigo-bg)] p-3 rounded-xl border border-[var(--accent-indigo)]/20 italic text-[12px]">
                                            <Clock size={14} /> AI-generated transcript. Click segments to seek in player.
                                        </div>
                                        <p className="text-[13px] leading-relaxed text-[var(--text-main)] font-medium">
                                            {resource.transcription}
                                        </p>
                                    </div>
                                ) : (
                                    <div className="text-center py-20 text-[var(--text-muted)] opacity-50 space-y-4">
                                        <FileText size={48} className="mx-auto" />
                                        <p className="text-sm font-bold uppercase tracking-widest">No transcript available.</p>
                                    </div>
                                )}
                            </motion.div>
                        )}

                        {activeTab === 'AI' && (
                            <motion.div 
                                initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }}
                                className="space-y-6"
                            >
                                <div className="p-4 bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo)]/10 rounded-[20px] shadow-sm">
                                    <div className="flex items-center gap-2 text-[var(--accent-indigo)] mb-2">
                                        <Sparkles size={16} />
                                        <h4 className="text-[11px] font-black uppercase tracking-widest">Intelligent Assistant</h4>
                                    </div>
                                    <p className="text-[12px] text-[var(--text-muted)] leading-relaxed">
                                        Hello! I've analyzed this session's recording. You can ask me anything about the content, specific topics, or for a summary.
                                    </p>
                                </div>
                                
                                {chatHistory.length > 0 && (
                                    <div className="space-y-6 pt-4">
                                        {chatHistory.map((chat, idx) => (
                                            <div key={idx} className={`flex flex-col ${chat.role === 'user' ? 'items-end' : 'items-start'} space-y-2`}>
                                                <div className={`max-w-[90%] p-4 rounded-2xl text-[13px] font-medium leading-relaxed shadow-sm ${chat.role === 'user' ? 'bg-[var(--accent-indigo)] text-white rounded-tr-none' : 'bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] rounded-tl-none'}`}>
                                                    {chat.content}
                                                </div>
                                            </div>
                                        ))}
                                        {askingAI && (
                                            <div className="flex items-center gap-2 text-[var(--text-muted)]">
                                                <div className="flex gap-1">
                                                    <motion.div animate={{ scale: [1, 1.5, 1] }} transition={{ repeat: Infinity, duration: 1 }} className="w-1 h-1 bg-[var(--text-muted)] rounded-full" />
                                                    <motion.div animate={{ scale: [1, 1.5, 1] }} transition={{ repeat: Infinity, duration: 1, delay: 0.2 }} className="w-1 h-1 bg-[var(--text-muted)] rounded-full" />
                                                    <motion.div animate={{ scale: [1, 1.5, 1] }} transition={{ repeat: Infinity, duration: 1, delay: 0.4 }} className="w-1 h-1 bg-[var(--text-muted)] rounded-full" />
                                                </div>
                                                <span className="text-[10px] font-black uppercase tracking-widest">AI is thinking...</span>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>

                {/* Chat Input - Only visible on AI tab */}
                {activeTab === 'AI' && (
                    <div className="p-6 bg-[var(--bg-card)] border-t border-[var(--border)]">
                        <form onSubmit={handleAskAI} className="relative group">
                            <input 
                                value={chatInput}
                                onChange={e => setChatInput(e.target.value)}
                                className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl py-4 pl-5 pr-14 text-sm font-medium focus:border-[var(--accent-indigo)] outline-none transition-all placeholder:text-[var(--text-muted)]"
                                placeholder="Ask AI about this video..."
                                disabled={askingAI}
                            />
                            <button 
                                type="submit"
                                disabled={askingAI}
                                className="absolute right-2 top-2 w-10 h-10 rounded-xl bg-[var(--accent-indigo)] text-white flex items-center justify-center hover:opacity-90 active:scale-95 transition-all shadow-md shadow-indigo-200"
                            >
                                <Send size={18} />
                            </button>
                        </form>
                        <div className="mt-3 flex items-center gap-2 text-[9px] font-bold text-[var(--text-muted)] uppercase tracking-wider ml-1">
                            <Sparkles size={12} className="text-[var(--accent-indigo)]" /> Powered by Advanced LLM
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default ContentViewer;
