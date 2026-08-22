import React, { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Gauge, RefreshCw, SlidersHorizontal, Users, Target, TrendingUp,
  AlertTriangle, ChevronDown, Percent, Info, Calculator,
} from 'lucide-react';
import {
  DashboardHero, HeaderSelect, HeroButton, Section, Th, Td, TableShell,
  KpiTile, usePaged, Pager,
} from '../../features/tpms/common/dashboardKit';
import { getIrmScores, recalculateIrm } from '../../services/irmApi';
import {
  canEditWeightages, canRecalculate, currentPeriod, errText, fmtNum, fmtPct, periodLabel,
  periodOptions, scoreColor, scoreTone, useAsync, useIrmCompany,
} from './irmUtils';

/* ─────────────────────────────────────────────────────────────
   IRM ▸ scoreboard.

   One row per person, one column per evaluation parameter. Every cell shows the
   achievement % AND what it contributed after weighting, because the whole point of
   the sheet is that those two numbers are different:

       Weighted Score = (Achievement % × Weightage) ÷ 100

   Expanding a row spells the arithmetic out per parameter. Nothing is computed here —
   the backend returns achievement, weightage, weighted_score and final_irm already
   derived from the company's saved weightages, so this page and the API can never
   disagree about a score.
   ───────────────────────────────────────────────────────────── */

const MotionDiv = motion.div;

/** Achievement % as a bar + value. Muted and dashed when the parameter had no data. */
const AchievementBar = ({ value, hasData }) => {
  if (!hasData) {
    return <span className="text-[11.5px] font-bold text-[var(--text-muted)]">No data</span>;
  }
  const c = scoreColor(value);
  return (
    <div className="flex items-center gap-2 min-w-[104px]">
      <div className="h-1.5 flex-1 rounded-full bg-[var(--input-bg)] overflow-hidden">
        <div className="h-full rounded-full transition-all"
          style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: c }} />
      </div>
      <span className="text-[11.5px] font-bold tabular-nums w-[52px] text-right" style={{ color: c }}>
        {fmtPct(value)}
      </span>
    </div>
  );
};

/** "20 / 25" — what the parameter contributed out of what it could have. */
const WeightedCell = ({ p }) => (
  <span className="text-[11px] font-bold tabular-nums text-[var(--text-muted)]">
    {p.has_data ? fmtNum(p.weighted_score) : '0'}
    <span className="opacity-60"> / {fmtNum(p.max_score)}</span>
  </span>
);

/** The final IRM, out of 100. */
const FinalScore = ({ value, hasData }) => {
  const c = hasData ? scoreColor(value) : 'var(--text-muted)';
  return (
    <span className="inline-flex items-baseline gap-1 justify-end">
      <span className="text-[16px] font-extrabold tabular-nums" style={{ color: c }}>
        {hasData ? fmtNum(value) : '—'}
      </span>
      {hasData && <span className="text-[10px] font-bold text-[var(--text-muted)]">/ 100</span>}
    </span>
  );
};

