import { WifiOff } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";

import { api } from "./api/client";
import type { Position } from "./api/types";
import { AddPositionModal } from "./components/AddPositionModal";
import { AlertsFeed } from "./components/AlertsFeed";
import { CorrelationHeatmap } from "./components/CorrelationHeatmap";
import { Header } from "./components/Header";
import { KpiBar } from "./components/KpiBar";
import { PortfolioTable } from "./components/PortfolioTable";
import { useDashboard } from "./hooks/useDashboard";

// Recharts is the heaviest dependency; load the deep-dive panel as its own chunk.
const StockDetailPanel = lazy(() =>
  import("./components/detail/StockDetailPanel").then((m) => ({ default: m.StockDetailPanel })),
);

function LoadingSkeleton() {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="panel h-[112px] animate-pulse" />
        ))}
      </div>
      <div className="panel h-[260px] animate-pulse" />
      <div className="panel h-[360px] animate-pulse" />
    </div>
  );
}

function OfflineState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="panel mx-auto mt-16 flex max-w-lg flex-col items-center gap-3 px-8 py-12 text-center">
      <WifiOff className="h-8 w-8 text-rose-400" />
      <h2 className="text-sm font-semibold text-zinc-100">Backend unavailable</h2>
      <p className="text-sm text-zinc-400">{message}</p>
      <code className="rounded bg-zinc-950 px-3 py-1.5 font-mono text-xs text-zinc-400">uvicorn main:app --reload --port 8000</code>
      <button
        type="button"
        onClick={onRetry}
        className="mt-2 rounded border border-zinc-700 px-4 py-1.5 text-xs font-medium text-zinc-200 hover:border-emerald-500/50 hover:text-emerald-300"
      >
        Retry
      </button>
    </div>
  );
}

export default function App() {
  const { portfolio, alerts, loading, refreshing, error, lastUpdated, refresh } = useDashboard();
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const positions = portfolio?.positions ?? [];

  // Auto-select the riskiest holding once data arrives (or after the selection is removed).
  useEffect(() => {
    if (selectedSymbol || positions.length === 0) return;
    const riskiest = positions.reduce((a, b) => (b.risk_score > a.risk_score ? b : a));
    setSelectedSymbol(riskiest.symbol);
  }, [positions, selectedSymbol]);

  const handleDelete = useCallback(
    async (position: Position) => {
      try {
        await api.deletePosition(position.id);
        setActionError(null);
        if (selectedSymbol === position.symbol) setSelectedSymbol(null);
        await refresh();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Could not delete position.");
      }
    },
    [refresh, selectedSymbol],
  );

  const handleAdded = useCallback(
    (symbol: string) => {
      setSelectedSymbol(symbol);
      void refresh();
    },
    [refresh],
  );

  const closeModal = useCallback(() => setModalOpen(false), []);
  const connected = !error && portfolio !== null;
  const selectedPosition = positions.find((p) => p.symbol === selectedSymbol);

  return (
    <div className="min-h-screen">
      <Header connected={connected} lastUpdated={lastUpdated} />

      <main className="mx-auto max-w-[1680px] space-y-3 px-4 py-4">
        {loading && !portfolio ? (
          <LoadingSkeleton />
        ) : error && !portfolio ? (
          <OfflineState message={error} onRetry={() => void refresh()} />
        ) : (
          <>
            {(error || actionError) && (
              <div className="rounded border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs text-rose-300" role="alert">
                {actionError ?? `Showing last known data — ${error}`}
              </div>
            )}

            <KpiBar summary={portfolio?.summary ?? null} alerts={alerts} refreshing={refreshing} onRefresh={() => void refresh()} />

            <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
              <div className="min-w-0 space-y-3 xl:col-span-9">
                <PortfolioTable
                  positions={positions}
                  selectedSymbol={selectedSymbol}
                  onSelect={setSelectedSymbol}
                  onDelete={handleDelete}
                  onAdd={() => setModalOpen(true)}
                />
                {selectedSymbol && (
                  <Suspense fallback={<div className="panel h-[380px] animate-pulse" />}>
                    <StockDetailPanel
                      key={selectedSymbol}
                      symbol={selectedSymbol}
                      position={selectedPosition}
                      refreshKey={lastUpdated?.getTime()}
                    />
                  </Suspense>
                )}
              </div>
              <aside className="min-w-0 space-y-3 xl:col-span-3">
                <CorrelationHeatmap refreshKey={lastUpdated?.getTime()} onSelectSymbol={setSelectedSymbol} />
                <AlertsFeed alerts={alerts} onSelectSymbol={setSelectedSymbol} />
              </aside>
            </div>
          </>
        )}
      </main>

      <footer className="border-t border-zinc-900 px-4 py-3">
        <div className="num mx-auto flex max-w-[1680px] flex-wrap justify-between gap-2 text-[10px] text-zinc-600">
          <span>DATA: Yahoo Finance · 5-min server cache · 60s client refresh</span>
          <span>VaR: historical 95% 1-day · Vol: σ√252 · Sharpe rf 4% · Sentiment: VADER</span>
        </div>
      </footer>

      <AddPositionModal open={modalOpen} onClose={closeModal} onAdded={handleAdded} />
    </div>
  );
}
