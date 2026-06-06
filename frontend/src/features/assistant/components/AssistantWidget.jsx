import React, { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { MessageCircle, X } from 'lucide-react';
import { useAuth } from '../../../context/AuthContext';
import ChatWindow from './ChatWindow';

/**
 * Global floating assistant. Mounted once in App.jsx; renders nothing when the
 * user is logged out, so it appears on every authenticated page but not /login.
 */
export default function AssistantWidget() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);

  if (!user) return null;

  return (
    <>
      <AnimatePresence>
        {open && (
          <motion.div
            key="assistant-panel"
            initial={{ opacity: 0, y: 24, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.98 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className={
              expanded
                ? 'fixed bottom-24 right-4 z-[70] h-[calc(100vh-8rem)] w-[min(900px,calc(100vw-2rem))]'
                : 'fixed bottom-24 right-4 z-[70] h-[min(620px,calc(100vh-8rem))] w-[min(400px,calc(100vw-2rem))]'
            }
          >
            <ChatWindow
              onClose={() => setOpen(false)}
              expanded={expanded}
              onToggleExpand={() => setExpanded((e) => !e)}
            />
          </motion.div>
        )}
      </AnimatePresence>

      <motion.button
        type="button"
        whileTap={{ scale: 0.92 }}
        onClick={() => setOpen((o) => !o)}
        title={open ? 'Close assistant' : 'Ask Sparsh'}
        className="fixed bottom-5 right-5 z-[70] flex h-14 w-14 items-center justify-center rounded-full bg-[var(--accent-indigo)] text-white shadow-xl transition hover:opacity-90"
      >
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={open ? 'close' : 'open'}
            initial={{ rotate: -90, opacity: 0 }}
            animate={{ rotate: 0, opacity: 1 }}
            exit={{ rotate: 90, opacity: 0 }}
            transition={{ duration: 0.15 }}
          >
            {open ? <X size={22} /> : <MessageCircle size={22} />}
          </motion.span>
        </AnimatePresence>
      </motion.button>
    </>
  );
}
