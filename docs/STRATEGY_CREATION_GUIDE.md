# Algorithmic Trading & Strategy Creation Guide

A comprehensive, beginner-friendly guide to understanding quantitative trading strategies, how technical indicators work, and how to create, test, and run new strategies inside **Strategy-Lab**.

---

## Table of Contents
1. [Introduction to Algorithmic & Strategy Trading](#1-introduction-to-algorithmic--strategy-trading)
2. [Anatomy of a Trading Strategy](#2-anatomy-of-a-trading-strategy)
3. [Understanding Technical Indicators (Intuition & Math)](#3-understanding-technical-indicators-intuition--math)
   - [Simple Moving Average (SMA)](#simple-moving-average-sma)
   - [Exponential Moving Average (EMA)](#exponential-moving-average-ema)
   - [Relative Strength Index (RSI)](#relative-strength-index-rsi)
   - [Moving Average Convergence Divergence (MACD)](#moving-average-convergence-divergence-macd)
   - [Bollinger Bands (BBands)](#bollinger-bands-bbands)
   - [Average True Range (ATR)](#average-true-range-atr)
   - [Volume Indicators (Rel Volume, CMF, OBV)](#volume-indicators)
4. [How Strategy-Lab Works: The JSON Strategy Spec](#4-how-strategy-lab-works-the-json-strategy-spec)
   - [Condition Tree DSL (Entry & Exit Logic)](#condition-tree-dsl)
   - [Execution Model & No-Lookahead Bias](#execution-model--no-lookahead-bias)
5. [Step-by-Step Tutorial: Creating Your First Strategy](#5-step-by-step-tutorial-creating-your-first-strategy)
6. [Testing & Running Your Strategy](#6-testing--running-your-strategy)
7. [Repository File Map (Where Everything Lives)](#7-repository-file-map-where-everything-lives)

---

## 1. Introduction to Algorithmic & Strategy Trading

In discretionary trading, a human trader looks at a chart, feels an emotion (fear, greed, optimism), and clicks "Buy" or "Sell". This often leads to inconsistent decisions, emotional mistakes, and poor risk management.

**Algorithmic (Systematic) Trading** replaces emotion with explicit, verifiable mathematical rules:
1. **Rule-Based Entry:** If condition $A$ and condition $B$ are true on day $t$, buy at the open of day $t+1$.
2. **Rule-Based Exit:** If price drops by $5\%$, cut the loss. If price rises for 10 days, take profit.
3. **Statistical Backtesting:** Run this exact recipe over 10–12 years of historical stock data across hundreds of companies to see whether it genuinely generates an "edge" (consistent positive expected return after fees and slippage) or just random noise.

---

## 2. Anatomy of a Trading Strategy

Every valid quantitative trading strategy consists of four core pillars:

```
+-----------------------------------------------------------+
|                      STRATEGY                             |
+-----------------------------------------------------------+
| 1. Universe     : What stocks can we trade? (e.g. S&P 500)|
| 2. Timeframe    : Bar resolution (e.g. 1d = Daily bars)   |
| 3. Entry Signal : Strict mathematical trigger to buy/sell |
| 4. Exit Rules   : How to close the position               |
|      - Time Stop  : e.g. Close after 10 days              |
|      - Stop Loss  : e.g. Cut loss if down -5%             |
|      - Take Profit: e.g. Book gain if up +10%             |
|      - Dynamic/ATR: e.g. Trailing stop by volatility      |
+-----------------------------------------------------------+
```

### The Life Cycle of a Trade
In Strategy-Lab:
* **Bar $t$ Close (Day 1):** The market closes at 4:00 PM. Our algorithm calculates indicators on daily OHLCV (Open, High, Low, Close, Volume) data. If all entry conditions evaluate to `True`, an entry order is generated.
* **Bar $t+1$ Open (Day 2):** At 9:30 AM next morning, the position is entered at the actual `Open` price plus simulated transaction costs and slippage.
* **Exit Evaluation:** On every subsequent day, the system checks in order:
  1. Did price touch the **Stop Loss**? (If yes, exit immediately).
  2. Did price touch the **Take Profit**?
  3. Did an **indicator exit** trigger? (e.g., RSI crossed back above 50).
  4. Has the **Time Exit** expired? (e.g., held for 10 bars).

---

## 3. Understanding Technical Indicators (Intuition & Math)

Indicators transform raw OHLCV prices into normalized metrics. Here are the most important ones implemented in `lab/indicators.py`:

### Simple Moving Average (SMA)
* **Concept:** The arithmetic average of closing prices over the past $N$ bars.
$$\text{SMA}_N = \frac{1}{N} \sum_{i=0}^{N-1} \text{Close}_{t-i}$$
* **Intuition:** Filters out daily erratic fluctuations to reveal the underlying direction.
* **How traders use it:**
  * **Trend Filter:** If $\text{Close} > \text{SMA}_{200}$, the stock is in a long-term bull market. Only take long trades.
  * **Moving Average Cross:** When a fast average (e.g. 50-day) crosses above a slow average (e.g. 200-day), it signals a bullish regime shift ("Golden Cross").

---

### Exponential Moving Average (EMA)
* **Concept:** Similar to SMA, but gives exponentially more weight to recent prices:
$$\text{EMA}_t = \alpha \cdot \text{Close}_t + (1 - \alpha) \cdot \text{EMA}_{t-1}, \quad \text{where } \alpha = \frac{2}{N+1}$$
* **Intuition:** Reacts faster to sudden momentum changes than an SMA without lagging as far behind.

---

### Relative Strength Index (RSI)
* **Concept:** Momentum oscillator oscillating between $0$ and $100$. Measures the speed and change of price movements over $N$ bars (default 14).
$$\text{RS} = \frac{\text{Average Gain over } N \text{ bars}}{\text{Average Loss over } N \text{ bars}}, \quad \text{RSI} = 100 - \left( \frac{100}{1 + \text{RS}} \right)$$
* **Intuition:**
  * **Oversold ($\text{RSI} < 30$):** Sellers have aggressively dumped the stock; price may be due for a sharp mean-reverting bounce.
  * **Overbought ($\text{RSI} > 70$):** Buyers have pushed price up rapidly; momentum may be exhausted.
  * **Centerline ($\text{RSI} = 50$):** Above 50 indicates net positive momentum; below 50 indicates net negative momentum.

---

### Moving Average Convergence Divergence (MACD)
* **Concept:** Trend-following momentum indicator showing the relationship between two EMAs:
  * $\text{MACD Line} = \text{EMA}_{12}(\text{Close}) - \text{EMA}_{26}(\text{Close})$
  * $\text{Signal Line} = \text{EMA}_{9}(\text{MACD Line})$
  * $\text{Histogram} = \text{MACD Line} - \text{Signal Line}$
* **Intuition:**
  * When the MACD line crosses **above** the Signal line, short-term acceleration is exceeding medium-term trend (Bullish momentum).

---

### Bollinger Bands (BBands)
* **Concept:** A center line ($\text{SMA}_{20}$) flanked by upper and lower bands set 2 standard deviations ($\sigma$) away:
  * $\text{Middle} = \text{SMA}_{20}$
  * $\text{Upper} = \text{SMA}_{20} + 2\sigma$
  * $\text{Lower} = \text{SMA}_{20} - 2\sigma$
* **Intuition:** Around $95\%$ of price action typically falls inside the bands under normal distribution. When price touches or dips below the lower band, it is statistically stretched downward.

---

### Average True Range (ATR)
* **Concept:** Measures absolute price volatility in dollars/points per bar, accounting for overnight gaps:
$$\text{True Range} = \max(\text{High} - \text{Low}, |\text{High} - \text{Close}_{\text{prev}}|, |\text{Low} - \text{Close}_{\text{prev}}|)$$
* **Intuition:** ATR does **not** indicate direction—only volatility. High ATR means wide daily swings; low ATR means quiet consolidation. Used extensively for dynamic stop-losses (e.g. `stop = 2.0 * ATR`).

---

### Volume Indicators
* **Relative Volume (`rel_volume`):** Current volume divided by 20-day average volume ($\text{Volume} / \text{SMA}_{20}(\text{Volume})$). A value of $2.5$ means trading volume is $250\%$ of normal, confirming institutional interest.
* **Chaikin Money Flow (`cmf`):** Combines price and volume to assess whether smart money is accumulating (buying near bar highs) or distributing (selling near bar lows).

---

## 4. How Strategy-Lab Works: The JSON Strategy Spec

In Strategy-Lab, strategies are **never hardcoded in Python**. Instead, they are defined as declarative JSON documents called **Strategy Specs**.

This allows:
1. Automatic validation against strict whitelists (no arbitrary code execution).
2. Parameter grid expansion (creating variations automatically).
3. Cross-testing across 500+ stocks without altering backtest engine code.

### Strategy Spec Schema (`lab/spec.py`)

A spec JSON has the following top-level keys:

```json
{
  "id": "strategy_unique_identifier_v1",
  "name": "Human Readable Name",
  "family": "trend | momentum | mean_reversion | breakout | candlestick_reversal | volume_flow | combo",
  "direction": "long | short",
  "timeframe": "1d",
  "entry": { ... },
  "exit": { ... },
  "params_grid": { ... },
  "notes": "Description of why this strategy works."
}
```

### Condition Tree DSL (Entry & Exit Logic)
The `entry` block is a condition tree:

#### Single Condition:
```json
{
  "left": { "indicator": "rsi", "params": { "period": 14 } },
  "op": "<",
  "right": { "value": 30 }
}
```

#### Multiple Conditions with `"all"` (AND) or `"any"` (OR):
```json
{
  "all": [
    {
      "left": { "indicator": "rsi", "params": { "period": 14 } },
      "op": "<",
      "right": { "value": 30 }
    },
    {
      "left": { "field": "close" },
      "op": ">",
      "right": { "indicator": "sma", "params": { "period": 200 } }
    }
  ]
}
```

#### Candlestick Pattern Condition:
```json
{
  "pattern": "hammer",
  "params": {}
}
```

#### Supported Operators:
* `<` (Less than)
* `<=` (Less than or equal to)
* `>` (Greater than)
* `>=` (Greater than or equal to)
* `cross_above` (Left crosses above Right on the current bar)
* `cross_below` (Left crosses below Right on the current bar)
* `between` (Left value is within `[min, max]` specified in `right.value`)

#### Exit Rules Block:
```json
"exit": {
  "hold_bars": 10,
  "stop_loss_pct": 5.0,
  "take_profit_pct": 10.0,
  "trailing_atr_mult": null,
  "any": [
    {
      "left": { "indicator": "rsi", "params": { "period": 14 } },
      "op": ">",
      "right": { "value": 60 }
    }
  ]
}
```

#### Parameter Grid (`params_grid`):
You can test multiple variations of parameters automatically:
```json
"params_grid": {
  "exit.hold_bars": [5, 10, 20],
  "entry.all.0.left.params.period": [10, 14, 21]
}
```
The lab expands this grid into distinct **variants** and tests each one independently.

---

## 5. Step-by-Step Tutorial: Creating Your First Strategy

Let's build a classic institutional strategy: **RSI Pullback in a Bull Trend**.

* **Thesis:** Strong stocks above their 200-day moving average are in a macro uptrend. When such a stock temporarily pulls back and RSI drops below 30, it is a high-probability dip-buying opportunity.
* **Exit:** Hold for a maximum of 10 days, or exit early if price recovers and RSI exceeds 50, with a safety stop loss at $-7\%$.

### Step 1: Create the JSON file
Create a new file in `strategy-lab/library/specs/rsi_trend_pullback_v1.json`:

```json
{
  "id": "rsi_trend_pullback_v1",
  "name": "RSI Pullback in Macro Uptrend",
  "family": "mean_reversion",
  "direction": "long",
  "timeframe": "1d",
  "entry": {
    "all": [
      {
        "left": { "indicator": "rsi", "params": { "period": 14 } },
        "op": "<",
        "right": { "value": 30 }
      },
      {
        "left": { "field": "close" },
        "op": ">",
        "right": { "indicator": "sma", "params": { "period": 200 } }
      }
    ]
  },
  "exit": {
    "hold_bars": 10,
    "stop_loss_pct": 7.0,
    "take_profit_pct": 12.0,
    "trailing_atr_mult": null,
    "any": [
      {
        "left": { "indicator": "rsi", "params": { "period": 14 } },
        "op": ">",
        "right": { "value": 50 }
      }
    ]
  },
  "params_grid": {
    "exit.hold_bars": [5, 10, 15]
  },
  "notes": "Buy oversold pullbacks (RSI < 30) for stocks trading above their 200-day SMA."
}
```

### Step 2: Validate the Spec
Ensure there are no typos or invalid parameters by running a single Python command:

```powershell
python -c "from lab.spec import load_spec; s = load_spec('library/specs/rsi_trend_pullback_v1.json'); print('Valid spec:', s.name)"
```
If valid, it will output:
`Valid spec: RSI Pullback in Macro Uptrend`

### Step 3: Document in Strategy Library (Optional)
Open `strategy-lab/library/strategies.md` and append:

```markdown
---
## RSI Pullback in Macro Uptrend

**Family:** mean_reversion | **Direction:** long

**Idea:** Buy temporary pullbacks in fundamentally strong stocks in a long-term uptrend.

**Entry:** Close > 200 SMA and 14-period RSI < 30.

**Exit:** Hold 10 bars, or exit when RSI > 50, with a -7% stop loss.

**Source:** manual
```

---

## 6. Testing & Running Your Strategy

Once your file is placed inside `strategy-lab/library/specs/`, you can launch the strategy runner:

```powershell
python -m lab run
```

### What happens under the hood:
1. **Discovery:** The Orchestrator scans `library/specs/*.json` and notices the new spec `rsi_trend_pullback_v1`.
2. **Variant Generation:** It looks at `"params_grid"` (`hold_bars`: 5, 10, 15) and generates 3 variant specifications.
3. **Queue Creation:** It pairs each variant with all 500 stocks in the universe ($3 \times 500 = 1,500$ simulation jobs).
4. **Execution:** Worker threads run the simulation bar-by-bar, recording every trade, return, drawdowns, and holding period into SQLite (`data/lab.db`).
5. **Statistical Verdict:** The metrics engine computes Sharpe ratio, win rate, Out-of-Sample (OOS) t-statistics, and False Discovery Rate (FDR) adjustments to tell you whether the edge is genuine!

Check current progress at any time:
```powershell
python -m lab status
```

Generate markdown and HTML summary reports:
```powershell
python -m lab report
```

---

## 7. Repository File Map (Where Everything Lives)

Here is a breakdown of the key files and directories:

| Path | Purpose |
| :--- | :--- |
| [`strategy-lab/library/specs/`](file:///d:/Finance/Projects/02.%20Orchestrator%20price%20actin%20trading/strategy-lab/library/specs) | **Where executable strategy specs (`.json`) are stored.** Put your new strategy files here! |
| [`strategy-lab/library/strategies.md`](file:///d:/Finance/Projects/02.%20Orchestrator%20price%20actin%20trading/strategy-lab/library/strategies.md) | **Human-readable strategy catalog.** Documents the ideas, logic, and rationale. |
| [`strategy-lab/lab/spec.py`](file:///d:/Finance/Projects/02.%20Orchestrator%20price%20actin%20trading/strategy-lab/lab/spec.py) | **Pydantic schema & validation rules.** Defines all allowed indicators, operators, and parameters. |
| [`strategy-lab/lab/indicators.py`](file:///d:/Finance/Projects/02.%20Orchestrator%20price%20actin%20trading/strategy-lab/lab/indicators.py) | **Math calculations for all technical indicators** (SMA, EMA, RSI, MACD, BBands, ATR, CMF, etc.). |
| [`strategy-lab/lab/patterns.py`](file:///d:/Finance/Projects/02.%20Orchestrator%20price%20actin%20trading/strategy-lab/lab/patterns.py) | **Candlestick pattern recognition** (Hammer, Engulfing, Three White Soldiers, Doji, etc.). |
| [`strategy-lab/lab/backtest.py`](file:///d:/Finance/Projects/02.%20Orchestrator%20price%20actin%20trading/strategy-lab/lab/backtest.py) | **Trade simulation engine.** Simulates entries at $t+1$ Open, stops, targets, and commissions. |
| [`strategy-lab/lab/metrics.py`](file:///d:/Finance/Projects/02.%20Orchestrator%20price%20actin%20trading/strategy-lab/lab/metrics.py) | **Statistical evaluation.** Computes t-stat, win rate, Sharpe ratio, and OOS validation. |
| [`strategy-lab/lab/orchestrator.py`](file:///d:/Finance/Projects/02.%20Orchestrator%20price%20actin%20trading/strategy-lab/lab/orchestrator.py) | **Main control loop.** Scans `specs/`, enqueues jobs, manages background worker threads. |
| [`strategy-lab/data/lab.db`](file:///d:/Finance/Projects/02.%20Orchestrator%20price%20actin%20trading/strategy-lab/data) | **SQLite database.** Holds raw trade history, variant results, and queue status. |
| [`strategy-lab/config.yaml`](file:///d:/Finance/Projects/02.%20Orchestrator%20price%20actin%20trading/strategy-lab/config.yaml) | **Configuration settings.** Sets paths, universe size, CPU limits, costs, and thresholds. |
| [`strategy-lab/docs/`](file:///d:/Finance/Projects/02.%20Orchestrator%20price%20actin%20trading/strategy-lab/docs) | **Documentation folder.** Contains the complete documentary and this creation guide. |
