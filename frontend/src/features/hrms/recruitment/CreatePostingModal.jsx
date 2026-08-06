import React, { useEffect, useMemo, useState } from 'react';
import { X, Megaphone, Link2, FileText } from 'lucide-react';
import { useNotification } from '../../../context/NotificationContext';
import { useHrms } from '../HrmsContext';
import { getJds, createPostings, applyUrlFor } from '../../../services/hrmsApi';

/**
 * HRMS ▸ publish a job description.
 *
 * One posting ROW per selected platform, each independently configured:
 *   • Generate form link → the built-in public form at /apply/<code>
 *   • Paste external link → the platform's own listing
 *
 * Two things this screen is careful about:
 *
 * 1. **The code is previewed client-side and sent with the request.** The user copies the
 *    apply link while filling the form, so the code they copied must be the one stored. The
 *    server honours it only if it matches the public pattern and is unused, and returns
 *    whatever it actually saved.
 * 2. **External postings are labelled honestly.** Applications made on a job board never
 *    reach this pipeline — nothing writes them back. Saying so here is better than an
 *    application count that silently stays at zero.
 */

const PLATFORMS = ['LinkedIn', 'Naukri', 'Indeed', 'Foundit', 'Apna', 'Career Page', 'Referral', 'Manual'];
const PREFIX = {
  LinkedIn: 'LI', Naukri: 'NK', Indeed: 'ID', Foundit: 'FN',
  Apna: 'AP', 'Career Page': 'CP', Referral: 'RF', Manual: 'MN',
};
const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';

/** Mirrors the server's `^[A-Z]{2}-[A-Z0-9]{6}$`. Uses crypto when available — this is a
 *  public identifier, and guessable codes would let someone enumerate a company's openings. */
const previewCode = (platform) => {
  const bytes = new Uint8Array(6);
  (window.crypto || window.msCrypto)?.getRandomValues?.(bytes);
  const body = Array.from(bytes, (b) => ALPHABET[b % ALPHABET.length]).join('');
  return `${PREFIX[platform] || 'JB'}-${body || 'XXXXXX'}`;
};

const FIELD = 'w-full h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';
const LABEL = 'block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5';

