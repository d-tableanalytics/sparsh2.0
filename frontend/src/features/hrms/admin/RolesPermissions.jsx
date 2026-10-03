import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  KeyRound, Search, RotateCcw, UserPlus, UserX, X, Info, Check, Layers, ListChecks,
  SlidersHorizontal, ChevronDown, ChevronUp,
} from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import HrmsScopeBar from '../common/HrmsScopeBar';
import { HrmsLoading, HrmsError, HrmsEmpty } from '../common/HrmsStates';
import { useNotification } from '../../../context/NotificationContext';
import {
  getEmployees, getHrmsPermissions, saveHrmsPermission, resetHrmsPermission,
} from '../../../services/hrmsApi';
import { Btn } from '../internal/internalKit.jsx';

/**
 * HRMS ▸ Roles & Permissions.
 *
 * Every HRMS action, by MODULE ▸ WORKFLOW STEP ▸ ACTION in the order the process runs,
 * starting with raising a manpower requisition. Modules sit in a horizontal bar; the steps
 * of the chosen module sit under it; each action row sets which roles may do it and which
 * people are always allowed or blocked (a block wins). The list and the defaults come from
 * the server, and the server applies the saved rules at its one permission gate.
 */
const FIELD = 'h-9 px-3 rounded-lg border border-[var(--border)] bg-[var(--input-bg)] text-[13px] text-[var(--text-main)]';

// Short names for the horizontal bar ("Internal hiring — requisition & planning" is a
// heading, not a tab).
const SHORT = {
  'Internal hiring — requisition & planning': 'Requisition & planning',
  'Internal hiring — sourcing & screening': 'Sourcing & screening',
  'Internal hiring — interview & selection': 'Interview & selection',
};
const shortName = (m) => SHORT[m] || m;

const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