/** The expanded row — the calculation, parameter by parameter. */
const Breakdown = ({ row, columns }) => (
  <div className="px-4 py-4 bg-[var(--input-bg)]/40 border-t border-[var(--border)]">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {row.parameters.map((p) => (
        <div key={p.code}
          className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-3.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[12px] font-extrabold tracking-tight">{p.name}</span>
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              {fmtNum(p.weightage)}%
            </span>
          </div>

          <dl className="mt-2.5 space-y-1 text-[11.5px]">
            <div className="flex items-center justify-between gap-2">
              <dt className="text-[var(--text-muted)]">
                {p.source === 'form' ? 'Rating points' : 'Achieved / Assigned'}
              </dt>
              <dd className="font-bold tabular-nums">
                {fmtNum(p.achieved, '0')} / {fmtNum(p.assigned, '0')}
                {/* A part-finished checklist earns part of a task, so `achieved` can read
                    3.9 of 5. Spell out the split rather than leaving a puzzling decimal. */}
                {p.source === 'task' && p.partial > 0 && (
                  <span className="text-[10px] font-medium text-[var(--text-muted)]">
                    {' '}({p.completed} done + {p.partial} part-done)
                  </span>
                )}
                {p.source === 'form' && p.ratings > 0 && (
                  <span className="text-[10px] font-medium text-[var(--text-muted)]">
                    {' '}({p.ratings} × {p.scale_max})
                  </span>
                )}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-2">
              <dt className="text-[var(--text-muted)]">Achievement %</dt>
              <dd className="font-bold tabular-nums" style={{ color: scoreColor(p.achievement) }}>
                {fmtPct(p.achievement, 'No data')}
              </dd>
            </div>
          </dl>

          {/* The formula, with this person's numbers substituted in. */}
          <div className="mt-2.5 pt-2.5 border-t border-[var(--border)]">
            <p className="text-[10.5px] font-mono text-[var(--text-muted)] leading-relaxed break-words">
              {p.has_data
                ? `(${fmtNum(p.achievement)} × ${fmtNum(p.weightage)}) ÷ 100`
                : 'no data → contributes 0'}
            </p>
            <p className="text-[13px] font-extrabold tabular-nums mt-1">
              = {fmtNum(p.weighted_score)}
              <span className="text-[10.5px] font-bold text-[var(--text-muted)]"> of {fmtNum(p.max_score)}</span>
            </p>
          </div>
        </div>
      ))}
    </div>

    {/* The sum, written out. */}
    <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3">
      <Calculator size={14} className="text-[var(--accent-indigo)]" />
      <span className="text-[11.5px] font-bold text-[var(--text-muted)]">Final IRM =</span>
      <span className="text-[11.5px] font-mono tabular-nums">
        {row.parameters.map((p) => fmtNum(p.weighted_score)).join(' + ')}
      </span>
      <span className="text-[13px] font-extrabold tabular-nums" style={{ color: scoreColor(row.final_irm) }}>
        = {fmtNum(row.final_irm)}%
      </span>
      {row.applicable_weightage < row.total_weightage && row.has_data && (
        <span className="text-[10.5px] font-bold text-[var(--text-muted)] w-full sm:w-auto">
          · only {fmtNum(row.applicable_weightage)}% of the weightage had data
          {row.final_irm_applicable !== null && (
            <> — {fmtNum(row.final_irm_applicable)}% on what was scored</>
          )}
        </span>
      )}
    </div>

    {/* Column key for the collapsed row, so the header abbreviations stay readable. */}
    <p className="mt-2 text-[10.5px] text-[var(--text-muted)]">
      {columns.map((c) => `${c.name} ${fmtNum(c.weightage)}%`).join(' · ')}
    </p>
  </div>
);

