import React, { useCallback, useEffect, useState } from 'react';
import {
  Megaphone, Plus, Search, Copy, Check, ExternalLink, Radio, Users2, Trash2, Pause, Play,
} from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import {
  getPostings, updatePosting, deletePosting, applyUrlFor,
} from '../../../services/hrmsApi';
import CreatePostingModal from './CreatePostingModal';

/**
 * HRMS ▸ job postings.
 *
 * One card per posting, and one posting per role — there is no platform breakdown here
 * because a posting no longer has one. Each card shows the single link to share and copies
 * exactly that; which channel a candidate came through is answered on the form itself and
 * read from the `source` column in the pipeline.
 *
 * External postings carry a visible warning: applications made on a job board never reach
 * this pipeline. Showing an application count of 0 without that context would look like a
 * bug rather than the design.
 */

const STATUS_TONES = {
  Live: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Paused: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
  Expired: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
  Closed: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
};

const Tile = ({ icon: Icon, label, value }) => (
  <div className="p-3.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
    <div className="flex items-center gap-2 text-[var(--text-muted)]">
      <Icon size={14} />
      <span className="text-[10.5px] font-bold uppercase tracking-widest">{label}</span>
    </div>
    <p className="mt-1.5 text-[20px] font-bold text-[var(--text-main)]">{value ?? 0}</p>
  </div>
);

const PostingCard = ({ posting: p, canWrite, onCopy, copied, onStatus, onDelete }) => {
  const isExternal = p.apply_link_mode === 'external';
  const link = isExternal ? p.external_url : applyUrlFor(p.posting_code);

  return (
    <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="px-2 py-0.5 rounded-md text-[11px] font-bold bg-[var(--input-bg)] text-[var(--text-main)]">
              {isExternal ? 'External link' : 'Form link'}
            </span>
            <span className={`px-2 py-0.5 rounded-md text-[11px] font-bold ${
              STATUS_TONES[p.live_status] || 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}>
              {p.live_status}
            </span>
          </div>
          <p className="mt-1.5 text-[13.5px] font-bold text-[var(--text-main)] truncate">
            {p.title || 'Untitled role'}
          </p>
          <p className="font-mono text-[11px] text-[var(--text-muted)]">
            {p.posting_code} · {p.jd_no}
          </p>
        </div>
        <span className={`px-2 py-0.5 rounded-md text-[10.5px] font-bold shrink-0 ${
          p.requires_assessment
            ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
            : 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}>
          {p.requires_assessment ? 'Assessment required' : 'No assessment'}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        {[['Applied', p.application_count], ['Posted', p.posting_date],
          ['Expires', p.expiry_date || '—']].map(([label, value]) => (
          <div key={label} className="p-2 rounded-lg bg-[var(--input-bg)]">
            <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{label}</p>
            <p className="text-[12px] font-bold text-[var(--text-main)] truncate">{value}</p>
          </div>
        ))}
      </div>

      <div>
        <div className="flex items-center gap-2 p-2 rounded-lg bg-[var(--input-bg)]">
          <span className="flex-1 font-mono text-[11px] text-[var(--text-muted)] truncate">{link}</span>
          <button type="button" onClick={() => onCopy(p.posting_code, link)}
            title="Copy application link"
            className="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
            {copied === p.posting_code ? <Check size={14} /> : <Copy size={14} />}
          </button>
          {isExternal && (
            <a href={link} target="_blank" rel="noopener noreferrer"
              className="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--accent-indigo)]">
              <ExternalLink size={14} />
            </a>
          )}
        </div>
        {isExternal ? (
          <p className="mt-1.5 text-[11px] text-[var(--accent-red)]">
            Applications made there do not appear here — it links out to another site.
          </p>
        ) : (
          <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">
            Share this one link anywhere — applicants tell the form where they found the job.
          </p>
        )}
      </div>

      {canWrite && (
        <div className="flex items-center gap-1.5 pt-1">
          {p.live_status === 'Live' ? (
            <button type="button" onClick={() => onStatus(p, 'Paused')}
              className="h-8 px-3 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)] flex items-center gap-1.5">
              <Pause size={13} /> Pause
            </button>
          ) : (
            <button type="button" onClick={() => onStatus(p, 'Live')}
              className="h-8 px-3 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)] flex items-center gap-1.5">
              <Play size={13} /> Set live
            </button>
          )}
          <button type="button" onClick={() => onStatus(p, 'Closed')}
            className="h-8 px-3 rounded-lg border border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)]">
            Close
          </button>
          <button type="button" onClick={() => onDelete(p)} title="Delete posting"
            className="h-8 w-8 grid place-items-center rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-red)] ml-auto">
            <Trash2 size={13} />
          </button>
        </div>
      )}
    </div>
  );
};

const PostingList = () => {
  const { can, scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [data, setData] = useState({ postings: [], stats: {} });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [copied, setCopied] = useState(null);

  const canWrite = can(CAP.POSTING_WRITE);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data: res } = await getPostings({
        ...scope, search: search || undefined, live_status: status || undefined,
      });
      setData(res);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load postings.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, search, status]);

  useEffect(() => { load(); }, [load]);

  const copy = async (code, link) => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(code);
      setTimeout(() => setCopied(null), 1800);
    } catch {
      showError("Couldn't copy to clipboard.");
    }
  };

  const setStatusFor = async (p, next) => {
    try {
      await updatePosting(p.posting_code, { live_status: next }, scope);
      showSuccess(`${p.posting_code} set to ${next}`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not update the posting.');
    }
  };

  const remove = async (p) => {
    if (!window.confirm(
      `Remove posting ${p.posting_code}? Applications already received are kept.`)) return;
    try {
      await deletePosting(p.posting_code, scope);
      showSuccess(`${p.posting_code} removed`);
      load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not delete the posting.');
    }
  };

  const stats = data.stats || {};

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={Megaphone}
        title="Job Postings"
        subtitle="Publish an approved role and share its single application link anywhere."
        actions={
          <div className="flex items-center gap-2">
            <HrmsScopeBar />
            {canWrite && (
              <button type="button" onClick={() => setShowCreate(true)}
                className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5">
                <Plus size={14} /> New posting
              </button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-3 gap-3">
        <Tile icon={Radio} label="Live postings" value={stats.live} />
        <Tile icon={Users2} label="Applications" value={stats.applications} />
        <Tile icon={Megaphone} label="Postings" value={stats.postings} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by code, role or JD…"
            className="w-full h-9 pl-9 pr-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]" />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]">
          <option value="">All statuses</option>
          {['Live', 'Paused', 'Expired', 'Closed'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {loading ? (
        <HrmsLoading label="Loading postings…" />
      ) : error ? (
        <HrmsError message={error} onRetry={load} />
      ) : data.postings.length === 0 ? (
        <HrmsEmpty icon={Megaphone} title="No postings yet"
          hint={canWrite
            ? 'Publish an approved job description to start receiving applications.'
            : undefined} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {data.postings.map((p) => (
            <PostingCard key={p.posting_code} posting={p} canWrite={canWrite}
              onCopy={copy} copied={copied} onStatus={setStatusFor} onDelete={remove} />
          ))}
        </div>
      )}

      {showCreate && (
        <CreatePostingModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); load(); }}
        />
      )}
    </div>
  );
};

export default PostingList;
