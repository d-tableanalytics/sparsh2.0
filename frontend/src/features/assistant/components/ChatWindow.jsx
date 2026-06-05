import React, { useEffect, useRef, useState } from 'react';
import { Bot, X, AlertTriangle, PanelLeft, Plus, Square } from 'lucide-react';
import useAssistant from '../hooks/useAssistant';
import useConversation from '../hooks/useConversation';
import MessageList from './MessageList';
import ChatInput from './ChatInput';
import ConversationSidebar from './ConversationSidebar';

export default function ChatWindow({ onClose }) {
  const {
    messages,
    streaming,
    uploading,
    activeTool,
    error,
    send,
    cancel,
    reset,
    loadConversation,
    currentConversationId,
  } = useAssistant();

  const conversations = useConversation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [editTarget, setEditTarget] = useState(null); // { id, content }
  const prevStreaming = useRef(false);

  useEffect(() => {
    conversations.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (prevStreaming.current && !streaming) {
      conversations.refresh();
    }
    prevStreaming.current = streaming;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streaming]);

  const openSidebar = () => {
    conversations.refresh();
    setSidebarOpen(true);
  };

  const handleSelect = async (id) => {
    setSidebarOpen(false);
    try {
      const convo = await conversations.load(id);
      loadConversation(convo);
    } catch {
      /* surfaced by the hook; keep current view */
    }
  };

  const handleNew = () => {
    setSidebarOpen(false);
    reset();
  };

  const handleDelete = async (id) => {
    await conversations.remove(id);
    if (id === currentConversationId) reset();
  };

  // Called from MessageBubble when user clicks Edit on their message
  const handleEditMessage = (messageId, content) => {
    setEditTarget({ id: messageId, content });
  };

  const handleEditConsumed = () => setEditTarget(null);

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-2xl">

      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg-card)] px-2.5 py-2.5">
        <div className="flex items-center gap-1.5">
          <button
            onClick={openSidebar}
            title="Conversations"
            className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--text-muted)] hover:bg-[var(--bg-main)] hover:text-[var(--text-main)]"
          >
            <PanelLeft size={16} />
          </button>
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--accent-indigo)] text-white">
              <Bot size={15} />
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold text-[var(--text-main)]">Sparsh Assistant</p>
              <p className="text-[10px] text-[var(--text-muted)]">Read-only · your data</p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleNew}
            title="New chat"
            className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--text-muted)] hover:bg-[var(--bg-main)] hover:text-[var(--text-main)]"
          >
            <Plus size={16} />
          </button>
          <button
            onClick={onClose}
            title="Close"
            className="flex h-7 w-7 items-center justify-center rounded-lg text-[var(--text-muted)] hover:bg-[var(--bg-main)] hover:text-[var(--text-main)]"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="min-h-0 flex-1 overflow-y-auto no-scrollbar">
        <MessageList
          messages={messages}
          streaming={streaming}
          activeTool={activeTool}
          onPickSuggestion={send}
          onEditMessage={handleEditMessage}
        />
      </div>

      {/* "Stop generating" pill — visible only while streaming */}
      {streaming && (
        <div className="flex justify-center pb-1 pt-0.5">
          <button
            type="button"
            onClick={cancel}
            className="flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 py-1.5 text-xs font-medium text-[var(--text-muted)] shadow-sm hover:border-red-400 hover:text-red-500 transition"
          >
            <Square size={11} />
            Stop generating
          </button>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-2 border-t border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-xs text-[var(--accent-red)]">
          <AlertTriangle size={14} className="shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Input */}
      <ChatInput
        onSend={send}
        onCancel={cancel}
        streaming={streaming}
        uploading={uploading}
        editTarget={editTarget}
        onEditConsumed={handleEditConsumed}
      />

      {/* Conversation sidebar overlay */}
      {sidebarOpen && (
        <div className="absolute inset-0 z-10 flex">
          <div className="h-full w-[72%] max-w-[260px] border-r border-[var(--border)] shadow-xl">
            <ConversationSidebar
              conversations={conversations.conversations}
              loading={conversations.loading}
              activeId={currentConversationId}
              onSelect={handleSelect}
              onNew={handleNew}
              onDelete={handleDelete}
              onClose={() => setSidebarOpen(false)}
            />
          </div>
          <button
            aria-label="Close conversations"
            onClick={() => setSidebarOpen(false)}
            className="h-full flex-1 bg-black/30"
          />
        </div>
      )}
    </div>
  );
}
