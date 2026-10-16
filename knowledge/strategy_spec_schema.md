# Strategy Spec Schema Reference

This document describes the JSON DSL schema for strategy specifications used by the Strategy Lab backtesting system.

Defined and enforced by `lab/spec.py`.

---

## 1. Top-Level Structure

Every strategy specification is stored as `<strategy_id>.json` in `library/specs/`.

```json
{
  "id": "strategy_unique_id_v1",
  "name": "Strategy Name",
  "family": "trend",
  "direction": "long",
  "timeframe": "1d",
  "entry": { ... },
  "exit": { ... },
  "params_grid": { ... },
  "notes": "Strategy notes and hypothesis."
}
```

### Whitelisted Families
- `candlestick_reversal`
- `candlestick_continuation`
- `trend`
- `momentum`
- `mean_reversion`
- `breakout`
- `volatility`
- `volume_flow`
- `combo`

### Direction
- `long`
- `short`

---

## 2. Condition Tree DSL (`entry`)

The `entry` field can be:
1. A **Comparison Condition** (`left`, `op`, `right`)
2. A **Logical Group** (`all` for AND, `any` for OR)
3. A **Pattern Condition** (`pattern`, `params`)

### Operators (`op`)
- `<`, `<=`, `>`, `>=`
- `cross_above`, `cross_below`
- `between` (requires `right.value` to be a 2-element list `[min, max]`)

### Operands (`left` / `right`)
- **Field:** `{"field": "open" | "high" | "low" | "close" | "volume"}`
- **Value:** `{"value": 42.0}`
- **Indicator:** `{"indicator": "rsi", "params": {"period": 14}, "output": null, "shift": 0}`

### Whitelisted Indicators & Allowed Parameters
| Indicator | Params & Default Ranges | Outputs |
| :--- | :--- | :--- |
| `sma` | `period` [2, 300] | single series |
| `ema` | `period` [2, 300] | single series |
| `rsi` | `period` [2, 50] | single series |
| `macd` | `fast` [3, 30], `slow` [10, 60], `signal` [3, 20] | `macd`, `signal`, `hist` |
| `bbands` | `period` [5, 100], `std` [0.5, 4.0] | `upper`, `middle`, `lower` |
| `atr` | `period` [2, 50] | single series |
| `adx` | `period` [5, 50] | single series |
| `stoch` | `k` [5, 30], `d` [2, 10] | `k`, `d` |
| `roc` | `period` [1, 252] | single series |
| `donchian` | `period` [5, 252] | `upper`, `lower`, `middle` |
| `zscore` | `period` [5, 100] | single series |
| `obv` | (no params) | single series |
| `mfi` | `period` [5, 30] | single series |
| `cmf` | `period` [5, 50] | single series |
| `vol_sma` | `period` [5, 100] | single series |
| `rel_volume`| `period` [5, 100] | single series |
| `keltner` | `period` [5, 60], `mult` [0.5, 4.0] | `upper`, `middle`, `lower` |
| `gap_pct` | (no params) | single series |
| `range_pct` | (no params) | single series |
| `highest` | `period` [2, 260] | single series |
| `lowest` | `period` [2, 260] | single series |

### Whitelisted Candlestick Patterns
- `three_white_soldiers`, `three_black_crows`
- `bullish_engulfing`, `bearish_engulfing`
- `hammer`, `shooting_star`, `morning_star`, `evening_star`
- `bullish_harami`, `bearish_harami`, `piercing_line`, `dark_cloud_cover`
- `doji`, `inside_bar_breakout_up`, `inside_bar_breakout_down`
- `tweezer_bottom`, `tweezer_top`, `nr7_breakout_up`

---

## 3. Exit Rules (`exit`)

```json
{
  "hold_bars": 10,
  "stop_loss_pct": 8.0,
  "take_profit_pct": 15.0,
  "trailing_atr_mult": null,
  "any": [
    {
      "left": { "indicator": "rsi", "params": { "period": 14 } },
      "op": ">",
      "right": { "value": 70 }
    }
  ]
}
```

- `hold_bars` (required): Max holding duration in bars (e.g. 10 days).
- `stop_loss_pct` (optional): Percentage drop from entry to trigger stop-loss (e.g. `8.0`).
- `take_profit_pct` (optional): Percentage gain from entry to book profit (e.g. `15.0`).
- `trailing_atr_mult` (optional): Trailing stop distance in multiples of ATR at entry (e.g. `2.5`).
- `any` (optional): List of condition nodes. If any condition triggers at bar close, trade exits at next open.
