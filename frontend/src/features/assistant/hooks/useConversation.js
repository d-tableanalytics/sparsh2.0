import { useCallback, useState } from 'react';
import { deleteConversation, getConversation, listConversations } from '../services/assistantApi';

/**
 * Owns the conversation history list and load/delete operations.
 */
export default function useConversation() {
  const [conversations, setConversations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listConversations();
      // Guarantee newest-first ordering regardless of server order.
      list.sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
      setConversations(list);
    } catch {
      setError('Could not load conversations.');
    } finally {
      setLoading(false);
    }
  }, []);

  const load = useCallback((id) => getConversation(id), []);

  const remove = useCallback(async (id) => {
    await deleteConversation(id);
    setConversations((list) => list.filter((c) => c.id !== id));
  }, []);

  return { conversations, loading, error, refresh, load, remove };
}
