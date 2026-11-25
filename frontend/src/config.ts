/**
 * API origin. Empty by default so requests go to same-origin `/api/...`,
 * which the Vite dev server proxies to FastAPI (see vite.config.ts).
 * Set VITE_API_BASE_URL for deployments where the API lives elsewhere.
 */
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");

/** How often the dashboard re-polls the backend (backend caches quotes for 5 min). */
export const AUTO_REFRESH_MS = 60_000;
