import { ChevronDown, FlaskConical } from "lucide-react";
import { useState } from "react";

import { MonteCarloPanel } from "./MonteCarloPanel";
import { StressTestPanel } from "./StressTestPanel";

const STORAGE_KEY = "finpulse.riskLab.open";

function readOpen(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

/** Full-width, collapsible Risk Lab: Monte Carlo fan chart beside the stress-test simulator. */
export function RiskLab({ refreshKey }: { refreshKey: unknown }) {
  const [open, setOpen] = useState(readOpen);

  const toggle = () => {
    setOpen((value) => {
      try {
        window.localStorage.setItem(STORAGE_KEY, String(!value));
      } catch {
        // Storage can be unavailable (private mode); the toggle still works for this session.
      }
      return !value;
    });
  };

  return (
    <section aria-labelledby="risk-lab-title">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="panel flex w-full items-center justify-between px-4 py-2.5 text-left transition hover:border-zinc-700"
      >
        <span className="flex items-center gap-2">
          <FlaskConical className="h-3.5 w-3.5 text-sky-400" />
          <span id="risk-lab-title" className="panel-title text-zinc-300">
            Risk Lab
          </span>
          <span className="text-[11px] text-zinc-500">Monte Carlo simulation &amp; stress testing</span>
        </span>
        <ChevronDown className={`h-4 w-4 text-zinc-500 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-12">
          <div className="min-w-0 xl:col-span-7">
            <MonteCarloPanel refreshKey={refreshKey} />
          </div>
          <div className="min-w-0 xl:col-span-5">
            <StressTestPanel refreshKey={refreshKey} />
          </div>
        </div>
      )}
    </section>
  );
}
