export const WAKE_PATTERN = /\b(?:hey|ok(?:ay)?|hi|hello|excuse me)\b(?:\s+|,\s*)+sight[\s-]?guide\b/i;

export const CANCEL_PATTERN = /\b(?:stop(?!\s+(?:at|by|over|here)\b)|cancel|never\s*mind|abort|pause|be\s+quiet|shut\s+up|quiet)\b/i;

export function matchesWakeWord(text: string): boolean {
  const clean = (text || "").trim();
  if (!clean) return false;
  return WAKE_PATTERN.test(clean);
}

/** Text after the wake phrase when wake word and command arrive in one utterance. */
export function extractWakeCommand(text: string): string | null {
  const match = WAKE_PATTERN.exec(text || "");
  if (!match) return null;
  let rest = (text || "").slice(match.index + match[0].length).trim();
  rest = rest.replace(/^[,.\s]+/, "").trim();
  if (rest.length < 2) return null;
  return rest;
}

export function matchesCancelPhrase(text: string): boolean {
  const clean = (text || "").trim();
  if (!clean) return false;
  if (clean.length > 40 && !CANCEL_PATTERN.test(clean)) return false;
  const match = CANCEL_PATTERN.exec(clean);
  if (!match) return false;
  return clean.length <= 40;
}

/** Join final transcripts into a single command string. */
export function joinFinalTranscripts(records: Array<{ transcript: string; isFinal: boolean }>): string {
  return records
    .filter((record) => record.isFinal)
    .map((record) => record.transcript.trim())
    .filter(Boolean)
    .join(" ")
    .trim();
}