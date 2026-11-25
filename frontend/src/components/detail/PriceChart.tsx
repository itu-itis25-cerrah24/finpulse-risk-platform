import { GitCompareArrows, LoaderCircle } from "lucide-react";
import { useId, useMemo, useState, type ReactNode } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../../api/client";
import type { BenchmarkComparison, BenchmarkPoint, PricePoint } from "../../api/types";
import { useApiResource } from "../../hooks/useApiResource";
import { formatDateShort, formatMoney, formatNumber, formatPct, pnlColor } from "../../lib/format";

const RANGES = [
  { label: "1M", days: 30 },
  { label: "2M", days: 60 },
  { label: "3M", days: 90 },
] as const;

type RangeLabel = (typeof RANGES)[number]["label"];

const ASSET_COLOR = "#38bdf8"; // sky-400: the selected stock in compare mode
const BENCHMARK_COLOR = "#f59e0b"; // amber-500: the index
const AXIS_TICK = { fill: "#71717a", fontSize: 10, fontFamily: "JetBrains Mono, monospace" };
const CHART_HEIGHT = "h-[280px]";

/** Mirrors the backend rule in risk_engine.benchmark_for_symbol. */
const benchmarkFor = (symbol: string) => (symbol.toUpperCase().endsWith(".IS") ? "XU100.IS" : "SPY");

interface PriceChartProps {
  symbol: string;
  history: PricePoint[];
  currency: string | null;
  avgCost?: number | null;
}

// ---------------------------------------------------------------------------
// Tooltips
// ---------------------------------------------------------------------------

interface TooltipBase<T> {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: T }>;
}

function TooltipShell({ date, children }: { date: string; children: ReactNode }) {
  return (
    <div className="rounded border border-zinc-700 bg-zinc-950/95 px-3 py-2 shadow-xl shadow-black/50 backdrop-blur">
      <div className="label mb-1">
        {new Date(`${date}T00:00:00`).toLocaleDateString("en-US", {
          weekday: "short",
          month: "short",
          day: "numeric",
          year: "numeric",
        })}
      </div>
      {children}
    </div>
  );
}

function PriceTooltip({ active, payload, basePrice, currency }: TooltipBase<PricePoint> & { basePrice: number; currency: string | null }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  const change = ((point.close - basePrice) / basePrice) * 100;
  return (
    <TooltipShell date={point.date}>
      <div className="num text-sm font-semibold text-zinc-50">{formatMoney(point.close, currency)}</div>
      <div className={`num text-[11px] ${pnlColor(change)}`}>{formatPct(change, 2, true)} vs range start</div>
    </TooltipShell>
  );
}

function CompareTooltip({ active, payload, symbol, benchmark }: TooltipBase<BenchmarkPoint> & { symbol: string; benchmark: string }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  const spread = point.asset_pct - point.benchmark_pct;
  const row = (color: string, label: string, value: number) => (
    <div className="flex items-center justify-between gap-6">
      <span className="flex items-center gap-1.5 font-mono text-[11px] text-zinc-300">
        <span className="h-2 w-2 rounded-sm" style={{ background: color }} />
        {label}
      </span>
      <span className={`num text-xs font-semibold ${pnlColor(value)}`}>{formatPct(value, 2, true)}</span>
    </div>
  );
  return (
    <TooltipShell date={point.date}>
      <div className="space-y-0.5">
        {row(ASSET_COLOR, symbol, point.asset_pct)}
        {row(BENCHMARK_COLOR, benchmark, point.benchmark_pct)}
      </div>
      <div className="mt-1 flex justify-between border-t border-zinc-800 pt-1 text-[11px]">
        <span className="text-zinc-500">Spread</span>
        <span className={`num font-semibold ${pnlColor(spread)}`}>{formatPct(spread, 2, true)}</span>
      </div>
    </TooltipShell>
  );
}

// ---------------------------------------------------------------------------
// Chart bodies
// ---------------------------------------------------------------------------

