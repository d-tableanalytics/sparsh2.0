import React, { useMemo, useState } from 'react';
import {
  RefreshCw, Download, ClipboardCheck, Users, Star, Search, LayoutGrid, LineChart as LineIcon, MessageSquare,
} from 'lucide-react';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts';
import { DashboardHero, HeroButton, Section, KpiTile, FilterSelect } from './dashboardKit';

/* ─────────────────────────────────────────────────────────────
   Review Report — review-form responses with a Cards view and a
   Monthly Trend chart. Shared by the Admin panel and SMOPS panel.
   All data is placeholder mock.
   ───────────────────────────────────────────────────────────── */

const FORMS = ['Accountability', 'Culture', 'O&A Rating', 'Success Review'];

const RESPONSES = [
  { form: 'Accountability', month: 'Jul', company: 'Acme Corp',     hod: 'Ananya Rao',   employee: 'Priya S.',  rating: 4.6, date: '2026-07-14', comment: 'Consistently owns delivery and unblocks the team quickly.' },
  { form: 'Accountability', month: 'Jul', company: 'Nimbus Ltd',    hod: 'Rahul Verma',  employee: 'Megha M.',  rating: 3.4, date: '2026-07-13', comment: 'Follow-through on WRMs needs improvement this month.' },
  { form: 'Culture',        month: 'Jul', company: 'Vertex Health', hod: 'Deepak Joshi', employee: 'Sneha I.',  rating: 4.4, date: '2026-07-12', comment: 'Great team culture; recognition rituals are working.' },
  { form: 'O&A Rating',     month: 'Jun', company: 'Acme Corp',     hod: 'Ananya Rao',   employee: 'Rohit S.',  rating: 4.1, date: '2026-06-28', comment: 'Objectives clear; alignment cadence is solid.' },
  { form: 'Success Review', month: 'Jun', company: 'Orbit Media',   hod: 'Neha Gupta',   employee: 'Aashi K.',  rating: 2.9, date: '2026-06-24', comment: 'Several success measures slipped; needs a recovery plan.' },
  { form: 'Culture',        month: 'May', company: 'Nimbus Ltd',    hod: 'Rahul Verma',  employee: 'Karan M.',  rating: 3.8, date: '2026-05-19', comment: 'Improving; more consistency in 1:1s would help.' },
  { form: 'Accountability', month: 'May', company: 'Vertex Health', hod: 'Deepak Joshi', employee: 'Anil P.',   rating: 4.7, date: '2026-05-15', comment: 'Reliable and accurate throughout the quarter.' },
];

const TREND = [
  { m: 'Jan', rating: 3.6 }, { m: 'Feb', rating: 3.8 }, { m: 'Mar', rating: 3.7 },
  { m: 'Apr', rating: 4.0 }, { m: 'May', rating: 3.9 }, { m: 'Jun', rating: 4.1 }, { m: 'Jul', rating: 4.2 },
];

const formColor = { 'Accountability': 'var(--accent-indigo)', 'Culture': 'var(--accent-green)', 'O&A Rating': 'var(--accent-orange)', 'Success Review': 'var(--badge-type-text)' };
const ratingColor = (r) => (r >= 4 ? 'var(--accent-green)' : r >= 3 ? 'var(--accent-orange)' : 'var(--accent-red)');

const Stars = ({ value }) => (
  <span className="inline-flex items-center gap-0.5">
    {[1, 2, 3, 4, 5].map((i) => (
      <Star key={i} size={13} style={{ color: 'var(--accent-yellow)', fill: i <= Math.round(value) ? 'var(--accent-yellow)' : 'transparent' }} className={i <= Math.round(value) ? '' : 'opacity-30'} />
    ))}
  </span>
);

const ChartTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 shadow-lg">
      <p className="text-[11px] font-bold text-[var(--text-muted)] mb-1">{label}</p>
      <p className="text-[12px] font-bold text-[var(--accent-indigo)]">Avg rating: {payload[0].value}</p>
    </div>
  );
};

