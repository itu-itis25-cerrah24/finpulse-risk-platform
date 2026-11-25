import { ArrowDown, ArrowUp, ChevronsUpDown, Plus, Trash2, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { Position } from "../api/types";
import { formatMoney, formatNumber, formatPct, formatSignedMoney, pnlColor } from "../lib/format";
import { RiskScoreBar, SentimentBadge } from "./ui/Badges";

type SortKey =
  | "symbol"
  | "price"
  | "daily_change_pct"
  | "unrealized_pnl_usd"
  | "volatility"
  | "var"
  | "drawdown"
  | "sentiment"
  | "risk_score";

interface Column {
  key: SortKey;
  label: string;
  align: "left" | "right" | "center";
  value: (p: Position) => number | string | null;
}

const COLUMNS: Column[] = [
  { key: "symbol", label: "Symbol", align: "left", value: (p) => p.symbol },
  { key: "price", label: "Last", align: "right", value: (p) => p.price },
  { key: "daily_change_pct", label: "Chg %", align: "right", value: (p) => p.daily_change_pct },
  { key: "unrealized_pnl_usd", label: "Unrl. P&L", align: "right", value: (p) => p.unrealized_pnl_usd },
  { key: "volatility", label: "Ann. Vol", align: "right", value: (p) => p.quant.annualized_volatility_pct },
  { key: "var", label: "VaR 95", align: "right", value: (p) => p.quant.var_95_pct },
  { key: "drawdown", label: "Max DD", align: "right", value: (p) => p.quant.max_drawdown_pct },
  { key: "sentiment", label: "Sentiment", align: "center", value: (p) => p.sentiment.score },
  { key: "risk_score", label: "Risk", align: "left", value: (p) => p.risk_score },
];

const alignClass = { left: "text-left", right: "text-right", center: "text-center" } as const;

interface PortfolioTableProps {
  positions: Position[];
  selectedSymbol: string | null;
  onSelect: (symbol: string) => void;
  onDelete: (position: Position) => Promise<void>;
  onAdd: () => void;
}

function compareValues(a: number | string | null, b: number | string | null): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1; // nulls always last
  if (b == null) return -1;
  if (typeof a === "string" && typeof b === "string") return a.localeCompare(b);
  return Number(a) - Number(b);
}

