import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, ChevronLeft, ChevronRight, Save } from 'lucide-react';

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const isSameDay = (a, b) => a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

// Hand-rolled month-grid date/time picker (no date-picker library installed in this
// project) matching the reference "Select Due Date" popover.
const MiniDatePicker = ({ isOpen, onClose, value, onApply, title = 'Select Due Date' }) => {
  const [viewMonth, setViewMonth] = useState(0);
  const [viewYear, setViewYear] = useState(2000);
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [time, setTime] = useState('12:00');
  const [tab, setTab] = useState('date');

  useEffect(() => {
    if (!isOpen) return;
    const d = value ? new Date(value) : new Date();
    setViewMonth(d.getMonth());
    setViewYear(d.getFullYear());
    setSelectedDate(d);
    setTime(`${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`);
    setTab('date');
  }, [isOpen, value]);

  if (!isOpen) return null;

  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
  const firstDayOfWeek = new Date(viewYear, viewMonth, 1).getDay();
  const today = new Date();

  const cells = [];
  for (let i = 0; i < firstDayOfWeek; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  const navigate = (delta) => {
    let m = viewMonth + delta, y = viewYear;
    if (m < 0) { m = 11; y -= 1; }
    if (m > 11) { m = 0; y += 1; }
    setViewMonth(m); setViewYear(y);
  };

  const handleApply = () => {
    const [h, min] = time.split(':').map(Number);
    const final = new Date(viewYear, viewMonth, selectedDate.getDate(), h, min);
    onApply(final.toISOString());
    onClose();
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[400] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-sm bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl overflow-hidden">
          <div className="px-5 py-4 border-b border-[var(--border)] flex items-center justify-between">
            <h3 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest">{title}</h3>
            <button onClick={onClose} className="p-1 rounded-full hover:bg-[var(--input-bg)] text-[var(--text-muted)]"><X size={18} /></button>
          </div>

          <div className="p-5">
            <div className="flex bg-[var(--input-bg)] p-1 rounded-full mb-4">
              {['date', 'time'].map(t => (
                <button type="button" key={t} onClick={() => setTab(t)}
                  className={`flex-1 py-2 rounded-full text-[10px] font-black uppercase tracking-widest transition-all ${tab === t ? 'bg-[var(--bg-card)] text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)]'}`}>
                  {t}
                </button>
              ))}
            </div>

            {tab === 'date' ? (
              <>
                <div className="flex items-center justify-between mb-4">
                  <span className="px-4 py-1.5 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] rounded-full text-[11px] font-black uppercase tracking-widest">
                    {new Date(viewYear, viewMonth).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
                  </span>
                  <div className="flex gap-1.5">
                    <button type="button" onClick={() => navigate(-1)} className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)]"><ChevronLeft size={14} /></button>
                    <button type="button" onClick={() => navigate(1)} className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)]"><ChevronRight size={14} /></button>
                  </div>
                </div>
                <div className="grid grid-cols-7 gap-1 text-center mb-1">
                  {WEEKDAYS.map(w => <span key={w} className="text-[9px] font-black text-[var(--text-muted)] uppercase">{w}</span>)}
                </div>
                <div className="grid grid-cols-7 gap-1">
                  {cells.map((d, i) => {
                    if (!d) return <span key={i} />;
                    const cellDate = new Date(viewYear, viewMonth, d);
                    const isToday = isSameDay(cellDate, today);
                    const isSelected = isSameDay(cellDate, selectedDate) && !isToday;
                    const isWeekend = cellDate.getDay() === 0;
                    return (
                      <button type="button" key={i} onClick={() => setSelectedDate(cellDate)}
                        className={`aspect-square flex items-center justify-center rounded-full text-[11px] font-bold transition-all ${
                          isToday ? 'bg-[var(--accent-indigo)] text-white'
                            : isSelected ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                            : isWeekend ? 'text-[var(--accent-red)]' : 'text-[var(--text-main)]'
                        }`}>
                        {d}
                      </button>
                    );
                  })}
                </div>
              </>
            ) : (
              <input type="time" value={time} onChange={e => setTime(e.target.value)}
                className="w-full px-4 py-3 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[14px] font-bold outline-none text-center" />
            )}
          </div>

          <div className="px-5 py-4 border-t border-[var(--border)] flex items-center justify-between">
            <button type="button" onClick={onClose} className="text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)]">Cancel</button>
            <button type="button" onClick={handleApply} className="flex items-center gap-1.5 px-5 py-2 bg-[var(--accent-orange)] text-white rounded-xl text-[10px] font-black uppercase tracking-widest">
              <Save size={13} /> Done
            </button>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default MiniDatePicker;
