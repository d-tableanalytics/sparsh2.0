import React, { useCallback, useEffect, useState } from 'react';
import { Wallet, Printer, Clock } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { getPayslip } from '../../../services/hrmsApi';
import { FIELD, LABEL } from '../internal/internalKit';

/**
 * HRMS ▸ the employee payslip (§22.7, SM-HR-031).
 *
 * Reads hrms_payslip_service.get_payslip — every figure is the payroll run's own, this
 * component only lays it out. Printed via the browser (Print / Save as PDF), the same
 * pattern Offer/Appointment letters already use — see hrms_payslip_service.py's docstring
 * for why there is no server-side PDF generation here.
 *
 * `embedded`: true when mounted inside PayrollBoard's "My Payslip" tab (which already has
 * its own page header/scope bar); false when routed on its own.
 *
 * `employeeCode`: set when HR opens a SPECIFIC employee's payslip (e.g. from the Payroll
 * Runs records table) rather than the caller's own — the backend already accepts this for
 * any role but EMPLOYEE (see hrms_payslip_service._resolve_employee_code, which ignores it
 * for a self-service caller and resolves their own code instead regardless).
 *
 * FRD §14: what the document shows is driven by the template the run was LOCKED with
 * (identifiers, bank, LOP days, employer contributions, net pay in words — each a template
 * switch the server has already applied), plus the confirmed payment once the bank paid it.
 * An employee asking for a month that is not released yet gets a 404 saying so.
 */
const money = (n) => (typeof n === 'number' ? `₹${n.toLocaleString('en-IN')}` : '—');

const currentPeriod = () => new Date().toISOString().slice(0, 7);

