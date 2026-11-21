/** One item per line; surrounding spaces trimmed and blank lines dropped. */
export function toList(text: string): string[] | null {
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  // An empty list is sent as null so the value is actually removed on the server.
  return lines.length > 0 ? lines : null;
}

export const fromList = (list: string[] | null | undefined): string => (list ?? []).join("\n");

/** Blank text becomes null so a cleared field is removed rather than stored as "". */
export const textOrNull = (text: string): string | null => text.trim() || null;
