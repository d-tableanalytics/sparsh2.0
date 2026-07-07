import React, { useCallback, useEffect, useState } from 'react';
import { Plus, GripVertical, Pencil } from 'lucide-react';
import { getBoardCards, createBoardCard, updateBoardCard, moveBoardCard, deleteBoardCard } from '../../services/groupBoardApi';
import { getInitials } from '../tasks/taskDisplayUtils';
import BoardCardModal from './BoardCardModal';
import { useNotification } from '../../context/NotificationContext';

const COLUMNS = [
  { key: 'todo', label: 'To Do' },
  { key: 'in_progress', label: 'In Progress' },
  { key: 'done', label: 'Done' },
];

// Fixed 3-column kanban board scoped to the group. Uses native HTML5 drag-and-drop
// (no dnd library installed in this project) -- v1 drop behavior appends to the end of
// the target column rather than detecting a precise insertion index.
const GroupIdeaboard = ({ group, userMap, staffOptions }) => {
  const { showError } = useNotification();
  const [cards, setCards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingCard, setEditingCard] = useState(null);
  const [modalColumn, setModalColumn] = useState('todo');
  const [dragOverColumn, setDragOverColumn] = useState(null);

  const members = staffOptions.filter(u => (group.member_ids || []).includes(u._id));

  const fetchCards = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getBoardCards(group.id);
      setCards(res.data || []);
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to load board');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group.id]);

  useEffect(() => { fetchCards(); }, [fetchCards]);

  const columnCards = (key) => cards.filter(c => c.column === key).sort((a, b) => a.order - b.order);

  const handleSave = async (payload) => {
    try {
      if (editingCard) {
        await updateBoardCard(group.id, editingCard.id, payload);
      } else {
        await createBoardCard(group.id, payload);
      }
      setModalOpen(false);
      fetchCards();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to save card');
    }
  };

  const handleDelete = async (card) => {
    try {
      await deleteBoardCard(group.id, card.id);
      setModalOpen(false);
      fetchCards();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to delete card');
    }
  };

  const handleDrop = async (e, columnKey) => {
    e.preventDefault();
    setDragOverColumn(null);
    const cardId = e.dataTransfer.getData('text/plain');
    const card = cards.find(c => c.id === cardId);
    if (!card || card.column === columnKey) return;
    try {
      await moveBoardCard(group.id, cardId, { column: columnKey });
      fetchCards();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to move card');
    }
  };

  if (loading) {
    return <div className="p-16 text-center text-[var(--text-muted)] text-[12px] font-bold bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px]">Loading board...</div>;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {COLUMNS.map(col => (
        <div key={col.key}
          onDragOver={(e) => { e.preventDefault(); setDragOverColumn(col.key); }}
          onDragLeave={() => setDragOverColumn(prev => (prev === col.key ? null : prev))}
          onDrop={(e) => handleDrop(e, col.key)}
          className={`bg-[var(--bg-card)] border rounded-[24px] p-3 space-y-2 min-h-[240px] transition-colors ${dragOverColumn === col.key ? 'border-[var(--accent-indigo)]' : 'border-[var(--border)]'}`}>
          <div className="flex items-center justify-between px-1.5 pb-1">
            <p className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">{col.label} ({columnCards(col.key).length})</p>
            <button onClick={() => { setEditingCard(null); setModalColumn(col.key); setModalOpen(true); }}
              className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--accent-indigo)]">
              <Plus size={14} />
            </button>
          </div>

          {columnCards(col.key).map(card => (
            <div key={card.id} draggable
              onDragStart={(e) => e.dataTransfer.setData('text/plain', card.id)}
              onClick={() => { setEditingCard(card); setModalColumn(card.column); setModalOpen(true); }}
              className="bg-[var(--input-bg)] border border-[var(--border)] rounded-xl p-3 cursor-grab active:cursor-grabbing hover:border-[var(--accent-indigo)] transition-all">
              <div className="flex items-start gap-2">
                <GripVertical size={13} className="text-[var(--text-muted)] shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <p className="text-[12px] font-bold text-[var(--text-main)] break-words">{card.title}</p>
                  {card.description && <p className="text-[11px] font-medium text-[var(--text-muted)] mt-1 line-clamp-2">{card.description}</p>}
                  <div className="flex items-center justify-between mt-2">
                    {card.assignee_id ? (
                      <div className="w-6 h-6 rounded-full flex items-center justify-center text-white font-black text-[9px]" style={{ background: 'var(--avatar-bg)' }} title={userMap[card.assignee_id]}>
                        {getInitials(userMap[card.assignee_id] || '?')}
                      </div>
                    ) : <span />}
                    <Pencil size={11} className="text-[var(--text-muted)] opacity-0 group-hover:opacity-100" />
                  </div>
                </div>
              </div>
            </div>
          ))}

          {columnCards(col.key).length === 0 && (
            <p className="text-center text-[10px] font-bold text-[var(--text-muted)] py-6 opacity-60">Drop cards here</p>
          )}
        </div>
      ))}

      <BoardCardModal isOpen={modalOpen} onClose={() => setModalOpen(false)} onSave={handleSave} onDelete={handleDelete}
        card={editingCard} defaultColumn={modalColumn} members={members} />
    </div>
  );
};

export default GroupIdeaboard;
