import api from '../../../services/api';

// Streaming uses native fetch + ReadableStream because EventSource cannot send
// the Authorization header or a POST body. Non-streaming endpoints reuse the
// shared axios instance (which already injects the JWT).

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

function getToken() {
  return localStorage.getItem('token');
}

/**
 * POST /assistant/ask with stream:true and dispatch SSE events.
 * onEvent(eventName, data) is called for: meta | tool | token | done.
 * Throws an Error (with .status / .retryAfter) on non-OK responses.
 */
export async function streamAsk({ message, conversationId, signal, onEvent }) {
  const res = await fetch(`${API_BASE}/assistant/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({
      message,
      conversation_id: conversationId || null,
      stream: true,
    }),
    signal,
  });

  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.json();
      detail = body.detail || '';
    } catch {
      /* non-JSON error body */
    }
    const err = new Error(detail || `Request failed (${res.status})`);
    err.status = res.status;
    const retry = res.headers.get('Retry-After');
    if (retry) err.retryAfter = Number(retry);
    throw err;
  }

  // If streaming is disabled server-side (STREAMING_ENABLED=false), the backend
  // returns a JSON AskResponse instead of SSE. Adapt it to the same event flow.
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    const data = await res.json();
    const meta = data.meta || {};
    if (data.conversation_id) onEvent('meta', { conversation_id: data.conversation_id });
    if (data.answer) onEvent('token', { text: data.answer });
    onEvent('done', {
      conversation_id: data.conversation_id,
      sources: data.sources || [],
      attributions: meta.attributions || [],
      usage: meta.usage,
      cost: meta.cost,
      latency_ms: meta.latency_ms,
      title: meta.title,
    });
    return;
  }

  // Fallback if the environment doesn't expose a readable stream.
  if (!res.body || !res.body.getReader) {
    const text = await res.text();
    text.split('\n\n').forEach((frame) => dispatchFrame(frame, onEvent));
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    // Normalize CRLF that some proxies inject, then split into SSE frames.
    buffer += decoder.decode(value, { stream: true }).replace(/\r/g, '');
    let sep;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      dispatchFrame(frame, onEvent);
    }
  }
  if (buffer.trim()) dispatchFrame(buffer, onEvent);
}

function dispatchFrame(frame, onEvent) {
  if (!frame.trim()) return;
  let event = 'message';
  const dataLines = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return;
  let data;
  try {
    data = JSON.parse(dataLines.join('\n'));
  } catch {
    data = { raw: dataLines.join('\n') };
  }
  onEvent(event, data);
}

/**
 * Upload a file to the assistant. Returns { filename, text, has_images }.
 * The extracted text is appended to the user's next message as context.
 */
export async function uploadFile(file) {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${API_BASE}/assistant/upload`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${getToken()}` },
    body: formData,
  });

  if (!res.ok) {
    const err = new Error(`Upload failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

/** Non-streaming fallback. Returns { conversation_id, answer, sources, meta }. */
export async function askOnce({ message, conversationId }) {
  const res = await api.post('/assistant/ask', {
    message,
    conversation_id: conversationId || null,
    stream: false,
  });
  return res.data;
}

// ── Conversation management (used in Milestone B) ──────────────────────────
export async function listConversations() {
  const res = await api.get('/assistant/conversations');
  return res.data.conversations || [];
}

export async function getConversation(id) {
  const res = await api.get(`/assistant/conversations/${id}`);
  return res.data;
}

export async function deleteConversation(id) {
  const res = await api.delete(`/assistant/conversations/${id}`);
  return res.data;
}
