import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  UploadCloud, FileVideo, FileAudio, FileText, FileImage, File as FileIcon,
  Trash2, Download, Search, Loader2, X, Library, Folder, BarChart2
} from 'lucide-react';
import api from '../services/api';
import { useNotification } from '../context/NotificationContext';
import { useUploadQueue } from '../context/UploadContext';
import MediaChatbot from '../components/MediaChatbot';
import MediaInsights from '../components/MediaInsights';
import UploadProgressDashboard from '../components/UploadProgressDashboard';

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
  const { enqueueFile } = useUploadQueue();
  const fileInputRef = useRef(null);

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');

  const [form, setForm] = useState({ media_type: 'video', name: '', description: '' });
  const [file, setFile] = useState(null);

  // New folder, tag, and insights dashboard states
  const [currentFolder, setCurrentFolder] = useState('/');
  const [folders, setFolders] = useState([]);
  const [selectedTag, setSelectedTag] = useState('');
  const [activeTab, setActiveTab] = useState('library');

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

  const fetchFolders = async () => {
    try {
      const { data } = await api.get('/media/ai/folders');
      setFolders(data);
    } catch (err) {
      console.warn("Failed to fetch folders:", err);
    }
  };

  useEffect(() => {
    fetchItems();
    fetchFolders();
  }, []);

  const handleFileChange = (e) => {
    // For high volume uploads, support multiple files
    const selectedFiles = Array.from(e.target.files || []);
    if (!selectedFiles.length) return;
    
    // Process the first file for form preview, others will be queued directly
    setFile(selectedFiles[0]);
    // Store all files in a temp attribute if multiple selected
    if (selectedFiles.length > 1) {
       fileInputRef.current._filesToProcess = selectedFiles;
       showSuccess(`Selected ${selectedFiles.length} files for upload. Submit to start queue.`);
    } else {
       fileInputRef.current._filesToProcess = [selectedFiles[0]];
    }

    setForm((prev) => ({
      ...prev,
      name: prev.name || selectedFiles[0].name.replace(/\.[^/.]+$/, ''),
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const filesToUpload = fileInputRef.current?._filesToProcess || (file ? [file] : []);
    
    if (filesToUpload.length === 0) return showError('Please choose a file to upload');
    if (filesToUpload.length === 1 && !form.name.trim()) return showError('Please enter a name');

    for (let i = 0; i < filesToUpload.length; i++) {
        let fileToProcess = filesToUpload[i];
        // Only use the form name for the first file if multiple selected
        const formToUpload = i === 0 ? { ...form } : { media_type: form.media_type, name: fileToProcess.name, description: '' };

        // Additive Duplicate Detection check before calling upload API
        try {
          const { data: dupCheck } = await api.get(`/media/ai/check-duplicate?filename=${encodeURIComponent(fileToProcess.name)}&size=${fileToProcess.size}`);
          if (dupCheck.duplicate) {
            const option = window.prompt(
              `A file named "${fileToProcess.name}" already exists.\n\nType one of the following options:\n- "both": Keep both (rename the new file)\n- "replace": Replace the existing file\n- "skip": Skip this upload\n\nChoice:`,
              "both"
            );
            if (!option) continue;
            const choice = option.toLowerCase().trim();
            if (choice === 'skip') {
              continue;
            } else if (choice === 'replace') {
              await api.delete(`/media/${dupCheck.existing.id}`);
            } else {
              const nameParts = fileToProcess.name.split('.');
              const ext = nameParts.pop();
              const baseName = nameParts.join('.');
              const newFileName = `${baseName}_copy_${Date.now()}.${ext}`;
              fileToProcess = new File([fileToProcess], newFileName, { type: fileToProcess.type });
              formToUpload.name = `${formToUpload.name.trim()} (Copy)`;
            }
          }
        } catch (err) {
          console.warn("Duplicate check error:", err);
        }

        // Enqueue to the background manager instead of blocking UI
        await enqueueFile(fileToProcess, formToUpload, currentFolder);
    }
    
    showSuccess(`${filesToUpload.length} file(s) added to the background upload queue.`);

    // Clear form state immediately for the next upload
    setForm({ media_type: 'video', name: '', description: '' });
    setFile(null);
    if (fileInputRef.current) {
        fileInputRef.current.value = '';
        fileInputRef.current._filesToProcess = [];
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
    const matchesFolder = (i.folder || '/') === currentFolder;
    const matchesTag = !selectedTag || (i.tags && i.tags.includes(selectedTag));
    return matchesType && matchesSearch && matchesFolder && matchesTag;
  });

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
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

        {/* View/Insights Toggle */}
        <div className="flex bg-[var(--input-bg)] p-1 rounded-xl border border-[var(--border)] w-fit self-end sm:self-auto">
          <button
            onClick={() => setActiveTab('library')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeTab === 'library'
                ? 'bg-[var(--bg-card)] text-[var(--text-main)] shadow-sm'
                : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'
            }`}
          >
            Library
          </button>
          <button
            onClick={() => setActiveTab('insights')}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
              activeTab === 'insights'
                ? 'bg-[var(--bg-card)] text-[var(--text-main)] shadow-sm'
                : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'
            }`}
          >
            <BarChart2 size={13} />
            AI Insights
          </button>
        </div>
      </div>

      {activeTab === 'insights' ? (
        <MediaInsights />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Upload form column */}
          <div className="lg:col-span-1 space-y-4 sticky top-6">
            <motion.form
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              onSubmit={handleSubmit}
              className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-5 h-fit space-y-4"
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
              disabled={!file && (!fileInputRef.current || !fileInputRef.current._filesToProcess?.length)}
              className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] font-semibold text-sm disabled:opacity-60 hover:opacity-90 transition-opacity"
            >
              <UploadCloud size={16} />
              Upload
            </button>
          </motion.form>
        </div>

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

          {/* Folder Navigation & Tag Breadcrumbs */}
          <div className="flex items-center justify-between flex-wrap gap-2 py-1.5 px-3 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl text-xs font-semibold text-[var(--text-muted)]">
            <div className="flex items-center gap-1.5 flex-wrap">
              <button
                onClick={() => {
                  setCurrentFolder('/');
                  setSelectedTag('');
                }}
                className={`hover:text-[var(--text-main)] ${currentFolder === '/' ? 'text-[var(--text-main)] font-bold' : ''}`}
              >
                Root
              </button>
              {currentFolder !== '/' && (
                <>
                  <span>/</span>
                  <span className="text-[var(--text-main)] font-bold">{currentFolder.replace(/^\//, '')}</span>
                </>
              )}
              {selectedTag && (
                <div className="flex items-center gap-1 bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)] px-2 py-0.5 rounded-full text-[10px]">
                  <span>Tag: {selectedTag}</span>
                  <button onClick={() => setSelectedTag('')} className="hover:opacity-80">
                    <X size={10} />
                  </button>
                </div>
              )}
            </div>

            {currentFolder === '/' && folders.length > 0 && (
              <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">{folders.length} Folder(s) available</span>
            )}
          </div>

          {/* Virtual Folders Grid */}
          {currentFolder === '/' && folders.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {folders.map((f) => (
                <div
                  key={f.id}
                  onClick={() => setCurrentFolder(f.name)}
                  className="flex items-center gap-3 p-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl cursor-pointer hover:border-[var(--sidebar-active-bg)] transition-colors group"
                >
                  <div className="p-2.5 rounded-lg bg-[var(--input-bg)] text-amber-500 group-hover:bg-amber-500/10 transition-colors">
                    <Folder size={18} />
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-bold text-[var(--text-main)] truncate">{f.name.replace(/^\//, '')}</p>
                    <p className="text-[9px] text-[var(--text-muted)] mt-0.5">Click to view</p>
                  </div>
                </div>
              ))}
            </div>
          )}

          {loading ? (
            <div className="flex items-center justify-center py-20 text-[var(--text-muted)]">
              <Loader2 size={22} className="animate-spin" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-20 text-[var(--text-muted)] border border-dashed border-[var(--border)] rounded-2xl">
              <Library size={32} className="mx-auto mb-3 opacity-50" />
              <p className="text-sm">No files yet in this view.</p>
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

                        {/* Display custom tags */}
                        {item.tags && item.tags.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1.5">
                            {item.tags.map((t) => (
                              <span
                                key={t}
                                onClick={() => setSelectedTag(t)}
                                className="cursor-pointer hover:bg-[var(--sidebar-active-bg)] hover:text-[var(--sidebar-active-text)] text-[9px] bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] px-1.5 py-0.5 rounded-full transition-colors"
                              >
                                #{t}
                              </span>
                            ))}
                          </div>
                        )}

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
      )}

      {/* Floating Chatbot Assistant */}
      <UploadProgressDashboard />
      <MediaChatbot
        currentFolder={currentFolder}
        onFilterChange={({ media_type, search, folder, tag }) => {
          if (media_type) setFilter(media_type);
          if (search !== undefined) setSearch(search);
          if (folder) setCurrentFolder(folder);
          if (tag !== undefined) setSelectedTag(tag);
        }}
        onRefreshFiles={fetchItems}
        onFolderCreated={(folder) => {
          fetchFolders();
          setCurrentFolder(folder.name);
        }}
      />
    </div>
  );
};

export default MediaLibrary;
