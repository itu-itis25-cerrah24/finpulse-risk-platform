import type { QuantMetrics } from "../../api/types";
import { formatNumber, formatPct } from "../../lib/format";

interface MetricRowProps {
  label: string;
  hint: string;
  value: string;
  valueClass: string;
  /** 0-1 share of the "danger" cap, drawn as a thin severity bar. */
  intensity: number | null;
}

function intensityColor(intensity: number): string {
  if (intensity < 0.35) return "bg-emerald-500";
  if (intensity < 0.65) return "bg-amber-500";
  return "bg-rose-500";
}

function MetricRow({ label, hint, value, valueClass, intensity }: MetricRowProps) {
  return (
    <div className="border-b border-zinc-800/70 px-4 py-3 last:border-b-0">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <div className="text-xs font-medium text-zinc-200">{label}</div>
          <div className="text-[11px] text-zinc-500">{hint}</div>
        </div>
        <div className={`num text-lg font-semibold ${valueClass}`}>{value}</div>
      </div>
      {intensity != null && (
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-zinc-800">
          <div
            className={`h-full rounded-full ${intensityColor(intensity)}`}
            style={{ width: `${Math.max(2, Math.min(100, intensity * 100))}%` }}
          />
        </div>
      )}
    </div>
  );
}

const ratio = (value: number | null, cap: number) => (value == null ? null : Math.min(1, Math.abs(value) / cap));

function sharpeClass(sharpe: number | null): string {
  if (sharpe == null) return "text-zinc-400";
  if (sharpe >= 1) return "text-emerald-400";
  if (sharpe >= 0) return "text-amber-400";
  return "text-rose-400";
}

export function QuantBreakdown({ quant }: { quant: QuantMetrics }) {
  return (
    <section className="panel flex flex-col">
      <header className="panel-header">
        <h3 className="panel-title">Quant Risk Breakdown</h3>
        <span className="num text-[11px] text-zinc-500">n={quant.observations} daily returns</span>
      </header>
      <MetricRow
        label="Annualized Volatility"
        hint="σ(daily returns) × √252"
        value={formatPct(quant.annualized_volatility_pct, 2)}
        valueClass="text-zinc-100"
        intensity={ratio(quant.annualized_volatility_pct, 60)}
      />
      <MetricRow
        label="Value at Risk (95%, 1-day)"
        hint="Historical 5th-percentile loss"
        value={formatPct(quant.var_95_pct, 2)}
        valueClass="text-zinc-100"
        intensity={ratio(quant.var_95_pct, 5)}
      />
      <MetricRow
        label="Max Drawdown"
        hint="Worst peak-to-trough decline"
        value={formatPct(quant.max_drawdown_pct, 2)}
        valueClass="text-rose-300"
        intensity={ratio(quant.max_drawdown_pct, 40)}
      />
      <MetricRow
        label="Sharpe Ratio"
        hint="Excess return / vol · rf = 4%"
        value={formatNumber(quant.sharpe_ratio, 2)}
        valueClass={sharpeClass(quant.sharpe_ratio)}
        intensity={null}
      />
    </section>
  );
}
