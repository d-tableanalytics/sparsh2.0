import React, { useState } from 'react';
import { FileUp, X, Download } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { importEmployees, downloadEmployeeImportTemplate } from '../../../services/hrmsApi';

const TONE = {
  Ready: 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]',
  Created: 'bg-[var(--accent-green-bg)] text-[var(--accent-green)]',
  Error: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]',
};

/**
 * FRD §4 "HR creates or imports the employee record".
 *
 * Two steps on the same file: Preview checks every row exactly as Add Employee would and
 * writes nothing; Import creates the rows that passed. Each row names an existing user
 * account by email, the same rule Add Employee follows.
 */
const ImportEmployeesModal = ({ onClose, onImported }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async (commit) => {
    if (!file) return;
    setBusy(true);
    try {
      const { data } = await importEmployees(file, commit, scope);
      setResult(data);
      if (commit) {
        showSuccess(`${data.Created} employee(s) imported${data.Error ? `, ${data.Error} row(s) not` : ''}.`);
        if (data.Created) onImported();
      }
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not read that file.');
    } finally {
      setBusy(false);
    }
  };

  const template = () => downloadEmployeeImportTemplate(scope)
    .catch(() => showError('Could not download the template.'));

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-3xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <FileUp size={17} className="text-[var(--accent-indigo)]" />
            <h2 className="text-[15px] font-bold text-[var(--text-main)]">Import employees</h2>
          </div>
          <button type="button" aria-label="Close" onClick={onClose}
            className="text-[var(--text-muted)] hover:opacity-70"><X size={17} /></button>
        </div>

        <div className="p-5 space-y-4 overflow-y-auto">
          <p className="text-[12.5px] text-[var(--text-muted)]">
            One row per employee, CSV or Excel. The <b>email</b> column names the user account
            each row is for. Department and designation go by name, managers by email, dates as
            YYYY-MM-DD, configurable fields as <code>custom.&lt;code&gt;</code>. Leave
            employee_code blank to number them automatically.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input type="file" accept=".csv,.xlsx" aria-label="Employee file"
              onChange={(e) => { setFile(e.target.files?.[0] || null); setResult(null); }}
              className="text-[12.5px] text-[var(--text-main)]" />
            <button type="button" onClick={template}
              className="h-8 px-3 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-main)] flex items-center gap-1.5">
              <Download size={13} /> Template
            </button>
          </div>

          {result && (
            <div className="space-y-2">
              <p className="text-[12.5px] text-[var(--text-main)]">
                {result.commit
                  ? `${result.Created} created, ${result.Error} not imported.`
                  : `${result.Ready} ready to import, ${result.Error} with problems.`}
                {result.ignored_columns?.length > 0 && (
                  <span className="text-[var(--text-muted)]"> Ignored columns: {result.ignored_columns.join(', ')}.</span>
                )}
              </p>
              <div className="rounded-lg border border-[var(--border)] overflow-x-auto">
                <table className="w-full text-[12px]">
                  <thead className="bg-[var(--input-bg)] text-[var(--text-muted)]">
                    <tr>
                      <th className="text-left px-3 py-2">Row</th>
                      <th className="text-left px-3 py-2">Email</th>
                      <th className="text-left px-3 py-2">Status</th>
                      <th className="text-left px-3 py-2">Detail</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border)]">
                    {result.rows.map((r) => (
                      <tr key={r.row}>
                        <td className="px-3 py-2 text-[var(--text-muted)]">{r.row}</td>
                        <td className="px-3 py-2 text-[var(--text-main)]">{r.email || '—'}</td>
                        <td className="px-3 py-2">
                          <span className={`px-2 py-0.5 rounded-md text-[11px] font-bold ${TONE[r.status] || ''}`}>{r.status}</span>
                        </td>
                        <td className="px-3 py-2 text-[var(--text-main)]">
                          {r.error || [r.name, r.employee_code || (result.commit ? '' : 'number on import')].filter(Boolean).join(' · ')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose}
            className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-main)]">
            Close
          </button>
          <button type="button" onClick={() => run(false)} disabled={!file || busy}
            className="h-9 px-4 rounded-lg border border-[var(--accent-indigo)] text-[12px] font-bold text-[var(--accent-indigo)] disabled:opacity-50">
            Preview
          </button>
          <button type="button" onClick={() => run(true)}
            disabled={!file || busy || !result || result.commit || !result.Ready}
            className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
            {busy ? 'Working…' : `Import ${result && !result.commit ? result.Ready : ''} employee(s)`}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ImportEmployeesModal;
