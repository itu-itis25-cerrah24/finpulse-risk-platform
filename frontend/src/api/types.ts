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

export interface CorrelationPair {
  symbol_a: string;
  symbol_b: string;
  correlation: number;
}

export interface CorrelationMatrix {
  symbols: string[];
  /** Pearson coefficients; null where undefined (e.g. zero-variance series). */
  matrix: (number | null)[][];
  observations: number;
  start_date: string | null;
  end_date: string | null;
  average_correlation: number | null;
  high_correlation_threshold: number;
  high_correlation_pairs: CorrelationPair[];
  excluded_symbols: string[];
}

export interface BenchmarkPoint {
  date: string;
  asset_pct: number;
  benchmark_pct: number;
}

export interface BenchmarkComparison {
  symbol: string;
  benchmark_symbol: string;
  window_days: number;
  points: BenchmarkPoint[];
  asset_return_pct: number | null;
  benchmark_return_pct: number | null;
  excess_return_pct: number | null;
  beta: number | null;
  correlation: number | null;
  observations: number;
}

// ---------------------------------------------------------------------------
// Risk Lab
// ---------------------------------------------------------------------------

export type DriftModel = "historical" | "zero";

export interface MonteCarloBand {
  /** Trading days from today; day 0 is the current value. */
  day: number;
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
}

export interface SimulatedHolding {
  symbol: string;
  value_usd: number;
  weight_pct: number;
  annualized_drift_pct: number;
  annualized_volatility_pct: number;
  fx_adjusted: boolean;
}

export interface MonteCarloResult {
  horizon_days: number;
  simulations: number;
  seed: number | null;
  drift_model: DriftModel;
  confidence: number;
  observations: number;
  start_date: string;
  end_date: string;
  cholesky_jitter: number;
  holdings: SimulatedHolding[];
  initial_value: number;
  expected_value: number;
  median_value: number;
  expected_return_pct: number;
  /** USD loss at the 95% level (positive = loss). */
  var_95_simulated: number;
  var_95_pct: number;
  /** Expected Shortfall: mean loss beyond VaR, always >= VaR. */
  cvar_95_simulated: number;
  cvar_95_pct: number;
  probability_of_loss_pct: number;
  bands: MonteCarloBand[];
  excluded_symbols: string[];
}

export type ScenarioKey = "covid_crash" | "tech_selloff" | "usd_try_spike" | "rate_hike";
export type MarketSegment = "US_EQUITY" | "BIST_EQUITY";

export interface StressShocks {
  us_equity_shock_pct: number;
  bist_equity_shock_pct: number;
  /** % change in TRY per USD; positive = lira depreciation. */
  usd_try_shock_pct: number;
}

export interface StressScenario extends StressShocks {
  key: ScenarioKey;
  label: string;
  description: string;
}

/** A preset scenario or custom shocks; the API rejects a mix of both. */
export type StressTestRequest = { scenario: ScenarioKey } | StressShocks;

export interface StressImpact {
  symbol: string;
  segment: MarketSegment;
  currency: string | null;
  value_before_usd: number;
  value_after_usd: number;
  pnl_usd: number;
  pnl_pct: number;
  equity_shock_pct: number;
  fx_shock_pct: number;
}

export interface StressTestResult extends StressShocks {
  scenario: ScenarioKey | null;
  label: string;
  positions: StressImpact[];
  total_before_usd: number;
  total_after_usd: number;
  total_pnl_usd: number;
  total_pnl_pct: number | null;
  worst_hit_symbol: string | null;
  excluded_symbols: string[];
}

export type RebalanceAction = "BUY" | "SELL" | "HOLD";

export interface PortfolioWeight {
  symbol: string;
  weight_pct: number;
}

export interface FrontierPoint {
  expected_return_pct: number;
  volatility_pct: number;
  sharpe_ratio: number | null;
}

export interface OptimalPortfolio extends FrontierPoint {
  weights: PortfolioWeight[];
}

export interface AssetMoments {
  symbol: string;
  value_usd: number;
  expected_return_pct: number;
  volatility_pct: number;
}

export interface RebalanceRow {
  symbol: string;
  current_weight_pct: number;
  target_weight_pct: number;
  delta_weight_pct: number;
  /** Positive = buy, negative = sell. */
  delta_usd: number;
  action: RebalanceAction;
}

export type OptimizationTarget = "max_sharpe" | "min_volatility";

export interface OptimizationResult {
  samples: number;
  seed: number | null;
  risk_free_rate_pct: number;
  observations: number;
  start_date: string;
  end_date: string;
  covariance_jitter: number;
  total_value_usd: number;
  assets: AssetMoments[];
  current_portfolio: OptimalPortfolio;
  max_sharpe: OptimalPortfolio;
  min_volatility: OptimalPortfolio;
  frontier_cloud: FrontierPoint[];
  efficient_frontier: FrontierPoint[];
  rebalancing: Record<OptimizationTarget, RebalanceRow[]>;
  excluded_symbols: string[];
}

export interface NewPosition {
  symbol: string;
  shares: number;
  avg_cost: number;
  risk_threshold_pct: number;
}
