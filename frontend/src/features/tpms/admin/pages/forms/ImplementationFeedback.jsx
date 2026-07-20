import React from 'react';
import { ClipboardList } from 'lucide-react';
import ChecklistForm from './ChecklistForm';

// Renders the shared engine; shows a "coming soon" state until the
// Implementation Feedback criteria are added to backend/app/models/forms.py.
const ImplementationFeedback = () => <ChecklistForm formType="implementation_feedback" icon={ClipboardList} />;

export default ImplementationFeedback;
