import React from 'react';
import { Bot, X, AlertTriangle } from 'lucide-react';
import useAssistant from '../hooks/useAssistant';
import MessageList from './MessageList';
import ChatInput from './ChatInput';

export default function ChatWindow({ onClose }) {
  const { messages, streaming, activeTool, error, send, cancel } = useAssistant();

  return (
    <div className="flex h-full w-full flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg-card)] px-3.5 py-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--accent-indigo)] text-white">
            <Bot size={15} />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-[var(--text-main)]">Sparsh Assistant</p>
            <p className="text-[10px] text-[var(--text-muted)]">Read-only · your data</p>
          </div>
        </div>
        <button
          onClick={onClose}
          title="Close"
          className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--text-muted)] hover:bg-[var(--bg-main)] hover:text-[var(--text-main)]"
        >
          <X size={16} />
        </button>
      </div>

      {/* Messages */}
      <div className="min-h-0 flex-1 overflow-y-auto no-scrollbar">
        <MessageList messages={messages} streaming={streaming} activeTool={activeTool} />
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-2 border-t border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-xs text-[var(--accent-red)]">
          <AlertTriangle size={14} className="shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Input */}
      <ChatInput onSend={send} onCancel={cancel} streaming={streaming} />
    </div>
  );
}
