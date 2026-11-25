import { LoaderCircle, X } from "lucide-react";
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";

import { api } from "../api/client";

interface AddPositionModalProps {
  open: boolean;
  onClose: () => void;
  onAdded: (symbol: string) => void;
}

interface FormState {
  symbol: string;
  shares: string;
  avgCost: string;
  threshold: string;
}

const EMPTY_FORM: FormState = { symbol: "", shares: "", avgCost: "", threshold: "3" };
const QUICK_PICKS = ["GARAN.IS", "BIMAS.IS", "KCHOL.IS", "MSFT", "AMZN", "TSLA"];
const SYMBOL_PATTERN = /^[A-Z0-9.\-=^]{1,20}$/;

function validate(form: FormState): string | null {
  const symbol = form.symbol.trim().toUpperCase();
  if (!SYMBOL_PATTERN.test(symbol)) return "Enter a valid ticker, e.g. GARAN.IS or MSFT.";
  if (!(Number(form.shares) > 0)) return "Shares must be greater than zero.";
  if (!(Number(form.avgCost) > 0)) return "Average cost must be greater than zero.";
  const threshold = Number(form.threshold);
  if (!(threshold > 0 && threshold <= 50)) return "Risk threshold must be between 0 and 50%.";
  return null;
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="mt-1 block text-[11px] text-zinc-600">{hint}</span>}
    </label>
  );
}

const inputClass =
  "w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 font-mono text-sm text-zinc-100 placeholder:text-zinc-600 outline-none transition focus:border-emerald-500/70 focus:ring-1 focus:ring-emerald-500/40";

export function AddPositionModal({ open, onClose, onAdded }: AddPositionModalProps) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const symbolRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setForm(EMPTY_FORM);
    setError(null);
    window.setTimeout(() => symbolRef.current?.focus(), 0);

    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const update = (key: keyof FormState) => (event: ChangeEvent<HTMLInputElement>) =>
    setForm((prev) => ({ ...prev, [key]: event.target.value }));

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const validationError = validate(form);
    if (validationError) {
      setError(validationError);
      return;
    }

    const symbol = form.symbol.trim().toUpperCase();
    setSubmitting(true);
    setError(null);
    try {
      await api.addPosition({
        symbol,
        shares: Number(form.shares),
        avg_cost: Number(form.avgCost),
        risk_threshold_pct: Number(form.threshold),
      });
      onAdded(symbol);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add position.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-position-title"
        className="w-full max-w-md rounded-md border border-zinc-700 bg-zinc-900 shadow-2xl shadow-black/60"
      >
        <header className="flex items-center justify-between border-b border-zinc-800 px-5 py-3">
          <div>
            <h2 id="add-position-title" className="text-sm font-semibold text-zinc-100">
              Add Position
            </h2>
            <p className="text-[11px] text-zinc-500">BIST tickers use the .IS suffix · ticker is validated against live data</p>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </header>

        <form onSubmit={handleSubmit} className="space-y-4 px-5 py-4" noValidate>
          <Field label="Ticker Symbol">
            <input
              ref={symbolRef}
              value={form.symbol}
              onChange={update("symbol")}
              placeholder="GARAN.IS"
              autoComplete="off"
              spellCheck={false}
              className={`${inputClass} uppercase`}
            />
          </Field>
          <div className="flex flex-wrap gap-1.5">
            {QUICK_PICKS.map((symbol) => (
              <button
                key={symbol}
                type="button"
                onClick={() => setForm((prev) => ({ ...prev, symbol }))}
                className={`rounded-sm border px-2 py-0.5 font-mono text-[11px] transition ${
                  form.symbol.toUpperCase() === symbol
                    ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300"
                    : "border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200"
                }`}
              >
                {symbol}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Shares">
              <input type="number" min="0" step="any" inputMode="decimal" value={form.shares} onChange={update("shares")} placeholder="100" className={inputClass} />
            </Field>
            <Field label="Avg Cost" hint="In the ticker's currency">
              <input type="number" min="0" step="any" inputMode="decimal" value={form.avgCost} onChange={update("avgCost")} placeholder="125.50" className={inputClass} />
            </Field>
          </div>

          <Field label="Daily Risk Threshold (%)" hint="Moves beyond ±threshold raise HIGH_DROP / HIGH_SPIKE alerts">
            <input type="number" min="0.1" max="50" step="0.1" inputMode="decimal" value={form.threshold} onChange={update("threshold")} className={inputClass} />
          </Field>

          {error && (
            <div className="rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300" role="alert">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 border-t border-zinc-800 pt-4">
            <button type="button" onClick={onClose} className="rounded px-3 py-1.5 text-xs font-medium text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200">
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex items-center gap-1.5 rounded bg-emerald-600 px-4 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-60"
            >
              {submitting && <LoaderCircle className="h-3.5 w-3.5 animate-spin" />}
              {submitting ? "Validating…" : "Add to Portfolio"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
