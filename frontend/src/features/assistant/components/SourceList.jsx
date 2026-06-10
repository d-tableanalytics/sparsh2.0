import React from 'react';
import { Database } from 'lucide-react';

// Friendly labels for backend collection/source names. Unknown values (e.g.
// knowledge document titles like "OOP_Notes.pdf") are shown as-is.
const SOURCE_LABELS = {
  'staff/learners': 'Your profile',
  LearnerAssessments: 'Your assessments',
  LearnerAsessments: 'Your assessments',
  attendance: 'Attendance',
  learnings: 'Learning modules',
  quarters: 'Courses',
  STAFF_CALENDER: 'Sessions',
  LEARNER_CALENDER: 'Sessions',
  calendar_events: 'Sessions',
  KnowledgeBase: 'Knowledge base',
};

export default function SourceList({ sources = [] }) {
  if (!sources || sources.length === 0) return null;

  // De-duplicate friendly labels while preserving order.
  const seen = new Set();
  const labels = [];
  for (const s of sources) {
    const label = SOURCE_LABELS[s] || s;
    if (!seen.has(label)) {
      seen.add(label);
      labels.push(label);
    }
  }

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1 pl-9">
      <span className="flex items-center gap-1 text-[10px] text-[var(--text-muted)]">
        <Database size={11} /> Based on:
      </span>
      {labels.map((label) => (
        <span
          key={label}
          className="rounded-full border border-[var(--border)] bg-[var(--bg-main)] px-2 py-0.5 text-[10px] text-[var(--text-muted)]"
        >
          {label}
        </span>
      ))}
    </div>
  );
}
