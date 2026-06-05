import React, { useState } from 'react';
import { Copy, Check, Pencil } from 'lucide-react';

export default function MessageActions({ content, messageId, onEdit, visible }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(content).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div
      className={`flex items-center gap-0.5 transition-opacity duration-150 ${
        visible ? 'opacity-100' : 'opacity-0 pointer-events-none'
      }`}
    >
      <button
        type="button"
        onClick={handleCopy}
        title="Copy message"
        className="flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-medium text-[var(--text-muted)] hover:bg-[var(--bg-main)] hover:text-[var(--text-main)] transition"
      >
        {copied ? <Check size={11} /> : <Copy size={11} />}
        {copied ? 'Copied' : 'Copy'}
      </button>

      {onEdit && (
        <button
          type="button"
          onClick={() => onEdit(messageId, content)}
          title="Edit message"
          className="flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-medium text-[var(--text-muted)] hover:bg-[var(--bg-main)] hover:text-[var(--text-main)] transition"
        >
          <Pencil size={11} />
          Edit
        </button>
      )}
    </div>
  );
}
