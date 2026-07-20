import React, { useEffect, useMemo, useState } from 'react';
import { Save, RefreshCw, UserPlus, Trash2, History, Users, ClipboardCheck } from 'lucide-react';
import { DashboardHero, Section, TableShell, Th, Td } from '../../../common/dashboardKit';
import { useNotification } from '../../../../../context/NotificationContext';
import {
  getFormDefinitions,
  getCompanies,
  getFormMembers,
  submitForm,
  getFormSubmissions,
} from '../../../../../services/tpmsFormsApi';

/**
 * Reusable rating-matrix form engine for the TPMS ▸ Forms checklists
 * (Accountability, Ownership, …). Driven entirely by the backend form
 * definition for `formType`, so a new checklist needs no new UI code —
 * just criteria in backend/app/models/forms.py.
 *
 * Shape mirrors the source Google Forms: pick Company + HOD + Month, then
 * score every team member on each criterion using a 0–5 radio scale.
 */

let manualRowSeq = 0;
const newManualRow = () => ({
  key: `manual-${++manualRowSeq}`,
  member_id: null,
  employee_id: null,
  member_name: '',
  designation: '',
  department: null,
  manual: true,
});

const ScaleRadio = ({ min, max, value, onChange, name }) => {
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
            onChange={() => onChange(n)}
            className="w-[18px] h-[18px] accent-[var(--accent-indigo)] cursor-pointer"
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
  const [hodKey, setHodKey] = useState('');          // member_id of the chosen HOD
  const [period, setPeriod] = useState('');

  const [memberOptions, setMemberOptions] = useState([]); // company roster (for HOD + rows)
  const [rows, setRows] = useState([]);                    // members being rated
  const [scores, setScores] = useState({});                // { rowKey: { code: value } }
  const [loadingMembers, setLoadingMembers] = useState(false);
  const [saving, setSaving] = useState(false);

  const [submissions, setSubmissions] = useState([]);

  const criteria = definition?.criteria || [];
  const scaleMin = definition?.scale?.min ?? 0;
  const scaleMax = definition?.scale?.max ?? 5;

  // ── Load definition (criteria) + companies once ──
  useEffect(() => {
    let alive = true;
    (async () => {
      setLoadingDefs(true);
      try {
        const [defRes, coRes] = await Promise.all([getFormDefinitions(), getCompanies()]);
        if (!alive) return;
        const def = (defRes.data?.definitions || []).find((d) => d.form_type === formType) || null;
        setDefinition(def);
        setCompanies(coRes.data || []);
      } catch (err) {
        if (alive) showError(err.response?.data?.detail || 'Failed to load form configuration');
      } finally {
        if (alive) setLoadingDefs(false);
      }
    })();
    return () => { alive = false; };
  }, [formType, showError]);

  const rowKey = (m) => m.key || m.member_id || m.member_name;

  // ── Load company roster whenever company changes ──
  useEffect(() => {
    if (!companyId) {
      setMemberOptions([]); setRows([]); setScores({}); setHodKey('');
      return;
    }
    let alive = true;
    (async () => {
      setLoadingMembers(true);
      try {
        const res = await getFormMembers(companyId);
        if (!alive) return;
        const members = (res.data?.members || []).map((m) => ({ ...m, key: m.member_id }));
        setMemberOptions(members);
        setHodKey('');
        // Default: everyone in the roster becomes a ratable row.
        setRows(members);
        setScores({});
      } catch (err) {
        if (alive) showError(err.response?.data?.detail || 'Failed to load team members');
      } finally {
        if (alive) setLoadingMembers(false);
      }
    })();
    return () => { alive = false; };
  }, [companyId, showError]);

  // ── When HOD changes, drop them from the ratable rows ──
  useEffect(() => {
    if (!memberOptions.length) return;
    setRows(memberOptions.filter((m) => m.key !== hodKey));
  }, [hodKey, memberOptions]);

  // ── Load recent submissions for context ──
  const refreshSubmissions = React.useCallback(async () => {
    if (!companyId) { setSubmissions([]); return; }
    try {
      const res = await getFormSubmissions(formType, { company_id: companyId, period: period || undefined });
      setSubmissions(res.data?.submissions || []);
    } catch {
      /* non-fatal — the list is informational */
    }
  }, [formType, companyId, period]);

  useEffect(() => { refreshSubmissions(); }, [refreshSubmissions]);

  const setScore = (key, code, value) => {
    setScores((prev) => ({ ...prev, [key]: { ...(prev[key] || {}), [code]: value } }));
  };

  const addManualRow = () => setRows((prev) => [...prev, newManualRow()]);
  const removeRow = (key) => {
    setRows((prev) => prev.filter((m) => rowKey(m) !== key));
    setScores((prev) => { const n = { ...prev }; delete n[key]; return n; });
  };
  const updateRowField = (key, field, value) => {
    setRows((prev) => prev.map((m) => (rowKey(m) === key ? { ...m, [field]: value } : m)));
  };

  const hod = useMemo(() => memberOptions.find((m) => m.key === hodKey), [memberOptions, hodKey]);
  const companyName = useMemo(
    () => companies.find((c) => (c._id || c.id) === companyId)?.name || companyId,
    [companies, companyId],
  );

  const validate = () => {
    if (!companyId) return 'Please select a company';
    if (!period.trim()) return 'Please enter the month / period';
    if (!hodKey) return 'Please select the HOD';
    if (!rows.length) return 'Add at least one team member to rate';
    for (const m of rows) {
      const key = rowKey(m);
      if (!m.member_name?.trim()) return 'Every member row needs a name';
      const s = scores[key] || {};
      for (const c of criteria) {
        if (typeof s[c.code] !== 'number') {
          return `Score "${c.title}" for ${m.member_name || 'a member'}`;
        }
      }
    }
    return null;
  };

  const handleSubmit = async () => {
    const err = validate();
    if (err) { showError(err); return; }
    setSaving(true);
    try {
      const payload = {
        company_id: companyId,
        period: period.trim(),
        hod_id: hod?.employee_id || hod?.member_id || null,
        hod_name: hod?.member_name || null,
        members: rows.map((m) => ({
          member_id: m.member_id || null,
          employee_id: m.employee_id || null,
          member_name: m.member_name.trim(),
          designation: m.designation || null,
          department: m.department || null,
          scores: scores[rowKey(m)] || {},
        })),
      };
      await submitForm(formType, payload);
      showSuccess(`${definition?.title || 'Form'} submitted successfully`);
      setScores({});
      refreshSubmissions();
    } catch (e) {
      showError(e.response?.data?.detail || 'Failed to submit the form');
    } finally {
      setSaving(false);
    }
  };

  const heroTitle = definition?.title || 'Checklist';
  const highlight = companyId ? `${companyName}${period ? ` · ${period}` : ''}` : undefined;

  if (loadingDefs) {
    return <div className="py-20 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading form…</div>;
  }

  if (definition && definition.available === false) {
    return (
      <div className="space-y-5">
        <DashboardHero icon={icon || ClipboardCheck} title={heroTitle} subtitle="This checklist is not configured yet." />
        <Section title="Awaiting configuration" icon={ClipboardCheck}>
          <div className="px-5 py-10 text-center text-[13px] text-[var(--text-muted)]">
            The criteria for “{heroTitle}” haven't been added yet. Once the form's questions are
            provided they'll appear here automatically — no further setup needed.
          </div>
        </Section>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <DashboardHero
        icon={icon || ClipboardCheck}
        title={heroTitle}
        highlight={highlight}
        subtitle={definition?.description}
      >
        <button
          onClick={handleSubmit}
          disabled={saving}
          className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-white text-[var(--accent-indigo)] text-[12.5px] font-bold shadow-sm hover:bg-white/90 transition-all disabled:opacity-60"
        >
          {saving ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
          {saving ? 'Submitting…' : 'Submit'}
        </button>
      </DashboardHero>

      {/* ── Context selectors ── */}
      <Section title="Submission Details" icon={Users}>
        <div className="px-5 py-4 grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <label className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">Company</label>
            <select
              value={companyId}
              onChange={(e) => setCompanyId(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)]"
            >
              <option value="">Select company…</option>
              {companies.map((c) => (
                <option key={c._id || c.id} value={c._id || c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">HOD</label>
            <select
              value={hodKey}
              onChange={(e) => setHodKey(e.target.value)}
              disabled={!companyId || loadingMembers}
              className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] disabled:opacity-60"
            >
              <option value="">{loadingMembers ? 'Loading…' : 'Select HOD…'}</option>
              {memberOptions.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.member_name}{m.designation ? ` — ${m.designation}` : ''}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">Month / Period</label>
            <input
              type="text"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="e.g. july26"
              className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)]"
            />
          </div>
        </div>
      </Section>

      {/* ── One matrix Section per criterion (mirrors the source form) ── */}
      {companyId && criteria.map((c, idx) => (
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
                <tr><Td className="text-[var(--text-muted)]" >No members. Add one below or pick a company.</Td></tr>
              )}
              {rows.map((m) => {
                const key = rowKey(m);
                return (
                  <tr key={key} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)]">
                    <Td>
                      {m.manual ? (
                        <div className="flex flex-col gap-1">
                          <input
                            value={m.member_name}
                            onChange={(e) => updateRowField(key, 'member_name', e.target.value)}
                            placeholder="Member name"
                            className="px-2 py-1 rounded-md bg-[var(--input-bg)] border border-[var(--input-border)] text-[12.5px] outline-none focus:border-[var(--accent-indigo)]"
                          />
                          <input
                            value={m.designation || ''}
                            onChange={(e) => updateRowField(key, 'designation', e.target.value)}
                            placeholder="Designation"
                            className="px-2 py-1 rounded-md bg-[var(--input-bg)] border border-[var(--input-border)] text-[11px] outline-none focus:border-[var(--accent-indigo)]"
                          />
                        </div>
                      ) : (
                        <div>
                          <div className="font-semibold text-[13px]">{m.member_name}</div>
                          {m.designation && <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">{m.designation}</div>}
                        </div>
                      )}
                    </Td>
                    <Td align="center">
                      <div className="flex justify-center">
                        <ScaleRadio
                          min={scaleMin}
                          max={scaleMax}
                          name={`${c.code}-${key}`}
                          value={scores[key]?.[c.code]}
                          onChange={(v) => setScore(key, c.code, v)}
                        />
                      </div>
                    </Td>
                    {idx === 0 && (
                      <Td align="right">
                        <button
                          onClick={() => removeRow(key)}
                          title="Remove member"
                          className="p-1.5 rounded-md text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] transition-colors"
                        >
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
              <button
                onClick={addManualRow}
                className="inline-flex items-center gap-1.5 text-[12px] font-bold text-[var(--accent-indigo)] hover:opacity-80"
              >
                <UserPlus size={14} /> Add member
              </button>
            </div>
          )}
        </Section>
      ))}

      {/* ── Recent submissions (informational) ── */}
      {companyId && (
        <Section title="Recent Submissions" subtitle="Stored responses for this company" icon={History}>
          <TableShell minWidth={720}>
            <thead>
              <tr className="border-b border-[var(--border)]">
                <Th>Period</Th><Th>HOD</Th><Th align="center">Members</Th><Th>Submitted By</Th><Th align="right">When</Th>
              </tr>
            </thead>
            <tbody>
              {submissions.length === 0 && (
                <tr><Td className="text-[var(--text-muted)]">No submissions yet.</Td></tr>
              )}
              {submissions.map((s) => (
                <tr key={s._id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)]">
                  <Td className="font-semibold">{s.period}</Td>
                  <Td>{s.hod_name || '—'}</Td>
                  <Td align="center">{s.members?.length ?? 0}</Td>
                  <Td>{s.submitted_by_name || '—'}</Td>
                  <Td align="right" className="text-[var(--text-muted)] text-[11.5px]">
                    {s.created_at ? new Date(s.created_at).toLocaleString() : '—'}
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        </Section>
      )}
    </div>
  );
};

export default ChecklistForm;
