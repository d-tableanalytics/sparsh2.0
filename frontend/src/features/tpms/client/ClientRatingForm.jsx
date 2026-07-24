import React, { useEffect, useMemo, useState } from 'react';
import { Save, RefreshCw, Users, ClipboardCheck, Lock, User } from 'lucide-react';
import { DashboardHero, Section, TableShell, Th, Td } from '../common/dashboardKit';
import { useNotification } from '../../../context/NotificationContext';
import { useAuth } from '../../../context/AuthContext';
import { getFormDefinitions, getFormMembers, getRatings, submitRatings } from '../../../services/tpmsFormsApi';

/**
 * Client-side rating-matrix form (self-service).
 *
 * Company + respondent are the logged-in user — there are no selectors. Two modes,
 * driven by the backend definition:
 *   • audience "hod"  (Accountability / Ownership) → the HOD rates each TEAM member.
 *   • self_rating     (Culture)                    → the user rates THEMSELVES.
 * Cell-level partial submission is preserved: already-saved cells load locked; submit
 * appends only the newly-filled ones. The backend scopes every read/write to the caller.
 */

// Default period token, e.g. "jul26" (matches the source form's MID style).
const defaultPeriod = (now) => {
  const d = now || new Date();
  const mon = d.toLocaleString('en-US', { month: 'short' }).toLowerCase();
  return `${mon}${String(d.getFullYear()).slice(-2)}`;
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

const ClientRatingForm = ({ formType, icon }) => {
  const { showSuccess, showError } = useNotification();
  const { user } = useAuth();

  const companyId = user?.company_id || '';
  const selfId = String(user?._id || user?.id || '');
  const selfName = user?.full_name || [user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.email || 'Me';

  const [definition, setDefinition] = useState(null);
  const [loadingDefs, setLoadingDefs] = useState(true);
  const [period, setPeriod] = useState(defaultPeriod());

  const [rows, setRows] = useState([]);
  const [loadingMembers, setLoadingMembers] = useState(false);

  const [savedRatings, setSavedRatings] = useState({});   // { code: { member_id: {rating,...} } } (locked)
  const [picks, setPicks] = useState({});                 // { "code::member_id": rating } (draft)
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const criteria = definition?.criteria || [];
  const scaleMin = definition?.scale?.min ?? 0;
  const scaleMax = definition?.scale?.max ?? 5;
  const selfRating = !!definition?.self_rating;

  // ── Load definition once ──
  useEffect(() => {
    let alive = true;
    (async () => {
      setLoadingDefs(true);
      try {
        const res = await getFormDefinitions();
        if (!alive) return;
        setDefinition((res.data?.definitions || []).find((d) => d.form_type === formType) || null);
      } catch (err) {
        if (alive) showError(err.response?.data?.detail || 'Failed to load form configuration');
      } finally {
        if (alive) setLoadingDefs(false);
      }
    })();
    return () => { alive = false; };
  }, [formType, showError]);

  // ── Build the rows to rate: self (culture) or the team roster (HOD forms) ──
  useEffect(() => {
    if (!definition) return;
    let alive = true;
    if (selfRating) {
      setRows([{ member_id: selfId, member_name: selfName, designation: user?.designation || null, employee_id: user?.employee_id || null, key: selfId }]);
      setPicks({});
      return () => { alive = false; };
    }
    (async () => {
      setLoadingMembers(true);
      try {
        const res = await getFormMembers(companyId, selfId);   // roster excludes the HOD (self)
        if (!alive) return;
        setRows((res.data?.members || []).map((m) => ({ ...m, key: m.member_id })));
        setPicks({});
      } catch (err) {
        if (alive) showError(err.response?.data?.detail || 'Failed to load your team members');
      } finally {
        if (alive) setLoadingMembers(false);
      }
    })();
    return () => { alive = false; };
  }, [definition, selfRating, companyId, selfId, selfName, user, showError]);

  // ── Load already-saved ratings (lock state) ──
  const refreshSaved = React.useCallback(async () => {
    if (!companyId || !period.trim() || !definition || definition.available === false) { setSavedRatings({}); return; }
    setLoadingSaved(true);
    try {
      const res = await getRatings(formType, { company_id: companyId, period: period.trim(), hod_id: selfId });
      setSavedRatings(res.data?.ratings || {});
      setPicks({});
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to load saved ratings');
    } finally {
      setLoadingSaved(false);
    }
  }, [formType, companyId, selfId, period, definition, showError]);

  useEffect(() => { refreshSaved(); }, [refreshSaved]);

  const cellKey = (code, memberId) => `${code}::${memberId}`;
  const savedCell = (code, memberId) => savedRatings?.[code]?.[memberId];
  const setPick = (code, memberId, v) => setPicks((p) => ({ ...p, [cellKey(code, memberId)]: v }));

  const ready = companyId && period.trim();

  const { totalCells, savedCount, pickedCount } = useMemo(() => {
    let saved = 0, picked = 0;
    criteria.forEach((c) => rows.forEach((m) => {
      if (savedCell(c.code, m.member_id) != null) saved += 1;
      else if (picks[cellKey(c.code, m.member_id)] != null) picked += 1;
    }));
    return { totalCells: criteria.length * rows.length, savedCount: saved, pickedCount: picked };
  }, [criteria, rows, savedRatings, picks]);

  const handleSubmit = async () => {
    if (!companyId) return showError('Your account has no company assigned. Contact your administrator.');
    if (!period.trim()) return showError('Please enter the month / period');
    if (!rows.length) return showError(selfRating ? 'Nothing to rate.' : 'You have no team members to rate.');

    const cells = [];
    criteria.forEach((c) => rows.forEach((m) => {
      if (savedCell(c.code, m.member_id) != null) return;        // locked → skip
      const v = picks[cellKey(c.code, m.member_id)];
      if (v == null) return;                                      // blank → leave for next visit
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
        hod_id: selfId,
        hod_name: selfName,
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

  const title = definition?.title || 'Rating';

  if (definition && definition.available === false) {
    return (
      <div className="space-y-5">
        <DashboardHero icon={icon || ClipboardCheck} title={title} subtitle="This form is not configured yet." />
        <Section title="Awaiting configuration" icon={ClipboardCheck}>
          <div className="px-5 py-10 text-center text-[13px] text-[var(--text-muted)]">
            The criteria for “{title}” haven't been added yet. Once they're provided they'll
            appear here automatically — no further setup needed.
          </div>
        </Section>
      </div>
    );
  }

  const highlight = `${selfName}${period ? ` · ${period}` : ''}`;

  return (
    <div className="space-y-5">
      <DashboardHero
        icon={icon || ClipboardCheck}
        title={title}
        highlight={highlight}
        subtitle={selfRating ? 'Rate yourself on each criterion (0–5).' : 'Rate each of your team members on every criterion (0–5).'}
      >
        <button
          onClick={handleSubmit}
          disabled={saving || !ready}
          className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-white text-[var(--accent-indigo)] text-[12.5px] font-bold shadow-sm hover:bg-white/90 transition-all disabled:opacity-60"
        >
          {saving ? <RefreshCw size={14} className="animate-spin" /> : <Save size={14} />}
          {saving ? 'Submitting…' : 'Submit'}
        </button>
      </DashboardHero>

      {/* Period + progress */}
      <Section title="Submission Details" icon={selfRating ? User : Users}>
        <div className="px-5 py-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-[11px] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">Month / Period</label>
            <input type="text" value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="e.g. jul26"
              className="w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)]" />
          </div>
          <div className="flex items-end">
            <div className="text-[12px] text-[var(--text-muted)]">
              {savedCount > 0 && (
                <span className="inline-flex items-center gap-1.5 mr-3 text-[var(--accent-green)] font-semibold">
                  <Lock size={12} /> {savedCount} saved &amp; locked
                </span>
              )}
              {loadingSaved || loadingMembers ? 'Loading…' : `${savedCount + pickedCount} / ${totalCells} rated`}
            </div>
          </div>
        </div>
      </Section>

      {/* One matrix Section per criterion */}
      {ready && criteria.map((c, idx) => (
        <Section key={c.code} title={`${idx + 1}. ${c.code}. ${c.title}`} subtitle={c.prompt} icon={ClipboardCheck}>
          <TableShell minWidth={560}>
            <thead>
              <tr className="border-b border-[var(--border)]">
                <Th>{selfRating ? 'You' : 'Team Member'}</Th>
                <Th align="center">Rating ({scaleMin}–{scaleMax})</Th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><Td className="text-[var(--text-muted)]">{loadingMembers ? 'Loading…' : 'No members to rate.'}</Td></tr>
              )}
              {rows.map((m) => {
                const locked = savedCell(c.code, m.member_id) != null;
                const value = locked ? savedCell(c.code, m.member_id).rating : picks[cellKey(c.code, m.member_id)];
                return (
                  <tr key={m.member_id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)]">
                    <Td>
                      <div className="flex items-center gap-2">
                        <div>
                          <div className="font-semibold text-[13px]">{m.member_name}</div>
                          {m.designation && <div className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">{m.designation}</div>}
                        </div>
                        {locked && <Lock size={12} className="text-[var(--accent-green)]" title="Saved" />}
                      </div>
                    </Td>
                    <Td align="center">
                      <div className="flex justify-center">
                        <ScaleRadio min={scaleMin} max={scaleMax} name={`${c.code}-${m.member_id}`}
                          value={value} disabled={locked} onChange={(v) => setPick(c.code, m.member_id, v)} />
                      </div>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </TableShell>
        </Section>
      ))}
    </div>
  );
};

export default ClientRatingForm;
