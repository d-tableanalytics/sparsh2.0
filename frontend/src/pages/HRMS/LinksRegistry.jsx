import React, { useCallback, useEffect, useState } from 'react';
import {
  Link2, Search, X, Loader2, AlertTriangle, Eye, Copy, Check, Ban,
  ExternalLink, Activity,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { getLinks, revealLink, revokeLink } from '../../services/hrmsApi';
import { hasHrmsPermission } from '../../utils/hrmsAccess';
import { StatTile } from '../../components/hrms/hrmsUi';
import { inputCls, fmtDateTime } from '../../components/hrms/hrmsStyles';

// HRMS ▸ Links. Every public link the HRMS has issued, with its tracking.
//
// This list never contains access codes. Revealing one is an explicit, per-link action that
// needs the update grant and is written to that link's audit trail before the code comes back —
// which is how "trackable and easily accessible whenever required" is delivered without
// reinstating the leak that a code-bearing list endpoint would be.
//
// The reveal panel shows the URL once, to the person who asked. Reload and it is gone again.

const TYPE_LABEL = {
  posting: 'Job posting',
  assessment: 'Assessment',
  offer: 'Offer',
  appointment: 'Appointment letter',
  onboarding: 'Onboarding / KYC',
};

const STATUS_TONE = {
  Active:  { fg: 'var(--status-active-text)', bg: 'var(--status-active-bg)', border: 'var(--status-active-border)' },
  Used:    { fg: 'var(--text-muted)', bg: 'var(--input-bg)', border: 'var(--border)' },
  Expired: { fg: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', border: 'var(--accent-orange-border)' },
  Revoked: { fg: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)' },
};

const StatusChip = ({ status }) => {
  const tone = STATUS_TONE[status] || STATUS_TONE.Active;
  return (
    <span className="inline-block px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest border whitespace-nowrap"
      style={{ color: tone.fg, backgroundColor: tone.bg, borderColor: tone.border }}>
      {status}
    </span>
  );
};

const LinksRegistry = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();

  const canManage = hasHrmsPermission(user, 'recruitment', 'update');

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  const [busy, setBusy] = useState('');
  const [revealed, setRevealed] = useState(null);   // { name, url } — shown once
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getLinks({
        search: search || undefined,
        link_type: typeFilter || undefined,
        status: statusFilter || undefined,
      });
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load links');
    } finally {
      setLoading(false);
    }
  }, [search, typeFilter, statusFilter]);

  useEffect(() => { load(); }, [load]);

  const rows = data?.links ?? [];
  const stats = data?.stats ?? {};
  const linkTypes = data?.linkTypes ?? [];
  const statuses = data?.statuses ?? [];

  const reveal = async (row) => {
    setBusy(row.id);
    try {
      const res = await revealLink(row.id);
      setRevealed({
        name: row.candidateName || row.label || TYPE_LABEL[row.linkType] || 'Link',
        url: `${window.location.origin}${res.data.path}/${res.data.code}`,
      });
      setCopied(false);
      load();   // reveal count just changed
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to reveal link');
    } finally {
      setBusy('');
    }
  };

  const revoke = async (row) => {
    setBusy(row.id);
    try {
      await revokeLink(row.id);
      showSuccess('Link revoked');
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to revoke link');
    } finally {
      setBusy('');
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(revealed.url);
      setCopied(true);
    } catch {
      showError('Could not copy — select the link and copy manually.');
    }
  };

  return (
    <div className="p-5 sm:p-7 flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
          <Link2 size={20} />
        </span>
        <div>
          <h1 className="text-xl font-black tracking-tight text-[var(--text-main)] leading-tight">
            Links
          </h1>
          <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
            Every public link issued, and whether it has been opened
          </p>
        </div>
      </div>

      {/* Revealed link — shown once, to whoever asked. */}
      {revealed && (
        <div className="p-4 rounded-2xl border flex flex-col gap-3"
          style={{ backgroundColor: 'var(--accent-indigo-bg)', borderColor: 'var(--accent-indigo-border)' }}>
          <div className="flex items-center justify-between gap-3">
            <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: 'var(--accent-indigo)' }}>
              Link for {revealed.name}
            </span>
            <button onClick={() => setRevealed(null)} className="text-[var(--text-muted)]">
              <X size={16} />
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <code className="flex-1 min-w-[240px] px-3 py-2 rounded-lg bg-[var(--bg-card)] border border-[var(--border)] text-[12px] font-mono text-[var(--text-main)] break-all">
              {revealed.url}
            </code>
            <button onClick={copy}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-white text-[11px] font-black uppercase tracking-widest"
              style={{ backgroundColor: 'var(--btn-primary)' }}>
              {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <p className="text-[11.5px] font-semibold text-[var(--text-muted)]">
            This reveal has been recorded against the link. Close this panel and the code is
            hidden again.
          </p>
        </div>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <StatTile icon={Link2} label="Total" value={stats.total ?? 0} loading={loading} />
        <StatTile icon={Activity} label="Active" value={stats.Active ?? 0} loading={loading} />
        <StatTile icon={Check} label="Used" value={stats.Used ?? 0} loading={loading} />
        <StatTile icon={AlertTriangle} label="Expired" value={stats.Expired ?? 0} loading={loading} />
        <StatTile icon={Ban} label="Revoked" value={stats.Revoked ?? 0} loading={loading} />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input className={`${inputCls} pl-9`} placeholder="Search candidate, requisition or label"
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}
          className={`${inputCls} cursor-pointer`} style={{ maxWidth: 200 }}>
          <option value="">All types</option>
          {linkTypes.map((t) => <option key={t} value={t}>{TYPE_LABEL[t] || t}</option>)}
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
          className={`${inputCls} cursor-pointer`} style={{ maxWidth: 180 }}>
          <option value="">All statuses</option>
          {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {(search || typeFilter || statusFilter) && (
          <button onClick={() => { setSearch(''); setTypeFilter(''); setStatusFilter(''); }}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
            <X size={13} /> Clear
          </button>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2.5 px-4 py-3 rounded-xl border text-[12px] font-bold"
          style={{ color: 'var(--accent-red)', backgroundColor: 'var(--accent-red-bg)', borderColor: 'var(--accent-red-border)' }}>
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {/* Table */}
      <div className="rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full" style={{ minWidth: 1000 }}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                {['Link', 'For', 'Status', 'Opens', 'Last opened', 'Reveals', ''].map((h, i) => (
                  <th key={i} className="text-left px-4 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={7} className="px-4 py-12 text-center">
                  <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
                    <Loader2 size={16} className="animate-spin" /> Loading…
                  </span>
                </td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-12 text-center">
                  <p className="text-[13px] font-bold text-[var(--text-main)]">No links yet.</p>
                  <p className="text-[12px] font-medium text-[var(--text-muted)] mt-1">
                    Publishing a posting or sending an assessment, offer or letter records one here.
                  </p>
                </td></tr>
              )}
              {!loading && rows.map((l) => (
                <tr key={l.id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <td className="px-4 py-3">
                    <div className="text-[12.5px] font-black text-[var(--text-main)]">
                      {TYPE_LABEL[l.linkType] || l.linkType}
                    </div>
                    <div className="text-[11px] font-medium text-[var(--text-muted)]">{l.label}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-[12px] font-bold text-[var(--text-main)]">
                      {l.candidateName || '—'}
                    </div>
                    <div className="text-[11px] font-medium text-[var(--text-muted)]"
                      style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {l.requestNo || l.candidateUk}
                    </div>
                  </td>
                  <td className="px-4 py-3"><StatusChip status={l.status} /></td>
                  <td className="px-4 py-3 text-[12.5px] font-black text-[var(--text-main)]"
                    style={{ fontVariantNumeric: 'tabular-nums' }}>{l.openedCount}</td>
                  <td className="px-4 py-3 text-[11.5px] font-semibold text-[var(--text-muted)]">
                    {l.lastOpenedAt ? fmtDateTime(l.lastOpenedAt) : 'Never'}
                  </td>
                  <td className="px-4 py-3 text-[11.5px] font-semibold text-[var(--text-muted)]">
                    {l.revealCount > 0
                      ? `${l.revealCount} · ${l.lastRevealedBy || ''}`
                      : '—'}
                  </td>
                  <td className="px-4 py-3">
                    {canManage && (
                      <div className="flex items-center gap-1.5">
                        <button onClick={() => reveal(l)} disabled={busy === l.id || l.status === 'Revoked'}
                          title="Reveal and copy the link (recorded)"
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--border)] text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] disabled:opacity-40 transition-colors">
                          <Eye size={12} /> Reveal
                        </button>
                        {l.status !== 'Revoked' && (
                          <button onClick={() => revoke(l)} disabled={busy === l.id}
                            title="Revoke this link"
                            className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:border-[var(--accent-red)] disabled:opacity-40 transition-colors">
                            <Ban size={12} />
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default LinksRegistry;
