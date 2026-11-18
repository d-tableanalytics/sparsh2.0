import React from 'react';
import { MapPin, ExternalLink } from 'lucide-react';

/**
 * Where a self check-in / check-out was made (`self_in` / `self_out` on the day record).
 *
 * Everyone who can see the row gets the office the punch was matched to and how far from it.
 * The exact pin — coordinates and GPS accuracy — is sent by the server to HR / MD / Admin
 * only (hrms_attendance_service._shape_punch_locations); when it is present this adds a
 * "Map" link so they can review exactly where attendance was marked from.
 */
const hasExactPin = (loc) => loc && loc.lat != null && loc.lng != null;

const mapUrl = (loc) => `https://www.google.com/maps?q=${loc.lat},${loc.lng}`;

const placeText = (loc) => {
  if (!loc) return null;
  const parts = [loc.office || 'Unknown office'];
  if (loc.distance_m != null) parts.push(`${loc.distance_m} m away`);
  return parts.join(' · ');
};

/** One punch: "In · Head Office · 35 m away  [Map]". Renders nothing for a missing punch. */
export const PunchPlace = ({ label, loc, detailed = false }) => {
  if (!loc) return null;
  const exact = hasExactPin(loc);
  return (
    <span className="inline-flex flex-wrap items-center gap-1 text-[11.5px] text-[var(--text-main)]">
      <MapPin size={11} className="shrink-0 text-[var(--accent-indigo)]" />
      {label && <b className="font-semibold">{label}</b>}
      <span>{placeText(loc)}</span>
      {detailed && exact && (
        <span className="text-[var(--text-muted)]">
          · {Number(loc.lat).toFixed(5)}, {Number(loc.lng).toFixed(5)}
          {loc.accuracy_m != null ? ` (±${loc.accuracy_m} m)` : ''}
        </span>
      )}
      {exact && (
        <a href={mapUrl(loc)} target="_blank" rel="noopener noreferrer"
          title="Open the exact check-in point in Google Maps"
          className="inline-flex items-center gap-0.5 font-bold text-[var(--accent-indigo)] hover:underline">
          Map <ExternalLink size={10} />
        </a>
      )}
    </span>
  );
};

/** Both punches of a day, stacked; a dash when neither was a self check-in. */
const PunchLocation = ({ row }) => {
  if (!row?.self_in && !row?.self_out) {
    return (
      <span className="text-[11.5px] text-[var(--text-muted)]"
        title="Not a self check-in — marked by HR, biometric or import, so no location was recorded">
        —
      </span>
    );
  }
  return (
    <div className="flex flex-col items-start gap-0.5">
      <PunchPlace label="In" loc={row.self_in} />
      <PunchPlace label="Out" loc={row.self_out} />
    </div>
  );
};

export default PunchLocation;
