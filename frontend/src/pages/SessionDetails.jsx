import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../services/api';
import { motion } from 'framer-motion';
import { 
    ArrowLeft, Calendar as CalendarIcon, Clock, Link as LinkIcon, 
    Video, Users2, Activity, CheckCircle, PlusCircle, AlertCircle, 
    UploadCloud, UserCheck, FileUp, X, ListTodo, FileText, CheckSquare, HelpCircle
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const SessionDetails = () => {
    const { sessionId } = useParams();
    const navigate = useNavigate();
    const { user } = useAuth();
    
    const [session, setSession] = useState(null);
    const [loading, setLoading] = useState(true);
    const [completing, setCompleting] = useState(false);
    
    const role = user?.role?.toLowerCase();
    const isStaff = ['superadmin', 'admin', 'coach', 'staff'].includes(role);
    
    // Attendance State
    const [attendees, setAttendees] = useState([]);
    const [attendanceMarks, setAttendanceMarks] = useState({});
    const [showAttendanceModal, setShowAttendanceModal] = useState(false);
    const [savingAttendance, setSavingAttendance] = useState(false);

    const fetchSessionData = async () => {
        try {
            const res = await api.get(`/calendar/events/${sessionId}`);
            const ev = res.data;
            setSession(ev);
            
            // Also fetch users and filter attendees
            const usersRes = await api.get('/users');
            const assignedIds = ev.assigned_member_ids || [];
            // Target staff might also be attendees if it's a task. We'll handle 'assigned_member_ids'
            const filteredUsers = usersRes.data.filter(u => assignedIds.includes(u._id || u.id));
            setAttendees(filteredUsers);
            
            if (ev.attendance) {
                setAttendanceMarks(ev.attendance);
            } else {
                // Default all to absent (false)
                const initialMarks = {};
                filteredUsers.forEach(u => initialMarks[u._id || u.id] = false);
                setAttendanceMarks(initialMarks);
            }

        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchSessionData();
    }, [sessionId]);

    const handleSaveAttendance = async () => {
        setSavingAttendance(true);
        try {
            await api.post(`/calendar/events/${sessionId}/attendance`, {
                attendees: attendanceMarks
            });
            setShowAttendanceModal(false);
            alert("Attendance marked! Emails sent in the background.");
            fetchSessionData(); // Refresh to ensure we have the latest payload
        } catch (err) {
            console.error(err);
            alert("Failed to submit attendance.");
        } finally {
            setSavingAttendance(false);
        }
    };

    // Upload States
    const [uploadModalType, setUploadModalType] = useState(null); // 'content' or 'resource'
    const [uploadFile, setUploadFile] = useState(null);
    const [resourceType, setResourceType] = useState('pdf');
    const [uploading, setUploading] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);

    const handleUploadSubmit = async () => {
        if (!uploadFile) return alert("Please select a file first.");
        setUploading(true);
        setUploadProgress(0);
        const formData = new FormData();
        formData.append('file', uploadFile);
        
        try {
            const config = {
                headers: { 'Content-Type': 'multipart/form-data' },
                onUploadProgress: (progressEvent) => {
                    const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
                    setUploadProgress(percentCompleted);
                }
            };
            
            if (uploadModalType === 'resource') {
                formData.append('resource_type', resourceType);
                await api.post(`/calendar/events/${sessionId}/upload-resource`, formData, config);
            } else {
                await api.post(`/calendar/events/${sessionId}/upload-content`, formData, config);
            }
            alert("Upload successful!");
            setUploadModalType(null);
            setUploadFile(null);
            setUploadProgress(0);
            fetchSessionData();
        } catch (err) {
            console.error(err);
            const msg = err.response?.data?.detail || "Upload failed.";
            alert("Upload failed: " + msg);
        } finally {
            setUploading(false);
        }
    };

    const handleMarkCompleted = async () => {
        if (!window.confirm("Are you sure you want to mark this session as completed? This will update the attendance records and lock the session status.")) return;
        
        setCompleting(true);
        try {
            await api.patch(`/calendar/events/${sessionId}/complete`);
            alert("Session marked as completed successfully!");
            fetchSessionData();
        } catch (err) {
            console.error(err);
            alert("Failed to mark session as completed: " + (err.response?.data?.detail || err.message));
        } finally {
            setCompleting(false);
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center min-h-[60vh]">
                <div className="w-10 h-10 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
            </div>
        );
    }

    if (!session) {
        return (
            <div className="flex flex-col items-center justify-center min-h-[60vh] text-[var(--text-muted)] space-y-4">
                <AlertCircle size={48} className="opacity-50" />
                <p className="text-xl font-bold tracking-tight">Session not found.</p>
                <button onClick={() => navigate(-1)} className="px-6 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg font-bold text-[13px]">Go Back</button>
            </div>
        );
    }

    return (
        <div className="max-w-5xl mx-auto space-y-8 pb-20 relative">
            {/* Header */}
            <div className="flex items-start justify-between">
                <div className="flex items-center gap-4">
                    <button onClick={() => navigate(-1)} className="p-2.5 rounded-xl bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all">
                        <ArrowLeft size={18} />
                    </button>
                    <div>
                        <div className="flex items-center gap-2 mb-1">
                            <span className="px-2.5 py-1 rounded-md text-[10px] font-black uppercase tracking-widest bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center gap-1.5">
                                <Activity size={12} /> {session.type || 'Session'}
                            </span>
                            <span className={`px-2.5 py-1 rounded-md text-[10px] font-black uppercase tracking-widest ${session.status === 'completed' ? 'bg-emerald-50 text-emerald-600' : 'bg-orange-50 text-orange-600'}`}>
                                {session.status || 'Scheduled'}
                            </span>
                        </div>
                        <h1 className="text-3xl font-black text-[var(--text-main)] tracking-tight">{session.title}</h1>
                    </div>
                </div>
                
                {isStaff && (
                    <div className="flex gap-3">
                        {session.status !== 'completed' && (
                            <button 
                                onClick={handleMarkCompleted} 
                                disabled={completing}
                                className="flex items-center gap-2 h-10 px-5 bg-indigo-600 text-white border border-indigo-700 rounded-xl text-[13px] font-black hover:bg-indigo-700 transition-all shadow-md active:scale-95 disabled:opacity-50"
                            >
                                {completing ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div> : <CheckCircle size={16} />} 
                                Mark Completed
                            </button>
                        )}
                        <button onClick={() => setShowAttendanceModal(true)} className="flex items-center gap-2 h-10 px-5 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-xl text-[13px] font-black hover:bg-emerald-500 hover:text-white transition-all shadow-sm">
                            <UserCheck size={16} /> Mark Attendance
                        </button>
                        <button onClick={() => setUploadModalType('resource')} className="flex items-center gap-2 h-10 px-5 bg-amber-50 border border-amber-200 text-amber-700 rounded-xl text-[13px] font-black hover:bg-amber-500 hover:text-white transition-all shadow-sm">
                            <FileUp size={16} /> Upload Resources
                        </button>
                        <button onClick={() => setUploadModalType('content')} className="flex items-center gap-2 h-10 px-5 bg-[var(--accent-indigo)] text-white rounded-xl text-[13px] font-black hover:opacity-90 transition-all shadow-md shadow-indigo-200">
                            <UploadCloud size={16} /> Upload Content
                        </button>
                    </div>
                )}
            </div>

            {/* Content Details */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                
                {/* Left Card: Core Info */}
                <div className="lg:col-span-2 space-y-6">
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] p-8 rounded-[32px] shadow-sm">
                        <h3 className="text-[12px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-6 border-b border-[var(--border)] pb-4">Session Brief</h3>
                        
                        <div className="grid grid-cols-2 gap-8 mb-8">
                            <div className="space-y-1.5">
                                <span className="flex items-center gap-2 text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider"><CalendarIcon size={14} /> Date</span>
                                <p className="text-[15px] font-bold text-[var(--text-main)]">
                                    {new Date(session.start).toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
                                </p>
                            </div>
                            <div className="space-y-1.5">
                                <span className="flex items-center gap-2 text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider"><Clock size={14} /> Time (IST)</span>
                                <p className="text-[15px] font-bold text-[var(--text-main)]">
                                    {new Date(session.start).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true })}
                                    {session.end && ` — ${new Date(session.end).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true })}`}
                                </p>
                            </div>
                        </div>

                        {session.meeting_link && (
                            <div className="mb-8 p-4 bg-[var(--input-bg)] rounded-2xl border border-[var(--border)] flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    <div className="w-10 h-10 rounded-full bg-blue-50 flex items-center justify-center text-blue-600">
                                        <Video size={18} />
                                    </div>
                                    <div>
                                        <p className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wider">Meeting Link</p>
                                        <a href={session.meeting_link} target="_blank" rel="noreferrer" className="text-[14px] font-bold text-[var(--accent-indigo)] hover:underline flex items-center gap-1.5 mt-0.5">
                                            {session.meeting_link} <LinkIcon size={12} />
                                        </a>
                                    </div>
                                </div>
                                <a href={session.meeting_link} target="_blank" rel="noreferrer" className="px-4 py-2 bg-blue-600 text-white text-[11px] font-bold uppercase rounded-lg shadow-sm hover:bg-blue-700 transition-colors">Join Now</a>
                            </div>
                        )}

                        <div className="space-y-2">
                            <span className="flex items-center gap-2 text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider mb-2">Extended Notes / Instructions</span>
                            {session.additional_details ? (
                                <p className="text-[14px] leading-relaxed text-[var(--text-main)] bg-[var(--input-bg)] p-5 rounded-2xl whitespace-pre-wrap font-medium border border-transparent">
                                    {session.additional_details}
                                </p>
                            ) : (
                                <p className="text-[13px] italic text-[var(--text-muted)] opacity-60">No additional instructions provided for this session.</p>
                            )}
                        </div>
                    </div>
                </div>

                {/* Right Card: Participants & Settings */}
                <div className="space-y-6">
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] p-6 rounded-[32px] shadow-sm">
                        <h3 className="text-[12px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-6 flex items-center gap-2"><Users2 size={16} /> Participants & Scope</h3>
                        
                        <div className="space-y-5">
                            <div className="space-y-2">
                                <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Delegated To (Departments)</label>
                                <div className="flex flex-wrap gap-2">
                                    {session.assigned_departments?.length > 0 ? (
                                        session.assigned_departments.map((d, i) => <span key={i} className="px-3 py-1 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[11px] font-bold">{d}</span>)
                                    ) : <span className="text-[12px] text-[var(--text-muted)] italic">N/A</span>}
                                </div>
                            </div>
                            
                            <div className="space-y-2">
                                <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Session Type</label>
                                <p className="text-[13px] font-bold text-[var(--text-main)]">{session.session_type || 'General'}</p>
                            </div>

                            <div className="space-y-2">
                                <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Priority Segment</label>
                                <p className={`text-[13px] font-black ${session.priority === 'High' || session.priority === 'Urgent' ? 'text-red-500' : 'text-[var(--text-main)]'}`}>{session.priority || 'Normal'}</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Uploaded Materials rendering */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4">
                {/* Content - Downloadable */}
                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-6 shadow-sm">
                    <h3 className="text-[12px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-4 flex items-center gap-2">
                        <UploadCloud size={16} className="text-[var(--accent-indigo)]" /> Uploaded Content
                    </h3>
                    <div className="space-y-2">
                        {session.contents && session.contents.length > 0 ? (
                            session.contents.map((item, idx) => (
                                <div key={idx} className="flex items-center justify-between p-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl">
                                    <span className="text-[12px] font-bold text-[var(--text-main)] truncate max-w-[200px]">{item.name}</span>
                                    <a href={item.url} target="_blank" rel="noreferrer" download className="px-3 py-1.5 bg-blue-50 text-blue-700 text-[10px] font-black uppercase rounded-lg hover:bg-blue-100 transition-colors">
                                        Download
                                    </a>
                                </div>
                            ))
                        ) : (
                            <p className="text-[12px] text-gray-400 italic text-center py-4">No content uploaded yet.</p>
                        )}
                    </div>
                </div>

                {/* Resources - View Only */}
                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-6 shadow-sm">
                    <h3 className="text-[12px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-4 flex items-center gap-2">
                        <FileUp size={16} className="text-amber-500" /> Session Resources
                    </h3>
                    <div className="space-y-2">
                        {session.resources && session.resources.length > 0 ? (
                            session.resources.map((item, idx) => (
                                <div key={idx} className="flex flex-col bg-[var(--input-bg)] border border-[var(--border)] rounded-xl overflow-hidden">
                                    <div className="flex items-center justify-between p-3 border-b border-transparent">
                                        <div className="flex flex-col">
                                            <span className="text-[12px] font-bold text-[var(--text-main)] truncate max-w-[180px]">{item.name}</span>
                                            <span className="text-[9px] font-black uppercase text-amber-600">
                                                {item.system_type} {item.status === 'processing' && '— Processing...'}
                                                {item.status === 'failed' && '— Failed'}
                                            </span>
                                        </div>
                                        {item.status === 'processing' ? (
                                            <div className="w-5 h-5 border-2 border-amber-500 border-t-transparent rounded-full animate-spin"></div>
                                        ) : item.status === 'failed' ? (
                                            <AlertCircle size={16} className="text-red-500" />
                                        ) : (
                                            <button onClick={() => navigate(`/sessions/${sessionId}/resource/${item.id}`)} className="px-3 py-1.5 bg-gray-200 text-gray-700 text-[10px] font-black uppercase rounded-lg hover:bg-gray-300 transition-colors">
                                                View Content
                                            </button>
                                        )}
                                    </div>
                                </div>
                            ))
                        ) : (
                            <p className="text-[12px] text-gray-400 italic text-center py-4">No resources uploaded yet.</p>
                        )}
                    </div>
                </div>
                {/* Template Tasks */}
                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-6 shadow-sm">
                    <h3 className="text-[12px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-4 flex items-center gap-2">
                        <ListTodo size={16} className="text-emerald-500" /> Session Tasks
                    </h3>
                    <div className="space-y-2">
                        {session.template_tasks && session.template_tasks.length > 0 ? (
                            session.template_tasks.map((task, idx) => (
                                <div key={idx} className="flex items-center justify-between p-3 bg-emerald-50/10 border border-emerald-500/10 rounded-xl">
                                    <div className="flex flex-col">
                                        <span className="text-[12px] font-bold text-[var(--text-main)]">{task.title}</span>
                                        <span className="text-[9px] font-black uppercase text-emerald-600">{task.points} Experience Points</span>
                                    </div>
                                    <CheckCircle size={16} className="text-emerald-500 opacity-30" />
                                </div>
                            ))
                        ) : (
                            <p className="text-[12px] text-gray-400 italic text-center py-4">No tasks assigned from template.</p>
                        )}
                    </div>
                </div>

                {/* Academic Assessments */}
                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-6 shadow-sm">
                    <h3 className="text-[12px] font-black text-[var(--text-muted)] uppercase tracking-widest mb-4 flex items-center gap-2">
                        <HelpCircle size={16} className="text-purple-500" /> Academic Assessments
                    </h3>
                    <div className="space-y-2">
                        {session.template_assessments && session.template_assessments.length > 0 ? (
                            session.template_assessments.map((asm, idx) => (
                                <div key={idx} className="flex items-center justify-between p-3 bg-purple-50/10 border border-purple-500/10 rounded-xl">
                                    <div className="flex flex-col">
                                        <span className="text-[12px] font-bold text-[var(--text-main)]">{asm.title}</span>
                                        <span className="text-[9px] font-black uppercase text-purple-600">
                                            {asm.passing_score}% Passing • {asm.questions?.length || 0} Questions
                                        </span>
                                    </div>
                                    <button className="px-3 py-1.5 bg-purple-500 text-white text-[9px] font-black uppercase rounded-lg hover:bg-purple-600 transition-colors shadow-sm">
                                        Take Quiz
                                    </button>
                                </div>
                            ))
                        ) : (
                            <p className="text-[12px] text-gray-400 italic text-center py-4">No assessments found from template.</p>
                        )}
                    </div>
                </div>
            </div>

            {/* Attendance Modal Overlay */}
            {showAttendanceModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowAttendanceModal(false)} />
                    <motion.div initial={{ opacity: 0, scale: 0.95, y: 20 }} animate={{ opacity: 1, scale: 1, y: 0 }} className="relative bg-[var(--bg-card)] border border-[var(--border)] w-full max-w-xl rounded-3xl shadow-2xl p-8 flex flex-col max-h-[85vh]">
                        <div className="flex items-center justify-between mb-6 border-b border-[var(--border)] pb-4">
                            <h2 className="text-xl font-black text-[var(--text-main)] flex items-center gap-2">
                                <UserCheck className="text-[var(--accent-indigo)]" /> Manage Attendance
                            </h2>
                            <button onClick={() => setShowAttendanceModal(false)} className="text-[var(--text-muted)] hover:text-red-500 transition-colors p-1 bg-[var(--input-bg)] rounded-lg">
                                <X size={20} />
                            </button>
                        </div>
                        
                        <div className="flex-1 overflow-y-auto no-scrollbar mb-6 border border-[var(--border)] rounded-2xl bg-[var(--input-bg)] p-2">
                            {attendees.length > 0 ? (
                                <div className="space-y-1">
                                    {attendees.map(u => {
                                        const uid = u._id || u.id;
                                        const isPresent = attendanceMarks[uid] || false;
                                        return (
                                            <div key={uid} className={`flex items-center justify-between p-3 rounded-xl border transition-all ${isPresent ? 'bg-emerald-50 border-emerald-200 shadow-sm' : 'bg-white border-transparent hover:border-gray-200'}`}>
                                                <div className="flex flex-col">
                                                    <span className={`text-[13px] font-black ${isPresent ? 'text-emerald-800' : 'text-[var(--text-main)]'}`}>{u.full_name || u.first_name || u.email}</span>
                                                    <span className="text-[10px] font-black text-[var(--text-muted)] uppercase">{u.department || 'No Dept'}</span>
                                                </div>
                                                <label className="flex items-center gap-2 cursor-pointer">
                                                    <span className={`text-[10px] font-black uppercase ${isPresent ? 'text-emerald-600' : 'text-gray-400'}`}>{isPresent ? 'Present' : 'Absent'}</span>
                                                    <input type="checkbox" checked={isPresent} onChange={e => setAttendanceMarks({...attendanceMarks, [uid]: e.target.checked})} className="w-5 h-5 accent-emerald-500 rounded-lg cursor-pointer" />
                                                </label>
                                            </div>
                                        );
                                    })}
                                </div>
                            ) : (
                                <div className="flex flex-col items-center justify-center p-10 text-[var(--text-muted)] opacity-70">
                                    <Users2 size={32} className="mb-2" />
                                    <p className="text-[12px] font-bold uppercase tracking-widest">No assigned attendees found.</p>
                                </div>
                            )}
                        </div>

                        <div className="flex justify-end gap-3 pt-4 border-t border-[var(--border)]">
                            <button onClick={() => setShowAttendanceModal(false)} className="px-6 py-2.5 bg-[var(--input-bg)] text-[var(--text-muted)] rounded-xl text-[12px] font-black border border-[var(--border)] hover:bg-gray-100 transition-colors">
                                Cancel
                            </button>
                            <button onClick={handleSaveAttendance} disabled={savingAttendance} className="px-6 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[12px] font-black hover:opacity-90 transition-all flex items-center gap-2 shadow-lg disabled:opacity-50">
                                {savingAttendance ? 'Saving...' : 'Save & Send Notifications'}
                            </button>
                        </div>
                    </motion.div>
                </div>
            )}

            {/* Upload Modal */}
            {uploadModalType && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setUploadModalType(null)} />
                    <motion.div initial={{ opacity: 0, scale: 0.95, y: 20 }} animate={{ opacity: 1, scale: 1, y: 0 }} className="relative bg-[var(--bg-card)] border border-[var(--border)] w-full max-w-md rounded-3xl shadow-2xl p-8 flex flex-col">
                        <div className="flex items-center justify-between mb-6 border-b border-[var(--border)] pb-4">
                            <h2 className="text-xl font-black text-[var(--text-main)] flex items-center gap-2">
                                {uploadModalType === 'resource' ? <FileUp className="text-amber-500" /> : <UploadCloud className="text-[var(--accent-indigo)]" />} 
                                Upload {uploadModalType === 'resource' ? 'Resource' : 'Content'}
                            </h2>
                            <button onClick={() => setUploadModalType(null)} className="text-[var(--text-muted)] hover:text-red-500 transition-colors p-1 bg-[var(--input-bg)] rounded-lg">
                                <X size={20} />
                            </button>
                        </div>

                        <div className="space-y-6 flex-1">
                            {uploadModalType === 'resource' && (
                                <div className="space-y-2">
                                    <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Resource Format</label>
                                    <select value={resourceType} onChange={e => setResourceType(e.target.value)}
                                        className="w-full bg-[var(--input-bg)] px-4 py-3 border border-[var(--border)] rounded-[16px] text-sm font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)] transition-all">
                                        <option value="video">Video</option>
                                        <option value="audio">Audio</option>
                                        <option value="pdf">PDF Document</option>
                                        <option value="excel">Excel Sheet</option>
                                        <option value="other">Other</option>
                                    </select>
                                </div>
                            )}

                            <div className="space-y-2">
                                <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Select File</label>
                                <input type="file" onChange={e => setUploadFile(e.target.files[0])}
                                    className="w-full bg-[var(--input-bg)] px-4 py-3 border border-dashed border-[var(--border)] rounded-[16px] text-sm font-bold text-[var(--text-muted)] outline-none focus:border-[var(--accent-indigo)] transition-all
                                        file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-[11px] file:font-black file:uppercase file:bg-[var(--accent-indigo-bg)] file:text-[var(--accent-indigo)] hover:file:opacity-90" />
                            </div>
                            
                            {uploading && (
                                <div className="space-y-2 pt-2">
                                    <div className="flex justify-between items-center text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">
                                        <span>Server Transfer Progress</span>
                                        <span>{uploadProgress}%</span>
                                    </div>
                                    <div className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-full h-2.5 overflow-hidden">
                                        <div className="bg-[var(--accent-indigo)] h-2.5 rounded-full transition-all duration-300 ease-out" style={{ width: `${uploadProgress}%` }}></div>
                                    </div>
                                    {uploadProgress === 100 && <p className="text-[10px] text-emerald-600 font-bold text-center mt-1">Finalizing with backend...</p>}
                                </div>
                            )}
                        </div>

                        <div className="flex justify-end gap-3 pt-6 border-t border-[var(--border)] mt-6">
                            <button onClick={() => setUploadModalType(null)} className="px-6 py-2.5 bg-[var(--input-bg)] text-[var(--text-muted)] rounded-xl text-[12px] font-black border border-[var(--border)] hover:bg-gray-100 transition-colors">
                                Cancel
                            </button>
                            <button onClick={handleUploadSubmit} disabled={uploading} className="px-6 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[12px] font-black hover:opacity-90 transition-all flex items-center gap-2 shadow-lg disabled:opacity-50">
                                {uploading ? 'Processing...' : 'Upload File'}
                            </button>
                        </div>
                    </motion.div>
                </div>
            )}
        </div>
    );
};

export default SessionDetails;
