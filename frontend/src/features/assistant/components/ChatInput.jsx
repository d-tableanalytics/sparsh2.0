import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Send, Square, Paperclip, X, Mic, Check } from 'lucide-react';
import FilePreview from './FilePreview';

const MAX_FILE_SIZE = 10 * 1024 * 1024;

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

const SpeechRecognition =
  typeof window !== 'undefined' &&
  (window.SpeechRecognition || window.webkitSpeechRecognition);

const BAR_COUNT = 36;

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
  const [listening, setListening] = useState(false);
  const [micError, setMicError] = useState('');
  const [waveformBars, setWaveformBars] = useState(Array(BAR_COUNT).fill(4));

  const recognitionRef = useRef(null);
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);
  const baseTextRef = useRef('');
  const audioCtxRef = useRef(null);
  const animFrameRef = useRef(null);

  // ── Waveform ───────────────────────────────────────────────────────────────
  const stopWaveform = useCallback(() => {
    cancelAnimationFrame(animFrameRef.current);
    if (audioCtxRef.current) {
      try {
        audioCtxRef.current.stream.getTracks().forEach((t) => t.stop());
        audioCtxRef.current.ctx.close();
      } catch (_) {}
      audioCtxRef.current = null;
    }
    setWaveformBars(Array(BAR_COUNT).fill(4));
  }, []);

  const startWaveform = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 128;
      analyser.smoothingTimeConstant = 0.8;
      ctx.createMediaStreamSource(stream).connect(analyser);
      audioCtxRef.current = { ctx, stream, analyser };

      const tick = () => {
        const data = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(data);
        const bars = Array.from({ length: BAR_COUNT }, (_, i) => {
          const idx = Math.floor((i / BAR_COUNT) * (analyser.frequencyBinCount * 0.65));
          return Math.max(4, Math.round((data[idx] / 255) * 48));
        });
        setWaveformBars(bars);
        animFrameRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch (_) {
      // Fallback: CSS sine-wave animation
      let t = 0;
      const tick = () => {
        t += 0.12;
        const bars = Array.from({ length: BAR_COUNT }, (_, i) =>
          Math.max(4, Math.round(20 + Math.sin(t + i * 0.45) * 14 + Math.sin(t * 1.7 + i * 0.8) * 8))
        );
        setWaveformBars(bars);
        animFrameRef.current = requestAnimationFrame(tick);
      };
      tick();
    }
  }, []);

  // ── Speech recognition ─────────────────────────────────────────────────────
  const startListening = useCallback(() => {
    if (!SpeechRecognition) {
      setMicError('Speech recognition is not supported in this browser.');
      return;
    }
    setMicError('');
    baseTextRef.current = (textareaRef.current?.value ?? '').trimEnd();

    const rec = new SpeechRecognition();
    rec.lang = 'en-IN';
    rec.continuous = true;
    rec.interimResults = true;

    rec.onstart = () => {
      setListening(true);
      startWaveform();
    };

    rec.onresult = (e) => {
      let finalText = '';
      let interimText = '';
      for (let i = 0; i < e.results.length; i++) {
        if (e.results[i].isFinal) finalText += e.results[i][0].transcript;
        else interimText += e.results[i][0].transcript;
      }
      const speech = (finalText + interimText).trim();
      const base = baseTextRef.current;
      setValue(base ? `${base} ${speech}` : speech);
    };

    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'permission-denied') {
        setMicError('Microphone access denied. Please allow it in your browser settings.');
      } else if (e.error !== 'no-speech') {
        setMicError('Microphone error. Please try again.');
      }
      setListening(false);
      stopWaveform();
    };

    rec.onend = () => {
      setListening(false);
      stopWaveform();
    };

    recognitionRef.current = rec;
    rec.start();
  }, [startWaveform, stopWaveform]);

  // Confirm: stop and keep transcript in textarea
  const confirmListening = useCallback(() => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setListening(false);
    stopWaveform();
    setTimeout(() => {
      const el = textareaRef.current;
      if (el) {
        el.focus();
        el.style.height = 'auto';
        el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
        el.selectionStart = el.selectionEnd = el.value.length;
      }
    }, 50);
  }, [stopWaveform]);

  // Discard: stop and reset to pre-mic text
  const discardListening = useCallback(() => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setListening(false);
    stopWaveform();
    setValue(baseTextRef.current);
  }, [stopWaveform]);

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setListening(false);
    stopWaveform();
  }, [stopWaveform]);

  // Cleanup on unmount
  useEffect(() => () => {
    recognitionRef.current?.stop();
    stopWaveform();
  }, [stopWaveform]);

  // Reset height when input cleared
  useEffect(() => {
    if (!value && textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [value]);

  // ── Edit pre-fill ──────────────────────────────────────────────────────────
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

  // ── Submit ─────────────────────────────────────────────────────────────────
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

  // ── File handling ──────────────────────────────────────────────────────────
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
      {editTarget && !listening && (
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

      {/* File previews */}
      {!listening && files.length > 0 && (
        <div className="flex flex-wrap gap-2 px-3 pt-2">
          {files.map((file, i) => (
            <FilePreview key={`${file.name}-${i}`} file={file} onRemove={() => removeFile(i)} />
          ))}
        </div>
      )}

      {/* Errors */}
      {!listening && fileError && <p className="px-3 pt-1.5 text-xs text-[var(--accent-red)]">{fileError}</p>}
      {!listening && micError  && <p className="px-3 pt-1.5 text-xs text-[var(--accent-red)]">{micError}</p>}

      {listening ? (
        /* ── ChatGPT-style voice UI ──────────────────────────────────────── */
        <div className="flex items-center gap-3 px-4 py-3">
          {/* Waveform */}
          <div className="flex flex-1 items-center justify-center gap-[2px] h-12">
            {waveformBars.map((h, i) => (
              <div
                key={i}
                className="w-[3px] rounded-full bg-[var(--accent-indigo)] transition-all duration-75"
                style={{ height: `${h}px`, opacity: 0.5 + (h / 48) * 0.5 }}
              />
            ))}
          </div>

          {/* Discard */}
          <button
            type="button"
            onClick={discardListening}
            title="Discard"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--bg-main)] text-[var(--text-muted)] hover:border-[var(--accent-red)] hover:text-[var(--accent-red)] transition"
          >
            <X size={18} />
          </button>

          {/* Confirm */}
          <button
            type="button"
            onClick={confirmListening}
            title="Use transcript"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[var(--accent-indigo)] text-white hover:opacity-90 transition"
          >
            <Check size={18} />
          </button>
        </div>
      ) : (
        /* ── Normal input row ────────────────────────────────────────────── */
        <div className="flex items-end gap-2 p-2.5">

          {/* Attach */}
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
            placeholder="Ask anything…"
            className="max-h-[120px] flex-1 resize-none rounded-xl border border-[var(--input-border)] bg-[var(--input-bg)] px-3 py-2 text-sm text-[var(--text-main)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-indigo)] disabled:opacity-60 no-scrollbar"
          />

          {/* Mic */}
          {!streaming && (
            <button
              type="button"
              onClick={startListening}
              disabled={disabled || uploading || !SpeechRecognition}
              title={!SpeechRecognition ? 'Speech recognition not supported' : 'Speak your message'}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--bg-main)] text-[var(--text-muted)] hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)] disabled:opacity-40 transition"
            >
              <Mic size={15} />
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
      )}
    </div>
  );
}
