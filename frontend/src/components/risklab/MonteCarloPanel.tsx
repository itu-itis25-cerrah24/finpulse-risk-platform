import { Dices, LoaderCircle } from "lucide-react";
import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import {
  Area,
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
import type { DriftModel, MonteCarloBand, MonteCarloResult } from "../../api/types";
import { useApiResource } from "../../hooks/useApiResource";
import { formatMoney, formatNumber, formatPct, pnlColor } from "../../lib/format";

const HORIZONS = [
  { label: "30D", days: 30 },
  { label: "90D", days: 90 },
  { label: "180D", days: 180 },
] as const;

const DRIFTS: ReadonlyArray<{ value: DriftModel; label: string; title: string }> = [
  { value: "historical", label: "Hist μ", title: "Drift = historical mean log-return" },
  { value: "zero", label: "Zero μ", title: "Zero drift: only volatility and correlation drive the fan" },
];

const SIMULATIONS = 1000;
const DEFAULT_SEED = 42;
const MEDIAN_COLOR = "#38bdf8"; // sky-400
const BAND_COLOR = "#0ea5e9"; // sky-500
const TAIL_COLOR = "#f43f5e"; // rose-500: the p5 (VaR) edge
const START_COLOR = "#f59e0b"; // amber-500: today's value
const AXIS_TICK = { fill: "#71717a", fontSize: 10, fontFamily: "JetBrains Mono, monospace" };

interface FanRow {
  day: number;
  outer: [number, number];
  inner: [number, number];
  p50: number;
  p5: number;
  band: MonteCarloBand;
}

const compactUsd = (value: number) => formatMoney(value, "USD", true);

/** Round axis ticks (1/2/2.5/5 × 10ⁿ steps) that enclose [lo, hi]. */
function niceTicks(lo: number, hi: number, target = 5): number[] {
  const span = hi - lo || Math.abs(hi) || 1;
  const raw = span / target;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 2, 2.5, 5, 10].find((m) => m * magnitude >= raw) ?? 10) * magnitude;
  const start = Math.floor(lo / step) * step;
  const ticks: number[] = [];
  for (let value = start; value < hi + step; value += step) ticks.push(Number(value.toFixed(6)));
  return ticks;
}

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

