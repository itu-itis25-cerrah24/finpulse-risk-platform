import { ShieldCheck } from "lucide-react";

import type { AlertType, RiskAlert } from "../api/types";
import { formatRelativeTime, severityAccent } from "../lib/format";
import { SeverityBadge } from "./ui/Badges";

const typeLabel: Record<AlertType, string> = {
  HIGH_DROP: "Sharp Drop",
  HIGH_SPIKE: "Sharp Spike",
  HIGH_RISK_SCORE: "Risk Score",
  BEARISH_SENTIMENT: "Bearish News",
  DEEP_DRAWDOWN: "Drawdown",
};

interface AlertsFeedProps {
  alerts: RiskAlert[];
  onSelectSymbol: (symbol: string) => void;
}

export function AlertsFeed({ alerts, onSelectSymbol }: AlertsFeedProps) {
  return (
    <section className="panel flex max-h-[560px] min-h-[240px] flex-col">
      <header className="panel-header">
        <h2 className="panel-title">Risk Alerts</h2>
        <span className="num text-[11px] text-zinc-500">{alerts.length} events</span>
      </header>

      {alerts.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 py-12 text-center">
          <ShieldCheck className="h-8 w-8 text-emerald-500/60" />
          <p className="text-sm text-zinc-400">No risk alerts triggered.</p>
          <p className="text-xs text-zinc-600">Thresholds are evaluated on every portfolio refresh.</p>
        </div>
      ) : (
        <ul className="flex-1 divide-y divide-zinc-800/70 overflow-y-auto">
          {alerts.map((alert) => (
            <li key={alert.id}>
              <button
                type="button"
                onClick={() => onSelectSymbol(alert.symbol)}
                className="flex w-full gap-3 px-4 py-3 text-left transition hover:bg-zinc-800/40"
              >
                <span className={`w-0.5 shrink-0 self-stretch rounded-full ${severityAccent[alert.severity]}`} aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-semibold text-zinc-100">{alert.symbol}</span>
                      <span className="text-[11px] text-zinc-500">{typeLabel[alert.alert_type] ?? alert.alert_type}</span>
                    </div>
                    <SeverityBadge severity={alert.severity} />
                  </div>
                  <p className="mt-1 text-xs leading-snug text-zinc-400">{alert.message}</p>
                  <div className="num mt-1 text-[10px] text-zinc-600">{formatRelativeTime(alert.created_at)}</div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
