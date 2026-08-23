export function formatDate(value: string, includeTime = false): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Unknown date";
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(includeTime ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" } : {}),
    timeZone: "UTC",
  }).format(date);
}

export function formatReaction(value: number): string {
  const sign = value > 0 ? "+" : "";
  const precision = Math.abs(value) >= 10 ? 1 : 2;
  return `${sign}${value.toFixed(precision)}%`;
}

export function reactionTone(value: number): string {
  if (value > 0) return "text-emerald-300";
  if (value < 0) return "text-rose-300";
  return "text-slate-300";
}

export function formatImportance(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function safeExternalUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}
