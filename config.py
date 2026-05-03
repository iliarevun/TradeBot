"""
Конфігурація бота
"""
# ── Telegram ──────────────────────────────────────────────────────────────────
BOT_TOKEN  = "8459945082:AAECYkWNOE0T_mueF3hpPcY9XXZMhW1mfig"
WEBAPP_URL = "https://iliarevun.github.io/TradeBot/webapp/"

# ── API ключі (ВИПРАВЛЕНО: Alpha Vantage був URL замість ключа!) ──────────────
TWELVE_DATA_KEY   = "2ae21e0394c14b51a2eda20530184f66"
ALPHA_VANTAGE_KEY = ""   # Отримайте безкоштовно: alphavantage.co/support/#api-key

# ── Параметри аналізу ─────────────────────────────────────────────────────────
EMA_FAST   = 21
EMA_SLOW   = 50
EMA_TREND  = 200
RSI_PERIOD = 14
RSI_OVERSOLD   = 30
RSI_OVERBOUGHT = 70
ATR_PERIOD = 14
ATR_SL_MULTIPLIER = 1.5
MIN_RR     = 2.0
CANDLES_COUNT = 100

CONTEXT_TIMEFRAMES = {
    "5m": "1h", "15m": "4h", "30m": "4h",
    "1h": "1d", "4h": "1d",  "1d": "1wk",
}

REQUEST_DELAY     = 1.0
MIN_SIGNAL_STRENGTH = 40
