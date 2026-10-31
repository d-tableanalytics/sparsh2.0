import React, { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { X, Download, Upload, CheckCircle2, AlertTriangle, FileSpreadsheet, RefreshCw, Repeat } from 'lucide-react';
import api from '../../services/api';
import { downloadTaskImportTemplate, bulkImportTasks } from '../../services/taskApi';
import { getTaskCategories } from '../../services/taskMetaApi';
import { useNotification } from '../../context/NotificationContext';

const errText = (err, fallback) => {
  const d = err?.response?.data?.detail;
  return typeof d === 'string' ? d : fallback;
};
const todayIso = () => new Date().toLocaleDateString('en-CA');
const personLabel = (u) => (u.full_name && u.email && u.full_name !== u.email
  ? `${u.full_name} <${u.email}>` : (u.email || u.full_name || ''));
const INPUT = 'w-full px-2 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg text-[11.5px] font-bold outline-none focus:border-[var(--accent-indigo)]';
const LABEL = 'text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest';

/**
 * Delegation ▸ Bulk import. Download the template (its Category and Assign To columns are
 * dropdowns of your categories and the people you may assign to), upload the filled sheet for a
 * PREVIEW — nothing is created yet — then import the valid rows.
 *
 * A row the sheet left incomplete (no due date above all, or a category / person that was not
 * recognised) can be corrected right here: the values go back with the file as `overrides`, so
 * nobody has to return to Excel to set a deadline. Re-check, then import.
 */
const BulkImportTasksModal = ({ isOpen, onClose, onImported }) => {
  const { showSuccess, showError } = useNotification();
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [fixes, setFixes] = useState({});        // { row: { deadline_date, deadline_time, category, assignees } }
  const [dirty, setDirty] = useState(false);     // corrections made since the last preview
  const [bulkDate, setBulkDate] = useState('');
  const [categories, setCategories] = useState([]);
  const [people, setPeople] = useState([]);

  useEffect(() => {
    if (!isOpen) return;
    getTaskCategories({ active_only: true })
      .then(({ data }) => setCategories((data || []).map((c) => c.name).filter(Boolean)))
      .catch(() => setCategories([]));
    api.get('/tasks/assignable-users')
      .then(({ data }) => setPeople((data || []).map(personLabel).filter(Boolean)))
      .catch(() => setPeople([]));
  }, [isOpen]);

  if (!isOpen) return null;

  const reset = () => {
    setFile(null); setPreview(null); setResult(null); setFixes({}); setDirty(false); setBulkDate('');
    if (fileRef.current) fileRef.current.value = '';
  };
  const close = () => { reset(); onClose(); };

  const downloadTemplate = async () => {
    try {
      const res = await downloadTaskImportTemplate();
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = 'delegation_bulk_import_template.xlsx';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      showError(errText(err, 'Could not download the template.'));
    }
  };

  const runPreview = async (chosen, withFixes) => {
    setBusy(true); setResult(null);
    try {
      const { data } = await bulkImportTasks(chosen, true, withFixes);
      setPreview(data);
      setDirty(false);
    } catch (err) {
      setPreview(null);
      showError(errText(err, 'Could not read this file.'));
    } finally {
      setBusy(false);
    }
  };

  const runImport = async () => {
    setBusy(true);
    try {
      const { data } = await bulkImportTasks(file, false, fixes);
      setResult(data);
      if (data.created) {
        showSuccess(`${data.created} task(s) created${data.invalid ? `, ${data.invalid} skipped` : ''}.`);
        onImported?.();
      } else {
        showError('No task was created — fix the rows listed and try again.');
      }
    } catch (err) {
      showError(errText(err, 'The import failed.'));
    } finally {
      setBusy(false);
    }
  };

  const fixOf = (r, key, fallback = '') => (fixes[r.row]?.[key] ?? fallback);
  const setFix = (row, key, value) => {
    setFixes((f) => ({ ...f, [row]: { ...(f[row] || {}), [key]: value } }));
    setDirty(true);
  };
  const needsDate = (r) => r.errors?.some((e) => e.startsWith('Deadline Date'));
  const applyBulkDate = () => {
    if (!bulkDate) return;
    setFixes((f) => {
      const next = { ...f };
      preview.rows.filter(needsDate).forEach((r) => { next[r.row] = { ...(next[r.row] || {}), deadline_date: bulkDate }; });
      return next;
    });
    setDirty(true);
  };

  const shown = result || preview;
  const okCount = shown ? (result ? result.created : shown.valid) : 0;
  const missingDates = preview && !result ? preview.rows.filter(needsDate).length : 0;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[500] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={close} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-4xl max-h-[90vh] flex flex-col bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl overflow-hidden">
          <div className="px-5 py-4 border-b border-[var(--border)] flex items-center justify-between">
            <h3 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest">Bulk import tasks</h3>
            <button onClick={close} className="p-1 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)]" aria-label="Close"><X size={18} /></button>
          </div>

          <datalist id="bulk-categories">{categories.map((c) => <option key={c} value={c} />)}</datalist>
          <datalist id="bulk-people">{people.map((p) => <option key={p} value={p} />)}</datalist>

          <div className="px-5 py-4 space-y-4 overflow-y-auto">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="rounded-xl border border-[var(--border)] p-3.5">
                <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">1. Get the template</p>
                <p className="text-[12px] text-[var(--text-main)] mt-1">
                  One task per row. <b>Task Title, Category and Deadline Date are mandatory</b> (red headers).
                  For a <b>repeating</b> task set Repeat (Daily / Weekly / Monthly / Yearly) instead of a deadline.
                </p>
                <button onClick={downloadTemplate}
                  className="mt-2.5 flex items-center gap-1.5 px-3.5 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--text-main)] hover:border-[var(--accent-indigo)]">
                  <Download size={14} /> Download template
                </button>
              </div>
              <div className="rounded-xl border border-[var(--border)] p-3.5">
                <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">2. Upload the filled sheet</p>
                <p className="text-[12px] text-[var(--text-main)] mt-1">
                  Excel (.xlsx) or CSV, up to 500 tasks. You see a preview first — and can set a missing due date there.
                </p>
                <input ref={fileRef} type="file" accept=".xlsx,.xlsm,.csv" className="hidden" id="bulk-task-file"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) { setFile(f); setFixes({}); runPreview(f, null); } }} />
                <label htmlFor="bulk-task-file"
                  className="mt-2.5 inline-flex items-center gap-1.5 px-3.5 py-2 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest cursor-pointer hover:opacity-90">
                  <Upload size={14} /> {file ? 'Choose another file' : 'Choose file'}
                </label>
                {file && (
                  <p className="mt-1.5 text-[11px] text-[var(--text-muted)] flex items-center gap-1"><FileSpreadsheet size={12} /> {file.name}</p>
                )}
              </div>
            </div>

            {busy && <p className="text-[12px] font-bold text-[var(--text-muted)]">Working…</p>}

            {shown && !busy && (
              <div className="space-y-2.5">
                <div className="flex flex-wrap items-center gap-3 text-[12px] font-bold">
                  <span className="text-[var(--text-main)]">{shown.total} row(s)</span>
                  <span className="text-[var(--accent-green)] flex items-center gap-1"><CheckCircle2 size={14} /> {okCount} {result ? 'created' : 'ready to import'}</span>
                  {shown.invalid > 0 && (
                    <span className="text-[var(--accent-red)] flex items-center gap-1"><AlertTriangle size={14} /> {shown.invalid} need attention{result ? ' — not created' : ' — correct them below, or they are skipped'}</span>
                  )}
                </div>

                {missingDates > 0 && (
                  <div className="flex flex-wrap items-end gap-2 rounded-xl border border-[var(--accent-orange)] bg-[var(--accent-orange-bg)] px-3 py-2.5">
                    <div>
                      <label className={LABEL} htmlFor="bulk-date">Set this due date for every row without one ({missingDates})</label>
                      <input id="bulk-date" type="date" min={todayIso()} value={bulkDate} className={`${INPUT} mt-1 w-44`}
                        onChange={(e) => setBulkDate(e.target.value)} />
                    </div>
                    <button onClick={applyBulkDate} disabled={!bulkDate}
                      className="px-3 py-2 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg text-[10.5px] font-black uppercase tracking-widest disabled:opacity-50">
                      Apply
                    </button>
                  </div>
                )}

                <div className="overflow-x-auto rounded-xl border border-[var(--border)]">
                  <table className="w-full text-[11.5px]">
                    <thead>
                      <tr className="text-[9.5px] font-black uppercase tracking-widest text-[var(--text-muted)] border-b border-[var(--border)] bg-[var(--input-bg)]">
                        <th className="py-2 px-2.5 text-left">Row</th>
                        <th className="py-2 px-2.5 text-left">Task</th>
                        <th className="py-2 px-2.5 text-left">Assign to</th>
                        <th className="py-2 px-2.5 text-left">Deadline / Repeat</th>
                        <th className="py-2 px-2.5 text-left">Result</th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.rows.map((r) => (
                        <React.Fragment key={r.row}>
                          <tr className={`${r.errors?.length && !result ? '' : 'border-b'} border-[var(--border)] align-top`}>
                            <td className="py-2 px-2.5 text-[var(--text-muted)]">{r.row}</td>
                            <td className="py-2 px-2.5 text-[var(--text-main)] font-bold">
                              {r.title || '—'}
                              <span className="block font-normal text-[var(--text-muted)]">
                                {[r.category, r.priority, r.checklist_items ? `${r.checklist_items} checklist item(s)` : null].filter(Boolean).join(' · ')}
                              </span>
                            </td>
                            <td className="py-2 px-2.5 text-[var(--text-main)]">
                              {r.assignees?.length ? r.assignees.join(', ') : 'Myself'}
                              {r.assignees?.length > 1 && <span className="block text-[var(--text-muted)]">{r.assignment_mode}</span>}
                            </td>
                            <td className="py-2 px-2.5 text-[var(--text-main)]">
                              {r.repeat_summary ? (
                                <span className="flex items-start gap-1"><Repeat size={12} className="mt-0.5 shrink-0 text-[var(--accent-indigo)]" /> {r.repeat_summary}</span>
                              ) : (
                                <span className="whitespace-nowrap">{r.deadline || '—'}</span>
                              )}
                            </td>
                            <td className="py-2 px-2.5">
                              {r.errors?.length ? (
                                <ul className="text-[var(--accent-red)] space-y-0.5">{r.errors.map((e) => <li key={e}>{e}</li>)}</ul>
                              ) : (
                                <span className="text-[var(--accent-green)] font-bold">{result ? 'Created' : 'OK'}</span>
                              )}
                            </td>
                          </tr>
                          {r.errors?.length > 0 && !result && (
                            <tr className="border-b border-[var(--border)] bg-[var(--input-bg)]">
                              <td />
                              <td colSpan={4} className="py-2 px-2.5">
                                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                                  {r.repeat ? (
                                    <>
                                      <div>
                                        <label className={LABEL} htmlFor={`fix-start-${r.row}`}>Start date</label>
                                        <input id={`fix-start-${r.row}`} type="date" min={todayIso()} className={INPUT}
                                          value={fixOf(r, 'start_date', r.start_date || '')}
                                          onChange={(e) => setFix(r.row, 'start_date', e.target.value)} />
                                      </div>
                                      <div>
                                        <label className={LABEL} htmlFor={`fix-end-${r.row}`}>Repeat end date</label>
                                        <input id={`fix-end-${r.row}`} type="date" min={todayIso()} className={INPUT}
                                          value={fixOf(r, 'repeat_end_date', r.repeat_end_date || '')}
                                          onChange={(e) => setFix(r.row, 'repeat_end_date', e.target.value)} />
                                      </div>
                                    </>
                                  ) : (
                                    <>
                                      <div>
                                        <label className={LABEL} htmlFor={`fix-date-${r.row}`}>Due date *</label>
                                        <input id={`fix-date-${r.row}`} type="date" min={todayIso()} className={INPUT}
                                          value={fixOf(r, 'deadline_date', r.deadline_date || '')}
                                          onChange={(e) => setFix(r.row, 'deadline_date', e.target.value)} />
                                      </div>
                                      <div>
                                        <label className={LABEL} htmlFor={`fix-time-${r.row}`}>Time</label>
                                        <input id={`fix-time-${r.row}`} type="time" className={INPUT}
                                          value={fixOf(r, 'deadline_time')}
                                          onChange={(e) => setFix(r.row, 'deadline_time', e.target.value)} />
                                      </div>
                                    </>
                                  )}
                                  <div>
                                    <label className={LABEL} htmlFor={`fix-cat-${r.row}`}>Category *</label>
                                    <input id={`fix-cat-${r.row}`} list="bulk-categories" className={INPUT}
                                      value={fixOf(r, 'category', r.category || '')}
                                      onChange={(e) => setFix(r.row, 'category', e.target.value)} />
                                  </div>
                                  <div>
                                    <label className={LABEL} htmlFor={`fix-who-${r.row}`}>Assign to</label>
                                    <input id={`fix-who-${r.row}`} list="bulk-people" className={INPUT}
                                      placeholder="Blank = yourself"
                                      value={fixOf(r, 'assignees', r.assignees_input || '')}
                                      onChange={(e) => setFix(r.row, 'assignees', e.target.value)} />
                                  </div>
                                  {(r.repeat === 'Weekly' || r.repeat === 'Monthly') && (
                                    <div className="col-span-2">
                                      <label className={LABEL} htmlFor={`fix-on-${r.row}`}>Repeat on</label>
                                      <input id={`fix-on-${r.row}`} className={INPUT}
                                        placeholder={r.repeat === 'Weekly' ? 'e.g. Mon, Thu' : 'e.g. 1, 15, Last'}
                                        value={fixOf(r, 'repeat_on', r.repeat_on_input || '')}
                                        onChange={(e) => setFix(r.row, 'repeat_on', e.target.value)} />
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          <div className="px-5 py-4 border-t border-[var(--border)] flex items-center justify-end gap-3">
            <button onClick={close}
              className="px-4 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] border border-[var(--border)] hover:text-[var(--text-main)]">
              {result ? 'Close' : 'Cancel'}
            </button>
            {preview && !result && dirty && (
              <button onClick={() => runPreview(file, fixes)} disabled={busy}
                className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest disabled:opacity-50 hover:opacity-90">
                <RefreshCw size={13} /> Re-check
              </button>
            )}
            {preview && !result && !dirty && (
              <button onClick={runImport} disabled={busy || !preview.valid}
                className="px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest disabled:opacity-50 hover:opacity-90">
                {busy ? 'Importing…' : `Import ${preview.valid} task(s)`}
              </button>
            )}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default BulkImportTasksModal;
