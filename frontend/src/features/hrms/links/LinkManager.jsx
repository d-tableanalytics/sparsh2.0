import React, { useCallback, useEffect, useState } from 'react';
import {
  Link2, Copy, Check, Ban, RefreshCw, Eye, EyeOff, Search, Info, ChevronDown,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getHrmsLinks, revokeHrmsLink, reissueHrmsLink, linkUrlFor,
} from '../../../services/hrmsApi';

/**
 * HRMS ▸ the public-link registry (Phase 11-R, Item 1).
 *
 * One screen that answers: what candidate-facing links exist, who opened them, and how do
 * I kill one. Before this, four kinds of link were minted independently and surfaced
 * ad-hoc, with no registry, no open tracking, no expiry and no revocation.
 *
 * Status is computed SERVER-side (an expired link reads Expired without a nightly job), so
 * this screen never re-derives it — it renders what the API says, which is the same rule
 * the public handlers enforce.
 */

const FIELD = 'h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';

const STATUS_TONE = {
  Active: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Consumed: 'bg-[var(--accent-green-bg,var(--accent-indigo-bg))] text-[var(--accent-green,var(--accent-indigo))]',
  Expired: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  Revoked: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
};

const KIND_LABEL = {
  apply: 'Application',
  assessment: 'Assessment',
  offer: 'Offer',
  onboarding: 'Onboarding',
  appointment: 'Appointment',
};

const fmtDate = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString();
};

/** The permanent "how link generation works" panel.
 *
 *  Required by the review, and it stays on the page rather than living in a tooltip: the
 *  question "where do these links come from and what does revoke actually do" is asked by
 *  every new operator, and a page that answers it once in place answers it for everyone.
 *  Collapsed by default so it does not push the table down for people who already know. */
