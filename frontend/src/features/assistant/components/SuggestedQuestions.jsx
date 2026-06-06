import React from 'react';

const SUGGESTIONS = [
  'How am I performing overall?',
  'What should I study today?',
  'What sessions do I have coming up?',
  'How did I do on my last quiz?',
  'What is polymorphism?',
];

export default function SuggestedQuestions({ onPick, disabled }) {
  return (
    <div className="mt-4 flex w-full flex-col gap-1.5">
      {SUGGESTIONS.map((q) => (
        <button
          key={q}
          type="button"
          disabled={disabled}
          onClick={() => onPick(q)}
          className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-left text-xs text-[var(--text-main)] transition hover:border-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] disabled:opacity-50"
        >
          {q}
        </button>
      ))}
    </div>
  );
}
