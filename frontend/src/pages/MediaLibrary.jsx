import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  UploadCloud, FileVideo, FileAudio, FileText, FileImage, File as FileIcon,
  Trash2, Download, Search, Loader2, X, Library
} from 'lucide-react';
import api from '../services/api';
import { useNotification } from '../context/NotificationContext';

const MEDIA_TYPES = [
  { value: 'video', label: 'Video', icon: FileVideo },
  { value: 'audio', label: 'Audio', icon: FileAudio },
  { value: 'pdf', label: 'PDF', icon: FileText },
  { value: 'document', label: 'Document', icon: FileText },
  { value: 'image', label: 'Image', icon: FileImage },
  { value: 'other', label: 'Other', icon: FileIcon },
];

const typeMeta = (type) =>
  MEDIA_TYPES.find((t) => t.value === type) || MEDIA_TYPES[MEDIA_TYPES.length - 1];

const formatSize = (bytes) => {
  if (!bytes) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
};

const MediaLibrary = () => {
  const { showSuccess, showError } = useNotification();
  const fileInputRef = useRef(null);

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');

  const [form, setForm] = useState({ media_type: 'video', name: '', description: '' });
  const [file, setFile] = useState(null);

  const fetchItems = async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/media');
      setItems(data);
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to load media library');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchItems();
  }, []);

  const handleFileChange = (e) => {
    const selected = e.target.files?.[0];
    if (!selected) return;
    setFile(selected);
    // Pre-fill the name from the filename if the user hasn't typed one yet.
    setForm((prev) => ({
      ...prev,
      name: prev.name || selected.name.replace(/\.[^/.]+$/, ''),
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) return showError('Please choose a file to upload');
    if (!form.name.trim()) return showError('Please enter a name');

    const fd = new FormData();
    fd.append('media_type', form.media_type);
    fd.append('name', form.name.trim());
    fd.append('description', form.description.trim());
    fd.append('file', file);

    setUploading(true);
    try {
      const { data } = await api.post('/media', fd);
      setItems((prev) => [data.media, ...prev]);
      showSuccess('File uploaded successfully');
      setForm({ media_type: 'video', name: '', description: '' });
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    } catch (err) {
      showError(err.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this file? This cannot be undone.')) return;
    try {
      await api.delete(`/media/${id}`);
      setItems((prev) => prev.filter((i) => i._id !== id));
      showSuccess('File deleted');
    } catch (err) {
      showError(err.response?.data?.detail || 'Delete failed');
    }
  };

  const filtered = items.filter((i) => {
    const matchesType = filter === 'all' || i.media_type === filter;
    const matchesSearch =
      !search.trim() ||
      i.name?.toLowerCase().includes(search.toLowerCase()) ||
      i.description?.toLowerCase().includes(search.toLowerCase());
    return matchesType && matchesSearch;
  });

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2.5 rounded-xl bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)]">
          <Library size={22} />
        </div>
        <div>
          <h1 className="text-xl font-bold text-[var(--text-main)] tracking-tight">Media Library</h1>
          <p className="text-sm text-[var(--text-muted)]">
            Upload videos, audio, PDFs and any file type. Other modules reference these uploads.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Upload form */}
        <motion.form
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          onSubmit={handleSubmit}
          className="lg:col-span-1 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-5 h-fit space-y-4 sticky top-6"
        >
          <h2 className="text-sm font-bold uppercase tracking-widest text-[var(--text-muted)]">
            Upload File
          </h2>

          <div>
            <label className="block text-xs font-semibold text-[var(--text-muted)] mb-1.5">Type</label>
            <select
              value={form.media_type}
              onChange={(e) => setForm({ ...form, media_type: e.target.value })}
              className="w-full px-3 py-2.5 rounded-lg bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--sidebar-active-bg)]"
            >
              {MEDIA_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-[var(--text-muted)] mb-1.5">Name</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Onboarding walkthrough"
              className="w-full px-3 py-2.5 rounded-lg bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--sidebar-active-bg)]"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-[var(--text-muted)] mb-1.5">Description</label>
            <textarea
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              rows={3}
              placeholder="Optional description"
              className="w-full px-3 py-2.5 rounded-lg bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] text-sm resize-none focus:outline-none focus:ring-2 focus:ring-[var(--sidebar-active-bg)]"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-[var(--text-muted)] mb-1.5">File</label>
            <div
              onClick={() => fileInputRef.current?.click()}
              className="border-2 border-dashed border-[var(--border)] rounded-lg p-5 text-center cursor-pointer hover:border-[var(--sidebar-active-bg)] transition-colors"
            >
              <UploadCloud size={24} className="mx-auto text-[var(--text-muted)] mb-2" />
              {file ? (
                <div className="flex items-center justify-center gap-2 text-sm text-[var(--text-main)]">
                  <span className="truncate max-w-[180px]">{file.name}</span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setFile(null);
                      if (fileInputRef.current) fileInputRef.current.value = '';
                    }}
                    className="text-[var(--accent-red)]"
                  >
                    <X size={16} />
                  </button>
                </div>
              ) : (
                <p className="text-sm text-[var(--text-muted)]">Click to choose a file (any type)</p>
              )}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              onChange={handleFileChange}
              className="hidden"
            />
          </div>

          <button
            type="submit"
            disabled={uploading}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] font-semibold text-sm disabled:opacity-60 hover:opacity-90 transition-opacity"
          >
            {uploading ? <Loader2 size={16} className="animate-spin" /> : <UploadCloud size={16} />}
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
        </motion.form>

        {/* Library list */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by name or description"
                className="w-full pl-9 pr-3 py-2.5 rounded-lg bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--sidebar-active-bg)]"
              />
            </div>
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="px-3 py-2.5 rounded-lg bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-main)] text-sm focus:outline-none"
            >
              <option value="all">All types</option>
              {MEDIA_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-20 text-[var(--text-muted)]">
              <Loader2 size={22} className="animate-spin" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-20 text-[var(--text-muted)] border border-dashed border-[var(--border)] rounded-2xl">
              <Library size={32} className="mx-auto mb-3 opacity-50" />
              <p className="text-sm">No files yet. Upload your first file using the form.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <AnimatePresence>
                {filtered.map((item) => {
                  const meta = typeMeta(item.media_type);
                  const Icon = meta.icon;
                  return (
                    <motion.div
                      key={item._id}
                      layout
                      initial={{ opacity: 0, scale: 0.97 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.97 }}
                      className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 flex gap-3"
                    >
                      <div className="p-2.5 rounded-lg bg-[var(--input-bg)] text-[var(--text-main)] h-fit">
                        <Icon size={20} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between gap-2">
                          <h3 className="text-sm font-semibold text-[var(--text-main)] truncate">{item.name}</h3>
                          <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] bg-[var(--input-bg)] px-2 py-0.5 rounded-full whitespace-nowrap">
                            {meta.label}
                          </span>
                        </div>
                        {item.description && (
                          <p className="text-xs text-[var(--text-muted)] mt-1 line-clamp-2">{item.description}</p>
                        )}
                        <p className="text-[11px] text-[var(--text-muted)] mt-1 truncate">
                          {item.file_name}{item.size ? ` · ${formatSize(item.size)}` : ''}
                        </p>
                        <div className="flex items-center gap-3 mt-2.5">
                          <a
                            href={item.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--sidebar-active-text)]"
                          >
                            <Download size={13} /> Open
                          </a>
                          <button
                            onClick={() => handleDelete(item._id)}
                            className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--accent-red)]"
                          >
                            <Trash2 size={13} /> Delete
                          </button>
                        </div>
                      </div>
                    </motion.div>
                  );
                })}
              </AnimatePresence>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default MediaLibrary;
