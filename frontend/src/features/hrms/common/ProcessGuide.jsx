import React, { useState } from 'react';
import { ArrowRight, CheckCircle2, ChevronDown, ChevronUp, Clock, Lightbulb } from 'lucide-react';

/**
 * HRMS ▸ plain-language process guidance.
 *
 * Two pieces, written for somebody who has never seen an HR system before:
 *
 *   <ProcessGuide>  "How this works" — the whole process as numbered steps, with the step a
 *                   record is on highlighted. Collapsible, and remembers being collapsed per
 *                   page, so it helps a newcomer without nagging a regular.
 *   <NextStep>      one line under a record: what happens next, and whether that is
 *                   something YOU do (action), something you are waiting on (waiting), or
 *                   nothing because it is finished (done).
 *
 * The words themselves live in processGuides.js, next to the rules that pick them.
 */

const storageKey = (id) => `hrms.guide.${id}.hidden`;

const readHidden = (id) => {
  try { return window.localStorage.getItem(storageKey(id)) === '1'; } catch { return false; }
};

const writeHidden = (id, hidden) => {
  try { window.localStorage.setItem(storageKey(id), hidden ? '1' : '0'); } catch { /* private mode */ }
};

export const ProcessGuide = ({ guide, current = null }) => {
  const [hidden, setHidden] = useState(() => readHidden(guide.id));
  const toggle = () => { setHidden((h) => { writeHidden(guide.id, !h); return !h; }); };

  if (hidden) {
    return (
      <button type="button" onClick={toggle}
        className="inline-flex items-center gap-1.5 text-[12px] font-bold text-[var(--accent-indigo)] hover:underline">
        <Lightbulb size={14} /> {guide.title} <ChevronDown size={14} />
      </button>
    );
  }

  return (
    <section className="rounded-xl border border-[var(--accent-indigo)]/25 bg-[var(--accent-indigo-bg)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2.5 min-w-0">
          <Lightbulb size={17} className="text-[var(--accent-indigo)] shrink-0 mt-0.5" />
          <div className="min-w-0">
            <h2 className="text-[13.5px] font-bold text-[var(--text-main)]">{guide.title}</h2>
            {guide.intro && (
              <p className="text-[12px] text-[var(--text-muted)] mt-0.5">{guide.intro}</p>
            )}
          </div>
        </div>
        <button type="button" onClick={toggle}
          className="shrink-0 inline-flex items-center gap-1 text-[11.5px] font-bold text-[var(--text-muted)] hover:text-[var(--text-main)]">
          Hide <ChevronUp size={14} />
        </button>
      </div>

      <ol className="mt-3.5 grid gap-2 sm:grid-cols-2 xl:grid-cols-[repeat(auto-fit,minmax(170px,1fr))]">
        {guide.steps.map((s, i) => {
          const isHere = current === i;
          const isDone = current != null && i < current;
          return (
            <li key={s.title}
              className={`rounded-lg border p-2.5 bg-[var(--bg-card)] ${isHere
                ? 'border-[var(--accent-indigo)] ring-2 ring-[var(--accent-indigo)]/20'
                : 'border-[var(--border)]'}`}>
              <div className="flex items-center gap-2">
                <span className={`h-5 w-5 rounded-full text-[10.5px] font-bold flex items-center justify-center shrink-0 ${
                  isDone ? 'bg-[var(--accent-green)] text-white'
                    : isHere ? 'bg-[var(--accent-indigo)] text-white'
                      : 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}>
                  {isDone ? <CheckCircle2 size={12} /> : i + 1}
                </span>
                <span className="text-[12.5px] font-bold text-[var(--text-main)]">{s.title}</span>
                {isHere && (
                  <span className="ml-auto text-[9.5px] font-bold uppercase tracking-wide text-[var(--accent-indigo)]">
                    You are here
                  </span>
                )}
              </div>
              <p className="mt-1 text-[11.5px] leading-snug text-[var(--text-muted)]">{s.text}</p>
            </li>
          );
        })}
      </ol>
    </section>
  );
};

const NEXT_TONE = {
  action:  { Icon: ArrowRight,   cls: 'text-[var(--accent-indigo)]', label: 'Next step', banner: 'What to do now' },
  waiting: { Icon: Clock,        cls: 'text-[var(--accent-orange)]', label: 'Next step', banner: 'What happens next' },
  done:    { Icon: CheckCircle2, cls: 'text-[var(--accent-green)]',  label: 'Done',      banner: 'All done' },
};

/** One line saying what happens next. `step` is { tone, text } from processGuides.js. */
export const NextStep = ({ step, className = '' }) => {
  if (!step?.text) return null;
  const t = NEXT_TONE[step.tone] || NEXT_TONE.action;
  return (
    <p className={`flex items-start gap-1.5 text-[11.5px] leading-snug ${className}`}>
      <t.Icon size={13} className={`${t.cls} shrink-0 mt-px`} />
      <span>
        <span className={`font-bold ${t.cls}`}>{t.label}:</span>{' '}
        <span className="text-[var(--text-main)]">{step.text}</span>
      </span>
    </p>
  );
};

/** A highlighted "what to do now" banner for a detail page. */
export const NextStepBanner = ({ step }) => {
  if (!step?.text) return null;
  const t = NEXT_TONE[step.tone] || NEXT_TONE.action;
  const bg = step.tone === 'done' ? 'bg-[var(--accent-green-bg)]'
    : step.tone === 'waiting' ? 'bg-[var(--accent-orange-bg)]' : 'bg-[var(--accent-indigo-bg)]';
  return (
    <div className={`rounded-lg ${bg} px-3.5 py-2.5 flex items-start gap-2`}>
      <t.Icon size={16} className={`${t.cls} shrink-0 mt-0.5`} />
      <p className="text-[12.5px]">
        <span className={`font-bold ${t.cls}`}>{t.banner}:</span>{' '}
        <span className="text-[var(--text-main)]">{step.text}</span>
      </p>
    </div>
  );
};

export default ProcessGuide;