function PriceArea({ data, currency, avgCost }: { data: PricePoint[]; currency: string | null; avgCost?: number | null }) {
  const gradientId = useId().replace(/:/g, "");
  const first = data[0].close;
  const up = data[data.length - 1].close >= first;
  const stroke = up ? "#10b981" : "#f43f5e";

  // Include the average cost in the y-domain so the reference line is always visible.
  const showCost = avgCost != null && avgCost > 0;
  const closes = data.map((p) => p.close);
  const lo = Math.min(...closes, ...(showCost ? [avgCost] : []));
  const hi = Math.max(...closes, ...(showCost ? [avgCost] : []));
  const pad = (hi - lo) * 0.08 || hi * 0.02;

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity={0.28} />
            <stop offset="100%" stopColor={stroke} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#27272a" strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="date" tickFormatter={formatDateShort} tick={AXIS_TICK} axisLine={{ stroke: "#3f3f46" }} tickLine={false} minTickGap={32} />
        <YAxis
          orientation="right"
          domain={[lo - pad, hi + pad]}
          tickFormatter={(v: number) => v.toLocaleString("en-US", { maximumFractionDigits: v >= 1000 ? 0 : 2 })}
          tick={AXIS_TICK}
          axisLine={false}
          tickLine={false}
          width={60}
        />
        <Tooltip content={<PriceTooltip basePrice={first} currency={currency} />} cursor={{ stroke: "#52525b", strokeDasharray: "3 3" }} />
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
  );
}

