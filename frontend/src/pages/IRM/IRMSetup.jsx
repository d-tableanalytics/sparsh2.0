import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  SlidersHorizontal, Save, RotateCcw, AlertTriangle, CheckCircle2, RefreshCw,
  Percent, ShieldAlert, Gauge, Calculator, ArrowLeft,
} from 'lucide-react';
import {
  DashboardHero, HeaderSelect, HeroButton, Section, Th, Td, TableShell,
} from '../../features/tpms/common/dashboardKit';
import { getIrmConfig, saveIrmConfig } from '../../services/irmApi';
import {
  canEditWeightages, errText, fmtNum, scoreColor, useAsync, useIrmCompany,
} from './irmUtils';

/* ─────────────────────────────────────────────────────────────
   IRM ▸ Setup — the sheet's highlighted weightage cells, made editable.

   The column must total exactly 100: the backend refuses anything else, and Save stays
   disabled until the draft agrees, so an invalid split can never be persisted. The
   preview panel re-runs the worked example against the draft as it is typed, so the
   effect of a change is visible before it is saved.

   Saving takes effect immediately — scores are derived from this config on every read,
   so there is no recalculation to wait for.
   ───────────────────────────────────────────────────────────── */

/** Sample achievement %s used only to illustrate the draft weightages. */
const PREVIEW_ACHIEVEMENT = { task: 80, delegation: 50, culture: 90, accountability: 75 };

const numOrZero = (v) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

/** The editable weightage cell. Kept as a string so a half-typed value isn't clobbered. */
const WeightageInput = ({ value, onChange, disabled }) => (
  <input
    type="number"
    min={0}
    max={100}
    step="0.01"
    value={value}
    disabled={disabled}
    onChange={(e) => onChange(e.target.value)}
    className="w-24 px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-bold tabular-nums text-right outline-none focus:border-[var(--accent-indigo)] transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
  />
);

