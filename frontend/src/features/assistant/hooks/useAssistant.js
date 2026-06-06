import { useCallback, useRef, useState } from 'react';
import { streamAsk } from '../services/assistantApi';

let _seq = 0;
const nextId = (p) => `${p}-${Date.now()}-${_seq++}`;

/**
 * Owns the chat message list and the SSE streaming lifecycle.
 * Message shape: { id, role: 'user'|'assistant', content, streaming?, errored?,
 *                  sources?, attributions?, meta? }
 */
export default function useAssistant() {
  const [messages, setMessages] = useState([]);
  const [streaming, setStreaming] = useState(false);
  const [activeTool, setActiveTool] = useState(null);
  const [error, setError] = useState(null);
  const [currentConversationId, setCurrentConversationId] = useState(null);

  const conversationIdRef = useRef(null);
  const abortRef = useRef(null);

  const rememberConversation = useCallback((id) => {
    if (!id) return;
    conversationIdRef.current = id;
    setCurrentConversationId(id);
  }, []);

  const patch = useCallback((id, fields) => {
    setMessages((list) =>
      list.map((m) => (m.id === id ? { ...m, ...(typeof fields === 'function' ? fields(m) : fields) } : m)),
    );
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    conversationIdRef.current = null;
    setCurrentConversationId(null);
    setMessages([]);
    setError(null);
    setActiveTool(null);
    setStreaming(false);
  }, []);

  // Hydrate from a loaded conversation (Milestone B).
  const loadConversation = useCallback((conversation) => {
    abortRef.current?.abort();
    conversationIdRef.current = conversation.id;
    setCurrentConversationId(conversation.id);
    setError(null);
    setActiveTool(null);
    setStreaming(false);
    setMessages(
      (conversation.messages || [])
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => {
          const attributions = m.attributions || [];
          // Persisted turns store `attributions` (not the live `sources` array),
          // so derive the flat source list for the attribution chips.
          const sources = [...new Set(attributions.flatMap((a) => a.sources || []))];
          return {
            id: nextId(m.role),
            role: m.role,
            content: m.content || '',
            attributions,
            sources,
            attachments: m.attachments || undefined,
          };
        }),
    );
  }, []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const send = useCallback(
    async (text, { editFromIndex, attachments, attachmentIds } = {}) => {
      const content = (text || '').trim();
      const hasAttachments = attachmentIds && attachmentIds.length > 0;
      // Allow an attachment-only message (no text), but otherwise require text.
      if ((!content && !hasAttachments) || streaming) return;

      setError(null);
      const userId = nextId('u');
      const asstId = nextId('a');
      setMessages((list) => [
        ...list,
        { id: userId, role: 'user', content, attachments: attachments || undefined },
        { id: asstId, role: 'assistant', content: '', streaming: true },
      ]);
      setStreaming(true);
      setActiveTool(null);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        await streamAsk({
          message: content,
          conversationId: conversationIdRef.current,
          editFromIndex,
          attachmentIds,
          signal: controller.signal,
          onEvent: (event, data) => {
            if (event === 'meta') {
              rememberConversation(data.conversation_id);
            } else if (event === 'tool') {
              setActiveTool(data.name || null);
            } else if (event === 'token') {
              patch(asstId, (m) => ({ content: m.content + (data.text || '') }));
            } else if (event === 'done') {
              rememberConversation(data.conversation_id);
              setActiveTool(null);
              patch(asstId, {
                streaming: false,
                sources: data.sources || [],
                attributions: data.attributions || [],
                meta: { usage: data.usage, cost: data.cost, latency_ms: data.latency_ms },
              });
            }
          },
        });
      } catch (e) {
        if (e.name === 'AbortError') {
          patch(asstId, { streaming: false });
        } else {
          const msg =
            e.status === 429
              ? `You're sending messages too quickly.${e.retryAfter ? ` Try again in ${Math.ceil(e.retryAfter)}s.` : ' Please slow down.'}`
              : e.status === 403
                ? 'The assistant isn’t available for your account yet.'
                : 'Something went wrong reaching the assistant. Please try again.';
          setError(msg);
          patch(asstId, (m) => ({
            streaming: false,
            errored: true,
            content: m.content || '',
          }));
        }
      } finally {
        setStreaming(false);
        setActiveTool(null);
        abortRef.current = null;
      }
    },
    [streaming, patch, rememberConversation],
  );

  // Edit a previously sent user message: drop it and everything after it, then
  // resend the new text so the assistant answers the revised question.
  const editAndResend = useCallback(
    (id, newText) => {
      const content = (newText || '').trim();
      if (!content || streaming) return;
      // The on-screen list mirrors the stored conversation 1:1, so this index
      // is also the backend message index to truncate from.
      const idx = messages.findIndex((m) => m.id === id);
      if (idx === -1) return;
      setMessages((list) => list.slice(0, idx));
      send(content, { editFromIndex: idx });
    },
    [messages, streaming, send],
  );

  return {
    messages,
    streaming,
    activeTool,
    error,
    send,
    cancel,
    reset,
    editAndResend,
    loadConversation,
    currentConversationId,
  };
}
