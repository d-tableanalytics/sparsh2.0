/**
 * Source Analytics: the funnel stages and the per-platform colours, shared by the page and
 * its charts. Stage keys match SRC_STAGES in hrms_analytics_service.py.
 */
export const STAGES = [
  { key: 'applied', label: 'Applied', color: '#6366f1',
    hint: 'Applied in the period' },
  { key: 'shortlisted', label: 'Shortlisted', color: '#0ea5e9',
    hint: 'Cleared HR’s CV screening' },
  { key: 'connected', label: 'Connected', color: '#8b5cf6',
    hint: 'HR spoke to them on the phone screen (Passed or Rejected — “No Answer” does not count)' },
  { key: 'interviewed', label: 'Interviewed', color: '#f59e0b',
    hint: 'An interview actually took place (Completed or given a result)' },
  { key: 'selected', label: 'Selected', color: '#22c55e',
    hint: 'Selected for the role' },
  { key: 'hired', label: 'Hired', color: '#059669',
    hint: 'Joined the company' },
];

// Brand-ish so a platform reads the same in every chart; "Not specified" is grey.
export const PLATFORM_COLORS = {
  linkedin: '#0a66c2', naukri: '#4a90e2', indeed: '#2557a7', apna: '#e5397c', foundit: '#6f3fd8',
  shine: '#f59e0b', website: '#10b981', referral: '#ec4899', social: '#8b5cf6', whatsapp: '#22c55e',
  other: '#64748b', unspecified: '#94a3b8', untagged: '#94a3b8',
};

export const platformColor = (key) => PLATFORM_COLORS[key] || PLATFORM_COLORS.other;
