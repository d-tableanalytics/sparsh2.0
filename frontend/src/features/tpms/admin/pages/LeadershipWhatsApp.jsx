import React, { useCallback, useMemo, useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import {
  MessageCircle, RefreshCw, AlertTriangle, CheckCircle2, ShieldAlert,
  Send, Clock, XCircle, Info, FileCheck2, Pencil, Plus,
} from 'lucide-react';
import {
  DashboardHero, HeaderSelect, HeroButton, Section,
} from '../../common/dashboardKit';
import LeadershipTemplateModal from './LeadershipTemplateModal';
import {
  getLeadershipWhatsAppTemplate, submitLeadershipWhatsAppTemplate,
  syncLeadershipWhatsAppTemplate, checkLeadershipWaTemplate, saveLeadershipWaDraft,
} from '../../../../services/leadershipApi';
import {
  canManageTemplate, errText, parseUtc, useAsync, useLeadershipCompany,
} from '../../leadership/leadershipUtils';

/* ─────────────────────────────────────────────────────────────
   Leadership Score ▸ WhatsApp Template.

   Write the invitation here, submit it to Meta, and watch it move to Approved. Nothing can
   be sent until Meta has approved it — Meta renders every business-initiated message from
   its OWN approved copy, so an unapproved name fails per recipient with nothing on screen
   to explain why. Showing the verdict here is what makes that visible before it matters.

   ENTIRELY SEPARATE FROM TPMS. Leadership's templates live in their own collection with
   their own endpoints; a TPMS template change cannot alter a feedback invitation.

   Editing the wording sends it back to Draft on purpose. Meta reviews CONTENT, so a
   template whose text changed locally is no longer the thing that was approved.
   ───────────────────────────────────────────────────────────── */

// DRAFT is ours — written here, never sent to Meta. The other three are Meta's verdict,
// mirrored locally so the page can answer "where is it up to?" without a round trip.
const TPL_TONE = {
  DRAFT:    { c: 'var(--text-muted)',    bg: 'var(--input-bg)',         bd: 'var(--border)',               icon: Clock,      label: 'Draft — not submitted' },
  PENDING:  { c: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)', bd: 'var(--accent-yellow-border)', icon: Send,       label: 'Pending Meta review' },
  APPROVED: { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)',  icon: FileCheck2, label: 'Approved' },
  REJECTED: { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)',    icon: XCircle,    label: 'Rejected' },
};

const StatusPill = ({ value }) => {
  const s = TPL_TONE[value] || TPL_TONE.DRAFT;
  const Icon = s.icon;
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide px-3 py-1.5 rounded-full border whitespace-nowrap"
      style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      <Icon size={12} /> {s.label}
    </span>
  );
};

