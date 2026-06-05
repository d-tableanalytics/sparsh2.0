import { useCallback, useRef, useState } from 'react';
import { streamAsk, uploadFile } from '../services/assistantApi';

let _seq = 0;
const nextId = (p) => `${p}-${Date.now()}-${_seq++}`;

const EXT_MIME = {
  pdf: 'application/pdf',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  txt: 'text/plain',
  mp3: 'audio/mpeg',
  wav: 'audio/wav',
  mp4: 'video/mp4',
  mov: 'video/quicktime',
  webm: 'video/webm',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
};

// Text-based extensions readable directly in the browser (no backend needed)
const TEXT_EXTS = new Set(['txt', 'csv', 'md', 'json', 'xml', 'html', 'js', 'ts', 'py', 'log', 'yaml', 'yml']);

function readFileAsText(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = (e) => resolve((e.target.result || '').trim());
    reader.onerror = () => resolve('');
    reader.readAsText(file);
  });
}

// Parse backend-stored user content back into displayText + file cards
function parseUserContent(raw) {
  const filePattern = /\[File(?:\s+attached)?:\s*([^\]\n]+)\]/g;
  const files = [];
  let match;
  while ((match = filePattern.exec(raw)) !== null) {
    const name = match[1].trim();
    const ext = name.split('.').pop().toLowerCase();
    files.push({ name, type: EXT_MIME[ext] || 'application/octet-stream', size: 0, previewUrl: null });
  }
  const firstFileIdx = raw.search(/\[File(?:\s+attached)?:/);
  const displayText = firstFileIdx >= 0 ? raw.slice(0, firstFileIdx).trim() : raw;
  return { displayText, files: files.length > 0 ? files : undefined };
}

// Extract text from a single file (backend first, client-side fallback for text files)
async function extractFileContext(file) {
  const ext = file.name.split('.').pop().toLowerCase();
  let text = '';
  let filename = file.name;

  try {
    const result = await uploadFile(file);
    filename = result.filename || file.name;
    text = result.text || '';
  } catch {
    // backend unavailable — fall through to client-side read
  }

  if (!text && TEXT_EXTS.has(ext)) {
    text = await readFileAsText(file);
  }

  return {
    context: text
      ? `[File: ${filename}]\n${text.slice(0, 3000)}`
      : `[File attached: ${filename}]`,
    hasText: Boolean(text),
  };
}

export default function useAssistant() {
  const [messages, setMessages] = useState([]);
  const [streaming, setStreaming] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [activeTool, setActiveTool] = useState(null);
  const [error, setError] = useState(null);
  const [currentConversationId, setCurrentConversationId] = useState(null);

  const conversationIdRef = useRef(null);
  const abortRef = useRef(null);
  // Stores extracted file contexts from file-only uploads, to be attached on next message
  const pendingFileContextsRef = useRef([]);

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
    pendingFileContextsRef.current = [];
    setMessages([]);
    setError(null);
    setActiveTool(null);
    setStreaming(false);
  }, []);

  const loadConversation = useCallback((conversation) => {
    abortRef.current?.abort();
    conversationIdRef.current = conversation.id;
    setCurrentConversationId(conversation.id);
    pendingFileContextsRef.current = [];
    setError(null);
    setActiveTool(null);
    setStreaming(false);
    setMessages(
      (conversation.messages || [])
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => {
          const attributions = m.attributions || [];
          const sources = [...new Set(attributions.flatMap((a) => a.sources || []))];
          if (m.role === 'user') {
            const { displayText, files } = parseUserContent(m.content || '');
            return { id: nextId('u'), role: 'user', content: displayText, files, attributions, sources };
          }
          return { id: nextId('a'), role: 'assistant', content: m.content || '', attributions, sources };
        }),
    );
  }, []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const send = useCallback(
    async (text, { editMessageId, files = [] } = {}) => {
      const content = (text || '').trim();
      if ((!content && files.length === 0) || streaming) return;

      setError(null);

      if (editMessageId) {
        setMessages((list) => {
          const idx = list.findIndex((m) => m.id === editMessageId);
          return idx >= 0 ? list.slice(0, idx) : list;
        });
      }

      // ── File-only upload: extract text, store for next message, show status ──
      if (files.length > 0 && !content) {
        setUploading(true);
        const fileContexts = [];
        const fileMetas = files.map((f) => ({
          name: f.name,
          type: f.type,
          size: f.size,
          previewUrl: f.type.startsWith('image/') ? URL.createObjectURL(f) : null,
        }));

        for (const file of files) {
          const { context } = await extractFileContext(file);
          fileContexts.push(context);
        }
        setUploading(false);

        // Store extracted contexts to attach on the user's next message
        pendingFileContextsRef.current = [
          ...pendingFileContextsRef.current,
          ...fileContexts,
        ];

        // Show file card message + synthetic assistant status (no AI call)
        setMessages((list) => [
          ...list,
          { id: nextId('u'), role: 'user', content: '', files: fileMetas },
          {
            id: nextId('a'),
            role: 'assistant',
            content: 'File uploaded and read successfully. You can now ask me to explain or summarize it.',
            synthetic: true,
          },
        ]);
        return;
      }

      // ── Normal send: attach any pending file contexts, then call AI ──────────
      let finalContent = content;

      // If files were also sent alongside text, extract them now
      if (files.length > 0) {
        setUploading(true);
        const fileContexts = [];
        for (const file of files) {
          const { context } = await extractFileContext(file);
          fileContexts.push(context);
        }
        setUploading(false);
        if (fileContexts.length > 0) {
          finalContent = `${finalContent}\n\n${fileContexts.join('\n\n')}`;
        }
      }

      // Attach pending file contexts from a previous file-only upload
      if (pendingFileContextsRef.current.length > 0) {
        finalContent = `${finalContent}\n\n${pendingFileContextsRef.current.join('\n\n')}`;
        pendingFileContextsRef.current = [];
      }

      if (!finalContent) return;

      const userId = nextId('u');
      const asstId = nextId('a');

      const fileMetas = files.map((f) => ({
        name: f.name,
        type: f.type,
        size: f.size,
        previewUrl: f.type.startsWith('image/') ? URL.createObjectURL(f) : null,
      }));

      setMessages((list) => [
        ...list,
        {
          id: userId,
          role: 'user',
          content: content,
          files: fileMetas.length > 0 ? fileMetas : undefined,
        },
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
