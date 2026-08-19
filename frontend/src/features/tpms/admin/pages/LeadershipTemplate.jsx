import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Mail, Save, RefreshCw, RotateCcw, Eye, AlertTriangle, CheckCircle2,
  ShieldAlert, Link2, Code2,
} from 'lucide-react';
import {
  DashboardHero, HeroButton, Section, TableShell, Th, Td,
} from '../../common/dashboardKit';
import {
  getLeadershipTemplate, saveLeadershipTemplate, previewLeadershipTemplate,
} from '../../../../services/leadershipApi';
import { canManagePanel, errText, useAsync } from '../../leadership/leadershipUtils';
import { useAuth } from '../../../../context/AuthContext';

/* ─────────────────────────────────────────────────────────────
   Leadership Score ▸ invitation email template.

   Authored once, sent personalised: `{{leadership_link}}` is replaced at dispatch time
   with each giver's own single-use /lf/<token> URL, so eight givers receive eight
   different links from this one template. Nobody is ever shown or asked for a token.

   The template lives in the shared tpms_mail_templates collection under a key only
   Leadership uses, so editing here cannot reach any other TPMS template.
   ───────────────────────────────────────────────────────────── */

const inputCls =
  'w-full px-3 py-2 rounded-lg bg-[var(--input-bg)] border border-[var(--input-border)] text-[13px] font-medium outline-none focus:border-[var(--accent-indigo)] transition-colors';