const ProcessPanel = () => {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-4 py-3 flex items-center gap-2.5 text-left"
      >
        <Info size={15} className="text-[var(--accent-indigo)] shrink-0" />
        <span className="text-[13px] font-bold text-[var(--text-main)] flex-1">
          How link generation works
        </span>
        <ChevronDown
          size={15}
          className={`text-[var(--text-muted)] transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="px-4 pb-4 pt-1 border-t border-[var(--border)] space-y-3 text-[12.5px] leading-relaxed text-[var(--text-muted)]">
          <p>
            <b className="text-[var(--text-main)]">One form, one link per purpose.</b>{' '}
            A job posting produces a single application link per channel. Assessment, offer,
            appointment and onboarding links are issued per candidate, at the moment that
            step happens — you never generate them by hand.
          </p>
          <p>
            <b className="text-[var(--text-main)]">The codes are unguessable.</b>{' '}
            Every per-candidate link carries 128 bits of cryptographic randomness. Guessing
            one is not a practical attack, and the public pages are rate limited on top of
            that.
          </p>
          <p>
            <b className="text-[var(--text-main)]">Where did you hear about this job.</b>{' '}
            The application form asks every applicant how they found the role, and the
            answer is mandatory. That is what feeds the source and referral reporting — so
            one tracked form replaces a link per platform.
          </p>
          <p>
            <b className="text-[var(--text-main)]">&ldquo;Opened&rdquo; counts page views, not people.</b>{' '}
            A link forwarded to three colleagues counts three opens. It tells you a link was
            reached; it is not a read receipt.
          </p>
          <p>
            <b className="text-[var(--text-main)]">Revoke really stops it.</b>{' '}
            A revoked link is refused by the public page from the next request onward, with
            the same neutral message a closed position gives — it never reveals that the
            link was withdrawn from that person specifically. Reissue reverses that: it
            mints a fresh code for the same record and kills the old one.
          </p>
          <p>
            <b className="text-[var(--text-main)]">External postings are not tracked, deliberately.</b>{' '}
            When a posting sends applicants to a job board or an external form, the
            applications never reach this pipeline — nothing writes them back. Those links
            are therefore absent from this register rather than shown with figures that
            would always read zero.
          </p>
        </div>
      )}
    </div>
  );
};

const Tile = ({ label, value, tone }) => (
  <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3">
    <p className="text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
      {label}
    </p>
    <p className={`text-[22px] font-bold tracking-tight mt-1 ${tone || 'text-[var(--text-main)]'}`}>
      {value}
    </p>
  </div>
);

const LinkManager = () => {
  const { scope, can, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({ kind: '', status: '', search: '' });
  const [copied, setCopied] = useState(null);
  const [busy, setBusy] = useState(null);
  const [revoking, setRevoking] = useState(null);
  const [reason, setReason] = useState('');

  const canManage = can(CAP.LINK_MANAGE);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { ...scope };
      if (filters.kind) params.kind = filters.kind;
      if (filters.status) params.status = filters.status;
      if (filters.search) params.search = filters.search;
      const { data: payload } = await getHrmsLinks(params);
      setData(payload);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the link register.');
    } finally {
      setLoading(false);
    }
  }, [companyId, filters.kind, filters.status, filters.search]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  const copy = async (row) => {
    try {
      await navigator.clipboard.writeText(linkUrlFor(row.path));
      setCopied(row.link_id);
      setTimeout(() => setCopied(null), 1600);
    } catch {
      showError('Could not copy the link.');
    }
  };

  const doRevoke = async () => {
    if (!revoking) return;
    setBusy(revoking.link_id);
    try {
      await revokeHrmsLink(revoking.link_id, { reason }, scope);
      showSuccess('The link has been revoked and will no longer open.');
      setRevoking(null);
      setReason('');
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not revoke the link.');
    } finally {
      setBusy(null);
    }
  };

  const doReissue = async (row) => {
    setBusy(row.link_id);
    try {
      const { data: result } = await reissueHrmsLink(row.link_id, scope);
      showSuccess(`A fresh link was issued (${result?.link?.link_id || 'new code'}). Send it to the candidate.`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not reissue the link.');
    } finally {
      setBusy(null);
    }
  };

  const rows = data?.links || [];
  const stats = data?.stats || {};

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={Link2}
        title="Links"
        subtitle="Every candidate-facing link this company has issued, with its opens and status"
      />
      <HrmsScopeBar />
      <ProcessPanel />

      {data?.scoped_to_own_requisitions && (
        <p className="text-[12px] text-[var(--text-muted)]">
          Showing links for requisitions you raised.
        </p>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <Tile label="Active" value={stats.active ?? 0} tone="text-[var(--accent-indigo)]" />
        <Tile label="Completed" value={stats.consumed ?? 0} />
        <Tile label="Expired" value={stats.expired ?? 0} />
        <Tile label="Revoked" value={stats.revoked ?? 0} tone="text-[var(--accent-red)]" />
        <Tile label="Never opened" value={stats.never_opened ?? 0} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            className={`${FIELD} pl-8 w-56`}
            placeholder="Code, candidate or reference"
            value={filters.search}
            onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
          />
        </div>
        <select
          className={FIELD}
          value={filters.kind}
          onChange={(e) => setFilters((f) => ({ ...f, kind: e.target.value }))}
        >
          <option value="">All kinds</option>
          {Object.entries(KIND_LABEL).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <select
          className={FIELD}
          value={filters.status}
          onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
        >
          <option value="">All statuses</option>
          {['Active', 'Consumed', 'Expired', 'Revoked'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {loading && <HrmsLoading label="Loading links…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}
      {!loading && !error && rows.length === 0 && (
        <HrmsEmpty
          icon={Link2}
          title="No links yet"
          hint="Links appear here automatically as you publish postings and issue assessments, offers, appointment letters and onboarding forms."
        />
      )}

      {!loading && !error && rows.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-x-auto">
          <table className="w-full text-[13px] min-w-[880px]">
            <thead>
              <tr className="border-b border-[var(--border)] text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                <th className="text-left px-4 py-2.5">Kind</th>
                <th className="text-left px-4 py-2.5">For</th>
                <th className="text-left px-4 py-2.5">Reference</th>
                <th className="text-left px-4 py-2.5">Status</th>
                <th className="text-right px-4 py-2.5">Opens</th>
                <th className="text-left px-4 py-2.5">Issued</th>
                <th className="text-left px-4 py-2.5">Expires</th>
                <th className="text-right px-4 py-2.5">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.link_id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-4 py-2.5 font-semibold text-[var(--text-main)]">
                    {KIND_LABEL[row.kind] || row.kind}
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-main)]">
                    {row.candidate_name || <span className="text-[var(--text-muted)]">Open posting</span>}
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">{row.target_id || '—'}</td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-block px-2 py-0.5 rounded-md text-[11px] font-bold ${STATUS_TONE[row.status] || ''}`}>
                      {row.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <span className="inline-flex items-center gap-1 text-[var(--text-main)]">
                      {row.never_opened
                        ? <EyeOff size={13} className="text-[var(--text-muted)]" />
                        : <Eye size={13} className="text-[var(--text-muted)]" />}
                      {row.open_count ?? 0}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">
                    {fmtDate(row.issued_at)}
                    {row.issued_by_name && (
                      <span className="block text-[11px]">by {row.issued_by_name}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-[var(--text-muted)]">
                    {row.expires_at || '—'}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        type="button"
                        onClick={() => copy(row)}
                        title="Copy link"
                        className="h-7 w-7 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-main)]"
                      >
                        {copied === row.link_id ? <Check size={13} /> : <Copy size={13} />}
                      </button>
                      {canManage && row.status !== 'Revoked' && (
                        <button
                          type="button"
                          onClick={() => { setRevoking(row); setReason(''); }}
                          disabled={busy === row.link_id}
                          title="Revoke"
                          className="h-7 w-7 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--accent-red)] disabled:opacity-40"
                        >
                          <Ban size={13} />
                        </button>
                      )}
                      {canManage && row.kind !== 'apply' && (
                        <button
                          type="button"
                          onClick={() => doReissue(row)}
                          disabled={busy === row.link_id}
                          title="Reissue — mints a fresh code and kills this one"
                          className="h-7 w-7 rounded-lg border border-[var(--border)] flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-main)] disabled:opacity-40"
                        >
                          <RefreshCw size={13} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {revoking && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 space-y-4">
            <div>
              <h2 className="text-[15px] font-bold text-[var(--text-main)]">Revoke this link?</h2>
              <p className="text-[12.5px] text-[var(--text-muted)] mt-1">
                The candidate&rsquo;s page will stop opening immediately. They see the same
                neutral message a closed position gives — never that it was withdrawn from
                them.
              </p>
            </div>
            <textarea
              className="w-full h-20 px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]"
              placeholder="Reason (optional, kept in the audit trail)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRevoking(null)}
                className="h-9 px-4 rounded-lg border border-[var(--border)] text-[13px] font-bold text-[var(--text-muted)]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={doRevoke}
                disabled={busy === revoking.link_id}
                className="h-9 px-4 rounded-lg bg-[var(--accent-red)] text-white text-[13px] font-bold disabled:opacity-50"
              >
                Revoke link
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default LinkManager;
