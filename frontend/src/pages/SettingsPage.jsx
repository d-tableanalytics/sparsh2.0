import React, { useState, useEffect } from 'react';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';
import { ShieldCheck, Plus, Trash2, Mail, Save, ToggleLeft as ToggleOff, ToggleRight as ToggleOn, Settings, Building2, UserCircle2, Search, Info } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const SettingsPage = () => {
    const { user } = useAuth();
    const [config, setConfig] = useState({ allow_backdate: false, exception_users: [] });
    const [newEmail, setNewEmail] = useState('');
    const [loading, setLoading] = useState(true);
    
    // Notification Templates State
    const [activeTab, setActiveTab] = useState('backdate');
    const [templates, setTemplates] = useState([]);
    const [editingTemplate, setEditingTemplate] = useState(null);
    
    // Auto-detect scope: Client roles = company, Staff roles = staff
    const scope = user?.role?.toLowerCase().includes('client') ? 'company' : 'staff';
    
    const [companies, setCompanies] = useState([]);
    const [selectedCompanyId, setSelectedCompanyId] = useState('');
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [newTemplateForm, setNewTemplateForm] = useState({ name: '', slug: 'task_created_email' });
    const [searchQuery, setSearchQuery] = useState('');

    const templateVariables = {
        task: ['task_name', 'topic', 'task_category', 'critical_level', 'assigned_user', 'assigned_by', 'deadline', 'date', 'day', 'time', 'description', 'task_status', 'session_type'],
        event: ['session_type', 'topic', 'date', 'day', 'time', 'meeting_link', 'description', 'batch_name', 'quarter', 'event_title', 'event_datetime'],
        user: ['name', 'email', 'new_role', 'updated_by', 'login_url', 'password'],
        company: ['name', 'company_name', 'email', 'password', 'login_url'],
        attendance: ['user_name', 'event_title', 'event_time'],
        reminder: ['title', 'reminder_time', 'event_time', 'task_deadline', 'meeting_url', 'description'],
        general: ['name', 'email', 'role', 'login_url']
    };

    const getVarsForTemplate = (slug) => {
        if (slug.includes('task')) return templateVariables.task;
        if (slug.includes('event')) return templateVariables.event;
        if (slug.includes('user')) return templateVariables.user;
        if (slug.includes('company')) return templateVariables.company;
        if (slug.includes('attendance')) return templateVariables.attendance;
        if (slug.includes('reminder')) return templateVariables.reminder;
        return templateVariables.general;
    };

    useEffect(() => {
        const init = async () => {
            setLoading(true);
            try {
                if (user?.role === 'superadmin') {
                    const [settingsRes, companiesRes] = await Promise.all([
                        api.get('/settings/backdate-control'),
                        api.get('/company')
                    ]);
                    setConfig(settingsRes.data);
                    setCompanies(companiesRes.data);
                } else if (user?.role === 'clientadmin') {
                    setSelectedCompanyId(user.company_id);
                }
            } catch (err) { console.error(err); }
            finally { setLoading(false); }
        };
        init();
    }, [user]);

    useEffect(() => {
        if (activeTab === 'templates') fetchTemplates();
    }, [activeTab, scope, selectedCompanyId]);

    const fetchTemplates = async () => {
        try {
            let url = `/settings/templates?scope=${scope}`;
            if (scope === 'company' && selectedCompanyId) url += `&company_id=${selectedCompanyId}`;
            const res = await api.get(url);
            setTemplates(res.data);
        } catch (err) { console.error(err); }
    };

    const handleSave = async () => {
        try {
            await api.put('/settings/backdate-control', config);
            alert("Workflow settings deployed successfully.");
        } catch (error) { alert("Failed to deploy config."); }
    };

    const handleTemplateSave = async () => {
        try {
            await api.put(`/settings/templates/${editingTemplate._id}`, editingTemplate);
            alert("Template synchronized.");
            setEditingTemplate(null);
            fetchTemplates();
        } catch (err) { alert("Sync failed."); }
    };

    const deleteTemplate = async (id) => {
        if (!window.confirm("Permanently remove this template override?")) return;
        try {
            await api.delete(`/settings/templates/${id}`);
            fetchTemplates();
        } catch (err) { alert("Delete failed."); }
    };

    const handleCreateTemplate = async () => {
        try {
            const payload = {
                name: newTemplateForm.name,
                slug: newTemplateForm.slug,
                subject: `New ${newTemplateForm.name} Notification`,
                body: "Hello {{name}},\n\nAdd your template content here...",
                scope: scope,
                company_id: selectedCompanyId || null
            };
            await api.post('/settings/templates', payload);
            setShowCreateModal(false);
            setNewTemplateForm({ name: '', slug: 'task_created_email' });
            fetchTemplates();
        } catch (err) {
            alert("Failed to initialize template.");
        }
    };

    const insertVariable = (variable) => {
        if (!editingTemplate) return;
        const curPos = document.getElementById('template-editor')?.selectionStart || 0;
        const text = editingTemplate.body;
        const newText = text.slice(0, curPos) + `{{${variable}}}` + text.slice(curPos);
        setEditingTemplate({...editingTemplate, body: newText});
    };

    const filteredTemplates = templates.filter(t => 
        t.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
        t.slug.toLowerCase().includes(searchQuery.toLowerCase())
    );

    if (loading) return (
        <div className="h-screen flex items-center justify-center bg-[var(--bg-main)]">
            <div className="flex flex-col items-center gap-4">
                <div className="w-10 h-10 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"/>
                <p className="text-[9px] font-black text-[var(--accent-indigo)] uppercase tracking-[0.3em] animate-pulse">Initializing Comm Layer...</p>
            </div>
        </div>
    );

    return (
        <div className="flex flex-col h-[calc(100vh-56px)] bg-[var(--bg-main)] overflow-hidden">
            {/* Top Navigation - Secondary Navbar */}
            <div className="flex items-center gap-2 px-6 py-2.5 bg-[var(--bg-card)] border-b border-[var(--border)] overflow-x-auto no-scrollbar">
                <button 
                    onClick={() => setActiveTab('backdate')} 
                    className={`flex items-center gap-2 px-4 py-1.5 rounded-lg text-[11px] font-black transition-all shrink-0 uppercase tracking-widest ${activeTab === 'backdate' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
                    <ShieldCheck size={14}/> Security Rules
                </button>
                <button 
                    onClick={() => setActiveTab('templates')} 
                    className={`flex items-center gap-2 px-4 py-1.5 rounded-lg text-[11px] font-black transition-all shrink-0 uppercase tracking-widest ${activeTab === 'templates' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
                    <Mail size={14}/> Comms Templates
                </button>
                
                {activeTab === 'templates' && scope === 'company' && user?.role === 'superadmin' && (
                    <div className="flex items-center gap-2 ml-4 pl-4 border-l border-[var(--border)]">
                        <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest">Client</span>
                        <select value={selectedCompanyId} onChange={(e) => setSelectedCompanyId(e.target.value)}
                            className="bg-[var(--input-bg)] border border-[var(--border)] px-3 py-1 rounded-lg text-[10px] font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]">
                            <option value="">Select Company...</option>
                            {companies.map(c => <option key={c._id} value={c._id}>{c.name}</option>)}
                        </select>
                    </div>
                )}
            </div>

            {/* Main Workspace */}
            <div className="flex-1 overflow-hidden relative">
                {activeTab === 'backdate' ? (
                    <div className="p-4 max-w-5xl mx-auto w-full h-full overflow-y-auto no-scrollbar pb-20">
                        <div className="mb-6 flex items-center justify-between">
                            <div>
                                <h1 className="text-lg font-black text-[var(--text-main)] tracking-tight">System Permissions</h1>
                                <p className="text-[11px] font-medium text-[var(--text-muted)] italic">Global overrides and security exception logic.</p>
                            </div>
                            <button onClick={handleSave} className="bg-[var(--accent-indigo)] text-white px-6 py-2 rounded-xl font-black text-[11px] shadow-lg shadow-indigo-500/20 uppercase tracking-widest">
                                Save Config
                            </button>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {/* Toggle Block */}
                            <div className="p-6 bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] flex items-center justify-between shadow-sm">
                                <div className="space-y-1">
                                    <h2 className="text-[13px] font-black text-[var(--text-main)]">Allow History Creation</h2>
                                    <p className="text-[10px] font-medium text-[var(--text-muted)] max-w-sm">Enable session/task scheduling in the past.</p>
                                </div>
                                <div className="cursor-pointer" onClick={() => setConfig({...config, allow_backdate: !config.allow_backdate})}>
                                    {config.allow_backdate ? <ToggleOn size={32} className="text-[var(--accent-indigo)]" /> : <ToggleOff size={32} className="text-gray-200" />}
                                </div>
                            </div>

                            {/* Exception Block */}
                            <div className="p-6 bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] space-y-4 shadow-sm">
                                <div className="space-y-1">
                                    <h2 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-tight">Access Whitelist</h2>
                                    <p className="text-[10px] font-medium text-[var(--text-muted)]">Users with permanent backdate permission.</p>
                                </div>

                                <div className="flex gap-2">
                                    <input placeholder="Auth email..." value={newEmail} onChange={e => setNewEmail(e.target.value)}
                                        className="flex-1 bg-[var(--input-bg)] border border-[var(--border)] px-3 py-2 rounded-xl text-[12px] font-medium outline-none focus:bg-white focus:border-[var(--accent-indigo)]" />
                                    <button onClick={() => { if(newEmail) setConfig({...config, exception_users: [...config.exception_users, newEmail]}); setNewEmail(''); }}
                                        className="bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] px-4 rounded-xl font-black text-[10px] uppercase tracking-widest border border-[var(--accent-indigo-border)]">
                                        Authorize
                                    </button>
                                </div>

                                <div className="space-y-2 max-h-40 overflow-y-auto no-scrollbar">
                                    {config.exception_users.map(email => (
                                        <div key={email} className="flex items-center justify-between p-2 bg-[var(--input-bg)] rounded-xl group border border-transparent">
                                            <span className="text-[11px] font-bold text-[var(--text-main)]">{email}</span>
                                            <button onClick={() => setConfig({...config, exception_users: config.exception_users.filter(e => e !== email)})} className="text-gray-300 hover:text-red-500 transition-all"><Trash2 size={12}/></button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="flex h-full overflow-hidden">
                        {/* Compact Sidebar: Template Selection */}
                        <div className="w-64 border-r border-[var(--border)] flex flex-col bg-[var(--bg-card)]">
                            <div className="p-4 space-y-3 border-b border-[var(--border)]">
                                <div className="flex items-center justify-between">
                                    <h2 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest">Infrastructure</h2>
                                    <span className="px-1.5 py-0.5 rounded-md bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[8px] font-black uppercase">{scope}</span>
                                </div>
                                <div className="relative">
                                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" size={12}/>
                                    <input placeholder="Search..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                                        className="w-full pl-8 pr-3 py-1.5 bg-[var(--input-bg)] rounded-lg text-[11px] font-bold outline-none border border-transparent focus:border-[var(--border)]" />
                                </div>
                            </div>

                            <div className="flex-1 overflow-y-auto no-scrollbar p-2 space-y-1">
                                {filteredTemplates.length > 0 ? (
                                    filteredTemplates.map(t => (
                                        <button key={t._id} onClick={() => setEditingTemplate(t)}
                                            className={`w-full p-3 rounded-xl flex flex-col gap-0.5 text-left transition-all group border-2 ${editingTemplate?._id === t._id ? 'bg-white border-[var(--accent-indigo)] shadow-md' : 'bg-transparent border-transparent hover:bg-[var(--input-bg)]'}`}>
                                            <div className="flex items-center justify-between">
                                                <span className={`text-[11px] font-black transition-colors ${editingTemplate?._id === t._id ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-main)]'}`}>{t.name}</span>
                                                {scope === 'company' && user?.role === 'superadmin' && (
                                                    <Trash2 size={12} className="text-gray-200 hover:text-red-500 transition-all cursor-pointer" onClick={(e) => { e.stopPropagation(); deleteTemplate(t._id); }} />
                                                )}
                                            </div>
                                            <span className="text-[9px] font-medium text-[var(--text-muted)] uppercase italic">/{t.slug}</span>
                                        </button>
                                    ))
                                ) : (
                                    <div className="mt-10 text-center px-4">
                                        <p className="text-[9px] font-black text-gray-300 uppercase tracking-widest italic">Inventory Empty</p>
                                        <button onClick={() => setShowCreateModal(true)} className="mt-2 text-[10px] font-black text-[var(--accent-indigo)] hover:underline">+ New Template</button>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Dense Editor Workspace */}
                        <div className="flex-1 bg-[var(--bg-main)] overflow-y-auto p-6 no-scrollbar">
                            {editingTemplate ? (
                                <div className="max-w-6xl mx-auto space-y-4 pb-10">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center gap-3">
                                            <div className="w-10 h-10 rounded-xl bg-[var(--bg-card)] border border-[var(--border)] flex items-center justify-center text-[var(--accent-indigo)]">
                                                <Mail size={20}/>
                                            </div>
                                            <div>
                                                <h2 className="text-lg font-black text-[var(--text-main)] leading-tight">{editingTemplate.name}</h2>
                                                <div className="flex items-center gap-2 mt-0.5">
                                                    <span className="text-[8px] font-black px-1.5 py-0.5 rounded bg-gray-100 text-gray-400 uppercase tracking-tighter">/{editingTemplate.slug}</span>
                                                    <span className="text-[8px] font-black px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-400 uppercase tracking-tighter">{editingTemplate.scope}</span>
                                                </div>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <button onClick={() => setEditingTemplate(null)} className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest hover:text-red-500 mr-2 transition-all">Discard</button>
                                            <button onClick={handleTemplateSave} className="bg-[var(--accent-indigo)] text-white px-5 py-2 rounded-xl font-black text-[11px] shadow-lg shadow-indigo-500/20 flex items-center gap-2 hover:brightness-110 transition-all uppercase tracking-widest">
                                                <Save size={14}/> Sync Template
                                            </button>
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-1 xl:grid-cols-4 gap-6 items-start">
                                        {/* Main Editor */}
                                        <div className="xl:col-span-3 space-y-4">
                                            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-6 space-y-4 shadow-sm">
                                                <div className="space-y-1.5">
                                                    <label className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest px-2">Email Subject Header</label>
                                                    <input value={editingTemplate.subject} onChange={e => setEditingTemplate({...editingTemplate, subject: e.target.value})}
                                                        className="w-full bg-[var(--input-bg)] px-4 py-2.5 border border-[var(--border)] rounded-xl font-black text-[13px] text-[var(--text-main)] outline-none focus:bg-white focus:border-[var(--accent-indigo)] transition-all" />
                                                </div>

                                                <div className="space-y-1.5">
                                                    <div className="flex items-center justify-between px-2">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest">Canvas (HTML Supported)</label>
                                                        <span className="text-[8px] font-black text-[var(--accent-indigo)] flex items-center gap-1"><Info size={10}/> FULL HTML WRAPPER ACTIVE</span>
                                                    </div>
                                                    <textarea id="template-editor" rows={18} value={editingTemplate.body} onChange={e => setEditingTemplate({...editingTemplate, body: e.target.value})}
                                                        className="w-full bg-[var(--input-bg)] p-6 border border-[var(--border)] rounded-[20px] font-medium text-[13px] leading-relaxed text-[var(--text-main)] outline-none focus:bg-white focus:border-[var(--accent-indigo)] transition-all font-mono" />
                                                </div>
                                            </div>
                                        </div>

                                        {/* Compact Side Panel: Variables */}
                                        <div className="space-y-4">
                                            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-4 shadow-sm">
                                                <h3 className="text-[10px] font-black text-[var(--text-main)] uppercase tracking-widest border-b border-[var(--border)] pb-3 mb-3 flex items-center gap-2"> <Plus size={12}/> Placeholders</h3>
                                                <div className="flex flex-wrap gap-1.5">
                                                    {getVarsForTemplate(editingTemplate.slug).map(v => (
                                                        <button key={v} onClick={() => insertVariable(v)}
                                                            className="px-2 py-1 bg-[var(--input-bg)] hover:bg-[var(--accent-indigo-bg)] hover:text-[var(--accent-indigo)] rounded-lg border border-[var(--border)] text-[9px] font-black transition-all">
                                                            {"{{" + v + "}}"}
                                                        </button>
                                                    ))}
                                                </div>
                                                <div className="mt-6 p-3 bg-indigo-50/30 rounded-xl border border-indigo-100/50">
                                                     <p className="text-[9px] font-black text-indigo-400 uppercase tracking-tighter mb-1">Navigation Tip</p>
                                                     <p className="text-[9px] font-medium text-indigo-300 leading-tight">
                                                         Type {"{{"} in editor to see all placeholders. Click any tag to auto-inject.
                                                     </p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            ) : (
                                <div className="h-full flex flex-col items-center justify-center text-center opacity-30">
                                    <div className="w-20 h-20 border-2 border-dashed border-gray-400 rounded-full flex items-center justify-center">
                                        <Mail size={32} className="text-gray-400" />
                                    </div>
                                    <h3 className="mt-6 text-sm font-black text-[var(--text-main)] uppercase tracking-[0.2em]">Communication Hub</h3>
                                    <p className="text-[11px] font-medium text-[var(--text-muted)] mt-1">Select a core infrastructure from the left panel to begin editing.</p>
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>

            {/* Create Template Modal */}
            <AnimatePresence>
                {showCreateModal && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} 
                        className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
                        <motion.div initial={{ scale: 0.9, y: 20 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.9, y: 20 }}
                            className="bg-white w-full max-w-sm rounded-[32px] overflow-hidden shadow-2xl">
                            <div className="p-6 space-y-6">
                                <div className="flex items-center justify-between">
                                    <h2 className="text-[16px] font-black text-gray-900 uppercase italic">New Override</h2>
                                    <button onClick={() => setShowCreateModal(false)} className="text-gray-300 hover:text-black"> <Trash2 size={20} /> </button>
                                </div>

                                <div className="space-y-4">
                                    <div className="space-y-1">
                                        <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest px-1">Friendly Name</label>
                                        <input value={newTemplateForm.name} onChange={e => setNewTemplateForm({...newTemplateForm, name: e.target.value})} placeholder="Ex: Custom Session Email" className="w-full bg-gray-50 border border-gray-100 p-3 rounded-xl font-bold text-[12px] outline-none focus:border-indigo-500" />
                                    </div>
                                    <div className="space-y-1">
                                        <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest px-1">Infrastructure Slug</label>
                                        <select value={newTemplateForm.slug} onChange={e => setNewTemplateForm({...newTemplateForm, slug: e.target.value})} className="w-full bg-gray-50 border border-gray-100 p-3 rounded-xl font-bold text-[12px] outline-none">
                                            <optgroup label="Calendar">
                                                <option value="task_created_email">Task Created</option>
                                                <option value="task_updated_email">Task Updated</option>
                                                <option value="task_deleted_email">Task Deleted</option>
                                                <option value="event_created_email">Session Scheduled</option>
                                                <option value="event_updated_email">Session Rescheduled</option>
                                                <option value="event_deleted_email">Session Cancelled</option>
                                            </optgroup>
                                            <optgroup label="User Management">
                                                <option value="user_creation_email">User Created</option>
                                                <option value="user_edit_email">Profile Updated</option>
                                                <option value="user_access_control_change_email">Access Changed</option>
                                                <option value="company_registration_email">New Company</option>
                                            </optgroup>
                                            <optgroup label="Engagement">
                                                <option value="reminder_email">Event Reminder</option>
                                                <option value="attendance_thanks_email">Attendance Thanks</option>
                                                <option value="attendance_absent_email">Attendance Absent</option>
                                            </optgroup>
                                        </select>
                                    </div>
                                </div>

                                <button onClick={handleCreateTemplate} className="w-full bg-indigo-600 text-white py-4 rounded-2xl font-black text-[12px] uppercase tracking-widest shadow-xl shadow-indigo-100 hover:brightness-110 active:scale-95 transition-all">
                                    Initialize Infrastructure
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
};

export default SettingsPage;
