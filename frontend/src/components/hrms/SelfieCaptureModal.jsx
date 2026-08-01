import React, { useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Camera, X, RefreshCw, Check, AlertTriangle } from 'lucide-react';

// Selfie capture for a punch. Opens the camera, freezes a frame, and hands the caller a JPEG
// data URI — the parent uploads it with the punch.
//
// The stream is stopped on every exit path (capture, cancel, unmount, error). A forgotten
// getUserMedia stream leaves the camera light on, which users reasonably read as spying.
//
// Worth being honest about what this is: proof that *someone* was at the device, not identity
// verification. It is a deterrent, and the backend treats it that way.

const SelfieCaptureModal = ({ isOpen, onClose, onCapture, title = 'Capture selfie' }) => {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const [shot, setShot] = useState('');
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);

  const stopStream = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
  }, []);

  const startStream = useCallback(async () => {
    setError('');
    setStarting(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => {});
      }
    } catch {
      // Denied permission, no camera, or an insecure origin — all recoverable by the user, so
      // say so plainly rather than failing silently.
      setError('Camera unavailable. Allow camera access and try again.');
    } finally {
      setStarting(false);
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return undefined;
    setShot('');
    startStream();
    return () => stopStream();
  }, [isOpen, startStream, stopStream]);

  if (!isOpen) return null;

  const capture = () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !video.videoWidth) return;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    // 0.8 keeps a webcam frame around 100-200 KB — well inside the server's 4 MB ceiling.
    setShot(canvas.toDataURL('image/jpeg', 0.8));
    stopStream();
  };

  const retake = () => { setShot(''); startStream(); };

  const confirm = () => { stopStream(); onCapture?.(shot); };

  const cancel = () => { stopStream(); onClose?.(); };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[400] flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={cancel}
          className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        />
        <motion.div
          initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-sm rounded-[24px] bg-[var(--bg-card)] border border-[var(--border)] shadow-2xl overflow-hidden"
        >
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-[var(--border)] bg-[var(--table-header-bg)]">
            <div className="flex items-center gap-2.5">
              <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
                <Camera size={16} />
              </span>
              <h2 className="text-[14px] font-black tracking-tight text-[var(--text-main)]">{title}</h2>
            </div>
            <button onClick={cancel}
              className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--table-hover)] transition-colors"
              aria-label="Close">
              <X size={18} />
            </button>
          </div>

          <div className="p-5 flex flex-col gap-4">
            <div className="relative rounded-2xl overflow-hidden bg-[var(--input-bg)] border border-[var(--border)] aspect-[4/3] flex items-center justify-center">
              {error ? (
                <div className="flex flex-col items-center gap-2 px-6 text-center">
                  <AlertTriangle size={22} style={{ color: 'var(--accent-red)' }} />
                  <p className="text-[12px] font-bold text-[var(--text-muted)]">{error}</p>
                </div>
              ) : shot ? (
                <img src={shot} alt="Captured selfie" className="w-full h-full object-cover" />
              ) : (
                <>
                  {/* Mirrored, so moving left moves left on screen. */}
                  <video ref={videoRef} playsInline muted
                    className="w-full h-full object-cover"
                    style={{ transform: 'scaleX(-1)' }} />
                  {starting && (
                    <span className="absolute text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">
                      Starting camera…
                    </span>
                  )}
                </>
              )}
            </div>
            <canvas ref={canvasRef} className="hidden" />

            <div className="flex items-center gap-2.5">
              {error ? (
                <button onClick={startStream}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors">
                  <RefreshCw size={14} /> Retry
                </button>
              ) : shot ? (
                <>
                  <button onClick={retake}
                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-[var(--border)] text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors">
                    <RefreshCw size={14} /> Retake
                  </button>
                  <button onClick={confirm}
                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] transition-all">
                    <Check size={14} /> Use photo
                  </button>
                </>
              ) : (
                <button onClick={capture} disabled={starting}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-[var(--btn-primary)] text-white text-[11px] font-black uppercase tracking-widest shadow-md hover:opacity-90 active:scale-[0.98] disabled:opacity-50 transition-all">
                  <Camera size={14} /> Capture
                </button>
              )}
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default SelfieCaptureModal;
