import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, Link2 as LinkIcon, Copy, Check, ExternalLink, Send, AlertTriangle, Inbox, Trash2 } from 'lucide-react';
import { DashboardHero, HeroButton, Section, TableShell, Th, Td, usePaged, Pager } from '../../common/dashboardKit';
import { getCompanies, getFormAssignments, resendFormAssignment, deleteFormAssignment } from '../../../../services/tpmsFormsApi';
import { currentPeriod, periodLabel } from '../../../../services/tpmsApi';
import { useNotification } from '../../../../context/NotificationContext';

/* ─────────────────────────────────────────────────────────────
   TPMS ▸ Admin ▸ Form Links.
   Every unique, single-use form link (Accountability / Ownership / Culture /
   Implementation Feedback) per company + month, with copy, open, resend and delete.
   Data: GET /forms/assignments  ·  resend: POST /forms/assignments/{id}/resend  ·  delete: DELETE /forms/assignments/{id}
   ───────────────────────────────────────────────────────────── */

const FORM_LABEL = {
  accountability: 'Accountability',
  ownership: 'Ownership',
  culture: 'Culture',
  implementation_feedback: 'Implementation Feedback',
};

const STATUS_TONE = {
  submitted: { c: 'var(--accent-green)', bg: 'var(--accent-green-bg)' },
  opened: { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)' },
  sent: { c: 'var(--text-muted)', bg: 'var(--input-bg)' },
  expired: { c: 'var(--accent-red)', bg: 'var(--accent-red-bg)' },
  pending: { c: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)' },
};

const selectCls =
  'h-9 px-3 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[12.5px] font-semibold text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]';

const monthOptions = () => {
  const out = [];
  const base = new Date();
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(base.getFullYear(), base.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    out.push({ value, label: periodLabel(value) || value });
  }
  return out;
};

const fullUrl = (link) => (!link ? '' : link.startsWith('http') ? link : window.location.origin + link);

const StatusPill = ({ status }) => {
  const t = STATUS_TONE[status] || STATUS_TONE.sent;
  return (
    <span className="inline-flex items-center text-[10px] font-bold tracking-wide px-2.5 py-1 rounded-full capitalize"
      style={{ color: t.c, background: t.bg }}>
      {status || '—'}
    </span>
  );
};

