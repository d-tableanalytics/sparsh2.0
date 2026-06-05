import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import api from '../services/api';
import { useNotification } from './NotificationContext';

const UploadContext = createContext(null);

const MAX_CONCURRENT = 5;
const CHUNK_SIZE = 5 * 1024 * 1024; // 5MB
const MAX_RETRIES = 3;

// IndexedDB Helper
const DB_NAME = 'MediaUploadQueueDB';
const STORE_NAME = 'UploadQueue';

const openDB = () => {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
};

const saveToDB = async (upload) => {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).put(upload);
    return new Promise((resolve) => {
      tx.oncomplete = resolve;
    });
  } catch (err) {
    console.warn('IDB Save Error:', err);
  }
};

const loadFromDB = async () => {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const request = store.getAll();
    return new Promise((resolve) => {
      request.onsuccess = () => resolve(request.result || []);
    });
  } catch (err) {
    console.warn('IDB Load Error:', err);
    return [];
  }
};

const removeFromDB = async (id) => {
  try {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).delete(id);
    return new Promise((resolve) => {
      tx.oncomplete = resolve;
    });
  } catch (err) {
    console.warn('IDB Delete Error:', err);
  }
};

export const UploadProvider = ({ children }) => {
  const [queue, setQueue] = useState([]);
  const { showSuccess, showError } = useNotification();
  const activeProcessing = useRef(new Set());
  const abortControllers = useRef(new Map());

  // Load from DB on mount
  useEffect(() => {
    const init = async () => {
      const stored = await loadFromDB();
      if (stored && stored.length > 0) {
        // Any interrupted uploads mark as 'queued' so they resume
        const resumed = stored.map(u => ({
          ...u,
          status: (u.status === 'uploading' || u.status === 'processing') ? 'queued' : u.status
        }));
        setQueue(resumed);
      }
    };
    init();
  }, []);

  // Effect to process queue automatically
  useEffect(() => {
    processQueue();
  }, [queue]);

  const processQueue = () => {
    const uploadingCount = activeProcessing.current.size;
    if (uploadingCount >= MAX_CONCURRENT) return;

    // Find next pending items
    const pending = queue.filter(u => u.status === 'queued' && !activeProcessing.current.has(u.id));
    
    // Start up to the max concurrent limit
    const toStart = pending.slice(0, MAX_CONCURRENT - uploadingCount);
    toStart.forEach(u => {
      startUpload(u.id);
    });
  };

  const updateUploadState = (id, updates) => {
    setQueue(prev => {
      const updated = prev.map(u => {
        if (u.id === id) {
          const newU = { ...u, ...updates };
          saveToDB(newU);
          return newU;
        }
        return u;
      });
      return updated;
    });
  };

  const enqueueFile = async (file, form, currentFolder) => {
    const id = Date.now() + Math.random().toString(36).substring(2, 9);
    const newUpload = {
      id,
      file, // Native File object stores perfectly in IndexedDB
      fileName: file.name,
      size: file.size,
      media_type: form.media_type,
      name: form.name.trim() || file.name,
      description: form.description || '',
      folder: currentFolder,
      progress: 0,
      status: 'queued',
      uploadedChunks: [],
      s3UploadId: null,
      s3Key: null,
      retries: 0
    };
    
    await saveToDB(newUpload);
    setQueue(prev => [...prev, newUpload]);
    return id;
  };

  const startUpload = async (id) => {
    activeProcessing.current.add(id);
    updateUploadState(id, { status: 'uploading' });

    // Retrieve full item
    const uploadItem = await loadFromDB().then(db => db.find(u => u.id === id));
    if (!uploadItem || !uploadItem.file) {
      activeProcessing.current.delete(id);
      updateUploadState(id, { status: 'failed', error: 'File data lost from local cache' });
      return;
    }

    const { file, s3UploadId, s3Key, uploadedChunks } = uploadItem;
    let currentUploadId = s3UploadId;
    let currentKey = s3Key;
    const completedParts = [...(uploadedChunks || [])];
    
    const abortController = new AbortController();
    abortControllers.current.set(id, abortController);

    try {
      // 1. Initialize Multipart Upload if not already done
      if (!currentUploadId || !currentKey) {
        const startFd = new FormData();
        startFd.append('filename', file.name);
        startFd.append('content_type', file.type || 'application/octet-stream');
        
        const { data: startData } = await api.post('/media/chunk/start', startFd);
        currentUploadId = startData.upload_id;
        currentKey = startData.key;
        updateUploadState(id, { s3UploadId: currentUploadId, s3Key: currentKey });
      }

      // 2. Upload Chunks
      const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
      if (totalChunks === 0) throw new Error("Empty file");

      for (let i = 0; i < totalChunks; i++) {
        if (abortController.signal.aborted) throw new Error("Cancelled");
        
        const partNumber = i + 1;
        // Skip already uploaded parts
        if (completedParts.some(p => p.PartNumber === partNumber)) continue;

        const start = i * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE, file.size);
        const chunk = file.slice(start, end);

        let chunkRetries = 0;
        let chunkUploaded = false;

        while (!chunkUploaded && chunkRetries < MAX_RETRIES) {
          if (abortController.signal.aborted) throw new Error("Cancelled");
          try {
            const chunkFd = new FormData();
            chunkFd.append('upload_id', currentUploadId);
            chunkFd.append('key', currentKey);
            chunkFd.append('part_number', partNumber);
            chunkFd.append('file', new File([chunk], file.name, { type: file.type || 'application/octet-stream' }));

            const { data: partData } = await api.post('/media/chunk/upload', chunkFd, {
              signal: abortController.signal
            });

            completedParts.push({ ETag: partData.ETag, PartNumber: partData.PartNumber });
            chunkUploaded = true;
            
            // Update progress
            const progress = Math.round((completedParts.length / totalChunks) * 100);
            updateUploadState(id, { progress, uploadedChunks: completedParts });
            
          } catch (chunkErr) {
            if (abortController.signal.aborted) throw new Error("Cancelled");
            chunkRetries++;
            if (chunkRetries >= MAX_RETRIES) throw new Error(`Failed to upload chunk ${partNumber}`);
            await new Promise(r => setTimeout(r, 1000 * chunkRetries)); // exponential backoff
          }
        }
      }

      // 3. Complete Upload
      if (abortController.signal.aborted) throw new Error("Cancelled");
      updateUploadState(id, { status: 'processing', progress: 100 });
      
      const completeFd = new FormData();
      completeFd.append('upload_id', currentUploadId);
      completeFd.append('key', currentKey);
      completeFd.append('parts', JSON.stringify(completedParts));
      completeFd.append('media_type', uploadItem.media_type);
      completeFd.append('name', uploadItem.name);
      completeFd.append('description', uploadItem.description);
      completeFd.append('folder', uploadItem.folder || '/');
      completeFd.append('tags', ''); // Can append tags later if needed
      completeFd.append('size', file.size);
      completeFd.append('original_filename', file.name);
      completeFd.append('content_type', file.type || '');

      await api.post('/media/chunk/complete', completeFd);

      updateUploadState(id, { status: 'completed' });
      activeProcessing.current.delete(id);
      abortControllers.current.delete(id);
      removeFromDB(id); // Clean up IDB
      
    } catch (err) {
      if (err.message === "Cancelled") {
        updateUploadState(id, { status: 'cancelled' });
      } else {
        const retries = (uploadItem.retries || 0) + 1;
        if (retries < MAX_RETRIES) {
          updateUploadState(id, { status: 'queued', retries }); // auto-requeue
        } else {
          updateUploadState(id, { status: 'failed', error: err.message });
        }
      }
      activeProcessing.current.delete(id);
      abortControllers.current.delete(id);
    }
  };

  const cancelUpload = async (id) => {
    const controller = abortControllers.current.get(id);
    if (controller) {
      controller.abort();
    }
    
    updateUploadState(id, { status: 'cancelled' });
    activeProcessing.current.delete(id);
    
    // Optional: Call /media/chunk/abort to clean up S3 parts
    const u = await loadFromDB().then(db => db.find(x => x.id === id));
    if (u && u.s3UploadId && u.s3Key) {
      const fd = new FormData();
      fd.append('upload_id', u.s3UploadId);
      fd.append('key', u.s3Key);
      api.post('/media/chunk/abort', fd).catch(() => {});
    }
    removeFromDB(id);
  };

  const resumeUpload = (id) => {
    updateUploadState(id, { status: 'queued', retries: 0 });
  };

  const clearCompleted = () => {
    setQueue(prev => prev.filter(u => u.status !== 'completed' && u.status !== 'cancelled'));
  };

  return (
    <UploadContext.Provider value={{ queue, enqueueFile, cancelUpload, resumeUpload, clearCompleted }}>
      {children}
    </UploadContext.Provider>
  );
};

export const useUploadQueue = () => useContext(UploadContext);
