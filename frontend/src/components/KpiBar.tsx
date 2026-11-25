import { Bell, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import type { PortfolioSummary, RiskAlert } from "../api/types";
import { formatMoney, formatPct, formatSignedMoney, pnlColor, riskTone } from "../lib/format";
import { RiskGauge } from "./ui/RiskGauge";

interface KpiBarProps {
  summary: PortfolioSummary | null;
  alerts: RiskAlert[];
  refreshing: boolean;
  onRefresh: () => void;
}

function KpiCard({ label, children, footer }: { label: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="panel flex min-h-[112px] flex-col justify-between px-4 py-3">
      <div className="label">{label}</div>
      <div className="mt-1 flex-1">{children}</div>
      {footer && <div className="mt-1 text-[11px] text-zinc-500">{footer}</div>}
    </div>
  );
}

/** Alerts raised during the current UTC day count as "active". */
function countActiveAlerts(alerts: RiskAlert[]): { total: number; critical: number } {
  const today = new Date().toISOString().slice(0, 10);
  const active = alerts.filter((a) => a.created_at.slice(0, 10) === today);
  return {
    total: active.length,
    critical: active.filter((a) => a.severity === "CRITICAL" || a.severity === "HIGH").length,
  };
}

export function KpiBar({ summary, alerts, refreshing, onRefresh }: KpiBarProps) {
  const pnl = summary?.total_pnl ?? null;
  const score = summary?.weighted_risk_score ?? null;
  const tone = riskTone(score);
  const active = countActiveAlerts(alerts);

  return (
    <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <KpiCard
        label="Total Portfolio Value"
        footer={
          summary && (
            <>
              {summary.priced_position_count}/{summary.position_count} positions priced · base {summary.base_currency}
            </>
          )
        }
      >
        <div className="num text-2xl font-semibold text-zinc-50">{formatMoney(summary?.total_value, "USD")}</div>
      </KpiCard>

      <KpiCard
        label="Total Unrealized P&L"
        footer={summary && <>Cost basis {formatMoney(summary.total_cost, "USD")}</>}
      >
        <div className="flex items-baseline gap-3">
          <span className={`num text-2xl font-semibold ${pnlColor(pnl)}`}>{formatSignedMoney(pnl, "USD")}</span>
          <span className={`num text-sm font-medium ${pnlColor(pnl)}`}>
            {formatPct(summary?.total_pnl_pct, 2, true)}
          </span>
        </div>
      </KpiCard>

      <KpiCard label="Weighted Risk Score">
        <div className="flex items-center gap-4">
          <RiskGauge score={score} />
          <div>
            <div className={`text-sm font-semibold tracking-wider ${tone.text}`}>{summary?.risk_level ?? "N/A"}</div>
            <div className="mt-0.5 text-[11px] leading-snug text-zinc-500">
              Market-value weighted
              <br />
              0 calm · 100 extreme
            </div>
          </div>
        </div>
      </KpiCard>

      <KpiCard label="Active Risk Alerts" footer={<>Raised today (UTC) · {alerts.length} in log</>}>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Bell className={`h-5 w-5 ${active.total ? "text-amber-400" : "text-zinc-600"}`} />
            <span className="num text-2xl font-semibold text-zinc-50">{active.total}</span>
            {active.critical > 0 && (
              <span className="rounded-sm border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-rose-400">
                {active.critical} HIGH+
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded border border-zinc-700 bg-zinc-800/80 px-3 py-1.5 text-xs font-medium text-zinc-200 transition hover:border-emerald-500/50 hover:text-emerald-300 disabled:cursor-wait disabled:opacity-60"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            {refreshing ? "Refreshing" : "Refresh Data"}
          </button>
        </div>
      </KpiCard>
    </section>
  );
}
