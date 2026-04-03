import React, { useState, useEffect, useRef } from 'react';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import timeGridPlugin from '@fullcalendar/timegrid';
import listPlugin from '@fullcalendar/list';
import multiMonthPlugin from '@fullcalendar/multimonth';
import interactionPlugin from '@fullcalendar/interaction';
import { motion, AnimatePresence } from 'framer-motion';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';
import { 
  ChevronLeft, ChevronRight, Clock, X, UserCircle2, 
  Zap, ListChecks, Users2, Activity, CalendarDays, Building2, 
  Layers, Trash2, AlertCircle, Link, Check, UserPlus2, ShieldCheck,
  Edit2, CheckCircle, ArrowRightLeft, Ban, PlayCircle, MoreHorizontal,
  PlusCircle, LayoutGrid, Calendar as CalendarIcon, Briefcase, Video
} from 'lucide-react';

const CalendarPage = () => {
    const calendarRef = useRef(null);
    const { user } = useAuth();
    const [events, setEvents] = useState([]);
    const [loading, setLoading] = useState(true);
    const [viewName, setViewName] = useState('dayGridMonth');
    
    const [batches, setBatches] = useState([]);
    const [quarters, setQuarters] = useState([]);
    const [templates, setTemplates] = useState([]);
    const [allUsers, setAllUsers] = useState([]);
    
    const [showSummary, setShowSummary] = useState(false);
    const [summaryDate, setSummaryDate] = useState(null);
    const [dayEvents, setDayEvents] = useState([]);

    const [showModal, setShowModal] = useState(false);
    const [isEdit, setIsEdit] = useState(false);
    const [currentEventId, setCurrentEventId] = useState(null);

    const initialForm = {
        title: '', type: 'event', start: '', end: '', all_day: true,
        session_type: 'Core', priority: 'Normal', session_template_id: '',
        batch_id: '', quarter_id: '', status: 'schedule', meeting_link: '',
        assigned_departments: [], assigned_member_ids: [], coach_ids: [],
        additional_details: '', category: 'General', repeat: 'Does not repeat',
        repeat_end_date: '', repeat_interval: 1, assigned_to: 'myself', target_staff_id: ''
    };
    const [eventForm, setEventForm] = useState(initialForm);

    const departments = ['HOD', 'EA', 'MD', 'Implementor', 'HR', 'Other'];

    const fetchData = async () => {
        setLoading(true);
        try {
            const [evRes, bRes, qRes, tRes, uRes] = await Promise.all([
                api.get('/calendar/events'), api.get('/batches'),
                api.get('/quarters'), api.get('/session-templates'),
                api.get('/users')
            ]);
            setEvents(evRes.data.map(e => ({
                id: e.id, title: e.title, start: e.start, end: e.end,
                backgroundColor: 'transparent', borderColor: 'transparent',
                textColor: 'var(--text-main)', allDay: e.allDay,
                extendedProps: { ...e.extendedProps, id: e.id, dotColor: e.color || 'var(--accent-indigo)' }
            })));
            setBatches(bRes.data); setQuarters(qRes.data); setTemplates(tRes.data); setAllUsers(uRes.data);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    };
    useEffect(() => { fetchData(); }, []);

    const formatIST = (dateStr) => {
        if (!dateStr) return "";
        return new Date(dateStr).toLocaleString('en-IN', {
            timeZone: 'Asia/Kolkata', weekday: 'long', day: 'numeric', month: 'long',
            hour: '2-digit', minute: '2-digit', hour12: true
        });
    };

    // ─── Summary Logic ───
    const handleDateSelect = (info) => {
        const selectedDate = info.startStr;
        const eventsForDay = events.filter(e => {
            const eStart = e.start.split('T')[0];
            return eStart === selectedDate && !['batch', 'quarter'].includes(e.extendedProps.type);
        });
        setSummaryDate(selectedDate);
        setDayEvents(eventsForDay);
        setShowSummary(true);
    };

    const openCreateModal = (type) => {
        setIsEdit(false); setCurrentEventId(null);
        setEventForm({ ...initialForm, type, start: summaryDate, end: summaryDate });
        setShowModal(true);
    };

    const openEditModal = (ev) => {
        const props = ev.extendedProps;
        setIsEdit(true); setCurrentEventId(ev.id || ev._id);
        const startRaw = ev.start; const endRaw = ev.end || ev.start;
        setEventForm({
            ...initialForm, title: ev.title, type: props.type, start: startRaw, end: endRaw,
            all_day: ev.allDay, session_type: props.session_type, priority: props.priority || 'Normal',
            session_template_id: props.session_template_id, batch_id: props.batch_id,
            quarter_id: props.quarter_id, assigned_departments: props.assigned_departments || [],
            assigned_member_ids: props.assigned_member_ids || [], coach_ids: props.coach_ids || [],
            meeting_link: props.meeting_link, additional_details: props.additional_details,
            category: props.category || 'General',
            status: props.status || 'schedule',
            repeat: props.repeat || 'Does not repeat',
            repeat_end_date: props.repeat_end_date || '',
            repeat_interval: props.repeat_interval || 1,
            assigned_to: props.assigned_to || 'myself',
            target_staff_id: props.target_staff_id || ''
        });
        setShowModal(true);
    };

    const handleQuickAction = async (id, action) => {
        try {
            if (action === 'delete') { if(!confirm('Delete?')) return; await api.delete(`/calendar/events/${id}`); }
            else if (action === 'complete') await api.put(`/calendar/events/${id}`, { status: 'completed' });
            fetchData();
            // If in summary modal, refresh current day list
            if (showSummary) {
                const res = await api.get('/calendar/events'); // Fast refresh for summary
                const eventsForDay = res.data.filter(e => e.start.split('T')[0] === summaryDate && !['batch', 'quarter'].includes(e.type)).map(e => ({
                    id: e.id, title: e.title, start: e.start, end: e.end, extendedProps: { ...e.extendedProps, id: e.id }
                }));
                setDayEvents(eventsForDay);
            }
        } catch (err) { console.error(err); }
    };

    const handleSave = async () => {
        if (!eventForm.title) return alert("Add a title");
        try {
            if (isEdit) await api.put(`/calendar/events/${currentEventId}`, eventForm);
            else await api.post('/calendar/events', eventForm);
            fetchData(); setShowModal(false); setShowSummary(false); // Close both on save
        } catch (err) { console.error(err); }
    };

    const role = user?.role?.toLowerCase();
    const isStaff = ['superadmin', 'admin', 'coach'].includes(role);
    const isClient = ['clientadmin', 'clientdoer'].includes(role);

    const visibleMembers = allUsers.filter(u => {
        const uRole = u.role?.toLowerCase();
        const isL = ['learner', 'clientadmin', 'clientdoer'].includes(uRole);
        if (!isL) return false;
        
        if (isStaff) {
            return !eventForm.batch_id || u.batch_id === eventForm.batch_id;
        }
        return u.company_id === user?.company_id;
    });

    const handleDeptToggle = (dept) => {
        const currentDepts = [...eventForm.assigned_departments];
        const idx = currentDepts.indexOf(dept);
        let newDepts = []; let newMemberIds = [...eventForm.assigned_member_ids];
        
        const isMatch = (userDept, targetDept) => userDept?.toString().toUpperCase() === targetDept?.toUpperCase();

        if (idx > -1) {
            newDepts = currentDepts.filter(d => d !== dept);
            const membersToRemove = visibleMembers.filter(u => isMatch(u.department, dept)).map(u => u._id || u.id);
            newMemberIds = newMemberIds.filter(id => !membersToRemove.includes(id));
        } else {
            newDepts = [...currentDepts, dept];
            const membersToAdd = visibleMembers.filter(u => isMatch(u.department, dept)).map(u => u._id || u.id);
            newMemberIds = [...new Set([...newMemberIds, ...membersToAdd])];
        }
        setEventForm({ ...eventForm, assigned_departments: newDepts, assigned_member_ids: newMemberIds });
    };

    const renderEventTile = (ev) => {
        const s = ev.extendedProps.status;
        const type = ev.extendedProps.type;
        return (
            <motion.div key={ev.id} layout className={`group relative bg-[var(--input-bg)] rounded-[32px] border border-[var(--border)] p-6 hover:shadow-2xl hover:shadow-black/5 transition-all overflow-hidden ${s === 'completed' ? 'opacity-50' : ''}`}>
                <div className="absolute top-0 right-0 w-2 h-full" style={{ background: ev.extendedProps.dotColor }} />
                <div className="flex items-start justify-between mb-4">
                    <div className="space-y-1">
                        <div className="flex items-center gap-2 text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                            {type === 'task' ? <CheckCircle size={12} className="text-orange-500"/> : <Activity size={12} className="text-[var(--accent-indigo)]"/>}
                            {type} • {s || 'scheduled'}
                        </div>
                        <h4 className="text-[16px] font-black text-[var(--text-main)] group-hover:text-[var(--accent-indigo)] transition-colors pr-20">{ev.title}</h4>
                    </div>
                </div>
                <div className="flex items-center flex-wrap gap-4 text-[11px] font-bold text-[var(--text-muted)] mt-2">
                    <div className="flex items-center gap-1.5"> <Clock size={14}/> {new Date(ev.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true })} </div>
                    {ev.extendedProps.assigned_to === 'other' && (
                        <div className="flex items-center gap-1.5 text-[var(--accent-indigo)] bg-indigo-500/5 px-2 py-0.5 rounded-lg border border-indigo-500/10"> 
                            <UserCircle2 size={14}/> {allUsers.find(u => u._id === ev.extendedProps.target_staff_id)?.full_name || "Delegated Duty"} 
                        </div>
                    )}
                    {ev.extendedProps.meeting_link && <span className="flex items-center gap-1 text-[var(--accent-indigo)]"> <Video size={14}/> Linked </span>}
                </div>
                
                <div className="mt-8 flex items-center justify-between border-t border-dashed border-gray-200 pt-4">
                    <div className="flex items-center gap-2">
                        <button onClick={() => handleQuickAction(ev.id, 'complete')} className={`flex items-center gap-2 px-4 py-2 rounded-xl text-[11px] font-black transition-all ${s === 'completed' ? 'bg-green-100/10 text-green-600 border border-green-200' : 'bg-[var(--bg-main)] text-[var(--text-muted)] hover:bg-green-500 hover:text-white border border-[var(--border)]'}`}>
                            {s === 'completed' ? <Check size={14}/> : <CheckCircle size={14}/>} {s === 'completed' ? 'Finished' : 'Complete'}
                        </button>
                        <button onClick={() => openEditModal(ev)} className="p-2 bg-[var(--bg-main)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-indigo-500/10 rounded-xl transition-all"> <Edit2 size={16}/> </button>
                    </div>
                    <button onClick={() => handleQuickAction(ev.id, 'delete')} className="p-2 text-gray-300 hover:text-red-500 hover:bg-red-500/10 rounded-xl transition-all opacity-0 group-hover:opacity-100"> <Trash2 size={16}/> </button>
                </div>
            </motion.div>
        );
    };

    return (
        <div className="space-y-6 flex flex-col h-[calc(100vh-100px)]">
            <div className="flex items-center justify-between px-2">
                <div>
                   <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight">Organization Calendar</h1>
                   <p className="text-[12px] text-[var(--text-muted)] font-bold italic tracking-wide">Elite session governance & operational accountability engine.</p>
                </div>
                <div className="flex items-center gap-3">
                    <div className="flex items-center bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-1 shadow-sm">
                        {['dayGridMonth', 'timeGridWeek', 'timeGridDay', 'multiMonthYear'].map((view) => (
                            <button 
                                key={view}
                                onClick={() => {
                                    setViewName(view);
                                    calendarRef.current.getApi().changeView(view);
                                }}
                                className={`px-4 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest transition-all ${viewName === view ? 'bg-[var(--accent-indigo)] text-white shadow-lg shadow-indigo-100' : 'text-[var(--text-muted)] hover:text-[var(--text-main)] hover:bg-[var(--input-bg)]'}`}
                            >
                                {view === 'dayGridMonth' ? 'Month' : view === 'timeGridWeek' ? 'Week' : view === 'timeGridDay' ? 'Day' : 'Year'}
                            </button>
                        ))}
                    </div>

                    <button onClick={() => calendarRef.current.getApi().today()} className="h-10 px-4 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-main)] rounded-xl text-[12px] font-black hover:border-[var(--accent-indigo)]">Today</button>
                    <div className="flex items-center bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-1 shadow-sm">
                        <button onClick={() => calendarRef.current.getApi().prev()} className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-indigo)]"><ChevronLeft size={16} /></button>
                        <button onClick={() => calendarRef.current.getApi().next()} className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-indigo)]"><ChevronRight size={16} /></button>
                    </div>
                </div>
            </div>

            <div className="flex-1 bg-[var(--bg-card)] border border-[var(--border)] rounded-[40px] overflow-hidden shadow-2xl p-6 fc-theme-orlando relative">
                {loading && ( <div className="absolute inset-0 flex items-center justify-center bg-[var(--bg-card)]/80 backdrop-blur-sm z-[100]"> <div className="w-12 h-12 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"></div> </div> )}
                <FullCalendar ref={calendarRef} plugins={[dayGridPlugin, timeGridPlugin, listPlugin, multiMonthPlugin, interactionPlugin]}
                    initialView="dayGridMonth" headerToolbar={false} events={events} height="100%" selectable={true}
                    select={handleDateSelect} eventClick={(info) => {
                         const eStart = info.event.startStr.split('T')[0];
                         const eventsForDay = events.filter(e => e.start.split('T')[0] === eStart && !['batch', 'quarter'].includes(e.extendedProps.type));
                         setSummaryDate(eStart); setDayEvents(eventsForDay); setShowSummary(true);
                    }} 
                    dayMaxEvents={4} eventContent={(info) => {
                        const s = info.event.extendedProps.status;
                        return (
                            <div className={`flex items-center gap-1.5 px-2 py-0.5 max-w-full overflow-hidden group/ev rounded-md transition-all ${s === 'completed' ? 'opacity-40 grayscale line-through' : ''}`}>
                                <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: info.event.extendedProps.dotColor }}></div>
                                <span className="text-[10px] font-black truncate">{info.event.title}</span>
                            </div>
                        );
                    }}
                />
            </div>

            {/* ─── Day Summary Modal (Tile View) ─── */}
            <AnimatePresence>
                {showSummary && (
                    <div className="fixed inset-0 z-[190] flex items-center justify-center p-4">
                        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowSummary(false)} className="absolute inset-0 bg-black/40 backdrop-blur-[4px]" />
                        <motion.div initial={{ opacity: 0, scale: 0.9, y: 30 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.9, y: 30 }}
                            className="bg-[var(--bg-card)] w-full max-w-[860px] rounded-[48px] shadow-2xl relative overflow-hidden flex flex-col border border-[var(--border)] max-h-[90vh]"
                        >
                            <div className="flex px-10 py-8 items-center justify-between border-b border-[var(--border)] bg-[var(--table-header-bg)]">
                                <div className="flex items-center gap-4">
                                     <div className="p-3 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] rounded-2xl shadow-inner"> <CalendarIcon size={24}/> </div>
                                     <div>
                                        <h2 className="text-2xl font-black text-[var(--text-main)] tracking-tight">Day Summary</h2>
                                        <p className="text-[12px] font-black text-[var(--text-muted)] uppercase tracking-wider">{new Date(summaryDate).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</p>
                                     </div>
                                </div>
                                <button onClick={() => setShowSummary(false)} className="p-3 text-[var(--text-muted)] hover:bg-gray-100 rounded-2xl transition-all"> <X size={24} /> </button>
                            </div>

                            <div className="p-10 overflow-y-auto no-scrollbar space-y-12">
                                {/* ─── Section 1: Corporate Sessions ─── */}
                                <div className="space-y-6">
                                    <div className="flex items-center justify-between border-b border-[var(--border)] pb-4">
                                        <h3 className="text-[14px] font-black text-[var(--accent-indigo)] uppercase tracking-[0.2em] flex items-center gap-2"> <Activity size={18}/> Corporate Sessions ({dayEvents.filter(e => e.extendedProps.type === 'event').length}) </h3>
                                        <button onClick={() => openCreateModal('event')} className="flex items-center gap-2 px-5 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black shadow-lg shadow-indigo-200/40 hover:opacity-90 transition-all"> <PlusCircle size={14}/> NEW SESSION </button>
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                        {dayEvents.filter(e => e.extendedProps.type === 'event').map(ev => renderEventTile(ev))}
                                        {dayEvents.filter(e => e.extendedProps.type === 'event').length === 0 && (
                                            <div className="col-span-full py-10 flex flex-col items-center justify-center bg-gray-50/50 rounded-[32px] border border-dashed border-gray-200 opacity-50">
                                                <p className="text-[11px] font-black text-gray-400 uppercase">No sessions scheduled.</p>
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {/* ─── Section 2: Strategic Tasks ─── */}
                                <div className="space-y-6">
                                    <div className="flex items-center justify-between border-b border-[var(--border)] pb-4">
                                        <h3 className="text-[14px] font-black text-orange-500 uppercase tracking-[0.2em] flex items-center gap-2"> <CheckCircle size={18}/> Strategic Tasks ({dayEvents.filter(e => e.extendedProps.type === 'task').length}) </h3>
                                        <button onClick={() => openCreateModal('task')} className="flex items-center gap-2 px-5 py-2.5 bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] rounded-xl text-[11px] font-black hover:bg-gray-100 transition-all"> <PlusCircle size={14}/> ADD TASK </button>
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                        {dayEvents.filter(e => e.extendedProps.type === 'task').map(ev => renderEventTile(ev))}
                                        {dayEvents.filter(e => e.extendedProps.type === 'task').length === 0 && (
                                            <div className="col-span-full py-10 flex flex-col items-center justify-center bg-gray-50/50 rounded-[32px] border border-dashed border-gray-200 opacity-50">
                                                <p className="text-[11px] font-black text-gray-400 uppercase">No tasks listed.</p>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>

                            <div className="p-10 border-t border-[var(--border)] bg-[var(--table-header-bg)] flex items-center justify-center gap-4">
                                <Zap size={20} className="text-orange-400" />
                                <p className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest">Select a tile above to modify or confirm the session architect.</p>
                            </div>
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>

            {/* ─── Event Architect Modal (Create/Edit) ─── */}
            <AnimatePresence>
                {showModal && (
                    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
                        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setShowModal(false)} className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
                        <motion.div initial={{ opacity: 0, scale: 0.9, y: 30 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.9, y: 30 }}
                            className="bg-[var(--bg-card)] w-full max-w-[820px] rounded-[40px] shadow-[0_50px_100px_-20px_rgba(0,0,0,0.5)] relative overflow-hidden flex flex-col border border-[var(--border)] max-h-[95vh]"
                        >
                            <div className="flex px-10 py-8 items-center justify-between border-b border-[var(--border)] bg-[var(--bg-main)]">
                                <div className="flex items-center gap-3">
                                   <div className={`w-3 h-3 rounded-full animate-pulse ${eventForm.status === 'completed' ? 'bg-green-500' : 'bg-indigo-500'}`} />
                                   <span className="text-[11px] font-black uppercase tracking-widest text-[var(--accent-indigo)]"> {isEdit ? `Edit Operation [${eventForm.status}]` : 'Architect New Session'} </span>
                                </div>
                                <div className="flex items-center gap-3">
                                    {isEdit && (
                                        <div className="flex items-center bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl p-1 shadow-inner">
                                             <button onClick={() => setEventForm({...eventForm, status: 'completed'})} className={`p-3 rounded-xl transition-all ${eventForm.status === 'completed' ? 'bg-green-500 text-white shadow-lg' : 'text-gray-400 hover:text-green-500'}`}> <CheckCircle size={20}/> </button>
                                             <button onClick={() => setEventForm({...eventForm, status: 'canceled'})} className={`p-3 rounded-xl transition-all ${eventForm.status === 'canceled' ? 'bg-red-500 text-white shadow-lg' : 'text-gray-400 hover:text-red-500'}`}> <Ban size={20}/> </button>
                                             <button onClick={() => handleQuickAction(currentEventId, 'delete')} className="p-3 text-gray-400 hover:text-red-500 hover:bg-red-500/10 rounded-xl"> <Trash2 size={20}/> </button>
                                        </div>
                                    )}
                                    <button onClick={() => setShowModal(false)} className="p-3 text-[var(--text-muted)] hover:bg-gray-800 rounded-full transition-all"> <X size={24} /> </button>
                                </div>
                            </div>

                            <div className="p-10 overflow-y-auto no-scrollbar space-y-12">
                                <div className="space-y-4">
                                    <input autoFocus placeholder={eventForm.type === 'task' ? "Task Name" : "Session Title"} className="w-full text-4xl font-black bg-transparent border-b-2 border-dashed border-gray-200 focus:border-[var(--accent-indigo)] outline-none pb-3 text-[var(--text-main)] transition-colors" 
                                        value={eventForm.title} onChange={e => setEventForm({...eventForm, title: e.target.value})} />
                                    
                                    <div className="flex flex-wrap items-center gap-4">
                                        <div className="flex items-center gap-2 px-3 py-1.5 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[10px] font-black uppercase tracking-widest rounded-lg"> <Clock size={14}/> IST • {formatIST(eventForm.start)} </div>
                                        {isEdit && (
                                            <div className="flex items-center gap-1.5">
                                                 <label className="text-[10px] font-black text-gray-400 uppercase">Operational Status:</label>
                                                 <select value={eventForm.status} onChange={e => setEventForm({...eventForm, status: e.target.value})}
                                                    className="bg-[var(--input-bg)] border border-[var(--border)] rounded-lg px-3 py-1 text-[11px] font-black text-[var(--accent-indigo)] uppercase outline-none">
                                                    <option value="schedule">Scheduled</option>
                                                    <option value="reschedule">Rescheduled</option>
                                                    <option value="canceled">Canceled</option>
                                                    <option value="completed">Completed</option>
                                                 </select>
                                            </div>
                                        )}
                                    </div>
                                </div>

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
                                    {isStaff ? (
                                        eventForm.type === 'event' ? (
                                            <>
                                                <div className="space-y-6">
                                                    <div className="space-y-1.5">
                                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase flex items-center gap-2"><Zap size={14}/> Session Strategy</label>
                                                        <select className="w-full px-4 py-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl text-[13px] font-bold" value={eventForm.session_type} onChange={e => setEventForm({...eventForm, session_type: e.target.value})}><option>Core</option><option>Support</option></select>
                                                    </div>
                                                    <div className="space-y-1.5">
                                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase flex items-center gap-2"><Building2 size={14}/> Organizational Batch</label>
                                                        <select className="w-full px-4 py-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl text-[13px] font-bold" value={eventForm.batch_id} onChange={e => setEventForm({...eventForm, batch_id: e.target.value})}><option value="">Select Batch</option>{batches.map(b => <option key={b._id} value={b._id}>{b.name}</option>)}</select>
                                                    </div>
                                                    <div className="space-y-1.5">
                                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase flex items-center gap-2"><Layers size={14}/> Quarter Selection</label>
                                                        <select className="w-full px-4 py-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl text-[13px] font-bold" value={eventForm.quarter_id} onChange={e => setEventForm({...eventForm, quarter_id: e.target.value})}><option value="">Select Quarter</option>{quarters.map(q => <option key={q._id} value={q._id}>{q.name}</option>)}</select>
                                                    </div>
                                                </div>
                                                <div className="space-y-6">
                                                    <div className="space-y-1.5">
                                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase flex items-center gap-2"><LayoutGrid size={14}/> Session Template</label>
                                                        <select className="w-full px-4 py-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl text-[13px] font-bold" value={eventForm.session_template_id} onChange={e => setEventForm({...eventForm, session_template_id: e.target.value})}><option value="">None / Custom</option>{templates.map(t => <option key={t._id} value={t._id}>{t.title}</option>)}</select>
                                                    </div>
                                                    <div className="space-y-1.5">
                                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase flex items-center gap-2"><Link size={14}/> Meeting URL</label>
                                                        <input placeholder="Zoom / Meet URL" className="w-full px-4 py-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl text-[13px] font-bold" value={eventForm.meeting_link} onChange={e => setEventForm({...eventForm, meeting_link: e.target.value})} />
                                                    </div>
                                                    <div className="space-y-2">
                                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase flex items-center gap-2"><UserPlus2 size={14}/> Coaching Team</label>
                                                        <div className="flex flex-wrap gap-1.5 p-2 bg-[var(--input-bg)] rounded-2xl border border-[var(--border)] min-h-[50px]">
                                                            {allUsers.filter(u => ['superadmin', 'admin', 'coach'].includes(u.role?.toLowerCase())).map(c => (
                                                                <div key={c._id} onClick={() => {
                                                                    const current = [...eventForm.coach_ids];
                                                                    setEventForm({...eventForm, coach_ids: current.includes(c._id) ? current.filter(id => id !== c._id) : [...current, c._id]})
                                                                }}
                                                                    className={`px-3 py-1.5 rounded-lg text-[11px] font-black cursor-pointer transition-all flex items-center gap-2 ${eventForm.coach_ids?.includes(c._id) ? 'bg-[var(--accent-indigo)] text-white shadow-lg' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)]'}`}>
                                                                    {c.full_name || c.name}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                </div>
                                            </>
                                        ) : (
                                            <>
                                                <div className="space-y-6">
                                                    <div className="space-y-1.5"><label className="text-[10px] font-black text-[var(--text-muted)] uppercase flex items-center gap-2"><Briefcase size={14}/> Task Category</label>
                                                        <select className="w-full px-4 py-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl" value={eventForm.category} onChange={e => setEventForm({...eventForm, category: e.target.value})}><option>General</option><option>Feedback</option><option>Administrative</option></select>
                                                    </div>
                                                    <div className="space-y-1.5"><label className="text-[10px] font-black text-[var(--text-muted)] uppercase">Strategic Repetition</label>
                                                        <div className="space-y-3">
                                                            <select className="w-full px-4 py-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl" value={eventForm.repeat} onChange={e => setEventForm({...eventForm, repeat: e.target.value})}><option>Does not repeat</option><option>Daily</option><option>Weekly</option><option>Monthly</option><option value="periodic">Periodically</option></select>
                                                            {eventForm.repeat !== 'Does not repeat' && (
                                                                <div className="flex gap-2">
                                                                    <input type="date" className="flex-1 px-4 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold text-white" value={eventForm.repeat_end_date} onChange={e => setEventForm({...eventForm, repeat_end_date: e.target.value})} />
                                                                    {eventForm.repeat === 'periodic' && <input type="number" placeholder="Days" className="w-[80px] px-4 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold text-white" value={eventForm.repeat_interval} onChange={e => setEventForm({...eventForm, repeat_interval: e.target.value})} />}
                                                                </div>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                                <div className="space-y-6">
                                                    <div className="space-y-1.5"><label className="text-[10px] font-black text-[var(--text-muted)] uppercase">Criticality Level</label>
                                                        <div className="flex gap-2 p-1 bg-[var(--input-bg)] rounded-xl border border-[var(--border)]">{['Normal', 'High', 'Urgent'].map(p => <button key={p} onClick={() => setEventForm({...eventForm, priority: p})} className={`flex-1 py-2 rounded-lg text-[10px] font-black transition-all ${eventForm.priority === p ? 'bg-[var(--accent-indigo)] text-white shadow-lg' : 'text-[var(--text-muted)] hover:text-white'}`}>{p.toUpperCase()}</button>)}</div>
                                                    </div>
                                                    <div className="space-y-1.5"><label className="text-[10px] font-black text-[var(--text-muted)] uppercase">Assignment Delegation</label>
                                                        <div className="space-y-3">
                                                            <div className="flex gap-2 p-1 bg-[var(--input-bg)] rounded-xl border border-[var(--border)]"><button onClick={() => setEventForm({...eventForm, assigned_to: 'myself'})} className={`flex-1 py-1.5 rounded-lg text-[10px] font-black ${eventForm.assigned_to === 'myself' ? 'bg-[var(--accent-indigo)] text-white' : 'text-gray-500'}`}>MYSELF</button><button onClick={() => setEventForm({...eventForm, assigned_to: 'other'})} className={`flex-1 py-1.5 rounded-lg text-[10px] font-black ${eventForm.assigned_to === 'other' ? 'bg-[var(--accent-indigo)] text-white' : 'text-gray-500'}`}>OTHER</button></div>
                                                            {eventForm.assigned_to === 'other' && <select className="w-full px-4 py-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl text-[12px] font-bold text-white" value={eventForm.target_staff_id} onChange={e => setEventForm({...eventForm, target_staff_id: e.target.value})}><option value="">Select Professional</option>{allUsers.filter(u => ['superadmin', 'admin', 'coach'].includes(u.role?.toLowerCase())).map(s => <option key={s._id} value={s._id}>{s.full_name || s.name}</option>)}</select>}
                                                        </div>
                                                    </div>
                                                </div>
                                            </>
                                        )
                                    ) : (
                                        <div className="md:col-span-2 space-y-6">
                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
                                                <div className="space-y-1.5">
                                                    <label className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-2"><Link size={14}/> Secure Meeting Link</label>
                                                    <input placeholder="Zoom / Meet URL" className="w-full px-6 py-4 bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl text-[14px] font-bold shadow-inner focus:border-[var(--accent-indigo)] transition-all" value={eventForm.meeting_link} onChange={e => setEventForm({...eventForm, meeting_link: e.target.value})} />
                                                </div>
                                                <div className="space-y-1.5">
                                                     <label className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-2"><CalendarIcon size={14}/> Operation Horizon</label>
                                                     <div className="px-6 py-4 bg-[var(--input-bg)] border border-[var(--border)] rounded-2xl text-[14px] font-bold text-[var(--accent-indigo)]"> {new Date(eventForm.start).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })} </div>
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>

                                <div className="space-y-6 p-8 bg-[var(--input-bg)] rounded-[40px] border border-[var(--border)] shadow-sm">
                                    <div className="space-y-4">
                                        <label className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-2"> 
                                            <Users2 size={16}/> {isStaff ? `Active Assignment: ${eventForm.assigned_departments.join(", ") || "None"}` : "Participant Management"} 
                                        </label>
                                        {isStaff && (
                                            <div className="flex flex-wrap gap-2">
                                                {departments.map(dept => (
                                                    <button key={dept} onClick={() => handleDeptToggle(dept)}
                                                        className={`px-6 py-2.5 rounded-xl text-[12px] font-black border transition-all ${eventForm.assigned_departments.includes(dept) ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)] shadow-xl shadow-indigo-200' : 'bg-white text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--accent-indigo)]'}`}>
                                                        {dept}
                                                    </button>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                    <div className="flex flex-wrap gap-1.5 p-3 min-h-[60px] max-h-[180px] overflow-y-auto no-scrollbar">
                                        {visibleMembers.filter(u => !isStaff || eventForm.assigned_departments.some(dept => u.department?.toString().toUpperCase() === dept.toUpperCase())).map(m => (
                                            <div key={m._id} onClick={() => {
                                                const ids = [...eventForm.assigned_member_ids];
                                                setEventForm({...eventForm, assigned_member_ids: ids.includes(m._id) ? ids.filter(id => id !== m._id) : [...ids, m._id]})
                                            }}
                                                className={`px-3 py-2 rounded-xl text-[11px] font-bold cursor-pointer transition-all flex items-center gap-2 ${eventForm.assigned_member_ids?.includes(m._id) ? 'bg-[var(--accent-indigo)] text-white shadow-lg border border-[var(--accent-indigo-border)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] opacity-50 border border-dashed border-gray-500'}`}>
                                                {m.full_name || m.name} <X size={10} className={`${eventForm.assigned_member_ids?.includes(m._id) ? 'text-red-200' : 'block'}`}/>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                <div className="space-y-6">
                                     <div className="flex items-center gap-6 flex-wrap">
                                         <div className="flex items-center gap-3 bg-[var(--input-bg)] px-6 py-3.5 rounded-2xl border border-[var(--border)]">
                                             <CalendarDays size={22} className="text-[var(--accent-indigo)]" />
                                             <span className="text-[15px] font-black">{new Date(eventForm.start).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}</span>
                                         </div>
                                         <label className="flex items-center gap-4 cursor-pointer bg-[var(--input-bg)] border border-[var(--border)] px-6 py-3.5 rounded-2xl shadow-inner group">
                                            <input type="checkbox" checked={eventForm.all_day} onChange={e => setEventForm({...eventForm, all_day: e.target.checked})} className="w-5 h-5 accent-[var(--accent-indigo)]" />
                                            <span className="text-[13px] font-black uppercase text-[var(--text-muted)] group-hover:text-white transition-colors">Full Day Block</span>
                                         </label>
                                         {!eventForm.all_day && (
                                             <div className="flex items-center gap-3 bg-[var(--accent-indigo-bg)] p-1.5 rounded-2xl border border-[var(--border)] shadow-inner">
                                                <input type="time" className="bg-transparent px-4 py-2 text-[14px] font-black text-[var(--accent-indigo)] outline-none" 
                                                    value={new Date(eventForm.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}
                                                    onChange={(e) => {
                                                        const [hours, minutes] = e.target.value.split(':');
                                                        const newDate = new Date(eventForm.start);
                                                        newDate.setHours(parseInt(hours), parseInt(minutes));
                                                        setEventForm({ ...eventForm, start: newDate.toISOString() });
                                                    }}
                                                />
                                                <ArrowRightLeft size={14} className="text-[var(--accent-indigo)] opacity-40"/>
                                                <input type="time" className="bg-transparent px-4 py-2 text-[14px] font-black text-[var(--accent-indigo)] outline-none" 
                                                    value={new Date(eventForm.end).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}
                                                    onChange={(e) => {
                                                        const [hours, minutes] = e.target.value.split(':');
                                                        const newDate = new Date(eventForm.end);
                                                        newDate.setHours(parseInt(hours), parseInt(minutes));
                                                        setEventForm({ ...eventForm, end: newDate.toISOString() });
                                                    }}
                                                />
                                             </div>
                                         )}
                                     </div>
                                     <textarea placeholder={eventForm.type === 'task' ? "Task description or specific action items..." : "Instructions for AI (Checker) or session curriculum notes..."} rows={4} className="w-full bg-[var(--input-bg)] p-6 rounded-[32px] text-[14px] font-medium border border-[var(--border)] outline-none focus:bg-white transition-all shadow-inner"
                                            value={eventForm.additional_details} onChange={e => setEventForm({...eventForm, additional_details: e.target.value})} />
                                </div>
                            </div>

                            <div className="p-10 border-t border-[var(--border)] flex justify-between items-center bg-[var(--table-header-bg)]">
                                <div className="flex items-center gap-4">
                                    <ShieldCheck size={28} className="text-[var(--accent-indigo)] opacity-30" />
                                    <div className="space-y-0.5">
                                        <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Digital Authorization</p>
                                        <p className="text-[11px] font-bold text-gray-400 italic">Changes will sync to attendee calendars instantly.</p>
                                    </div>
                                </div>
                                <button onClick={handleSave} className="bg-[var(--btn-primary)] text-white px-24 py-4.5 rounded-[22px] text-[14px] font-black shadow-2xl shadow-indigo-500/40 hover:scale-[1.02] active:scale-[0.98] transition-all tracking-[0.1em] uppercase">
                                    {isEdit ? 'Authorize Updates' : 'Schedule Session'}
                                </button>
                            </div>
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>
        </div>
    );
};

export default CalendarPage;
