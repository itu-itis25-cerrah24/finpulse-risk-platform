import { LoaderCircle } from "lucide-react";

import type { Position } from "../../api/types";
import { useStockDetail } from "../../hooks/useStockDetail";
import { formatMoney, formatPct, pnlColor, riskTone } from "../../lib/format";
import { NewsFeed } from "./NewsFeed";
import { PriceChart } from "./PriceChart";
import { QuantBreakdown } from "./QuantBreakdown";

interface StockDetailPanelProps {
  symbol: string;
  position: Position | undefined;
  refreshKey: unknown;
}

function Stat({ label, value, className = "text-zinc-100" }: { label: string; value: string; className?: string }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div className={`num mt-0.5 text-sm font-medium ${className}`}>{value}</div>
    </div>
  );
}

export function StockDetailPanel({ symbol, position, refreshKey }: StockDetailPanelProps) {
  const { detail, loading, error } = useStockDetail(symbol, refreshKey);
  const tone = riskTone(detail?.risk_score);

  return (
    <div className="space-y-3">
      <section className="panel">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-zinc-800 px-4 py-3">
          <div className="flex items-center gap-4">
            <div>
              <div className="label">Deep Dive</div>
              <div className="flex items-baseline gap-3">
                <h2 className="font-mono text-xl font-semibold text-zinc-50">{symbol}</h2>
                {detail && (
                  <>
                    <span className="num text-lg text-zinc-100">{formatMoney(detail.price, detail.currency)}</span>
                    <span className={`num text-sm font-medium ${pnlColor(detail.daily_change_pct)}`}>
                      {formatPct(detail.daily_change_pct, 2, true)}
                    </span>
                  </>
                )}
                {loading && <LoaderCircle className="h-4 w-4 animate-spin text-zinc-500" />}
              </div>
            </div>
          </div>

          {detail && (
            <div className="flex flex-wrap items-center gap-6">
              <Stat label="Prev Close" value={formatMoney(detail.previous_close, detail.currency)} />
              {position && (
                <>
                  <Stat label="Mkt Value" value={formatMoney(position.market_value, position.currency)} />
                  <Stat
                    label="Unrl. P&L"
                    value={formatPct(position.unrealized_pnl_pct, 2, true)}
                    className={pnlColor(position.unrealized_pnl_pct)}
                  />
                </>
              )}
              <div className={`rounded border px-3 py-1.5 text-center ${tone.text} border-current/30`}>
                <div className="text-[9px] font-semibold tracking-[0.14em] uppercase opacity-80">Risk</div>
                <div className="num text-lg leading-tight font-semibold">{detail.risk_score.toFixed(0)}</div>
              </div>
            </div>
          )}
        </header>

        <div className="p-4">
          {error ? (
            <div className="flex h-[300px] items-center justify-center text-sm text-rose-400">{error}</div>
          ) : detail ? (
            <PriceChart symbol={symbol} history={detail.history} currency={detail.currency} avgCost={position?.avg_cost} />
          ) : (
            <div className="h-[300px] animate-pulse rounded bg-zinc-800/30" />
          )}
        </div>
      </section>

      {detail && (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
          <div className="lg:col-span-2">
            <QuantBreakdown quant={detail.quant} />
          </div>
          <div className="lg:col-span-3">
            <NewsFeed headlines={detail.headlines} sentiment={detail.sentiment} />
          </div>
        </div>
      )}
    </div>
  );
}
