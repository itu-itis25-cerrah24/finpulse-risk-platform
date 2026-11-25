import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { Portfolio, RiskAlert } from "../api/types";
import { AUTO_REFRESH_MS } from "../config";

export interface DashboardState {
  portfolio: Portfolio | null;
  alerts: RiskAlert[];
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  lastUpdated: Date | null;
  refresh: () => Promise<void>;
}

/**
 * Loads the portfolio and alerts together. The portfolio call runs first
 * because it is what evaluates and persists new alerts on the backend.
 */
export function useDashboard(): DashboardState {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [alerts, setAlerts] = useState<RiskAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setRefreshing(true);

    try {
      const nextPortfolio = await api.getPortfolio(controller.signal);
      const nextAlerts = await api.getAlerts(50, controller.signal);
      setPortfolio(nextPortfolio);
      setAlerts(nextAlerts);
      setLastUpdated(new Date());
      setError(null);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : "Unexpected error");
    } finally {
      if (controllerRef.current === controller) {
        setRefreshing(false);
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), AUTO_REFRESH_MS);
    return () => {
      window.clearInterval(timer);
      controllerRef.current?.abort();
    };
  }, [refresh]);

  return { portfolio, alerts, loading, refreshing, error, lastUpdated, refresh };
}