const ReviewReport = ({ title = 'Review Reports', subtitle = 'Evaluation & feedback responses across teams' }) => {
  const [view, setView] = useState('cards');
  const [form, setForm] = useState('All Forms');
  const [month, setMonth] = useState('All Months');
  const [company, setCompany] = useState('All Companies');
  const [hod, setHod] = useState('All HODs');
  const [q, setQ] = useState('');

  const rows = useMemo(() => RESPONSES.filter((r) =>
    (form === 'All Forms' || r.form === form) &&
    (month === 'All Months' || r.month === month) &&
    (company === 'All Companies' || r.company === company) &&
    (hod === 'All HODs' || r.hod === hod) &&
    (!q.trim() || `${r.hod} ${r.employee} ${r.company} ${r.comment}`.toLowerCase().includes(q.trim().toLowerCase()))
  ), [form, month, company, hod, q]);

  const stats = useMemo(() => {
    const responses = rows.length;
    const hods = new Set(rows.map((r) => r.hod)).size;
    const avg = responses ? (rows.reduce((a, r) => a + r.rating, 0) / responses).toFixed(1) : '—';
    return { responses, hods, avg };
  }, [rows]);

  const kpis = [
    { value: stats.responses, label: 'Responses', sub: 'Submitted',        tone: 'blue',  icon: ClipboardCheck },
    { value: stats.hods,      label: 'HODs',      sub: 'Reviewed',         tone: 'green', icon: Users },
    { value: stats.avg,       label: 'Avg Rating',sub: 'Out of 5',         tone: 'yellow',icon: Star },
  ];

  const uniq = (key) => Array.from(new Set(RESPONSES.map((r) => r[key])));

  return (
    <div className="space-y-5">
      {/* Hero */}
      <DashboardHero icon={ClipboardCheck} title={title} subtitle={subtitle}>
        <div className="flex items-center gap-1 bg-white/20 p-1 rounded-lg">
          {[{ k: 'cards', label: 'Cards', icon: LayoutGrid }, { k: 'trend', label: 'Monthly Trend', icon: LineIcon }].map((v) => (
            <button key={v.k} onClick={() => setView(v.k)}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-bold transition-all ${view === v.k ? 'bg-white text-[var(--accent-indigo)] shadow-sm' : 'text-white/80 hover:text-white'}`}>
              <v.icon size={13} /> {v.label}
            </button>
          ))}
        </div>
        <HeroButton icon={RefreshCw}>Refresh</HeroButton>
        <HeroButton icon={Download}>CSV</HeroButton>
      </DashboardHero>

      {/* KPI tiles */}
      <div className="grid grid-cols-3 gap-3">
        {kpis.map((k) => <KpiTile key={k.label} {...k} />)}
      </div>

      {/* Filter bar */}
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-4">
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3 items-end">
          {[
            { label: 'Form', value: form, set: setForm, opts: ['All Forms', ...FORMS] },
            { label: 'Month', value: month, set: setMonth, opts: ['All Months', ...uniq('month')] },
            { label: 'Company', value: company, set: setCompany, opts: ['All Companies', ...uniq('company')] },
            { label: 'HOD', value: hod, set: setHod, opts: ['All HODs', ...uniq('hod')] },
          ].map((f) => (
            <label key={f.label} className="flex flex-col gap-1">
              <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{f.label}</span>
              <FilterSelect value={f.value} onChange={f.set} options={f.opts} />
            </label>
          ))}
          <label className="flex flex-col gap-1 col-span-2 md:col-span-1">
            <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]">Search</span>
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="HOD, employee, company…"
                className="w-full pl-9 pr-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)]" />
            </div>
          </label>
        </div>
      </div>

      {/* Content */}
      {view === 'trend' ? (
        <Section title="Monthly Rating Trend" subtitle="Average review rating over time" icon={LineIcon}>
          <div className="px-2 py-5 h-[320px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={TREND} margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis dataKey="m" tick={{ fontSize: 11, fontWeight: 700, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                <YAxis domain={[0, 5]} tick={{ fontSize: 11, fontWeight: 700, fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTooltip />} />
                <Line type="monotone" dataKey="rating" stroke="var(--accent-indigo)" strokeWidth={2.5} dot={{ r: 4, fill: 'var(--accent-indigo)' }} activeDot={{ r: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Section>
      ) : rows.length === 0 ? (
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm py-16 text-center">
          <MessageSquare size={26} className="mx-auto text-[var(--text-muted)]" />
          <p className="text-[13px] font-bold mt-3">No responses match these filters.</p>
          <p className="text-[12px] text-[var(--text-muted)] mt-1">Try widening the form, month, company or HOD.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {rows.map((r, i) => (
            <div key={i} className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm p-4 flex flex-col hover:shadow-md transition-all">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2.5 min-w-0">
                  <span className="w-9 h-9 rounded-xl text-white text-[11px] font-bold flex items-center justify-center shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                    {r.hod.split(' ').map((x) => x[0]).join('')}
                  </span>
                  <div className="min-w-0">
                    <p className="text-[13.5px] font-bold truncate">{r.hod}</p>
                    <p className="text-[11px] text-[var(--text-muted)] truncate">{r.company}</p>
                  </div>
                </div>
                <span className="text-[10px] font-bold px-2 py-1 rounded-md shrink-0" style={{ color: formColor[r.form], background: 'var(--input-bg)' }}>{r.form}</span>
              </div>

              <div className="flex items-center gap-2 mt-3">
                <Stars value={r.rating} />
                <span className="text-[13px] font-extrabold tabular-nums" style={{ color: ratingColor(r.rating) }}>{r.rating}</span>
              </div>

              <p className="text-[12.5px] text-[var(--text-main)] mt-3 leading-relaxed flex-1">“{r.comment}”</p>

              <div className="flex items-center justify-between mt-3 pt-3 border-t border-[var(--border)] text-[11px] font-medium text-[var(--text-muted)]">
                <span>By {r.employee}</span>
                <span className="tabular-nums">{r.date}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default ReviewReport;