const stamp = (value) => {
  const d = parseUtc(value);
  return d && d.toLocaleString(undefined,
    { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
};

const LeadershipWhatsApp = () => {
  const { user, staff, companyOptions, companyId, setCompanyId } = useLeadershipCompany();
  // Administrators only — superadmin, admin, client admin. Writing the invitation is an
  // administrative decision, and HR does not need the screen to send links.
  const manage = canManageTemplate(user);

  const [composerOpen, setComposerOpen] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const waiting = staff && !companyId;

  const loadTemplate = useCallback(
    async () => (await getLeadershipWhatsAppTemplate(companyId)).data, [companyId]);
  const { data: template, loading, reload } =
    useAsync(loadTemplate, [companyId], { skip: waiting || !manage });

  const status = template?.status || 'DRAFT';
  // `can_edit` from the server is the authority; the same rule is applied locally so the
  // authoring controls are never rendered and then refused.
  const mayEdit = manage && template?.can_edit !== false;

  // Company scoping is closed over here, so the modal only ever deals in a message.
  const templateApi = useMemo(() => ({
    check: (doc) => checkLeadershipWaTemplate(doc),
    save: (doc) => saveLeadershipWaDraft(companyId, doc),
    submit: () => submitLeadershipWhatsAppTemplate(companyId),
  }), [companyId]);

  const run = async (kind, fn, failure) => {
    setBusy(kind);
    setError('');
    setNotice('');
    try {
      const res = await fn();
      setNotice([res?.data?.message, res?.data?.note].filter(Boolean).join(' '));
      await reload();
    } catch (e) {
      setError(errText(e, failure));
    } finally {
      setBusy('');
    }
  };

  const submit = () => run('submit', () => submitLeadershipWhatsAppTemplate(companyId),
    'Could not submit the template to Meta.');

  const refreshStatus = () => run('sync', () => syncLeadershipWhatsAppTemplate(companyId),
    'Could not check the status with Meta.');

  if (!manage) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold">Administrators only</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <DashboardHero icon={MessageCircle} title="Leadership Score — WhatsApp Template"
        subtitle="Write the invitation, submit it to Meta, and track its approval">
        {staff && <HeaderSelect value={companyId} onChange={setCompanyId} options={companyOptions} />}
        <HeroButton icon={RefreshCw} onClick={refreshStatus}>
          {busy === 'sync' ? 'Checking…' : 'Check Status'}
        </HeroButton>
        {/* The page's primary action, so it sits with the other page-level controls rather
            than at the bottom of a section — writing the message is the first thing anyone
            comes here to do, and the only thing that has to happen before anything else can. */}
        {!waiting && mayEdit && (
          <HeroButton icon={template?.meta_template_name ? Pencil : Plus}
            onClick={() => setComposerOpen(true)}>
            {template?.meta_template_name ? 'Edit Template' : 'Create Template'}
          </HeroButton>
        )}
      </DashboardHero>

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}
      {notice && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)]">
          <CheckCircle2 size={15} /> {notice}
        </div>
      )}

      {waiting ? (
        <Section title="WhatsApp Template" subtitle="Select a company" icon={MessageCircle}>
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Select a company to write its invitation template.
          </div>
        </Section>
      ) : loading ? (
        <Section title="WhatsApp Template" subtitle="Loading" icon={MessageCircle}>
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Loading template…
          </div>
        </Section>
      ) : (
        <>
          {/* ─── Approval status ─── */}
          <Section title="Approval Status" icon={FileCheck2}
            subtitle="Meta reviews every business-initiated template before it can be sent">
            <div className="px-5 py-4 space-y-3.5">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <StatusPill value={status} />
                {/* Both actions need a template to act on. With nothing written the row is
                    empty rather than offering a Check that has nothing to check and a
                    Submit whose only outcome is "save the template first". */}
                {template?.meta_template_name && (
                  <div className="flex items-center gap-2">
                    <button type="button" onClick={refreshStatus} disabled={!!busy}
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                      <RefreshCw size={14} className={busy === 'sync' ? 'animate-spin' : ''} />
                      Check with Meta
                    </button>
                    {template?.can_submit && mayEdit && (
                      <button type="button" onClick={submit} disabled={!!busy}
                        title="Send this template to Meta for review"
                        className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
                        {busy === 'submit' ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
                        {busy === 'submit' ? 'Submitting…' : 'Submit to Meta'}
                      </button>
                    )}
                  </div>
                )}
              </div>

              {/* What each state means for whether invitations can go out at all. */}
              {status === 'DRAFT' && (
                <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
                  Written here but never sent to Meta. <b className="text-[var(--text-main)]">No
                  invitations can go out</b> until it is submitted and approved.
                </p>
              )}
              {status === 'PENDING' && (
                <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-yellow)]">
                  <Clock size={14} className="mt-[1px] shrink-0" />
                  <span>
                    With Meta for review — usually minutes to hours. Nothing polls for the
                    verdict, so press <b>Check with Meta</b> to pick it up. Invitations still
                    cannot be sent while it is pending.
                  </span>
                </div>
              )}
              {status === 'APPROVED' && (
                <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-green)]">
                  <CheckCircle2 size={14} className="mt-[1px] shrink-0" />
                  <span>
                    Approved by Meta. Invitations for this company will be sent with it
                    {template?.active === false && ' — once you switch it on below'}.
                  </span>
                </div>
              )}
              {status === 'REJECTED' && (
                <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-red)]">
                  <XCircle size={14} className="mt-[1px] shrink-0" />
                  <span>
                    Meta rejected it{template?.rejected_reason ? `: ${template.rejected_reason}` : '.'}
                    {' '}Correct the wording below and submit again — the same template is
                    resubmitted, because a rejected name stays taken on your account.
                  </span>
                </div>
              )}

              {template?.last_submit_error && (
                <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-red)]">
                  <AlertTriangle size={14} className="mt-[1px] shrink-0" />
                  <span>Last submission failed: {template.last_submit_error}</span>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[11px] font-semibold text-[var(--text-muted)]">
                {template?.meta_template_id && (
                  <span>Meta id <span className="font-mono">{template.meta_template_id}</span></span>
                )}
                {stamp(template?.submitted_at) && <span>Submitted {stamp(template.submitted_at)}</span>}
                {stamp(template?.synced_at) && <span>Checked {stamp(template.synced_at)}</span>}
              </div>
            </div>
          </Section>

          {/* ─── The template itself ─── */}
          {/* Authored in the SHARED composer (components/whatsapp/TemplateComposer), the
              same modal TPMS and Notifications use: live WhatsApp preview, Meta's own
              validation rules, header/footer/buttons, and a payload you can read before an
              irreversible submit. Rebuilding a lesser version of it here would have meant
              two sets of rules to keep in step with Meta. */}
          <Section title="Message" icon={MessageCircle}
            subtitle={template?.meta_template_name
              ? `${template.meta_template_name} · ${template.language || 'en'}`
              : 'Not written yet'}>
            <div className="px-5 py-4 space-y-3.5">
              {template?.meta_template_name ? (
                <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-3">
                  <span className="block text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)] mb-1.5">
                    What the recipient reads
                  </span>
                  <p className="text-[12.5px] font-medium whitespace-pre-wrap break-words">
                    {template.body || '—'}
                  </p>
                </div>
              ) : (
                <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
                  No template written for this company yet. Everything Meta needs — the
                  wording, header, buttons and category — is set in the composer.
                </p>
              )}

              {/* Fixed, not configurable. Every Leadership invitation says the same three
                  things, so the body is written to this order rather than each company
                  mapping it — a mapping whose only wrong answer looked completely correct. */}
              <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-3">
                <span className="block text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)] mb-2">
                  Write the body using these
                </span>
                <div className="space-y-1.5">
                  {[
                    ['{{1}}', 'the person being asked for feedback'],
                    ['{{2}}', 'their feedback link — generated per invitation'],
                  ].map(([slot, meaning]) => (
                    <div key={slot} className="flex items-center gap-3">
                      <span className="font-mono text-[12px] font-bold text-[var(--accent-indigo)] w-12 shrink-0">
                        {slot}
                      </span>
                      <span className="text-[12px] font-semibold text-[var(--text-muted)]">{meaning}</span>
                    </div>
                  ))}
                </div>
                <p className="text-[11px] font-semibold text-[var(--text-muted)] mt-2.5 leading-relaxed">
                  Never paste a link into the template. Each giver gets a fresh single-use URL
                  minted when the invitation is sent, and {'{{2}}'} is where it lands — a fixed
                  link would send everyone to the same form.
                </p>
              </div>

              <span className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-[var(--text-muted)]">
                <Info size={13} />
                {template?.is_ready
                  ? 'Approved — invitations will send with this.'
                  : 'Invitations cannot be sent until Meta approves this.'}
              </span>
            </div>
          </Section>

        </>
      )}

      <AnimatePresence>
        {composerOpen && (
          <LeadershipTemplateModal
            key={companyId}
            template={template}
            api={templateApi}
            onClose={() => setComposerOpen(false)}
            onSaved={() => { setComposerOpen(false); reload(); }}
          />
        )}
      </AnimatePresence>
    </div>
  );
};

export default LeadershipWhatsApp;
