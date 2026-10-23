/**
 * Reminder offset vocabulary, shared between the editor and the read-only views.
 *
 * A plain module rather than part of ReminderModal.jsx because a file that exports both a
 * component and a helper loses Fast Refresh for the whole file
 * (react-refresh/only-export-components) -- editing the modal would full-reload the page
 * instead of patching the component.
 *
 * offset_minutes is what's actually persisted (see Reminder model in calendar_event.py);
 * offset_unit is UI-only (silently dropped by the backend's pydantic model on save) so a
 * reminder edited/reloaded later re-derives its display unit from offset_minutes via
 * inferUnit.
 */

export const UNIT_MINUTES = { Minutes: 1, Hours: 60, Days: 1440 };

export const inferUnit = (mins) => {
    if (mins && mins % 1440 === 0) return 'Days';
    if (mins && mins % 60 === 0) return 'Hours';
    return 'Minutes';
};

// Shared so read-only views (e.g. the task View screen) describe a reminder exactly the way
// the editor does, instead of re-deriving the unit and drifting from it.
export const describeReminder = (r) => {
    const unit = r?.offset_unit || inferUnit(r?.offset_minutes);
    const amount = Math.round((r?.offset_minutes || 0) / UNIT_MINUTES[unit]);
    const when = `${amount} ${amount === 1 ? unit.replace(/s$/, '') : unit} ${r?.timing_type || 'before'}`;
    const channel = r?.reminder_type === 'both' ? 'Email + WhatsApp'
        : r?.reminder_type === 'whatsapp' ? 'WhatsApp' : 'Email';
    return { when, channel };
};
