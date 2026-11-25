import { useEffect, useState } from "react";

export interface ResourceState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/**
 * Generic fetch-on-change hook with abort handling. Pass `null` as the
 * fetcher to stay idle (e.g. while a feature toggle is off). The previous
 * data is kept on screen while a reload is in flight.
 */
export function useApiResource<T>(
  fetcher: ((signal: AbortSignal) => Promise<T>) | null,
  deps: readonly unknown[],
): ResourceState<T> {
  const [state, setState] = useState<ResourceState<T>>({ data: null, loading: false, error: null });

  useEffect(() => {
    if (!fetcher) {
      setState({ data: null, loading: false, error: null });
      return;
    }
    const controller = new AbortController();
    setState((prev) => ({ ...prev, loading: true, error: null }));

    fetcher(controller.signal)
      .then((data) => setState({ data, loading: false, error: null }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ data: null, loading: false, error: err instanceof Error ? err.message : "Unexpected error" });
      });

    return () => controller.abort();
    // The caller controls when to refetch through `deps` (the fetcher is recreated every render).
  }, deps);

  return state;
}