const IRMSetup = () => {
  const navigate = useNavigate();
  const { user, staff, companies, companyId, setCompanyId } = useIrmCompany();
  const canEdit = canEditWeightages(user);

  const [draft, setDraft] = useState({});      // {code: string} — raw input values
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saved, setSaved] = useState('');

  const waitingForCompany = staff && !companyId;
  const companyOptions = useMemo(
    () => (companies.length ? companies : [{ id: '', name: 'Loading companies…' }]),
    [companies],
  );

  const load = useCallback(async () => (await getIrmConfig(companyId)).data, [companyId]);
  const { data: config, loading, error, reload } = useAsync(load, [companyId], {
    skip: waitingForCompany,
  });

  // Seed the draft from whatever the server currently holds.
  useEffect(() => {
    if (!config) return;
    setDraft(Object.fromEntries(config.parameters.map((p) => [p.code, String(p.weightage)])));
    setSaveError('');
    setSaved('');
  }, [config]);

  const parameters = useMemo(() => config?.parameters || [], [config]);
  const total = useMemo(
    () => Math.round(parameters.reduce((s, p) => s + numOrZero(draft[p.code]), 0) * 100) / 100,
    [parameters, draft],
  );
  const isValid = Math.abs(total - 100) < 0.01;
  const isDirty = parameters.some((p) => numOrZero(draft[p.code]) !== p.weightage);

  const setWeight = (code, value) => {
    setDraft((d) => ({ ...d, [code]: value }));
    setSaved('');
    setSaveError('');
  };

  const resetToSaved = () => {
    setDraft(Object.fromEntries(parameters.map((p) => [p.code, String(p.weightage)])));
    setSaved('');
    setSaveError('');
  };

  const resetToDefaults = () => {
    setDraft(Object.fromEntries(parameters.map((p) => [p.code, String(p.default_weightage)])));
    setSaved('');
    setSaveError('');
  };

  const save = async () => {
    setSaving(true);
    setSaveError('');
    setSaved('');
    try {
      const payload = parameters.map((p) => ({
        code: p.code,
        weightage: numOrZero(draft[p.code]),
      }));
      await saveIrmConfig(companyId, payload);
      setSaved('Weightages saved. IRM scores now use the updated values.');
      await reload();
    } catch (e) {
      setSaveError(errText(e, 'Could not save weightages.'));
    } finally {
      setSaving(false);
    }
  };

  // Worked example against the DRAFT, so the effect of an edit is visible before saving.
  const preview = useMemo(() => {
    const rows = parameters.map((p) => {
      const achievement = PREVIEW_ACHIEVEMENT[p.code] ?? 100;
      const weightage = numOrZero(draft[p.code]);
      return { ...p, achievement, weightage, weighted: Math.round(achievement * weightage) / 100 };
    });
    return { rows, final: Math.round(rows.reduce((s, r) => s + r.weighted, 0) * 100) / 100 };
  }, [parameters, draft]);

  if (!canEdit) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold">Administrators only</p>
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-sm">
          IRM weightages decide how every person is scored, so only a Super Admin or Admin
          can change them. You can see the weightages in force on the IRM scoreboard.
        </p>
        <Link to="/irm" className="text-[12.5px] font-bold text-[var(--accent-indigo)] hover:underline">
          Back to IRM
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <DashboardHero
        icon={SlidersHorizontal}
        title="IRM Setup"
        subtitle="Set each parameter's weightage — the column must total exactly 100%"
      >
        {staff && (
          <HeaderSelect value={companyId} onChange={setCompanyId} options={companyOptions} />
        )}
        <HeroButton icon={ArrowLeft} onClick={() => navigate('/irm')}>Back to IRM</HeroButton>
      </DashboardHero>

      {(error || saveError) && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error || saveError}
        </div>
      )}
      {saved && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)]">
          <CheckCircle2 size={15} /> {saved}
        </div>
      )}

      {waitingForCompany ? (
        <Section title="Weightage" subtitle="Select a company" icon={Percent}>
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Select a company to configure its IRM weightages.
          </div>
        </Section>
      ) : loading ? (
        <Section title="Weightage" subtitle="Loading" icon={Percent}>
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Loading weightages…
          </div>
        </Section>
      ) : (
        <>
          <Section
            title="Evaluation Parameters"
            subtitle={config?.is_customised
              ? `Last updated by ${config.updated_by || 'an administrator'}`
              : 'Using the default weightages — not yet customised'}
            icon={Percent}
          >
            <TableShell minWidth={720}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th>Evaluation Parameter</Th>
                  <Th>Measured From</Th>
                  <Th align="center">Default</Th>
                  <Th align="right">Weightage</Th>
                </tr>
              </thead>
              <tbody>
                {parameters.map((p) => (
                  <tr key={p.code} className="border-b border-[var(--border)] last:border-0">
                    <Td>
                      <span className="font-bold">{p.name}</span>
                      {p.description && (
                        <span className="block text-[10.5px] text-[var(--text-muted)] mt-0.5 max-w-[420px]">
                          {p.description}
                        </span>
                      )}
                    </Td>
                    <Td className="text-[var(--text-muted)]">
                      {p.source === 'form' ? 'Rating form (0–5 scale)' : 'Achieved ÷ Assigned'}
                    </Td>
                    <Td align="center" className="tabular-nums text-[var(--text-muted)]">
                      {fmtNum(p.default_weightage)}%
                    </Td>
                    <Td align="right">
                      <WeightageInput
                        value={draft[p.code] ?? ''}
                        onChange={(v) => setWeight(p.code, v)}
                        disabled={saving}
                      />
                    </Td>
                  </tr>
                ))}

                {/* GRAND TOTAL — the sheet's green row, and the rule Save enforces. */}
                <tr style={{
                  background: isValid ? 'var(--accent-green-bg)' : 'var(--accent-red-bg)',
                }}>
                  <Td className="font-extrabold uppercase tracking-wide text-[11px]"
                    style={{ color: isValid ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                    Grand Total
                  </Td>
                  <Td />
                  <Td />
                  <Td align="right">
                    <span className="text-[15px] font-extrabold tabular-nums pr-[26px]"
                      style={{ color: isValid ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                      {fmtNum(total)}%
                    </span>
                  </Td>
                </tr>
              </tbody>
            </TableShell>

            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-t border-[var(--border)]">
              <p className="text-[11.5px] font-bold"
                style={{ color: isValid ? 'var(--text-muted)' : 'var(--accent-red)' }}>
                {isValid
                  ? 'Total is 100% — ready to save.'
                  : `Total must be exactly 100% (currently ${fmtNum(total)}%, ${total > 100 ? 'over' : 'under'} by ${fmtNum(Math.abs(100 - total))}%).`}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" onClick={resetToDefaults} disabled={saving}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                  <RotateCcw size={13} /> Defaults
                </button>
                <button type="button" onClick={resetToSaved} disabled={saving || !isDirty}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                  <RefreshCw size={13} /> Discard changes
                </button>
                <button type="button" onClick={save} disabled={saving || !isValid || !isDirty}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed">
                  {saving ? <RefreshCw size={13} className="animate-spin" /> : <Save size={13} />}
                  {saving ? 'Saving…' : 'Save Weightages'}
                </button>
              </div>
            </div>
          </Section>

          {/* Live worked example against the draft. */}
          <Section
            title="Preview"
            subtitle="A sample person scored with the weightages above"
            icon={Calculator}
            tone="green"
          >
            <TableShell minWidth={720}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th>Parameter</Th>
                  <Th align="center">Achievement %</Th>
                  <Th align="center">Weightage</Th>
                  <Th align="right">Weighted Score</Th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.code} className="border-b border-[var(--border)] last:border-0">
                    <Td className="font-bold">{r.name}</Td>
                    <Td align="center" className="tabular-nums">{fmtNum(r.achievement)}%</Td>
                    <Td align="center" className="tabular-nums text-[var(--text-muted)]">{fmtNum(r.weightage)}%</Td>
                    <Td align="right">
                      <span className="text-[11px] font-mono text-[var(--text-muted)] mr-2">
                        ({fmtNum(r.achievement)} × {fmtNum(r.weightage)}) ÷ 100 =
                      </span>
                      <span className="text-[13px] font-extrabold tabular-nums">{fmtNum(r.weighted)}</span>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-t border-[var(--border)]">
              <span className="inline-flex items-center gap-2 text-[12px] font-bold text-[var(--text-muted)]">
                <Gauge size={14} /> Final IRM ={' '}
                <span className="font-mono tabular-nums">
                  {preview.rows.map((r) => fmtNum(r.weighted)).join(' + ')}
                </span>
              </span>
              <span className="text-[18px] font-extrabold tabular-nums"
                style={{ color: scoreColor(preview.final) }}>
                {fmtNum(preview.final)}%
              </span>
            </div>
          </Section>
        </>
      )}
    </div>
  );
};

export default IRMSetup;
