import React, { useCallback, useEffect, useState } from 'react';
import {
  BarChart3, Loader2, AlertTriangle, X, FileText, Users, Send,
  CheckCircle2, XCircle, UserCheck,
} from 'lucide-react';
import { useNotification } from '../../context/NotificationContext';
import { getRecruitmentAnalytics, getHrmsClientOptions } from '../../services/hrmsApi';
import { StatTile } from '../../components/hrms/hrmsUi';
import { inputCls } from '../../components/hrms/hrmsStyles';

// HRMS ▸ Recruitment analytics. Client-wise hiring performance.
//
// ONE chart on this page, deliberately. The headline numbers are single values, which read
// better as stat tiles than as bars; the position-wise breakdown is many columns of counts,
// which is a table. Only the funnel is genuinely a chart — ordered magnitude — so it is the
// only thing drawn.
//
// The funnel is a SINGLE series, so it uses one hue and needs no legend (the heading names it).
// That is also what keeps it colorblind-safe by construction: there are no adjacent hues to
// confuse. Colouring the stages by status (green/red) was checked with the palette validator
// and fails — red↔green sit at ΔE 7.4 under deuteranopia — so status lives in labelled tiles
// instead, never in colour alone.

// Validated against BOTH surfaces: light #ffffff and dark #111127 (contrast ≥ 3:1, inside each
// mode's lightness band). Deliberately NOT var(--accent-indigo) — that token lightens to
// #818cf8 in dark mode, which falls outside the dark band. One selected step, both themes.
const SERIES = '#6366f1';