const LeadershipTemplate = () => {
  const { user } = useAuth();
  const allowed = canManagePanel(user);

  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState('');
  const [err, setErr] = useState('');
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);

  const load = useCallback(async () => (await getLeadershipTemplate()).data, []);
  const { data, loading, error, reload } = useAsync(load, [], { skip: !allowed });

  useEffect(() => {
    if (!data) return;
    setSubject(data.subject || '');
    setBody(data.body_html || '');
    setSaved('');
    setErr('');
  }, [data]);

  const placeholders = useMemo(() => data?.placeholders || [], [data]);
  const hasLink = /\{\{\s*leadership_link\s*\}\}/.test(body);
  const dirty = data ? (subject !== data.subject || body !== data.body_html) : false;

  const insert = (key) => {
    setBody((b) => `${b}{{${key}}}`);
    setSaved('');
  };

  const save = async () => {
    setSaving(true);
    setErr('');
    setSaved('');
    try {
      const res = await saveLeadershipTemplate({ subject, body_html: body, active: true });
      setSaved(res.data?.has_link_placeholder
        ? 'Template saved. Each giver will receive their own link.'
        : 'Template saved. It has no {{leadership_link}} placeholder, so the link will be '
          + 'appended at the end of every message.');
      await reload();
    } catch (e) {
      setErr(errText(e, 'Could not save the template.'));
    } finally {
      setSaving(false);
    }
  };

  const runPreview = async () => {
    setPreviewing(true);
    setErr('');
    try {
      const res = await previewLeadershipTemplate({ subject, body_html: body });
      setPreview(res.data);
    } catch (e) {
      setErr(errText(e, 'Could not render the preview.'));
    } finally {
      setPreviewing(false);
    }
  };

  const resetToDefault = () => {
    if (!data) return;
    setSubject(data.default_subject || '');
    setBody(data.default_body_html || '');
    setSaved('');
  };

  if (!allowed) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold">HR only</p>
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-sm">
          The feedback invitation is part of the giver flow, so only HR and administrators
          can edit it.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <DashboardHero icon={Mail} title="Leadership Score — Invitation Email"
        subtitle="One template, personalised per giver at dispatch">
        <HeroButton icon={Eye} onClick={runPreview}>{previewing ? 'Rendering…' : 'Preview'}</HeroButton>
        <HeroButton icon={RefreshCw} onClick={reload}>Reload</HeroButton>
      </DashboardHero>

      {(error || err) && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error || err}
        </div>
      )}
      {saved && (
        <div className="flex items-start gap-2 rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)]">
          <CheckCircle2 size={15} className="shrink-0 mt-0.5" /> {saved}
        </div>
      )}

      {loading ? (
        <Section title="Invitation" subtitle="Loading" icon={Mail}>
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Loading template…
          </div>
        </Section>
      ) : (
        <>
          <Section
            title="Message"
            subtitle={data?.is_customised
              ? `Last edited by ${data.updated_by || 'an administrator'}`
              : 'Using the built-in default — not yet customised'}
            icon={Mail}
          >
            <div className="px-5 py-4 space-y-4">
              <label className="flex flex-col gap-1.5">
                <span className="text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]">
                  Subject line
                </span>
                <input type="text" value={subject} onChange={(e) => setSubject(e.target.value)}
                  className={inputCls} placeholder="Leadership Feedback - {{subject_name}}" />
              </label>

              <label className="flex flex-col gap-1.5">
                <span className="text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]">
                  Message body (HTML)
                </span>
                <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={14}
                  spellCheck={false}
                  className={`${inputCls} font-mono text-[12px] leading-relaxed resize-y`} />
              </label>

              {!hasLink && (
                <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3.5 py-2.5 text-[12px] font-bold text-[var(--accent-orange)]">
                  <Link2 size={14} className="shrink-0 mt-0.5" />
                  <span>
                    No <code>{'{{leadership_link}}'}</code> in the body. The message will still
                    work — each giver's link is appended at the end — but put the placeholder
                    where you want the button to appear.
                  </span>
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-t border-[var(--border)]">
              <p className="text-[11.5px] font-bold text-[var(--text-muted)]">
                Sent to every giver on dispatch, with their own link substituted in.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" onClick={resetToDefault} disabled={saving}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[12.5px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                  <RotateCcw size={13} /> Default
                </button>
                <button type="button" onClick={save} disabled={saving || !dirty}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12.5px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed">
                  {saving ? <RefreshCw size={13} className="animate-spin" /> : <Save size={13} />}
                  {saving ? 'Saving…' : 'Save Template'}
                </button>
              </div>
            </div>
          </Section>

          <Section title="Placeholders" subtitle="Click to append to the body" icon={Code2}>
            <TableShell minWidth={620}>
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <Th>Placeholder</Th><Th>Becomes</Th><Th align="right">Insert</Th>
                </tr>
              </thead>
              <tbody>
                {placeholders.map((p) => (
                  <tr key={p.key} className="border-b border-[var(--border)] last:border-0">
                    <Td>
                      <code className="text-[11.5px] font-bold text-[var(--accent-indigo)]">
                        {`{{${p.key}}}`}
                      </code>
                      {p.key === 'leadership_link' && (
                        <span className="ml-2 text-[9.5px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded bg-[var(--accent-green-bg)] text-[var(--accent-green)]">
                          unique per giver
                        </span>
                      )}
                    </Td>
                    <Td className="text-[var(--text-muted)]">{p.desc}</Td>
                    <Td align="right">
                      <button type="button" onClick={() => insert(p.key)}
                        className="px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                        Insert
                      </button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>
          </Section>

          {preview && (
            <Section title="Preview" subtitle="Sample values — the link shown is not a real token"
              icon={Eye} tone="green">
              <div className="px-5 py-4 space-y-3">
                <div className="text-[12px]">
                  <span className="font-bold uppercase tracking-wide text-[10px] text-[var(--text-muted)]">
                    Subject
                  </span>
                  <p className="font-bold mt-1">{preview.subject}</p>
                </div>
                <div className="rounded-xl border border-[var(--border)] bg-white p-4 overflow-x-auto">
                  <div dangerouslySetInnerHTML={{ __html: preview.body_html }} />
                </div>
              </div>
            </Section>
          )}
        </>
      )}
    </div>
  );
};

export default LeadershipTemplate;
