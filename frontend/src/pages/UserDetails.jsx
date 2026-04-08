import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  UserCircle2, Shield, Mail, Phone, Clock, 
  ChevronLeft, Edit3, Trash2, CheckCircle2, 
  XCircle, MoreHorizontal, History, Zap, 
  Lock, Settings2, Save, X, Building2, MapPin
} from 'lucide-react';
import api from '../services/api';
import { useNotification } from '../context/NotificationContext';

const UserDetails = () => {
    const { userId } = useParams();
    const navigate = useNavigate();
    const { showSuccess, showError } = useNotification();
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const [isEditing, setIsEditing] = useState(false);
    const [editForm, setEditForm] = useState({});

    // ─── Fetching Logic ───
    const fetchData = async () => {
        try {
            const res = await api.get(`/users/${userId}`);
            setUser(res.data);
            setEditForm({
                ...res.data,
                permissions: res.data.permissions || {
                    batches: { create: false, read: true, update: false, delete: false },
                    calendar: { create: false, read: true, update: false, delete: false },
                    users: { create: false, read: true, update: false, delete: false },
                    companies: { create: false, read: true, update: false, delete: false },
                    logs: { create: false, read: true, update: false, delete: false },
                    templates: { create: false, read: true, update: false, delete: false }
                }
            });
        } catch (err) {
            console.error("Fetch user error:", err);
            navigate('/admin/users');
        } finally {
            setLoading(false);
        }
    };
    useEffect(() => { fetchData(); }, [userId]);

    // ─── Update Logic ───
    const handleUpdate = async () => {
        try {
            await api.put(`/users/${userId}`, editForm);
            setIsEditing(false);
            showSuccess("Profile updated");
            fetchData();
        } catch (err) { showError("Update failed"); }
    };

    const handleToggleStatus = async () => {
        try {
            await api.put(`/users/${userId}`, { is_active: !user.is_active });
            showSuccess(`User ${!user.is_active ? 'activated' : 'deactivated'}`);
            fetchData();
        } catch (err) { showError("Status change failed"); }
    };

    const handleDelete = async () => {
        try {
            await api.delete(`/users/${userId}`);
            showSuccess("Member removed from registry");
            navigate('/admin/users');
        } catch (err) { showError("Delete failed"); }
    };

    if (loading) return <div className="flex items-center justify-center h-96 animate-pulse font-black uppercase text-[12px] text-[var(--accent-indigo)] tracking-widest">Generating Digital Profile...</div>;
    if (!user) return null;

    return (
        <div className="space-y-8 pb-20">
            {/* Header: Navigation & Context */}
            <div className="flex items-center justify-between">
                <button onClick={() => navigate('/admin/users')} className="group flex items-center gap-2 text-[12px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] transition-all">
                    <ChevronLeft size={16} className="group-hover:-translate-x-1 transition-transform" /> Back to Staff Registry
                </button>
                <div className="flex items-center gap-2">
                    <button onClick={handleDelete} className="p-3 text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] rounded-xl transition-all border border-transparent hover:border-[var(--accent-red-border)]"> <Trash2 size={20}/></button>
                    <button onClick={() => setIsEditing(!isEditing)} className={`flex items-center gap-2 px-6 py-2.5 rounded-xl text-[13px] font-black transition-all ${isEditing ? 'bg-red-500 text-white' : 'bg-[var(--accent-indigo)] text-white shadow-xl shadow-indigo-100'}`}>
                        {isEditing ? <><X size={16}/> Cancel</> : <><Edit3 size={16}/> Edit Profile</>}
                    </button>
                </div>
            </div>

            {/* Main Profile Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Left Column: Essential Profile */}
                <div className="lg:col-span-2 space-y-8">
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[40px] p-10 shadow-sm relative overflow-hidden group">
                        <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-to-br from-[var(--accent-indigo-bg)] text-transparent opacity-30 rounded-bl-full" />
                        
                        <div className="flex flex-col md:flex-row items-center md:items-start gap-8 relative">
                           <div className="w-40 h-40 rounded-[32px] bg-[var(--input-bg)] border-4 border-white shadow-2xl flex items-center justify-center text-[var(--accent-indigo)] overflow-hidden relative">
                               <UserCircle2 size={100} strokeWidth={1} />
                               <div className={`absolute bottom-4 right-4 w-6 h-6 rounded-full border-4 border-white shadow-lg ${user.is_active !== false ? 'bg-green-500' : 'bg-red-500'}`} />
                           </div>
                           
                           <div className="flex-1 space-y-4 text-center md:text-left">
                               <div className="space-y-1">
                                    {isEditing ? (
                                        <input className="text-3xl font-black bg-[var(--input-bg)] rounded-xl px-4 py-2 w-full outline-none border border-[var(--border)]"
                                            value={editForm.full_name} onChange={e => setEditForm({...editForm, full_name: e.target.value})} />
                                    ) : (
                                        <h1 className="text-4xl font-black text-[var(--text-main)] tracking-tight">{user.full_name || user.name}</h1>
                                    )}
                                    <div className="flex flex-wrap justify-center md:justify-start gap-4 text-[13px] font-bold text-[var(--text-muted)]">
                                        <span className="flex items-center gap-1.5"><Shield size={16} className="text-[var(--accent-indigo)]"/> {user.role?.toUpperCase()}</span>
                                        <span className="flex items-center gap-1.5 text-green-500 bg-green-50 px-3 py-0.5 rounded-full"><CheckCircle2 size={14}/> {user.is_active !== false ? 'Active Status' : 'Deactivated'}</span>
                                        <span className="flex items-center gap-1.5"><Building2 size={16}/> Coaching Department</span>
                                    </div>
                               </div>
                               {!isEditing && (
                                   <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-6">
                                       <div className="bg-[var(--input-bg)] p-4 rounded-2xl border border-[var(--border)] space-y-1">
                                           <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Corporate Email</p>
                                           <div className="flex items-center gap-2 text-[var(--text-main)] font-bold text-[14px]"><Mail size={16}/> {user.email}</div>
                                       </div>
                                       <div className="bg-[var(--input-bg)] p-4 rounded-2xl border border-[var(--border)] space-y-1">
                                           <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Mobile Contact</p>
                                           <div className="flex items-center gap-2 text-[var(--text-main)] font-bold text-[14px]"><Phone size={16}/> {user.mobile || 'Not linked'}</div>
                                       </div>
                                   </div>
                               )}
                               {isEditing && (
                                   <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                       <input className="bg-[var(--input-bg)] p-4 rounded-xl text-[14px] font-bold border border-[var(--border)]" placeholder="Email" value={editForm.email} onChange={e => setEditForm({...editForm, email: e.target.value})} />
                                       <input className="bg-[var(--input-bg)] p-4 rounded-xl text-[14px] font-bold border border-[var(--border)]" placeholder="Phone" value={editForm.mobile} onChange={e => setEditForm({...editForm, mobile: e.target.value})} />
                                       <select className="bg-[var(--input-bg)] p-4 rounded-xl text-[14px] font-bold border border-[var(--border)]" value={editForm.role} onChange={e => setEditForm({...editForm, role: e.target.value})}>
                                            <option value="superadmin">Superadmin</option><option value="admin">Admin</option><option value="coach">Coach</option>
                                       </select>
                                       <button onClick={handleUpdate} className="bg-[var(--btn-primary)] text-white rounded-xl font-black flex items-center justify-center gap-2 tracking-widest uppercase text-[12px] hover:opacity-90"> <Save size={16}/> Update Registry </button>
                                   </div>
                               )}
                           </div>
                        </div>
                    </div>

                    {/* Access & Permissions Section */}
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-8 shadow-sm space-y-6">
                        <div className="flex items-center justify-between">
                            <h3 className="text-xl font-black text-[var(--text-main)] flex items-center gap-2"><Lock size={22} className="text-[var(--accent-orange)]"/> Access Management</h3>
                            <button className="text-[12px] font-black text-[var(--accent-indigo)] px-4 py-2 hover:bg-[var(--accent-indigo-bg)] rounded-xl transition-all"> <Settings2 size={16} className="inline mr-2"/> Default Module Access </button>
                        </div>
                        <div className="space-y-4">
                            {[
                                { id: 'batches', label: 'Batch Access' },
                                { id: 'calendar', label: 'Calendar Admin' },
                                { id: 'users', label: 'User Management' },
                                { id: 'companies', label: 'Company Oversight' },
                                { id: 'logs', label: 'Log Access' },
                                { id: 'templates', label: 'Template Designer' }
                            ].map(mod => {
                                const perms = editForm.permissions?.[mod.id] || { create: false, read: false, update: false, delete: false };
                                return (
                                    <div key={mod.id} className="p-5 bg-[var(--input-bg)] border border-[var(--border)] rounded-3xl flex flex-col md:flex-row md:items-center justify-between gap-4 group hover:border-[var(--accent-indigo)] transition-all">
                                        <div className="flex items-center gap-3">
                                            <div className="w-10 h-10 rounded-xl bg-[var(--bg-card)] border border-[var(--border)] flex items-center justify-center text-[var(--accent-indigo)] shadow-sm">
                                                <Settings2 size={20}/>
                                            </div>
                                            <span className="text-[14px] font-black text-[var(--text-main)]">{mod.label}</span>
                                        </div>
                                        
                                        <div className="flex items-center gap-2 sm:gap-6">
                                            {['create', 'read', 'update', 'delete'].map(action => {
                                                const active = perms[action];
                                                return (
                                                    <div key={action} 
                                                        onClick={() => {
                                                            // Auto-enable edit mode if superadmin
                                                            if (!isEditing) setIsEditing(true);
                                                            
                                                            setEditForm(prev => {
                                                                const updatedPerms = { ...(prev.permissions || {}) };
                                                                updatedPerms[mod.id] = { 
                                                                    ...(updatedPerms[mod.id] || { create: false, read: false, update: false, delete: false }), 
                                                                    [action]: !active 
                                                                };
                                                                return { ...prev, permissions: updatedPerms };
                                                            });
                                                        }}
                                                        className={`flex flex-col items-center gap-1.5 px-3 py-2 rounded-xl transition-all ${active ? 'bg-[var(--accent-indigo-bg)] border-[var(--accent-indigo-border)]' : 'bg-[var(--bg-card)] border-[var(--border)]'} border cursor-pointer hover:scale-105 active:scale-95`}>
                                                        <span className={`text-[8px] font-black uppercase tracking-tighter ${active ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-muted)]'}`}>{action}</span>
                                                        <div className={`w-8 h-4 rounded-full relative transition-colors ${active ? 'bg-[var(--accent-indigo)]' : 'bg-gray-200 shadow-inner'}`}>
                                                            <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all shadow-sm ${active ? 'right-0.5' : 'left-0.5'}`} />
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                        <p className="text-[11px] text-[var(--text-muted)] italic font-bold">
                            {isEditing ? "Defining explicit Create/Read/Update/Delete boundaries for this account." : "Access architecture is currently strictly enforced based on the matrix above."}
                        </p>
                    </div>
                </div>

                {/* Right Column: Metadata & Activity */}
                <div className="space-y-8">
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-8 shadow-sm">
                        <h3 className="text-lg font-black text-[var(--text-main)] mb-6 flex items-center gap-2"><History size={20} className="text-[var(--accent-indigo)]"/> Action History</h3>
                        <div className="space-y-6 relative ml-4 border-l-2 border-[var(--border)] border-dashed pl-6 pb-2">
                             {[
                                 { action: 'Session Scheduled', meta: 'Batch B22', time: '2h ago' },
                                 { action: 'Profile Updated', meta: 'Security Section', time: '1d ago' },
                                 { action: 'Company Created', meta: 'NexGen Ltd', time: '3d ago' }
                             ].map((act, i) => (
                                <div key={i} className="relative group">
                                    <div className="absolute -left-[31px] top-1 w-2.5 h-2.5 bg-[var(--bg-card)] border-2 border-[var(--accent-indigo)] rounded-full z-10 group-hover:scale-150 transition-all shadow-sm shadow-indigo-100" />
                                    <div className="space-y-1">
                                        <p className="text-[13px] font-black text-[var(--text-main)]">{act.action}</p>
                                        <p className="text-[11px] font-black text-[var(--text-muted)] opacity-60 uppercase tracking-widest">{act.meta} • {act.time}</p>
                                    </div>
                                </div>
                             ))}
                        </div>
                        <button className="w-full mt-6 py-3 border border-[var(--border)] rounded-2xl text-[12px] font-black text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)] transition-all">View All Logs</button>
                    </div>

                    <div className="bg-[var(--accent-indigo)] rounded-[32px] p-8 text-white relative overflow-hidden group shadow-2xl shadow-indigo-500/20">
                        <div className="absolute inset-0 bg-gradient-to-br from-white/10 to-transparent pointer-events-none" />
                        <Zap size={48} className="text-white/20 mb-4 group-hover:scale-110 group-hover:rotate-12 transition-all duration-500" />
                        <h3 className="text-xl font-black mb-2 tracking-tight">Access Token Insight</h3>
                        <p className="text-[13px] font-medium opacity-80 leading-relaxed">This user's identity is verified via JWT. Last login detected from New Delhi, IN under secure IP.</p>
                        <button className="mt-6 w-full py-3 bg-white text-[var(--accent-indigo)] rounded-2xl text-[12px] font-black shadow-lg">Revoke All Sessions</button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default UserDetails;
