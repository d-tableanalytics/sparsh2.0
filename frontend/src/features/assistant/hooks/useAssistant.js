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

  const conversationIdRef = useRef(null);
  const abortRef = useRef(null);

  const patch = useCallback((id, fields) => {
    setMessages((list) =>
      list.map((m) => (m.id === id ? { ...m, ...(typeof fields === 'function' ? fields(m) : fields) } : m)),
    );
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    conversationIdRef.current = null;
    setMessages([]);
    setError(null);
    setActiveTool(null);
    setStreaming(false);
  }, []);

  // Hydrate from a loaded conversation (Milestone B).
  const loadConversation = useCallback((conversation) => {
    abortRef.current?.abort();
    conversationIdRef.current = conversation.id;
    setError(null);
    setActiveTool(null);
    setStreaming(false);
    setMessages(
      (conversation.messages || [])
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({
          id: nextId(m.role),
          role: m.role,
          content: m.content || '',
          attributions: m.attributions || [],
        })),
    );
  }, []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const send = useCallback(
    async (text) => {
      const content = (text || '').trim();
      if (!content || streaming) return;

      setError(null);
      const userId = nextId('u');
      const asstId = nextId('a');
      setMessages((list) => [
        ...list,
        { id: userId, role: 'user', content },
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
          signal: controller.signal,
          onEvent: (event, data) => {
            if (event === 'meta') {
              if (data.conversation_id) conversationIdRef.current = data.conversation_id;
            } else if (event === 'tool') {
              setActiveTool(data.name || null);
            } else if (event === 'token') {
              patch(asstId, (m) => ({ content: m.content + (data.text || '') }));
            } else if (event === 'done') {
              if (data.conversation_id) conversationIdRef.current = data.conversation_id;
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
    [streaming, patch],
  );

  return {
    messages,
    streaming,
    activeTool,
    error,
    send,
    cancel,
    reset,
    loadConversation,
    conversationId: conversationIdRef,
  };
}
