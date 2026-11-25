# FinPulse — Quantitative Portfolio Risk & Market Sentiment Terminal

[![CI](https://github.com/itu-itis25-cerrah24/finpulse-risk-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/itu-itis25-cerrah24/finpulse-risk-platform/actions/workflows/ci.yml)

A full-stack risk analytics terminal for mixed **BIST (Borsa Istanbul)** and **global equity** portfolios. FinPulse pulls live market data, computes institutional risk metrics from return distributions, scores news sentiment with NLP, and condenses everything into a single composite risk score and an alert stream, presented in a dark, Bloomberg-inspired dashboard.

![FinPulse Terminal](docs/dashboard.png)

---

## Engineering Highlights

| Area | What it does |
| --- | --- |
| **Quant risk engine** | Vectorized NumPy computation of **Annualized Volatility** (σ × √252), **95% Historical VaR** (1-day, empirical 5th percentile), **Max Drawdown** (running-peak method) and **Sharpe Ratio** (4% risk-free rate) from 90 days of daily returns. Pure functions with no I/O, so every metric is unit-tested against hand-calculated values. |
| **Portfolio correlation matrix** | Pairwise **Pearson correlation** of daily returns. Prices are first **inner-joined on common trading dates**, because BIST and NYSE holidays differ, so every return covers the same calendar interval for every symbol. Pairs above ρ = 0.70 are flagged as concentration risk in a hover-enabled heatmap. |
| **Benchmark comparison** | Each stock can be overlaid on its benchmark (**SPY** for US equities, **XU100.IS** for BIST). Both series are rebased to **0% cumulative return** at the start of the selected 1M/2M/3M window, with excess return, **beta** (Cov/Var) and correlation shown alongside. |
| **Correlated Monte Carlo simulation** | Thousands of **Geometric Brownian Motion** paths of total portfolio value in USD. Cross-asset correlation is preserved by colouring independent normal draws with the **Cholesky factor** of the historical log-return covariance; a scaled **diagonal jitter** fallback keeps singular matrices (collinear or single-asset books) factorisable. **Antithetic variates** cut sampling noise, and an optional **seed** makes every run reproducible. Output: p5/p25/p50/p75/p95 fan bands plus simulated **VaR, CVaR (Expected Shortfall)** and probability of loss. |
| **Stress testing** | Instant USD revaluation under preset crises (COVID crash, tech selloff, lira crisis, Fed hike) or custom US-equity / BIST-equity / USD-TRY shocks. Lira holdings take both the equity and the **currency-translation** hit. The UI sliders reprice the book live (debounced). |
| **Markowitz portfolio optimizer** | Long-only mean-variance optimization **without SciPy**. The weight simplex (w ≥ 0, Σw = 1) is sampled with **Dirichlet draws** (uniform and sparse), plus anchors: every single-asset corner, equal weight and the current allocation. Each candidate is scored on annualized return, volatility and Sharpe ratio. The result includes the **max-Sharpe** and **min-volatility** portfolios, the **efficient frontier**, and a USD **rebalancing plan**. Seeded, so results are reproducible. |
| **Composite risk score (0–100)** | Weighted blend of volatility, VaR, drawdown, daily move and news sentiment. Each factor is scaled against a "maximum risk" cap, and weights are **re-normalized when a factor is unavailable**, so a missing news feed never skews the score. |
| **NLP sentiment** | VADER scores every headline (`BULLISH` / `BEARISH` / `NEUTRAL` at ±0.05 compound), then aggregates per symbol. |
| **5-minute TTL caching** | A thread-safe `cachetools.TTLCache` wraps every Yahoo Finance call. Repeat dashboard loads drop from ~5.7 s to ~6 ms. Failed lookups are deliberately **not cached**, so the next request retries. |
| **Multi-currency USD normalization** | TRY- and USD-denominated positions are converted to USD with live FX rates (`TRY=X`) before portfolio totals and the **market-value-weighted** risk score are computed. |
| **Thread-safe alert deduplication** | Alert rules (sharp drop/spike, high risk score, bearish news, deep drawdown) are pure functions. Persistence uses a check-then-insert under a lock, so concurrent refreshes (multiple tabs, React StrictMode) never store the same alert twice in one day. |
| **Concurrent data fetching** | Positions are analyzed in parallel with a `ThreadPoolExecutor`, since the work is network-bound. |
| **Graceful degradation** | Missing prices, empty news or upstream outages return well-defined fallbacks instead of 500s. The UI shows `NO DATA` or an offline state. |
| **145 automated tests + CI** | `pytest` suite covering every quant metric, correlation, date alignment, beta and benchmark rebasing, seeded Monte Carlo determinism, optimizer weight validity, frontier dominance, the closed-form minimum-variance check, the Cholesky fallback, the CVaR ≥ VaR invariant, every stress scenario, risk-score edge cases, sentiment and P&L, plus API tests that run against an in-memory database and a fake market data provider (no network needed). **GitHub Actions** runs the backend tests and the strict TypeScript check and production build on every push and pull request to `main`. |

---

## Screenshots

**Quant risk & sentiment deep dive.** 90-day price chart with average-cost reference line, quant breakdown, and scored news feed.

![Quant Risk & Sentiment Deep Dive](docs/deep-dive.png)

**FastAPI interactive docs.** Fully typed request/response schemas generated from Pydantic models.

![FastAPI Interactive Docs](docs/api-docs.png)

---

## Tech Stack

**Backend**
- Python 3.11+ · FastAPI · Uvicorn
- SQLAlchemy 2.0 (typed `Mapped[]` models) · SQLite
- NumPy (quant engine) · yfinance (market data) · vaderSentiment (NLP)
- cachetools (TTL cache) · Pydantic v2 (validation & API schemas)
- pytest · httpx (`TestClient`)

**Frontend**
- React 19 · TypeScript (strict) · Vite
- Tailwind CSS v4 · Recharts · lucide-react

**Infrastructure**
- Docker (multi-stage builds) · Docker Compose · Nginx (static hosting + reverse proxy)
- GitHub Actions (CI: pytest, strict type-check, production build)

---

## Architecture

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │  Browser — React + TypeScript SPA                                    │
 │  KPI bar · Positions · Deep dive · Correlation · Alerts · Risk Lab   │
 └───────────────────────────────┬──────────────────────────────────────┘
                                 │  same-origin  /api/*
 ┌───────────────────────────────▼──────────────────────────────────────┐
 │  Nginx (frontend container)   static assets + reverse proxy /api     │
 └───────────────────────────────┬──────────────────────────────────────┘
                                 │  http://backend:8000
 ┌───────────────────────────────▼──────────────────────────────────────┐
 │  FastAPI (backend container)                     main.py · schemas   │
 │                                                                      │
 │   portfolio_service ──► risk_engine (NumPy · VADER, pure functions)  │
 │          │         ──► monte_carlo · stress_test · optimizer (NumPy)  │
 │          │                                                           │
 │          ├──────────► market_service ──► TTLCache (5 min, locked)    │
 │          │                   │                                       │
 │          ▼                   ▼                                       │
 │   alert_service       Yahoo Finance API (quotes · history · news ·   │
 │   (rules + dedupe)                       FX rates)                   │
 │          │                                                           │
 │          ▼                                                           │
 │   SQLAlchemy ──► SQLite  (watchlist_items · risk_alerts)             │
 └──────────────────────────────────────────────────────────────────────┘
```

**Request flow for `GET /api/portfolio`:** load watchlist rows → fetch quote, 90-day history and news for each symbol in parallel (served from cache when warm) → compute quant metrics, sentiment, P&L and risk score → convert to USD and aggregate → evaluate alert rules and persist new alerts → return one typed JSON payload.

### Repository layout

```
finpulse-risk-platform/
├── backend/
│   ├── main.py                 # FastAPI app, routes, dependency injection
│   ├── database.py             # Engine, session factory, get_db dependency
│   ├── models.py               # WatchlistItem, RiskAlert ORM models
│   ├── schemas.py              # Pydantic request/response contracts
│   ├── seed.py                 # Default watchlist (THYAO.IS, ASELS.IS, AAPL, NVDA)
│   ├── services/
│   │   ├── market_service.py   # yfinance facade + TTL cache + FX
│   │   ├── risk_engine.py      # Volatility, VaR, drawdown, Sharpe, sentiment, score
│   │   ├── monte_carlo.py      # Correlated GBM, Cholesky + jitter, VaR/CVaR
│   │   ├── stress_test.py      # Preset & custom factor-shock scenarios
│   │   ├── optimizer.py        # Markowitz simplex search, efficient frontier
│   │   ├── portfolio_service.py# Orchestration + USD aggregation
│   │   └── alert_service.py    # Alert rules + deduplicated persistence
│   ├── tests/                  # 145 pytest tests
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/                # Typed client + response types
│   │   ├── hooks/              # useDashboard, useStockDetail, useApiResource
│   │   ├── components/         # KPI bar, table, deep dive, heatmap, alerts, modal
│   │   │   └── risklab/        # Monte Carlo fan chart, stress test, MPT optimizer
│   │   └── lib/format.ts       # Number/currency formatting, semantic colors
│   ├── nginx.conf
│   └── Dockerfile
├── .github/workflows/ci.yml    # CI pipeline
├── docs/                       # Screenshots
└── docker-compose.yml
```

---

## Quick Start

### Option A: Docker (recommended)

Requires Docker Desktop (or Docker Engine with the Compose plugin).

```bash
docker compose up --build
```

| Service | URL |
| --- | --- |
| Dashboard | http://localhost:8080 |
| API docs (Swagger UI) | http://localhost:8000/docs |

The SQLite database lives in the named volume `finpulse-data`, so your watchlist survives restarts. Run `docker compose down -v` to reset it.

### Option B: Local development

Requires **Python 3.11+** and **Node.js 20.19+**.

**1. Backend** (terminal 1)

```bash
cd backend
python -m venv .venv
# Windows:  .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pytest                                   # 145 tests
uvicorn main:app --reload --port 8000
```

**2. Frontend** (terminal 2)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to `http://127.0.0.1:8000`.

On first startup the backend seeds a demo portfolio of `THYAO.IS`, `ASELS.IS`, `AAPL` and `NVDA`.

### Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `FINPULSE_DATABASE_URL` | SQLite file at `backend/finpulse.db` | SQLAlchemy database URL |
| `FINPULSE_CORS_ORIGINS` | `http://localhost:5173,…` | Comma-separated allowed origins |
| `VITE_BACKEND_URL` | `http://127.0.0.1:8000` | Dev-server proxy target |
| `VITE_API_BASE_URL` | *(empty, same origin)* | API origin baked into production builds |

---

## API Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/portfolio` | All positions with live prices, quant metrics, sentiment and risk score, plus a USD portfolio summary (total value, P&L, weighted risk score). Also evaluates alert rules. |
| `POST` | `/api/portfolio` | Add a position `{symbol, shares, avg_cost, risk_threshold_pct}`. Validates the ticker against live data. Returns `201`, or `409` for a duplicate and `404` for an unknown symbol. |
| `DELETE` | `/api/portfolio/{item_id}` | Remove a position. Returns `204`, or `404` if not found. |
| `GET` | `/api/portfolio/correlation` | Pearson correlation matrix of date-aligned 90-day daily returns, average pairwise ρ, and pairs above 0.70 (concentration risk). |
| `GET` | `/api/portfolio/monte-carlo?days=90&simulations=1000&seed=42&drift=historical` | Correlated GBM simulation of total USD value: daily p5/p25/p50/p75/p95 bands, expected value and return, simulated 95% VaR and CVaR, probability of loss. `days` 1–252, `simulations` 100–5000, `drift` `historical` or `zero`. Returns `422` if fewer than 5 aligned returns exist. |
| `GET` | `/api/portfolio/optimize?samples=4000&seed=42` | Markowitz long-only optimization over USD log-returns. Returns the current, max-Sharpe and min-volatility portfolios (return, volatility, Sharpe, weights), a ~300-point risk/return cloud, the efficient frontier, and per-symbol rebalancing for both targets (current / target / Δ weight, USD trade, `BUY` / `SELL` / `HOLD`). `samples` is 100–20000. A single holding returns its current 100% weight. Returns `422` with fewer than 5 aligned returns. |
| `GET` | `/api/portfolio/stress-test/scenarios` | Preset crisis scenarios and their shocks. |
| `POST` | `/api/portfolio/stress-test` | Body `{"scenario": "covid_crash" \| "tech_selloff" \| "usd_try_spike" \| "rate_hike"}` **or** custom `{us_equity_shock_pct, bist_equity_shock_pct, usd_try_shock_pct}` (mixing both is a `422`). Returns per-holding and total USD value before/after, P&L in USD and %, and the worst-hit position. |
| `GET` | `/api/stock/{symbol}/history` | 90-day closing prices, sentiment-scored headlines, quant metrics and risk score for any symbol. |
| `GET` | `/api/stock/{symbol}/benchmark?days=90` | Cumulative % return of the symbol vs SPY (or XU100.IS for `.IS` symbols), rebased to 0% at the window start, plus excess return, beta and correlation. Returns `503` if benchmark data is unavailable. |
| `GET` | `/api/alerts?limit=50&refresh=true` | Most recent risk alerts, newest first, with severity `LOW` / `MEDIUM` / `HIGH` / `CRITICAL`. |
| `GET` | `/api/health` | Liveness probe used by the Docker health check. |

---

## Risk Methodology

| Metric | Definition |
| --- | --- |
| Daily return | rₜ = Pₜ / Pₜ₋₁ − 1 on adjusted closes |
| Annualized volatility | sample std-dev(r) × √252 |
| 95% Historical VaR | −(5th percentile of r), floored at 0, reported as a positive 1-day loss % |
| Max drawdown | min(Pₜ / max(P₀…Pₜ) − 1) |
| Sharpe ratio | (mean(r) − 4% / 252) / std-dev(r) × √252 |
| Correlation | Pearson ρ of daily returns, computed on prices inner-joined by date |
| Beta | Cov(r_asset, r_benchmark) / Var(r_benchmark) |
| Cumulative return | (Pₜ / P_start − 1) × 100, rebased at the window start |
| Risk score | 30% volatility (cap 60%) · 25% VaR (cap 5%) · 20% drawdown (cap 40%) · 10% daily move (cap 10%) · 15% sentiment |
| Risk level | `LOW` < 35 ≤ `MODERATE` < 65 ≤ `HIGH` |

### Monte Carlo simulation (correlated GBM)

1. **USD log-returns.** Non-USD prices are divided by the same-day `<CCY>=X` close (e.g. `TRY=X`), so a BIST holding carries lira risk. Series are inner-joined by date, then ℓₜ = ln(Pₜ / Pₜ₋₁).
2. **Parameters.** The drift is m = mean(ℓ) (GBM's μ − ½σ² term) and the covariance is Σ = cov(ℓ). With `drift=zero`, m = −½·diag(Σ), so E[Sₜ] = S₀ and only dispersion remains. This is useful because a 90-day mean extrapolated over 180 days can be extreme.
3. **Cholesky.** Factor Σ = L Lᵀ. If Σ is only positive semi-definite (collinear holdings, zero variance, more assets than observations), add εI with ε = 10⁻¹⁰ · mean(diag Σ) and grow it tenfold until the factorisation succeeds. The jitter used is returned in the response.
4. **Paths.** For each day: ln Sₜ₊₁ = ln Sₜ + m + L z with z ~ N(0, I). Because Cov(L z) = L Lᵀ = Σ, the shocks keep the historical correlations. Each z is paired with −z (antithetic variates). Portfolio value = Σᵢ Vᵢ,₀ · exp(cumulative log growth).
5. **Risk measures** on the horizon P&L (X = V_T − V₀):
   - VaR₉₅ = −q₀.₀₅(X)
   - CVaR₉₅ = −E[X | X ≤ q₀.₀₅(X)] (Expected Shortfall: the mean loss in the worst 5% of paths, so CVaR ≥ VaR by construction)
   - P(loss) = share of paths with V_T < V₀

### Portfolio optimization (Markowitz MPT)

1. **Inputs.** The optimizer uses the same date-aligned USD log-returns as the Monte Carlo engine. The annualized mean is μ = 252 · mean(ℓ) and the covariance is Σ = 252 · cov(ℓ). When Σ is singular, the Cholesky jitter fallback is added to it.
2. **Candidates.** Long-only weights live on the simplex {w ≥ 0, Σw = 1}. Half the samples are Dirichlet(1), which is uniform on the simplex. The other half are Dirichlet(0.3), which pushes weight toward the edges and corners, where constrained optima usually sit.
3. **Anchors.** The current allocation, every 100% single-asset corner and equal weight are always included. As a result, the min-volatility portfolio is never riskier than the current one, and the max-Sharpe portfolio never has a lower Sharpe ratio.
4. **Scoring.** For every candidate, return = wᵀμ, volatility = √(wᵀΣw) and Sharpe = (return − 4%) / volatility. All candidates are scored at once in a single vectorized `einsum`.
5. **Efficient frontier.** Candidates are sorted by volatility, and a point is kept if its return beats every lower-risk point (the non-dominated upper envelope). The frontier is thinned to at most 60 points. The scatter cloud is an evenly spaced subset of about 300 candidates.
6. **Rebalancing.** For each holding, Δwᵢ = target − current and the trade is Δwᵢ × total USD value. Trades sum to zero, so the plan is self-financing. Changes under 0.05 percentage points are reported as `HOLD`.

Sampling instead of an exact quadratic-programming solver keeps the backend dependencies to NumPy alone. With 4,000 samples and a handful of holdings, the result lands within about 1 percentage point of the analytic optimum. The tests check the two-asset minimum-variance weight against the closed form w₁ = (σ₂² − σ₁₂) / (σ₁² + σ₂² − 2σ₁₂).

Mean returns estimated from 90 days are noisy, so the max-Sharpe portfolio often concentrates in whichever asset rallied recently. This is the classic estimation-error weakness of MPT, and it's why the min-volatility target is offered alongside it.

### Stress testing

Each holding's USD value is multiplied by (1 + equity shock) ÷ (1 + FX shock). The equity shock is the US or BIST shock, chosen by the `.IS` suffix. The FX shock (USD/TRY % change) applies only to TRY-denominated holdings, so a +25% USD/TRY move alone costs a lira asset 1 − 1/1.25 = 20% in USD. The presets are hypothetical shocks loosely calibrated to past episodes: COVID-19 (Feb–Mar 2020), the 2022 tech de-rating, the Aug 2018 lira crisis, and a surprise Fed tightening.

---

## Testing

```bash
cd backend
pytest -v
```

- `tests/test_risk_engine.py`: volatility, VaR, max drawdown and Sharpe against closed-form values; risk-score bounds, weighting and re-normalization; sentiment classification; P&L and daily-move flags.
- `tests/test_correlation_benchmark.py`: cross-market date alignment, Pearson correlation (±1, hand-calculated, zero-variance and too-few-observation cases), pair ranking, benchmark selection, rebasing, beta and windowing.
- `tests/test_simulation.py`: log-returns and FX conversion; Cholesky on positive-definite, perfectly collinear, linear-combination and zero-variance single-asset matrices; seeded determinism; zero-volatility paths matching the closed form; ρ = ±1 transmission through the Cholesky factor; antithetic mirroring; ordered percentile bands; the zero-drift martingale; hand-calculated VaR/CVaR and the CVaR ≥ VaR invariant; every stress preset, custom FX shocks on `.IS` holdings and input validation; plus API tests for both endpoints.
- `tests/test_optimizer.py` covers:
  - annualization and singular-covariance regularization;
  - simplex sampling (non-negative weights that sum to 1, anchors, seeded);
  - hand-calculated return, volatility and Sharpe;
  - efficient-frontier dominance and thinning;
  - seeded determinism;
  - `min_volatility ≤ current` and `max_sharpe ≥ min_volatility`;
  - the closed-form two-asset minimum-variance weight;
  - single-asset and collinear portfolios;
  - self-financing rebalancing;
  - the `/api/portfolio/optimize` endpoint.
- `tests/test_api.py`: full CRUD, correlation and benchmark endpoints, validation (`409` / `404` / `422`), stock history and alert deduplication, using an in-memory SQLite database and a deterministic fake market data provider.

```bash
cd frontend
npm run build    # strict TypeScript check + production bundle
```

---

## Disclaimer

FinPulse is an educational and portfolio project. Market data comes from Yahoo Finance via the unofficial `yfinance` library and may be delayed or incomplete. Nothing in this application constitutes investment advice.
