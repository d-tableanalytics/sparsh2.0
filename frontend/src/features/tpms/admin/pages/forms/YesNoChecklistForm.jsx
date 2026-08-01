import React, { useEffect, useMemo, useState } from 'react';
import { Save, RefreshCw, Users, ClipboardList, CheckCircle2, Lock } from 'lucide-react';
import { DashboardHero, Section } from '../../../common/dashboardKit';
import { useNotification } from '../../../../../context/NotificationContext';
import {
  getFormDefinitions,
  getCompanies,
  getFormMembers,
  getFeedback,
  submitFeedback,
} from '../../../../../services/tpmsFormsApi';

/**
 * Yes/No checklist engine (Implementation Feedback).
 *
 * Mirrors the source Apps Script form: pick Company + MD + Month, then answer a
 * flat list of questions with a checkbox (ticked = Yes) + optional remark.
 * Partial submission — previously-saved answers come back locked with a YES/NO
 * tag; the MD fills only the remaining ones. A slot is submitted only if it's
 * ticked OR has a remark (an untouched "No" is skipped so it can be filled later).
 * Driven entirely by the backend definition's `questions` for `formType`.
 */
const YesNoChecklistForm = ({ formType, icon }) => {
  const { showSuccess, showError } = useNotification();

  const [definition, setDefinition] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [loadingDefs, setLoadingDefs] = useState(true);

  const [companyId, setCompanyId] = useState('');
  const [mdKey, setMdKey] = useState('');
  const [period, setPeriod] = useState('');

  const [mdOptions, setMdOptions] = useState([]);
  const [loadingMembers, setLoadingMembers] = useState(false);

  const [saved, setSaved] = useState({});         // { question_id: {checked, remark, question} } (locked)
  const [draft, setDraft] = useState({});         // { question_id: {checked, remark} } (editable)
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const questions = definition?.questions || [];

  // ── Load definition + companies once ──
  useEffect(() => {
    let alive = true;
    (async () => {
      setLoadingDefs(true);
      try {
        const [defRes, coRes] = await Promise.all([getFormDefinitions(), getCompanies()]);
        if (!alive) return;
        setDefinition((defRes.data?.definitions || []).find((d) => d.form_type === formType) || null);
        setCompanies(coRes.data || []);
      } catch (err) {
        if (alive) showError(err.response?.data?.detail || 'Failed to load form configuration');
      } finally {
        if (alive) setLoadingDefs(false);
      }
    })();
    return () => { alive = false; };
  }, [formType, showError]);

  // ── Load MD options (company roster) when company changes ──
  useEffect(() => {
    if (!companyId) { setMdOptions([]); setMdKey(''); return; }
    let alive = true;
    (async () => {
      setLoadingMembers(true);
      try {
        const res = await getFormMembers(companyId);
        if (!alive) return;
        setMdOptions((res.data?.members || []).map((m) => ({ ...m, key: m.member_id })));
      } catch (err) {
        if (alive) showError(err.response?.data?.detail || 'Failed to load MD list');
      } finally {
        if (alive) setLoadingMembers(false);
      }
    })();
    return () => { alive = false; };
  }, [companyId, showError]);

  const md = useMemo(() => mdOptions.find((m) => m.key === mdKey), [mdOptions, mdKey]);
  const mdId = md?.employee_id || md?.member_id || '';
  const companyName = useMemo(
    () => companies.find((c) => (c._id || c.id) === companyId)?.name || companyId,
    [companies, companyId],
  );

  // ── Load already-saved answers (lock state) when company+md+period all set ──
  const refreshSaved = React.useCallback(async () => {
    if (!companyId || !mdId || !period.trim()) { setSaved({}); return; }
    setLoadingSaved(true);
    try {
      const res = await getFeedback(formType, { company_id: companyId, period: period.trim(), md_id: mdId });
      setSaved(res.data?.answers || {});
      setDraft({});
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to load saved answers');
    } finally {
      setLoadingSaved(false);
    }
  }, [formType, companyId, mdId, period, showError]);

  useEffect(() => { refreshSaved(); }, [refreshSaved]);

  const setChecked = (qid, checked) =>
    setDraft((p) => ({ ...p, [qid]: { ...(p[qid] || {}), checked } }));
  const setRemark = (qid, remark) =>
    setDraft((p) => ({ ...p, [qid]: { ...(p[qid] || {}), remark } }));

  const editableQuestions = questions.filter((q) => saved[String(q.id)] == null);
  const answeredInDraft = editableQuestions.filter((q) => {
    const d = draft[String(q.id)] || {};
    return d.checked || (d.remark || '').trim();
  }).length;

  const handleSubmit = async () => {
    if (!companyId) return showError('Please select a company');
    if (!mdKey) return showError('Please select the MD');
    if (!period.trim()) return showError('Please enter the month / period');

    const answers = editableQuestions
      .map((q) => {
        const d = draft[String(q.id)] || {};
        return { question_id: String(q.id), question: q.title, checked: !!d.checked, remark: (d.remark || '').trim() };
      })
      .filter((a) => a.checked || a.remark);   // only ticked or remarked slots

    if (!answers.length) return showError('Tick a box or add a remark before submitting.');

    setSaving(true);
    try {
      const res = await submitFeedback(formType, {
        company_id: companyId,
        period: period.trim(),
        md_id: mdId,
        md_name: md?.member_name || null,
        answers,
      });
      showSuccess(res.data?.message || 'Feedback recorded');
      await refreshSaved();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to submit feedback');
    } finally {
      setSaving(false);
    }
  };

  if (loadingDefs) {
    return <div className="py-20 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading form…</div>;
  }

  const title = definition?.title || 'Implementation Feedback';

  if (definition && definition.available === false) {
    return (
      <div className="space-y-5">
        <DashboardHero icon={icon || ClipboardList} title={title} subtitle="This form is not configured yet." />
        <Section title="Awaiting questions" icon={ClipboardList}>
          <div className="px-5 py-10 text-center text-[13px] text-[var(--text-muted)]">
            The questions for “{title}” haven't been added yet. Once the question list is provided
            they'll appear here automatically — no further setup needed.
          </div>
        </Section>
      </div>
    );
  }

  const ctx = companyId ? `${companyName}${period ? ` · ${period}` : ''}${md ? ` · MD: ${md.member_name}` : ''}` : undefined;
  const totalQ = questions.length;
  const savedCount = Object.keys(saved).length;
  const ready = companyId && mdKey && period.trim();

  return (
    <div className="space-y-5">
      <DashboardHero icon={icon || ClipboardList} title={title} highlight={ctx} subtitle={definition?.description}>
        <button
          onClick={handleSubmit}
          disabled={saving || !ready}
          className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-white text-[var(--accent-indigo)] text-[12.5px] font-bold shadow-sm hover:bg-white/90 transition-all disabled:opacity-60"
        >
          {saving ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
          {saving ? 'Submitting…' : 'Submit'}
        </button>
      </DashboardHero>

      {/* Context selectors */}
      <Section title="Submission Details" icon={Users}>
        <div className="px-5 py-4 grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <label className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">Company</label>
            <select value={companyId} onChange={(e) => setCompanyId(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)]">
              <option value="">Select company…</option>
              {companies.map((c) => <option key={c._id || c.id} value={c._id || c.id}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">MD</label>
            <select value={mdKey} onChange={(e) => setMdKey(e.target.value)} disabled={!companyId || loadingMembers}
              className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] disabled:opacity-60">
              <option value="">{loadingMembers ? 'Loading…' : 'Select MD…'}</option>
              {mdOptions.map((m) => (
                <option key={m.key} value={m.key}>{m.member_name}{m.designation ? ` — ${m.designation}` : ''}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">Month / Period</label>
            <input type="text" value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="e.g. jan26"
              className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)]" />
          </div>
        </div>
        {ready && (
          <div className="px-5 pb-4 -mt-1 text-[12px] text-[var(--text-muted)]">
            {savedCount > 0 && (
              <span className="inline-flex items-center gap-1.5 mr-3 text-[var(--accent-green)] font-semibold">
                <Lock size={12} /> {savedCount} already saved (locked)
              </span>
            )}
            {loadingSaved ? 'Loading saved answers…' : `${answeredInDraft} / ${editableQuestions.length} to answer this visit · ${totalQ} total`}
          </div>
        )}
      </Section>

      {/* Questions */}
      {ready && questions.map((q, i) => {
        const qid = String(q.id);
        const lock = saved[qid];
        const locked = lock != null;
        const d = draft[qid] || {};
        return (
          <Section key={qid} title={`${i + 1}. ${q.title}`} subtitle={q.desc || undefined}
            icon={locked ? CheckCircle2 : ClipboardList} tone={locked ? 'green' : 'navy'}>
            <div className="px-5 py-4 space-y-3">
              {locked ? (
                <div className="flex items-center gap-3">
                  <span className={`text-[12px] font-bold px-2.5 py-1 rounded-full ${lock.checked ? 'text-[var(--accent-green)] bg-[var(--accent-green-bg)]' : 'text-[var(--accent-red)] bg-[var(--accent-red-bg)]'}`}>
                    {lock.checked ? 'YES' : 'NO'}
                  </span>
                  <span className="inline-flex items-center gap-1 text-[11px] text-[var(--text-muted)]"><Lock size={12} /> saved</span>
                </div>
              ) : (
                <label className="inline-flex items-center gap-2.5 cursor-pointer select-none">
                  <input type="checkbox" checked={!!d.checked} onChange={(e) => setChecked(qid, e.target.checked)}
                    className="w-[22px] h-[22px] accent-[var(--accent-indigo)] cursor-pointer" />
                  <span className="text-[13px] font-semibold">{d.checked ? 'Yes' : 'Tick for Yes'}</span>
                </label>
              )}
              <div>
                <div className="text-[11px] text-[var(--text-muted)] mb-1">Remark (optional)</div>
                <textarea rows={2} disabled={locked}
                  value={locked ? (lock.remark || '') : (d.remark || '')}
                  onChange={(e) => setRemark(qid, e.target.value)}
                  placeholder={locked ? '' : 'Add a note…'}
                  className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] outline-none focus:border-[var(--accent-indigo)] disabled:opacity-70 resize-y" />
              </div>
            </div>
          </Section>
        );
      })}
    </div>
  );
};

export default YesNoChecklistForm;
