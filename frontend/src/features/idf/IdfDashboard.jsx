import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ShieldCheck, RefreshCw, Download, FileSpreadsheet, FileText, AlertTriangle, ChevronDown, TrendingUp, TrendingDown,
  CheckCircle2, CircleDot, BellRing, ArrowRight, ThumbsUp, Wrench, MessageSquare,
  Compass, ShieldHalf, MessageSquareReply, Megaphone, CalendarCheck,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { getIdfDashboard, downloadIdfReport } from '../../services/idfApi';
import { BAND_STYLE, CARD, FIELD, bandOf, monthLabel, pctText, saveBlob, isStaffAdmin } from './idfKit';
import { CompanyPicker } from './IdfBits';

/* ─────────────────────────────────────────────────────────────
   Inter-Departmental Feedback ▸ Management Dashboard (client document §9) — ONE SCREEN.
   The company MD, and the Sparsh Super Admin / Admin for the company they pick.

   Layout: a compact header (cycle, refresh, download) · six headline tiles · two tabbed
   panels that fill the rest of the viewport and scroll inside, so the page itself does not:
     left  — Departments (ranking + change) · Matrix · Trend
     right — Needs attention · Parameters · Comments · Follow-up (actions, you said we did, issues)
   A one-line footer carries the leadership focus and the no-retaliation statement.
   ───────────────────────────────────────────────────────────── */

const DOWNLOADS = [
  ['compiled', FileSpreadsheet, 'Compiled Excel', 'Full feedback, client format'],
  ['analysis', FileSpreadsheet, 'Analysis Excel', 'All 8 reports'],
  ['pdf', FileText, 'PDF report', 'Printable report package'],
];
const tone = (pct) => BAND_STYLE[bandOf(pct)] || null;
const TH = 'px-2 py-2 text-[10px] font-black uppercase tracking-wide text-[var(--text-muted)] whitespace-nowrap';
// The two panels fill what is left of the viewport below the header, tiles and footer.
const PANEL_H = 'lg:h-[calc(100vh-318px)] lg:min-h-[340px]';

const Tile = ({ label, value, sub, color, subColor, onClick }) => {
  const Tag = onClick ? 'button' : 'div';
  return (
    <Tag type={onClick ? 'button' : undefined} onClick={onClick}
      className={`${CARD} min-w-0 px-3.5 py-2.5 text-left ${onClick ? 'hover:shadow-sm transition-shadow' : ''}`}>
      <p className="text-[10px] font-black uppercase tracking-wide text-[var(--text-muted)] truncate">{label}</p>
      <p className="text-[21px] leading-tight font-black tabular-nums truncate" style={{ color: color || 'var(--text-main)' }}>{value}</p>
      <p className="text-[11px] font-semibold truncate" style={{ color: subColor || 'var(--text-muted)' }}>{sub || ' '}</p>
    </Tag>
  );
};

