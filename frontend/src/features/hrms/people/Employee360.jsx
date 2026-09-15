import React, { useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, LayoutGrid } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import { getEmployee360 } from '../../../services/hrmsApi';
import { CARD, SECTION_TITLE, day, attLeaveToneFor } from '../internal/internalKit';
import { Chip, Facts } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Employee 360° (BA/Functional Design §6).
 *
 * A pure read-only aggregation, section by section, over every module that already tracks
 * this employee — no new source of truth here. A section key MISSING from the API response
 * means the caller is not authorised to see it there (the same "restricted" promise
 * §17/§22.5 make for discipline/PIP) — this page renders those sections not at all, never as
 * an empty placeholder, so the two cases stay visibly different from "authorised, but there
 * is genuinely nothing to show yet" (an empty array, shown as "No records").
 */

const Section = ({ title, children }) => (
  <section className={CARD}>
    <p className={`${SECTION_TITLE} mb-3`}>{title}</p>
    {children}
  </section>
);

const Empty = ({ label }) => <p className="text-[12px] text-[var(--text-muted)] py-1">{label}</p>;

const Employee360 = () => {
  const { userId } = useParams();
  const navigate = useNavigate();
  const { scope } = useHrms();
  const [view, setView] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await getEmployee360(userId, scope);
      setView(data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load this employee’s 360° view.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <HrmsLoading label="Loading Employee 360°…" />;
  if (error) return <HrmsError message={error} onRetry={load} />;
  if (!view) return null;

  const p = view.profile;

  return (
    <div className="space-y-6">
      <HrmsPageHeader
        icon={LayoutGrid}
        title={`${p.name} · 360°`}
        subtitle={[p.designation, p.department].filter(Boolean).join(' · ') || p.email}
        actions={(
          <button type="button" onClick={() => navigate(`/hrms/employees/${userId}`)}
            className="h-9 px-3.5 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-muted)] flex items-center gap-1.5">
            <ArrowLeft size={14} /> Profile
          </button>
        )}
      />

      <Section title="Profile">
        <Facts items={[
          { label: 'Employee Code', value: p.employee_code },
          { label: 'Status', value: p.employment_status },
          { label: 'Joined', value: day(p.joined_on) },
          { label: 'Reporting Manager', value: p.reporting_manager?.name },
        ]} />
      </Section>

      {'probation' in view && (
        <Section title="Probation">
          {view.probation ? (
            <Facts items={[
              { label: 'Started', value: day(view.probation.started_on) },
              { label: 'Ends', value: day(view.probation.ends_on) },
              { label: 'Outcome', value: view.probation.outcome },
              { label: 'Rating', value: view.probation.rating },
            ]} />
          ) : <Empty label="No probation record." />}
        </Section>
      )}

      {'recent_attendance' in view && (
        <Section title="Attendance (last 30 days)">
          {view.late_coming && (
            <p className="text-[12px] text-[var(--text-muted)] mb-2">
              {view.late_coming.total_late_days} late day(s) on record.
            </p>
          )}
          {view.recent_attendance.length ? (
            <div className="flex flex-wrap gap-1.5">
              {view.recent_attendance.map((r) => (
                <Chip key={r.work_date} tone={attLeaveToneFor(r.status)}>
                  {day(r.work_date)} · {r.status}
                </Chip>
              ))}
            </div>
          ) : <Empty label="No attendance captured yet." />}
        </Section>
      )}

      {'leave_balances' in view && (
        <Section title="Leave Balances">
          {view.leave_balances.length ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {view.leave_balances.map((b) => (
                <div key={b.leave_type} className="rounded-xl border border-[var(--border)] p-3">
                  <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
                    {b.leave_type}
                  </p>
                  <p className="text-[18px] font-bold text-[var(--text-main)]">{b.closing}</p>
                </div>
              ))}
            </div>
          ) : <Empty label="No leave types configured yet." />}
          {view.recent_leaves?.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {view.recent_leaves.map((l) => (
                <Chip key={l.leave_no} tone={attLeaveToneFor(l.status)}>
                  {l.leave_type} · {day(l.start_date)} · {l.status}
                </Chip>
              ))}
            </div>
          )}
        </Section>
      )}

      {'movements' in view && (
        <Section title="Movement History">
          {view.movements.length ? (
            <div className="space-y-2">
              {view.movements.map((m) => (
                <div key={m.move_no} className="flex items-center justify-between text-[12.5px]">
                  <span className="text-[var(--text-main)]">
                    {m.movement_type}: {m.current_value || '—'} → {m.proposed_value}
                  </span>
                  <Chip tone={attLeaveToneFor(m.status)}>{m.status}</Chip>
                </div>
              ))}
            </div>
          ) : <Empty label="No movements recorded." />}
        </Section>
      )}

      {'discipline_summary' in view && (
        <Section title="Discipline">
          <Facts items={[
            { label: 'Total Cases', value: view.discipline_summary?.total_cases ?? 0 },
            { label: 'Open Cases', value: view.discipline_summary?.open_cases ?? 0 },
          ]} />
          <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">
            A permission-controlled summary — Restricted/POSH cases beyond your access are not counted here.
          </p>
        </Section>
      )}

      {'pip_history' in view && (
        <Section title="Performance Improvement Plans">
          {view.pip_history.length ? (
            <div className="space-y-2">
              {view.pip_history.map((plan) => (
                <div key={plan.pip_no} className="flex items-center justify-between text-[12.5px]">
                  <span className="text-[var(--text-main)]">{plan.pip_no}: {plan.gap_statement}</span>
                  <Chip tone={attLeaveToneFor(plan.closure_result || plan.status)}>
                    {plan.closure_result || plan.status}
                  </Chip>
                </div>
              ))}
            </div>
          ) : <Empty label="No PIP on record." />}
        </Section>
      )}

      {'separation_history' in view && (
        <Section title="Separation History">
          {view.separation_history.length ? (
            <div className="space-y-2">
              {view.separation_history.map((s) => (
                <div key={s.sep_no} className="flex items-center justify-between text-[12.5px]">
                  <span className="text-[var(--text-main)]">{s.sep_no}: {s.exit_type}</span>
                  <Chip tone={attLeaveToneFor(s.stage)}>{s.stage}</Chip>
                </div>
              ))}
            </div>
          ) : <Empty label="No separation on record." />}
        </Section>
      )}

      {'orientation' in view && (
        <Section title="Orientation & Training">
          {view.orientation?.items?.length ? (
            <div className="space-y-2">
              {view.orientation.items.map((item) => (
                <div key={item.item_id} className="flex items-center justify-between text-[12.5px]">
                  <span className="text-[var(--text-main)]">
                    {item.topic}{item.mandatory ? ' *' : ''}
                  </span>
                  <Chip tone={attLeaveToneFor(item.status)}>{item.status}</Chip>
                </div>
              ))}
            </div>
          ) : <Empty label="No orientation plan assigned yet." />}
        </Section>
      )}

      {'pulse_surveys' in view && (
        <Section title="Pulse Surveys">
          {view.pulse_surveys.length ? (
            <div className="space-y-2">
              {view.pulse_surveys.map((s) => (
                <div key={`${s.employee_code}:${s.milestone}`} className="flex items-center justify-between text-[12.5px]">
                  <span className="text-[var(--text-main)]">
                    {s.milestone}-day{s.average != null ? ` — average ${s.average.toFixed(1)}` : ''}
                  </span>
                  <Chip tone={attLeaveToneFor(s.status)}>{s.status}</Chip>
                </div>
              ))}
            </div>
          ) : <Empty label="No pulse survey issued yet." />}
        </Section>
      )}

      {'letters' in view && (
        <Section title="Letters">
          {view.letters.length ? (
            <div className="space-y-2">
              {view.letters.map((l) => (
                <div key={l.letter_no} className="flex items-center justify-between text-[12.5px]">
                  <span className="text-[var(--text-main)]">{l.letter_no}: {l.title}</span>
                  <Chip tone={attLeaveToneFor(l.status)}>{l.status}</Chip>
                </div>
              ))}
            </div>
          ) : <Empty label="No correspondence on record." />}
        </Section>
      )}

      {'absconding_history' in view && (
        <Section title="Absconding History">
          {view.absconding_history.length ? (
            <div className="space-y-2">
              {view.absconding_history.map((a) => (
                <div key={a.case_no} className="flex items-center justify-between text-[12.5px]">
                  <span className="text-[var(--text-main)]">{a.case_no}: since {day(a.flagged_date)}</span>
                  <Chip tone={attLeaveToneFor(a.status)}>{a.status}</Chip>
                </div>
              ))}
            </div>
          ) : <Empty label="No absconding cases on record." />}
        </Section>
      )}
    </div>
  );
};

export default Employee360;
