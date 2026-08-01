import React from 'react';
import { ClipboardList } from 'lucide-react';
import YesNoChecklistForm from './YesNoChecklistForm';

// Implementation Update Feedback is a Yes/No + remark checklist (MD respondent,
// partial submission), NOT a 0–5 rating matrix. It shows a "coming soon" state
// until the questions are added to backend/app/models/forms.py.
const ImplementationFeedback = () => <YesNoChecklistForm formType="implementation_feedback" icon={ClipboardList} />;

export default ImplementationFeedback;
