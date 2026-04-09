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
import { useNotification } from '../context/NotificationContext';
import { useMemo } from 'react';

import {
    ChevronLeft, ChevronRight, Clock, X, UserCircle2,
    Zap, ListChecks, Users2, Activity, CalendarDays, Building2,
    Layers, Trash2, AlertCircle, Link, Check, UserPlus2, ShieldCheck,
    Edit2, CheckCircle, ArrowRightLeft, Ban, PlayCircle, MoreHorizontal,
    PlusCircle, LayoutGrid, Calendar as CalendarIcon, Briefcase, Video, Bell,
    Eye, Lock
} from 'lucide-react';
import ReminderModal from '../components/calendar/ReminderModal';

const CalendarPage = () => {
    const calendarRef = useRef(null);
    const { user } = useAuth();
    const { showSuccess, showError } = useNotification();
    const [events, setEvents] = useState([]);
    const [loading, setLoading] = useState(true);
    const [viewName, setViewName] = useState('dayGridMonth');
    const [viewMode, setViewMode] = useState('personal'); 

    const [batches, setBatches] = useState([]);
    const [quarters, setQuarters] = useState([]);
    const [templates, setTemplates] = useState([]);
    const [allUsers, setAllUsers] = useState([]);
    const [statFilter, setStatFilter] = useState(null);
    const [backdateSettings, setBackdateSettings] = useState({ allow_backdate: false, exception_users: [] });
    const [gptProjects, setGptProjects] = useState([]);

    const [showSummary, setShowSummary] = useState(false);
    const [summaryDate, setSummaryDate] = useState(null);
    const [dayEvents, setDayEvents] = useState([]);
    const [currentViewDate, setCurrentViewDate] = useState(new Date());

    const monthsList = [
        'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
        'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'
    ];

    const [showModal, setShowModal] = useState(false);
    const [isEdit, setIsEdit] = useState(false);
    const [currentEventId, setCurrentEventId] = useState(null);
    const [showReminderModal, setShowReminderModal] = useState(false);

    const initialForm = {
        title: '', type: 'event', start: '', end: '', all_day: true,
        session_type: 'Core', priority: 'Normal', session_template_id: '',
        batch_id: '', quarter_id: '', status: 'schedule', meeting_link: '',
        assigned_departments: [], assigned_member_ids: [], coach_ids: [],
        additional_details: '', category: 'General', repeat: 'Does not repeat',
        repeat_end_date: '', repeat_interval: 1, assigned_to: 'myself', target_staff_id: [],
        reminders: [], status_remark: '', gpt_projects: []
    };

    const [eventForm, setEventForm] = useState(initialForm);

    const departments = ['HOD', 'EA', 'MD', 'Implementor', 'HR', 'Other'];

    const fetchData = async () => {
        setLoading(true);
        try {
            const [evRes, bRes, qRes, tRes, uRes, sRes, gRes] = await Promise.all([
                api.get(`/calendar/events?view_mode=${viewMode}`), api.get('/batches'),
                api.get('/quarters'), api.get('/session-templates'),
                api.get('/users'), api.get('/settings/backdate-control'),
                api.get('/gpt/projects')
            ]);
            setEvents(evRes.data.map(e => ({
                id: e.id, title: e.title, start: e.start, end: e.end,
                backgroundColor: 'transparent', borderColor: 'transparent',
                textColor: 'var(--text-main)', allDay: e.allDay,
                extendedProps: { ...e.extendedProps, id: e.id, dotColor: getRescheduleColor(e.extendedProps?.status || e.status, e.extendedProps?.type || e.type, e.color) }
            })));
            setBatches(bRes.data); setQuarters(qRes.data); setTemplates(tRes.data); setAllUsers(uRes.data);
            setBackdateSettings(sRes.data); setGptProjects(gRes.data);
        } catch (err) { console.error(err); }
        finally { setLoading(false); }
    };
    useEffect(() => { fetchData(); }, [viewMode]);

    const formatIST = (dateStr) => {
        if (!dateStr) return "";
        let d = new Date(dateStr);
        if (typeof dateStr === 'string' && !dateStr.endsWith('Z') && !dateStr.includes('+')) {
            d = new Date(dateStr + 'Z');
        }
        return d.toLocaleString('en-IN', {
            timeZone: 'Asia/Kolkata', weekday: 'long', day: 'numeric', month: 'long',
            hour: '2-digit', minute: '2-digit', hour12: true
        });
    };

    const formatShortIST = (dateStr) => {
        if (!dateStr) return "";
        let d = new Date(dateStr);
        if (typeof dateStr === 'string' && !dateStr.endsWith('Z') && !dateStr.includes('+')) {
            d = new Date(dateStr + 'Z');
        }
        return d.toLocaleString('en-IN', {
            timeZone: 'Asia/Kolkata',
            day: 'numeric', month: 'short',
            hour: '2-digit', minute: '2-digit', hour12: true
        });
    };


    const getLocalDatePart = (dateStr) => {
        if (!dateStr) return "";
        const d = new Date(dateStr);
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    };

    const getLocalTimePart = (dateStr) => {
        if (!dateStr) return "00:00";
        const d = new Date(dateStr);
        return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    };

    const updateDateTimePart = (dateStr, newPart, isDate = true) => {
        if (!dateStr) return dateStr;
        const d = new Date(dateStr);
        if (isDate) {
            const [y, m, day] = newPart.split('-');
            d.setFullYear(parseInt(y), parseInt(m) - 1, parseInt(day));
        } else {
            const [h, min] = newPart.split(':');
            d.setHours(parseInt(h), parseInt(min));
        }
        return d.toISOString();
    };

    const categories = useMemo(() => {
        const set = new Set(['General', 'Maintenance', 'Meeting', 'Call', 'Private', 'Check-in']);
        events.forEach(e => { if (e.extendedProps?.category) set.add(e.extendedProps.category); });
        return Array.from(set);
    }, [events]);

    const getRescheduleColor = (status, type, color) => {
        if (status === 'reschedule') return '#f59e0b'; // Amber/Orange
        if (status === 'completed') return '#10b981'; // Emerald
        if (status === 'canceled') return '#ef4444'; // Red
        return color || (type === 'task' ? '#f97316' : '#6366f1');
    };

    // ─── Stats Calculation ───
    const currentMonthStats = useMemo(() => {
        const now = new Date();
        const currentYear = now.getFullYear();
        const currentMonth = now.getMonth();

        const data = events.filter(e => {
            const d = new Date(e.start);
            return d.getFullYear() === currentYear && d.getMonth() === currentMonth;
        });

        const getCount = (type, status) => {
            return data.filter(e => {
                const eType = e.extendedProps?.type || e.type;
                const eStatus = e.extendedProps?.status || e.status || "schedule";
                if (type && eType !== type) return false;
                if (status === 'pending') return eStatus === 'schedule';
                if (status && eStatus !== status) return false;
                return true;
            }).length;
        };

        return [
            { id: 'ev_total', label: 'Total Sessions', count: getCount('event', null), color: 'indigo', icon: <Activity size={14} />, filter: { type: 'event', status: null } },
            { id: 'ev_com', label: 'Completed', count: getCount('event', 'completed'), color: 'emerald', icon: <CheckCircle size={14} />, filter: { type: 'event', status: 'completed' } },
            { id: 'ev_pen', label: 'Pending', count: getCount('event', 'pending'), color: 'amber', icon: <Clock size={14} />, filter: { type: 'event', status: 'pending' } },
            { id: 'ev_res', label: 'Rescheduled', count: getCount('event', 'reschedule'), color: 'orange', icon: <ArrowRightLeft size={14} />, filter: { type: 'event', status: 'reschedule' } },
            { id: 'tk_total', label: 'Total Tasks', count: getCount('task', null), color: 'slate', icon: <ListChecks size={14} />, filter: { type: 'task', status: null } },
            { id: 'tk_com', label: 'Task Complete', count: getCount('task', 'completed'), color: 'emerald', icon: <CheckCircle size={14} />, filter: { type: 'task', status: 'completed' } },
            { id: 'tk_pen', label: 'Task Pending', count: getCount('task', 'pending'), color: 'rose', icon: <AlertCircle size={14} />, filter: { type: 'task', status: 'pending' } },
        ];
    }, [events]);

    const activeFilter = statFilter;
    const filteredEvents = useMemo(() => {
        if (!activeFilter) return events;
        return events.filter(e => {
            const eType = e.extendedProps?.type || e.type;
            const eStatus = e.extendedProps?.status || e.status || "schedule";
            if (activeFilter.type && eType !== activeFilter.type) return false;
            if (activeFilter.status === 'pending') return eStatus === 'schedule';
            if (activeFilter.status && eStatus !== activeFilter.status) return false;
            return true;
        });
    }, [events, activeFilter]);

    // ─── Summary Logic ───
    const handleDateSelect = (info) => {
        const selectedDate = info.startStr.split('T')[0];
        const eventsForDay = events.filter(e => {
            const d = new Date(e.start);
            if (isNaN(d.getTime())) return false;
            const eStart = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
            return eStart === selectedDate && !['batch', 'quarter'].includes(e.extendedProps?.type || e.type);
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
            target_staff_id: props.target_staff_id || [],
            reminders: props.reminders || [],
            status_remark: props.status_remark || '',
            gpt_projects: props.gpt_projects || [],
            isCreator: props.isCreator,
            isAssigned: props.isAssigned
        });

        setShowModal(true);
    };

    const handleQuickAction = async (id, action) => {
        if (!id) return showError("Invalid operation: Blueprint ID missing.");
        try {
            const ev = events.find(e => e.id === id || e._id === id);
            const isCreator = ev?.extendedProps?.isCreator;

            if (action === 'delete') { 
                if (!canDelete && !isCreator) return showError("Forbidden: You do not have digital authority to delete this blueprint.");
                await api.delete(`/calendar/events/${id}`); 
                showSuccess("Entity removed from calendar"); 
            }
            else if (action === 'complete') { 
                if (!canUpdate && !isCreator) return showError("Forbidden: You do not have digital authority to modify this event.");
                // Use the specialized completion endpoint for better reliability
                await api.patch(`/calendar/events/${id}/complete`); 
                showSuccess("Status updated"); 
            }
            fetchData();
            // If in summary modal, refresh current day list
            if (showSummary) {
                const res = await api.get('/calendar/events'); // Fast refresh for summary
                const eventsForDay = res.data
                    .filter(e => {
                        const d = new Date(e.start);
                        const eStart = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
                        return eStart === summaryDate && !['batch', 'quarter'].includes(e.type);
                    })
                    .map(e => ({
                        id: e.id, title: e.title, start: e.start, end: e.end, extendedProps: { ...e.extendedProps, id: e.id }
                    }));
                setDayEvents(eventsForDay);
            }
        } catch (err) { console.error(err); showError("Communication Failure: The session architect could not be reached."); }
    };

    const handleSave = async () => {
        if (!eventForm.title) return showError("Add a title");

        const eventStart = new Date(eventForm.start);
        const now = new Date();
        const isBackdated = eventStart < now;
        const canBackdate = backdateSettings.allow_backdate || backdateSettings.exception_users.includes(user?.email);

        if (isBackdated && !canBackdate && eventForm.status === 'schedule') {
            console.warn("RESTRICTED: Backdated attempt blocked in UI.");
            return showError("Operation Blocked: You do not have permission to schedule tasks or events in the past.");
        }


        // ─── CONFLICT DETECTION WARNING (Logged) ───
        try {
            const conflictCheck = await api.post('/calendar/events/validate-conflict', { 
                ...eventForm, id: currentEventId 
            });
            if (conflictCheck.data.has_conflict) {
                console.warn("Conflict detected:", conflictCheck.data.conflicts.map(c => c.title).join(", "));
            }
        } catch (e) { console.error("Conflict check failed", e); }

        try {
            if (isEdit) await api.patch(`/calendar/events/${currentEventId}`, eventForm);
            else await api.post('/calendar/events', eventForm);
            showSuccess(isEdit ? 'Event updated' : 'Event scheduled successfully');
            fetchData(); setShowModal(false); setShowSummary(false); 
        } catch (err) { showError('Failed to save event'); console.error(err); }
    };

    const role = user?.role?.toLowerCase();
    // Institutional roles (Staff) with global management authority
    const isPowerRole = ['superadmin', 'admin', 'coach', 'staff'].includes(role);
    const isStaff = isPowerRole;
    
    // Learners and Client Admins can create their own events.
    const isLearner = ['learner', 'clientadmin', 'clientdoer', 'clientuser'].includes(role);
    const canCreate = isStaff || isLearner || user?.permissions?.calendar?.create;

    // Only staff have global update/delete rights. Learners only have it if they are the creator (checked in the UI).
    const canUpdate = isStaff || user?.permissions?.calendar?.update;
    const canDelete = isStaff || user?.permissions?.calendar?.delete;

    // List of Staff users (Coaching side) for coaching team & task delegation
    const staffMembers = allUsers.filter(u => ['superadmin', 'admin', 'coach', 'staff'].includes(u.role?.toLowerCase()));

    // List of internal company members (including myself)
    const companyMembers = allUsers.filter(u => u.company_id === user?.company_id);

    // List of Learners for Staff Assignment (filtered by batch/department & session type compatibility)
    const assignableLearners = allUsers.filter(u => {
        const uRole = u.role?.toLowerCase();
        if (['superadmin', 'admin', 'coach', 'staff'].includes(uRole)) return false;

        // 1. Strict Batch & Company Linkage (Requirement: Only show batch-attached members)
        if (eventForm.batch_id) {
            const batch = batches.find(b => b._id === eventForm.batch_id || b.id === eventForm.batch_id);
            if (batch) {
                const belongsToBatch = (u.batch_id === eventForm.batch_id) || 
                                     (batch.companies || []).includes(u.company_id);
                if (!belongsToBatch) return false;
            }
        } else if (eventForm.type === 'event') {
            // For sessions, if no batch is selected, show no one to ensure accuracy
            return false;
        }

        // 2. Session Type Compatibility
        if (u.session_type === 'Both' || u.session_type === eventForm.session_type) return true;
        
        return false;
    });

    const visibleMembers = isStaff ? assignableLearners : companyMembers;

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
            <motion.div key={ev.id} layout className={`group relative bg-[var(--input-bg)] rounded-[24px] border border-[var(--border)] p-4 hover:shadow-xl hover:shadow-black/5 transition-all overflow-hidden ${s === 'completed' ? 'opacity-50' : ''}`}>
                <div className="absolute top-0 right-0 w-1.5 h-full" style={{ background: ev.extendedProps.dotColor }} />
                <div className="flex items-start justify-between mb-2">
                    <div className="space-y-0.5">
                        <div className="flex items-center gap-1.5 text-[8px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                            {type === 'task' ? <CheckCircle size={10} className="text-orange-500" /> : <Activity size={10} className="text-[var(--accent-indigo)]" />}
                            {type} • {s || 'scheduled'}
                        </div>
                        <h4 className="text-[14px] font-black text-[var(--text-main)] group-hover:text-[var(--accent-indigo)] transition-colors pr-10 leading-tight">{ev.title}</h4>
                    </div>
                </div>
                <div className="flex flex-col gap-1.5 text-[10px] font-bold text-[var(--text-muted)] mt-2 border-t border-[var(--border)] pt-2 border-dashed">
                    <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1 opacity-60"> <Clock size={11} /> Deadline: </span>
                        <span className="text-[var(--text-main)]">{formatShortIST(ev.start)}</span>
                    </div>
                    {ev.extendedProps.completed_at && (
                        <div className="flex items-center justify-between text-emerald-600 bg-emerald-500/5 px-2 py-0.5 rounded-md">
                            <span className="flex items-center gap-1 uppercase text-[8px] font-black"> <CheckCircle size={11} /> Completed: </span>
                            <span className="font-black italic">{formatShortIST(ev.extendedProps.completed_at)}</span>
                        </div>
                    )}
                    <div className="flex items-center gap-2 mt-0.5">
                        {ev.extendedProps.target_staff_id?.length > 0 && (
                            <div className="flex items-center gap-1 text-orange-600 bg-orange-500/5 px-1.5 py-0.5 rounded border border-orange-500/10 text-[9px]">
                                <UserCircle2 size={11} /> {ev.extendedProps.target_staff_id.map(id => allUsers.find(u => u._id === id || u.id === id)?.full_name).filter(Boolean).join(", ") || "Delegated"}
                            </div>
                        )}
                        {ev.extendedProps.meeting_link && <span className="flex items-center gap-1 text-[var(--accent-indigo)] text-[9px]"> <Video size={11} /> Linked </span>}
                    </div>
                </div>

                <div className="mt-3 flex items-center justify-between border-t border-dashed border-gray-200 pt-3">
                    <div className="flex items-center gap-2">
                        {(canUpdate || ev.extendedProps.isCreator) && (
                            <button onClick={() => handleQuickAction(ev.id, 'complete')} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[9px] font-black transition-all ${s === 'completed' ? 'bg-green-100/10 text-green-600 border border-green-200' : 'bg-[var(--bg-main)] text-[var(--text-muted)] hover:bg-green-500 hover:text-white border border-[var(--border)]'}`}>
                                {s === 'completed' ? <Check size={12} /> : <CheckCircle size={12} />} {s === 'completed' ? 'Done' : 'Complete'}
                            </button>
                        )}
                        <button onClick={() => openEditModal(ev)} className="p-1.5 bg-[var(--bg-main)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-indigo-500/10 rounded-lg transition-all"> 
                            { (canUpdate || ev.extendedProps.isCreator) ? <Edit2 size={12} /> : <Eye size={12} /> } 
                        </button>
                    </div>
                    {(canDelete || ev.extendedProps.isCreator) && (
                        <button onClick={() => handleQuickAction(ev.id, 'delete')} className="p-1.5 text-gray-300 hover:text-red-500 hover:bg-red-500/10 rounded-lg transition-all opacity-0 group-hover:opacity-100"> <Trash2 size={12} /> </button>
                    )}
                </div>
            </motion.div>
        );
    };

    return (
        <div className="space-y-6 flex flex-col min-h-screen pb-20">

            <div className="flex items-center justify-between px-2">
                <div>
                    <h1 className="text-xl font-black text-[var(--text-main)] tracking-tight uppercase">
                        Organization Calendar <span className="text-[var(--accent-indigo)] px-2">•</span> 
                        {currentViewDate.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
                    </h1>
                    <p className="text-[12px] text-[var(--text-muted)] font-bold italic tracking-wide">Elite session governance & operational accountability engine.</p>
                </div>
                <div className="flex items-center gap-3">
                    {/* Focus Toggle */}
                    {(user.role === 'superadmin' || user.role === 'admin') && (
                        <div className="flex items-center bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-1 shadow-sm mr-2">
                             <button onClick={() => setViewMode('personal')} className={`px-4 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all flex items-center gap-1.5 ${viewMode === 'personal' ? 'bg-[var(--accent-indigo)] text-white shadow-lg shadow-indigo-100' : 'text-[var(--text-muted)] hover:text-indigo-500'}`}>
                                 <UserCircle2 size={13} /> MY FOCUS
                             </button>
                             <button onClick={() => setViewMode('team')} className={`px-4 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all flex items-center gap-1.5 ${viewMode === 'team' ? 'bg-orange-600 text-white shadow-lg shadow-orange-100 font-black' : 'text-[var(--text-muted)] hover:text-orange-600'}`}>
                                 <Users2 size={13} /> TEAM VIEW
                             </button>
                        </div>
                    )}
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
                {loading && (<div className="absolute inset-0 flex items-center justify-center bg-[var(--bg-card)]/80 backdrop-blur-sm z-[100]"> <div className="w-12 h-12 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"></div> </div>)}
                {/* ─── Stats Dashboard Row ─── */}
                <div className="flex flex-nowrap items-center gap-3 mb-6 p-1 overflow-x-auto no-scrollbar scroll-smooth">

                    {currentMonthStats.map(s => {
                        const isActive = statFilter?.type === s.filter.type && statFilter?.status === s.filter.status;
                        const colorMap = {
                            indigo: 'bg-indigo-50 border-indigo-100 text-indigo-700 active:bg-indigo-500 active:text-white',
                            emerald: 'bg-emerald-50 border-emerald-100 text-emerald-700 active:bg-emerald-500 active:text-white',
                            amber: 'bg-amber-50 border-amber-100 text-amber-700 active:bg-amber-500 active:text-white',
                            orange: 'bg-orange-50 border-orange-100 text-orange-700 active:bg-orange-500 active:text-white',
                            slate: 'bg-slate-50 border-slate-100 text-slate-700 active:bg-slate-500 active:text-white',
                            rose: 'bg-rose-50 border-rose-100 text-rose-700 active:bg-rose-500 active:text-white',
                        };
                        const activeColorMap = {
                            indigo: 'bg-indigo-600 border-indigo-600 text-white ring-4 ring-indigo-100',
                            emerald: 'bg-emerald-600 border-emerald-600 text-white ring-4 ring-emerald-100',
                            amber: 'bg-amber-600 border-amber-600 text-white ring-4 ring-amber-100',
                            orange: 'bg-orange-600 border-orange-600 text-white ring-4 ring-orange-100',
                            slate: 'bg-slate-700 border-slate-700 text-white ring-4 ring-slate-100',
                            rose: 'bg-rose-600 border-rose-600 text-white ring-4 ring-rose-100',
                        };

                        return (
                            <button key={s.id} onClick={() => setStatFilter(isActive ? null : s.filter)}
                                className={`flex flex-col min-w-[130px] p-4 rounded-[24px] border-2 transition-all duration-300 transform active:scale-95 text-left grow basis-0 ${isActive ? activeColorMap[s.color] : colorMap[s.color]}`}>
                                <div className="flex items-center justify-between mb-2">
                                    <div className={`p-1.5 rounded-lg ${isActive ? 'bg-white/20' : 'bg-white shadow-sm'}`}>{s.icon}</div>
                                    <span className="text-[18px] font-black leading-none">{s.count}</span>
                                </div>
                                <span className={`text-[10px] font-black uppercase tracking-widest opacity-80 ${isActive ? 'text-white' : ''}`}>{s.label}</span>
                            </button>
                        );
                    })}
                </div>

                {/* ─── Month Jump Bar ─── */}
                <div className="flex items-center gap-1 mb-6 bg-[var(--input-bg)] p-1.5 rounded-2xl border border-[var(--border)] overflow-x-auto no-scrollbar">
                    {monthsList.map((m, idx) => {
                        const isCurrentMonth = currentViewDate.getMonth() === idx;
                        return (
                            <button
                                key={m}
                                onClick={() => {
                                    const newDate = new Date(currentViewDate);
                                    newDate.setMonth(idx);
                                    calendarRef.current.getApi().gotoDate(newDate);
                                }}
                                className={`flex-1 min-w-[50px] py-2 rounded-xl text-[11px] font-black transition-all ${
                                    isCurrentMonth 
                                    ? 'bg-[var(--accent-indigo)] text-white shadow-lg' 
                                    : 'text-[var(--text-muted)] hover:bg-white hover:text-[var(--accent-indigo)]'
                                }`}
                            >
                                {m}
                            </button>
                        );
                    })}
                </div>

                <FullCalendar
                    ref={calendarRef} plugins={[dayGridPlugin, timeGridPlugin, listPlugin, multiMonthPlugin, interactionPlugin]}
                    initialView="dayGridMonth" headerToolbar={false} events={filteredEvents} height="auto" selectable={true}
                    datesSet={(arg) => setCurrentViewDate(arg.view.currentStart)}

                    select={handleDateSelect} eventClick={(info) => {
                        const eStart = info.event.startStr.split('T')[0];
                        const eventsForDay = events.filter(e => e.start.split('T')[0] === eStart && !['batch', 'quarter'].includes(e.extendedProps.type));
                        setSummaryDate(eStart); setDayEvents(eventsForDay); setShowSummary(true);
                    }}
                    dayMaxEvents={3} eventContent={(info) => {
                        const s = info.event.extendedProps.status;
                        const type = info.event.extendedProps.type;
                        const isTask = type === 'task';
                        const isSpanning = info.isStart || info.isEnd || info.isMirror; // Simplified check
                        
                        return (
                            <div className={`flex items-center gap-1.5 px-2 py-0.5 max-w-full overflow-hidden group/ev transition-all border border-transparent hover:border-indigo-200/50 ${s === 'completed' ? 'opacity-40 grayscale' : ''} ${info.isStart ? 'rounded-l-lg' : ''} ${info.isEnd ? 'rounded-r-lg' : ''} ${!info.isStart && !info.isEnd ? '' : 'rounded-lg'}`}
                                 style={{ 
                                     background: isTask ? 'rgba(249, 115, 22, 0.08)' : 'rgba(99, 102, 241, 0.08)',
                                     marginLeft: info.isStart ? '0' : '-8px',
                                     marginRight: info.isEnd ? '0' : '-8px',
                                 }}>
                                <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: info.event.extendedProps.dotColor || (isTask ? '#f97316' : '#6366f1') }}></div>
                                <span className={`text-[10px] font-black truncate ${isTask ? 'text-orange-700' : 'text-indigo-700'}`} style={{ textDecoration: s === 'completed' ? 'line-through' : 'none' }}>
                                    {info.event.title}
                                </span>
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
                            className="bg-[var(--bg-card)] w-full max-w-[820px] rounded-[32px] shadow-2xl relative overflow-hidden flex flex-col border border-[var(--border)] max-h-[90vh]"
                        >
                            <div className="flex px-6 py-4 items-center justify-between border-b border-[var(--border)] bg-[var(--table-header-bg)]">
                                <div className="flex items-center gap-3">
                                    <div className="p-2.5 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] rounded-xl shadow-inner"> <CalendarIcon size={20} /> </div>
                                    <div>
                                        <h2 className="text-lg font-black text-[var(--text-main)] tracking-tight">Day Summary</h2>
                                        <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-wider">
                                            {new Date(summaryDate).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
                                            {(summaryDate && new Date(summaryDate + "T23:59:59") < new Date()) && <span className="ml-2 text-red-500">[PAST]</span>}
                                        </p>
                                    </div>
                                </div>
                                <button onClick={() => setShowSummary(false)} className="p-2 text-[var(--text-muted)] hover:bg-gray-100 rounded-xl transition-all"> <X size={20} /> </button>
                            </div>

                            <div className="p-6 overflow-y-auto no-scrollbar space-y-8">
                                {/* ─── Section 1: Corporate Sessions ─── */}
                                <div className="space-y-4">
                                    <div className="flex items-center justify-between border-b border-[var(--border)] pb-2">
                                        <h3 className="text-[11px] font-black text-[var(--accent-indigo)] uppercase tracking-[0.2em] flex items-center gap-1.5"> <Activity size={14} /> Sessions ({dayEvents.filter(e => e.extendedProps.type === 'event').length}) </h3>
                                        {(canCreate && (!summaryDate || new Date(summaryDate + "T23:59:59") >= new Date() || backdateSettings.allow_backdate || backdateSettings.exception_users.includes(user?.email))) && (
                                            <button onClick={() => openCreateModal('event')} className="flex items-center gap-1.5 px-4 py-1.5 bg-[var(--accent-indigo)] text-white rounded-lg text-[10px] font-black shadow-md shadow-indigo-200/40 hover:opacity-90 transition-all uppercase tracking-widest"> <PlusCircle size={12} /> Add Session </button>
                                        )}
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        {dayEvents.filter(e => e.extendedProps.type === 'event').map(ev => renderEventTile(ev))}
                                        {dayEvents.filter(e => e.extendedProps.type === 'event').length === 0 && (
                                            <div className="col-span-full py-8 flex flex-col items-center justify-center bg-gray-50/50 rounded-[24px] border border-dashed border-gray-200 opacity-50">
                                                <p className="text-[9px] font-black text-gray-400 uppercase tracking-widest">No sessions scheduled.</p>
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {/* ─── Section 2: Strategic Tasks ─── */}
                                <div className="space-y-4">
                                    <div className="flex items-center justify-between border-b border-[var(--border)] pb-2">
                                        <h3 className="text-[11px] font-black text-orange-500 uppercase tracking-[0.2em] flex items-center gap-1.5"> <CheckCircle size={14} /> Tasks ({dayEvents.filter(e => e.extendedProps.type === 'task').length}) </h3>
                                        {(canCreate && (!summaryDate || new Date(summaryDate + "T23:59:59") >= new Date() || backdateSettings.allow_backdate || backdateSettings.exception_users.includes(user?.email))) && (
                                            <button onClick={() => openCreateModal('task')} className="flex items-center gap-1.5 px-4 py-1.5 bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] rounded-lg text-[10px] font-black hover:bg-gray-100 transition-all uppercase tracking-widest"> <PlusCircle size={12} /> Add Task </button>
                                        )}
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        {dayEvents.filter(e => e.extendedProps.type === 'task').map(ev => renderEventTile(ev))}
                                        {dayEvents.filter(e => e.extendedProps.type === 'task').length === 0 && (
                                            <div className="col-span-full py-8 flex flex-col items-center justify-center bg-gray-50/50 rounded-[24px] border border-dashed border-gray-200 opacity-50">
                                                <p className="text-[9px] font-black text-gray-400 uppercase tracking-widest">No tasks listed.</p>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>

                            <div className="p-4 border-t border-[var(--border)] bg-[var(--table-header-bg)] flex items-center justify-center gap-3">
                                <Zap size={16} className="text-orange-400" />
                                <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest leading-none">Select a tile above to modify or confirm the session architect.</p>
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
                            className="bg-[var(--bg-card)] w-full max-w-[780px] rounded-[32px] shadow-[0_50px_100px_-20px_rgba(0,0,0,0.5)] relative overflow-hidden flex flex-col border border-[var(--border)] max-h-[95vh]"
                        >
                            <div className="flex px-6 py-4 items-center justify-between border-b border-[var(--border)] bg-[var(--bg-main)]">
                                <div className="flex items-center gap-3">
                                    <div className={`w-2.5 h-2.5 rounded-full animate-pulse ${eventForm.status === 'completed' ? 'bg-green-500' : 'bg-indigo-500'}`} />
                                    <span className="text-[10px] font-black uppercase tracking-widest text-[var(--accent-indigo)]"> 
                                        {isEdit ? `Edit Operation [${eventForm.status}]` : (eventForm.type === 'task' ? 'Architect Tasks' : 'Architect Session')} 
                                    </span>
                                </div>
                                <div className="flex items-center gap-2">
                                    {(isEdit && (canUpdate || eventForm.isCreator)) && (
                                        <div className="flex items-center bg-[var(--input-bg)] border border-[var(--border)] rounded-xl p-1 shrink-0">
                                            <button onClick={() => setEventForm({ ...eventForm, status: 'completed' })} className={`p-2 rounded-lg transition-all ${eventForm.status === 'completed' ? 'bg-green-500 text-white shadow-lg' : 'text-gray-400 hover:text-green-500'}`}> <CheckCircle size={16} /> </button>
                                            <button onClick={() => setEventForm({ ...eventForm, status: 'canceled' })} className={`p-2 rounded-lg transition-all ${eventForm.status === 'canceled' ? 'bg-red-500 text-white shadow-lg' : 'text-gray-400 hover:text-red-500'}`}> <Ban size={16} /> </button>
                                            {canDelete && <button onClick={() => handleQuickAction(currentEventId, 'delete')} className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-500/10 rounded-lg"> <Trash2 size={16} /> </button>}
                                        </div>
                                    )}
                                    {isEdit && !(canUpdate || eventForm.isCreator) && (
                                        <div className="px-3 py-1 bg-amber-500/10 border border-amber-500/20 text-amber-600 rounded-xl text-[8px] font-black uppercase tracking-tighter flex items-center gap-1">
                                            <Lock size={10} /> Read-Only Access
                                        </div>
                                    )}
                                    <button onClick={() => setShowModal(false)} className="p-2 text-[var(--text-muted)] hover:bg-gray-800 rounded-full transition-all"> <X size={20} /> </button>
                                </div>
                            </div>

                            <div className="p-6 overflow-y-auto no-scrollbar space-y-6">
                                {(!isStaff && isEdit && !eventForm.isCreator) ? (
                                    /* ─── SIMPLIFIED LEARNER TICKET VIEW ─── */
                                    <div className="space-y-8 py-4">
                                        <div className="flex flex-col items-center text-center space-y-2">
                                            <div className="w-16 h-16 rounded-full bg-indigo-50 flex items-center justify-center mb-2"> <PlayCircle size={32} className="text-[var(--accent-indigo)]" /> </div>
                                            <h2 className="text-3xl font-black text-[var(--text-main)] tracking-tight">{eventForm.title}</h2>
                                            <p className="text-[10px] font-black text-[var(--accent-indigo)] uppercase tracking-[0.3em]">Official Training Session</p>
                                        </div>

                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                            <div className="p-5 bg-gray-50/50 border border-dashed border-gray-200 rounded-[24px] space-y-2">
                                                <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest flex items-center gap-1.5"><Building2 size={12}/> Organizational Batch</label>
                                                <p className="text-[13px] font-black text-[var(--text-main)]">{batches.find(b => b._id === eventForm.batch_id)?.name || "N/A"}</p>
                                            </div>
                                            <div className="p-5 bg-gray-50/50 border border-dashed border-gray-200 rounded-[24px] space-y-2">
                                                <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest flex items-center gap-1.5"><LayoutGrid size={12}/> Session Module</label>
                                                <p className="text-[13px] font-black text-[var(--text-main)]">{templates.find(t => t._id === eventForm.session_template_id)?.title || "Custom Curriculum"}</p>
                                            </div>
                                        </div>

                                        <div className="p-6 bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] rounded-[32px] flex items-center justify-between shadow-inner">
                                            <div className="flex items-center gap-4">
                                                <div className="p-3 bg-white rounded-2xl text-[var(--accent-indigo)] shadow-sm"> <CalendarDays size={24} /> </div>
                                                <div className="space-y-1">
                                                    <p className="text-[14px] font-black text-[var(--accent-indigo)]">{new Date(eventForm.start).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}</p>
                                                    <p className="text-[11px] font-bold text-indigo-400 uppercase tracking-widest">{formatIST(eventForm.start)} • Indian Standard Time</p>
                                                </div>
                                            </div>
                                        </div>

                                        <div className="pt-4 flex flex-col items-center space-y-4">
                                            {eventForm.meeting_link ? (
                                                <>
                                                    <a href={eventForm.meeting_link} target="_blank" rel="noreferrer" 
                                                       className="w-full py-4 bg-indigo-600 text-white rounded-[24px] text-[14px] font-black uppercase tracking-widest flex items-center justify-center gap-3 shadow-xl shadow-indigo-500/40 hover:bg-indigo-700 hover:scale-[1.01] transition-all">
                                                        <Video size={18} /> Join Live Session
                                                    </a>
                                                    <button onClick={() => navigate(`/sessions/${currentEventId}`)} 
                                                       className="text-[10px] font-black text-[var(--accent-indigo)] uppercase tracking-widest hover:underline">
                                                        View Curriculum & Resources
                                                    </button>
                                                </>
                                            ) : (
                                                <button onClick={() => navigate(`/sessions/${currentEventId}`)} 
                                                   className="w-full py-4 bg-[var(--bg-main)] border border-[var(--border)] text-[var(--accent-indigo)] rounded-[24px] text-[14px] font-black uppercase tracking-widest flex items-center justify-center gap-3 hover:bg-[var(--accent-indigo-bg)] transition-all">
                                                    <Eye size={18} /> View Session Details
                                                </button>
                                            )}
                                        </div>

                                        <div className="pt-2 border-t border-dashed border-gray-200">
                                            <label className="text-[9px] font-black text-gray-400 uppercase tracking-widest block mb-2">Final Briefing:</label>
                                            <div className="text-[12px] font-medium text-gray-600 leading-relaxed bg-gray-50/50 p-4 rounded-xl italic">
                                                {eventForm.additional_details || "No additional instructions provided for this session."}
                                            </div>
                                        </div>
                                    </div>
                                ) : (
                                    <>
                                        <div className="space-y-3">
                                    <input autoFocus placeholder={eventForm.type === 'task' ? "Task Name" : "Session Title"} className="w-full text-2xl font-black bg-transparent border-b border-dashed border-gray-200 focus:border-[var(--accent-indigo)] outline-none pb-2 text-[var(--text-main)] transition-colors"
                                        value={eventForm.title} onChange={e => setEventForm({ ...eventForm, title: e.target.value })} />

                                    <div className="flex flex-wrap items-center gap-3">
                                        <div className="flex items-center gap-1.5 px-2 py-1 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] text-[9px] font-black uppercase tracking-widest rounded-lg"> <Clock size={12} /> IST • {formatIST(eventForm.start)} </div>
                                        {isEdit && (
                                            <div className="flex items-center gap-1.5">
                                                <label className="text-[9px] font-black text-gray-400 uppercase">Status:</label>
                                                {(eventForm.isCreator || canUpdate) ? (
                                                    <select value={eventForm.status} onChange={e => setEventForm({ ...eventForm, status: e.target.value })}
                                                        className="bg-[var(--input-bg)] border border-[var(--border)] rounded-md px-2 py-0.5 text-[10px] font-black text-[var(--accent-indigo)] uppercase outline-none focus:border-[var(--accent-indigo)]">
                                                        <option value="schedule">Scheduled</option>
                                                        <option value="reschedule">Rescheduled</option>
                                                        <option value="canceled">Canceled</option>
                                                        <option value="completed">Completed</option>
                                                    </select>
                                                ) : (
                                                    <span className="px-2 py-0.5 bg-gray-100 rounded text-[9px] font-black uppercase text-gray-500">{eventForm.status}</span>
                                                )}
                                            </div>
                                        )}
                                    </div>

                                    {isEdit && eventForm.status === 'reschedule' && (
                                        <div className="p-4 bg-amber-50 border border-amber-200 rounded-2xl space-y-3 shadow-inner">
                                            <div className="flex items-center justify-between">
                                                <label className="text-[9px] font-black text-amber-600 uppercase flex items-center gap-1 underline tracking-widest">Handover Note:</label>
                                                <div className="px-2 py-0.5 bg-amber-500 text-white rounded text-[8px] font-black uppercase">Rescheduled</div>
                                            </div>
                                            <textarea placeholder="Reason for change..."
                                                className="w-full bg-white border border-amber-100 p-3 rounded-xl text-xs font-bold outline-none text-amber-800 placeholder:text-amber-300"
                                                value={eventForm.status_remark} onChange={e => setEventForm({ ...eventForm, status_remark: e.target.value })}
                                            />
                                            <div className="grid grid-cols-2 gap-3">
                                                <div className="space-y-1">
                                                    <label className="text-[8px] font-black text-amber-600 uppercase">New Date</label>
                                                    <input type="date" className="w-full px-3 py-2 bg-white border border-amber-100 rounded-lg text-xs font-black text-amber-900 outline-none"
                                                           value={getLocalDatePart(eventForm.start)}
                                                           onChange={(e) => {
                                                               const newStart = updateDateTimePart(eventForm.start, e.target.value, true);
                                                               const newEnd = updateDateTimePart(eventForm.end, e.target.value, true);
                                                               setEventForm({...eventForm, start: newStart, end: newEnd});
                                                           }} />
                                                </div>
                                                <div className="space-y-1">
                                                    <label className="text-[8px] font-black text-amber-600 uppercase">New Time</label>
                                                    <input type="time" className="w-full px-3 py-2 bg-white border border-amber-100 rounded-lg text-xs font-black text-amber-900 outline-none"
                                                           value={getLocalTimePart(eventForm.start)}
                                                           onChange={(e) => setEventForm({...eventForm, start: updateDateTimePart(eventForm.start, e.target.value, false)})} />
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>

                                <div className={`grid grid-cols-1 md:grid-cols-2 gap-6 ${(isEdit && !eventForm.isCreator && !canUpdate && eventForm.isAssigned) ? 'opacity-40 pointer-events-none' : ''}`}>
                                    {isStaff ? (
                                        eventForm.type === 'event' ? (
                                            /* ─── STAFF ARCHITECT: SESSION ─── */
                                            <>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Zap size={12} /> Strategic Strategy</label>
                                                        <select className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.session_type} onChange={e => setEventForm({ ...eventForm, session_type: e.target.value })}><option>Core</option><option>Support</option></select>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><LayoutGrid size={12} /> Session Template</label>
                                                        <select className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.session_template_id} onChange={e => setEventForm({ ...eventForm, session_template_id: e.target.value })}><option value="">None / Custom</option>{templates.map(t => <option key={t._id} value={t._id}>{t.title}</option>)}</select>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Building2 size={12} /> Organizational Batch</label>
                                                        <select className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.batch_id} onChange={e => setEventForm({ ...eventForm, batch_id: e.target.value, quarter_id: '' })}><option value="">Select Batch</option>{batches.map(b => <option key={b._id} value={b._id}>{b.name}</option>)}</select>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Link size={12} /> Live Link</label>
                                                        <input placeholder="Zoom / Meet URL" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.meeting_link} onChange={e => setEventForm({ ...eventForm, meeting_link: e.target.value })} />
                                                    </div>
                                                </div>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Layers size={12} /> Quarter Selection</label>
                                                        <select disabled={!eventForm.batch_id} className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold disabled:opacity-50" value={eventForm.quarter_id} onChange={e => setEventForm({ ...eventForm, quarter_id: e.target.value })}><option value="">{eventForm.batch_id ? "Select Quarter" : "Select Batch First"}</option>{quarters.filter(q => q.batch_id === eventForm.batch_id).map(q => <option key={q._id} value={q._id}>{q.name}</option>)}</select>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><UserCircle2 size={12} /> Coaching Team</label>
                                                        <div className="flex flex-wrap gap-1 p-2 bg-[var(--input-bg)] rounded-xl border border-[var(--border)] min-h-[40px] max-h-[80px] overflow-y-auto no-scrollbar">
                                                            {staffMembers.map(c => (
                                                                <div key={c._id} onClick={() => {
                                                                    const current = [...(eventForm.coach_ids || [])];
                                                                    setEventForm({ ...eventForm, coach_ids: current.includes(c._id) ? current.filter(id => id !== c._id) : [...current, c._id] })
                                                                }}
                                                                    className={`px-2 py-1 rounded-md text-[9px] font-black cursor-pointer transition-all flex items-center gap-1.5 ${eventForm.coach_ids?.includes(c._id) ? 'bg-[var(--accent-indigo)] text-white shadow-sm' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)]'}`}>
                                                                    {c.full_name || c.name}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                </div>
                                            </>
                                        ) : (
                                            /* ─── STAFF ARCHITECT: TASKS ─── */
                                            <>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><LayoutGrid size={12} /> Task Category</label>
                                                        <input list="task-categories" placeholder="Category" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.category} onChange={e => setEventForm({ ...eventForm, category: e.target.value })} />
                                                        <datalist id="task-categories">{categories.map(c => <option key={c} value={c} />)}</datalist>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><AlertCircle size={12} /> Critical Level</label>
                                                        <div className="flex gap-2">
                                                            {['Normal', 'High', 'Urgent'].map(p => (
                                                                <button key={p} onClick={() => setEventForm({ ...eventForm, priority: p })} className={`flex-1 py-1.5 rounded-lg text-[10px] font-black transition-all ${eventForm.priority === p ? 'bg-[var(--accent-indigo)] text-white' : 'bg-white text-[var(--text-muted)] border border-[var(--border)]'}`}>{p.toUpperCase()}</button>
                                                            ))}
                                                        </div>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><ArrowRightLeft size={12} /> Strategic Repetition</label>
                                                        <select className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.repeat} onChange={e => setEventForm({ ...eventForm, repeat: e.target.value })}>
                                                            <option value="Does not repeat">Does not repeat</option><option value="Daily">Daily</option><option value="Weekly">Weekly</option><option value="Monthly">Monthly</option><option value="periodic">Periodically</option>
                                                        </select>
                                                    </div>
                                                    {eventForm.repeat === 'periodic' && (
                                                        <div className="space-y-1">
                                                            <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Clock size={12} /> Repeat in Days</label>
                                                            <input type="number" min="1" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.repeat_interval} onChange={e => setEventForm({ ...eventForm, repeat_interval: parseInt(e.target.value) })} />
                                                        </div>
                                                    )}
                                                    {eventForm.repeat !== 'Does not repeat' && (
                                                        <div className="space-y-1">
                                                            <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><CalendarDays size={12} /> End Repetition</label>
                                                            <input type="date" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.repeat_end_date ? eventForm.repeat_end_date.split('T')[0] : ''} onChange={e => setEventForm({ ...eventForm, repeat_end_date: e.target.value })} />
                                                        </div>
                                                    )}
                                                </div>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><UserPlus2 size={12} /> Assignment Delegation</label>
                                                        <div className="flex flex-wrap gap-1 p-2 bg-[var(--input-bg)] rounded-xl border border-[var(--border)] max-h-[140px] overflow-y-auto no-scrollbar">
                                                            <div onClick={() => setEventForm({ ...eventForm, target_staff_id: [user._id] })} className={`px-2 py-1 rounded-md text-[9px] font-black cursor-pointer transition-all ${eventForm.target_staff_id?.includes(user._id) ? 'bg-[var(--accent-indigo)] text-white' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)]'}`}>Myself</div>
                                                            {staffMembers.map(m => (
                                                                <div key={m._id} onClick={() => {
                                                                    const current = [...(eventForm.target_staff_id || [])];
                                                                    setEventForm({ ...eventForm, target_staff_id: current.includes(m._id) ? current.filter(id => id !== m._id) : [...current, m._id] })
                                                                }} className={`px-2 py-1 rounded-md text-[9px] font-black cursor-pointer transition-all ${eventForm.target_staff_id?.includes(m._id) ? 'bg-[var(--accent-indigo)] text-white' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)]'}`}>{m.full_name || m.name}</div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                </div>
                                            </>
                                        )
                                    ) : (
                                        eventForm.type === 'event' ? (
                                            /* ─── LEARNER ARCHITECT: SESSION ─── */
                                            <>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Link size={12} /> Live Link</label>
                                                        <input placeholder="Zoom / Meet URL" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.meeting_link} onChange={e => setEventForm({ ...eventForm, meeting_link: e.target.value })} />
                                                    </div>
                                                </div>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Users2 size={12} /> Participant (Company)</label>
                                                        <div className="flex flex-wrap gap-1 p-2 bg-[var(--input-bg)] rounded-xl border border-[var(--border)] min-h-[40px] max-h-[140px] overflow-y-auto no-scrollbar">
                                                            {companyMembers.map(m => (
                                                                <div key={m._id} onClick={() => {
                                                                    const current = [...(eventForm.assigned_member_ids || [])];
                                                                    setEventForm({ ...eventForm, assigned_member_ids: current.includes(m._id) ? current.filter(id => id !== m._id) : [...current, m._id] })
                                                                }} className={`px-2 py-1 rounded-md text-[9px] font-black cursor-pointer transition-all ${eventForm.assigned_member_ids?.includes(m._id) ? 'bg-[var(--accent-indigo)] text-white' : 'bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)]'}`}>{m.full_name || m.name}</div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                </div>
                                            </>
                                        ) : (
                                            /* ─── LEARNER ARCHITECT: TASKS ─── */
                                            <>
                                                <div className="space-y-4">
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><LayoutGrid size={12} /> Task Category</label>
                                                        <input list="task-categories" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.category} onChange={e => setEventForm({ ...eventForm, category: e.target.value })} />
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><AlertCircle size={12} /> Critical Level</label>
                                                        <div className="flex gap-2">
                                                            {['Normal', 'High', 'Urgent'].map(p => (
                                                                <button key={p} onClick={() => setEventForm({ ...eventForm, priority: p })} className={`flex-1 py-1.5 rounded-lg text-[10px] font-black transition-all ${eventForm.priority === p ? 'bg-[var(--accent-indigo)] text-white' : 'bg-white text-[var(--text-muted)] border border-[var(--border)]'}`}>{p.toUpperCase()}</button>
                                                            ))}
                                                        </div>
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><ArrowRightLeft size={12} /> Strategic Repetition</label>
                                                        <select className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.repeat} onChange={e => setEventForm({ ...eventForm, repeat: e.target.value })}>
                                                            <option value="Does not repeat">Does not repeat</option><option value="Daily">Daily</option><option value="Weekly">Weekly</option><option value="Monthly">Monthly</option><option value="periodic">Periodically</option>
                                                        </select>
                                                    </div>
                                                    {eventForm.repeat === 'periodic' && (
                                                        <div className="space-y-1">
                                                            <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><Clock size={12} /> Repeat in Days</label>
                                                            <input type="number" min="1" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.repeat_interval} onChange={e => setEventForm({ ...eventForm, repeat_interval: parseInt(e.target.value) })} />
                                                        </div>
                                                    )}
                                                    {eventForm.repeat !== 'Does not repeat' && (
                                                        <div className="space-y-1">
                                                            <label className="text-[9px] font-black text-[var(--text-muted)] uppercase flex items-center gap-1.5"><CalendarDays size={12} /> End Repetition</label>
                                                            <input type="date" className="w-full px-3 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[12px] font-bold" value={eventForm.repeat_end_date ? eventForm.repeat_end_date.split('T')[0] : ''} onChange={e => setEventForm({ ...eventForm, repeat_end_date: e.target.value })} />
                                                        </div>
                                                    )}
                                                </div>
                                                <div className="space-y-4">
                                                    {/* Additional Learner Task Fields can go here */}
                                                </div>
                                            </>
                                        )
                                    )}
                                </div>

                                {!(isStaff && eventForm.type === 'task') && (
                                    <div className="space-y-3 p-4 bg-[var(--input-bg)] rounded-2xl border border-[var(--border)] shadow-sm">
                                        <div className="space-y-2">
                                            <label className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-1.5">
                                                <Users2 size={12} /> {isStaff ? (eventForm.type === 'event' ? `Active Assignment: ${eventForm.assigned_departments.join(", ") || "None"}` : "Participant Scope") : "Participant Management"}
                                            </label>
                                            {(isStaff && eventForm.type === 'event') && (
                                                <div className="flex flex-wrap gap-1">
                                                    {departments.map(dept => (
                                                        <button key={dept} onClick={() => handleDeptToggle(dept)}
                                                            className={`px-3 py-1 rounded-lg text-[9px] font-black border transition-all ${eventForm.assigned_departments.includes(dept) ? 'bg-[var(--accent-indigo)] text-white border-[var(--accent-indigo)] shadow-sm' : 'bg-white text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--accent-indigo)]'}`}>
                                                            {dept}
                                                        </button>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                        <div className="flex flex-wrap gap-1 p-1 min-h-[40px] max-h-[100px] overflow-y-auto no-scrollbar">
                                            {visibleMembers.filter(u => {
                                                if (!isStaff || eventForm.type !== 'event') return true;
                                                if (!eventForm.assigned_departments || eventForm.assigned_departments.length === 0) return true;
                                                return eventForm.assigned_departments.some(dept => u.department?.toString().toUpperCase() === dept.toUpperCase());
                                            }).map(m => (
                                                <div key={m._id} onClick={() => {
                                                    const ids = [...(eventForm.assigned_member_ids || [])];
                                                    setEventForm({ ...eventForm, assigned_member_ids: ids.includes(m._id) ? ids.filter(id => id !== m._id) : [...ids, m._id] })
                                                }}
                                                    className={`px-2 py-0.5 rounded-md text-[9px] font-bold cursor-pointer transition-all flex items-center gap-1.5 ${eventForm.assigned_member_ids?.includes(m._id) ? 'bg-[var(--accent-indigo)] text-white shadow-sm border border-[var(--accent-indigo-border)]' : 'bg-[var(--bg-card)] text-[var(--text-muted)] opacity-50 border border-dotted border-gray-400'}`}>
                                                    {m.full_name || m.name} <X size={10} className={eventForm.assigned_member_ids?.includes(m._id) ? 'text-white' : 'hidden'} />
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                <div className="space-y-4">
                                    <div className="flex items-center gap-4 flex-wrap">
                                        <div className="flex items-center gap-2 bg-[var(--input-bg)] px-4 py-2.5 rounded-xl border border-[var(--border)] relative cursor-pointer hover:border-[var(--accent-indigo)] transition-all">
                                            <CalendarDays size={18} className="text-[var(--accent-indigo)]" />
                                            <span className="text-[13px] font-black">{new Date(eventForm.start).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })}</span>
                                            <input type="date" className="absolute inset-0 opacity-0 cursor-pointer" 
                                                   value={getLocalDatePart(eventForm.start)}
                                                   onChange={(e) => {
                                                       const newStart = updateDateTimePart(eventForm.start, e.target.value, true);
                                                       const newEnd = updateDateTimePart(eventForm.end, e.target.value, true);
                                                       setEventForm({...eventForm, start: newStart, end: newEnd});
                                                   }} />
                                        </div>
                                        <label className="flex items-center gap-3 cursor-pointer bg-[var(--input-bg)] border border-[var(--border)] px-4 py-2.5 rounded-xl shadow-inner group">
                                            <input type="checkbox" checked={eventForm.all_day} onChange={e => setEventForm({ ...eventForm, all_day: e.target.checked })} className="w-4 h-4 accent-[var(--accent-indigo)]" />
                                            <span className="text-[11px] font-black uppercase text-[var(--text-muted)] group-hover:text-[var(--accent-indigo)] transition-colors">Full Day Block</span>
                                        </label>
                                        {!eventForm.all_day && (
                                            <div className="flex items-center gap-2 bg-[var(--accent-indigo-bg)] p-1 rounded-xl border border-[var(--border)] shadow-inner">
                                                <input type="time" className="bg-transparent px-3 py-1.5 text-[12px] font-black text-[var(--accent-indigo)] outline-none"
                                                    value={new Date(eventForm.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}
                                                    onChange={(e) => {
                                                        const [hours, minutes] = e.target.value.split(':');
                                                        const newDate = new Date(eventForm.start);
                                                        newDate.setHours(parseInt(hours), parseInt(minutes));
                                                        setEventForm({ ...eventForm, start: newDate.toISOString() });
                                                    }}
                                                />
                                                <ArrowRightLeft size={10} className="text-[var(--accent-indigo)] opacity-40" />
                                                <input type="time" className="bg-transparent px-3 py-1.5 text-[12px] font-black text-[var(--accent-indigo)] outline-none"
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
                                </div>
                                <div className="space-y-4 p-5 bg-orange-50/20 rounded-[24px] border border-orange-100 border-dashed">
                                    <div className="flex items-center justify-between">
                                        <div className="flex items-center gap-2">
                                            <Bell size={14} className="text-orange-500" />
                                            <span className="text-[9px] font-black uppercase text-orange-600 tracking-widest">Active Reminders ({eventForm.reminders?.length || 0})</span>
                                        </div>
                                        <button type="button" onClick={() => setShowReminderModal(true)} className="px-3 py-1.5 bg-white border border-orange-100 text-orange-600 rounded-lg text-[9px] font-black hover:bg-orange-500 hover:text-white transition-all">
                                            {eventForm.reminders?.length > 0 ? 'MANAGE' : 'ADD'}
                                        </button>
                                    </div>
                                    {eventForm.reminders?.length > 0 && (
                                        <div className="flex flex-wrap gap-1.5">
                                            {eventForm.reminders.map((r, i) => (
                                                <div key={i} className="px-2 py-1 bg-white border border-gray-100 rounded text-[8px] font-bold text-gray-500 flex items-center gap-1.5">
                                                    {r.reminder_type === 'whatsapp' ? '💬' : r.reminder_type === 'email' ? '📧' : '⚡'}
                                                    {r.offset_minutes}m {r.timing_type}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>

                                <textarea placeholder={eventForm.type === 'task' ? "Task Details..." : "Instruction..." } rows={3} className="w-full bg-[var(--input-bg)] p-4 rounded-2xl text-[12px] font-medium border border-[var(--border)] outline-none focus:bg-white transition-all shadow-inner"
                                    value={eventForm.additional_details} onChange={e => setEventForm({ ...eventForm, additional_details: e.target.value })} />
                                    </>
                                )}
                            </div>

                            <ReminderModal
                                isOpen={showReminderModal}
                                onClose={() => setShowReminderModal(false)}
                                reminders={eventForm.reminders}
                                onApply={(reminders) => setEventForm({ ...eventForm, reminders })}
                            />

                            {!(isEdit && !isStaff && !eventForm.isCreator) && (
                                <div className="p-5 border-t border-[var(--border)] flex justify-between items-center bg-[var(--table-header-bg)]">
                                    <div className="flex items-center gap-3">
                                        <ShieldCheck size={20} className="text-[var(--accent-indigo)] opacity-30" />
                                        <div className="space-y-0">
                                            <p className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest leading-tight">Digital Authorization</p>
                                            <p className="text-[10px] font-bold text-gray-400 italic leading-tight">Changes sync to calendars instantly.</p>
                                        </div>
                                    </div>
                                    <button onClick={handleSave} 
                                        disabled={isEdit && !(user.role === 'superadmin' || user.role === 'admin' || eventForm.isCreator)}
                                        className={`bg-[var(--btn-primary)] text-white px-10 py-3 rounded-xl text-[12px] font-black shadow-xl shadow-indigo-500/30 hover:scale-[1.02] active:scale-[0.98] transition-all tracking-[0.1em] uppercase ${isEdit && !(user.role === 'superadmin' || user.role === 'admin' || eventForm.isCreator) ? 'opacity-20 cursor-not-allowed grayscale' : ''}`}>
                                        {isEdit ? 'Authorize Updates' : (eventForm.type === 'task' ? 'Schedule Task' : 'Schedule Session')}
                                    </button>
                                </div>
                            )}
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>
        </div>
    );
};

export default CalendarPage;