function Segmented<T extends string | number>({
  options,
  value,
  onChange,
}: {
  options: ReadonlyArray<{ value: T; label: string; title?: string }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex rounded border border-zinc-800 bg-zinc-950/60 p-0.5">
      {options.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          title={option.title}
          onClick={() => onChange(option.value)}
          aria-pressed={value === option.value}
          className={`rounded-sm px-2.5 py-0.5 font-mono text-[11px] font-medium transition ${
            value === option.value ? "bg-zinc-700 text-zinc-50" : "text-zinc-500 hover:text-zinc-200"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function Kpi({ label, value, sub, valueClass = "text-zinc-50" }: { label: string; value: string; sub: ReactNode; valueClass?: string }) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-950/40 px-3 py-2">
      <div className="label">{label}</div>
      <div className={`num mt-0.5 text-lg leading-tight font-semibold ${valueClass}`}>{value}</div>
      <div className="mt-0.5 text-[11px] text-zinc-500">{sub}</div>
    </div>
  );
}

function FanTooltip({ active, payload, initial }: { active?: boolean; payload?: ReadonlyArray<{ payload?: FanRow }>; initial: number }) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  const lines: Array<[string, number, string]> = [
    ["p95", row.band.p95, "text-zinc-300"],
    ["p75", row.band.p75, "text-zinc-300"],
    ["p50", row.band.p50, "text-sky-300"],
    ["p25", row.band.p25, "text-zinc-300"],
    ["p5", row.band.p5, "text-rose-300"],
  ];
  return (
    <div className="min-w-44 rounded border border-zinc-700 bg-zinc-950/95 px-3 py-2 shadow-xl shadow-black/50 backdrop-blur">
      <div className="label mb-1">{row.day === 0 ? "Today" : `Day +${row.day}`}</div>
      {lines.map(([label, value, color]) => {
        const change = (value / initial - 1) * 100;
        return (
          <div key={label} className="flex items-baseline justify-between gap-4">
            <span className={`font-mono text-[11px] ${color}`}>{label}</span>
            <span className="num text-xs text-zinc-100">{formatMoney(value, "USD")}</span>
            <span className={`num w-14 text-right text-[11px] ${pnlColor(change)}`}>{formatPct(change, 1, true)}</span>
          </div>
        );
      })}
    </div>
  );
}

function FanChart({ result }: { result: MonteCarloResult }) {
  const rows = useMemo<FanRow[]>(
    () =>
      result.bands.map((band) => ({
        day: band.day,
        outer: [band.p5, band.p95],
        inner: [band.p25, band.p75],
        p50: band.p50,
        p5: band.p5,
        band,
      })),
    [result.bands],
  );
  const ticks = useMemo(
    () => niceTicks(Math.min(...result.bands.map((b) => b.p5)), Math.max(...result.bands.map((b) => b.p95))),
    [result.bands],
  );

  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="#27272a" strokeDasharray="2 4" vertical={false} />
        <XAxis
          dataKey="day"
          type="number"
          domain={[0, result.horizon_days]}
          tickFormatter={(d: number) => (d === 0 ? "T0" : `+${d}d`)}
          tick={AXIS_TICK}
          axisLine={{ stroke: "#3f3f46" }}
          tickLine={false}
          minTickGap={28}
        />
        <YAxis
          orientation="right"
          domain={[ticks[0], ticks[ticks.length - 1]]}
          ticks={ticks}
          tickFormatter={compactUsd}
          tick={AXIS_TICK}
          axisLine={false}
          tickLine={false}
          width={64}
        />
        <Tooltip content={<FanTooltip initial={result.initial_value} />} cursor={{ stroke: "#52525b", strokeDasharray: "3 3" }} />
        <ReferenceLine y={result.initial_value} stroke={START_COLOR} strokeDasharray="4 4" strokeOpacity={0.7} />
        <Area dataKey="outer" stroke="none" fill={BAND_COLOR} fillOpacity={0.12} isAnimationActive={false} activeDot={false} />
        <Area dataKey="inner" stroke="none" fill={BAND_COLOR} fillOpacity={0.24} isAnimationActive={false} activeDot={false} />
        <Line dataKey="p5" stroke={TAIL_COLOR} strokeWidth={1} strokeDasharray="3 3" dot={false} activeDot={false} isAnimationActive={false} />
        <Line
          dataKey="p50"
          stroke={MEDIAN_COLOR}
          strokeWidth={2.25}
          dot={false}
          activeDot={{ r: 3.5, stroke: "#09090b", strokeWidth: 2, fill: MEDIAN_COLOR }}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function FanLegend() {
  const swatch = (style: CSSProperties, label: string) => (
    <span className="flex items-center gap-1.5 font-mono text-[10px] text-zinc-400">
      <span className="h-2.5 w-4 rounded-sm" style={style} />
      {label}
    </span>
  );
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {swatch({ background: BAND_COLOR, opacity: 0.25 }, "p5–p95")}
      {swatch({ background: BAND_COLOR, opacity: 0.5 }, "p25–p75")}
      {swatch({ background: MEDIAN_COLOR, height: 2 }, "Median")}
      {swatch({ borderTop: `1px dashed ${TAIL_COLOR}`, height: 0 }, "p5 tail")}
      {swatch({ borderTop: `1px dashed ${START_COLOR}`, height: 0 }, "Today")}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

export function MonteCarloPanel({ refreshKey }: { refreshKey: unknown }) {
  const [days, setDays] = useState<number>(90);
  const [drift, setDrift] = useState<DriftModel>("historical");
  const [seed, setSeed] = useState<number>(DEFAULT_SEED);

  const { data, loading, error } = useApiResource(
    (signal) => api.getMonteCarlo({ days, simulations: SIMULATIONS, drift, seed }, signal),
    [days, drift, seed, refreshKey],
  );

  return (
    <section className="panel flex min-w-0 flex-col">
      <header className="panel-header flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <h3 className="panel-title">Monte Carlo · Correlated GBM</h3>
          {loading && <LoaderCircle className="h-3 w-3 animate-spin text-zinc-500" />}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented options={DRIFTS} value={drift} onChange={setDrift} />
          <Segmented options={HORIZONS.map((h) => ({ value: h.days, label: h.label }))} value={days} onChange={setDays} />
          <button
            type="button"
            onClick={() => setSeed(Math.floor(Math.random() * 1_000_000))}
            title="Re-run with a new random seed"
            className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-2 py-1 font-mono text-[11px] text-zinc-400 transition hover:border-zinc-500 hover:text-zinc-200"
          >
            <Dices className="h-3.5 w-3.5" />
            Re-roll
          </button>
        </div>
      </header>

      <div className="flex flex-1 flex-col gap-3 p-4">
        {error ? (
          <div className="flex h-[360px] items-center justify-center px-6 text-center text-sm text-rose-400">{error}</div>
        ) : !data ? (
          <>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="h-[74px] animate-pulse rounded bg-zinc-800/30" />
              ))}
            </div>
            <div className="h-[280px] animate-pulse rounded bg-zinc-800/30" />
          </>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              <Kpi
                label="Expected Value"
                value={formatMoney(data.expected_value, "USD")}
                valueClass={pnlColor(data.expected_return_pct)}
                sub={
                  <>
                    {formatPct(data.expected_return_pct, 2, true)} vs {compactUsd(data.initial_value)} today
                  </>
                }
              />
              <Kpi
                label="Simulated VaR 95%"
                value={formatMoney(data.var_95_simulated, "USD")}
                valueClass="text-amber-300"
                sub={<>{formatPct(data.var_95_pct, 2)} of portfolio</>}
              />
              <Kpi
                label="Simulated CVaR 95%"
                value={formatMoney(data.cvar_95_simulated, "USD")}
                valueClass="text-rose-400"
                sub={<>Expected shortfall · {formatPct(data.cvar_95_pct, 2)}</>}
              />
              <Kpi
                label="Prob. of Loss"
                value={formatPct(data.probability_of_loss_pct, 1)}
                valueClass={data.probability_of_loss_pct >= 50 ? "text-rose-400" : "text-emerald-400"}
                sub={<>at day +{data.horizon_days}</>}
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <FanLegend />
              <span className="num text-[10px] text-zinc-500">
                median {compactUsd(data.median_value)} · p5 {compactUsd(data.bands[data.bands.length - 1].p5)} · p95{" "}
                {compactUsd(data.bands[data.bands.length - 1].p95)}
              </span>
            </div>

            <div className="h-[280px]">
              <FanChart result={data} />
            </div>

            <div className="flex flex-wrap gap-1.5">
              {data.holdings.map((h) => (
                <span
                  key={h.symbol}
                  className="num rounded border border-zinc-800 bg-zinc-950/50 px-2 py-0.5 text-[10px] text-zinc-400"
                  title={`Annualized drift ${formatPct(h.annualized_drift_pct, 1, true)}${h.fx_adjusted ? "" : " · local-currency returns (no FX history)"}`}
                >
                  <span className="text-zinc-200">{h.symbol.replace(/\.IS$/i, "")}</span> {formatNumber(h.weight_pct, 1)}% · σ{" "}
                  {formatNumber(h.annualized_volatility_pct, 0)}%{h.fx_adjusted ? "" : " *"}
                </span>
              ))}
            </div>

            <div className="num border-t border-zinc-800 pt-2 text-[10px] text-zinc-600">
              {data.simulations.toLocaleString("en-US")} paths · Cholesky-correlated · n={data.observations} USD log-returns (
              {data.start_date} → {data.end_date}) · seed {data.seed ?? "random"}
              {data.cholesky_jitter > 0 && ` · jitter ${data.cholesky_jitter.toExponential(1)}`}
              {data.excluded_symbols.length > 0 && ` · excluded: ${data.excluded_symbols.join(", ")}`}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
