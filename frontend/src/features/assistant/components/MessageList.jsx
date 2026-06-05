import React, { useEffect, useRef } from 'react';
import { Sparkles } from 'lucide-react';
import MessageBubble from './MessageBubble';
import TypingIndicator from './TypingIndicator';

export default function MessageList({ messages, streaming, activeTool }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, activeTool]);

  // Whether the last assistant message is still empty (so show a typing row).
  const last = messages[messages.length - 1];
  const showTyping = streaming && last && last.role === 'assistant' && !last.content;

  if (messages.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
          <Sparkles size={22} />
        </div>
        <p className="text-sm font-medium text-[var(--text-main)]">Ask Sparsh anything</p>
        <p className="text-xs text-[var(--text-muted)]">
          Your sessions, quiz scores, progress, or what to study next.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 px-3 py-3">
      {messages.map((m) => (
        <MessageBubble key={m.id} message={m} />
      ))}
      {showTyping && (
        <div className="pl-9">
          <TypingIndicator activeTool={activeTool} />
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
