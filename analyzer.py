"""
Market Analyzer v3 — максимально якісний технічний аналіз
Покращення:
  - Виправлено ambiguous DataFrame bug (_ok + float() скрізь)
  - Додано ADX (сила тренду), Stochastic RSI, Volume Profile
  - Покращено алгоритм рівнів (зважені за силою)
  - Додано фільтр часу сесій (London/NY/Asia)
  - Покращено SL/TP (структурний SL замість ATR*mult)
  - Додано multi-timeframe confluence score
  - Додано Fibonacci рівні
  - Більш точний розрахунок confidence
  - Захист від NaN/inf у всіх розрахунках
"""
import asyncio
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional
from data_provider import DataProvider
from config import (
    EMA_FAST, EMA_SLOW, EMA_TREND, RSI_PERIOD,
    RSI_OVERSOLD, RSI_OVERBOUGHT, ATR_PERIOD,
    ATR_SL_MULTIPLIER, MIN_RR, CONTEXT_TIMEFRAMES, REQUEST_DELAY
)

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe(v, default=0.0):
    """Захист від NaN/inf"""
    try:
        f = float(v)
        return default if (np.isnan(f) or np.isinf(f)) else f
    except Exception:
        return default

def _ok(df) -> bool:
    return df is not None and isinstance(df, pd.DataFrame) and len(df) >= 20

def _col(df: pd.DataFrame, col: str) -> pd.Series:
    """Завжди повертає Series (навіть якщо df[col] є DataFrame через MultiIndex)"""
    s = df[col]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s.astype(float)

PATTERN_NAMES = {
    "bullish_pinbar":    "Бичачий пін-бар 📍",
    "bearish_pinbar":    "Ведмежий пін-бар 📍",
    "bullish_engulfing": "Бичаче поглинання 🟢",
    "bearish_engulfing": "Ведмеже поглинання 🔴",
    "doji":              "Доджі ➕",
    "inside_bar":        "Inside Bar 📦",
    "morning_star":      "Ранкова зірка ⭐",
    "evening_star":      "Вечірня зірка ⭐",
    "hammer":            "Молот 🔨",
    "shooting_star":     "Падаюча зірка 💫",
    "three_white":       "3 білих солдати 🟢🟢🟢",
    "three_black":       "3 чорних ворони 🔴🔴🔴",
    "tweezer_bottom":    "Пінцет знизу 🔧",
    "tweezer_top":       "Пінцет зверху 🔧",
}


