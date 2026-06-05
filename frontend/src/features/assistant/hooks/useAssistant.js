import { useCallback, useRef, useState } from 'react';
import { streamAsk, uploadFile } from '../services/assistantApi';

let _seq = 0;
const nextId = (p) => `${p}-${Date.now()}-${_seq++}`;

export default function useAssistant() {
  const [messages, setMessages] = useState([]);
  const [streaming, setStreaming] = useState(false);
  const [uploading, setUploading] = useState(false);
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
          const sources = [...new Set(attributions.flatMap((a) => a.sources || []))];
          return {
            id: nextId(m.role),
            role: m.role,
            content: m.content || '',
            attributions,
            sources,
          };
        }),
    );
  }, []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  /**
   * send(text, { editMessageId, files })
   * - editMessageId: if set, remove that message and everything after it before sending
   * - files: File[] to upload before sending; extracted text is appended to message
   */
  const send = useCallback(
    async (text, { editMessageId, files = [] } = {}) => {
      const content = (text || '').trim();
      if ((!content && files.length === 0) || streaming) return;

      setError(null);

      // When editing, slice the conversation up to (but not including) the edited message
      if (editMessageId) {
        setMessages((list) => {
          const idx = list.findIndex((m) => m.id === editMessageId);
          return idx >= 0 ? list.slice(0, idx) : list;
        });
      }

      // Upload files and collect extracted text to append to the message
      let finalContent = content;
      if (files.length > 0) {
        setUploading(true);
        const fileContexts = [];
        for (const file of files) {
          try {
            const result = await uploadFile(file);
            fileContexts.push(
              result.text
                ? `[File: ${result.filename}]\n${result.text.slice(0, 2000)}`
                : `[File attached: ${result.filename}]`,
            );
          } catch {
            // If upload endpoint unavailable, just note the filename
            fileContexts.push(`[File attached: ${file.name}]`);
          }
        }
        setUploading(false);
        if (fileContexts.length > 0) {
          finalContent = finalContent
            ? `${finalContent}\n\n${fileContexts.join('\n\n')}`
            : fileContexts.join('\n\n');
        }
      }

      if (!finalContent) return;

      const userId = nextId('u');
      const asstId = nextId('a');

      // Show original user text in the bubble (not the enriched server payload)
      const displayContent =
        content || files.map((f) => `[File: ${f.name}]`).join(', ');

      setMessages((list) => [
        ...list,
        { id: userId, role: 'user', content: displayContent },
        { id: asstId, role: 'assistant', content: '', streaming: true },
      ]);
      setStreaming(true);
      setActiveTool(null);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        await streamAsk({
          message: finalContent,
          conversationId: conversationIdRef.current,
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
          // Mark the message as stopped — renders "Response stopped." indicator
          patch(asstId, { streaming: false, stopped: true });
        } else {
          const msg =
            e.status === 429
              ? `You're sending messages too quickly.${e.retryAfter ? ` Try again in ${Math.ceil(e.retryAfter)}s.` : ' Please slow down.'}`
              : e.status === 403
                ? "The assistant isn't available for your account yet."
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

  return {
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
  };
}
