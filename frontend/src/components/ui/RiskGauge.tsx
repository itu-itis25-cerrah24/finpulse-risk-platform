import { riskTone } from "../../lib/format";

interface RiskGaugeProps {
  score: number | null;
  size?: number;
}

/**
 * Semicircular 0-100 gauge. The arc uses `pathLength=100` so the dash length
 * maps 1:1 to the score without any trigonometry.
 */
export function RiskGauge({ score, size = 96 }: RiskGaugeProps) {
  const tone = riskTone(score);
  const value = score == null ? 0 : Math.min(100, Math.max(0, score));
  const arc = "M 8 50 A 42 42 0 0 1 92 50";

  return (
    <svg width={size} height={size * 0.58} viewBox="0 0 100 58" role="img" aria-label={`Risk score ${value.toFixed(0)} of 100`}>
      <path d={arc} fill="none" stroke="#27272a" strokeWidth="8" strokeLinecap="round" pathLength={100} />
      <path
        d={arc}
        fill="none"
        stroke={tone.hex}
        strokeWidth="8"
        strokeLinecap="round"
        pathLength={100}
        strokeDasharray={`${value} 100`}
        style={{ transition: "stroke-dasharray 600ms ease" }}
      />
      {/* Zone separators at the LOW / MODERATE / HIGH boundaries (35 and 65). */}
      <path d={arc} fill="none" stroke="#18181b" strokeWidth="9" pathLength={100} strokeDasharray="0 34.6 0.8 29.2 0.8 100" />
      <text x="50" y="49" textAnchor="middle" className="font-mono" fontSize="17" fontWeight="600" fill={tone.hex}>
        {score == null ? "—" : value.toFixed(0)}
      </text>
    </svg>
  );
}
