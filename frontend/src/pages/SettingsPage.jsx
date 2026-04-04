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
    const [scope, setScope] = useState('staff'); // 'staff' or 'company'
    const [companies, setCompanies] = useState([]);
    const [selectedCompanyId, setSelectedCompanyId] = useState('');
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');

    const templateVariables = {
        task: ['task_name', 'task_category', 'critical_level', 'assigned_user', 'assigned_by', 'deadline', 'description', 'task_status'],
        event: ['event_title', 'batch_name', 'quarter', 'session_strategy', 'meeting_url', 'event_datetime', 'instruction', 'created_by'],
        reminder: ['title', 'reminder_time', 'event_time', 'task_deadline', 'meeting_url', 'description'],
        general: ['name', 'email', 'role', 'login_url']
    };

    const getVarsForTemplate = (slug) => {
        if (slug.includes('task')) return templateVariables.task;
        if (slug.includes('event')) return templateVariables.event;
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
                    setScope('company');
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
                <div className="w-12 h-12 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"/>
                <p className="text-[10px] font-black text-[var(--accent-indigo)] uppercase tracking-[0.3em] animate-pulse">Initializing Comm Layer...</p>
            </div>
        </div>
    );

    return (
        <div className="flex h-[calc(100vh-56px)] bg-[var(--bg-main)] overflow-hidden">
            {/* Sidebar Controls */}
            <div className="w-64 bg-[var(--bg-card)] border-r border-[var(--border)] p-6 space-y-8 hidden lg:block">
                <div>
                    <h3 className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-[0.2em] mb-4">Core Systems</h3>
                    <div className="space-y-1">
                        <button onClick={() => setActiveTab('backdate')} 
                            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-[12px] font-black transition-all ${activeTab === 'backdate' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
                            <ShieldCheck size={16}/> Security Rules
                        </button>
                        <button onClick={() => setActiveTab('templates')} 
                            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-[12px] font-black transition-all ${activeTab === 'templates' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
                            <Mail size={16}/> Comms Templates
                        </button>
                    </div>
                </div>

                {activeTab === 'templates' && (
                    <div className="pt-8 border-t border-[var(--border)]">
                        <h3 className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-[0.2em] mb-4">Template Scope</h3>
                        <div className="bg-[var(--input-bg)] p-1 rounded-xl flex gap-1 mb-4">
                            <button onClick={() => setScope('staff')} className={`flex-1 py-2 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${scope === 'staff' ? 'bg-white shadow-sm text-[var(--accent-indigo)]' : 'text-[var(--text-muted)]'}`}>Staff</button>
                            <button onClick={() => setScope('company')} className={`flex-1 py-2 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${scope === 'company' ? 'bg-white shadow-sm text-[var(--accent-indigo)]' : 'text-[var(--text-muted)]'}`}>Company</button>
                        </div>

                        {scope === 'company' && user?.role === 'superadmin' && (
                            <div className="space-y-2">
                                <label className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest px-1">Select Company</label>
                                <select value={selectedCompanyId} onChange={(e) => setSelectedCompanyId(e.target.value)}
                                    className="w-full bg-[var(--input-bg)] border border-[var(--border)] p-2.5 rounded-xl text-[11px] font-bold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]">
                                    <option value="">Choose Client...</option>
                                    {companies.map(c => <option key={c._id} value={c._id}>{c.name}</option>)}
                                </select>
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Main Workspace */}
            <div className="flex-1 flex flex-col h-full bg-[var(--bg-main)]">
                {activeTab === 'backdate' ? (
                    <div className="p-8 max-w-4xl mx-auto w-full overflow-y-auto no-scrollbar">
                        <div className="mb-10 flex items-center justify-between">
                            <div>
                                <h1 className="text-2xl font-black text-[var(--text-main)] tracking-tight">System Permissions</h1>
                                <p className="text-[12px] font-medium text-[var(--text-muted)]">Configure global overrides and security exceptions.</p>
                            </div>
                            <button onClick={handleSave} className="bg-[var(--accent-indigo)] text-white px-8 py-3 rounded-2xl font-black text-[12px] shadow-xl shadow-indigo-500/30 hover:brightness-110 active:scale-95 transition-all uppercase tracking-widest">
                                Save Config
                            </button>
                        </div>

                        <div className="space-y-6">
                            {/* Toggle Block */}
                            <div className="p-8 bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] flex items-center justify-between shadow-sm hover:shadow-md transition-all">
                                <div className="space-y-1">
                                    <h2 className="text-[15px] font-black text-[var(--text-main)]">Allow History Creation</h2>
                                    <p className="text-[12px] font-medium text-[var(--text-muted)] max-w-lg">Enable this to allow users to schedule sessions or tasks in the past. Use with caution for data integrity.</p>
                                </div>
                                <div className="cursor-pointer p-1 rounded-full border border-[var(--border)] transition-all hover:bg-[var(--input-bg)]" onClick={() => setConfig({...config, allow_backdate: !config.allow_backdate})}>
                                    {config.allow_backdate ? <ToggleOn size={48} className="text-[var(--accent-indigo)]" /> : <ToggleOff size={48} className="text-gray-200" />}
                                </div>
                            </div>

                            {/* Exception Block */}
                            <div className="p-8 bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] space-y-8 shadow-sm">
                                <div className="space-y-1">
                                    <h2 className="text-[15px] font-black text-[var(--text-main)] uppercase tracking-tight">Access Whitelist</h2>
                                    <p className="text-[12px] font-medium text-[var(--text-muted)]">Users entered here will always have permission to create backdated entries, regardless of global toggle.</p>
                                </div>

                                <div className="flex gap-4">
                                    <div className="flex-1 relative">
                                        <Mail className="absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" size={16}/>
                                        <input placeholder="Enter authoritative email..." value={newEmail} onChange={e => setNewEmail(e.target.value)}
                                            className="w-full bg-[var(--input-bg)] border border-[var(--border)] pl-12 pr-4 py-3.5 rounded-2xl text-[14px] font-medium outline-none focus:bg-white focus:border-[var(--accent-indigo)] transition-all shadow-sm" />
                                    </div>
                                    <button onClick={() => { if(newEmail) setConfig({...config, exception_users: [...config.exception_users, newEmail]}); setNewEmail(''); }}
                                        className="bg-[var(--bg-card)] border-2 border-[var(--accent-indigo)] text-[var(--accent-indigo)] px-8 rounded-2xl font-black text-[11px] uppercase tracking-widest hover:bg-[var(--accent-indigo)] hover:text-white transition-all shadow-lg shadow-indigo-500/10">
                                        Authorize User
                                    </button>
                                </div>

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                    {config.exception_users.map(email => (
                                        <div key={email} className="flex items-center justify-between p-4 bg-[var(--input-bg)] rounded-2xl group border border-transparent hover:border-[var(--border)] transition-all">
                                            <span className="text-[13px] font-bold text-[var(--text-main)]">{email}</span>
                                            <button onClick={() => setConfig({...config, exception_users: config.exception_users.filter(e => e !== email)})} className="p-2 text-gray-300 hover:text-red-500 transition-all opacity-0 group-hover:opacity-100"><Trash2 size={16}/></button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="flex-1 flex overflow-hidden">
                        {/* Template Selector Panel */}
                        <div className="w-80 border-r border-[var(--border)] flex flex-col bg-[var(--bg-card)]">
                            <div className="p-6 space-y-4 border-b border-[var(--border)]">
                                <div className="flex items-center justify-between">
                                    <h2 className="text-[14px] font-black text-[var(--text-main)]">Templates</h2>
                                    <span className="px-2 py-0.5 rounded-md bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[9px] font-black uppercase">{scope}</span>
                                </div>
                                <div className="relative">
                                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" size={14}/>
                                    <input placeholder="Search slug..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                                        className="w-full pl-9 pr-4 py-2 bg-[var(--input-bg)] rounded-xl text-[11px] font-bold outline-none border border-transparent focus:border-[var(--border)]" />
                                </div>
                            </div>

                            <div className="flex-1 overflow-y-auto no-scrollbar p-4 space-y-2">
                                {filteredTemplates.length > 0 ? (
                                    filteredTemplates.map(t => (
                                        <button key={t._id} onClick={() => setEditingTemplate(t)}
                                            className={`w-full p-4 rounded-2xl flex flex-col gap-1 text-left transition-all group border-2 ${editingTemplate?._id === t._id ? 'bg-white border-[var(--accent-indigo)] shadow-lg' : 'bg-transparent border-transparent hover:bg-[var(--input-bg)]'}`}>
                                            <div className="flex items-center justify-between">
                                                <span className={`text-[12px] font-black transition-colors ${editingTemplate?._id === t._id ? 'text-[var(--accent-indigo)]' : 'text-[var(--text-main)]'}`}>{t.name}</span>
                                                {scope === 'company' && (
                                                    <Trash2 size={14} className="text-gray-200 hover:text-red-500 transition-all cursor-pointer" onClick={(e) => { e.stopPropagation(); deleteTemplate(t._id); }} />
                                                )}
                                            </div>
                                            <span className="text-[10px] font-medium text-[var(--text-muted)] group-hover:text-gray-400 transition-colors uppercase tracking-tight italic">/{t.slug}</span>
                                        </button>
                                    ))
                                ) : (
                                    <div className="p-8 text-center bg-gray-50 rounded-3xl border border-dashed border-gray-100">
                                        <p className="text-[10px] font-black text-gray-300 uppercase tracking-widest">No Templates Found</p>
                                        <button onClick={() => setShowCreateModal(true)} className="mt-4 text-[11px] font-black text-[var(--accent-indigo)] hover:underline">+ Create Override</button>
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Template Editor Workspace */}
                        <div className="flex-1 bg-[var(--bg-main)] overflow-y-auto p-10 no-scrollbar">
                            {editingTemplate ? (
                                <div className="max-w-4xl mx-auto space-y-8 pb-20">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center gap-4">
                                            <div className="w-12 h-12 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] flex items-center justify-center text-[var(--accent-indigo)]">
                                                <Mail size={24}/>
                                            </div>
                                            <div>
                                                <h2 className="text-xl font-black text-[var(--text-main)]">{editingTemplate.name}</h2>
                                                <div className="flex items-center gap-2 mt-1">
                                                    <span className="text-[9px] font-black px-2 py-0.5 rounded bg-gray-100 text-gray-500 uppercase">{editingTemplate.slug}</span>
                                                    <span className="text-[9px] font-black px-2 py-0.5 rounded bg-indigo-50 text-indigo-500 uppercase">{editingTemplate.scope}</span>
                                                </div>
                                            </div>
                                        </div>
                                        <button onClick={handleTemplateSave} className="bg-[var(--accent-indigo)] text-white px-8 py-3 rounded-2xl font-black text-[12px] shadow-xl shadow-indigo-500/30 flex items-center gap-2 hover:brightness-110 transition-all uppercase tracking-widest">
                                            <Save size={16}/> Deploy Changes
                                        </button>
                                    </div>

                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
                                        {/* Main Editor */}
                                        <div className="md:col-span-2 space-y-6">
                                            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-8 space-y-6 shadow-sm">
                                                <div className="space-y-2">
                                                    <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest px-2">Subject Header</label>
                                                    <input value={editingTemplate.subject} onChange={e => setEditingTemplate({...editingTemplate, subject: e.target.value})}
                                                        className="w-full bg-[var(--input-bg)] px-5 py-4 border border-[var(--border)] rounded-2xl font-black text-sm text-[var(--text-main)] outline-none focus:bg-white focus:border-[var(--accent-indigo)] transition-all" />
                                                </div>

                                                <div className="space-y-2">
                                                    <div className="flex items-center justify-between px-2">
                                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Email Body (Plain + Markers)</label>
                                                        <span className="text-[9px] font-bold text-[var(--accent-indigo)] flex items-center gap-1"><Info size={10}/> Supports Markdown</span>
                                                    </div>
                                                    <textarea id="template-editor" rows={14} value={editingTemplate.body} onChange={e => setEditingTemplate({...editingTemplate, body: e.target.value})}
                                                        className="w-full bg-[var(--input-bg)] p-8 border border-[var(--border)] rounded-[24px] font-medium text-[15px] leading-relaxed text-[var(--text-main)] outline-none focus:bg-white focus:border-[var(--accent-indigo)] transition-all" />
                                                </div>
                                            </div>
                                        </div>

                                        {/* Variables Panel */}
                                        <div className="space-y-6">
                                            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-6 shadow-sm sticky top-0">
                                                <h3 className="text-[11px] font-black text-[var(--text-main)] uppercase tracking-widest border-b border-[var(--border)] pb-4 mb-4">Available Variables</h3>
                                                <div className="flex flex-wrap gap-2">
                                                    {getVarsForTemplate(editingTemplate.slug).map(v => (
                                                        <button key={v} onClick={() => insertVariable(v)}
                                                            className="px-3 py-2 bg-[var(--input-bg)] hover:bg-[var(--accent-indigo-bg)] hover:text-[var(--accent-indigo)] rounded-xl border border-[var(--border)] text-[11px] font-black transition-all">
                                                            {"{{"+v+"}}"}
                                                        </button>
                                                    ))}
                                                </div>
                                                <div className="mt-8 p-4 bg-gray-50 rounded-2xl border border-gray-100 flex gap-3 italic">
                                                    <Info size={14} className="text-gray-400 shrink-0 mt-1"/>
                                                    <p className="text-[10px] font-medium text-gray-400 leading-normal">
                                                        Click any variable to insert it at your cursor's current position in the editor.
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            ) : (
                                <div className="h-full flex flex-col items-center justify-center text-center opacity-40">
                                    <motion.div animate={{ rotate: [0, 360] }} transition={{ repeat: Infinity, duration: 10, ease: 'linear' }}>
                                        <Mail size={120} className="text-gray-200 border-4 border-dashed border-gray-200 p-8 rounded-full" />
                                    </motion.div>
                                    <h3 className="mt-8 text-lg font-black text-[var(--text-main)] uppercase tracking-[0.2em]">Select Infrastructure</h3>
                                    <p className="text-sm font-medium text-[var(--text-muted)] mt-2">Choose a template from the left panel to begin customization.</p>
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
                            className="bg-white w-full max-w-lg rounded-[40px] overflow-hidden shadow-2xl">
                            <div className="p-10 space-y-8">
                                <div className="flex items-center justify-between">
                                    <h2 className="text-2xl font-black text-gray-900 tracking-tight italic uppercase">New Override</h2>
                                    <button onClick={() => setShowCreateModal(false)} className="p-2 hover:bg-gray-100 rounded-full transition-all"> <Trash2 size={24} className="text-gray-300" /> </button>
                                </div>

                                <div className="space-y-4">
                                    <div className="space-y-1">
                                        <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest px-1">Template Name</label>
                                        <input placeholder="Ex: Custom Task Welcome" className="w-full bg-gray-50 border border-gray-200 p-4 rounded-[20px] font-bold outline-none focus:border-indigo-500 transition-all" />
                                    </div>
                                    <div className="space-y-1">
                                        <label className="text-[10px] font-black text-gray-400 uppercase tracking-widest px-1">Internal Slug</label>
                                        <select className="w-full bg-gray-50 border border-gray-200 p-4 rounded-[20px] font-bold outline-none focus:border-indigo-500 transition-all">
                                            <option value="task_created_email">Task Created</option>
                                            <option value="task_updated_email">Task Updated</option>
                                            <option value="event_created_email">Session Scheduled</option>
                                            <option value="reminder_email">Event Reminder</option>
                                        </select>
                                    </div>
                                </div>

                                <button className="w-full bg-indigo-600 text-white py-5 rounded-[24px] font-black text-sm uppercase tracking-[0.2em] shadow-xl shadow-indigo-200 hover:brightness-110 active:scale-95 transition-all">
                                    Initialize Template
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
