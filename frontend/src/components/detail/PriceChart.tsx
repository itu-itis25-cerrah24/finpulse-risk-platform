import { useId, useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { PricePoint } from "../../api/types";
import { formatDateShort, formatMoney, formatPct } from "../../lib/format";

const RANGES = [
  { label: "1M", days: 30 },
  { label: "2M", days: 60 },
  { label: "3M", days: 90 },
] as const;

type RangeLabel = (typeof RANGES)[number]["label"];

interface PriceChartProps {
  history: PricePoint[];
  currency: string | null;
  avgCost?: number | null;
}

interface TooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: PricePoint }>;
  basePrice: number;
  currency: string | null;
}

function ChartTooltip({ active, payload, basePrice, currency }: TooltipProps) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  const change = ((point.close - basePrice) / basePrice) * 100;
  return (
    <div className="rounded border border-zinc-700 bg-zinc-950/95 px-3 py-2 shadow-xl shadow-black/50 backdrop-blur">
      <div className="label mb-1">
        {new Date(`${point.date}T00:00:00`).toLocaleDateString("en-US", {
          weekday: "short",
          month: "short",
          day: "numeric",
          year: "numeric",
        })}
      </div>
      <div className="num text-sm font-semibold text-zinc-50">{formatMoney(point.close, currency)}</div>
      <div className={`num text-[11px] ${change >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
        {formatPct(change, 2, true)} vs range start
      </div>
    </div>
  );
}

export function PriceChart({ history, currency, avgCost }: PriceChartProps) {
  const [range, setRange] = useState<RangeLabel>("3M");
  const gradientId = useId().replace(/:/g, "");

  const data = useMemo(() => {
    const days = RANGES.find((r) => r.label === range)?.days ?? 90;
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - days);
    const iso = cutoff.toISOString().slice(0, 10);
    return history.filter((p) => p.date >= iso);
  }, [history, range]);

  if (data.length < 2) {
    return <div className="flex h-[280px] items-center justify-center text-sm text-zinc-500">No price history available.</div>;
  }

  const first = data[0].close;
  const last = data[data.length - 1].close;
  const up = last >= first;
  const stroke = up ? "#10b981" : "#f43f5e";

  // Include the average cost in the y-domain so the reference line is always visible.
  const closes = data.map((p) => p.close);
  const showCost = avgCost != null && avgCost > 0;
  const lo = Math.min(...closes, ...(showCost ? [avgCost] : []));
  const hi = Math.max(...closes, ...(showCost ? [avgCost] : []));
  const pad = (hi - lo) * 0.08 || hi * 0.02;

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <span className="label">Period return</span>
          <span className={`num text-xs font-semibold ${up ? "text-emerald-400" : "text-rose-400"}`}>
            {formatPct(((last - first) / first) * 100, 2, true)}
          </span>
        </div>
        <div className="flex rounded border border-zinc-800 bg-zinc-950/60 p-0.5">
          {RANGES.map((r) => (
            <button
              key={r.label}
              type="button"
              onClick={() => setRange(r.label)}
              className={`rounded-sm px-2.5 py-0.5 font-mono text-[11px] font-medium transition ${
                range === r.label ? "bg-zinc-700 text-zinc-50" : "text-zinc-500 hover:text-zinc-200"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={stroke} stopOpacity={0.28} />
                <stop offset="100%" stopColor={stroke} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#27272a" strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={formatDateShort}
              tick={{ fill: "#71717a", fontSize: 10, fontFamily: "JetBrains Mono, monospace" }}
              axisLine={{ stroke: "#3f3f46" }}
              tickLine={false}
              minTickGap={32}
            />
            <YAxis
              orientation="right"
              domain={[lo - pad, hi + pad]}
              tickFormatter={(v: number) => v.toLocaleString("en-US", { maximumFractionDigits: v >= 1000 ? 0 : 2 })}
              tick={{ fill: "#71717a", fontSize: 10, fontFamily: "JetBrains Mono, monospace" }}
              axisLine={false}
              tickLine={false}
              width={60}
            />
            <Tooltip
              content={<ChartTooltip basePrice={first} currency={currency} />}
              cursor={{ stroke: "#52525b", strokeDasharray: "3 3" }}
            />
            {showCost && (
              <ReferenceLine
                y={avgCost}
                stroke="#f59e0b"
                strokeDasharray="4 4"
                strokeOpacity={0.7}
                label={{
                  value: `AVG COST ${avgCost.toLocaleString("en-US", { maximumFractionDigits: 2 })}`,
                  position: "insideTopLeft",
                  fill: "#f59e0b",
                  fontSize: 10,
                  fontFamily: "JetBrains Mono, monospace",
                }}
              />
            )}
            <Area
              type="monotone"
              dataKey="close"
              stroke={stroke}
              strokeWidth={1.75}
              fill={`url(#${gradientId})`}
              activeDot={{ r: 3.5, stroke: "#09090b", strokeWidth: 2, fill: stroke }}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
