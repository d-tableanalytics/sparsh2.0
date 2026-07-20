import React, { useEffect, useMemo, useState } from 'react';
import { Save, RefreshCw, UserPlus, Trash2, Users, ClipboardCheck, Lock } from 'lucide-react';
import { DashboardHero, Section, TableShell, Th, Td } from '../../../common/dashboardKit';
import { useNotification } from '../../../../../context/NotificationContext';
import {
  getFormDefinitions,
  getCompanies,
  getFormMembers,
  getRatings,
  submitRatings,
} from '../../../../../services/tpmsFormsApi';

/**
 * Rating-matrix engine (Ownership / Accountability / Culture).
 *
 * Mirrors the source Google Forms exactly: pick Company + HOD + Month, then score
 * every team member on each criterion using a 0–5 radio scale. Supports CELL-LEVEL
 * partial submission — each already-saved (criterion × member) cell loads locked
 * and pre-selected; submit appends only the newly-filled cells (no duplicates).
 * Fully driven by the backend definition's `criteria` for `formType`.
 */

let manualRowSeq = 0;
const newManualRow = () => {
  const id = `manual-${++manualRowSeq}`;
  return { key: id, member_id: id, employee_id: null, member_name: '', designation: '', department: null, manual: true };
};

const ScaleRadio = ({ min, max, value, onChange, name, disabled }) => {
  const opts = [];
  for (let i = min; i <= max; i += 1) opts.push(i);
  return (
    <div className="flex items-center gap-4 sm:gap-6">
      {opts.map((n) => (
        <label key={n} className="flex flex-col items-center gap-1 cursor-pointer select-none">
          <span className="text-[11px] font-bold text-[var(--text-muted)] tabular-nums">{n}</span>
          <input
            type="radio"
            name={name}
            checked={value === n}
            disabled={disabled}
            onChange={() => onChange(n)}
            className="w-[18px] h-[18px] accent-[var(--accent-indigo)] cursor-pointer disabled:cursor-default disabled:opacity-70"
          />
        </label>
      ))}
    </div>
  );
};

