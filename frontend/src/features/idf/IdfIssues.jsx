import React, { useCallback, useEffect, useState } from 'react';
import { Megaphone, RefreshCw, Send, X, CircleDot, CalendarCheck, CheckCircle2, EyeOff, ArrowRight, Trash2 } from 'lucide-react';
import { DashboardHero, HeroButton } from '../tpms/common/dashboardKit';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { getIdfIssues, raiseIdfIssue, updateIdfIssue, deleteIdfIssue } from '../../services/idfApi';
import { CARD, FIELD, day, dayTime, isStaffAdmin, canDelete } from './idfKit';
import { CompanyPicker } from './IdfBits';

/* ─────────────────────────────────────────────────────────────
   Inter-Departmental Feedback ▸ Raise an Issue — the open feedback channel (client Standard
   Approach: "No waiting for the next survey. Anyone can raise an inter-department problem
   through a simple form to HR; HR brings it to the weekly WRM").

   Everyone: raise an issue (optionally anonymous) and follow their own. HR / Admin / MD /
   Sparsh Admin: every issue — take it to WRM, add notes, resolve it.
   ───────────────────────────────────────────────────────────── */

const LABEL = 'text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]';
const STATUS = {
  New: { icon: CircleDot, c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)' },
  'Taken to WRM': { icon: CalendarCheck, c: 'var(--accent-orange)', bg: 'var(--accent-yellow-bg)' },
  Resolved: { icon: CheckCircle2, c: 'var(--accent-green)', bg: 'var(--accent-green-bg)' },
};

const Chip = ({ status }) => {
  const s = STATUS[status] || STATUS.New;
  return <span className="inline-block px-2 py-0.5 rounded-full text-[10.5px] font-black whitespace-nowrap" style={{ color: s.c, background: s.bg }}>{status}</span>;
};

