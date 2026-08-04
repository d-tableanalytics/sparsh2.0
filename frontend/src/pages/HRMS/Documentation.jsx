import React, { useCallback, useEffect, useState } from 'react';
import {
  FolderOpen, Plus, Search, X, Loader2, AlertTriangle, Upload, Download,
  CheckCircle2, XCircle, Clock, FileText, RefreshCw,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import {
  getDocuments, createDocument, updateDocument, getDocumentUrl,
} from '../../services/hrmsApi';
import { hasHrmsPermission } from '../../utils/hrmsAccess';
import { StatTile, Field } from '../../components/hrms/hrmsUi';
import { inputCls, fmtDate } from '../../components/hrms/hrmsStyles';

// HRMS ▸ Documentation. One library for employee AND candidate documents.
//
// Status is the point of this screen: Pending means "we still need this", Uploaded means "it
// arrived, nobody has checked it", Verified/Rejected are HR's verdict, and Expired is derived
// from the date rather than stored — so a document that lapses overnight reads correctly on the
// next load without anything having to sweep it.
//
// Files are never fetched directly: the download button asks the server for a short-lived
// signed URL, matching how punch selfies are served.

const MAX_MB = 5;

const STATUS_TONE = {
  Pending:  { fg: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)', border: 'var(--accent-yellow-border)', Icon: Clock },
  Uploaded: { fg: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', border: 'var(--accent-indigo-border)', Icon: FileText },
  Verified: { fg: 'var(--status-active-text)', bg: 'var(--status-active-bg)', border: 'var(--status-active-border)', Icon: CheckCircle2 },
  Rejected: { fg: 'var(--accent-red)', bg: 'var(--accent-red-bg)', border: 'var(--accent-red-border)', Icon: XCircle },
  Expired:  { fg: 'var(--accent-orange)', bg: 'var(--accent-orange-bg)', border: 'var(--accent-orange-border)', Icon: AlertTriangle },
};

const StatusChip = ({ status }) => {
  const tone = STATUS_TONE[status] || STATUS_TONE.Pending;
  const Icon = tone.Icon;
  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[9px] font-black uppercase tracking-widest border whitespace-nowrap"
      style={{ color: tone.fg, backgroundColor: tone.bg, borderColor: tone.border }}>
      <Icon size={11} /> {status}
    </span>
  );
};

const EMPTY = {
  owner_type: 'employee', owner_id: '', doc_type: 'Aadhaar', title: '',
  remarks: '', expires_on: '', file: null,
};

const Documentation = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();

  const canAddEmployee = hasHrmsPermission(user, 'hrms', 'create');
  const canAddCandidate = hasHrmsPermission(user, 'recruitment', 'create');
  const canAdd = canAddEmployee || canAddCandidate;
  const canUpdate = hasHrmsPermission(user, 'hrms', 'update')
    || hasHrmsPermission(user, 'recruitment', 'update');

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [ownerFilter, setOwnerFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [fileName, setFileName] = useState('');
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await getDocuments({
        search: search || undefined,
        owner_type: ownerFilter || undefined,
        status: statusFilter || undefined,
      });
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load documents');
    } finally {
      setLoading(false);
    }
  }, [search, ownerFilter, statusFilter]);

  useEffect(() => { load(); }, [load]);

  const rows = data?.documents ?? [];
  const stats = data?.stats ?? {};
  const docTypes = data?.docTypes ?? [];
  const statuses = data?.statuses ?? [];

  const onFile = (e, setter) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Checked here for a fast message; the server enforces the same cap and type allow-list.
    if (file.size > MAX_MB * 1024 * 1024) {
      showError(`That file is larger than ${MAX_MB} MB.`);
      e.target.value = '';
      return;
    }
    const reader = new FileReader();
    reader.onload = () => { setter(reader.result); setFileName(file.name); };
    reader.onerror = () => showError('That file could not be read.');
    reader.readAsDataURL(file);
  };

  const submit = async () => {
    if (!form.owner_id.trim()) { showError('Enter the employee code or candidate ID'); return; }
    setSaving(true);
    try {
      await createDocument({ ...form, expires_on: form.expires_on || null });
      showSuccess('Document registered');
      setShowForm(false);
      setForm(EMPTY);
      setFileName('');
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save document');
    } finally {
      setSaving(false);
    }
  };

  const setStatus = async (doc, status) => {
    setBusy(doc.id);
    try {
      await updateDocument(doc.id, { status });
      showSuccess(`${doc.documentNo} marked ${status}`);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update document');
    } finally {
      setBusy('');
    }
  };

  const replaceFile = async (doc, dataUrl) => {
    setBusy(doc.id);
    try {
      await updateDocument(doc.id, { file: dataUrl });
      showSuccess(`${doc.documentNo} updated`);
      load();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to upload file');
    } finally {
      setBusy('');
    }
  };

  const download = async (doc) => {
    setBusy(doc.id);
    try {
      const res = await getDocumentUrl(doc.id);
      window.open(res.data.url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to open document');
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="p-5 sm:p-7 flex flex-col gap-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="w-11 h-11 rounded-2xl flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
            <FolderOpen size={20} />
          </span>
          <div>
            <h1 className="text-xl font-black tracking-tight text-[var(--text-main)] leading-tight">
              Documentation
            </h1>
            <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
              Employee and candidate documents, with status tracking
            </p>
          </div>
        </div>
        {canAdd && (
          <button onClick={() => { setForm(EMPTY); setFileName(''); setShowForm(true); }}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[12px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] transition-all">
            <Plus size={15} /> Add document
          </button>
        )}
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <StatTile icon={FileText} label="Total" value={stats.total ?? 0} loading={loading} />
        <StatTile icon={Clock} label="Pending" value={stats.Pending ?? 0} loading={loading} />
        <StatTile icon={FileText} label="Uploaded" value={stats.Uploaded ?? 0} loading={loading} />
        <StatTile icon={CheckCircle2} label="Verified" value={stats.Verified ?? 0} loading={loading} />
        <StatTile icon={AlertTriangle} label="Expired" value={stats.Expired ?? 0} loading={loading} />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input className={`${inputCls} pl-9`} placeholder="Search name, type or document no."
            value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select value={ownerFilter} onChange={(e) => setOwnerFilter(e.target.value)}
          className={`${inputCls} cursor-pointer`} style={{ maxWidth: 180 }}>
          <option value="">All owners</option>
          <option value="employee">Employees</option>
          <option value="candidate">Candidates</option>
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
          className={`${inputCls} cursor-pointer`} style={{ maxWidth: 180 }}>
          <option value="">All statuses</option>
          {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {(search || ownerFilter || statusFilter) && (
          <button onClick={() => { setSearch(''); setOwnerFilter(''); setStatusFilter(''); }}
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
          <table className="w-full" style={{ minWidth: 900 }}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                {['Document', 'Owner', 'Type', 'Status', 'Expires', 'Actions'].map((h, i) => (
                  <th key={i} className="text-left px-4 py-3 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={6} className="px-4 py-12 text-center">
                  <span className="inline-flex items-center gap-2 text-[13px] font-bold text-[var(--text-muted)]">
                    <Loader2 size={16} className="animate-spin" /> Loading…
                  </span>
                </td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-12 text-center">
                  <p className="text-[13px] font-bold text-[var(--text-main)]">No documents.</p>
                  <p className="text-[12px] font-medium text-[var(--text-muted)] mt-1">
                    {canAdd ? 'Add one to start tracking.' : 'Nothing recorded yet.'}
                  </p>
                </td></tr>
              )}
              {!loading && rows.map((d) => (
                <tr key={d.id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <td className="px-4 py-3">
                    <div className="text-[12.5px] font-black text-[var(--text-main)]">
                      {d.title || d.docType}
                    </div>
                    <div className="text-[11px] font-medium text-[var(--text-muted)]"
                      style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {d.documentNo}{d.version > 0 ? ` · v${d.version}` : ''}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-[12px] font-bold text-[var(--text-main)]">
                      {d.ownerName || d.ownerId}
                    </div>
                    <div className="text-[11px] font-medium text-[var(--text-muted)] capitalize">
                      {d.ownerType}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]">{d.docType}</td>
                  <td className="px-4 py-3"><StatusChip status={d.status} /></td>
                  <td className="px-4 py-3 text-[12px] font-semibold text-[var(--text-muted)]">
                    {d.expiresOn ? fmtDate(d.expiresOn) : '—'}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {d.hasFile && (
                        <button onClick={() => download(d)} disabled={busy === d.id}
                          title="Open document"
                          className="p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] disabled:opacity-50 transition-colors">
                          <Download size={13} />
                        </button>
                      )}
                      {canUpdate && (
                        <>
                          <label title={d.hasFile ? 'Replace file' : 'Upload file'}
                            className="p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:border-[var(--accent-indigo)] cursor-pointer transition-colors">
                            {d.hasFile ? <RefreshCw size={13} /> : <Upload size={13} />}
                            <input type="file" className="hidden"
                              accept=".pdf,.doc,.docx,.jpg,.jpeg,.png"
                              onChange={(e) => onFile(e, (url) => replaceFile(d, url))} />
                          </label>
                          {d.status !== 'Verified' && d.hasFile && (
                            <button onClick={() => setStatus(d, 'Verified')} disabled={busy === d.id}
                              title="Mark verified"
                              className="p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--status-active-text)] hover:border-[var(--status-active-text)] disabled:opacity-50 transition-colors">
                              <CheckCircle2 size={13} />
                            </button>
                          )}
                          {d.status !== 'Rejected' && d.hasFile && (
                            <button onClick={() => setStatus(d, 'Rejected')} disabled={busy === d.id}
                              title="Reject"
                              className="p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:border-[var(--accent-red)] disabled:opacity-50 transition-colors">
                              <XCircle size={13} />
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add document */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
          <div className="w-full max-w-lg rounded-2xl bg-[var(--bg-card)] border border-[var(--border)] shadow-xl overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
              <h2 className="text-[13px] font-black uppercase tracking-widest text-[var(--text-main)]">
                Add document
              </h2>
              <button onClick={() => setShowForm(false)} className="text-[var(--text-muted)]">
                <X size={18} />
              </button>
            </div>
            <div className="p-6 grid grid-cols-1 sm:grid-cols-2 gap-3.5 max-h-[70vh] overflow-y-auto">
              <Field label="Owner" required>
                <select className={inputCls} value={form.owner_type}
                  onChange={(e) => setForm({ ...form, owner_type: e.target.value })}>
                  {canAddEmployee && <option value="employee">Employee</option>}
                  {canAddCandidate && <option value="candidate">Candidate</option>}
                </select>
              </Field>
              <Field label={form.owner_type === 'employee' ? 'Employee code' : 'Candidate ID'} required>
                <input className={inputCls} value={form.owner_id}
                  placeholder={form.owner_type === 'employee' ? 'EMP-2026-0001' : 'CAN-2026-0001'}
                  onChange={(e) => setForm({ ...form, owner_id: e.target.value })} />
              </Field>
              <Field label="Document type" required>
                <input className={inputCls} list="doc-types" value={form.doc_type}
                  onChange={(e) => setForm({ ...form, doc_type: e.target.value })} />
                <datalist id="doc-types">
                  {docTypes.map((t) => <option key={t} value={t} />)}
                </datalist>
              </Field>
              <Field label="Title">
                <input className={inputCls} value={form.title} placeholder="Optional label"
                  onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </Field>
              <Field label="Expires on">
                <input type="date" className={inputCls} value={form.expires_on}
                  onChange={(e) => setForm({ ...form, expires_on: e.target.value })} />
              </Field>
              <Field label="File">
                {/* Optional: leaving it empty records the document as Pending, which is how a
                    document you are still waiting for is tracked. */}
                <label className="flex items-center gap-2 px-3 py-2 rounded-xl border border-dashed border-[var(--border)] text-[11.5px] font-bold text-[var(--text-muted)] cursor-pointer">
                  <Upload size={14} /> {fileName || 'Choose a file (optional)'}
                  <input type="file" className="hidden" accept=".pdf,.doc,.docx,.jpg,.jpeg,.png"
                    onChange={(e) => onFile(e, (url) => setForm((f) => ({ ...f, file: url })))} />
                </label>
              </Field>
              <div className="sm:col-span-2">
                <Field label="Remarks">
                  <textarea rows={2} className={`${inputCls} resize-y`} value={form.remarks}
                    onChange={(e) => setForm({ ...form, remarks: e.target.value })} />
                </Field>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2.5 px-6 py-4 border-t border-[var(--border)] bg-[var(--table-header-bg)]">
              <button onClick={() => setShowForm(false)}
                className="px-5 py-2.5 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                Cancel
              </button>
              <button onClick={submit} disabled={saving}
                className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest disabled:opacity-50">
                {saving && <Loader2 size={14} className="animate-spin" />} Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Documentation;
