import { Dices, LoaderCircle } from "lucide-react";
import { useMemo, useState, type ReactElement } from "react";
import { CartesianGrid, Cell, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";

import { api } from "../../api/client";
import type { FrontierPoint, OptimalPortfolio, OptimizationResult, OptimizationTarget, RebalanceRow } from "../../api/types";
import { useApiResource } from "../../hooks/useApiResource";
import { formatMoney, formatNumber, formatPct, pnlColor } from "../../lib/format";

const SAMPLES = 4000;
const DEFAULT_SEED = 42;
const AXIS_TICK = { fill: "#71717a", fontSize: 10, fontFamily: "JetBrains Mono, monospace" };

interface MarkerSpec {
  key: "current_portfolio" | OptimizationTarget;
  label: string;
  color: string;
  shape: "diamond" | "star" | "circle";
}

const MARKERS: MarkerSpec[] = [
  { key: "current_portfolio", label: "Current", color: "#f59e0b", shape: "diamond" },
  { key: "max_sharpe", label: "Max Sharpe", color: "#10b981", shape: "star" },
  { key: "min_volatility", label: "Min Volatility", color: "#38bdf8", shape: "circle" },
];

const TARGETS: ReadonlyArray<{ value: OptimizationTarget; label: string }> = [
  { value: "max_sharpe", label: "Max Sharpe" },
  { value: "min_volatility", label: "Min Vol" },
];

/** A plotted point; `marker` is set for the three highlighted portfolios. */
interface ChartPoint extends FrontierPoint {
  marker?: MarkerSpec;
}

const shortSymbol = (symbol: string) => symbol.replace(/\.IS$/i, "");

// ---------------------------------------------------------------------------
// Sharpe colour scale: rose (low) -> amber -> emerald (high)
// ---------------------------------------------------------------------------

const SCALE: Array<[number, [number, number, number]]> = [
  [0, [244, 63, 94]],
  [0.5, [245, 158, 11]],
  [1, [16, 185, 129]],
];

function sharpeColor(value: number | null, lo: number, hi: number): string {
  if (value == null) return "#52525b";
  const t = hi > lo ? Math.min(1, Math.max(0, (value - lo) / (hi - lo))) : 0.5;
  const upper = SCALE.findIndex(([stop]) => stop >= t);
  const [s0, c0] = SCALE[Math.max(0, upper - 1)];
  const [s1, c1] = SCALE[upper];
  const f = s1 > s0 ? (t - s0) / (s1 - s0) : 0;
  const rgb = c0.map((c, i) => Math.round(c + (c1[i] - c) * f));
  return `rgb(${rgb.join(",")})`;
}

// ---------------------------------------------------------------------------
// Chart pieces
// ---------------------------------------------------------------------------

function MarkerGlyph({ cx, cy, spec }: { cx: number; cy: number; spec: MarkerSpec }): ReactElement {
  const common = { fill: spec.color, stroke: "#09090b", strokeWidth: 1.5 };
  if (spec.shape === "diamond") {
    return <path d={`M${cx},${cy - 8} L${cx + 8},${cy} L${cx},${cy + 8} L${cx - 8},${cy} Z`} {...common} />;
  }
  if (spec.shape === "star") {
    const points = Array.from({ length: 10 }, (_, i) => {
      const r = i % 2 === 0 ? 9 : 4;
      const a = (Math.PI / 5) * i - Math.PI / 2;
      return `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
    });
    return <polygon points={points.join(" ")} {...common} />;
  }
  return <circle cx={cx} cy={cy} r={6.5} {...common} />;
}

/** Glyph plus a soft halo so the marker stands out against the dense cloud. */
function MarkerShape({ cx = 0, cy = 0, spec, halo = true }: { cx?: number; cy?: number; spec: MarkerSpec; halo?: boolean }): ReactElement {
  return (
    <g>
      {halo && <circle cx={cx} cy={cy} r={13} fill={spec.color} fillOpacity={0.12} stroke={spec.color} strokeOpacity={0.6} />}
      <MarkerGlyph cx={cx} cy={cy} spec={spec} />
    </g>
  );
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: ReadonlyArray<{ payload?: ChartPoint }> }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="min-w-40 rounded border border-zinc-700 bg-zinc-950/95 px-3 py-2 shadow-xl shadow-black/50 backdrop-blur">
      <div className="label mb-1" style={point.marker ? { color: point.marker.color } : undefined}>
        {point.marker ? point.marker.label : "Sampled portfolio"}
      </div>
      {(
        [
          ["Return", formatPct(point.expected_return_pct, 2, true), pnlColor(point.expected_return_pct)],
          ["Volatility", formatPct(point.volatility_pct, 2), "text-zinc-100"],
          ["Sharpe", formatNumber(point.sharpe_ratio, 2), "text-zinc-100"],
        ] as const
      ).map(([label, value, color]) => (
        <div key={label} className="flex items-baseline justify-between gap-6 text-[11px]">
          <span className="text-zinc-500">{label}</span>
          <span className={`num font-semibold ${color}`}>{value}</span>
        </div>
      ))}
    </div>
  );
}

function FrontierChart({ result }: { result: OptimizationResult }) {
  const { lo, hi } = useMemo(() => {
    const values = result.frontier_cloud.map((p) => p.sharpe_ratio).filter((v): v is number => v != null);
    return { lo: Math.min(...values), hi: Math.max(...values) };
  }, [result.frontier_cloud]);

  return (
    <ResponsiveContainer width="100%" height="100%">
      <ScatterChart margin={{ top: 12, right: 12, bottom: 18, left: 4 }}>
        <CartesianGrid stroke="#27272a" strokeDasharray="2 4" />
        <XAxis
          type="number"
          dataKey="volatility_pct"
          name="Volatility"
          domain={["auto", "auto"]}
          tickFormatter={(v: number) => `${v.toFixed(0)}%`}
          tick={AXIS_TICK}
          axisLine={{ stroke: "#3f3f46" }}
          tickLine={false}
          label={{ value: "Annualized volatility", position: "insideBottom", offset: -10, fill: "#71717a", fontSize: 10 }}
        />
        <YAxis
          type="number"
          dataKey="expected_return_pct"
          name="Return"
          domain={["auto", "auto"]}
          tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v.toFixed(0)}%`}
          tick={AXIS_TICK}
          axisLine={false}
          tickLine={false}
          width={48}
        />
        {/* Fixed symbol area (px²) for the cloud; the highlighted markers draw their own shapes. */}
        <ZAxis range={[22, 22]} />
        <Tooltip content={<ChartTooltip />} cursor={{ stroke: "#52525b", strokeDasharray: "3 3" }} isAnimationActive={false} />

        <Scatter data={result.frontier_cloud} isAnimationActive={false} shape="circle">
          {result.frontier_cloud.map((point, i) => (
            <Cell key={i} fill={sharpeColor(point.sharpe_ratio, lo, hi)} fillOpacity={0.55} />
          ))}
        </Scatter>

        <Scatter
          data={result.efficient_frontier}
          line={{ stroke: "#e4e4e7", strokeWidth: 1.5, strokeOpacity: 0.8 }}
          shape={() => <g />}
          isAnimationActive={false}
        />

        {MARKERS.map((spec) => (
          <Scatter
            key={spec.key}
            data={[{ ...result[spec.key], marker: spec }]}
            shape={(props: unknown) => <MarkerShape {...(props as { cx?: number; cy?: number })} spec={spec} />}
            isAnimationActive={false}
          />
        ))}
      </ScatterChart>
    </ResponsiveContainer>
  );
}

function ChartLegend({ result }: { result: OptimizationResult }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {MARKERS.map((spec) => (
        <span key={spec.key} className="flex items-center gap-1.5 font-mono text-[10px] text-zinc-400">
          <svg width="14" height="14" viewBox="-9 -9 18 18" aria-hidden="true">
            <MarkerShape spec={spec} halo={false} />
          </svg>
          {spec.label}
          <span className="text-zinc-500">{formatNumber(result[spec.key].sharpe_ratio, 2)}</span>
        </span>
      ))}
      <span className="flex items-center gap-1.5 font-mono text-[10px] text-zinc-400">
        <span className="h-0.5 w-4 rounded bg-zinc-200/80" />
        Efficient frontier
      </span>
      <span className="flex items-center gap-1.5 font-mono text-[10px] text-zinc-500">
        Sharpe
        <span className="h-1.5 w-16 rounded-sm" style={{ background: "linear-gradient(to right, #f43f5e, #f59e0b, #10b981)" }} />
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rebalancing
// ---------------------------------------------------------------------------

function TradeBadge({ row }: { row: RebalanceRow }) {
  const tone =
    row.action === "BUY"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
      : row.action === "SELL"
        ? "border-rose-500/30 bg-rose-500/10 text-rose-400"
        : "border-zinc-700 bg-zinc-800/40 text-zinc-400";
  return (
    <span className={`num inline-flex items-center gap-1.5 rounded border px-1.5 py-px text-[11px] font-semibold ${tone}`}>
      <span className="text-[9px] tracking-wider">{row.action}</span>
      {row.action !== "HOLD" && formatMoney(Math.abs(row.delta_usd), "USD")}
    </span>
  );
}

function StatCompare({ label, current, target, format, better }: {
  label: string;
  current: number | null;
  target: number | null;
  format: (v: number | null) => string;
  better: "higher" | "lower";
}) {
  const delta = current != null && target != null ? target - current : null;
  const improved = delta != null && (better === "higher" ? delta > 0 : delta < 0);
  return (
    <div className="rounded border border-zinc-800 bg-zinc-950/40 px-2.5 py-1.5">
      <div className="label">{label}</div>
      <div className="num mt-0.5 text-sm font-semibold text-zinc-50">{format(target)}</div>
      <div className="num text-[10px] text-zinc-500">
        from {format(current)}
        {delta != null && Math.abs(delta) > 0.005 && (
          <span className={`ml-1 ${improved ? "text-emerald-400" : "text-rose-400"}`}>
            ({delta > 0 ? "+" : ""}
            {delta.toFixed(2)})
          </span>
        )}
      </div>
    </div>
  );
}

function RebalancePanel({ result }: { result: OptimizationResult }) {
  const [target, setTarget] = useState<OptimizationTarget>("max_sharpe");
  const rows = result.rebalancing[target];
  const goal: OptimalPortfolio = result[target];
  const current = result.current_portfolio;
  const turnover = rows.reduce((sum, r) => sum + Math.max(0, r.delta_usd), 0);

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <span className="label">Rebalance to</span>
        <div className="flex rounded border border-zinc-800 bg-zinc-950/60 p-0.5">
          {TARGETS.map((t) => (
            <button
              key={t.value}
              type="button"
              onClick={() => setTarget(t.value)}
              aria-pressed={target === t.value}
              className={`rounded-sm px-2.5 py-0.5 font-mono text-[11px] font-medium transition ${
                target === t.value ? "bg-zinc-700 text-zinc-50" : "text-zinc-500 hover:text-zinc-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <StatCompare label="Return" current={current.expected_return_pct} target={goal.expected_return_pct} format={(v) => formatPct(v, 2, true)} better="higher" />
        <StatCompare label="Volatility" current={current.volatility_pct} target={goal.volatility_pct} format={(v) => formatPct(v, 2)} better="lower" />
        <StatCompare label="Sharpe" current={current.sharpe_ratio} target={goal.sharpe_ratio} format={(v) => formatNumber(v, 2)} better="higher" />
      </div>

      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-zinc-800 text-right">
            <th className="label py-1.5 text-left font-medium">Ticker</th>
            <th className="label py-1.5 font-medium">Current</th>
            <th className="label py-1.5 font-medium">Target</th>
            <th className="label py-1.5 font-medium">Δ</th>
            <th className="label py-1.5 font-medium">Trade</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.symbol} className="border-b border-zinc-800/60">
              <td className="py-1.5 pr-2">
                <div className="font-mono text-xs font-semibold text-zinc-100">{shortSymbol(row.symbol)}</div>
                {/* Current (grey) vs target (coloured) weight bars */}
                <div className="mt-1 w-20 space-y-0.5">
                  <div className="h-0.5 rounded bg-zinc-600" style={{ width: `${row.current_weight_pct}%` }} />
                  <div
                    className={`h-0.5 rounded ${target === "max_sharpe" ? "bg-emerald-500" : "bg-sky-400"}`}
                    style={{ width: `${row.target_weight_pct}%` }}
                  />
                </div>
              </td>
              <td className="num py-1.5 pr-2 text-right text-xs text-zinc-400">{formatPct(row.current_weight_pct, 1)}</td>
              <td className="num py-1.5 pr-2 text-right text-xs text-zinc-100">{formatPct(row.target_weight_pct, 1)}</td>
              <td className={`num py-1.5 pr-2 text-right text-xs font-medium ${pnlColor(row.delta_weight_pct)}`}>
                {formatPct(row.delta_weight_pct, 1, true)}
              </td>
              <td className="py-1.5 text-right">
                <TradeBadge row={row} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="flex justify-between text-[10px] text-zinc-500">
        <span>One-way turnover</span>
        <span className="num text-zinc-300">
          {formatMoney(turnover, "USD")} · {formatPct((turnover / result.total_value_usd) * 100, 1)} of book
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

export function OptimizerPanel({ refreshKey }: { refreshKey: unknown }) {
  const [seed, setSeed] = useState<number>(DEFAULT_SEED);
  const { data, loading, error } = useApiResource((signal) => api.getOptimization(SAMPLES, seed, signal), [seed, refreshKey]);

  return (
    <section className="panel flex min-w-0 flex-col">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <h3 className="panel-title">Portfolio Optimizer · Markowitz MPT</h3>
          {loading && <LoaderCircle className="h-3 w-3 animate-spin text-zinc-500" />}
        </div>
        <button
          type="button"
          onClick={() => setSeed(Math.floor(Math.random() * 1_000_000))}
          title="Re-sample the simplex with a new random seed"
          className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-2 py-1 font-mono text-[11px] text-zinc-400 transition hover:border-zinc-500 hover:text-zinc-200"
        >
          <Dices className="h-3.5 w-3.5" />
          Re-sample
        </button>
      </header>

      <div className="p-4">
        {error ? (
          <div className="flex h-[340px] items-center justify-center px-6 text-center text-sm text-rose-400">{error}</div>
        ) : !data ? (
          <div className="h-[340px] animate-pulse rounded bg-zinc-800/30" />
        ) : (
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-12">
            <div className="min-w-0 lg:col-span-7">
              <ChartLegend result={data} />
              <div className="mt-2 h-[320px]">
                <FrontierChart result={data} />
              </div>
            </div>
            <div className="min-w-0 lg:col-span-5">
              <RebalancePanel result={data} />
            </div>
            <div className="num border-t border-zinc-800 pt-2 text-[10px] text-zinc-600 lg:col-span-12">
              {data.samples.toLocaleString("en-US")} long-only portfolios (Dirichlet simplex sampling + anchors) · annualized USD log-returns, n=
              {data.observations} ({data.start_date} → {data.end_date}) · rf {formatPct(data.risk_free_rate_pct, 1)} · seed {data.seed ?? "random"}
              {data.covariance_jitter > 0 && ` · jitter ${data.covariance_jitter.toExponential(1)}`}
              {data.excluded_symbols.length > 0 && ` · excluded: ${data.excluded_symbols.join(", ")}`}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
