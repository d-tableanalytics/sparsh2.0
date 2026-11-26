import React, { useCallback, useEffect, useState } from 'react';
import { Link2, RefreshCw, Copy, ExternalLink, Send, Search, CalendarClock, ArrowRight, Mail, Eye, CheckCircle2, Lock } from 'lucide-react';
import { DashboardHero, HeroButton } from '../tpms/common/dashboardKit';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { getIdfLinks, resendIdfLink } from '../../services/idfApi';
import { CARD, FIELD, TH, day, monthLabel, isStaffAdmin } from './idfKit';
import { CompanyPicker } from './IdfBits';

/* ─────────────────────────────────────────────────────────────
   Inter-Departmental Feedback ▸ Form Links (HR / Admin / MD) — the same idea as
   TPMS ▸ Form Links: every HOD's personal link to each form of a cycle, with its state.
   Copy it, open it, or email it again. Status only — never ratings or comments.
   ───────────────────────────────────────────────────────────── */

const LINK_STYLE = {
  Sent: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', icon: Mail, hint: 'not opened yet' },
  Opened: { c: 'var(--accent-orange)', bg: 'var(--accent-yellow-bg)', icon: Eye, hint: 'opened, not submitted' },
  Submitted: { c: 'var(--accent-green)', bg: 'var(--accent-green-bg)', icon: CheckCircle2, hint: 'done' },
  Closed: { c: 'var(--text-muted)', bg: 'var(--input-bg)', icon: Lock, hint: 'cycle closed' },
};
const STATUSES = ['Sent', 'Opened', 'Submitted', 'Closed'];

const LinkChip = ({ status }) => {
  const s = LINK_STYLE[status] || LINK_STYLE.Closed;
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-black whitespace-nowrap" style={{ color: s.c, background: s.bg }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.c }} />{status}
    </span>
  );
};

const initials = (name) => String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');

// The server builds the URL from Settings ▸ Application URL; if that is not set, use this site.
const fullUrl = (r) => r.link || `${window.location.origin}${r.link_path}`;

const toTime = (iso) => {
  if (!iso) return NaN;
  const s = String(iso);
  return new Date(/T/.test(s) && !/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? `${s}Z` : s).getTime();
};

const ago = (iso) => {
  const t = toTime(iso);
  if (Number.isNaN(t)) return '—';
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  if (m < 1440) return `${Math.round(m / 60)}h ago`;
  return day(iso);
};

const daysLeft = (iso) => {
  const t = toTime(iso);
  if (Number.isNaN(t)) return null;
  return Math.ceil((t - Date.now()) / 86400000);
};

const IconBtn = ({ title, onClick, href, children }) => {
  const cls = 'p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] transition-colors';
  return href
    ? <a href={href} target="_blank" rel="noopener noreferrer" title={title} aria-label={title} className={cls}>{children}</a>
    : <button type="button" title={title} aria-label={title} onClick={onClick} className={cls}>{children}</button>;
};