const IdfIssues = () => {
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const staff = isStaffAdmin(user);
  const [companyId, setCompanyId] = useState('');
  const cid = staff ? companyId : undefined;
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ about_department_id: '', description: '', suggestion: '', anonymous: false });
  const [busy, setBusy] = useState(false);
  const [tile, setTile] = useState('');
  const [editing, setEditing] = useState(null);
  const [upd, setUpd] = useState({ status: '', note: '' });

  const load = useCallback(async () => {
    if (staff && !companyId) return;
    try {
      const { data: d } = await getIdfIssues(cid);
      setData(d);
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not load the issues.');
    }
  }, [staff, companyId, cid, showError]);
  useEffect(() => { load(); }, [load]);

  const raise = async () => {
    setBusy(true);
    try {
      await raiseIdfIssue(form);
      showSuccess('Issue sent to HR — it will be taken to the weekly WRM.');
      setForm({ about_department_id: '', description: '', suggestion: '', anonymous: false });
      load();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not raise the issue.');
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      await updateIdfIssue(editing.id, upd, cid);
      showSuccess('Issue updated.');
      setEditing(null);
      load();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not update the issue.');
    } finally {
      setBusy(false);
    }
  };

  const manager = !!data?.manager;
  const issues = data?.issues || [];
  const shown = issues.filter((i) => !tile || i.status === tile);
  const canRaise = !staff;          // a Sparsh Admin monitors; company people raise
  const mayDelete = canDelete(user);   // MD, Client Admin, Super Admin

  const remove = async (i) => {
    if (!window.confirm(`Delete this issue about ${i.about_department}? This cannot be undone.`)) return;
    try {
      await deleteIdfIssue(i.id, cid);
      showSuccess('Issue deleted.');
      load();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not delete the issue.');
    }
  };

  return (
    <div className="space-y-5">
      <DashboardHero icon={Megaphone} title={manager ? 'Open Feedback Channel' : 'Raise an Issue'}
        subtitle={manager ? 'Inter-department issues raised between cycles — take them to the weekly WRM'
          : 'No need to wait for the next survey — tell HR about an inter-department problem'}>
        <HeroButton icon={RefreshCw} onClick={load}>Refresh</HeroButton>
      </DashboardHero>

      {staff && <div className={`${CARD} p-4`}><CompanyPicker value={companyId} onChange={setCompanyId} /></div>}

      {data && (
        <div className={`grid grid-cols-1 ${canRaise ? 'xl:grid-cols-[minmax(0,420px)_1fr]' : ''} gap-4 items-start`}>
          {canRaise && (
            <div className={`${CARD} p-4 sm:p-5 space-y-4`}>
              <div>
                <h3 className="text-[14px] font-black text-[var(--text-main)]">Raise an inter-department issue</h3>
                <p className="text-[11.5px] text-[var(--text-muted)]">Describe the process, not the person: the situation, its effect, and one change you suggest.</p>
              </div>
              <label className="block space-y-1.5">
                <span className={LABEL}>Which department is it about?</span>
                <select className={`${FIELD} w-full`} value={form.about_department_id} onChange={(e) => setForm({ ...form, about_department_id: e.target.value })}>
                  <option value="">Choose a department…</option>
                  {data.departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </label>
              <label className="block space-y-1.5">
                <span className={LABEL}>What is happening, and its effect</span>
                <textarea rows={4} className={`${FIELD} w-full`} maxLength={2000} value={form.description}
                  placeholder="e.g. Dispatch dates change without notice, so Sales cannot confirm delivery to customers."
                  onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </label>
              <label className="block space-y-1.5">
                <span className={LABEL}>One change you suggest (optional)</span>
                <input className={`${FIELD} w-full`} maxLength={1000} value={form.suggestion} placeholder="e.g. Share a dispatch freeze 3 days ahead"
                  onChange={(e) => setForm({ ...form, suggestion: e.target.value })} />
              </label>
              <label className="flex items-start gap-2 text-[12.5px] text-[var(--text-main)] cursor-pointer">
                <input type="checkbox" className="mt-0.5 accent-[var(--accent-indigo)]" checked={form.anonymous}
                  onChange={(e) => setForm({ ...form, anonymous: e.target.checked })} />
                <span><b>Raise anonymously</b><span className="block text-[11px] text-[var(--text-muted)]">HR will not see your name.</span></span>
              </label>
              <button type="button" onClick={raise} disabled={busy || !form.about_department_id || form.description.trim().length < 10}
                className="inline-flex w-full items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-black disabled:opacity-50">
                <Send size={14} /> {busy ? 'Sending…' : 'Send to HR'}
              </button>
            </div>
          )}

          <div className="space-y-3 min-w-0">
            {manager && (
              <div className="grid grid-cols-3 gap-2.5">
                {Object.keys(STATUS).map((k) => {
                  const s = STATUS[k];
                  const Icon = s.icon;
                  const on = tile === k;
                  return (
                    <button key={k} type="button" aria-pressed={on} onClick={() => setTile(on ? '' : k)}
                      className={`${CARD} flex items-center gap-3 px-3.5 py-2.5 text-left transition-all hover:shadow-sm`}
                      style={{ borderColor: on ? s.c : undefined, background: on ? s.bg : undefined }}>
                      <span className="rounded-lg p-2" style={{ color: s.c, background: s.bg }}><Icon size={15} /></span>
                      <span>
                        <span className="block text-[20px] font-black leading-tight tabular-nums text-[var(--text-main)]">{issues.filter((i) => i.status === k).length}</span>
                        <span className="block text-[11px] font-bold text-[var(--text-muted)]">{k}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
            <div className={`${CARD} overflow-hidden`}>
              <div className="px-4 py-3 border-b border-[var(--border)]">
                <h3 className="text-[13.5px] font-black text-[var(--text-main)]">{manager ? 'All raised issues' : 'Issues you raised'}</h3>
              </div>
              {shown.length ? (
                <ul className="divide-y divide-[var(--border)]">
                  {shown.map((i) => (
                    <li key={i.id} className="px-4 py-3 space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[13px] font-black text-[var(--text-main)]">About {i.about_department}</span>
                        <Chip status={i.status} />
                        <span className="ml-auto text-[11px] text-[var(--text-muted)]">{dayTime(i.created_at)}</span>
                      </div>
                      <p className="text-[12.5px] leading-relaxed text-[var(--text-main)]">{i.description}</p>
                      {i.suggestion && <p className="flex gap-1.5 text-[12px] text-[var(--text-muted)]"><ArrowRight size={13} className="mt-0.5 shrink-0" /> {i.suggestion}</p>}
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--text-muted)]">
                        {manager && (
                          <span className="inline-flex items-center gap-1">
                            {i.anonymous && <EyeOff size={11} />} Raised by {i.raised_by_name}{i.from_department ? ` · ${i.from_department}` : ''}
                          </span>
                        )}
                        {i.wrm_date && <span>WRM {day(i.wrm_date)}</span>}
                        {!!(i.notes || []).length && <span>Latest note: {i.notes[i.notes.length - 1].text}</span>}
                        {manager && (
                          <button type="button" onClick={() => { setEditing(i); setUpd({ status: i.status, note: '' }); }}
                            className="ml-auto text-[11.5px] font-bold text-[var(--accent-indigo)] hover:underline">Update</button>
                        )}
                        {mayDelete && (
                          <button type="button" onClick={() => remove(i)} title="Delete issue" aria-label="Delete issue"
                            className={`${manager ? '' : 'ml-auto '}p-1 rounded text-[var(--text-muted)] hover:text-[var(--accent-red)]`}><Trash2 size={13} /></button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="px-4 py-10 text-center text-[12.5px] text-[var(--text-muted)]">
                  {issues.length ? 'No issues with this status.' : manager ? 'No issues raised yet.' : 'You have not raised any issue.'}
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {editing && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={() => !busy && setEditing(null)}>
          <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" className="w-full max-w-lg rounded-2xl bg-[var(--bg-card)] shadow-2xl overflow-hidden">
            <div className="flex items-start gap-3 px-5 py-4 border-b border-[var(--border)]">
              <div className="flex-1 min-w-0">
                <h3 className="text-[15px] font-black text-[var(--text-main)]">Issue about {editing.about_department}</h3>
                <p className="mt-0.5 text-[12px] text-[var(--text-muted)] line-clamp-2">{editing.description}</p>
              </div>
              <button type="button" onClick={() => setEditing(null)} aria-label="Close" className="p-1 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]"><X size={17} /></button>
            </div>
            <div className="px-5 py-4 space-y-3">
              <label className="block space-y-1.5">
                <span className={LABEL}>Status</span>
                <select className={`${FIELD} w-full`} value={upd.status} onChange={(e) => setUpd({ ...upd, status: e.target.value })}>
                  {Object.keys(STATUS).map((k) => <option key={k}>{k}</option>)}
                </select>
              </label>
              <label className="block space-y-1.5">
                <span className={LABEL}>Note</span>
                <textarea rows={3} className={`${FIELD} w-full`} placeholder="e.g. Discussed in WRM; Operations to share a dispatch freeze" value={upd.note}
                  onChange={(e) => setUpd({ ...upd, note: e.target.value })} />
              </label>
              {!!(editing.notes || []).length && (
                <ol className="space-y-1.5 border-l-2 border-[var(--border)] pl-3">
                  {[...editing.notes].reverse().map((n, k) => (
                    <li key={k} className="text-[11.5px]"><span className="text-[var(--text-muted)]">{day(n.at)} · {n.by} · {n.status}</span><span className="block text-[var(--text-main)]">{n.text}</span></li>
                  ))}
                </ol>
              )}
            </div>
            <div className="flex justify-end gap-2 px-5 py-3.5 border-t border-[var(--border)] bg-[var(--input-bg)]">
              <button type="button" onClick={() => setEditing(null)} className="px-4 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] hover:bg-[var(--bg-card)]">Cancel</button>
              <button type="button" onClick={save} disabled={busy} className="px-5 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-black disabled:opacity-50">{busy ? 'Saving…' : 'Save'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default IdfIssues;
