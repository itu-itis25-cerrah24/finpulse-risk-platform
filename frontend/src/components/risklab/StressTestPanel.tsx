import { LoaderCircle, RotateCcw, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "../../api/client";
import type { ScenarioKey, StressImpact, StressShocks, StressTestRequest } from "../../api/types";
import { useApiResource } from "../../hooks/useApiResource";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { formatMoney, formatPct, formatSignedMoney, pnlColor } from "../../lib/format";

const ZERO_SHOCKS: StressShocks = { us_equity_shock_pct: 0, bist_equity_shock_pct: 0, usd_try_shock_pct: 0 };
const DEBOUNCE_MS = 150;

interface SliderSpec {
  key: keyof StressShocks;
  label: string;
  hint: string;
  min: number;
  max: number;
}

const SLIDERS: SliderSpec[] = [
  { key: "us_equity_shock_pct", label: "US Equities", hint: "Applied to US-listed holdings", min: -50, max: 30 },
  { key: "bist_equity_shock_pct", label: "BIST Equities", hint: "Applied to .IS holdings, in lira", min: -50, max: 30 },
  { key: "usd_try_shock_pct", label: "USD/TRY FX", hint: "+ = lira weakens; hits TRY assets in USD", min: -30, max: 60 },
];

// ---------------------------------------------------------------------------
// Pieces
// ---------------------------------------------------------------------------

function DeltaBadge({ value, digits = 2 }: { value: number | null; digits?: number }) {
  const tone =
    value == null || value === 0
      ? "border-zinc-700 bg-zinc-800/40 text-zinc-400"
      : value > 0
        ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
        : "border-rose-500/30 bg-rose-500/10 text-rose-400";
  return <span className={`num inline-block rounded border px-1.5 py-px text-[11px] font-semibold ${tone}`}>{formatPct(value, digits, true)}</span>;
}

function ShockSlider({ spec, value, onChange }: { spec: SliderSpec; value: number; onChange: (value: number) => void }) {
  // For FX a positive move is the adverse one (weaker lira), so the colour is flipped.
  const adverse = spec.key === "usd_try_shock_pct" ? value > 0 : value < 0;
  const accent = value === 0 ? "#71717a" : adverse ? "#f43f5e" : "#10b981";
  // Fill the track from the 0% mark to the current value, so the shock size reads at a glance.
  const toPct = (v: number) => ((v - spec.min) / (spec.max - spec.min)) * 100;
  const [from, to] = [toPct(Math.min(0, value)), toPct(Math.max(0, value))];
  const track = `linear-gradient(to right, #27272a ${from}%, ${accent} ${from}%, ${accent} ${to}%, #27272a ${to}%)`;
  return (
    <label className="block">
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-[11px] font-semibold text-zinc-300">{spec.label}</span>
        <span className="num text-xs font-semibold" style={{ color: accent }}>
          {value > 0 ? "+" : ""}
          {value}%
        </span>
      </div>
      <input
        type="range"
        min={spec.min}
        max={spec.max}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="shock-range mt-2 w-full"
        style={{ background: track, color: accent }}
        aria-label={`${spec.label} shock in percent`}
      />
      <div className="flex justify-between text-[9px] text-zinc-600">
        <span className="num">{spec.min}%</span>
        <span>{spec.hint}</span>
        <span className="num">+{spec.max}%</span>
      </div>
    </label>
  );
}

function ImpactRow({ impact, maxAbsPct, worst }: { impact: StressImpact; maxAbsPct: number; worst: boolean }) {
  const width = maxAbsPct > 0 ? (Math.abs(impact.pnl_pct) / maxAbsPct) * 100 : 0;
  const shock = [
    impact.equity_shock_pct !== 0 && `EQ ${formatPct(impact.equity_shock_pct, 0, true)}`,
    impact.fx_shock_pct !== 0 && `FX ${formatPct(impact.fx_shock_pct, 0, true)}`,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <tr className={`border-b border-zinc-800/60 ${worst ? "bg-rose-500/5" : ""}`}>
      <td className={`py-1.5 pr-2 pl-2 ${worst ? "border-l-2 border-rose-500" : "border-l-2 border-transparent"}`}>
        <div className="flex items-center gap-1.5 font-mono text-xs font-semibold text-zinc-100">
          {impact.symbol}
          {worst && <TriangleAlert className="h-3 w-3 text-rose-400" aria-label="Worst hit" />}
        </div>
        <div className="text-[10px] text-zinc-500">
          {impact.segment === "BIST_EQUITY" ? "BIST" : "US"} · {impact.currency ?? "—"}
          {shock && <span className="ml-1 text-zinc-600">({shock})</span>}
        </div>
      </td>
      <td className="num py-1.5 pr-2 text-right text-xs text-zinc-400">{formatMoney(impact.value_before_usd, "USD")}</td>
      <td className="num py-1.5 pr-2 text-right text-xs text-zinc-200">{formatMoney(impact.value_after_usd, "USD")}</td>
      <td className={`num py-1.5 pr-2 text-right text-xs font-medium ${pnlColor(impact.pnl_usd)}`}>{formatSignedMoney(impact.pnl_usd, "USD")}</td>
      <td className="py-1.5 pr-2 text-right">
        <DeltaBadge value={impact.pnl_pct} />
        <div className="mt-1 ml-auto h-0.5 w-16 rounded bg-zinc-800">
          <div
            className={`ml-auto h-full rounded ${impact.pnl_pct < 0 ? "bg-rose-500" : "bg-emerald-500"}`}
            style={{ width: `${width}%` }}
          />
        </div>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

export function StressTestPanel({ refreshKey }: { refreshKey: unknown }) {
  const [shocks, setShocks] = useState<StressShocks>(ZERO_SHOCKS);
  const [preset, setPreset] = useState<ScenarioKey | null>(null);

  const scenarios = useApiResource((signal) => api.getStressScenarios(signal), []);

  // A preset is sent by key so the server's definition stays the source of truth.
  const request = useMemo<StressTestRequest>(() => (preset ? { scenario: preset } : shocks), [preset, shocks]);
  const debounced = useDebouncedValue(request, DEBOUNCE_MS);
  const { data, loading, error } = useApiResource(
    (signal) => api.runStressTest(debounced, signal),
    [debounced, refreshKey],
  );

  const activeScenario = scenarios.data?.find((s) => s.key === preset);
  const maxAbsPct = Math.max(0, ...(data?.positions.map((p) => Math.abs(p.pnl_pct)) ?? []));
  const sorted = useMemo(() => [...(data?.positions ?? [])].sort((a, b) => a.pnl_usd - b.pnl_usd), [data]);

  const applyPreset = (key: ScenarioKey) => {
    const scenario = scenarios.data?.find((s) => s.key === key);
    if (!scenario) return;
    setPreset(key);
    setShocks({
      us_equity_shock_pct: scenario.us_equity_shock_pct,
      bist_equity_shock_pct: scenario.bist_equity_shock_pct,
      usd_try_shock_pct: scenario.usd_try_shock_pct,
    });
  };

  const setShock = (key: keyof StressShocks, value: number) => {
    setPreset(null);
    setShocks((prev) => ({ ...prev, [key]: value }));
  };

  const reset = () => {
    setPreset(null);
    setShocks(ZERO_SHOCKS);
  };

  return (
    <section className="panel flex min-w-0 flex-col">
      <header className="panel-header">
        <div className="flex items-center gap-2">
          <h3 className="panel-title">Stress Test · Scenario Analysis</h3>
          {loading && <LoaderCircle className="h-3 w-3 animate-spin text-zinc-500" />}
        </div>
        <button
          type="button"
          onClick={reset}
          className="inline-flex items-center gap-1.5 rounded border border-zinc-700 px-2 py-1 font-mono text-[11px] text-zinc-400 transition hover:border-zinc-500 hover:text-zinc-200"
        >
          <RotateCcw className="h-3 w-3" />
          Reset
        </button>
      </header>

      <div className="flex flex-1 flex-col gap-4 p-4">
        <div>
          <div className="label mb-1.5">Crisis presets</div>
          <div className="grid grid-cols-2 gap-1.5">
            {(scenarios.data ?? []).map((scenario) => (
              <button
                key={scenario.key}
                type="button"
                onClick={() => applyPreset(scenario.key)}
                aria-pressed={preset === scenario.key}
                title={scenario.description}
                className={`rounded border px-2.5 py-1.5 text-left transition ${
                  preset === scenario.key
                    ? "border-rose-500/50 bg-rose-500/10 text-rose-200"
                    : "border-zinc-800 bg-zinc-950/40 text-zinc-300 hover:border-zinc-600"
                }`}
              >
                <div className="text-xs font-semibold">{scenario.label}</div>
                <div className="num text-[10px] text-zinc-500">
                  US {formatPct(scenario.us_equity_shock_pct, 0, true)} · BIST {formatPct(scenario.bist_equity_shock_pct, 0, true)} · TRY{" "}
                  {formatPct(scenario.usd_try_shock_pct, 0, true)}
                </div>
              </button>
            ))}
            {scenarios.error && <p className="col-span-2 text-xs text-rose-400">{scenarios.error}</p>}
          </div>
          <p className="mt-1.5 min-h-4 text-[11px] text-zinc-500">
            {activeScenario ? activeScenario.description : "Drag a slider to build a custom scenario."}
          </p>
        </div>

        <div className="space-y-3">
          {SLIDERS.map((spec) => (
            <ShockSlider key={spec.key} spec={spec} value={shocks[spec.key]} onChange={(v) => setShock(spec.key, v)} />
          ))}
        </div>

        {error ? (
          <p className="py-6 text-center text-sm text-rose-400">{error}</p>
        ) : !data ? (
          <div className="h-[200px] animate-pulse rounded bg-zinc-800/30" />
        ) : (
          <div className={`transition-opacity ${loading ? "opacity-70" : ""}`}>
            <div className="grid grid-cols-3 gap-2 rounded border border-zinc-800 bg-zinc-950/40 px-3 py-2">
              <div>
                <div className="label">Before</div>
                <div className="num text-sm font-semibold text-zinc-200">{formatMoney(data.total_before_usd, "USD")}</div>
              </div>
              <div>
                <div className="label">After</div>
                <div className="num text-sm font-semibold text-zinc-50">{formatMoney(data.total_after_usd, "USD")}</div>
              </div>
              <div className="text-right">
                <div className="label">Impact</div>
                <div className={`num text-sm font-semibold ${pnlColor(data.total_pnl_usd)}`}>{formatSignedMoney(data.total_pnl_usd, "USD")}</div>
                <DeltaBadge value={data.total_pnl_pct} />
              </div>
            </div>

            <table className="mt-2 w-full border-collapse">
              <thead>
                <tr className="border-b border-zinc-800 text-right">
                  <th className="label py-1.5 pl-2.5 text-left font-medium">Holding</th>
                  <th className="label py-1.5 pr-2 font-medium">Before</th>
                  <th className="label py-1.5 pr-2 font-medium">After</th>
                  <th className="label py-1.5 pr-2 font-medium">P&amp;L</th>
                  <th className="label py-1.5 pr-2 font-medium">Δ%</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((impact) => (
                  <ImpactRow key={impact.symbol} impact={impact} maxAbsPct={maxAbsPct} worst={impact.symbol === data.worst_hit_symbol} />
                ))}
              </tbody>
            </table>

            <div className="mt-2 flex flex-wrap justify-between gap-2 text-[10px] text-zinc-600">
              <span>Instant revaluation in USD: value × (1 + equity) ÷ (1 + FX) for TRY assets</span>
              {data.excluded_symbols.length > 0 && <span>Excluded (no price/FX): {data.excluded_symbols.join(", ")}</span>}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
