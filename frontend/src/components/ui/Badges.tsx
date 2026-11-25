import type { AlertSeverity, SentimentLabel } from "../../api/types";
import { riskTone, sentimentStyles, severityStyles } from "../../lib/format";

const badgeBase =
  "inline-flex items-center rounded-sm border px-1.5 py-0.5 font-mono text-[10px] font-semibold tracking-wider";

export function SentimentBadge({ label }: { label: SentimentLabel }) {
  return <span className={`${badgeBase} ${sentimentStyles[label]}`}>{label}</span>;
}

export function SeverityBadge({ severity }: { severity: AlertSeverity }) {
  return <span className={`${badgeBase} ${severityStyles[severity]}`}>{severity}</span>;
}

/** Compact horizontal bar + number used for 0-100 risk scores. */
export function RiskScoreBar({ score, width = "w-16" }: { score: number; width?: string }) {
  const tone = riskTone(score);
  return (
    <div className="flex items-center gap-2">
      <div className={`h-1.5 ${width} overflow-hidden rounded-full bg-zinc-800`}>
        <div className={`h-full rounded-full ${tone.bar}`} style={{ width: `${Math.min(100, Math.max(0, score))}%` }} />
      </div>
      <span className={`num w-8 text-right text-xs font-semibold ${tone.text}`}>{score.toFixed(0)}</span>
    </div>
  );
}
