import { LoaderCircle, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import { useApiResource } from "../hooks/useApiResource";

interface CorrelationHeatmapProps {
  refreshKey: unknown;
  onSelectSymbol: (symbol: string) => void;
}

interface CellTone {
  background: string;
  text: string;
  label: string;
}

/**
 * Diversification-oriented color scale:
 * negative → teal (hedge), low → emerald, moderate → slate / amber,
 * > 0.70 → crimson (concentration risk).
 */
export function correlationTone(value: number | null): CellTone {
  if (value == null) return { background: "rgba(39,39,42,0.5)", text: "text-zinc-600", label: "Undefined" };
  const strength = Math.min(1, Math.abs(value));
  if (value < 0) {
    return { background: `rgba(20,184,166,${0.12 + 0.5 * strength})`, text: "text-teal-100", label: "Negative: natural hedge" };
  }
  if (value < 0.3) {
    return { background: `rgba(16,185,129,${0.1 + 0.4 * strength})`, text: "text-emerald-100", label: "Low: strong diversification" };
  }
  if (value < 0.5) return { background: "rgba(100,116,139,0.35)", text: "text-slate-100", label: "Moderate co-movement" };
  if (value <= 0.7) {
    return { background: `rgba(245,158,11,${0.2 + 0.5 * (value - 0.5)})`, text: "text-amber-100", label: "Elevated co-movement" };
  }
  return { background: `rgba(225,29,72,${0.35 + 0.9 * (value - 0.7)})`, text: "text-rose-50", label: "High: concentration risk" };
}

const shortSymbol = (symbol: string) => symbol.replace(/\.IS$/i, "");

function formatCorr(value: number | null): string {
  if (value == null) return "n/a";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

const LEGEND = [
  { label: "< 0", color: "rgba(20,184,166,0.55)" },
  { label: "0–0.3", color: "rgba(16,185,129,0.4)" },
  { label: "0.3–0.5", color: "rgba(100,116,139,0.45)" },
  { label: "0.5–0.7", color: "rgba(245,158,11,0.5)" },
  { label: "> 0.7", color: "rgba(225,29,72,0.7)" },
];

export function CorrelationHeatmap({ refreshKey, onSelectSymbol }: CorrelationHeatmapProps) {
  const { data, loading, error } = useApiResource((signal) => api.getCorrelation(signal), [refreshKey]);
  const [hover, setHover] = useState<{ row: number; col: number } | null>(null);

  const symbols = data?.symbols ?? [];
  const n = symbols.length;

  return (
    <section className="panel">
      <header className="panel-header">
        <h2 className="panel-title">Correlation Matrix</h2>
        <span className="num flex items-center gap-1.5 text-[11px] text-zinc-500">
          {loading && <LoaderCircle className="h-3 w-3 animate-spin" />}
          {data ? `n=${data.observations} aligned returns` : "90D daily"}
        </span>
      </header>

      {/* Cells are square, so cap the width: below the xl breakpoint the sidebar spans the full page. */}
      <div className="mx-auto max-w-[440px] p-4">
        {error ? (
          <p className="py-8 text-center text-sm text-rose-400">{error}</p>
        ) : !data ? (
          <div className="aspect-square animate-pulse rounded bg-zinc-800/30" />
        ) : n < 2 ? (
          <p className="py-8 text-center text-sm text-zinc-500">Add at least two positions with price history.</p>
        ) : (
          <>
            <div
              className="grid gap-[3px]"
              style={{ gridTemplateColumns: `auto repeat(${n}, minmax(0, 1fr))` }}
              onMouseLeave={() => setHover(null)}
            >
              <div />
              {symbols.map((symbol, col) => (
                <div
                  key={`col-${symbol}`}
                  className={`truncate pb-1 text-center font-mono text-[10px] font-semibold transition-colors ${
                    hover?.col === col ? "text-zinc-100" : "text-zinc-500"
                  }`}
                  title={symbol}
                >
                  {shortSymbol(symbol)}
                </div>
              ))}

              {symbols.map((rowSymbol, row) => (
                <div key={`row-${rowSymbol}`} className="contents">
                  <button
                    type="button"
                    onClick={() => onSelectSymbol(rowSymbol)}
                    className={`truncate pr-2 text-right font-mono text-[10px] font-semibold transition-colors hover:text-emerald-300 ${
                      hover?.row === row ? "text-zinc-100" : "text-zinc-500"
                    }`}
                    title={`Open ${rowSymbol} deep dive`}
                  >
                    {shortSymbol(rowSymbol)}
                  </button>

                  {data.matrix[row].map((value, col) => {
                    const diagonal = row === col;
                    const tone = correlationTone(value);
                    const active = hover?.row === row && hover.col === col;
                    const crossHair = hover != null && (hover.row === row || hover.col === col);
                    return (
                      <div
                        key={`${rowSymbol}-${symbols[col]}`}
                        onMouseEnter={() => setHover({ row, col })}
                        className={`relative flex aspect-square min-h-8 items-center justify-center rounded-[3px] font-mono text-[11px] font-medium transition ${
                          diagonal ? "text-zinc-600" : tone.text
                        } ${active ? "ring-1 ring-zinc-200" : crossHair ? "brightness-125" : ""}`}
                        style={{ background: diagonal ? "rgba(39,39,42,0.6)" : tone.background }}
                      >
                        {diagonal ? "1.00" : formatCorr(value)}

                        {active && !diagonal && (
                          <div
                            className={`pointer-events-none absolute bottom-full z-20 mb-2 w-48 rounded border border-zinc-700 bg-zinc-950/95 px-3 py-2 text-left shadow-xl shadow-black/50 ${
                              col >= n / 2 ? "right-0" : "left-0"
                            }`}
                          >
                            <div className="font-mono text-[11px] font-semibold text-zinc-100">
                              {symbols[row]} × {symbols[col]}
                            </div>
                            <div className="mt-0.5 flex items-baseline justify-between">
                              <span className="label">Pearson ρ</span>
                              <span className="num text-sm font-semibold text-zinc-50">{formatCorr(value)}</span>
                            </div>
                            <div className="mt-1 text-[11px] text-zinc-400">{tone.label}</div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>

            <div className="mt-4 flex items-center gap-1">
              {LEGEND.map((item) => (
                <div key={item.label} className="flex-1">
                  <div className="h-1.5 rounded-sm" style={{ background: item.color }} />
                  <div className="num mt-1 text-center text-[9px] text-zinc-500">{item.label}</div>
                </div>
              ))}
            </div>

            <div className="mt-3 space-y-1.5 border-t border-zinc-800 pt-3 text-[11px]">
              <div className="flex justify-between text-zinc-500">
                <span>Avg pairwise ρ</span>
                <span className="num text-zinc-200">{formatCorr(data.average_correlation)}</span>
              </div>
              {data.high_correlation_pairs.length > 0 ? (
                data.high_correlation_pairs.map((pair) => (
                  <div key={`${pair.symbol_a}-${pair.symbol_b}`} className="flex items-center justify-between gap-2 text-rose-300">
                    <span className="flex items-center gap-1.5">
                      <TriangleAlert className="h-3 w-3" />
                      <span className="font-mono">
                        {shortSymbol(pair.symbol_a)} / {shortSymbol(pair.symbol_b)}
                      </span>
                    </span>
                    <span className="num">{formatCorr(pair.correlation)}</span>
                  </div>
                ))
              ) : (
                <div className="text-emerald-400/80">No pair above ρ {data.high_correlation_threshold.toFixed(2)}: no concentration flags.</div>
              )}
              {data.excluded_symbols.length > 0 && (
                <div className="text-zinc-600">Excluded (no history): {data.excluded_symbols.join(", ")}</div>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