// A card with tabs; its body scrolls inside the fixed panel height.
const TabPanel = ({ tabs, active, onChange, children, right }) => (
  <div className={`${CARD} flex flex-col overflow-hidden ${PANEL_H}`}>
    <div className="flex items-center gap-1 border-b border-[var(--border)] px-2 pt-2">
      <div className="no-scrollbar flex min-w-0 flex-1 gap-0.5 overflow-x-auto">
        {tabs.map(([k, label, count]) => (
          <button key={k} type="button" onClick={() => onChange(k)}
            className={`shrink-0 whitespace-nowrap rounded-t-lg border-b-2 px-2.5 py-2 text-[12px] font-black transition-colors ${active === k
              ? 'border-[var(--accent-indigo)] text-[var(--accent-indigo)]'
              : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
            {label}{count != null && <span className="ml-1.5 rounded-full bg-[var(--input-bg)] px-1.5 text-[10px]">{count}</span>}
          </button>
        ))}
      </div>
      {right}
    </div>
    <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
  </div>
);

const Change = ({ value, dropped }) => {
  if (value == null) return <span className="w-12 text-right text-[11px] text-[var(--text-muted)]">—</span>;
  const down = value < 0;
  const Arrow = down ? TrendingDown : TrendingUp;
  return (
    <span className="w-12 inline-flex items-center justify-end gap-0.5 text-[11px] font-bold tabular-nums"
      style={{ color: down || dropped ? 'var(--accent-red)' : 'var(--accent-green)' }}>
      <Arrow size={11} />{value > 0 ? '+' : ''}{value}
    </span>
  );
};

const ScoreCell = ({ pct, strong }) => {
  const t = tone(pct);
  return (
    <td className="px-1.5 py-1 text-center">
      {pct == null ? <span className="text-[11px] text-[var(--text-muted)]">—</span> : (
        <span className={`inline-block min-w-[48px] rounded-md px-1.5 py-0.5 text-[11px] tabular-nums ${strong ? 'font-black' : 'font-bold'}`}
          style={{ color: t?.c, background: t?.bg }}>{pctText(pct)}</span>
      )}
    </td>
  );
};

const Empty = ({ children }) => <p className="px-4 py-8 text-center text-[12px] text-[var(--text-muted)]">{children}</p>;

const DownloadMenu = ({ onPick, busy }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)} disabled={!!busy}
        className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-black disabled:opacity-60">
        <Download size={13} /> {busy ? 'Preparing…' : 'Download'} <ChevronDown size={13} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-1.5 w-64 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl py-1">
            {DOWNLOADS.map((row) => {
              const [k, FileIcon, label, hint] = row;
              return (
                <button key={k} type="button" onClick={() => { setOpen(false); onPick(k); }}
                  className="w-full flex items-start gap-2.5 px-3 py-2 text-left hover:bg-[var(--input-bg)]">
                  <FileIcon size={15} className="mt-0.5 text-[var(--accent-indigo)]" />
                  <span>
                    <span className="block text-[12.5px] font-bold text-[var(--text-main)]">{label}</span>
                    <span className="block text-[11px] text-[var(--text-muted)]">{hint}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
};

const IdfDashboard = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { showError } = useNotification();
  const staff = isStaffAdmin(user);
  const [companyId, setCompanyId] = useState('');
  const cid = staff ? companyId : undefined;
  const [cycleId, setCycleId] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [downloading, setDownloading] = useState('');
  const [left, setLeft] = useState('departments');
  const [right, setRight] = useState('attention');
  const [commentDept, setCommentDept] = useState('');

  const load = useCallback(async () => {
    if (staff && !companyId) return;          // a Sparsh Admin picks the company first
    setLoading(true); setError(null);
    try {
      const { data: d } = await getIdfDashboard(cycleId || undefined, cid);
      setData(d);
      if (!cycleId && d.result) setCycleId(d.result.cycle.id);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Could not load the dashboard.');
    } finally {
      setLoading(false);
    }
  }, [staff, companyId, cid, cycleId]);
  // Fetch on open / company / cycle change; state is set only after the request returns.
  useEffect(() => { load(); }, [load]);

  const pickCompany = (v) => { setCompanyId(v); setCycleId(''); setData(null); setCommentDept(''); };

  const download = async (kind) => {
    if (!data?.result) return;
    setDownloading(kind);
    try {
      const res = await downloadIdfReport(data.result.cycle.id, kind, cid);
      const p = data.result.cycle.period;
      saveBlob(res.data, kind === 'pdf' ? `Interdepartmental_Feedback_Report_${p}.pdf`
        : `Interdepartmental_Feedback_${kind === 'compiled' ? 'Compiled' : 'Analysis'}_${p}.xlsx`);
    } catch {
      showError('Could not download the report.');
    } finally {
      setDownloading('');
    }
  };

  const r = data?.result;
  const ranked = useMemo(() => (r ? [...r.departments].sort((a, b) => (b.pct ?? -1) - (a.pct ?? -1)) : []), [r]);
  const delta = r && r.company.previous_pct != null && r.company.pct != null
    ? Number((r.company.pct - r.company.previous_pct).toFixed(1)) : null;
  const matrix = useMemo(() => {
    if (!r) return null;
    const givers = [...new Set(r.relationships.map((x) => x.from))].sort((a, b) => a.localeCompare(b));
    return { givers, cell: Object.fromEntries(r.relationships.map((x) => [`${x.to}|${x.from}`, x.pct])) };
  }, [r]);
  const trend = useMemo(() => data?.trend || [], [data]);
  const trendDepts = useMemo(() => [...new Set(trend.flatMap((t) => Object.keys(t.departments || {})))].sort((a, b) => a.localeCompare(b)), [trend]);
  const withComments = ranked.filter((d) => d.strengths.length || d.improvements.length || d.comments.length);
  const shownDept = withComments.find((d) => d.id === commentDept) || withComments[withComments.length - 1];
  const acts = data?.actions || {};
  const resp = data?.responses || {};
  const issues = data?.issues || {};

  const header = (
    <div className="flex flex-wrap items-center gap-2.5">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-indigo)] text-white"><ShieldCheck size={19} /></span>
      <div className="mr-auto min-w-0">
        <h1 className="text-[17px] font-black leading-tight text-[var(--text-main)]">Inter-Departmental Feedback</h1>
        <p className="text-[11.5px] text-[var(--text-muted)]">{staff ? 'Management dashboard — Sparsh Admin view' : 'Management dashboard — confidential, MD only'}</p>
      </div>
      {staff && <CompanyPicker value={companyId} onChange={pickCompany} className="w-full sm:w-56 font-bold" />}
      {r && (
        <select aria-label="Feedback cycle" className={`${FIELD} w-full sm:w-56 font-bold`} value={cycleId} onChange={(e) => setCycleId(e.target.value)}>
          {data.cycles.map((c) => (
            <option key={c.id} value={c.id}>{monthLabel(c.period)} — {c.status}{c.source === 'import' ? ' (imported)' : ''}{c.cycle_type === 'pulse' ? ' (pulse)' : ''}</option>
          ))}
        </select>
      )}
      <button type="button" onClick={load} title="Refresh" aria-label="Refresh"
        className="p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
        <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
      </button>
      {r && (r.cycle.status === 'Completed' ? <DownloadMenu onPick={download} busy={downloading} /> : (
        <span className="rounded-lg border border-dashed border-[var(--border)] px-3 py-2 text-[11.5px] font-bold text-[var(--text-muted)]"
          title="The final report is generated and emailed to the MD once every feedback form is submitted.">
          Report once all feedback is in ({r.completion.completed}/{r.completion.total})
        </span>
      ))}
    </div>
  );

  if (!r) {
    return (
      <div className="space-y-4">
        {header}
        {loading && !data && <p className="text-[12.5px] font-bold text-[var(--text-muted)]">Loading…</p>}
        {error && <p className="text-[12.5px] font-bold text-[var(--accent-red)]">{error}</p>}
        {staff && !companyId && <div className={`${CARD} p-8 text-center text-[12.5px] text-[var(--text-muted)]`}>Choose a company to see its dashboard.</div>}
        {data && !loading && <div className={`${CARD} p-8 text-center text-[12.5px] text-[var(--text-muted)]`}>No feedback cycles yet. HR/Admin start a cycle under Feedback Cycles.</div>}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {header}

      {r.cycle.status === 'Open' && (
        <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3 py-1.5 text-[12px] font-semibold text-[var(--accent-orange)]">
          <AlertTriangle size={14} className="shrink-0" /> Still collecting feedback ({r.completion.completed}/{r.completion.total}) — scores are provisional.
        </div>
      )}

      {/* Headline tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-2.5">
        <Tile label="Company score" value={pctText(r.company.pct)} color={BAND_STYLE[r.company.band]?.c}
          sub={delta == null ? `${r.company.band || ''} · ${r.company.stage || ''}` : `${delta >= 0 ? '▲ +' : '▼ '}${delta} vs last · ${r.company.stage || ''}`}
          subColor={delta == null ? undefined : delta >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'} />
        <Tile label="Completion" value={`${r.completion.percent}%`} sub={`${r.completion.completed} of ${r.completion.total} submitted`} />
        <Tile label="Weakest parameter" value={pctText(r.company.weakest_param_pct)} color={tone(r.company.weakest_param_pct)?.c}
          sub={r.company.weakest_param || '—'} />
        <Tile label="Red relationships" value={r.hotspots.length} color={r.hotspots.length ? 'var(--accent-red)' : 'var(--accent-green)'}
          sub="below 60%" onClick={() => setRight('attention')} />
        <Tile label="Action plans" value={acts.open ?? 0} sub={`open · ${acts.overdue ?? 0} overdue`}
          subColor={acts.overdue ? 'var(--accent-red)' : undefined} onClick={() => navigate('/idf/actions')} />
        <Tile label="You said, we did" value={resp.total ? `${resp.submitted}/${resp.total}` : '—'}
          sub={resp.total ? (resp.overdue ? `${resp.overdue} overdue` : 'departments answered') : 'after results'}
          subColor={resp.overdue ? 'var(--accent-red)' : undefined} onClick={() => setRight('followup')} />
      </div>

      {/* Two tabbed panels — fill the screen, scroll inside */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
        <div className="lg:col-span-7 min-w-0">
          <TabPanel active={left} onChange={setLeft}
            tabs={[['departments', 'Departments', ranked.length], ['matrix', 'Matrix'], ['trend', 'Trend']]}>
            {left === 'departments' && (
              <ul className="divide-y divide-[var(--border)]">
                {ranked.map((d) => {
                  const b = d.band || bandOf(d.pct);
                  return (
                    <li key={d.id} className="flex items-center gap-3 px-4 py-2">
                      <span className="w-36 min-w-0">
                        <span className="block truncate text-[12.5px] font-bold text-[var(--text-main)]" title={d.name}>{d.name}</span>
                        <span className="block text-[10.5px] font-semibold text-[var(--text-muted)]">{d.stage || '—'}</span>
                      </span>
                      <div className="flex-1 h-2 rounded-full bg-[var(--input-bg)] overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, d.pct || 0))}%`, background: b ? BAND_STYLE[b].c : 'var(--text-muted)' }} />
                      </div>
                      <span className="w-12 text-right text-[12.5px] font-black tabular-nums" style={{ color: b ? BAND_STYLE[b].c : 'var(--text-muted)' }}>{pctText(d.pct)}</span>
                      <Change value={d.change} dropped={d.dropped} />
                    </li>
                  );
                })}
                {!ranked.length && <Empty>No scores yet.</Empty>}
              </ul>
            )}
            {left === 'matrix' && (matrix.givers.length ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="sticky top-0 bg-[var(--bg-card)]"><tr className="border-b border-[var(--border)]">
                    <th className={`${TH} text-left pl-4`}>Rated ↓ · Rating →</th>
                    {matrix.givers.map((g) => <th key={g} className={`${TH} text-center`}>{g}</th>)}
                    <th className={`${TH} text-center pr-4`}>Overall</th>
                  </tr></thead>
                  <tbody>
                    {ranked.map((d) => (
                      <tr key={d.id} className="border-b border-[var(--border)] last:border-0">
                        <td className="pl-4 pr-2 py-1 text-[12px] font-bold text-[var(--text-main)] whitespace-nowrap">{d.name}</td>
                        {matrix.givers.map((g) => <ScoreCell key={g} pct={matrix.cell[`${d.name}|${g}`]} />)}
                        <ScoreCell pct={d.pct} strong />
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Empty>No ratings yet.</Empty>)}
            {left === 'trend' && (trend.length ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="sticky top-0 bg-[var(--bg-card)]"><tr className="border-b border-[var(--border)]">
                    <th className={`${TH} text-left pl-4`}>Department</th>
                    {trend.map((t) => <th key={t.period} className={`${TH} text-center`}>{monthLabel(t.period)}</th>)}
                    <th className={`${TH} text-center pr-4`}>Move</th>
                  </tr></thead>
                  <tbody>
                    <tr className="border-b border-[var(--border)] bg-[var(--input-bg)]">
                      <td className="pl-4 pr-2 py-1 text-[12px] font-black text-[var(--text-main)]">Company</td>
                      {trend.map((t) => <ScoreCell key={t.period} pct={t.company_pct} strong />)}
                      <td className="pr-4 text-center"><Change value={trend.length > 1 && trend[trend.length - 1].company_pct != null && trend[0].company_pct != null
                        ? Number((trend[trend.length - 1].company_pct - trend[0].company_pct).toFixed(1)) : null} /></td>
                    </tr>
                    {trendDepts.map((n) => {
                      const vals = trend.map((t) => t.departments?.[n]).filter((v) => v != null);
                      const move = vals.length > 1 ? Number((vals[vals.length - 1] - vals[0]).toFixed(1)) : null;
                      return (
                        <tr key={n} className="border-b border-[var(--border)] last:border-0">
                          <td className="pl-4 pr-2 py-1 text-[12px] font-bold text-[var(--text-main)] whitespace-nowrap">{n}</td>
                          {trend.map((t) => <ScoreCell key={t.period} pct={t.departments?.[n]} />)}
                          <td className="pr-4 text-center"><Change value={move} dropped={move != null && move <= -5} /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {trend.length === 1 && <p className="px-4 py-2 text-[11px] text-[var(--text-muted)]">The trend builds up as more cycles complete.</p>}
              </div>
            ) : <Empty>The trend appears once a cycle is completed.</Empty>)}
          </TabPanel>
        </div>

        <div className="lg:col-span-5 min-w-0">
          <TabPanel active={right} onChange={setRight}
            tabs={[['attention', 'Needs attention', r.hotspots.length], ['parameters', 'Parameters'], ['comments', 'Comments'], ['followup', 'Follow-up']]}
>
            {right === 'attention' && (r.hotspots.length ? (
              <ul className="divide-y divide-[var(--border)]">
                {[...r.hotspots].sort((a, b) => a.pct - b.pct).map((h) => (
                  <li key={`${h.from}>${h.to}`} className="flex items-center justify-between gap-3 px-4 py-2.5">
                    <span className="min-w-0">
                      <span className="block truncate text-[12.5px] font-bold text-[var(--text-main)]">{h.from} → {h.to}</span>
                      <span className="block truncate text-[11px] text-[var(--text-muted)]">Red repair{h.weakest ? ` · weakest: ${h.weakest}` : ''}</span>
                    </span>
                    <span className="text-[14px] font-black tabular-nums text-[var(--accent-red)]">{pctText(h.pct)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="flex items-center gap-2 px-4 py-6 text-[12.5px] font-semibold text-[var(--accent-green)]">
                <CheckCircle2 size={16} /> No relationship below 60%.
              </p>
            ))}
            {right === 'parameters' && (
              <ul className="divide-y divide-[var(--border)]">
                {r.parameters.map((p) => {
                  const pct = r.company.param_pct[p.code];
                  const t = tone(pct);
                  const low = ranked.filter((d) => d.param_pct[p.code] != null)
                    .reduce((m, d) => (!m || d.param_pct[p.code] < m.param_pct[p.code] ? d : m), null);
                  return (
                    <li key={p.code} className="px-4 py-2.5 space-y-1.5">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="truncate text-[12.5px] font-bold text-[var(--text-main)]">{p.name}</span>
                        <span className="text-[15px] font-black tabular-nums" style={{ color: t?.c }}>{pctText(pct)}</span>
                      </div>
                      <div className="h-1.5 rounded-full bg-[var(--input-bg)] overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, pct || 0))}%`, background: t?.c || 'var(--text-muted)' }} />
                      </div>
                      <p className="truncate text-[11px] text-[var(--text-muted)]">Lowest: {low ? <><b className="text-[var(--text-main)]">{low.name}</b> {pctText(low.param_pct[p.code])}</> : '—'}</p>
                    </li>
                  );
                })}
              </ul>
            )}
            {right === 'comments' && (shownDept ? (
              <div className="space-y-3 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]">Feedback for</span>
                  <select aria-label="Department" className={`${FIELD} w-44 py-1.5 text-[12px] font-bold`} value={shownDept?.id || ''} onChange={(e) => setCommentDept(e.target.value)}>
                    {withComments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                  </select>
                </div>
                {[
                  ['Does well', shownDept.strengths, ThumbsUp, 'var(--accent-green)'],
                  ['Should improve', shownDept.improvements, Wrench, 'var(--accent-orange)'],
                  ['Comments on ratings', shownDept.comments, MessageSquare, 'var(--accent-indigo)'],
                ].map((row) => {
                  const [label, items, ListIcon, c] = row;
                  return items.length ? (
                    <div key={label} className="space-y-1.5">
                      <p className="flex items-center gap-1.5 text-[10.5px] font-black uppercase tracking-wide" style={{ color: c }}><ListIcon size={12} /> {label} ({items.length})</p>
                      {items.map((it, i) => (
                        <div key={i} className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-1.5">
                          <p className="text-[12px] leading-snug text-[var(--text-main)]">{it.text}</p>
                          <p className="text-[10.5px] font-bold text-[var(--text-muted)]">From {it.from}{it.parameter ? ` · ${it.parameter}` : ''}</p>
                        </div>
                      ))}
                    </div>
                  ) : null;
                })}
              </div>
            ) : <Empty>No comments yet.</Empty>)}
            {right === 'followup' && (
              <div className="space-y-2.5 p-3">
                <div className="grid grid-cols-2 gap-2">
                  {[
                    ['Open', acts.open ?? 0, CircleDot, 'var(--accent-indigo)', 'var(--accent-indigo-bg)'],
                    ['Overdue', acts.overdue ?? 0, AlertTriangle, 'var(--accent-red)', 'var(--accent-red-bg)'],
                    ['Review due', acts.review_due ?? 0, BellRing, 'var(--accent-orange)', 'var(--accent-yellow-bg)'],
                    ['Closed', acts.closed ?? 0, CheckCircle2, 'var(--accent-green)', 'var(--accent-green-bg)'],
                  ].map((row) => {
                    const [label, n, StatIcon, c, bg] = row;
                    return (
                      <div key={label} className="flex items-center gap-2.5 rounded-lg border border-[var(--border)] px-2.5 py-2">
                        <span className="rounded-md p-1.5" style={{ color: c, background: bg }}><StatIcon size={13} /></span>
                        <span><span className="block text-[16px] font-black leading-tight tabular-nums text-[var(--text-main)]">{n}</span>
                          <span className="block text-[10.5px] font-bold text-[var(--text-muted)]">{label} actions</span></span>
                      </div>
                    );
                  })}
                </div>
                <button type="button" onClick={() => navigate('/idf/actions')}
                  className="flex w-full items-center justify-between rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] font-bold text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]">
                  Open Action Plans <ArrowRight size={13} />
                </button>
                <div className="flex items-start gap-2.5 rounded-lg border border-[var(--border)] px-3 py-2">
                  <MessageSquareReply size={15} className="mt-0.5 shrink-0 text-[var(--accent-indigo)]" />
                  <p className="text-[12px] text-[var(--text-main)]">
                    <b>You said, we did:</b> {resp.total ? `${resp.submitted} of ${resp.total} departments answered their raters` : 'created when the results are out'}
                    {resp.pending?.length ? <span className="block text-[11px] text-[var(--text-muted)]">Waiting for: {resp.pending.join(', ')}</span> : null}
                  </p>
                </div>
                <button type="button" onClick={() => navigate('/idf/issues')}
                  className="flex w-full items-start gap-2.5 rounded-lg border border-[var(--border)] px-3 py-2 text-left hover:bg-[var(--input-bg)]">
                  <Megaphone size={15} className="mt-0.5 shrink-0 text-[var(--accent-orange)]" />
                  <span className="text-[12px] text-[var(--text-main)]"><b>Raised issues:</b> {issues.open ?? 0} open{issues.new ? ` · ${issues.new} new` : ''} · {issues.resolved ?? 0} resolved</span>
                </button>
                {data.results_meeting_date && (
                  <div className="flex items-center gap-2.5 rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] text-[var(--text-main)]">
                    <CalendarCheck size={15} className="shrink-0 text-[var(--accent-green)]" />
                    <span><b>Results meeting</b> with all HODs: {new Date(`${data.results_meeting_date}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}</span>
                  </div>
                )}
              </div>
            )}
          </TabPanel>
        </div>
      </div>

      {/* One-line footer: leadership focus + no retaliation */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 px-1 text-[11.5px] text-[var(--text-muted)]">
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <Compass size={13} className="shrink-0 text-[var(--accent-indigo)]" />
          <b className="text-[var(--text-main)]">Leadership focus{r.company.stage ? ` (${r.company.stage})` : ''}:</b>
          <span className="truncate">{data.leadership_focus || '—'}</span>
        </span>
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <ShieldHalf size={13} className="shrink-0" /><span className="truncate">{data.no_retaliation}</span>
        </span>
      </div>
    </div>
  );
};

export default IdfDashboard;
