import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { StockDetail } from "../api/types";

interface StockDetailState {
  detail: StockDetail | null;
  loading: boolean;
  error: string | null;
}

/**
 * Fetches the deep-dive analytics for one symbol. `refreshKey` lets the parent
 * force a reload (e.g. after the global "Refresh Data" button).
 */
export function useStockDetail(symbol: string | null, refreshKey: unknown): StockDetailState {
  const [state, setState] = useState<StockDetailState>({ detail: null, loading: false, error: null });

  useEffect(() => {
    if (!symbol) {
      setState({ detail: null, loading: false, error: null });
      return;
    }

    const controller = new AbortController();
    // Keep the previous chart on screen while the same symbol reloads.
    setState((prev) => ({
      detail: prev.detail?.symbol === symbol ? prev.detail : null,
      loading: true,
      error: null,
    }));

    api
      .getStockDetail(symbol, controller.signal)
      .then((detail) => setState({ detail, loading: false, error: null }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ detail: null, loading: false, error: err instanceof Error ? err.message : "Unexpected error" });
      });

    return () => controller.abort();
  }, [symbol, refreshKey]);

  return state;
}
