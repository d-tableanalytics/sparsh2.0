import React, { useRef, useState } from 'react';
import { Send, Square } from 'lucide-react';

export default function ChatInput({ onSend, onCancel, streaming, disabled }) {
  const [value, setValue] = useState('');
  const textareaRef = useRef(null);

  const submit = () => {
    const text = value.trim();
    if (!text || streaming || disabled) return;
    onSend(text);
    setValue('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const autoGrow = (e) => {
    setValue(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  };

  return (
    <div className="flex items-end gap-2 border-t border-[var(--border)] bg-[var(--bg-card)] p-2.5">
      <textarea
        ref={textareaRef}
        rows={1}
        value={value}
        onChange={autoGrow}
        onKeyDown={onKeyDown}
        disabled={disabled}
        placeholder="Ask about your sessions, scores, progress…"
        className="max-h-[120px] flex-1 resize-none rounded-xl border border-[var(--input-border)] bg-[var(--input-bg)] px-3 py-2 text-sm text-[var(--text-main)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-indigo)] disabled:opacity-60"
      />
      {streaming ? (
        <button
          type="button"
          onClick={onCancel}
          title="Stop"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--bg-main)] text-[var(--text-muted)] hover:text-[var(--text-main)] border border-[var(--border)]"
        >
          <Square size={15} />
        </button>
      ) : (
        <button
          type="button"
          onClick={submit}
          disabled={!value.trim() || disabled}
          title="Send"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-indigo)] text-white transition hover:opacity-90 disabled:opacity-40"
        >
          <Send size={15} />
        </button>
      )}
    </div>
  );
}
