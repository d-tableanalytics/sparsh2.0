import React, { useEffect, useState } from 'react';
import { X, FileText, FileImage, Music, Video } from 'lucide-react';

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function FileIcon({ type }) {
  if (type.startsWith('image/'))  return <FileImage size={18} />;
  if (type.startsWith('audio/'))  return <Music size={18} />;
  if (type.startsWith('video/'))  return <Video size={18} />;
  return <FileText size={18} />;
}

export default function FilePreview({ file, onRemove }) {
  const isImage = file.type.startsWith('image/');
  const [preview, setPreview] = useState(null);
  const ext = file.name.split('.').pop().toUpperCase();

  useEffect(() => {
    if (!isImage) return;
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file, isImage]);

  return (
    <div className="relative flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-main)] p-2 pr-7 max-w-[190px] shrink-0">
      {/* Remove */}
      <button
        type="button"
        onClick={onRemove}
        className="absolute right-1.5 top-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-[var(--bg-card)] text-[var(--text-muted)] hover:bg-red-100 hover:text-red-500 transition"
        title="Remove"
      >
        <X size={9} />
      </button>

      {/* Thumbnail or icon */}
      {isImage && preview ? (
        <img
          src={preview}
          alt={file.name}
          className="h-10 w-10 rounded object-cover shrink-0"
        />
      ) : (
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
          <FileIcon type={file.type} />
        </div>
      )}

      {/* Info */}
      <div className="min-w-0">
        <p className="truncate text-[11px] font-medium text-[var(--text-main)]" title={file.name}>
          {file.name}
        </p>
        <p className="text-[10px] text-[var(--text-muted)]">
          {ext} · {formatBytes(file.size)}
        </p>
      </div>
    </div>
  );
}
