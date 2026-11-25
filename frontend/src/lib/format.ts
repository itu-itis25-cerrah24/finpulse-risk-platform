import type { AlertSeverity, RiskLevel, SentimentLabel } from "../api/types";

const DASH = "—";

const currencyFormatters = new Map<string, Intl.NumberFormat>();

function currencyFormatter(currency: string, compact: boolean): Intl.NumberFormat {
  const key = `${currency}:${compact}`;
  let formatter = currencyFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      notation: compact ? "compact" : "standard",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    currencyFormatters.set(key, formatter);
  }
  return formatter;
}

export function formatMoney(value: number | null | undefined, currency: string | null = "USD", compact = false): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  try {
    return currencyFormatter(currency ?? "USD", compact).format(value);
  } catch {
    // Unknown ISO code (e.g. Yahoo's "GBp") – fall back to plain number + code.
    return `${formatNumber(value)} ${currency ?? ""}`.trim();
  }
}

export function formatSignedMoney(value: number | null | undefined, currency: string | null = "USD"): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${formatMoney(Math.abs(value), currency)}`;
}

export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function formatPct(value: number | null | undefined, digits = 2, signed = false): string {
  if (value == null || !Number.isFinite(value)) return DASH;
  const sign = signed && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function formatDateShort(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00`);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function formatRelativeTime(iso: string): string {
  // SQLite returns naive UTC timestamps; treat missing offsets as UTC.
  const hasZone = /([zZ]|[+-]\d\d:?\d\d)$/.test(iso);
  const then = new Date(hasZone ? iso : `${iso}Z`).getTime();
  const seconds = Math.round((Date.now() - then) / 1000);
  if (!Number.isFinite(seconds)) return DASH;
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

// ---------------------------------------------------------------------------
// Semantic colors
// ---------------------------------------------------------------------------

/** Emerald for gains, rose for losses, neutral zinc for flat / unknown. */
export function pnlColor(value: number | null | undefined): string {
  if (value == null || value === 0) return "text-zinc-400";
  return value > 0 ? "text-emerald-400" : "text-rose-400";
}

export interface RiskTone {
  text: string;
  bar: string;
  hex: string;
}

export function riskTone(score: number | null | undefined): RiskTone {
  if (score == null) return { text: "text-zinc-400", bar: "bg-zinc-600", hex: "#71717a" };
  if (score < 35) return { text: "text-emerald-400", bar: "bg-emerald-500", hex: "#10b981" };
  if (score < 65) return { text: "text-amber-400", bar: "bg-amber-500", hex: "#f59e0b" };
  return { text: "text-rose-400", bar: "bg-rose-500", hex: "#f43f5e" };
}

export function riskLevelLabel(level: RiskLevel | null | undefined): string {
  return level ?? "N/A";
}

export const sentimentStyles: Record<SentimentLabel, string> = {
  BULLISH: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
  BEARISH: "border-rose-500/30 bg-rose-500/10 text-rose-400",
  NEUTRAL: "border-zinc-600/50 bg-zinc-700/20 text-zinc-400",
};

export const severityStyles: Record<AlertSeverity, string> = {
  CRITICAL: "border-rose-500/50 bg-rose-500/20 text-rose-300",
  HIGH: "border-rose-500/30 bg-rose-500/10 text-rose-400",
  MEDIUM: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  LOW: "border-sky-500/30 bg-sky-500/10 text-sky-400",
};

export const severityAccent: Record<AlertSeverity, string> = {
  CRITICAL: "bg-rose-500",
  HIGH: "bg-rose-500/70",
  MEDIUM: "bg-amber-500",
  LOW: "bg-sky-500",
};