function CompareChart({ comparison }: { comparison: BenchmarkComparison }) {
  const gradientId = useId().replace(/:/g, "");
  const values = comparison.points.flatMap((p) => [p.asset_pct, p.benchmark_pct]);
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const pad = (hi - lo) * 0.08 || 1;

  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={comparison.points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={ASSET_COLOR} stopOpacity={0.22} />
            <stop offset="100%" stopColor={ASSET_COLOR} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#27272a" strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="date" tickFormatter={formatDateShort} tick={AXIS_TICK} axisLine={{ stroke: "#3f3f46" }} tickLine={false} minTickGap={32} />
        <YAxis
          orientation="right"
          domain={[lo - pad, hi + pad]}
          tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v.toFixed(0)}%`}
          tick={AXIS_TICK}
          axisLine={false}
          tickLine={false}
          width={48}
        />
        <Tooltip
          content={<CompareTooltip symbol={comparison.symbol} benchmark={comparison.benchmark_symbol} />}
          cursor={{ stroke: "#52525b", strokeDasharray: "3 3" }}
        />
        <ReferenceLine y={0} stroke="#52525b" strokeWidth={1} />
        <Area
          type="monotone"
          dataKey="asset_pct"
          name={comparison.symbol}
          stroke={ASSET_COLOR}
          strokeWidth={1.75}
          fill={`url(#${gradientId})`}
          activeDot={{ r: 3.5, stroke: "#09090b", strokeWidth: 2, fill: ASSET_COLOR }}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="benchmark_pct"
          name={comparison.benchmark_symbol}
          stroke={BENCHMARK_COLOR}
          strokeWidth={1.5}
          strokeDasharray="5 3"
          dot={false}
          activeDot={{ r: 3, stroke: "#09090b", strokeWidth: 2, fill: BENCHMARK_COLOR }}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function CompareLegend({ comparison }: { comparison: BenchmarkComparison }) {
  const stat = (label: string, value: string, className = "text-zinc-200") => (
    <span className="flex items-baseline gap-1.5">
      <span className="label">{label}</span>
      <span className={`num text-xs font-semibold ${className}`}>{value}</span>
    </span>
  );
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
      <span className="flex items-center gap-1.5">
        <span className="h-0.5 w-4 rounded" style={{ background: ASSET_COLOR }} />
        <span className="font-mono text-[11px] text-zinc-300">{comparison.symbol}</span>
        <span className={`num text-xs font-semibold ${pnlColor(comparison.asset_return_pct)}`}>
          {formatPct(comparison.asset_return_pct, 2, true)}
        </span>
      </span>
      <span className="flex items-center gap-1.5">
        <span className="w-4 border-t-2 border-dashed" style={{ borderColor: BENCHMARK_COLOR }} />
        <span className="font-mono text-[11px] text-zinc-300">{comparison.benchmark_symbol}</span>
        <span className={`num text-xs font-semibold ${pnlColor(comparison.benchmark_return_pct)}`}>
          {formatPct(comparison.benchmark_return_pct, 2, true)}
        </span>
      </span>
      {stat("Excess", formatPct(comparison.excess_return_pct, 2, true), pnlColor(comparison.excess_return_pct))}
      {stat("β", formatNumber(comparison.beta, 2))}
      {stat("ρ", formatNumber(comparison.correlation, 2))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export function PriceChart({ symbol, history, currency, avgCost }: PriceChartProps) {
  const [range, setRange] = useState<RangeLabel>("3M");
  const [compare, setCompare] = useState(false);
  const days = RANGES.find((r) => r.label === range)?.days ?? 90;
  const benchmark = benchmarkFor(symbol);

  const priceData = useMemo(() => {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - days);
    const iso = cutoff.toISOString().slice(0, 10);
    return history.filter((p) => p.date >= iso);
  }, [history, days]);

  const comparison = useApiResource(
    compare ? (signal) => api.getBenchmark(symbol, days, signal) : null,
    [compare, symbol, days],
  );

  const priceReturn =
    priceData.length >= 2 ? ((priceData[priceData.length - 1].close - priceData[0].close) / priceData[0].close) * 100 : null;

  let body: ReactNode;
  if (compare) {
    if (comparison.error) {
      body = <div className="flex h-full items-center justify-center text-sm text-rose-400">{comparison.error}</div>;
    } else if (comparison.data && comparison.data.points.length >= 2) {
      body = <CompareChart comparison={comparison.data} />;
    } else if (comparison.data) {
      body = <div className="flex h-full items-center justify-center text-sm text-zinc-500">Not enough overlapping data with {benchmark}.</div>;
    } else {
      body = <div className="h-full animate-pulse rounded bg-zinc-800/30" />;
    }
  } else if (priceData.length >= 2) {
    body = <PriceArea data={priceData} currency={currency} avgCost={avgCost} />;
  } else {
    body = <div className="flex h-full items-center justify-center text-sm text-zinc-500">No price history available.</div>;
  }

  return (
    <div>
      <div className="mb-2 flex min-h-7 flex-wrap items-center justify-between gap-2">
        {compare ? (
          comparison.data ? (
            <CompareLegend comparison={comparison.data} />
          ) : (
            <span className="label">Cumulative return vs {benchmark}</span>
          )
        ) : (
          <div className="flex items-baseline gap-2">
            <span className="label">Period return</span>
            <span className={`num text-xs font-semibold ${pnlColor(priceReturn)}`}>{formatPct(priceReturn, 2, true)}</span>
          </div>
        )}

        <div className="flex items-center gap-2">
          {comparison.loading && <LoaderCircle className="h-3.5 w-3.5 animate-spin text-zinc-500" />}
          <button
            type="button"
            onClick={() => setCompare((value) => !value)}
            aria-pressed={compare}
            className={`inline-flex items-center gap-1.5 rounded border px-2.5 py-1 font-mono text-[11px] font-medium transition ${
              compare
                ? "border-amber-500/50 bg-amber-500/10 text-amber-300"
                : "border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200"
            }`}
            title={`Compare cumulative return against ${benchmark}`}
          >
            <GitCompareArrows className="h-3.5 w-3.5" />
            Compare vs {benchmark}
          </button>
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
      </div>

      <div className={CHART_HEIGHT}>{body}</div>
    </div>
  );
}