export function PortfolioTable({ positions, selectedSymbol, onSelect, onDelete, onAdd }: PortfolioTableProps) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "risk_score", dir: -1 });
  const [pendingDelete, setPendingDelete] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);

  // Two-step delete: the confirmation state expires after a few seconds.
  useEffect(() => {
    if (pendingDelete == null) return;
    const timer = window.setTimeout(() => setPendingDelete(null), 3500);
    return () => window.clearTimeout(timer);
  }, [pendingDelete]);

  const sorted = useMemo(() => {
    const column = COLUMNS.find((c) => c.key === sort.key) ?? COLUMNS[0];
    return [...positions].sort((a, b) => {
      const result = compareValues(column.value(a), column.value(b));
      const bothPresent = column.value(a) != null && column.value(b) != null;
      return bothPresent ? result * sort.dir : result;
    });
  }, [positions, sort]);

  const toggleSort = (key: SortKey) =>
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === 1 ? -1 : 1 } : { key, dir: key === "symbol" ? 1 : -1 }));

  const handleDelete = async (position: Position) => {
    if (pendingDelete !== position.id) {
      setPendingDelete(position.id);
      return;
    }
    setDeleting(position.id);
    try {
      await onDelete(position);
    } finally {
      setDeleting(null);
      setPendingDelete(null);
    }
  };

  return (
    <section className="panel overflow-hidden">
      <header className="panel-header">
        <div className="flex items-center gap-3">
          <h2 className="panel-title">Positions</h2>
          <span className="num text-[11px] text-zinc-500">{positions.length} holdings</span>
        </div>
        <button
          type="button"
          onClick={onAdd}
          className="inline-flex items-center gap-1.5 rounded border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-300 transition hover:bg-emerald-500/20"
        >
          <Plus className="h-3.5 w-3.5" />
          Add Position
        </button>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[920px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-zinc-800 bg-zinc-950/40">
              {COLUMNS.map((column) => {
                const active = sort.key === column.key;
                const Icon = !active ? ChevronsUpDown : sort.dir === 1 ? ArrowUp : ArrowDown;
                return (
                  <th
                    key={column.key}
                    className={`px-3 py-2 ${alignClass[column.align]} text-[10px] font-semibold tracking-[0.1em] text-zinc-500 uppercase first:pl-4`}
                  >
                    <button
                      type="button"
                      onClick={() => toggleSort(column.key)}
                      className={`inline-flex items-center gap-1 uppercase transition hover:text-zinc-200 ${active ? "text-zinc-200" : ""}`}
                    >
                      {column.label}
                      <Icon className={`h-3 w-3 ${active ? "text-emerald-400" : "opacity-40"}`} />
                    </button>
                  </th>
                );
              })}
              <th className="w-12 px-3 py-2" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((p) => {
              const selected = p.symbol === selectedSymbol;
              const flagged = p.daily_flag !== "NORMAL";
              return (
                <tr
                  key={p.id}
                  onClick={() => onSelect(p.symbol)}
                  className={`cursor-pointer border-b border-zinc-800/70 transition-colors last:border-b-0 ${
                    selected ? "bg-emerald-500/[0.06]" : "hover:bg-zinc-800/40"
                  }`}
                >
                  <td className={`border-l-2 py-2.5 pr-3 pl-[14px] ${selected ? "border-emerald-400" : "border-transparent"}`}>
                    <div className="font-mono text-[13px] font-semibold text-zinc-100">{p.symbol}</div>
                    <div className="num text-[11px] text-zinc-500">
                      {formatNumber(p.shares, 0)} @ {formatMoney(p.avg_cost, p.currency)}
                    </div>
                  </td>
                  <td className="num px-3 text-right text-zinc-100">
                    {p.data_available ? formatMoney(p.price, p.currency) : <span className="text-zinc-600">NO DATA</span>}
                  </td>
                  <td className={`num px-3 text-right font-medium ${pnlColor(p.daily_change_pct)}`}>
                    <span className="inline-flex items-center justify-end gap-1">
                      {flagged && (
                        <TriangleAlert
                          className={`h-3.5 w-3.5 ${p.daily_flag === "HIGH_DROP" ? "text-rose-400" : "text-emerald-400"}`}
                          aria-label={p.daily_flag}
                        />
                      )}
                      {formatPct(p.daily_change_pct, 2, true)}
                    </span>
                  </td>
                  <td className="num px-3 text-right">
                    <div className={pnlColor(p.unrealized_pnl_usd)}>{formatSignedMoney(p.unrealized_pnl_usd, "USD")}</div>
                    <div className={`text-[11px] ${pnlColor(p.unrealized_pnl_pct)} opacity-80`}>
                      {formatPct(p.unrealized_pnl_pct, 2, true)}
                    </div>
                  </td>
                  <td className="num px-3 text-right text-zinc-300">{formatPct(p.quant.annualized_volatility_pct, 1)}</td>
                  <td className="num px-3 text-right text-zinc-300">{formatPct(p.quant.var_95_pct, 2)}</td>
                  <td className="num px-3 text-right text-rose-300/90">{formatPct(p.quant.max_drawdown_pct, 1)}</td>
                  <td className="px-3 text-center">
                    <SentimentBadge label={p.sentiment.label} />
                  </td>
                  <td className="px-3">
                    <RiskScoreBar score={p.risk_score} />
                  </td>
                  <td className="px-3 text-right">
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        void handleDelete(p);
                      }}
                      disabled={deleting === p.id}
                      title={pendingDelete === p.id ? "Click again to confirm" : `Remove ${p.symbol}`}
                      className={`inline-flex items-center gap-1 rounded px-1.5 py-1 text-[10px] font-semibold transition ${
                        pendingDelete === p.id
                          ? "bg-rose-500/20 text-rose-300"
                          : "text-zinc-600 hover:bg-rose-500/10 hover:text-rose-400"
                      }`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      {pendingDelete === p.id && "CONFIRM"}
                    </button>
                  </td>
                </tr>
              );
            })}
            {positions.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length + 1} className="px-4 py-12 text-center text-sm text-zinc-500">
                  No positions yet. Add a BIST or global ticker to start tracking risk.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
