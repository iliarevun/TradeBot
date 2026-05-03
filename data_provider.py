"""
Data Provider — завантаження ринкових даних
Підтримує: Twelve Data → Alpha Vantage → yfinance (fallback)
"""
import asyncio
import aiohttp
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional
from config import (
    TWELVE_DATA_KEY, ALPHA_VANTAGE_KEY, CANDLES_COUNT, REQUEST_DELAY
)

logger = logging.getLogger(__name__)

TD_TF  = {"5m":"5min","15m":"15min","30m":"30min","1h":"1h","4h":"4h","1d":"1day","1wk":"1week"}
AV_TF  = {"5m":"5min","15m":"15min","30m":"30min","1h":"60min"}
YF_TF  = {"5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1wk":"1wk"}
YF_PERIOD = {"5m":"5d","15m":"15d","30m":"30d","1h":"60d","4h":"180d","1d":"365d","1wk":"730d"}

REQUIRED_COLS = ["open","high","low","close","volume"]

def _ok(df) -> bool:
    """Безпечна перевірка: DataFrame не None і має достатньо рядків"""
    return df is not None and isinstance(df, pd.DataFrame) and len(df) >= 20

def _sanitize(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Приводить DataFrame до стандартного вигляду:
    - плоскі (не MultiIndex) колонки open/high/low/close/volume
    - числові значення float64
    - скидає індекс
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None

    # Якщо MultiIndex колонок (yfinance новий формат) — беремо перший рівень
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(1, axis=1) if df.columns.nlevels == 2 else df
        df.columns = [str(c).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]

    # Перейменовуємо можливі варіанти назв
    rename_map = {
        "open":"open","high":"high","low":"low","close":"close","volume":"volume",
        "1. open":"open","2. high":"high","3. low":"low","4. close":"close",
        "adj close":"close","adjclose":"close",
    }
    df = df.rename(columns=rename_map)

    # Перевіряємо наявність обов'язкових колонок
    for col in ["open","high","low","close"]:
        if col not in df.columns:
            return None

    if "volume" not in df.columns:
        df["volume"] = 0.0

    df = df[["open","high","low","close","volume"]].copy()

    # Конвертуємо у float і прибираємо NaN
    for col in REQUIRED_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open","high","low","close"])

    if len(df) < 20:
        return None

    df = df.reset_index(drop=True)
    return df.tail(CANDLES_COUNT)


def normalize_symbol(symbol: str, provider: str) -> str:
    YF_MAP = {
        "EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X","USDJPY":"USDJPY=X",
        "USDCHF":"USDCHF=X","AUDUSD":"AUDUSD=X","NZDUSD":"NZDUSD=X",
        "USDCAD":"USDCAD=X","EURGBP":"EURGBP=X",
    }
    base = symbol.replace("=X","").replace("-USD","").replace("/","").upper()

    if provider == "yfinance":
        return YF_MAP.get(base, symbol)

    if provider in ("twelvedata","alphavantage"):
        crypto_bases = ("BTC","ETH","BNB","SOL","XRP","ADA","DOT","AVAX")
        forex_pairs = ("EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","NZDUSD","USDCAD","EURGBP")
        if any(base.startswith(c) for c in crypto_bases):
            return base[:3] + "/USD"
        elif base in forex_pairs:
            return base[:3] + "/" + base[3:]
        elif base in ("GCF","GCUSD","XAU"):
            return "XAU/USD"
        return base

    return symbol


class DataProvider:

    def __init__(self):
        self._cache: dict = {}
        self._cache_time: dict = {}

    def _cache_key(self, symbol, tf): return f"{symbol}_{tf}"

    def _is_cached(self, key, ttl=300):
        if key in self._cache and key in self._cache_time:
            return (datetime.now() - self._cache_time[key]).total_seconds() < ttl
        return False

    async def get_ohlcv(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        key = self._cache_key(symbol, tf)
        ttl = 300 if tf in ("5m","15m","30m") else 1800

        if self._is_cached(key, ttl):
            return self._cache[key]

        df = None

        # ── Twelve Data ──────────────────────────────────────────────────────
        if TWELVE_DATA_KEY and not _ok(df):
            try:
                raw = await self._twelve_data(symbol, tf)
                df  = _sanitize(raw)
                if _ok(df):
                    logger.info(f"TwelveData OK: {symbol} {tf} ({len(df)} bars)")
                else:
                    df = None
            except Exception as e:
                logger.warning(f"TwelveData fail {symbol}: {e}")
                df = None

        # ── Alpha Vantage ────────────────────────────────────────────────────
        if ALPHA_VANTAGE_KEY and not _ok(df) and tf in AV_TF:
            try:
                raw = await self._alpha_vantage(symbol, tf)
                df  = _sanitize(raw)
                if _ok(df):
                    logger.info(f"AlphaVantage OK: {symbol} {tf} ({len(df)} bars)")
                else:
                    df = None
            except Exception as e:
                logger.warning(f"AlphaVantage fail {symbol}: {e}")
                df = None

        # ── yfinance fallback ────────────────────────────────────────────────
        if not _ok(df):
            try:
                raw = await self._yfinance(symbol, tf)
                df  = _sanitize(raw)
                if _ok(df):
                    logger.info(f"yfinance OK: {symbol} {tf} ({len(df)} bars)")
                else:
                    df = None
            except Exception as e:
                logger.warning(f"yfinance fail {symbol}: {e}")
                df = None

        if _ok(df):
            self._cache[key]      = df
            self._cache_time[key] = datetime.now()
            return df

        return None

    # ── Twelve Data ───────────────────────────────────────────────────────────

    async def _twelve_data(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        sym      = normalize_symbol(symbol, "twelvedata")
        interval = TD_TF.get(tf, "1h")
        url = (
            f"https://api.twelvedata.com/time_series"
            f"?symbol={sym}&interval={interval}&outputsize={CANDLES_COUNT}"
            f"&apikey={TWELVE_DATA_KEY}&format=JSON"
        )
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(url) as resp:
                data = await resp.json()

        if "values" not in data:
            raise ValueError(f"TD error: {data.get('message','no values')}")

        rows = []
        for v in reversed(data["values"]):
            rows.append({
                "open":   float(v["open"]),
                "high":   float(v["high"]),
                "low":    float(v["low"]),
                "close":  float(v["close"]),
                "volume": float(v.get("volume", 0)),
            })
        return pd.DataFrame(rows)

    # ── Alpha Vantage ─────────────────────────────────────────────────────────

    async def _alpha_vantage(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        sym      = normalize_symbol(symbol, "alphavantage")
        interval = AV_TF.get(tf, "60min")
        base     = symbol.replace("=X","").replace("-USD","").upper()
        is_forex = base in ("EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","NZDUSD","USDCAD","EURGBP")

        if is_forex and tf == "1d":
            from_sym, to_sym = sym[:3], sym[4:]
            url = (f"https://www.alphavantage.co/query?function=FX_DAILY"
                   f"&from_symbol={from_sym}&to_symbol={to_sym}"
                   f"&outputsize=compact&apikey={ALPHA_VANTAGE_KEY}")
            ts_key = "Time Series FX (Daily)"
        elif is_forex:
            from_sym, to_sym = sym[:3], sym[4:]
            url = (f"https://www.alphavantage.co/query?function=FX_INTRADAY"
                   f"&from_symbol={from_sym}&to_symbol={to_sym}"
                   f"&interval={interval}&outputsize=compact&apikey={ALPHA_VANTAGE_KEY}")
            ts_key = f"Time Series FX ({interval})"
        else:
            return None

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(url) as resp:
                data = await resp.json()

        if ts_key not in data:
            raise ValueError(f"AV: {list(data.keys())}")

        rows = []
        for dt_str, v in sorted(data[ts_key].items()):
            rows.append({
                "open":   float(v.get("1. open",  v.get("open",  0))),
                "high":   float(v.get("2. high",  v.get("high",  0))),
                "low":    float(v.get("3. low",   v.get("low",   0))),
                "close":  float(v.get("4. close", v.get("close", 0))),
                "volume": 0.0,
            })
        return pd.DataFrame(rows)

    # ── yfinance ──────────────────────────────────────────────────────────────

    async def _yfinance(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._yf_download, symbol, tf)

    def _yf_download(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        try:
            import yfinance as yf
            sym      = normalize_symbol(symbol, "yfinance")
            interval = YF_TF.get(tf, "1h")
            period   = YF_PERIOD.get(tf, "60d")

            ticker = yf.Ticker(sym)
            df     = ticker.history(period=period, interval=interval)

            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                return None

            # 4h aggregation from 1h
            if tf == "4h":
                df = df.resample("4h").agg({
                    "Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"
                }).dropna()

            return df  # _sanitize handles renaming

        except Exception as e:
            logger.error(f"yf_download {symbol} {tf}: {e}")
            return None

    def clear_cache(self):
        self._cache.clear()
        self._cache_time.clear()
