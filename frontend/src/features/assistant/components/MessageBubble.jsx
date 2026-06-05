import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, User, AlertCircle, StopCircle, FileText, Music, Video } from 'lucide-react';
import SourceList from './SourceList';
import MessageActions from './MessageActions';

function fileStyle(type) {
  if (type === 'application/pdf')
    return { bg: 'bg-red-500', icon: <FileText size={16} />, label: 'PDF' };
  if (type.includes('word') || type.includes('document'))
    return { bg: 'bg-blue-500', icon: <FileText size={16} />, label: 'DOC' };
  if (type === 'text/plain')
    return { bg: 'bg-slate-500', icon: <FileText size={16} />, label: 'TXT' };
  if (type.startsWith('audio/'))
    return { bg: 'bg-purple-500', icon: <Music size={16} />, label: 'AUDIO' };
  if (type.startsWith('video/'))
    return { bg: 'bg-orange-500', icon: <Video size={16} />, label: 'VIDEO' };
  return { bg: 'bg-indigo-500', icon: <FileText size={16} />, label: type.split('/')[1]?.toUpperCase() || 'FILE' };
}

function FileCard({ file }) {
  if (file.type.startsWith('image/') && file.previewUrl) {
    return (
      <img
        src={file.previewUrl}
        alt={file.name}
        className="max-w-[200px] max-h-[160px] rounded-xl object-cover border border-[var(--border)]"
      />
    );
  }

  const { bg, icon, label } = fileStyle(file.type);

  return (
    <div className="flex items-center gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 shadow-sm min-w-[140px] max-w-[220px]">
      {/* Icon box */}
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${bg} text-white`}>
        {icon}
      </div>
      {/* Info */}
      <div className="min-w-0">
        <p className="truncate text-xs font-semibold text-[var(--text-main)] leading-snug" title={file.name}>
          {file.name}
        </p>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{label}</p>
      </div>
    </div>
  );
}

export default function MessageBubble({ message, onEdit }) {
  const isUser = message.role === 'user';
  const isSynthetic = Boolean(message.synthetic);
  const [hovered, setHovered] = useState(false);
  const hasFiles = isUser && message.files?.length > 0;
  const hasText = Boolean(message.content);

  return (
    <div
      className="flex flex-col"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className={`flex gap-2.5 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
        {/* Avatar */}
        <div
          className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
            isUser
              ? 'bg-[var(--accent-indigo)] text-white'
              : 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
          }`}
        >
          {isUser ? <User size={15} /> : <Bot size={15} />}
        </div>

        {/* Content column */}
        <div className={`flex flex-col gap-2 max-w-[82%] ${isUser ? 'items-end' : 'items-start'}`}>

          {/* File cards — outside the bubble */}
          {hasFiles && (
            <div className="flex flex-col gap-2 items-end">
              {message.files.map((file, i) => (
                <FileCard key={i} file={file} />
              ))}
            </div>
          )}

          {/* Text bubble — only render if there is text */}
          {(!isUser || hasText) && (
            <div
              className={`rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
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
                  <AlertCircle size={14} /> Couldn't complete that. Please try again.
                </span>
              ) : (
                <>
                  {message.content ? (
                    <div className="prose prose-sm max-w-none break-words dark:prose-invert prose-p:my-1.5 prose-headings:my-2 prose-ul:my-1.5 prose-li:my-0.5">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                    </div>
                  ) : null}

                  {message.stopped && (
                    <div className={`flex items-center gap-1.5 text-xs text-[var(--text-muted)] ${message.content ? 'mt-2 border-t border-[var(--border)] pt-2' : ''}`}>
                      <StopCircle size={12} className="shrink-0" />
                      Response stopped.
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Copy / Edit actions */}
      {isUser && (
        <div className="mt-1 flex justify-end pr-9">
          <MessageActions
            content={message.content}
            messageId={message.id}
            onEdit={onEdit}
            visible={hovered}
          />
        </div>
      )}

      {!isUser && !message.streaming && !isSynthetic && <SourceList sources={message.sources} />}
    </div>
  );
}
