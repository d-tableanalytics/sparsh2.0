import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, User, AlertCircle } from 'lucide-react';
import SourceList from './SourceList';

/**
 * A single chat message. Assistant content is rendered as markdown; user content
 * is plain text. Assistant messages show source-attribution chips when present.
 */
export default function MessageBubble({ message }) {
  const isUser = message.role === 'user';

  return (
    <div className="flex flex-col">
      <div className={`flex gap-2.5 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
        <div
          className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
            isUser ? 'bg-[var(--accent-indigo)] text-white' : 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
          }`}
        >
          {isUser ? <User size={15} /> : <Bot size={15} />}
        </div>

        <div
          className={`max-w-[82%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
            isUser
              ? 'bg-[var(--accent-indigo)] text-white'
              : message.errored
                ? 'bg-[var(--accent-red-bg)] text-[var(--text-main)] border border-[var(--accent-red-border)]'
                : 'bg-[var(--bg-main)] text-[var(--text-main)] border border-[var(--border)]'
          }`}
        >
          {isUser ? (
            <span className="whitespace-pre-wrap break-words">{message.content}</span>
          ) : message.errored && !message.content ? (
            <span className="flex items-center gap-1.5 text-[var(--accent-red)]">
              <AlertCircle size={14} /> Couldn’t complete that. Please try again.
            </span>
          ) : (
            <div className="prose prose-sm max-w-none break-words dark:prose-invert prose-p:my-1.5 prose-headings:my-2 prose-ul:my-1.5 prose-li:my-0.5">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content || ''}</ReactMarkdown>
            </div>
          )}
        </div>
      </div>

      {!isUser && !message.streaming && <SourceList sources={message.sources} />}
    </div>
  );
}