/** One role's on/off switch for one action. */
const RoleToggle = ({ on, changed, label, disabled, onClick }) => (
  <button type="button" onClick={onClick} disabled={disabled} aria-pressed={on}
    aria-label={`${label}: ${on ? 'allowed' : 'not allowed'}`}
    title={`${label} — ${on ? 'allowed' : 'not allowed'}${changed ? ' (changed from default)' : ''}`}
    className={`relative mx-auto h-7 w-7 grid place-items-center rounded-lg border transition ${on
      ? 'bg-[var(--accent-indigo)] border-[var(--accent-indigo)] text-white'
      : 'bg-[var(--bg-card)] border-[var(--border)] text-transparent hover:border-[var(--accent-indigo)]'} disabled:opacity-50`}>
    <Check size={14} strokeWidth={3} />
    {changed && <span className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full bg-[var(--accent-orange)] ring-2 ring-[var(--bg-card)]" />}
  </button>
);

const ActionRow = ({ action, roles, people, busy, onSave, onReset }) => {
  const [draftRoles, setDraftRoles] = useState(action.roles);
  const [allow, setAllow] = useState(action.allow_users);
  const [deny, setDeny] = useState(action.deny_users);
  const [adding, setAdding] = useState('');
  const [peopleOpen, setPeopleOpen] = useState(false);
  useEffect(() => {
    setDraftRoles(action.roles); setAllow(action.allow_users); setDeny(action.deny_users);
  }, [action]);

  const ids = (list) => list.map((p) => p.user_id);
  const dirty = !sameSet(draftRoles, action.roles)
    || !sameSet(ids(allow), ids(action.allow_users)) || !sameSet(ids(deny), ids(action.deny_users));
  const toggle = (r) => setDraftRoles((d) => (d.includes(r) ? d.filter((x) => x !== r) : [...d, r]));
  const nameOf = (id) => people.find((p) => p.user_id === id)?.name || id;
  const addPerson = (kind) => {
    if (!adding) return;
    const entry = { user_id: adding, name: nameOf(adding) };
    if (kind === 'allow') { setAllow((a) => [...a.filter((p) => p.user_id !== adding), entry]); setDeny((d) => d.filter((p) => p.user_id !== adding)); }
    else { setDeny((d) => [...d.filter((p) => p.user_id !== adding), entry]); setAllow((a) => a.filter((p) => p.user_id !== adding)); }
    setAdding('');
  };
  const undo = () => { setDraftRoles(action.roles); setAllow(action.allow_users); setDeny(action.deny_users); };

  return (
    <>
      <tr className={`border-t border-[var(--border)] ${dirty ? 'bg-[var(--accent-indigo-bg)]/40' : ''}`}>
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <p className="text-[13px] font-semibold text-[var(--text-main)]">{action.label}</p>
            {action.customised && (
              <span className="rounded-full bg-[var(--accent-indigo-bg)] px-2 py-0.5 text-[9.5px] font-bold uppercase tracking-wider text-[var(--accent-indigo)]"
                title={action.updated_by_name ? `Changed by ${action.updated_by_name}` : undefined}>
                Customised
              </span>
            )}
          </div>
          <p className="text-[10.5px] font-mono text-[var(--text-muted)]">{action.cap}</p>
        </td>
        {roles.map((r) => {
          const on = draftRoles.includes(r.value);
          return (
            <td key={r.value} className="px-1 py-3 text-center">
              <RoleToggle on={on} changed={on !== action.default_roles.includes(r.value)}
                label={r.label} disabled={busy} onClick={() => toggle(r.value)} />
            </td>
          );
        })}
        <td className="px-3 py-3">
          <button type="button" onClick={() => setPeopleOpen((o) => !o)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 h-7 text-[11.5px] font-semibold text-[var(--text-main)] hover:border-[var(--accent-indigo)]">
            {allow.length || deny.length ? (
              <>
                {allow.length > 0 && <span className="text-[var(--accent-green,#16a34a)]">+{allow.length}</span>}
                {deny.length > 0 && <span className="text-[var(--accent-red)]">⛔{deny.length}</span>}
              </>
            ) : <span className="text-[var(--text-muted)]">Add people</span>}
            {peopleOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        </td>
        <td className="px-4 py-3 text-right whitespace-nowrap">
          {dirty ? (
            <div className="flex justify-end gap-1.5">
              <Btn disabled={busy} onClick={undo}>Undo</Btn>
              <Btn tone="primary" disabled={busy}
                onClick={() => onSave(action.cap, { roles: draftRoles, allow_users: ids(allow), deny_users: ids(deny) })}>
                Save
              </Btn>
            </div>
          ) : action.customised ? (
            <Btn disabled={busy} onClick={() => onReset(action)}><RotateCcw size={12} /> Default</Btn>
          ) : <span className="text-[11px] text-[var(--text-muted)]">Default</span>}
        </td>
      </tr>
      {peopleOpen && (
        <tr className={dirty ? 'bg-[var(--accent-indigo-bg)]/40' : ''}>
          <td colSpan={roles.length + 3} className="px-4 pb-3">
            <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--input-bg)] p-3 flex flex-wrap items-center gap-2">
              <select className={`${FIELD} h-8 text-[12px] min-w-[200px]`} value={adding}
                onChange={(e) => setAdding(e.target.value)} aria-label="Pick a person">
                <option value="">Choose a person…</option>
                {people.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}
              </select>
              <Btn disabled={!adding} onClick={() => addPerson('allow')}><UserPlus size={13} /> Always allow</Btn>
              <Btn disabled={!adding} onClick={() => addPerson('deny')}><UserX size={13} /> Block</Btn>
              <span className="basis-full" />
              {!allow.length && !deny.length && (
                <span className="text-[11.5px] text-[var(--text-muted)]">No named people — only the ticked roles apply.</span>
              )}
              {allow.map((p) => (
                <span key={`a${p.user_id}`} className="inline-flex items-center gap-1 rounded-full bg-[var(--accent-green-bg,var(--accent-indigo-bg))] px-2.5 py-1 text-[11px] font-semibold text-[var(--accent-green,#16a34a)]">
                  <UserPlus size={11} /> {p.name}
                  <button type="button" aria-label={`Remove ${p.name}`} onClick={() => setAllow((a) => a.filter((x) => x.user_id !== p.user_id))}><X size={11} /></button>
                </span>
              ))}
              {deny.map((p) => (
                <span key={`d${p.user_id}`} className="inline-flex items-center gap-1 rounded-full bg-[var(--accent-red-bg)] px-2.5 py-1 text-[11px] font-semibold text-[var(--accent-red)]">
                  <UserX size={11} /> {p.name}
                  <button type="button" aria-label={`Unblock ${p.name}`} onClick={() => setDeny((d) => d.filter((x) => x.user_id !== p.user_id))}><X size={11} /></button>
                </span>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
};

const Stat = ({ icon: Icon, label, value, tone }) => (
  <div className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3">
    <span className={`h-9 w-9 grid place-items-center rounded-lg ${tone}`}>{React.createElement(Icon, { size: 17 })}</span>
    <div>
      <p className="text-[18px] font-bold leading-none text-[var(--text-main)]">{value}</p>
      <p className="mt-1 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">{label}</p>
    </div>
  </div>
);

const RolesPermissions = () => {
  const { scope, companyId } = useHrms();
  const { showSuccess, showError } = useNotification();
  const [data, setData] = useState(null);
  const [people, setPeople] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState('');
  const [onlyCustom, setOnlyCustom] = useState(false);
  const [moduleIdx, setModuleIdx] = useState(0);
  const [step, setStep] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);

  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true); setError(null);
    try {
      const [{ data: perms }, emp] = await Promise.all([
        getHrmsPermissions(scope),
        getEmployees({ ...scope, limit: 500 }).catch(() => ({ data: {} })),
      ]);
      setData(perms);
      setPeople((emp.data?.employees || []).filter((e) => e.user_id)
        .map((e) => ({ user_id: e.user_id, name: e.display_name || e.full_name || e.name || e.email })));
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load the permissions.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);
  useEffect(() => { load(); }, [load]);

  const save = async (cap, body) => {
    setBusy(true);
    try {
      const { data: next } = await saveHrmsPermission(cap, body, scope);
      setData(next);
      showSuccess('Saved — it takes effect within a few seconds.');
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not save.');
    } finally { setBusy(false); }
  };
  const reset = async (action) => {
    if (!window.confirm(`Put "${action.label}" back to its default?`)) return;
    setBusy(true);
    try {
      const { data: next } = await resetHrmsPermission(action.cap, scope);
      setData(next);
      showSuccess(`"${action.label}" is back to its default.`);
    } catch (err) {
      showError(err?.response?.data?.detail || 'Could not reset.');
    } finally { setBusy(false); }
  };

  const allModules = useMemo(() => data?.modules || [], [data]);
  const q = search.trim().toLowerCase();
  const searching = Boolean(q) || onlyCustom;
  const countOf = (m, pred = () => true) => m.steps.reduce((n, s) => n + s.actions.filter(pred).length, 0);
  const totals = useMemo(() => ({
    modules: allModules.length,
    actions: allModules.reduce((n, m) => n + countOf(m), 0),
    customised: data?.customised ?? 0,
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [data]);

  // What the page shows: the chosen module (one step, or all), or -- while searching or
  // filtering -- matches from every module, grouped under their module and step.
  const shown = useMemo(() => {
    const filterActions = (m, s) => s.actions.filter((a) => (!onlyCustom || a.customised)
      && (!q || `${m.module} ${s.step} ${a.label} ${a.cap}`.toLowerCase().includes(q)));
    const source = searching ? allModules : allModules.slice(moduleIdx, moduleIdx + 1);
    return source.map((m) => ({
      ...m,
      steps: m.steps
        .filter((s) => searching || !step || s.step === step)
        .map((s) => ({ ...s, actions: filterActions(m, s) }))
        .filter((s) => s.actions.length),
    })).filter((m) => m.steps.length);
  }, [allModules, moduleIdx, step, q, onlyCustom, searching]);

  const current = allModules[moduleIdx];

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={KeyRound}
        title="Roles & Permissions"
        subtitle="Choose who may do each HRMS action — by role, plus people who are always allowed or blocked."
      />
      <HrmsScopeBar />

      {loading && <HrmsLoading label="Loading permissions…" />}
      {!loading && error && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && data && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Stat icon={Layers} label="Modules" value={totals.modules}
              tone="bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]" />
            <Stat icon={ListChecks} label="Actions" value={totals.actions}
              tone="bg-[var(--input-bg)] text-[var(--text-main)]" />
            <Stat icon={SlidersHorizontal} label="Customised" value={totals.customised}
              tone="bg-[var(--accent-orange-bg)] text-[var(--accent-orange)]" />
          </div>

          {/* ── Horizontal module bar ── */}
          <div className="sticky top-0 z-10 -mx-1 px-1 pt-1 bg-[var(--bg-main,var(--bg))]">
            <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-1.5">
              <nav aria-label="HRMS modules" className="flex gap-1 overflow-x-auto no-scrollbar">
                {allModules.map((m, i) => {
                  const active = !searching && i === moduleIdx;
                  const custom = countOf(m, (a) => a.customised);
                  return (
                    <button key={m.module} type="button"
                      onClick={() => { setModuleIdx(i); setStep(''); setSearch(''); setOnlyCustom(false); }}
                      aria-current={active ? 'page' : undefined}
                      className={`shrink-0 inline-flex items-center gap-2 rounded-lg px-3.5 h-9 text-[12.5px] font-semibold transition whitespace-nowrap ${active
                        ? 'bg-[var(--accent-indigo)] text-white shadow-sm'
                        : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}`}>
                      {shortName(m.module)}
                      <span className={`rounded-md px-1.5 text-[10.5px] font-bold ${active ? 'bg-white/20' : 'bg-[var(--input-bg)]'}`}>
                        {countOf(m)}
                      </span>
                      {custom > 0 && <span className="h-2 w-2 rounded-full bg-[var(--accent-orange)]" title={`${custom} customised`} />}
                    </button>
                  );
                })}
              </nav>
            </div>
          </div>

          {/* ── Steps of the chosen module + search ── */}
          <div className="flex flex-wrap items-center gap-2">
            {!searching && current && (
              <div className="flex flex-wrap gap-1.5 mr-auto">
                {[{ step: '' }, ...current.steps].map((s) => (
                  <button key={s.step || 'all'} type="button" onClick={() => setStep(s.step)}
                    className={`rounded-full border px-3 h-7 text-[11.5px] font-semibold transition ${step === s.step
                      ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                      : 'border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
                    {s.step || 'All steps'}
                  </button>
                ))}
              </div>
            )}
            {searching && (
              <p className="mr-auto text-[12px] text-[var(--text-muted)]">
                Showing matches from every module. <button type="button" className="font-semibold text-[var(--accent-indigo)]"
                  onClick={() => { setSearch(''); setOnlyCustom(false); }}>Clear</button>
              </p>
            )}
            <div className="relative w-full sm:w-72">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input value={search} onChange={(e) => setSearch(e.target.value)}
                placeholder="Search all actions — e.g. approve" className={`${FIELD} w-full pl-8`} />
            </div>
            <label className="flex items-center gap-2 text-[12px] font-semibold text-[var(--text-main)]">
              <input type="checkbox" checked={onlyCustom} onChange={(e) => setOnlyCustom(e.target.checked)} />
              Only customised
            </label>
            <button type="button" onClick={() => setHelpOpen((o) => !o)}
              className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--accent-indigo)]">
              <Info size={14} /> How it works
            </button>
          </div>

          {helpOpen && (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-4 py-3 text-[12px] text-[var(--text-muted)] grid gap-1.5 sm:grid-cols-2">
              <p><b className="text-[var(--text-main)]">Roles:</b> a filled box means that role may do the action. An orange dot means it differs from the default.</p>
              <p><b className="text-[var(--text-main)]">People:</b> “Always allow” gives one person the action whatever their role; “Block” takes it away — a block always wins.</p>
              <p><b className="text-[var(--text-main)]">Save / Default:</b> save each row when you change it; “Default” puts it back the way it came.</p>
              <p><b className="text-[var(--text-main)]">Always true:</b> the Super Admin has full access; nobody approves their own request; managing these permissions can’t be removed. Changes apply within ~20 seconds.</p>
            </div>
          )}

          {!shown.length && (
            <HrmsEmpty icon={KeyRound} title="Nothing matches" hint="Clear the search or the filter." />
          )}

          {shown.map((m) => (
            <div key={m.module} className="space-y-3">
              {searching && (
                <p className="text-[12px] font-bold uppercase tracking-widest text-[var(--text-muted)]">{m.module}</p>
              )}
              {m.steps.map((s) => (
                <section key={s.step} className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
                  <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-[var(--border)] bg-[var(--input-bg)]">
                    <h3 className="text-[13px] font-bold text-[var(--text-main)]">{s.step}</h3>
                    <span className="text-[11px] text-[var(--text-muted)]">{s.actions.length} action{s.actions.length === 1 ? '' : 's'}</span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[880px]">
                      <thead>
                        <tr className="text-[10.5px] uppercase tracking-wider text-[var(--text-muted)]">
                          <th className="px-4 py-2 text-left font-bold w-[32%]">Action</th>
                          {data.roles.map((r) => <th key={r.value} className="px-1 py-2 font-bold text-center">{r.label}</th>)}
                          <th className="px-3 py-2 text-left font-bold">People</th>
                          <th className="px-4 py-2" />
                        </tr>
                      </thead>
                      <tbody>
                        {s.actions.map((a) => (
                          <ActionRow key={a.cap} action={a} roles={data.roles} people={people}
                            busy={busy} onSave={save} onReset={reset} />
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ))}
            </div>
          ))}
        </>
      )}
    </div>
  );
};

export default RolesPermissions;
