export function formatPercent(value: number | null, signed = true, decimals = 2): string {
  if (value === null) return "—";
  const factor = 10 ** decimals;
  const rounded = Math.round((value + Number.EPSILON) * factor) / factor;
  const normalized = Object.is(rounded, -0) || rounded === 0 ? 0 : rounded;
  const sign = signed && normalized > 0 ? "+" : "";
  return `${sign}${normalized.toFixed(decimals)}%`;
}
