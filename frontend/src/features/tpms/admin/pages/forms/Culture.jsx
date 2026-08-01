import React from 'react';
import { Sparkles } from 'lucide-react';
import ChecklistForm from './ChecklistForm';

// Renders the shared engine; shows a "coming soon" state until the Culture
// criteria are added to backend/app/models/forms.py (available:false for now).
const Culture = () => <ChecklistForm formType="culture" icon={Sparkles} />;

export default Culture;
