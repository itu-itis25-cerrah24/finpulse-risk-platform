import { API_BASE_URL } from "../config";
import type { NewPosition, Portfolio, RiskAlert, StockDetail } from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Turn FastAPI's `{detail: string | ValidationError[]}` into a readable message. */
function extractDetail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join("; ");
    }
  }
  return fallback;
}

const UNREACHABLE_MESSAGE = "Cannot reach the FinPulse API. Is the backend running on port 8000?";
// Status codes the Vite dev proxy returns when FastAPI is down.
const GATEWAY_ERRORS = new Set([502, 503, 504]);

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, UNREACHABLE_MESSAGE);
  }
  if (GATEWAY_ERRORS.has(response.status)) throw new ApiError(response.status, UNREACHABLE_MESSAGE);

  if (response.status === 204) return undefined as T;

  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, extractDetail(body, `Request failed (${response.status})`));
  }
  return body as T;
}

export const api = {
  getPortfolio: (signal?: AbortSignal) => request<Portfolio>("/api/portfolio", { signal }),

  addPosition: (payload: NewPosition) =>
    request<unknown>("/api/portfolio", { method: "POST", body: JSON.stringify(payload) }),

  deletePosition: (id: number) => request<void>(`/api/portfolio/${id}`, { method: "DELETE" }),

  getStockDetail: (symbol: string, signal?: AbortSignal) =>
    request<StockDetail>(`/api/stock/${encodeURIComponent(symbol)}/history`, { signal }),

  // Alert rules are re-evaluated by GET /api/portfolio, so skip the duplicate work here.
  getAlerts: (limit = 50, signal?: AbortSignal) =>
    request<RiskAlert[]>(`/api/alerts?limit=${limit}&refresh=false`, { signal }),
};
