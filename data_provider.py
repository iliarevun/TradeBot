"""
Data Provider — завантаження ринкових даних
Підтримує: Twelve Data → Alpha Vantage → yfinance (fallback)
"""
import asyncio
import aiohttp
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional
from config import (
    TWELVE_DATA_KEY, ALPHA_VANTAGE_KEY, CANDLES_COUNT, REQUEST_DELAY
)

logger = logging.getLogger(__name__)

# ── Маппінги таймфреймів ──────────────────────────────────────────────────────

TD_TF = {   # Twelve Data
    "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1h",   "4h": "4h",    "1d": "1day", "1wk": "1week",
}
AV_TF = {   # Alpha Vantage
    "5m": "5min", "15m": "15min", "30m": "30min", "1h": "60min",
}
YF_TF = {   # yfinance
    "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "1h",   "1d": "1d", "1wk": "1wk",
}
YF_PERIOD = {
    "5m": "5d",  "15m": "15d", "30m": "30d",
    "1h": "60d", "4h":  "180d","1d": "365d", "1wk": "730d",
}

# Символи для різних провайдерів
def normalize_symbol(symbol: str, provider: str) -> str:
    """Конвертує символ пари для конкретного провайдера"""
    # yfinance Forex формат
    YF_MAP = {
        "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
        "USDCHF": "USDCHF=X", "AUDUSD": "AUDUSD=X", "NZDUSD": "NZDUSD=X",
        "USDCAD": "USDCAD=X", "EURGBP": "EURGBP=X",
    }
    # Cleaned base symbol (без суфіксів)
    base = symbol.replace("=X", "").replace("-USD", "").replace("/", "").upper()

    if provider == "yfinance":
        return YF_MAP.get(base, symbol)
    elif provider in ("twelvedata", "alphavantage"):
        # Forex: "EUR/USD", Crypto: "BTC/USD"
        if base in ("BTCUSD", "ETHUSD", "BNBUSD", "SOLUSD", "XRPUSD", "ADAUSD"):
            return base[:3] + "/USD"
        elif base in ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD",
                      "NZDUSD", "USDCAD", "EURGBP"):
            return base[:3] + "/" + base[3:]
        elif base in ("GCUSD", "GCF"):
            return "XAU/USD"
        elif base in ("SPGSPC", "GSPC"):
            return "SPX"
        return base
    return symbol


class DataProvider:
    """Мультипровайдерне завантаження OHLCV"""

    def __init__(self):
        self._cache: dict = {}
        self._cache_time: dict = {}

    def _cache_key(self, symbol, tf):
        return f"{symbol}_{tf}"

    def _is_cached(self, key, ttl=300):
        if key in self._cache and key in self._cache_time:
            age = (datetime.now() - self._cache_time[key]).total_seconds()
            return age < ttl
        return False

    async def get_ohlcv(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        """Завантажити дані з кешем та fallback"""
        key = self._cache_key(symbol, tf)
        ttl = 300 if tf in ("5m", "15m", "30m") else 1800

        if self._is_cached(key, ttl):
            return self._cache[key]

        df = None

        # Провайдер 1: Twelve Data (якщо є ключ)
        if TWELVE_DATA_KEY and not df:
            try:
                df = await self._twelve_data(symbol, tf)
                if df is not None and len(df) >= 20:
                    logger.info(f"TwelveData OK: {symbol} {tf} ({len(df)} bars)")
            except Exception as e:
                logger.warning(f"TwelveData fail {symbol}: {e}")

        # Провайдер 2: Alpha Vantage (якщо є ключ і TF підходить)
        if ALPHA_VANTAGE_KEY and not df and tf in AV_TF:
            try:
                df = await self._alpha_vantage(symbol, tf)
                if df is not None and len(df) >= 20:
                    logger.info(f"AlphaVantage OK: {symbol} {tf} ({len(df)} bars)")
            except Exception as e:
                logger.warning(f"AlphaVantage fail {symbol}: {e}")

        # Провайдер 3: yfinance (завжди як fallback)
        if not df:
            try:
                df = await self._yfinance(symbol, tf)
                if df is not None and len(df) >= 20:
                    logger.info(f"yfinance OK: {symbol} {tf} ({len(df)} bars)")
            except Exception as e:
                logger.warning(f"yfinance fail {symbol}: {e}")

        if df is not None and len(df) >= 20:
            self._cache[key] = df
            self._cache_time[key] = datetime.now()
            return df

        return None

    # ── Twelve Data ───────────────────────────────────────────────────────────

    async def _twelve_data(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        sym = normalize_symbol(symbol, "twelvedata")
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
            raise ValueError(f"TD: {data.get('message', 'no values')}")

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
        sym = normalize_symbol(symbol, "alphavantage")
        interval = AV_TF.get(tf, "60min")
        base = symbol.replace("=X","").replace("-USD","").upper()
        is_forex = base in ("EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","NZDUSD","USDCAD","EURGBP")

        if is_forex and tf == "1d":
            func = "FX_DAILY"
            from_sym, to_sym = sym[:3], sym[4:]
            url = (f"https://www.alphavantage.co/query?function={func}"
                   f"&from_symbol={from_sym}&to_symbol={to_sym}"
                   f"&outputsize=compact&apikey={ALPHA_VANTAGE_KEY}")
            ts_key = "Time Series FX (Daily)"
        elif is_forex:
            func = "FX_INTRADAY"
            from_sym, to_sym = sym[:3], sym[4:]
            url = (f"https://www.alphavantage.co/query?function={func}"
                   f"&from_symbol={from_sym}&to_symbol={to_sym}"
                   f"&interval={interval}&outputsize=compact&apikey={ALPHA_VANTAGE_KEY}")
            ts_key = f"Time Series FX ({interval})"
        else:
            return None  # AV crypto потребує платного ключа

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(url) as resp:
                data = await resp.json()

        if ts_key not in data:
            raise ValueError(f"AV: {list(data.keys())}")

        rows = []
        for dt_str, v in sorted(data[ts_key].items()):
            rows.append({
                "open": float(v.get("1. open", v.get("open", 0))),
                "high": float(v.get("2. high", v.get("high", 0))),
                "low":  float(v.get("3. low",  v.get("low", 0))),
                "close":float(v.get("4. close", v.get("close", 0))),
                "volume": 0,
            })
        return pd.DataFrame(rows).tail(CANDLES_COUNT)

    # ── yfinance (sync in executor) ───────────────────────────────────────────

    async def _yfinance(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._yf_download, symbol, tf)

    def _yf_download(self, symbol: str, tf: str) -> Optional[pd.DataFrame]:
        try:
            import yfinance as yf
            sym = normalize_symbol(symbol, "yfinance")
            interval = YF_TF.get(tf, "1h")
            period = YF_PERIOD.get(tf, "60d")

            ticker = yf.Ticker(sym)
            df = ticker.history(period=period, interval=interval)

            if df.empty or len(df) < 10:
                return None

            # 4h aggregation from 1h
            if tf == "4h":
                df = df.resample("4h").agg({
                    "Open": "first", "High": "max",
                    "Low": "min",   "Close": "last", "Volume": "sum"
                }).dropna()

            df = df.rename(columns={
                "Open": "open", "High": "high",
                "Low": "low", "Close": "close", "Volume": "volume"
            })[["open","high","low","close","volume"]]

            return df.tail(CANDLES_COUNT).reset_index(drop=True)
        except Exception as e:
            logger.error(f"yf_download error {symbol} {tf}: {e}")
            return None

    def clear_cache(self):
        self._cache.clear()
        self._cache_time.clear()
