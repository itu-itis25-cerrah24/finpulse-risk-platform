/** TypeScript mirror of the FastAPI response schemas (backend/schemas.py). */

export type DailyRiskFlag = "HIGH_DROP" | "HIGH_SPIKE" | "NORMAL";
export type SentimentLabel = "BULLISH" | "BEARISH" | "NEUTRAL";
export type RiskLevel = "LOW" | "MODERATE" | "HIGH";
export type AlertSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type AlertType =
  | "HIGH_DROP"
  | "HIGH_SPIKE"
  | "HIGH_RISK_SCORE"
  | "BEARISH_SENTIMENT"
  | "DEEP_DRAWDOWN";

export interface QuantMetrics {
  annualized_volatility_pct: number | null;
  var_95_pct: number | null;
  max_drawdown_pct: number | null;
  sharpe_ratio: number | null;
  observations: number;
}

export interface Sentiment {
  label: SentimentLabel;
  score: number;
  headline_count: number;
}

export interface Headline {
  title: string;
  publisher: string | null;
  link: string | null;
  published_at: string | null;
  sentiment_score: number;
  sentiment_label: SentimentLabel;
}

export interface Position {
  id: number;
  symbol: string;
  shares: number;
  avg_cost: number;
  risk_threshold_pct: number;
  currency: string | null;
  data_available: boolean;
  price: number | null;
  previous_close: number | null;
  daily_change_pct: number | null;
  daily_flag: DailyRiskFlag;
  market_value: number | null;
  cost_basis: number;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  fx_rate_to_usd: number | null;
  market_value_usd: number | null;
  unrealized_pnl_usd: number | null;
  quant: QuantMetrics;
  sentiment: Sentiment;
  risk_score: number;
  risk_level: RiskLevel;
}

export interface PortfolioSummary {
  base_currency: string;
  total_value: number;
  total_cost: number;
  total_pnl: number;
  total_pnl_pct: number | null;
  weighted_risk_score: number | null;
  risk_level: RiskLevel | null;
  position_count: number;
  priced_position_count: number;
  as_of: string;
}

export interface Portfolio {
  summary: PortfolioSummary;
  positions: Position[];
}

export interface PricePoint {
  date: string;
  close: number;
}

export interface StockDetail {
  symbol: string;
  currency: string | null;
  price: number | null;
  previous_close: number | null;
  daily_change_pct: number | null;
  history: PricePoint[];
  headlines: Headline[];
  sentiment: Sentiment;
  quant: QuantMetrics;
  risk_score: number;
  risk_level: RiskLevel;
}

export interface RiskAlert {
  id: number;
  symbol: string;
  alert_type: AlertType;
  message: string;
  severity: AlertSeverity;
  created_at: string;
}

export interface NewPosition {
  symbol: string;
  shares: number;
  avg_cost: number;
  risk_threshold_pct: number;
}
