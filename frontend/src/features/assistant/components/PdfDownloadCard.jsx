import React from 'react';
import { FileText, Download, Loader2 } from 'lucide-react';

/**
 * Renders the in-chat PDF export state for an assistant message:
 *  - `pending`        → "Generating PDF…" with a spinner
 *  - `pdf={url,name}` → a "Download PDF" button (clicking saves the file)
 *
 * Stateless and self-contained so it can be dropped into any message bubble.
 */
export default function PdfDownloadCard({ pending, pdf }) {
  if (pending) {
    return (
      <div className="mt-2 flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg-main)] px-3 py-2 text-xs text-[var(--text-muted)]">
        <Loader2 size={14} className="animate-spin" />
        <span>Preparing your file…</span>
      </div>
    );
  }

  if (!pdf?.url) return null;

  return (
    <a
      href={pdf.url}
      download={pdf.filename || 'chat-conversation.pdf'}
      className="mt-2 inline-flex items-center gap-2 rounded-xl border border-[var(--accent-indigo-border,var(--border))] bg-[var(--accent-indigo-bg)] px-3 py-2 text-xs font-medium text-[var(--accent-indigo)] transition-opacity hover:opacity-90"
    >
      <FileText size={15} className="shrink-0" />
      <span className="max-w-[180px] truncate">{pdf.filename || 'chat-conversation.pdf'}</span>
      <Download size={14} className="shrink-0" />
    </a>
  );
}
