import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
    MessageSquare, CheckCircle2, XCircle, Clock, Activity,
    Search, RefreshCw, AlertTriangle, ChevronLeft, ChevronRight, ShieldCheck, ShieldAlert
} from 'lucide-react';
import {
    ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid
} from 'recharts';
import api from '../services/api';

const RANGES = [
    { label: '7D', value: 7 },
    { label: '30D', value: 30 },
    { label: '90D', value: 90 },
];

const STATUS_FILTERS = ['all', 'sent', 'failed', 'pending'];

const statusStyles = {
    sent: 'bg-emerald-100 text-emerald-700',
    failed: 'bg-red-100 text-red-700',
    pending: 'bg-amber-100 text-amber-700',
};

const WhatsAppDashboard = () => {
    const [stats, setStats] = useState(null);
    const [logsData, setLogsData] = useState(null);
    const [loadingStats, setLoadingStats] = useState(true);
    const [loadingLogs, setLoadingLogs] = useState(true);
    const [error, setError] = useState(null);

    // Filters
    const [days, setDays] = useState(30);
    const [statusFilter, setStatusFilter] = useState('all');
    const [search, setSearch] = useState('');
    const [debouncedSearch, setDebouncedSearch] = useState('');
    const [page, setPage] = useState(1);

    // Debounce the search box so we don't hammer the API on every keystroke
    useEffect(() => {
        const t = setTimeout(() => { setDebouncedSearch(search.trim()); setPage(1); }, 400);
        return () => clearTimeout(t);
    }, [search]);

    const fetchStats = useCallback(async () => {
        setLoadingStats(true);
        try {
            const res = await api.get('/notifications/whatsapp/stats', { params: { days } });
            setStats(res.data);
            setError(null);
        } catch (err) {
            console.error('Failed to load WhatsApp stats:', err);
            setError(err.response?.status === 403
                ? 'You do not have permission to view WhatsApp analytics.'
                : 'Failed to load WhatsApp analytics. Please try again.');
        } finally {
            setLoadingStats(false);
        }
    }, [days]);

    const fetchLogs = useCallback(async () => {
        setLoadingLogs(true);
        try {
            const params = { days, page, page_size: 25 };
            if (statusFilter !== 'all') params.status = statusFilter;
            if (debouncedSearch) params.search = debouncedSearch;
            const res = await api.get('/notifications/whatsapp/logs', { params });
            setLogsData(res.data);
        } catch (err) {
            console.error('Failed to load WhatsApp logs:', err);
        } finally {
            setLoadingLogs(false);
        }
    }, [days, page, statusFilter, debouncedSearch]);

    useEffect(() => { fetchStats(); }, [fetchStats]);
    useEffect(() => { fetchLogs(); }, [fetchLogs]);

    const refresh = () => { fetchStats(); fetchLogs(); };

    const totals = stats?.totals || {};
    const config = stats?.config || {};

    const statCards = [
        { label: 'Total Messages', val: totals.total ?? '—', icon: MessageSquare, cls: 'bg-indigo-50 text-indigo-600' },
        { label: 'Sent', val: totals.sent ?? '—', icon: CheckCircle2, cls: 'bg-emerald-50 text-emerald-600' },
        { label: 'Failed', val: totals.failed ?? '—', icon: XCircle, cls: 'bg-red-50 text-red-600' },
        { label: 'Success Rate', val: totals.success_rate != null ? `${totals.success_rate}%` : '—', icon: Activity, cls: 'bg-blue-50 text-blue-600' },
    ];

    const fmtDate = (d) => d ? new Date(d).toLocaleString(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    }) : '—';

    return (
        <div className="max-w-[1400px] mx-auto space-y-6 pb-10 px-4">
            {/* Header */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 py-2 border-b border-[var(--border)]">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-emerald-500 flex items-center justify-center text-white shadow-lg">
                        <MessageSquare size={20} />
                    </div>
                    <div>
                        <h1 className="text-2xl font-black text-[var(--text-main)] italic uppercase tracking-tighter leading-none">
                            WhatsApp <span className="text-emerald-500">Messaging</span>
                        </h1>
                        <p className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest mt-1 opacity-70">
                            Delivery analytics & logs
                        </p>
                    </div>
                </div>

                <div className="flex items-center gap-3">
                    <div className="flex bg-[var(--bg-card)] border border-[var(--border)] p-1 rounded-xl shadow-sm">
                        {RANGES.map(r => (
                            <button
                                key={r.value}
                                onClick={() => { setDays(r.value); setPage(1); }}
                                className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${days === r.value ? 'bg-black text-white shadow-md' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}
                            >
                                {r.label}
                            </button>
                        ))}
                    </div>
                    <button
                        onClick={refresh}
                        title="Refresh"
                        aria-label="Refresh"
                        className="w-9 h-9 rounded-xl bg-[var(--bg-card)] border border-[var(--border)] flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors"
                    >
                        <RefreshCw size={16} className={loadingStats || loadingLogs ? 'animate-spin' : ''} />
                    </button>
                </div>
            </div>

            {/* Config banner */}
            <div className={`flex items-center gap-3 p-3 rounded-2xl border text-[12px] font-bold ${config.configured ? 'bg-emerald-50/40 border-emerald-100 text-emerald-700' : 'bg-amber-50/40 border-amber-100 text-amber-700'}`}>
                {config.configured ? <ShieldCheck size={18} /> : <ShieldAlert size={18} />}
                {config.configured ? (
                    <span>
                        Meta WhatsApp Cloud API connected · Phone Number ID <span className="font-mono">{config.phone_number_id || 'n/a'}</span>
                        {config.business_account_id && <> · WABA <span className="font-mono">{config.business_account_id}</span></>}
                        {config.api_version && <> · API {config.api_version}</>}
                    </span>
                ) : (
                    <span>WhatsApp Cloud API is not fully configured — messages are being skipped. Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID.</span>
                )}
            </div>

            {error && (
                <div className="flex items-center gap-3 p-4 rounded-2xl bg-red-50/50 border border-red-100 text-red-700 text-[12px] font-bold">
                    <AlertTriangle size={18} /> {error}
                </div>
            )}

            {/* Stat cards */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                {statCards.map((s, idx) => (
                    <motion.div
                        key={idx}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: idx * 0.05 }}
                        className="bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-[24px] shadow-sm"
                    >
                        <div className="flex items-center gap-4">
                            <div className={`w-10 h-10 shrink-0 rounded-xl flex items-center justify-center shadow-sm ${s.cls}`}>
                                <s.icon size={18} />
                            </div>
                            <div>
                                <p className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest leading-none mb-1">{s.label}</p>
                                <h3 className="text-xl font-black text-[var(--text-main)]">{loadingStats ? '…' : s.val}</h3>
                            </div>
                        </div>
                    </motion.div>
                ))}
            </div>

            {/* Daily chart */}
            <div className="bg-[var(--bg-card)] border border-[var(--border)] p-5 rounded-[24px] shadow-sm">
                <h3 className="text-[13px] font-black text-[var(--text-main)] uppercase tracking-widest flex items-center gap-2 mb-4">
                    <Activity size={14} className="text-emerald-500" /> Daily Delivery
                </h3>
                <div style={{ width: '100%', height: 260 }}>
                    <ResponsiveContainer>
                        <BarChart data={stats?.daily || []} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} vertical={false} />
                            <XAxis
                                dataKey="date"
                                tick={{ fontSize: 10 }}
                                tickFormatter={(d) => new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                                interval="preserveStartEnd"
                                minTickGap={24}
                            />
                            <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                            <Tooltip
                                labelFormatter={(d) => new Date(d).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}
                                contentStyle={{ borderRadius: 12, border: '1px solid var(--border)', fontSize: 12, background: 'var(--bg-card)' }}
                            />
                            <Bar dataKey="sent" name="Sent" stackId="a" fill="#10b981" radius={[0, 0, 0, 0]} />
                            <Bar dataKey="failed" name="Failed" stackId="a" fill="#ef4444" radius={[4, 4, 0, 0]} />
                        </BarChart>
                    </ResponsiveContainer>
                </div>
                <div className="flex items-center gap-4 mt-2 justify-center">
                    <span className="flex items-center gap-1.5 text-[10px] font-bold text-[var(--text-muted)]"><span className="w-2.5 h-2.5 rounded-sm bg-emerald-500" /> Sent</span>
                    <span className="flex items-center gap-1.5 text-[10px] font-bold text-[var(--text-muted)]"><span className="w-2.5 h-2.5 rounded-sm bg-red-500" /> Failed</span>
                </div>
            </div>

            {/* Filters */}
            <div className="flex flex-col md:flex-row md:items-center gap-3">
                <div className="flex bg-[var(--bg-card)] border border-[var(--border)] p-1 rounded-xl shadow-sm">
                    {STATUS_FILTERS.map(s => (
                        <button
                            key={s}
                            onClick={() => { setStatusFilter(s); setPage(1); }}
                            className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${statusFilter === s ? 'bg-black text-white shadow-md' : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}
                        >
                            {s}
                        </button>
                    ))}
                </div>
                <div className="relative flex-1 max-w-sm">
                    <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
                    <input
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder="Search phone number or template…"
                        className="w-full pl-9 pr-3 py-2 rounded-xl bg-[var(--bg-card)] border border-[var(--border)] text-[12px] text-[var(--text-main)] focus:outline-none focus:border-emerald-400"
                    />
                </div>
            </div>

            {/* Logs table */}
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-sm overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="w-full text-left">
                        <thead>
                            <tr className="border-b border-[var(--border)] bg-[var(--input-bg)]">
                                {['Recipient', 'Template', 'Status', 'Details', 'Sent At'].map(h => (
                                    <th key={h} className="px-4 py-3 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap">{h}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {loadingLogs && (
                                <tr><td colSpan={5} className="px-4 py-10 text-center">
                                    <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mx-auto" />
                                </td></tr>
                            )}
                            {!loadingLogs && logsData?.logs?.map((log) => (
                                <tr key={log.id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors">
                                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-main)] font-mono whitespace-nowrap">{log.target_contact || '—'}</td>
                                    <td className="px-4 py-3 text-[11px] font-medium text-[var(--text-muted)] whitespace-nowrap">{log.template_slug || '—'}</td>
                                    <td className="px-4 py-3">
                                        <span className={`px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-wider ${statusStyles[log.status] || 'bg-gray-100 text-gray-600'}`}>
                                            {log.status || 'unknown'}
                                        </span>
                                    </td>
                                    <td className="px-4 py-3 text-[11px] text-[var(--text-muted)] max-w-xs truncate" title={log.error_message || log.content || ''}>
                                        {log.status === 'failed'
                                            ? <span className="text-red-600 font-medium">{log.error_message || 'Unknown error'}</span>
                                            : (log.content || '—')}
                                    </td>
                                    <td className="px-4 py-3 text-[11px] font-bold text-[var(--text-muted)] whitespace-nowrap">{fmtDate(log.sent_at)}</td>
                                </tr>
                            ))}
                            {!loadingLogs && (!logsData?.logs || logsData.logs.length === 0) && (
                                <tr><td colSpan={5} className="px-4 py-12 text-center">
                                    <MessageSquare size={28} className="mx-auto text-[var(--text-muted)] mb-3 opacity-20" />
                                    <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">No WhatsApp messages found</p>
                                </td></tr>
                            )}
                        </tbody>
                    </table>
                </div>

                {/* Pagination */}
                {logsData && logsData.total > 0 && (
                    <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border)]">
                        <p className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">
                            {logsData.total} message{logsData.total === 1 ? '' : 's'} · Page {logsData.page} / {logsData.total_pages}
                        </p>
                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => setPage(p => Math.max(1, p - 1))}
                                disabled={page <= 1}
                                className="w-8 h-8 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--text-muted)] disabled:opacity-30 hover:text-[var(--text-main)] transition-colors"
                            >
                                <ChevronLeft size={16} />
                            </button>
                            <button
                                onClick={() => setPage(p => (logsData && p < logsData.total_pages ? p + 1 : p))}
                                disabled={!logsData || page >= logsData.total_pages}
                                className="w-8 h-8 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--text-muted)] disabled:opacity-30 hover:text-[var(--text-main)] transition-colors"
                            >
                                <ChevronRight size={16} />
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default WhatsAppDashboard;
