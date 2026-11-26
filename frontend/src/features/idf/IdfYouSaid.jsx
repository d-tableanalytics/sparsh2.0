import React, { useCallback, useEffect, useState } from 'react';
import { MessageSquareReply, X, Plus, Trash2, ThumbsUp, Wrench, CheckCircle2, AlertTriangle, Inbox } from 'lucide-react';
import { useNotification } from '../../context/NotificationContext';
import { getIdfResponses, submitIdfResponse } from '../../services/idfApi';
import { CARD, FIELD, day, dayTime, monthLabel } from './idfKit';
import { BandChip } from './IdfBits';

/* ─────────────────────────────────────────────────────────────
   "You said, we did" (client Standard Approach: close the loop). Within 15 days of the
   results, each HOD tells the departments that rated them what will change and by when.
   Shown on My Feedback Forms: the HOD's own departments to answer for, and the answers
   received from departments their department rated.
   ───────────────────────────────────────────────────────────── */

const LABEL = 'text-[11px] font-black uppercase tracking-wide text-[var(--text-muted)]';

const Received = ({ title, icon, color, items }) => {
  const Icon = icon;
  return (
    <div className="space-y-1.5 min-w-0">
      <p className="flex items-center gap-1.5 text-[11px] font-black uppercase tracking-wide" style={{ color }}><Icon size={13} /> {title}</p>
      {items.length ? items.map((it, i) => (
        <div key={i} className="rounded-lg border border-[var(--border)] bg-[var(--input-bg)] px-3 py-2">
          <p className="text-[12.5px] leading-snug text-[var(--text-main)]">{it.text}</p>
          <p className="mt-0.5 text-[10.5px] font-bold text-[var(--text-muted)]">From {it.from}</p>
        </div>
      )) : <p className="text-[12px] text-[var(--text-muted)]">None.</p>}
    </div>
  );
};

