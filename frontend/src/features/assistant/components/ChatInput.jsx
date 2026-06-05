import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Send, Square, Paperclip, X, Mic, MicOff } from 'lucide-react';
import FilePreview from './FilePreview';

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB

const ALLOWED_TYPES = new Set([
  'image/jpeg', 'image/jpg', 'image/png', 'image/webp',
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
  'audio/mpeg', 'audio/wav', 'audio/mp4',
  'video/mp4', 'video/webm', 'video/quicktime',
]);

const ACCEPT = [
  '.jpg', '.jpeg', '.png', '.webp',
  '.pdf', '.doc', '.docx', '.txt',
  '.mp3', '.wav', '.mp4', '.mov', '.webm',
].join(',');

// Check browser support once
const SpeechRecognition =
  typeof window !== 'undefined' &&
  (window.SpeechRecognition || window.webkitSpeechRecognition);

export default function ChatInput({
  onSend,
  onCancel,
  streaming,
  disabled,
  uploading,
  editTarget,
  onEditConsumed,
}) {
  const [value, setValue] = useState('');
  const [files, setFiles] = useState([]);
  const [fileError, setFileError] = useState('');

  // Mic state
  const [listening, setListening] = useState(false);
  const [micError, setMicError] = useState('');
  const recognitionRef = useRef(null);

  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);

  // ── Speech recognition ────────────────────────────────────────────────────
  const startListening = useCallback(() => {
    if (!SpeechRecognition) {
      setMicError('Speech recognition is not supported in this browser.');
      return;
    }
    setMicError('');

    const rec = new SpeechRecognition();
    rec.lang = 'en-US';
    rec.continuous = true;       // keep recording until user stops
    rec.interimResults = true;   // show partial results while speaking

    let finalTranscript = '';

    rec.onstart = () => setListening(true);

    rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalTranscript += t + ' ';
        else interim = t;
      }
      // Append to whatever the user already typed
      setValue((prev) => {
        const base = prev.trimEnd();
        const combined = finalTranscript || interim;
        return base ? `${base} ${combined.trim()}` : combined.trim();
      });
      // Auto-grow textarea
      requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (el) {
          el.style.height = 'auto';
          el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
        }
      });
    };

    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'permission-denied') {
        setMicError('Microphone access denied. Please allow it in your browser settings.');
      } else if (e.error !== 'no-speech') {
        setMicError('Microphone error. Please try again.');
      }
      setListening(false);
    };

    rec.onend = () => setListening(false);

    recognitionRef.current = rec;
    rec.start();
  }, []);

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setListening(false);
  }, []);

  const toggleMic = () => {
    if (listening) stopListening();
    else startListening();
  };

  // Stop mic if input is sent or component unmounts
  useEffect(() => () => recognitionRef.current?.stop(), []);

  // ── Edit pre-fill ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (editTarget) {
      stopListening();
      setValue(editTarget.content);
      const el = textareaRef.current;
      if (el) {
        el.focus();
        el.style.height = 'auto';
        el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
        setTimeout(() => { el.selectionStart = el.selectionEnd = el.value.length; }, 0);
      }
    }
  }, [editTarget, stopListening]);

  // ── Submit ────────────────────────────────────────────────────────────────
  const submit = () => {
    const text = value.trim();
    if ((!text && files.length === 0) || streaming || disabled || uploading) return;
    stopListening();
    onSend(text, { editMessageId: editTarget?.id, files });
    setValue('');
    setFiles([]);
    setFileError('');
    setMicError('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    onEditConsumed?.();
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  };

  const autoGrow = (e) => {
    setValue(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  };

  // ── File handling ─────────────────────────────────────────────────────────
  const handleFileSelect = (e) => {
    setFileError('');
    const selected = Array.from(e.target.files || []);
    const valid = [];
    for (const file of selected) {
      if (!ALLOWED_TYPES.has(file.type)) {
        setFileError(`"${file.name}" — unsupported file type.`);
        continue;
      }
      if (file.size > MAX_FILE_SIZE) {
        setFileError(`"${file.name}" exceeds the 10 MB size limit.`);
        continue;
      }
      valid.push(file);
    }
    if (valid.length) setFiles((prev) => [...prev, ...valid]);
    e.target.value = '';
  };

  const removeFile = (index) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
    if (files.length === 1) setFileError('');
  };

  const cancelEdit = () => {
    setValue('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    onEditConsumed?.();
  };

  const isLoading = streaming || uploading;
  const canSend = (value.trim() || files.length > 0) && !isLoading && !disabled;

  return (
    <div className="border-t border-[var(--border)] bg-[var(--bg-card)]">

      {/* Edit mode banner */}
      {editTarget && (
        <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--accent-indigo-bg)] px-3 py-1.5">
          <span className="text-xs font-medium text-[var(--accent-indigo)]">Editing message</span>
          <button
            type="button"
            onClick={cancelEdit}
            className="flex items-center gap-1 rounded text-[10px] text-[var(--text-muted)] hover:text-[var(--text-main)] transition"
          >
            <X size={12} /> Cancel
          </button>
        </div>
      )}

      {/* Listening indicator */}
      {listening && (
        <div className="flex items-center gap-2 border-b border-[var(--border)] bg-red-50 dark:bg-red-950/20 px-3 py-1.5">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-red-500" />
          </span>
          <span className="text-xs font-medium text-red-600 dark:text-red-400">
            Listening… speak now
          </span>
          <button
            type="button"
            onClick={stopListening}
            className="ml-auto text-[10px] text-red-500 hover:text-red-700 underline"
          >
            Stop
          </button>
        </div>
      )}

      {/* File previews */}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-2 px-3 pt-2">
          {files.map((file, i) => (
            <FilePreview key={`${file.name}-${i}`} file={file} onRemove={() => removeFile(i)} />
          ))}
        </div>
      )}

      {/* Errors */}
      {fileError && <p className="px-3 pt-1.5 text-xs text-[var(--accent-red)]">{fileError}</p>}
      {micError  && <p className="px-3 pt-1.5 text-xs text-[var(--accent-red)]">{micError}</p>}

      {/* Input row */}
      <div className="flex items-end gap-2 p-2.5">

        {/* Attach button */}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isLoading || disabled}
          title="Attach file"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--bg-main)] text-[var(--text-muted)] hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)] disabled:opacity-40 transition"
        >
          <Paperclip size={16} />
        </button>
        <input ref={fileInputRef} type="file" multiple accept={ACCEPT} onChange={handleFileSelect} className="hidden" />

        {/* Textarea */}
        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          onChange={autoGrow}
          onKeyDown={onKeyDown}
          disabled={disabled}
          placeholder={listening ? 'Listening…' : 'Ask about your sessions, scores, progress…'}
          className="max-h-[120px] flex-1 resize-none rounded-xl border border-[var(--input-border)] bg-[var(--input-bg)] px-3 py-2 text-sm text-[var(--text-main)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-indigo)] disabled:opacity-60 no-scrollbar"
        />

        {/* Mic button */}
        {!streaming && (
          <button
            type="button"
            onClick={toggleMic}
            disabled={disabled || uploading}
            title={
              !SpeechRecognition
                ? 'Speech recognition not supported'
                : listening
                  ? 'Stop listening'
                  : 'Speak your message'
            }
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border transition disabled:opacity-40 ${
              listening
                ? 'border-red-400 bg-red-500 text-white animate-pulse'
                : 'border-[var(--border)] bg-[var(--bg-main)] text-[var(--text-muted)] hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)]'
            }`}
          >
            {listening ? <MicOff size={15} /> : <Mic size={15} />}
          </button>
        )}

        {/* Stop / Send */}
        {streaming ? (
          <button
            type="button"
            onClick={onCancel}
            title="Stop generating"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--bg-main)] text-[var(--text-muted)] hover:border-red-400 hover:text-red-500 transition"
          >
            <Square size={15} />
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={!canSend}
            title={uploading ? 'Uploading…' : 'Send'}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-indigo)] text-white transition hover:opacity-90 disabled:opacity-40"
          >
            {uploading ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            ) : (
              <Send size={15} />
            )}
          </button>
        )}
      </div>
    </div>
  );
}