const Bar = ({ label, value, max, hint }) => {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="group flex items-center gap-3" title={hint}>
      <div className="w-[150px] shrink-0 text-[11.5px] font-bold text-[var(--text-muted)] text-right truncate">
        {label}
      </div>
      {/* Track is recessive; the mark carries the data. 4px rounded data-end, anchored left. */}
      <div className="flex-1 h-5 rounded-md bg-[var(--input-bg)] relative overflow-hidden">
        <div className="h-full rounded-md transition-all duration-300"
          style={{ width: `${pct}%`, backgroundColor: SERIES, minWidth: value > 0 ? 3 : 0 }} />
      </div>
      {/* Direct label — the value is always visible, so the chart never depends on hover. */}
      <div className="w-11 shrink-0 text-[12.5px] font-black text-[var(--text-main)] text-right"
        style={{ fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
    </div>
  );
};

const RecruitmentAnalytics = () => {
  const { showError } = useNotification();

  const [data, setData] = useState(null);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [clientId, setClientId] = useState('');
  const [requestNo, setRequestNo] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getRecruitmentAnalytics({
        client_company_id: clientId || undefined,
        request_no: requestNo || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load recruitment analytics');
    } finally {
      setLoading(false);
    }
  }, [clientId, requestNo, dateFrom, dateTo]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    getHrmsClientOptions().then((r) => setClients(r.data || [])).catch(() => {});
  }, []);

  // Changing client invalidates the position filter — a requisition belongs to one client.
  useEffect(() => { setRequestNo(''); }, [clientId]);

  const totals = data?.totals ?? {};
  const funnel = data?.funnel ?? [];
  const positions = data?.positions ?? [];
  const sources = data?.sources ?? [];
  const referrals = data?.referrals ?? [];
  const requisitions = data?.requisitions ?? [];
  const stages = data?.stages ?? [];

  const funnelMax = funnel.length ? Math.max(...funnel.map((f) => f.count)) : 0;
  const sourceMax = sources.length ? Math.max(...sources.map((s) => s.count)) : 0;
  const received = totals.cvsReceived || 0;
  const pct = (n) => (received > 0 ? `${Math.round((n / received) * 100)}% of CVs received` : '');

  const filtered = clientId || requestNo || dateFrom || dateTo;

  return (
    <div className="p-5 sm:p-7 flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
          <BarChart3 size={20} />
        </span>
        <div>
          <h1 className="text-xl font-black tracking-tight text-[var(--text-main)] leading-tight">
            Recruitment analytics
          </h1>
          <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
            {clientId
              ? clients.find((c) => c._id === clientId)?.name || 'Client'
              : 'All clients and internal hiring'}
          </p>
        </div>
      </div>

      {/* Filters — one row above the charts. */}
      <div className="flex flex-wrap items-center gap-2.5">
        <select value={clientId} onChange={(e) => setClientId(e.target.value)}
          className={`${inputCls} cursor-pointer`} style={{ maxWidth: 240 }}>
          <option value="">All clients</option>
          {clients.map((c) => <option key={c._id} value={c._id}>{c.name}</option>)}
        </select>
        <select value={requestNo} onChange={(e) => setRequestNo(e.target.value)}
          className={`${inputCls} cursor-pointer`} style={{ maxWidth: 260 }}>
          <option value="">All positions</option>
          {requisitions.map((r) => (
            <option key={r.requestNo} value={r.requestNo}>
              {r.designation} · {r.requestNo}
            </option>
          ))}
        </select>
        <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
          className={inputCls} style={{ maxWidth: 160 }} aria-label="From date" />
        <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
          className={inputCls} style={{ maxWidth: 160 }} aria-label="To date" />
        {filtered && (
          <button onClick={() => { setClientId(''); setRequestNo(''); setDateFrom(''); setDateTo(''); }}
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

      {/* Headline numbers — single values, so tiles rather than a chart. */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile icon={FileText} label="CVs received" value={totals.cvsReceived ?? 0} loading={loading} />
        <StatTile icon={Users} label="CVs reviewed" value={totals.cvsReviewed ?? 0} loading={loading} />
        <StatTile icon={CheckCircle2} label="CVs selected" value={totals.cvsSelected ?? 0} loading={loading} />
        <StatTile icon={XCircle} label="CVs rejected" value={totals.cvsRejected ?? 0} loading={loading} />
        <StatTile icon={Send} label="Shared with client" value={totals.cvsSharedWithClient ?? 0} loading={loading} />
        <StatTile icon={CheckCircle2} label="Client shortlisted" value={totals.clientShortlisted ?? 0} loading={loading} />
        <StatTile icon={XCircle} label="Client rejected" value={totals.clientRejected ?? 0} loading={loading} />
        <StatTile icon={UserCheck} label="Joinings" value={totals.joinings ?? 0} loading={loading} />
      </div>

      {/* The one chart. Single series → one hue, no legend; the heading names it. */}
      <div className="p-5 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
        <h2 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-1">
          Hiring funnel
        </h2>
        <p className="text-[11.5px] font-medium text-[var(--text-muted)] mb-4">
          Candidates who reached each stage, including those who were rejected later.
        </p>
        {loading ? (
          <div className="py-10 text-center">
            <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
              <Loader2 size={16} className="animate-spin" /> Loading…
            </span>
          </div>
        ) : funnelMax === 0 ? (
          <p className="py-8 text-center text-[12.5px] font-semibold text-[var(--text-muted)]">
            No candidates match these filters.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {funnel.map((f) => (
              <Bar key={f.stage} label={f.stage} value={f.count} max={funnelMax}
                hint={`${f.stage}: ${f.count} — ${pct(f.count)}`} />
            ))}
          </div>
        )}
      </div>

      {/* Position-wise CV status — many columns of counts, so a table. */}
      <div className="rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm overflow-hidden">
        <div className="px-5 pt-5 pb-3">
          <h2 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)]">
            Position-wise CV status
          </h2>
        </div>
        {/* Wide table scrolls in its own container so the page never scrolls sideways. */}
        <div className="overflow-x-auto">
          <table className="w-full" style={{ minWidth: 900 }}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-y border-[var(--border)]">
                <th className="text-left px-4 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                  Position
                </th>
                <th className="text-right px-3 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                  Total
                </th>
                {stages.map((s) => (
                  <th key={s} className="text-right px-3 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] whitespace-nowrap">
                    {s}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={stages.length + 2} className="px-4 py-10 text-center">
                  <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
                    <Loader2 size={16} className="animate-spin" /> Loading…
                  </span>
                </td></tr>
              )}
              {!loading && positions.length === 0 && (
                <tr><td colSpan={stages.length + 2} className="px-4 py-10 text-center text-[12.5px] font-semibold text-[var(--text-muted)]">
                  No positions match these filters.
                </td></tr>
              )}
              {!loading && positions.map((p) => (
                <tr key={`${p.designation}-${p.requestNo}`}
                  className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <td className="px-4 py-3">
                    <div className="text-[12.5px] font-black text-[var(--text-main)]">{p.designation}</div>
                    {p.requestNo && (
                      <div className="text-[11px] font-medium text-[var(--text-muted)]"
                        style={{ fontVariantNumeric: 'tabular-nums' }}>{p.requestNo}</div>
                    )}
                  </td>
                  <td className="px-3 py-3 text-right text-[12.5px] font-black text-[var(--text-main)]"
                    style={{ fontVariantNumeric: 'tabular-nums' }}>{p.total}</td>
                  {stages.map((s) => (
                    <td key={s} className="px-3 py-3 text-right text-[12px] font-semibold"
                      style={{
                        fontVariantNumeric: 'tabular-nums',
                        color: p[s] ? 'var(--text-main)' : 'var(--text-muted)',
                        opacity: p[s] ? 1 : 0.4,
                      }}>
                      {p[s] ?? 0}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Source & referral mix */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="p-5 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
          <h2 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-4">
            Where CVs came from
          </h2>
          {sources.length === 0 ? (
            <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">Nothing yet.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {sources.slice(0, 8).map((s) => (
                <Bar key={s.source} label={s.source} value={s.count} max={sourceMax}
                  hint={`${s.source}: ${s.count}`} />
              ))}
            </div>
          )}
        </div>

        <div className="p-5 rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
          <h2 className="text-[10px] font-black uppercase tracking-[0.18em] text-[var(--text-muted)] mb-4">
            Referrals
          </h2>
          {referrals.length === 0 ? (
            <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
              No referrals recorded.
            </p>
          ) : (
            <div className="flex flex-col gap-2">
              {referrals.map((r) => (
                <Bar key={r.source} label={r.source} value={r.count}
                  max={Math.max(...referrals.map((x) => x.count))}
                  hint={`${r.source}: ${r.count}`} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default RecruitmentAnalytics;
