import {
  Users, UsersRound, Briefcase, Building2, Target, Layers,
  FileText, Megaphone, Wrench, Rocket, Star, Flag,
} from 'lucide-react';

// Small fixed icon/color palette for group creation -- reused by GroupFormModal (picker),
// GroupList (row icon) and GroupHeader (workspace header icon) so all three resolve a
// group's `icon`/`color` string fields identically.
export const GROUP_ICON_MAP = {
  Users, UsersRound, Briefcase, Building2, Target, Layers,
  FileText, Megaphone, Wrench, Rocket, Star, Flag,
};

export const GROUP_ICON_OPTIONS = Object.keys(GROUP_ICON_MAP);

export const GROUP_COLOR_OPTIONS = [
  'var(--accent-indigo)',
  'var(--accent-green)',
  'var(--accent-orange)',
  'var(--accent-red)',
  'var(--accent-yellow)',
];

export const resolveGroupIcon = (iconName) => GROUP_ICON_MAP[iconName] || UsersRound;