const Payslip = ({ embedded = false, employeeCode = null, initialPeriod = null }) => {
  const { scope } = useHrms();
  const [period, setPeriod] = useState(initialPeriod || currentPeriod());
  const [slip, setSlip] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    // Wait for the company scope: asking before it is known is a guaranteed 400 that only
    // flashes an error before the real request replaces it.
    if (!scope.company_id) return;
    setLoading(true); setError(null);
    try {
      const { data } = await getPayslip(
        period, employeeCode ? { ...scope, employee_code: employeeCode } : scope);
      setSlip(data);
    } catch (err) {
      setSlip(null);
      setError(err?.response?.data?.detail || 'No payslip is available for this period.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period, scope.company_id, employeeCode]);

  useEffect(() => { load(); }, [load]);

  const body = (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3 print:hidden">
        <div>
          <label className={LABEL} htmlFor="payslip-period">Period</label>
          <input id="payslip-period" type="month" value={period} className={`${FIELD} max-w-[200px]`}
            onChange={(e) => setPeriod(e.target.value)} />
        </div>
        {slip && (
          <button type="button" onClick={() => window.print()}
            className="h-9 px-3.5 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold flex items-center gap-1.5">
            <Printer size={14} /> Print / Save as PDF
          </button>
        )}
      </div>

      {loading && <HrmsLoading label="Loading payslip…" />}
      {!loading && error && (/not released/i.test(error) ? (
        // FRD §14 Release: the month exists but is not final (or, by company policy, not
        // paid) yet. Not an error — say when it will appear.
        <HrmsEmpty icon={Clock} title={`Your ${period} payslip is not out yet`}
          hint={`${error} You will see it here as soon as it is released.`} />
      ) : (
        <HrmsEmpty icon={Wallet} title="No payslip for this period" hint={error} />
      ))}
      {!loading && !error && slip && <PayslipDocument slip={slip} />}
    </div>
  );

  if (embedded) return body;

  return (
    <div className="space-y-6">
      <HrmsPageHeader icon={Wallet} title="My Payslip"
        subtitle="Your itemised earnings and deductions for a payroll period." />
      {body}
    </div>
  );
};

// Locked onwards the figures are final; before that HR is still looking at a draft.
const FINAL = ['Locked', 'Paid', 'Closed'];

const Row = ({ r }) => (
  <div className="py-1">
    <div className="flex justify-between gap-3 text-[12.5px]">
      <span>
        {r.label}
        {r.full_amount != null && (
          <span className="text-slate-400 text-[11px]"> (of {money(r.full_amount)})</span>
        )}
      </span>
      <span className="shrink-0">{money(r.amount)}</span>
    </div>
    {r.note && <p className="text-[10.5px] text-slate-400">{r.note}</p>}
  </div>
);

const niceDate = (iso) => {
  if (!iso) return null;
  const d = new Date(`${String(iso).slice(0, 10)}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso
    : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
};

export const PayslipDocument = ({ slip }) => {
  const t = slip.template || {};
  const ids = slip.identifiers || {};
  const earnings = [...(slip.earnings || []), ...(slip.other_earnings || [])];
  const deductions = slip.deductions || [];
  const employer = slip.employer_contributions || [];
  const paid = slip.payment?.status === 'Processed' ? slip.payment : null;
  const facts = [
    ['Employee', `${slip.employee_name} (${slip.employee_code})`],
    ['Designation', slip.designation || '—'],
    ['Department', slip.department || '—'],
    ['Date of joining', niceDate(slip.date_of_joining)],
    ['Payable days', `${slip.payable_days} / ${slip.days_in_period}`],
    ['Present days', slip.present_days],
    ...(t.show_lop_days !== false ? [['LOP days', slip.lop_days]] : []),
    ['PAN', ids.pan], ['UAN', ids.uan], ['PF number', ids.pf_number], ['ESI number', ids.esi_number],
    ['Work location', ids.work_location], ['Grade', ids.grade],
    ['Bank', [ids.bank_name, ids.bank_account].filter(Boolean).join(' · ')],
  ].filter(([, v]) => v != null && v !== '');

  return (
    <div className="bg-white text-slate-900 mx-auto rounded-xl overflow-hidden border border-slate-200"
      style={{ maxWidth: 720, printColorAdjust: 'exact', WebkitPrintColorAdjust: 'exact' }}>
      <div className="p-5 sm:p-8" style={{ fontFamily: 'Georgia, "Times New Roman", serif' }}>
        <div style={{ height: 4, background: '#0f172a', marginBottom: 20 }} />
        <div className="flex items-start justify-between gap-3 mb-6">
          <div className="min-w-0">
            <p className="text-[17px] font-bold">{t.company_name || 'Sparsh Magic LLP'}</p>
            {t.company_address && (
              <p className="text-[11px] text-slate-500 whitespace-pre-line">{t.company_address}</p>
            )}
            <p className="text-[11.5px] text-slate-500 mt-0.5">Payslip for {slip.period}</p>
            {t.header_note && (
              <p className="text-[11px] text-slate-500 mt-1">{t.header_note}</p>
            )}
          </div>
          {slip.run_status && (
            <span className="shrink-0 text-[10.5px] font-bold uppercase tracking-wide px-2 py-1 rounded"
              style={{ background: FINAL.includes(slip.run_status) ? '#dcfce7' : '#fef3c7',
                       color: FINAL.includes(slip.run_status) ? '#166534' : '#92400e' }}>
              {FINAL.includes(slip.run_status) ? 'Final' : 'Provisional'}
            </span>
          )}
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-[12.5px] mb-6 pb-6 border-b border-slate-200">
          {facts.map(([label, value]) => (
            <div key={label} className="min-w-0">
              <span className="text-slate-500">{label}</span><br />
              <span className="font-semibold break-words">{value}</span>
            </div>
          ))}
        </div>
        {slip.proration_note && (
          <p className="text-[11px] text-amber-700 mb-4 -mt-3">{slip.proration_note}</p>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 sm:gap-8">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500 mb-2">Earnings</p>
            {earnings.map((r, i) => <Row key={`${r.label}-${i}`} r={r} />)}
            {!earnings.length && (
              <p className="text-[12px] text-slate-400">No earnings on file.</p>
            )}
            <div className="flex justify-between text-[12.5px] font-bold pt-2 mt-2 border-t border-slate-200">
              <span>Gross Earnings</span><span>{money(slip.gross_earnings)}</span>
            </div>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500 mb-2">Deductions</p>
            {deductions.map((r, i) => <Row key={`${r.label}-${i}`} r={r} />)}
            {!deductions.length && (
              <p className="text-[12px] text-slate-400">No deductions on file.</p>
            )}
            <div className="flex justify-between text-[12.5px] font-bold pt-2 mt-2 border-t border-slate-200">
              <span>Total Deductions</span><span>{money(slip.total_deductions)}</span>
            </div>
          </div>
        </div>

        <div className="mt-6 pt-4 border-t-2 border-slate-800">
          <div className="flex justify-between items-center gap-3">
            <span className="text-[14px] font-bold">Net Pay</span>
            <span className="text-[18px] font-bold">{money(slip.net_pay)}</span>
          </div>
          {slip.net_pay_words && (
            <p className="mt-1 text-[11.5px] text-slate-600 text-right">{slip.net_pay_words}</p>
          )}
          {paid && (
            <p className="mt-1 text-[11.5px] text-emerald-700 text-right">
              Paid on {niceDate(paid.payment_date)} · UTR {paid.utr}
              {paid.payment_mode && ` · ${paid.payment_mode}`}
              {paid.bank_account && ` · ${paid.bank_account}`}
            </p>
          )}
        </div>

        {employer.length > 0 && (
          <div className="mt-6">
            <p className="text-[11px] font-bold uppercase tracking-wide text-slate-500 mb-2">
              Employer contributions <span className="normal-case font-normal">(paid by the company, not part of net pay)</span>
            </p>
            {employer.map((r, i) => <Row key={`${r.label}-${i}`} r={r} />)}
            {slip.total_employer_contributions != null && (
              <div className="flex justify-between text-[12.5px] font-bold pt-2 mt-2 border-t border-slate-200">
                <span>Total</span><span>{money(slip.total_employer_contributions)}</span>
              </div>
            )}
          </div>
        )}

        <div className="mt-8 flex items-end justify-between gap-4">
          <p className="text-[10.5px] text-slate-400">
            {t.footer_note || 'This is a system-generated payslip.'}
          </p>
          {t.version != null && t.version > 0 && (
            <p className="text-[9.5px] text-slate-300 shrink-0">Template v{t.version}</p>
          )}
        </div>
      </div>
    </div>
  );
};

export default Payslip;