const CreatePostingModal = ({ onClose, onCreated }) => {
  const { scope } = useHrms();
  const { showSuccess, showError } = useNotification();

  const [jds, setJds] = useState([]);
  const [jdNo, setJdNo] = useState('');
  const [selected, setSelected] = useState({ 'Career Page': true });
  const [config, setConfig] = useState({});
  const [expiry, setExpiry] = useState('');
  const [notes, setNotes] = useState('');
  const [requiresAssessment, setRequiresAssessment] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getJds({ ...scope, status: 'Approved' })
      .then(({ data }) => {
        const list = data?.job_descriptions || [];
        setJds(list);
        if (list.length) setJdNo(list[0].jd_no);
      })
      .catch((err) => showError(err?.response?.data?.detail || 'Could not load job descriptions.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const chosen = useMemo(() => PLATFORMS.filter((p) => selected[p]), [selected]);

  const toggle = (platform) => {
    setSelected((s) => ({ ...s, [platform]: !s[platform] }));
    setConfig((c) => (c[platform] ? c : {
      ...c, [platform]: { mode: 'auto', url: '', code: previewCode(platform) },
    }));
  };

  const setCfg = (platform, patch) =>
    setConfig((c) => ({ ...c, [platform]: { ...c[platform], ...patch } }));

  const submit = async (e) => {
    e.preventDefault();
    if (!jdNo) return showError('Select an approved job description.');
    if (!chosen.length) return showError('Select at least one platform.');
    for (const p of chosen) {
      const cfg = config[p] || {};
      if (cfg.mode === 'external' && !/^https?:\/\//i.test((cfg.url || '').trim())) {
        return showError(`${p}: enter a link starting with http:// or https://, or switch it to a generated form.`);
      }
    }

    setSaving(true);
    try {
      const { data } = await createPostings({
        jd_no: jdNo,
        expiry_date: expiry || null,
        notes: notes || null,
        requires_assessment: requiresAssessment,
        platform_links: chosen.map((p) => {
          const cfg = config[p] || {};
          return {
            platform: p,
            apply_link_mode: cfg.mode || 'auto',
            external_url: cfg.mode === 'external' ? cfg.url.trim() : null,
            code: cfg.mode === 'external' ? null : cfg.code,
          };
        }),
      }, scope);
      showSuccess(`Published to ${data.created} platform${data.created === 1 ? '' : 's'}`);
      onCreated();
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not publish the posting.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <Megaphone size={17} className="text-[var(--accent-indigo)]" />
            <h2 className="text-[15px] font-bold text-[var(--text-main)]">Publish a job</h2>
          </div>
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
            <X size={17} />
          </button>
        </div>

        <form onSubmit={submit} className="p-5 space-y-5 overflow-y-auto">
          <div>
            <label className={LABEL} htmlFor="p-jd">Job description *</label>
            {jds.length === 0 ? (
              <div className="p-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[12.5px] text-[var(--text-muted)] flex items-start gap-2">
                <FileText size={14} className="mt-0.5 shrink-0" />
                <span>
                  No approved job descriptions yet. A JD becomes publishable once its
                  requisition clears HR review and MD approval.
                </span>
              </div>
            ) : (
              <select id="p-jd" value={jdNo} onChange={(e) => setJdNo(e.target.value)} className={FIELD}>
                {jds.map((j) => (
                  <option key={j.jd_no} value={j.jd_no}>{j.jd_no} — {j.title || 'Untitled'}</option>
                ))}
              </select>
            )}
          </div>

          <div>
            <span className={LABEL}>Platforms *</span>
            <div className="flex flex-wrap gap-1.5">
              {PLATFORMS.map((p) => (
                <button key={p} type="button" onClick={() => toggle(p)}
                  className={`px-2.5 py-1 rounded-lg text-[12px] font-bold border transition-colors ${
                    selected[p]
                      ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                      : 'border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
                  {p}
                </button>
              ))}
            </div>
          </div>

          {chosen.length > 0 && (
            <div className="space-y-2">
              <span className={LABEL}>Where each platform sends applicants</span>
              {chosen.map((p) => {
                const cfg = config[p] || { mode: 'auto', url: '', code: previewCode(p) };
                return (
                  <div key={p} className="p-3 rounded-xl border border-[var(--border)] bg-[var(--input-bg)] space-y-2">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <span className="text-[12.5px] font-bold text-[var(--text-main)]">{p}</span>
                      <div className="flex gap-1">
                        {[['auto', 'Generate form link'], ['external', 'Paste external link']].map(([mode, label]) => (
                          <button key={mode} type="button" onClick={() => setCfg(p, { mode })}
                            className={`px-2 py-0.5 rounded-md text-[11px] font-bold border ${
                              cfg.mode === mode
                                ? 'border-[var(--accent-indigo)] bg-[var(--bg-card)] text-[var(--accent-indigo)]'
                                : 'border-transparent text-[var(--text-muted)]'}`}>
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>
                    {cfg.mode === 'external' ? (
                      <>
                        <input value={cfg.url} onChange={(e) => setCfg(p, { url: e.target.value })}
                          placeholder="https://…" className={FIELD} />
                        <p className="text-[11px] text-[var(--accent-red)]">
                          Applications made on that site will <strong>not</strong> appear in this
                          pipeline — nothing sends them back here.
                        </p>
                      </>
                    ) : (
                      <div className="flex items-center gap-2 text-[11.5px] text-[var(--text-muted)]">
                        <Link2 size={13} className="shrink-0" />
                        <span className="font-mono truncate">{applyUrlFor(cfg.code)}</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className={LABEL} htmlFor="p-exp">Expiry date</label>
              <input id="p-exp" type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} className={FIELD} />
            </div>
            <div>
              <label className={LABEL} htmlFor="p-notes">Notes</label>
              <input id="p-notes" value={notes} onChange={(e) => setNotes(e.target.value)} className={FIELD} />
            </div>
          </div>

          <label className="flex items-start gap-2.5 cursor-pointer">
            <input type="checkbox" checked={requiresAssessment}
              onChange={(e) => setRequiresAssessment(e.target.checked)} className="mt-0.5" />
            <span className="text-[12.5px] text-[var(--text-main)]">
              <span className="font-bold">Require an assessment</span>
              <span className="block text-[11.5px] text-[var(--text-muted)]">
                Applicants must pass an assessment before interviews can be scheduled. The flag
                is copied onto each applicant when they apply.
              </span>
            </span>
          </label>

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose}
              className="h-9 px-4 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)]">
              Cancel
            </button>
            <button type="submit" disabled={saving || !jdNo || chosen.length === 0}
              className="h-9 px-4 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold disabled:opacity-50">
              {saving ? 'Publishing…' : `Publish to ${chosen.length || 0}`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default CreatePostingModal;