const IRMPage = () => {
  const { user, staff, companies, companyId, setCompanyId } = useIrmCompany();
  const [period, setPeriod] = useState(currentPeriod());
  const [expanded, setExpanded] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  // Editing weightages is Super Admin only; refreshing the snapshot is not an edit.
  const canEdit = canEditWeightages(user);
  const canRefresh = canRecalculate(user);
  const periods = useMemo(() => periodOptions(12), []);
  const waitingForCompany = staff && !companyId;
  // A placeholder entry is how StyledSelect shows "nothing chosen yet" (see SelectField).
  const companyOptions = useMemo(
    () => (companies.length ? companies : [{ id: '', name: 'Loading companies…' }]),
    [companies],
  );

  const load = useCallback(
    async () => (await getIrmScores(companyId, period)).data,
    [companyId, period],
  );
  const { data, loading, error, setError, reload } = useAsync(load, [companyId, period], {
    skip: waitingForCompany,
  });

  const rows = data?.rows || [];
  const columns = data?.parameters || [];
  const paged = usePaged(rows, 12);

  const recalc = async () => {
    setBusy(true);
    setNotice('');
    setError('');
    try {
      const res = await recalculateIrm(companyId, period);
      setNotice(`Snapshot refreshed for ${res.data?.recalculated ?? 0} people.`);
      await reload();
    } catch (e) {
      setError(errText(e, 'Could not recalculate IRM.'));
    } finally {
      setBusy(false);
    }
  };

  const summary = data?.summary || {};
  const kpis = [
    { value: summary.people ?? 0, label: 'People', sub: 'On the roster', tone: 'blue', icon: Users },
    { value: summary.scored ?? 0, label: 'Scored', sub: 'With data this period', tone: summary.scored ? 'green' : 'plain', icon: Target },
    { value: fmtNum(summary.average_irm), label: 'Average IRM', sub: 'Out of 100', tone: scoreTone(summary.average_irm), icon: Gauge },
    { value: fmtNum(summary.highest), label: 'Highest IRM', sub: 'Top performer', tone: scoreTone(summary.highest), icon: TrendingUp },
  ];

  return (
    <div className="space-y-5">
      <DashboardHero
        icon={Gauge}
        title="Individual Result Matrix (IRM)"
        subtitle={`Weighted performance score per person · ${periodLabel(period)}`}
      >
        {staff && (
          <HeaderSelect value={companyId} onChange={setCompanyId} options={companyOptions} />
        )}
        <HeaderSelect value={period} onChange={setPeriod} options={periods} />
        {canRefresh && <HeroButton icon={RefreshCw} onClick={recalc}>{busy ? 'Working…' : 'Recalculate'}</HeroButton>}
        <HeroButton icon={RefreshCw} onClick={reload}>Refresh</HeroButton>
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}
      {notice && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)]">
          <Info size={15} /> {notice}
        </div>
      )}

      {/* The weightage column from the sheet, read-only here — editable in Setup. */}
      {columns.length > 0 && (
        <Section
          title="Weightage"
          subtitle={canEdit
            ? "Each parameter's share of the 100-point score"
            : "Each parameter's share of the 100-point score · set by your Sparsh administrator"}
          icon={Percent}
          action={canEdit && (
            <Link to="/irm/setup"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
              <SlidersHorizontal size={13} /> Edit Weightages
            </Link>
          )}
        >
          <div className="flex flex-wrap items-center gap-2.5 px-5 py-4">
            {columns.map((c) => (
              <span key={c.code}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)]">
                <span className="text-[12px] font-bold">{c.name}</span>
                <span className="text-[12px] font-extrabold tabular-nums text-[var(--accent-indigo)]">
                  {fmtNum(c.weightage)}%
                </span>
              </span>
            ))}
            <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border"
              style={{
                background: data?.is_valid_weightage ? 'var(--accent-green-bg)' : 'var(--accent-red-bg)',
                borderColor: data?.is_valid_weightage ? 'var(--accent-green-border)' : 'var(--accent-red-border)',
                color: data?.is_valid_weightage ? 'var(--accent-green)' : 'var(--accent-red)',
              }}>
              <span className="text-[11px] font-bold uppercase tracking-wide">Grand Total</span>
              <span className="text-[12px] font-extrabold tabular-nums">{fmtNum(data?.total_weightage)}%</span>
            </span>
          </div>
          {data && !data.is_valid_weightage && (
            <p className="px-5 pb-4 -mt-1 text-[11.5px] font-bold text-[var(--accent-red)]">
              Weightages total {fmtNum(data.total_weightage)}%, not 100% — scores are not out of 100
              until an administrator corrects this in Setup.
            </p>
          )}
        </Section>
      )}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      <Section
        title="Individual Scores"
        subtitle={waitingForCompany ? 'Select a company' : `${rows.length} ${rows.length === 1 ? 'person' : 'people'} · ${periodLabel(period)}`}
        icon={Users}
      >
        {waitingForCompany ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Select a company to view its IRM.
          </div>
        ) : loading ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Calculating IRM…
          </div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
              <Users size={20} />
            </span>
            <p className="text-[13px] font-bold">No people to score</p>
            <p className="text-[12px] text-[var(--text-muted)]">
              This company has no active members on its roster.
            </p>
          </div>
        ) : (
          <>
            <TableShell minWidth={1080}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th>Person</Th>
                  {columns.map((c) => (
                    <Th key={c.code}>
                      {c.name}
                      <span className="ml-1 opacity-70">({fmtNum(c.weightage)}%)</span>
                    </Th>
                  ))}
                  <Th align="right">Final IRM</Th>
                  <Th align="center"> </Th>
                </tr>
              </thead>
              <tbody>
                {paged.pageRows.map((row) => {
                  const open = expanded === row.person_id;
                  return (
                    <React.Fragment key={row.person_id}>
                      <tr
                        className="border-b border-[var(--border)] hover:bg-[var(--table-hover)] transition-colors cursor-pointer"
                        onClick={() => setExpanded(open ? null : row.person_id)}
                      >
                        <Td>
                          <span className="font-bold">{row.name}</span>
                          {(row.designation || row.department) && (
                            <span className="block text-[10.5px] text-[var(--text-muted)]">
                              {[row.designation, row.department].filter(Boolean).join(' · ')}
                            </span>
                          )}
                        </Td>
                        {columns.map((c) => {
                          const p = row.parameters.find((x) => x.code === c.code) || {};
                          return (
                            <Td key={c.code}>
                              <AchievementBar value={p.achievement} hasData={p.has_data} />
                              <span className="block mt-1"><WeightedCell p={p} /></span>
                            </Td>
                          );
                        })}
                        <Td align="right">
                          <FinalScore value={row.final_irm} hasData={row.has_data} />
                        </Td>
                        <Td align="center">
                          <ChevronDown size={15}
                            className={`inline text-[var(--text-muted)] transition-transform ${open ? 'rotate-180' : ''}`} />
                        </Td>
                      </tr>
                      <AnimatePresence initial={false}>
                        {open && (
                          <tr>
                            <td colSpan={columns.length + 3} className="p-0">
                              <MotionDiv
                                initial={{ height: 0, opacity: 0 }}
                                animate={{ height: 'auto', opacity: 1 }}
                                exit={{ height: 0, opacity: 0 }}
                                className="overflow-hidden"
                              >
                                <Breakdown row={row} columns={columns} />
                              </MotionDiv>
                            </td>
                          </tr>
                        )}
                      </AnimatePresence>
                    </React.Fragment>
                  );
                })}
              </tbody>
            </TableShell>
            <Pager {...paged} label="people" />
          </>
        )}
      </Section>
    </div>
  );
};

export default IRMPage;
