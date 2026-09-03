import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { FileText, Search, Save, Rocket, ExternalLink } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { CAP } from '../access';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { getJds, updateJd } from '../../../services/hrmsApi';

/**
 * HRMS ▸ job description library.
 *
 * A view/edit library, not an approval queue. JDs are authored with their requisition and
 * approved together, so there is deliberately no "New JD" and no approve/reject here — the
 * source's standalone JD workflow was removed and its route left behind as dead code
 * (BACKEND_ANALYSIS §5.3); we simply never built it.
 *
 * An Approved JD is read-only: it is what the MD signed off on and what candidates will be
 * shown. The server enforces the same rule with a 409.
 */

const STATUS_TONES = {
  'Pending Approval': 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Approved: 'bg-[var(--input-bg)] text-[var(--text-main)]',
  Rejected: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
  Draft: 'bg-[var(--input-bg)] text-[var(--text-muted)]',
};

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] disabled:opacity-60';
const AREA = 'w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)] resize-none disabled:opacity-60';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

const JdLibrary = () => {
  const { can, scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);

  const canWrite = can(CAP.JD_WRITE);
  const locked = selected?.status === 'Approved';

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const { data } = await getJds({ ...scope, status: status || undefined, search: search || undefined });
      const list = data?.job_descriptions || [];
      setRows(list);
      setSelected((prev) => (prev ? list.find((j) => j.jd_no === prev.jd_no) || null : null));
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load job descriptions.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, status, search]);

  useEffect(() => { load(); }, [load]);

  const select = (jd) => {
    setSelected(jd);
    setForm({
      title: jd.title || '', responsibilities: jd.responsibilities || '',
      skills: jd.skills || '', qualifications: jd.qualifications || '',
      experience: jd.experience || '', ctc: jd.ctc || '',
      location: jd.location || '', benefits: jd.benefits || '',
    });
  };

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await updateJd(selected.jd_no, form, scope);
      showSuccess(`${selected.jd_no} saved`);
      setSelected(data);
      await load();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save the job description.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <HrmsLoading label="Loading job descriptions…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={FileText}
        title="Job Descriptions"
        subtitle="JDs are authored with their requisition and approved together — manage them from the requisition."
        actions={
          <div className="flex items-center gap-2">
            <HrmsScopeBar />
            <Link to="/hrms/requisitions"
              className="h-9 px-3.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)] flex items-center gap-1.5">
              <ExternalLink size={14} /> Go to requisitions
            </Link>
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by JD number or title…"
            className="w-full h-9 pl-9 pr-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]" />
        </div>
        <select value={status} onChange={(e) => setStatus(e.target.value)}
          className="h-9 px-2.5 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] font-semibold text-[var(--text-main)]">
          <option value="">All statuses</option>
          {['Pending Approval', 'Approved', 'Rejected'].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {rows.length === 0 ? (
        <HrmsEmpty icon={FileText} title="No job descriptions yet"
          hint="JDs are created with their requisition in Hiring Requisitions." />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="space-y-2 lg:max-h-[70vh] lg:overflow-y-auto">
            {rows.map((jd) => (
              <button key={jd.jd_no} type="button" onClick={() => select(jd)}
                className={`w-full text-left p-3 rounded-xl border transition-colors ${
                  selected?.jd_no === jd.jd_no
                    ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]'
                    : 'border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--accent-indigo)]'}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11.5px] text-[var(--text-muted)]">{jd.jd_no}</span>
                  <span className={`px-2 py-0.5 rounded-md text-[10.5px] font-bold ${
                    STATUS_TONES[jd.status] || 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}>
                    {jd.status}
                  </span>
                </div>
                <p className="mt-1 text-[13px] font-semibold text-[var(--text-main)] truncate">
                  {jd.title || 'Untitled'}
                </p>
                <p className="text-[11.5px] text-[var(--text-muted)]">{jd.request_no}</p>
              </button>
            ))}
          </div>

          <div className="lg:col-span-2">
            {!selected ? (
              <HrmsEmpty icon={FileText} title="Select a job description"
                hint="Pick one from the list to view or edit its content." />
            ) : (
              <div className="p-4 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] space-y-4">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <p className="font-mono text-[12px] text-[var(--text-muted)]">{selected.jd_no}</p>
                    <p className="text-[15px] font-bold text-[var(--text-main)]">{selected.title || 'Untitled'}</p>
                    <p className="text-[12px] text-[var(--text-muted)]">
                      Linked to {selected.request_no} · v{selected.version || 1}
                    </p>
                  </div>
                  {locked ? (
                    <span className="h-8 px-3 rounded-lg bg-[var(--input-bg)] text-[var(--text-main)] text-[12px] font-bold flex items-center gap-1.5">
                      <Rocket size={14} /> Posting enabled
                    </span>
                  ) : canWrite && (
                    <button type="button" onClick={save} disabled={saving}
                      className="h-8 px-3.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5 disabled:opacity-50">
                      <Save size={14} /> {saving ? 'Saving…' : 'Save'}
                    </button>
                  )}
                </div>

                {locked && (
                  <div className="p-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12px] text-[var(--text-muted)]">
                    This JD is approved and locked — it is what the MD signed off on and what
                    candidates will see. Raise a new requisition to hire on different terms.
                  </div>
                )}
                {selected.status === 'Pending Approval' && (
                  <div className="p-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12px] text-[var(--text-muted)]">
                    Approved together with requisition{' '}
                    <Link to="/hrms/requisitions" className="font-bold text-[var(--accent-indigo)]">
                      {selected.request_no}
                    </Link> — HR reviews it and the MD approves it as one decision.
                  </div>
                )}
                {selected.status === 'Rejected' && selected.md_remarks && (
                  <div className="p-3 rounded-lg border border-[var(--accent-red)]/30 bg-[var(--accent-red-bg)] text-[12px] text-[var(--accent-red)]">
                    Rejected: {selected.md_remarks}
                  </div>
                )}

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className={LABEL} htmlFor="jd-title">Title</label>
                    <input id="jd-title" value={form.title} onChange={set('title')} disabled={locked || !canWrite} className={FIELD} />
                  </div>
                  <div>
                    <label className={LABEL} htmlFor="jd-loc">Location</label>
                    <input id="jd-loc" value={form.location} onChange={set('location')} disabled={locked || !canWrite} className={FIELD} />
                  </div>
                  <div>
                    <label className={LABEL} htmlFor="jd-exp">Experience</label>
                    <input id="jd-exp" value={form.experience} onChange={set('experience')} disabled={locked || !canWrite} className={FIELD} />
                  </div>
                  <div>
                    <label className={LABEL} htmlFor="jd-ctc">CTC</label>
                    <input id="jd-ctc" value={form.ctc} onChange={set('ctc')} disabled={locked || !canWrite} className={FIELD} />
                  </div>
                </div>

                <div>
                  <label className={LABEL} htmlFor="jd-resp">Responsibilities</label>
                  <textarea id="jd-resp" rows={5} value={form.responsibilities} onChange={set('responsibilities')}
                    disabled={locked || !canWrite} className={AREA} />
                </div>
                <div>
                  <label className={LABEL} htmlFor="jd-skills">Skills</label>
                  <textarea id="jd-skills" rows={2} value={form.skills} onChange={set('skills')}
                    disabled={locked || !canWrite} className={AREA} />
                </div>
                <div>
                  <label className={LABEL} htmlFor="jd-qual">Qualifications</label>
                  <textarea id="jd-qual" rows={2} value={form.qualifications} onChange={set('qualifications')}
                    disabled={locked || !canWrite} className={AREA} />
                </div>
                <div>
                  <label className={LABEL} htmlFor="jd-ben">Benefits</label>
                  <textarea id="jd-ben" rows={2} value={form.benefits} onChange={set('benefits')}
                    disabled={locked || !canWrite} className={AREA} />
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default JdLibrary;
