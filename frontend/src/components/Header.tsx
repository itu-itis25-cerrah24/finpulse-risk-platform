import { Activity } from "lucide-react";
import { useEffect, useState } from "react";

interface HeaderProps {
  connected: boolean;
  lastUpdated: Date | null;
}

const CLOCKS = [
  { label: "IST", timeZone: "Europe/Istanbul" },
  { label: "NY", timeZone: "America/New_York" },
  { label: "UTC", timeZone: "UTC" },
] as const;

function useNow(intervalMs = 1000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

function formatClock(date: Date, timeZone: string): string {
  return date.toLocaleTimeString("en-GB", { timeZone, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function Header({ connected, lastUpdated }: HeaderProps) {
  const now = useNow();

  return (
    <header className="sticky top-0 z-40 border-b border-zinc-800 bg-zinc-950/90 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-[1680px] items-center justify-between gap-4 px-4">
        <div className="flex items-center gap-3">
          <div className="flex h-7 w-7 items-center justify-center rounded border border-emerald-500/40 bg-emerald-500/10">
            <Activity className="h-4 w-4 text-emerald-400" />
          </div>
          <div className="leading-tight">
            <div className="font-mono text-sm font-semibold tracking-[0.2em] text-zinc-50">FINPULSE</div>
            <div className="text-[10px] tracking-wider text-zinc-500 uppercase">Portfolio Risk &amp; Sentiment Terminal</div>
          </div>
        </div>

        <div className="hidden items-center gap-5 md:flex">
          {CLOCKS.map((clock) => (
            <div key={clock.label} className="flex items-baseline gap-1.5">
              <span className="text-[10px] font-semibold tracking-wider text-zinc-600">{clock.label}</span>
              <span className="num text-xs text-zinc-300">{formatClock(now, clock.timeZone)}</span>
            </div>
          ))}
        </div>

        <div className="flex items-center gap-4 text-[11px]">
          {lastUpdated && (
            <span className="hidden text-zinc-500 sm:inline">
              Updated <span className="num text-zinc-300">{formatClock(lastUpdated, Intl.DateTimeFormat().resolvedOptions().timeZone)}</span>
            </span>
          )}
          <span className="flex items-center gap-1.5">
            <span className="relative flex h-2 w-2">
              {connected && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />}
              <span className={`relative inline-flex h-2 w-2 rounded-full ${connected ? "bg-emerald-400" : "bg-rose-500"}`} />
            </span>
            <span className={`font-mono font-semibold tracking-wider ${connected ? "text-emerald-400" : "text-rose-400"}`}>
              {connected ? "LIVE" : "OFFLINE"}
            </span>
          </span>
        </div>
      </div>
    </header>
  );
}