const ChecklistForm = ({ formType, icon }) => {
  const { showSuccess, showError } = useNotification();

  const [definition, setDefinition] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [loadingDefs, setLoadingDefs] = useState(true);

  const [companyId, setCompanyId] = useState('');
  const [hodKey, setHodKey] = useState('');
  const [period, setPeriod] = useState('');

  const [memberOptions, setMemberOptions] = useState([]);
  const [rows, setRows] = useState([]);
  const [loadingMembers, setLoadingMembers] = useState(false);

  const [savedRatings, setSavedRatings] = useState({});   // { code: { member_id: {rating, ...} } } (locked)
  const [picks, setPicks] = useState({});                 // { "code::member_id": rating } (editable draft)
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const criteria = definition?.criteria || [];
  const scaleMin = definition?.scale?.min ?? 0;
  const scaleMax = definition?.scale?.max ?? 5;

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

  // ── Load company roster when company changes ──
  useEffect(() => {
    if (!companyId) { setMemberOptions([]); setRows([]); setHodKey(''); setPicks({}); return; }
    let alive = true;
    (async () => {
      setLoadingMembers(true);
      try {
        const res = await getFormMembers(companyId);
        if (!alive) return;
        const members = (res.data?.members || []).map((m) => ({ ...m, key: m.member_id }));
        setMemberOptions(members);
        setHodKey('');
        setRows(members);
        setPicks({});
      } catch (err) {
        if (alive) showError(err.response?.data?.detail || 'Failed to load team members');
      } finally {
        if (alive) setLoadingMembers(false);
      }
    })();
    return () => { alive = false; };
  }, [companyId, showError]);

  // ── Drop the chosen HOD from the ratable rows ──
  useEffect(() => {
    if (!memberOptions.length) return;
    setRows(memberOptions.filter((m) => m.key !== hodKey));
  }, [hodKey, memberOptions]);

  const hod = useMemo(() => memberOptions.find((m) => m.key === hodKey), [memberOptions, hodKey]);
  const hodId = hod?.employee_id || hod?.member_id || '';
  const companyName = useMemo(
    () => companies.find((c) => (c._id || c.id) === companyId)?.name || companyId,
    [companies, companyId],
  );

  // ── Load already-saved ratings (lock state) ──
  const refreshSaved = React.useCallback(async () => {
    if (!companyId || !hodId || !period.trim()) { setSavedRatings({}); return; }
    setLoadingSaved(true);
    try {
      const res = await getRatings(formType, { company_id: companyId, period: period.trim(), hod_id: hodId });
      setSavedRatings(res.data?.ratings || {});
      setPicks({});
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to load saved ratings');
    } finally {
      setLoadingSaved(false);
    }
  }, [formType, companyId, hodId, period, showError]);

  useEffect(() => { refreshSaved(); }, [refreshSaved]);

  const cellKey = (code, memberId) => `${code}::${memberId}`;
  const savedCell = (code, memberId) => savedRatings?.[code]?.[memberId];
  const setPick = (code, memberId, v) => setPicks((p) => ({ ...p, [cellKey(code, memberId)]: v }));

  const addManualRow = () => setRows((prev) => [...prev, newManualRow()]);
  const removeRow = (memberId) => setRows((prev) => prev.filter((m) => m.member_id !== memberId));
  const updateRowField = (memberId, field, value) =>
    setRows((prev) => prev.map((m) => (m.member_id === memberId ? { ...m, [field]: value } : m)));

  const ready = companyId && hodKey && period.trim();

  // ── Progress ──
  const { totalCells, savedCount, pickedCount } = useMemo(() => {
    let saved = 0, picked = 0;
    criteria.forEach((c) => rows.forEach((m) => {
      if (savedCell(c.code, m.member_id) != null) saved += 1;
      else if (picks[cellKey(c.code, m.member_id)] != null) picked += 1;
    }));
    return { totalCells: criteria.length * rows.length, savedCount: saved, pickedCount: picked };
  }, [criteria, rows, savedRatings, picks]);

  const handleSubmit = async () => {
    if (!companyId) return showError('Please select a company');
    if (!hodKey) return showError('Please select the HOD');
    if (!period.trim()) return showError('Please enter the month / period');
    if (!rows.length) return showError('Add at least one team member to rate');

    const cells = [];
    criteria.forEach((c) => rows.forEach((m) => {
      if (savedCell(c.code, m.member_id) != null) return;         // locked → skip
      const v = picks[cellKey(c.code, m.member_id)];
      if (v == null) return;                                       // blank → leave for next visit
      if (!m.member_name?.trim()) return;
      cells.push({
        criterion_code: c.code,
        member_id: m.member_id,
        member_name: m.member_name.trim(),
        designation: m.designation || null,
        employee_id: m.employee_id || null,
        rating: v,
      });
    }));

    if (!cells.length) return showError('Pick at least one rating before submitting.');

    setSaving(true);
    try {
      const res = await submitRatings(formType, {
        company_id: companyId,
        period: period.trim(),
        hod_id: hodId,
        hod_name: hod?.member_name || null,
        ratings: cells,
      });
      showSuccess(res.data?.message || 'Ratings saved');
      await refreshSaved();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to submit ratings');
    } finally {
      setSaving(false);
    }
  };

  if (loadingDefs) {
    return <div className="py-20 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading form…</div>;
  }

  const title = definition?.title || 'Checklist';

  if (definition && definition.available === false) {
    return (
      <div className="space-y-5">
        <DashboardHero icon={icon || ClipboardCheck} title={title} subtitle="This checklist is not configured yet." />
        <Section title="Awaiting configuration" icon={ClipboardCheck}>
          <div className="px-5 py-10 text-center text-[13px] text-[var(--text-muted)]">
            The criteria for “{title}” haven't been added yet. Once the questions are provided
            they'll appear here automatically — no further setup needed.
          </div>
        </Section>
      </div>
    );
  }

  const highlight = companyId
    ? `${companyName}${period ? ` · ${period}` : ''}${hod ? ` · HOD: ${hod.member_name}` : ''}`
    : undefined;

  return (
    <div className="space-y-5">
      <DashboardHero icon={icon || ClipboardCheck} title={title} highlight={highlight} subtitle={definition?.description}>
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
            <label className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">HOD</label>
            <select value={hodKey} onChange={(e) => setHodKey(e.target.value)} disabled={!companyId || loadingMembers}
              className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] disabled:opacity-60">
              <option value="">{loadingMembers ? 'Loading…' : 'Select HOD…'}</option>
              {memberOptions.map((m) => (
                <option key={m.key} value={m.key}>{m.member_name}{m.designation ? ` — ${m.designation}` : ''}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">Month / Period</label>
            <input type="text" value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="e.g. jun26"
              className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)]" />
          </div>
        </div>
        {ready && (
          <div className="px-5 pb-4 -mt-1 text-[12px] text-[var(--text-muted)]">
            {savedCount > 0 && (
              <span className="inline-flex items-center gap-1.5 mr-3 text-[var(--accent-green)] font-semibold">
                <Lock size={12} /> {savedCount} cell(s) saved &amp; locked
              </span>
            )}
            {loadingSaved ? 'Loading saved ratings…' : `${savedCount + pickedCount} / ${totalCells} rated`}
          </div>
        )}
      </Section>

      {/* One matrix Section per criterion */}
      {ready && criteria.map((c, idx) => (
        <Section key={c.code} title={`${idx + 1}. ${c.code}. ${c.title}`} subtitle={c.prompt} icon={ClipboardCheck}>
          <TableShell minWidth={640}>
            <thead>
              <tr className="border-b border-[var(--border)]">
                <Th>Team Member</Th>
                <Th align="center">Rating ({scaleMin}–{scaleMax})</Th>
                {idx === 0 && <Th align="right"> </Th>}
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><Td className="text-[var(--text-muted)]">No members. Add one below or pick a company.</Td></tr>
              )}
              {rows.map((m) => {
                const locked = savedCell(c.code, m.member_id) != null;
                const lockedVal = locked ? savedCell(c.code, m.member_id).rating : undefined;
                const value = locked ? lockedVal : picks[cellKey(c.code, m.member_id)];
                return (
                  <tr key={m.member_id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)]">
                    <Td>
                      {m.manual ? (
                        <div className="flex flex-col gap-1">
                          <input value={m.member_name} onChange={(e) => updateRowField(m.member_id, 'member_name', e.target.value)}
                            placeholder="Member name"
                            className="px-2 py-1 rounded-md bg-[var(--input-bg)] border border-[var(--input-border)] text-[12.5px] outline-none focus:border-[var(--accent-indigo)]" />
                          <input value={m.designation || ''} onChange={(e) => updateRowField(m.member_id, 'designation', e.target.value)}
                            placeholder="Designation"
                            className="px-2 py-1 rounded-md bg-[var(--input-bg)] border border-[var(--input-border)] text-[11px] outline-none focus:border-[var(--accent-indigo)]" />
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <div>
                            <div className="font-semibold text-[13px]">{m.member_name}</div>
                            {m.designation && <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">{m.designation}</div>}
                          </div>
                          {locked && <Lock size={12} className="text-[var(--accent-green)]" title="Saved" />}
                        </div>
                      )}
                    </Td>
                    <Td align="center">
                      <div className="flex justify-center">
                        <ScaleRadio min={scaleMin} max={scaleMax} name={`${c.code}-${m.member_id}`}
                          value={value} disabled={locked} onChange={(v) => setPick(c.code, m.member_id, v)} />
                      </div>
                    </Td>
                    {idx === 0 && (
                      <Td align="right">
                        <button onClick={() => removeRow(m.member_id)} title="Remove member"
                          className="p-1.5 rounded-md text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] transition-colors">
                          <Trash2 size={15} />
                        </button>
                      </Td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </TableShell>
          {idx === 0 && (
            <div className="px-5 py-3 border-t border-[var(--border)]">
              <button onClick={addManualRow} className="inline-flex items-center gap-1.5 text-[12px] font-bold text-[var(--accent-indigo)] hover:opacity-80">
                <UserPlus size={14} /> Add member
              </button>
            </div>
          )}
        </Section>
      ))}
    </div>
  );
};

export default ChecklistForm;