class MarketAnalyzer:

    def __init__(self):
        self.dp = DataProvider()

    # ══════════════════════════════════════════════════════════════════════════
    #  ІНДИКАТОРИ
    # ══════════════════════════════════════════════════════════════════════════

    def _ema(self, s: pd.Series, n: int) -> pd.Series:
        return s.ewm(span=n, adjust=False).mean()

    def _sma(self, s: pd.Series, n: int) -> pd.Series:
        return s.rolling(window=n, min_periods=1).mean()

    def _rsi(self, close: pd.Series, n=14) -> pd.Series:
        d = close.diff()
        g = d.clip(lower=0).ewm(span=n, adjust=False).mean()
        l = (-d.clip(upper=0)).ewm(span=n, adjust=False).mean()
        rs = g / l.replace(0, np.nan)
        return (100 - 100 / (1 + rs)).fillna(50)

    def _stoch_rsi(self, close: pd.Series, n=14, k=3, d=3) -> tuple:
        """Stochastic RSI — більш чутливий до перекупленості"""
        rsi = self._rsi(close, n)
        rsi_min = rsi.rolling(n).min()
        rsi_max = rsi.rolling(n).max()
        diff = (rsi_max - rsi_min).replace(0, np.nan)
        k_line = ((rsi - rsi_min) / diff * 100).fillna(50)
        d_line = k_line.rolling(d).mean().fillna(50)
        return k_line, d_line

    def _atr(self, df: pd.DataFrame, n=14) -> pd.Series:
        h  = _col(df, "high")
        l  = _col(df, "low")
        pc = _col(df, "close").shift(1)
        tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        return tr.ewm(span=n, adjust=False).mean()

    def _adx(self, df: pd.DataFrame, n=14) -> dict:
        """ADX — сила тренду (0-100). >25 = сильний тренд"""
        h  = _col(df, "high")
        l  = _col(df, "low")
        c  = _col(df, "close")
        pc = c.shift(1)
        ph = h.shift(1)
        pl = l.shift(1)

        up   = h - ph
        down = pl - l
        plus_dm  = np.where((up > down) & (up > 0), up, 0.0)
        minus_dm = np.where((down > up) & (down > 0), down, 0.0)

        tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        atr = pd.Series(tr).ewm(span=n, adjust=False).mean()

        plus_di  = 100 * pd.Series(plus_dm).ewm(span=n, adjust=False).mean()  / atr.replace(0, np.nan)
        minus_di = 100 * pd.Series(minus_dm).ewm(span=n, adjust=False).mean() / atr.replace(0, np.nan)

        dx_denom = (plus_di + minus_di).replace(0, np.nan)
        dx  = 100 * (plus_di - minus_di).abs() / dx_denom
        adx = dx.ewm(span=n, adjust=False).mean().fillna(0)

        last_adx      = _safe(adx.iloc[-1])
        last_plus_di  = _safe(plus_di.iloc[-1])
        last_minus_di = _safe(minus_di.iloc[-1])

        if last_adx >= 25:
            trend_strong = True
            trend_dir = "bullish" if last_plus_di > last_minus_di else "bearish"
        else:
            trend_strong = False
            trend_dir = "sideways"

        return {
            "adx": last_adx,
            "plus_di": last_plus_di,
            "minus_di": last_minus_di,
            "strong": trend_strong,
            "direction": trend_dir,
        }

    def _macd(self, close: pd.Series) -> tuple:
        fast   = self._ema(close, 12)
        slow   = self._ema(close, 26)
        macd   = fast - slow
        signal = self._ema(macd, 9)
        hist   = macd - signal
        return macd, signal, hist

    def _bollinger(self, close: pd.Series, n=20, k=2) -> tuple:
        mid = close.rolling(n, min_periods=1).mean()
        std = close.rolling(n, min_periods=1).std().fillna(0)
        return mid + k * std, mid, mid - k * std

    def _vwap(self, df: pd.DataFrame) -> Optional[float]:
        """VWAP — середньозважена ціна за обсягом"""
        vol = _col(df, "volume")
        if vol.sum() < 1:
            return None
        tp = (_col(df, "high") + _col(df, "low") + _col(df, "close")) / 3
        return _safe((tp * vol).sum() / vol.sum())

    # ══════════════════════════════════════════════════════════════════════════
    #  РІВНІ ПІДТРИМКИ / ОПОРУ (покращений алгоритм)
    # ══════════════════════════════════════════════════════════════════════════

    def _find_levels(self, df: pd.DataFrame, window=8) -> dict:
        h     = _col(df, "high").values.astype(float)
        l     = _col(df, "low").values.astype(float)
        close = float(_col(df, "close").iloc[-1])
        vol   = _col(df, "volume").values.astype(float)
        total_vol = vol.sum() if vol.sum() > 0 else 1.0

        supports, resistances = [], []

        for i in range(window, len(df) - window):
            # Зважуємо рівні за обсягом (сильніший рівень = більший обсяг)
            local_vol_weight = vol[max(0,i-2):i+3].sum() / total_vol

            if h[i] == max(h[i - window: i + window + 1]):
                resistances.append((h[i], local_vol_weight))
            if l[i] == min(l[i - window: i + window + 1]):
                supports.append((l[i], local_vol_weight))

        def cluster(raw_levels, tol=0.0015):
            if not raw_levels:
                return []
            raw_levels.sort(key=lambda x: x[0])
            result = [[raw_levels[0][0], raw_levels[0][1], 1]]  # price, weight, touches
            for price, weight in raw_levels[1:]:
                if (price - result[-1][0]) / max(result[-1][0], 1e-10) > tol:
                    result.append([price, weight, 1])
                else:
                    # Об'єднуємо — зважений середній
                    result[-1][0] = (result[-1][0] * result[-1][1] + price * weight) / (result[-1][1] + weight)
                    result[-1][1] += weight
                    result[-1][2] += 1
            return result  # [[price, weight, touches], ...]

        sup_cl = cluster(supports)
        res_cl = cluster(resistances)

        sup_prices = [x[0] for x in sup_cl]
        res_prices = [x[0] for x in res_cl]

        ns = max([s[0] for s in sup_cl if s[0] < close], default=None)
        nr = min([r[0] for r in res_cl if r[0] > close], default=None)

        ns_touches = next((s[2] for s in sup_cl if s[0] == ns), 0) if ns else 0
        nr_touches = next((r[2] for r in res_cl if r[0] == nr), 0) if nr else 0

        # Fibonacci рівні між найближчими sup/res
        fib_levels = {}
        if ns and nr and nr > ns:
            diff = nr - ns
            for ratio, label in [(0.236,"Fib 23.6%"),(0.382,"Fib 38.2%"),
                                  (0.500,"Fib 50.0%"),(0.618,"Fib 61.8%"),(0.786,"Fib 78.6%")]:
                fib_levels[label] = ns + diff * ratio

        return {
            "supports":           sup_prices,
            "resistances":        res_prices,
            "nearest_support":    ns,
            "nearest_resistance": nr,
            "support_strength":   ns_touches,
            "resistance_strength":nr_touches,
            "fib_levels":         fib_levels,
        }

    # ══════════════════════════════════════════════════════════════════════════
    #  СВІЧКОВІ ПАТТЕРНИ (розширено до 14)
    # ══════════════════════════════════════════════════════════════════════════

    def _patterns(self, df: pd.DataFrame) -> list:
        found = []
        if len(df) < 4:
            return found

        o  = _col(df, "open").values.astype(float)
        h  = _col(df, "high").values.astype(float)
        l  = _col(df, "low").values.astype(float)
        c  = _col(df, "close").values.astype(float)

        def body(i):    return abs(c[i] - o[i])
        def rng(i):     return h[i] - l[i]
        def upper(i):   return h[i] - max(o[i], c[i])
        def lower(i):   return min(o[i], c[i]) - l[i]
        def is_bull(i): return c[i] > o[i]
        def is_bear(i): return c[i] < o[i]

        n = len(c) - 1  # поточна свічка

        if rng(n) < 1e-10:
            return found

        # ── Пін-бар ──────────────────────────────────────────────────────────
        if lower(n) >= 0.6 * rng(n) and body(n) <= 0.35 * rng(n):
            found.append("bullish_pinbar")
        if upper(n) >= 0.6 * rng(n) and body(n) <= 0.35 * rng(n):
            found.append("bearish_pinbar")

        # ── Молот / Падаюча зірка ────────────────────────────────────────────
        if body(n) > 0 and lower(n) >= 2 * body(n) and upper(n) <= 0.15 * rng(n):
            found.append("hammer")
        if body(n) > 0 and upper(n) >= 2 * body(n) and lower(n) <= 0.15 * rng(n):
            found.append("shooting_star")

        # ── Поглинання ───────────────────────────────────────────────────────
        if (n >= 1 and is_bear(n-1) and is_bull(n)
                and o[n] <= c[n-1] and c[n] >= o[n-1]
                and body(n) > body(n-1) * 1.05):
            found.append("bullish_engulfing")
        if (n >= 1 and is_bull(n-1) and is_bear(n)
                and o[n] >= c[n-1] and c[n] <= o[n-1]
                and body(n) > body(n-1) * 1.05):
            found.append("bearish_engulfing")

        # ── Доджі ────────────────────────────────────────────────────────────
        if body(n) <= 0.07 * rng(n):
            found.append("doji")

        # ── Inside Bar ───────────────────────────────────────────────────────
        if n >= 1 and h[n] <= h[n-1] and l[n] >= l[n-1]:
            found.append("inside_bar")

        # ── Ранкова / Вечірня зірка ──────────────────────────────────────────
        if (n >= 2
                and is_bear(n-2) and body(n-2) > 0.5 * rng(n-2)
                and body(n-1) < 0.3 * rng(n-1)
                and is_bull(n) and c[n] > (o[n-2] + c[n-2]) / 2):
            found.append("morning_star")
        if (n >= 2
                and is_bull(n-2) and body(n-2) > 0.5 * rng(n-2)
                and body(n-1) < 0.3 * rng(n-1)
                and is_bear(n) and c[n] < (o[n-2] + c[n-2]) / 2):
            found.append("evening_star")

        # ── 3 білих солдати / 3 чорних ворони ───────────────────────────────
        if (n >= 2
                and all(is_bull(n-i) for i in range(3))
                and c[n] > c[n-1] > c[n-2]
                and all(body(n-i) > 0.5 * rng(n-i) for i in range(3))):
            found.append("three_white")
        if (n >= 2
                and all(is_bear(n-i) for i in range(3))
                and c[n] < c[n-1] < c[n-2]
                and all(body(n-i) > 0.5 * rng(n-i) for i in range(3))):
            found.append("three_black")

        # ── Пінцет (Tweezer) ─────────────────────────────────────────────────
        if (n >= 1 and is_bear(n-1) and is_bull(n)
                and abs(l[n] - l[n-1]) / max(rng(n), 1e-10) < 0.05):
            found.append("tweezer_bottom")
        if (n >= 1 and is_bull(n-1) and is_bear(n)
                and abs(h[n] - h[n-1]) / max(rng(n), 1e-10) < 0.05):
            found.append("tweezer_top")

        return found

    # ══════════════════════════════════════════════════════════════════════════
    #  ТРЕНД та СТРУКТУРА
    # ══════════════════════════════════════════════════════════════════════════

    def _trend(self, df: pd.DataFrame) -> dict:
        close = _col(df, "close")
        e21   = self._ema(close, EMA_FAST)
        e50   = self._ema(close, EMA_SLOW)
        e200  = self._ema(close, EMA_TREND)

        lc   = _safe(close.iloc[-1])
        l21  = _safe(e21.iloc[-1])
        l50  = _safe(e50.iloc[-1])
        l200 = _safe(e200.iloc[-1])
        p21  = _safe(e21.iloc[-2])
        p50  = _safe(e50.iloc[-2])

        # Кут нахилу EMA 21 (momentum)
        slope_pct = (l21 - _safe(e21.iloc[-5])) / max(_safe(e21.iloc[-5]), 1e-10) * 100

        if l21 > l50 > l200 and lc > l21:
            direction, strength = "bullish", "strong"
        elif l21 > l50 and lc > l50:
            direction, strength = "bullish", "moderate"
        elif l21 < l50 < l200 and lc < l21:
            direction, strength = "bearish", "strong"
        elif l21 < l50 and lc < l50:
            direction, strength = "bearish", "moderate"
        else:
            direction, strength = "sideways", "weak"

        crossover = "none"
        if p21 <= p50 and l21 > l50:
            crossover = "bullish_cross"
        elif p21 >= p50 and l21 < l50:
            crossover = "bearish_cross"

        return {
            "direction": direction, "strength": strength,
            "ema21": l21, "ema50": l50, "ema200": l200,
            "crossover": crossover, "slope_pct": slope_pct,
        }

    def _structure(self, df: pd.DataFrame) -> dict:
        """Ринкова структура через HH/HL/LH/LL на останніх 30 свічках"""
        h = _col(df, "high").values[-30:].astype(float)
        l = _col(df, "low").values[-30:].astype(float)
        m = len(h) // 2

        hh = float(h[m:].max()) > float(h[:m].max())
        hl = float(l[m:].min()) > float(l[:m].min())
        ll = float(l[m:].min()) < float(l[:m].min())
        lh = float(h[m:].max()) < float(h[:m].max())

        # Розрахунок ATR-нормалізованого діапазону (чи ринок у флеті)
        atr = self._atr(df).iloc[-1]
        price = _safe(_col(df, "close").iloc[-1])
        range_pct = (float(h.max()) - float(l.min())) / max(price, 1e-10) * 100
        atr_pct   = _safe(atr) / max(price, 1e-10) * 100

        if hh and hl:
            st = "uptrend"
        elif ll and lh:
            st = "downtrend"
        else:
            st = "ranging"

        return {
            "structure": st, "hh": hh, "hl": hl, "ll": ll, "lh": lh,
            "range_pct": range_pct, "atr_pct": atr_pct,
        }

    def _market_session(self) -> str:
        """Поточна торгова сесія (UTC)"""
        hour = datetime.now(timezone.utc).hour
        if 0 <= hour < 8:   return "asia"
        if 7 <= hour < 12:  return "london"
        if 12 <= hour < 17: return "new_york"
        if 17 <= hour < 21: return "overlap_close"
        return "off_hours"

    # ══════════════════════════════════════════════════════════════════════════
    #  СТРАТЕГІЇ (покращені + строгі умови)
    # ══════════════════════════════════════════════════════════════════════════

    def _s1_level_bounce(self, df, levels, trend, adx) -> dict:
        close = _safe(_col(df, "close").iloc[-1])
        ns, nr = levels["nearest_support"], levels["nearest_resistance"]
        pats   = self._patterns(df)
        score, signals, direction = 0, [], "NEUTRAL"

        # Близькість до рівня: 1.2% зона (раніше 1.5% — забагато)
        at_sup = ns and abs(close - ns) / max(close, 1e-10) < 0.012
        at_res = nr and abs(close - nr) / max(close, 1e-10) < 0.012

        if at_sup:
            score += 25
            signals.append(f"✅ Ціна біля підтримки {ns:.5f}")
            direction = "BUY"

            # Сила рівня (кількість дотиків)
            st = levels["support_strength"]
            if st >= 4:   score += 20; signals.append(f"✅ Дуже сильний рівень ({st} дотиків)")
            elif st >= 2: score += 10; signals.append(f"✅ Підтверджений рівень ({st} дотики)")

            if "bullish_pinbar" in pats or "hammer" in pats:
                score += 35; signals.append("✅ Бичачий пін-бар / молот")
            if "bullish_engulfing" in pats:
                score += 30; signals.append("✅ Бичаче поглинання")
            if "morning_star" in pats or "three_white" in pats:
                score += 25; signals.append("✅ Сильний розворотний паттерн")
            if "tweezer_bottom" in pats:
                score += 20; signals.append("✅ Пінцет знизу")

            # ADX: слабкий тренд = кращий відбій
            if adx["adx"] < 20:
                score += 10; signals.append("✅ ADX низький — ринок у боковику, відбій ймовірний")

        elif at_res:
            score += 25
            signals.append(f"✅ Ціна біля опору {nr:.5f}")
            direction = "SELL"

            st = levels["resistance_strength"]
            if st >= 4:   score += 20; signals.append(f"✅ Дуже сильний рівень ({st} дотиків)")
            elif st >= 2: score += 10; signals.append(f"✅ Підтверджений рівень ({st} дотики)")

            if "bearish_pinbar" in pats or "shooting_star" in pats:
                score += 35; signals.append("✅ Ведмежий пін-бар / зірка")
            if "bearish_engulfing" in pats:
                score += 30; signals.append("✅ Ведмеже поглинання")
            if "evening_star" in pats or "three_black" in pats:
                score += 25; signals.append("✅ Сильний розворотний паттерн")
            if "tweezer_top" in pats:
                score += 20; signals.append("✅ Пінцет зверху")

            if adx["adx"] < 20:
                score += 10; signals.append("✅ ADX низький — відбій ймовірний")

        # Підтвердження тренду: лонг в бичачому, шорт у ведмежому
        if trend["direction"] == "bullish" and direction == "BUY":
            score += 15; signals.append("✅ Тренд підтверджує лонг")
        elif trend["direction"] == "bearish" and direction == "SELL":
            score += 15; signals.append("✅ Тренд підтверджує шорт")
        elif direction != "NEUTRAL":
            score -= 10; signals.append("⚠️ Торгівля проти тренду — підвищений ризик")

        return {"name": "Відбій від рівня", "score": min(max(score, 0), 100),
                "direction": direction, "signals": signals}

    def _s2_breakout(self, df, levels, trend, adx) -> dict:
        close = _safe(_col(df, "close").iloc[-1])
        prev  = _safe(_col(df, "close").iloc[-2])
        ns, nr = levels["nearest_support"], levels["nearest_resistance"]
        vol   = _col(df, "volume")
        score, signals, direction = 0, [], "NEUTRAL"

        # Пробій повинен бути закритий свічкою (не просто тінь)
        if nr and prev < nr and close > nr:
            score += 40; signals.append("✅ Пробій рівня опору (закриття вище)"); direction = "BUY"
            pct_above = (close - nr) / max(nr, 1e-10) * 100
            if pct_above < 0.3:
                score += 25; signals.append("✅ Ретест рівня (ціна близько до пробою)")
            if adx["adx"] > 20:
                score += 15; signals.append(f"✅ ADX {adx['adx']:.0f} — тренд набирає силу")

        elif ns and prev > ns and close < ns:
            score += 40; signals.append("✅ Пробій рівня підтримки (закриття нижче)"); direction = "SELL"
            pct_below = (ns - close) / max(ns, 1e-10) * 100
            if pct_below < 0.3:
                score += 25; signals.append("✅ Ретест рівня")
            if adx["adx"] > 20:
                score += 15; signals.append(f"✅ ADX {adx['adx']:.0f} — тренд набирає силу")

        # Обсяг підтверджує пробій
        if direction != "NEUTRAL" and len(vol) >= 10:
            avg_vol = float(vol.iloc[-10:-1].mean())
            last_vol = float(vol.iloc[-1])
            if avg_vol > 0 and last_vol > avg_vol * 1.3:
                score += 20; signals.append(f"✅ Обсяг вищий за середній на {(last_vol/avg_vol-1)*100:.0f}%")

        if trend["direction"] == "bullish" and direction == "BUY":
            score += 10
        elif trend["direction"] == "bearish" and direction == "SELL":
            score += 10

        return {"name": "Пробій + ретест", "score": min(max(score, 0), 100),
                "direction": direction, "signals": signals}

    def _s3_trend_pullback(self, df, trend, levels, adx) -> dict:
        close = _safe(_col(df, "close").iloc[-1])
        e21, e50 = trend["ema21"], trend["ema50"]
        pats  = self._patterns(df)
        score, signals, direction = 0, [], "NEUTRAL"

        # ADX > 20 обов'язковий для стратегії тренду
        if adx["adx"] < 15:
            return {"name": "Тренд + корекція", "score": 0, "direction": "NEUTRAL",
                    "signals": [f"❌ ADX {adx['adx']:.0f} — тренд занадто слабкий"]}

        bull_pats = ("bullish_pinbar","bullish_engulfing","hammer","morning_star","tweezer_bottom","three_white")
        bear_pats = ("bearish_pinbar","bearish_engulfing","shooting_star","evening_star","tweezer_top","three_black")

        if trend["direction"] in ("bullish",) and trend["strength"] in ("strong","moderate"):
            score += 25; signals.append(f"✅ Висхідний тренд (ADX {adx['adx']:.0f})"); direction = "BUY"
            slope = trend.get("slope_pct", 0)
            if slope > 0.1: score += 10; signals.append(f"✅ EMA 21 нахилена вгору ({slope:.2f}%)")

            dist_21 = abs(close - e21) / max(close, 1e-10) * 100
            dist_50 = abs(close - e50) / max(close, 1e-10) * 100

            if dist_21 < 0.8:
                score += 35; signals.append("✅ Глибока корекція до EMA 21 — ідеальна зона")
            elif dist_21 < 1.5:
                score += 20; signals.append("✅ Корекція до EMA 21")
            elif dist_50 < 1.2:
                score += 15; signals.append("✅ Корекція до EMA 50 (глибша)")

            if any(p in pats for p in bull_pats):
                score += 25; signals.append("✅ Паттерн підтверджує відновлення")

        elif trend["direction"] in ("bearish",) and trend["strength"] in ("strong","moderate"):
            score += 25; signals.append(f"✅ Низхідний тренд (ADX {adx['adx']:.0f})"); direction = "SELL"
            slope = trend.get("slope_pct", 0)
            if slope < -0.1: score += 10; signals.append(f"✅ EMA 21 нахилена вниз ({slope:.2f}%)")

            dist_21 = abs(close - e21) / max(close, 1e-10) * 100
            dist_50 = abs(close - e50) / max(close, 1e-10) * 100

            if dist_21 < 0.8:
                score += 35; signals.append("✅ Корекція до EMA 21 — зона продажу")
            elif dist_21 < 1.5:
                score += 20; signals.append("✅ Корекція до EMA 21")
            elif dist_50 < 1.2:
                score += 15; signals.append("✅ Корекція до EMA 50")

            if any(p in pats for p in bear_pats):
                score += 25; signals.append("✅ Паттерн підтверджує продовження")

        return {"name": "Тренд + корекція", "score": min(max(score, 0), 100),
                "direction": direction, "signals": signals}

    def _s4_range(self, df, levels, structure, adx) -> dict:
        close = _safe(_col(df, "close").iloc[-1])
        ns, nr = levels["nearest_support"], levels["nearest_resistance"]
        pats  = self._patterns(df)
        score, signals, direction = 0, [], "NEUTRAL"

        # Флет: ADX < 20 і структура ranging
        is_flat = structure["structure"] == "ranging" or adx["adx"] < 20
        if not is_flat:
            return {"name": "Діапазон (флет)", "score": 0, "direction": "NEUTRAL",
                    "signals": [f"❌ ADX {adx['adx']:.0f} — ринок у тренді, не у флеті"]}

        if not (ns and nr):
            return {"name": "Діапазон (флет)", "score": 0, "direction": "NEUTRAL",
                    "signals": ["❌ Рівні не визначено"]}

        rng_size = (nr - ns) / max(ns, 1e-10)
        if rng_size < 0.005:
            return {"name": "Діапазон (флет)", "score": 0, "direction": "NEUTRAL",
                    "signals": ["❌ Діапазон занадто вузький (<0.5%)"]}

        score += 30; signals.append(f"✅ Флет підтверджено (ADX {adx['adx']:.0f})")
        score += 10; signals.append(f"✅ Діапазон {rng_size*100:.1f}%")

        pos = (close - ns) / max(nr - ns, 1e-10)

        if pos < 0.2:
            score += 40; signals.append("✅ Ціна біля нижньої межі → BUY"); direction = "BUY"
            if any(p in pats for p in ("bullish_pinbar","hammer","bullish_engulfing","morning_star","tweezer_bottom")):
                score += 25; signals.append("✅ Бичачий паттерн підтверджує розворот")
        elif pos > 0.8:
            score += 40; signals.append("✅ Ціна біля верхньої межі → SELL"); direction = "SELL"
            if any(p in pats for p in ("bearish_pinbar","shooting_star","bearish_engulfing","evening_star","tweezer_top")):
                score += 25; signals.append("✅ Ведмежий паттерн підтверджує розворот")
        else:
            signals.append(f"ℹ️ Ціна в середині діапазону ({pos*100:.0f}%) — очікуйте меж")

        return {"name": "Діапазон (флет)", "score": min(max(score, 0), 100),
                "direction": direction, "signals": signals}

    def _s5_ema_cross(self, df, trend, adx) -> dict:
        close = _col(df, "close")
        pats  = self._patterns(df)
        score, signals, direction = 0, [], "NEUTRAL"
        macd_line, macd_sig, macd_hist = self._macd(close)
        stoch_k, stoch_d = self._stoch_rsi(close)

        last_hist   = _safe(macd_hist.iloc[-1])
        prev_hist   = _safe(macd_hist.iloc[-2])
        last_stoch  = _safe(stoch_k.iloc[-1])

        cross = trend["crossover"]

        if cross == "bullish_cross":
            score += 50; signals.append("✅ Бичачий перетин EMA 21 × EMA 50"); direction = "BUY"
        elif cross == "bearish_cross":
            score += 50; signals.append("✅ Ведмежий перетин EMA 21 × EMA 50"); direction = "SELL"
        else:
            if trend["ema21"] > trend["ema50"]:
                score += 20; signals.append("ℹ️ EMA 21 > EMA 50 (бичача розстановка)"); direction = "BUY"
            elif trend["ema21"] < trend["ema50"]:
                score += 20; signals.append("ℹ️ EMA 21 < EMA 50 (ведмежа розстановка)"); direction = "SELL"

        if direction != "NEUTRAL":
            # MACD підтвердження
            if direction == "BUY" and last_hist > 0:
                score += 15; signals.append("✅ MACD гістограма бичача")
                if prev_hist < 0 < last_hist:
                    score += 10; signals.append("✅ MACD щойно перетнув нуль вгору")
            elif direction == "SELL" and last_hist < 0:
                score += 15; signals.append("✅ MACD гістограма ведмежа")
                if prev_hist > 0 > last_hist:
                    score += 10; signals.append("✅ MACD щойно перетнув нуль вниз")

            # Stochastic RSI
            if direction == "BUY" and last_stoch < 30:
                score += 15; signals.append(f"✅ Stoch RSI перепроданий ({last_stoch:.0f})")
            elif direction == "SELL" and last_stoch > 70:
                score += 15; signals.append(f"✅ Stoch RSI перекуплений ({last_stoch:.0f})")

            # ADX
            if adx["adx"] > 25:
                score += 10; signals.append(f"✅ ADX {adx['adx']:.0f} — сильний тренд")

            # Паттерн
            bull_pats = ("bullish_pinbar","bullish_engulfing","hammer","morning_star")
            bear_pats = ("bearish_pinbar","bearish_engulfing","shooting_star","evening_star")
            if direction == "BUY"  and any(p in pats for p in bull_pats):
                score += 20; signals.append("✅ Бичачий паттерн підтверджує")
            elif direction == "SELL" and any(p in pats for p in bear_pats):
                score += 20; signals.append("✅ Ведмежий паттерн підтверджує")

        return {"name": "EMA Crossover + MACD", "score": min(max(score, 0), 100),
                "direction": direction, "signals": signals}

    # ══════════════════════════════════════════════════════════════════════════
    #  ГОЛОВНИЙ АНАЛІЗ
    # ══════════════════════════════════════════════════════════════════════════

    async def analyze(self, symbol: str, tf: str, strategy: str = "all") -> dict:
        # ── Дані ────────────────────────────────────────────────────────────
        df = await self.dp.get_ohlcv(symbol, tf)
        if not _ok(df):
            raise ValueError(f"Недостатньо даних для {symbol} на {tf}. "
                             "Перевірте API ключ або спробуйте інший таймфрейм.")

        ctx_tf = CONTEXT_TIMEFRAMES.get(tf, "1d")
        df_ctx = await self.dp.get_ohlcv(symbol, ctx_tf)

        close = _col(df, "close")

        # ── Індикатори ────────────────────────────────────────────────────────
        rsi_s            = self._rsi(close, RSI_PERIOD)
        stoch_k, stoch_d = self._stoch_rsi(close)
        atr_s            = self._atr(df, ATR_PERIOD)
        macd_l, _, hist  = self._macd(close)
        bb_up, bb_mid, bb_low = self._bollinger(close)
        adx_d            = self._adx(df)
        vwap_val         = self._vwap(df)

        trend     = self._trend(df)
        ctx_trend = self._trend(df_ctx) if _ok(df_ctx) else trend
        levels    = self._find_levels(df)
        struct    = self._structure(df)
        pats      = self._patterns(df)
        session   = self._market_session()

        last_close = _safe(close.iloc[-1])
        last_rsi   = _safe(rsi_s.iloc[-1], 50)
        last_atr   = _safe(atr_s.iloc[-1])
        last_hist  = _safe(hist.iloc[-1])
        last_stoch = _safe(stoch_k.iloc[-1], 50)

        # ── Стратегії ──────────────────────────────────────────────────────────
        all_strats = {
            "s1": self._s1_level_bounce(df, levels, trend, adx_d),
            "s2": self._s2_breakout(df, levels, trend, adx_d),
            "s3": self._s3_trend_pullback(df, trend, levels, adx_d),
            "s4": self._s4_range(df, levels, struct, adx_d),
            "s5": self._s5_ema_cross(df, trend, adx_d),
        }

        strats = {strategy: all_strats[strategy]} if strategy in all_strats else all_strats

        best = max(strats.values(), key=lambda x: x["score"])

        # ── Зважений vote ─────────────────────────────────────────────────────
        # Стратегії мають різні ваги (більш надійні — більша вага)
        WEIGHTS = {"s1": 1.2, "s2": 1.1, "s3": 1.3, "s4": 0.9, "s5": 1.0}
        buy_s = sum(s["score"] * WEIGHTS.get(k, 1.0)
                    for k, s in all_strats.items() if s["direction"] == "BUY")
        sell_s = sum(s["score"] * WEIGHTS.get(k, 1.0)
                     for k, s in all_strats.items() if s["direction"] == "SELL")
        total = buy_s + sell_s

        if total < 1:
            direction, confidence = "NEUTRAL", 0
        elif buy_s > sell_s:
            direction = "BUY"
            confidence = int(min(buy_s / total * 100, 100))
        else:
            direction = "SELL"
            confidence = int(min(sell_s / total * 100, 100))

        # ── Бонуси / Штрафи до confidence ─────────────────────────────────────

        # RSI підтвердження
        if last_rsi < RSI_OVERSOLD and direction == "BUY":
            confidence = min(confidence + 8, 100)
        elif last_rsi > RSI_OVERBOUGHT and direction == "SELL":
            confidence = min(confidence + 8, 100)
        elif last_rsi > 65 and direction == "BUY":
            confidence = max(confidence - 5, 0)   # купуємо вже перегрітий ринок
        elif last_rsi < 35 and direction == "SELL":
            confidence = max(confidence - 5, 0)

        # Stochastic RSI підтвердження
        if last_stoch < 20 and direction == "BUY":
            confidence = min(confidence + 5, 100)
        elif last_stoch > 80 and direction == "SELL":
            confidence = min(confidence + 5, 100)

        # ADX підсилює впевненість при тренді
        if adx_d["adx"] > 30 and direction != "NEUTRAL":
            confidence = min(confidence + 7, 100)
        elif adx_d["adx"] < 15:
            confidence = max(confidence - 5, 0)

        # MACD
        if direction == "BUY"  and last_hist > 0: confidence = min(confidence + 5, 100)
        elif direction == "SELL" and last_hist < 0: confidence = min(confidence + 5, 100)

        # Конфлікт з контекстним ТФ — суттєвий штраф
        if direction != "NEUTRAL" and ctx_trend["direction"] not in (trend["direction"], "sideways"):
            confidence = max(confidence - 20, 0)

        # Торгівля поза ключовими сесіями (для Forex)
        if session == "off_hours" and "USD" in symbol:
            confidence = max(confidence - 10, 0)

        # VWAP підтвердження
        if vwap_val and direction == "BUY" and last_close > vwap_val:
            confidence = min(confidence + 5, 100)
        elif vwap_val and direction == "SELL" and last_close < vwap_val:
            confidence = min(confidence + 5, 100)

        # ── SL та TP (структурний підхід) ─────────────────────────────────────
        sl_dist = last_atr * ATR_SL_MULTIPLIER

        if direction == "BUY":
            # SL нижче найближчої підтримки або ATR × 1.5
            if levels["nearest_support"]:
                sl = min(levels["nearest_support"] - last_atr * 0.3,
                         last_close - sl_dist)
            else:
                sl = last_close - sl_dist

            tp1 = last_close + abs(last_close - sl) * MIN_RR
            tp2 = last_close + abs(last_close - sl) * 3.0

            # Обрізаємо TP1 перед сильним опором
            if levels["nearest_resistance"]:
                tp1 = min(tp1, levels["nearest_resistance"] * 0.999)

        elif direction == "SELL":
            if levels["nearest_resistance"]:
                sl = max(levels["nearest_resistance"] + last_atr * 0.3,
                         last_close + sl_dist)
            else:
                sl = last_close + sl_dist

            tp1 = last_close - abs(sl - last_close) * MIN_RR
            tp2 = last_close - abs(sl - last_close) * 3.0

            if levels["nearest_support"]:
                tp1 = max(tp1, levels["nearest_support"] * 1.001)
        else:
            sl = tp1 = tp2 = last_close

        rr = abs(tp1 - last_close) / max(abs(sl - last_close), 1e-10)

        # Остаточний фільтр: якщо RR < 1.5 — понижаємо confidence
        if rr < 1.5 and direction != "NEUTRAL":
            confidence = max(confidence - 15, 0)

        return {
            "symbol": symbol, "timeframe": tf, "context_tf": ctx_tf,
            "price": last_close, "direction": direction, "confidence": confidence,
            "best_strategy": best, "all_strategies": all_strats,
            "trend": trend, "ctx_trend": ctx_trend,
            "levels": levels, "structure": struct, "adx": adx_d,
            "rsi": last_rsi, "stoch_rsi": last_stoch, "atr": last_atr,
            "macd_hist": last_hist,
            "bb_upper": _safe(bb_up.iloc[-1]),
            "bb_lower": _safe(bb_low.iloc[-1]),
            "vwap": vwap_val,
            "session": session,
            "sl": sl, "tp1": tp1, "tp2": tp2, "rr": rr,
            "candle_patterns": pats,
            "timestamp": datetime.now(),
        }

    # ══════════════════════════════════════════════════════════════════════════
    #  СКАН РИНКУ
    # ══════════════════════════════════════════════════════════════════════════

    async def scan_market(self, symbols: list, tf="1h") -> list:
        results = []
        for sym in symbols:
            try:
                r = await self.analyze(sym, tf, "all")
                results.append({
                    "symbol":        sym,
                    "signal":        r["direction"],
                    "confidence":    r["confidence"],
                    "best_strategy": r["best_strategy"]["name"],
                    "rsi":           round(r["rsi"], 1),
                    "adx":           round(r["adx"]["adx"], 1),
                    "price":         r["price"],
                    "rr":            round(r["rr"], 2),
                    "trend":         r["trend"]["direction"],
                    "patterns":      r["candle_patterns"],
                    "session":       r["session"],
                })
                await asyncio.sleep(REQUEST_DELAY)
            except Exception as e:
                logger.warning(f"Scan fail {sym}: {e}")
                results.append({
                    "symbol": sym, "signal": "ERROR", "confidence": 0,
                    "best_strategy": "N/A", "rsi": 50, "adx": 0,
                    "price": 0, "rr": 0, "trend": "unknown",
                    "patterns": [], "session": "unknown",
                })

        # Сортуємо: спочатку сильні сигнали за confidence
        results.sort(key=lambda x: (
            0 if x["signal"] in ("BUY", "SELL") else 1,
            -x["confidence"]
        ))
        return results