const FormLinks = () => {
  const { showSuccess, showError } = useNotification();
  const months = useMemo(() => monthOptions(), []);
  const [companies, setCompanies] = useState([]);
  const [company, setCompany] = useState('');
  const [period, setPeriod] = useState(currentPeriod());
  const [formType, setFormType] = useState('');
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copiedId, setCopiedId] = useState('');
  const [resending, setResending] = useState('');
  const [deletingId, setDeletingId] = useState('');

  useEffect(() => {
    getCompanies()
      .then((res) => setCompanies((res.data || []).map((c) => ({ id: String(c._id || c.id), name: c.name || c._id }))))
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getFormAssignments({ company_id: company || undefined, period: period || undefined });
      setRows(res.data?.assignments || []);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load form links.');
    } finally {
      setLoading(false);
    }
  }, [company, period]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(
    () => (formType ? rows.filter((r) => r.form_type === formType) : rows),
    [rows, formType],
  );
  const paged = usePaged(filtered, 15);

  const copy = async (row) => {
    try {
      await navigator.clipboard.writeText(fullUrl(row.link));
      setCopiedId(row.id);
      setTimeout(() => setCopiedId(''), 1600);
    } catch {
      showError('Could not copy — select the link and copy manually.');
    }
  };

  const resend = async (row) => {
    if (!row.respondent_email) { showError('This recipient has no email on file.'); return; }
    setResending(row.id);
    try {
      await resendFormAssignment(row.id);
      showSuccess(`Link re-sent to ${row.respondent_email}`);
      load();
    } catch (e) {
      showError(e.response?.data?.detail || 'Resend failed.');
    } finally {
      setResending('');
    }
  };

  const handleDelete = async (row) => {
    if (!window.confirm(`Are you sure you want to delete the form link for ${row.respondent_name || 'this respondent'}?`)) return;
    setDeletingId(row.id);
    try {
      await deleteFormAssignment(row.id);
      showSuccess('Form link deleted successfully');
      load();
    } catch (e) {
      showError(e.response?.data?.detail || 'Delete failed.');
    } finally {
      setDeletingId('');
    }
  };

  return (
    <div className="space-y-5">
      <DashboardHero icon={LinkIcon} title="Form Links" subtitle="Unique monthly form links per company & HOD — copy, open, resend or delete">
        <select value={company} onChange={(e) => setCompany(e.target.value)} className={selectCls}>
          <option value="">All companies</option>
          {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select value={period} onChange={(e) => setPeriod(e.target.value)} className={selectCls}>
          {months.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
        <select value={formType} onChange={(e) => setFormType(e.target.value)} className={selectCls}>
          <option value="">All forms</option>
          {Object.entries(FORM_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      <Section title="Generated links" icon={LinkIcon}
        subtitle={filtered.length ? `${filtered.length} link${filtered.length === 1 ? '' : 's'}` : 'Nothing for this selection'}>
        {loading && !rows.length ? (
          <div className="px-5 py-16 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading…</div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-14 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--input-bg)] text-[var(--text-muted)] flex items-center justify-center"><Inbox size={20} /></span>
            <p className="text-[13px] font-bold text-[var(--text-main)]">No form links yet</p>
            <p className="text-[12px] text-[var(--text-muted)] max-w-md">
              Links are created when a form activity (Accountability &amp; Ownership Rating, Culture Rating,
              Implementation Update Feedback) is <b>scheduled</b> for this company &amp; month.
            </p>
          </div>
        ) : (
          <>
            <TableShell minWidth={1000}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th>Form</Th><Th>HOD / MD</Th><Th>Company</Th>
                  <Th align="center">Status</Th><Th>Link</Th><Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {paged.pageRows.map((r) => (
                  <tr key={r.id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                    <Td className="font-bold whitespace-nowrap">{FORM_LABEL[r.form_type] || r.form_type}</Td>
                    <Td>
                      <div className="font-semibold">{r.respondent_name || '—'}</div>
                      <div className="text-[11px] text-[var(--text-muted)]">{r.respondent_email || 'no email'}</div>
                    </Td>
                    <Td className="text-[var(--text-muted)] whitespace-nowrap">{r.company_name || r.company_id}</Td>
                    <Td align="center"><StatusPill status={r.status} /></Td>
                    <Td>
                      <code className="text-[11px] text-[var(--text-muted)] font-mono truncate inline-block max-w-[260px] align-middle">{r.link}</code>
                    </Td>
                    <Td align="right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button type="button" onClick={() => copy(r)} title="Copy link"
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90">
                          {copiedId === r.id ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy</>}
                        </button>
                        <a href={fullUrl(r.link)} target="_blank" rel="noreferrer" title="Open form"
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)]">
                          <ExternalLink size={12} /> Open
                        </a>
                        <button type="button" onClick={() => resend(r)} disabled={resending === r.id || !r.respondent_email} title="Email this link again"
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-green)] bg-[var(--accent-green-bg)] border border-[var(--accent-green-border)] hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed">
                          <Send size={12} /> {resending === r.id ? 'Sending…' : 'Resend'}
                        </button>
                        <button type="button" onClick={() => handleDelete(r)} disabled={deletingId === r.id} title="Delete form link"
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-red)] bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed">
                          <Trash2 size={12} /> {deletingId === r.id ? 'Deleting…' : 'Delete'}
                        </button>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
            <Pager {...paged} label="links" />
          </>
        )}
      </Section>
    </div>
  );
};

export default FormLinks;