const AnswerDialog = ({ r, onClose, onSaved }) => {
  const { showSuccess, showError } = useNotification();
  const [items, setItems] = useState(r.items?.length ? r.items : [{ what: '', by_when: '' }]);
  const [note, setNote] = useState(r.note || '');
  const [busy, setBusy] = useState(false);
  const setItem = (i, k, v) => setItems((xs) => xs.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  const ready = items.some((x) => x.what.trim() && x.by_when) && items.every((x) => (!x.what.trim() && !x.by_when) || (x.what.trim() && x.by_when));

  const save = async () => {
    setBusy(true);
    try {
      await submitIdfResponse(r.id, { items, note });
      showSuccess(`Sent to ${r.raters.join(', ')} — thank you for closing the loop.`);
      onSaved();
    } catch (e) {
      showError(e?.response?.data?.detail || 'Could not send your answer.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={() => !busy && onClose()}>
      <div onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true"
        className="w-full max-w-3xl max-h-[92vh] flex flex-col rounded-2xl bg-[var(--bg-card)] shadow-2xl overflow-hidden">
        <div className="flex items-start gap-3 px-5 py-4 border-b border-[var(--border)]">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]"><MessageSquareReply size={18} /></span>
          <div className="flex-1 min-w-0">
            <h3 className="text-[15px] font-black text-[var(--text-main)]">You said, we did — {r.department}</h3>
            <p className="text-[11.5px] text-[var(--text-muted)]">{monthLabel(r.period)} · {r.pct}% · tell {r.raters.join(', ')} what will change and by when</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]"><X size={17} /></button>
        </div>
        <div className="px-5 py-4 space-y-5 overflow-y-auto">
          <section className="space-y-2">
            <p className={LABEL}>What your department was told</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Received title="Does well" icon={ThumbsUp} color="var(--accent-green)" items={r.received?.strengths || []} />
              <Received title="Should improve" icon={Wrench} color="var(--accent-orange)" items={r.received?.improvements || []} />
            </div>
          </section>
          <section className="space-y-2">
            <p className={LABEL}>What will change, and by when</p>
            {items.map((x, i) => (
              <div key={i} className="grid grid-cols-1 sm:grid-cols-[1fr_170px_auto] gap-2 items-start">
                <input className={FIELD} placeholder="e.g. Leave queries answered within 24 hours" value={x.what} maxLength={500}
                  onChange={(e) => setItem(i, 'what', e.target.value)} />
                <input type="date" className={FIELD} value={x.by_when} onChange={(e) => setItem(i, 'by_when', e.target.value)} aria-label="By when" />
                <button type="button" disabled={items.length <= 1} aria-label="Remove change" onClick={() => setItems((xs) => xs.filter((_, j) => j !== i))}
                  className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-red)] disabled:opacity-30"><Trash2 size={14} /></button>
              </div>
            ))}
            {items.length < 5 && (
              <button type="button" onClick={() => setItems((xs) => [...xs, { what: '', by_when: '' }])}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
                <Plus size={13} /> Add another change
              </button>
            )}
          </section>
          <label className="block space-y-1.5">
            <span className={LABEL}>Note to the raters (optional)</span>
            <textarea rows={2} className={`${FIELD} w-full`} placeholder="e.g. Thank you for the honest feedback…" value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3.5 border-t border-[var(--border)] bg-[var(--input-bg)]">
          <span className="text-[11.5px] text-[var(--text-muted)]">Due {day(r.due_date)} · the raters' HODs get it by email</span>
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] hover:bg-[var(--bg-card)]">Cancel</button>
            <button type="button" onClick={save} disabled={!ready || busy}
              className="px-5 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-black disabled:opacity-50">
              {busy ? 'Sending…' : r.status === 'Submitted' ? 'Update and resend' : 'Send to the raters'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

const IdfYouSaid = () => {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);
  const load = useCallback(async () => {
    try {
      const { data: d } = await getIdfResponses();
      setData(d);
    } catch {
      setData({ mine: [], received: [] });
    }
  }, []);
  // Fetch on open; state is set only after the request returns.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(); }, [load]);

  const mine = data?.mine || [];
  const received = data?.received || [];
  if (!mine.length && !received.length) return null;

  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      {!!mine.length && (
        <div className={`${CARD} overflow-hidden`}>
          <div className="px-4 py-3 border-b border-[var(--border)]">
            <h3 className="flex items-center gap-2 text-[13.5px] font-black text-[var(--text-main)]"><MessageSquareReply size={15} className="text-[var(--accent-indigo)]" /> You said, we did</h3>
            <p className="text-[11px] text-[var(--text-muted)]">Within 15 days of the results, tell the raters what will change and by when</p>
          </div>
          <ul className="divide-y divide-[var(--border)]">
            {mine.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <div className="flex-1 min-w-[180px]">
                  <p className="flex items-center gap-2 text-[13px] font-black text-[var(--text-main)]">{r.department} <BandChip band={r.band} /></p>
                  <p className="text-[11.5px] text-[var(--text-muted)]">{monthLabel(r.period)} · rated by {r.raters.join(', ')}</p>
                </div>
                {r.status === 'Submitted' ? (
                  <span className="inline-flex items-center gap-1 text-[12px] font-bold text-[var(--accent-green)]"><CheckCircle2 size={14} /> Sent {dayTime(r.submitted_at)}</span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-[12px] font-bold" style={{ color: r.overdue ? 'var(--accent-red)' : 'var(--accent-orange)' }}>
                    {r.overdue && <AlertTriangle size={13} />}Due {day(r.due_date)}
                  </span>
                )}
                <button type="button" onClick={() => setOpen(r)}
                  className={r.status === 'Submitted'
                    ? 'px-3 py-1.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)]'
                    : 'px-3.5 py-1.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-black hover:opacity-90'}>
                  {r.status === 'Submitted' ? 'View / update' : 'Answer the raters'}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {!!received.length && (
        <div className={`${CARD} overflow-hidden`}>
          <div className="px-4 py-3 border-b border-[var(--border)]">
            <h3 className="flex items-center gap-2 text-[13.5px] font-black text-[var(--text-main)]"><Inbox size={15} className="text-[var(--accent-green)]" /> Answers to your feedback</h3>
            <p className="text-[11px] text-[var(--text-muted)]">What the departments you rated will change</p>
          </div>
          <ul className="divide-y divide-[var(--border)] max-h-96 overflow-y-auto">
            {received.map((r) => (
              <li key={r.id} className="px-4 py-3 space-y-1.5">
                <p className="text-[13px] font-black text-[var(--text-main)]">{r.department} <span className="text-[11.5px] font-semibold text-[var(--text-muted)]">· {monthLabel(r.period)}</span></p>
                <ul className="space-y-1">
                  {(r.items || []).map((it, i) => (
                    <li key={i} className="flex gap-2 text-[12.5px] text-[var(--text-main)]">
                      <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-[var(--accent-green)]" />
                      <span>{it.what} <span className="text-[var(--text-muted)]">— by {day(it.by_when)}</span></span>
                    </li>
                  ))}
                </ul>
                {r.note && <p className="text-[11.5px] italic text-[var(--text-muted)]">“{r.note}”</p>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {open && <AnswerDialog r={open} onClose={() => setOpen(null)} onSaved={() => { setOpen(null); load(); }} />}
    </div>
  );
};

export default IdfYouSaid;