const IdfFormLinks = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const staff = isStaffAdmin(user);
  const [companyId, setCompanyId] = useState('');
  const cid = staff ? companyId : undefined;
  const [cycleId, setCycleId] = useState('');
  const [data, setData] = useState(null);
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    if (staff && !companyId) return;
    try {
      const { data: d } = await getIdfLinks(cycleId || undefined, cid);
      setData(d);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not load the form links.');
    }
  }, [staff, companyId, cid, cycleId, showError]);
  // Fetch on open / company / cycle change; state is set only after the request returns.
  useEffect(() => { load(); }, [load]);

  const copy = async (r) => {
    try {
      await navigator.clipboard.writeText(fullUrl(r));
      showSuccess(`Link copied — ${r.rater_name}'s form for ${r.receiver_name}.`);
    } catch {
      showError('Could not copy — open the form and copy the address instead.');
    }
  };

  const resend = async (r) => {
    setBusy(r.id);
    try {
      await resendIdfLink(r.id, cid);
      showSuccess(`Link emailed again to ${r.rater_name}.`);
      load();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not resend the link.');
    } finally {
      setBusy(null);
    }
  };

  const all = data?.links || [];
  const links = all.filter((r) =>
    (!status || r.status === status)
    && (!q || `${r.receiver_name} ${r.giver_name} ${r.rater_name} ${r.rater_email}`.toLowerCase().includes(q.toLowerCase())));
  const counts = all.reduce((m, r) => ({ ...m, [r.status]: (m[r.status] || 0) + 1 }), {});
  const cycle = data?.cycle;
  const left = cycle ? daysLeft(cycle.deadline) : null;
  const deadlineText = left == null ? '' : left < 0 ? `${-left} day${left === -1 ? '' : 's'} overdue`
    : left === 0 ? 'due today' : `${left} day${left === 1 ? '' : 's'} left`;
  const deadlineColor = left == null || cycle?.status !== 'Open' ? 'var(--text-muted)'
    : left < 0 ? 'var(--accent-red)' : left <= 2 ? 'var(--accent-orange)' : 'var(--text-muted)';

  return (
    <div className="space-y-5">
      <DashboardHero icon={Link2} title="Form Links" subtitle="Each HOD's personal feedback form link — copy, open or email it again">
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {staff && <div className={`${CARD} p-4`}><CompanyPicker value={companyId} onChange={(v) => { setCompanyId(v); setCycleId(''); }} /></div>}

      {data && (
        <div className={`${CARD} p-4 sm:p-5 space-y-4`}>
          {/* Cycle + deadline */}
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            <select aria-label="Feedback cycle" className={`${FIELD} w-full sm:w-64 font-bold`} value={cycle?.id || ''} onChange={(e) => setCycleId(e.target.value)}>
              {!data.cycles.length && <option value="">No cycles yet</option>}
              {data.cycles.map((c) => <option key={c.id} value={c.id}>{monthLabel(c.period)} · {c.status}</option>)}
            </select>
            {cycle && (
              <>
                <div className="flex items-center gap-2 text-[12px] sm:ml-auto">
                  <CalendarClock size={16} className="text-[var(--text-muted)]" />
                  <span>
                    <span className="block font-bold text-[var(--text-main)]">Deadline {day(cycle.deadline)}</span>
                    {deadlineText && cycle.status === 'Open' && <span className="block text-[11px] font-semibold" style={{ color: deadlineColor }}>{deadlineText}</span>}
                  </span>
                </div>
              </>
            )}
          </div>

          {/* Status tiles double as the filter */}
          {!!all.length && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
              {STATUSES.map((s) => {
                const st = LINK_STYLE[s];
                const Icon = st.icon;
                const on = status === s;
                return (
                  <button key={s} type="button" onClick={() => setStatus(on ? '' : s)} aria-pressed={on}
                    className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl border text-left transition-all hover:shadow-sm"
                    style={{ borderColor: on ? st.c : 'var(--border)', background: on ? st.bg : 'transparent' }}>
                    <span className="p-2 rounded-lg" style={{ color: st.c, background: st.bg }}><Icon size={15} /></span>
                    <span className="min-w-0">
                      <span className="block text-[18px] leading-tight font-black tabular-nums text-[var(--text-main)]">{counts[s] || 0}</span>
                      <span className="block text-[11px] font-bold text-[var(--text-muted)] truncate">{s} · {st.hint}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {data && (
        <div className={`${CARD} overflow-hidden`}>
          <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-[var(--border)]">
            <span className="relative flex-1 min-w-[200px] max-w-md">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input className={`${FIELD} w-full pl-9`} placeholder="Search department, HOD or email" value={q} onChange={(e) => setQ(e.target.value)} />
            </span>
            <span className="text-[11.5px] font-semibold text-[var(--text-muted)]">
              Showing {links.length} of {all.length}{status && <> · <button type="button" className="text-[var(--accent-indigo)] hover:underline" onClick={() => setStatus('')}>clear filter</button></>}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-[var(--input-bg)]"><tr>
                <th className={TH}>Feedback</th><th className={TH}>HOD</th>
                <th className={TH}>Status</th><th className={TH}>Last sent</th><th className={`${TH} text-right`}>Actions</th>
              </tr></thead>
              <tbody>
                {links.map((r) => {
                  const live = r.status === 'Sent' || r.status === 'Opened';
                  return (
                    <tr key={r.id} className="border-t border-[var(--border)] hover:bg-[var(--input-bg)]">
                      <td className="px-4 py-3">
                        <span className="flex items-center gap-2 text-[13px] whitespace-nowrap">
                          <span className="text-[var(--text-muted)] font-semibold">{r.giver_name}</span>
                          <ArrowRight size={13} className="text-[var(--text-muted)]" />
                          <span className="font-black text-[var(--text-main)]">{r.receiver_name}</span>
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="flex items-center gap-2.5">
                          <span className="w-8 h-8 shrink-0 rounded-full grid place-items-center text-[11px] font-black text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]">{initials(r.rater_name)}</span>
                          <span className="min-w-0">
                            <span className="block text-[13px] font-bold text-[var(--text-main)] truncate">{r.rater_name || '—'}</span>
                            <span className="block text-[11px] text-[var(--text-muted)] truncate">{r.rater_email || ''}</span>
                          </span>
                        </span>
                      </td>
                      <td className="px-4 py-3"><LinkChip status={r.status} /></td>
                      <td className="px-4 py-3 text-[12.5px] text-[var(--text-main)] whitespace-nowrap">
                        <span title={r.last_sent_at ? day(r.last_sent_at) : ''}>{ago(r.last_sent_at)}</span>
                        {r.send_count > 1 && <span className="block text-[11px] text-[var(--text-muted)]">sent {r.send_count}×</span>}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-0.5 whitespace-nowrap">
                          <IconBtn title="Copy link" onClick={() => copy(r)}><Copy size={15} /></IconBtn>
                          <IconBtn title="Open the form (opens for the HOD it belongs to)" href={r.link_path}><ExternalLink size={15} /></IconBtn>
                          {live && (
                            <button type="button" disabled={busy === r.id} onClick={() => resend(r)}
                              className="ml-1 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[11.5px] font-black hover:opacity-90 disabled:opacity-50">
                              <Send size={12} /> {busy === r.id ? 'Sending…' : 'Resend'}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {!links.length && (
                  <tr><td className="px-4 py-10 text-center text-[12.5px] text-[var(--text-muted)]" colSpan={5}>
                    {cycle ? 'No links match.' : 'No feedback cycle yet — links are created when a cycle starts.'}
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <p className="text-[11.5px] text-[var(--text-muted)]">
        Each link opens only for the HOD it was sent to. Reminders go out automatically — use Resend to email one now.
      </p>
    </div>
  );
};

export default IdfFormLinks;
