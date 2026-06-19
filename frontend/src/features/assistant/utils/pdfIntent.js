/**
 * Detects whether a user message is asking to export the current chat as a PDF,
 * in either English or (romanized/Devanagari) Hindi.
 *
 * Kept deliberately conservative: it requires both a "PDF" mention AND an
 * action/target cue ("this chat", "is chat", "conversation", "banao",
 * "download" …) so ordinary messages that merely mention a PDF file aren't
 * hijacked. The core chat flow only diverts when this returns true.
 */

// Must mention a PDF.
const PDF_RE = /\bpdf\b|पीडीएफ|पी\.?डी\.?एफ/i;

// Must reference the current chat / conversation (EN + Hindi).
const CHAT_TARGET_RE =
  /\b(this|current|our|is|yeh|ye)\b.*\b(chat|conversation|baat\s?cheet|baatcheet)\b|\bchat\b|conversation|बातचीत|चैट|वार्तालाप|is\s*chat|yeh\s*chat|ye\s*chat/i;

// Must express an export/create/download action (EN + romanized + Devanagari Hindi).
const ACTION_RE =
  /\b(make|create|generate|export|download|save|get|give)\b|bana\s?do|banado|banaa?o|banaye|banaiye|nikal\s?do|nikalo|de\s?do|chahiye|बना\s*दो|बनाओ|बनाइए|डाउनलोड|निकाल|दे\s*दो|चाहिए/i;

/**
 * @param {string} text raw user message
 * @returns {boolean} true if the message is a "export this chat to PDF" intent
 */
export function isPdfExportIntent(text) {
  const t = (text || '').trim();
  if (!t || t.length > 200) return false; // long messages are almost never this command
  if (!PDF_RE.test(t)) return false;
  // Either an explicit action or an explicit chat-target makes it unambiguous
  // enough alongside the PDF mention.
  return ACTION_RE.test(t) || CHAT_TARGET_RE.test(t);
}

export default isPdfExportIntent;
