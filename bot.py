"""
TradeBot v2 — Telegram Trading Analysis Bot
"""
import asyncio, logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, WEBAPP_URL
from analyzer import MarketAnalyzer
from messages import (
    WELCOME_MSG, HELP_MSG, LOADING_MSG,
    format_signal, format_scan_result
)

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot      = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp       = Dispatcher(storage=MemoryStorage())
analyzer = MarketAnalyzer()

# ── Символи ───────────────────────────────────────────────────────────────────
PAIRS = {
    "forex": [
        ("EUR/USD 🇪🇺","EURUSD=X"), ("GBP/USD 🇬🇧","GBPUSD=X"),
        ("USD/JPY 🇯🇵","USDJPY=X"), ("USD/CHF 🇨🇭","USDCHF=X"),
        ("AUD/USD 🇦🇺","AUDUSD=X"), ("NZD/USD 🇳🇿","NZDUSD=X"),
        ("USD/CAD 🇨🇦","USDCAD=X"), ("EUR/GBP 🌍","EURGBP=X"),
    ],
    "crypto": [
        ("BTC/USD ₿","BTC-USD"), ("ETH/USD Ξ","ETH-USD"),
        ("BNB/USD","BNB-USD"),   ("SOL/USD","SOL-USD"),
        ("XRP/USD","XRP-USD"),   ("ADA/USD","ADA-USD"),
    ],
    "indices": [
        ("S&P 500","^GSPC"), ("NASDAQ","^IXIC"),
        ("DAX","^GDAXI"),    ("FTSE 100","^FTSE"),
    ],
    "commodities": [
        ("Золото XAU","GC=F"), ("Нафта WTI","CL=F"), ("Срібло","SI=F"),
    ],
}

SCAN_PAIRS = {
    "forex":  ["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCHF=X","USDCAD=X"],
    "crypto": ["BTC-USD","ETH-USD","BNB-USD","SOL-USD"],
    "all":    ["EURUSD=X","GBPUSD=X","USDJPY=X","BTC-USD","ETH-USD","GC=F","^GSPC"],
}

# ── Keyboards ─────────────────────────────────────────────────────────────────

def _btn(text, data): return InlineKeyboardButton(text=text, callback_data=data)
def _url_btn(text, url): return InlineKeyboardButton(text=text, url=url)
def _webapp_btn(text, url): return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))

def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📊 Аналіз пари","menu_analyze"),      _btn("🔍 Авто-скан","menu_scan")],
        [_btn("📱 Mini App (графіки)","menu_webapp"), _btn("📚 Стратегії","menu_strategies")],
        [_btn("⚙️ Налаштування","menu_settings"),    _btn("❓ Допомога","menu_help")],
    ])

def kb_pairs(cat="forex"):
    b = InlineKeyboardBuilder()
    cats = [("💱 Forex","forex"),("₿ Крипто","crypto"),
            ("📊 Індекси","indices"),("🥇 Товари","commodities")]
    for lbl,c in cats:
        b.button(text=("✅ " if c==cat else "")+lbl, callback_data=f"cat_{c}")
    b.adjust(4)
    for lbl,sym in PAIRS.get(cat,[]):
        b.button(text=lbl, callback_data=f"pair_{sym}")
    b.adjust(4, *([2]*10))
    b.button(text="🏠 Меню", callback_data="menu_main")
    return b.as_markup()

def kb_timeframes(sym):
    tfs = [("M5","5m"),("M15","15m"),("M30","30m"),
           ("H1","1h"),("H4","4h"),("D1","1d")]
    b = InlineKeyboardBuilder()
    for lbl,tf in tfs:
        b.button(text=lbl, callback_data=f"tf_{sym}_{tf}")
    b.adjust(3)
    b.button(text="◀️ Назад", callback_data="menu_analyze")
    b.button(text="🏠 Меню",  callback_data="menu_main")
    b.adjust(3,3,2)
    return b.as_markup()

def kb_strategies(sym, tf):
    strats = [
        ("1️⃣ Відбій від рівня","s1"), ("2️⃣ Пробій+ретест","s2"),
        ("3️⃣ Тренд+корекція","s3"),   ("4️⃣ Діапазон","s4"),
        ("5️⃣ EMA Crossover","s5"),    ("🔥 Всі стратегії","all"),
    ]
    b = InlineKeyboardBuilder()
    for lbl,s in strats:
        b.button(text=lbl, callback_data=f"strat_{sym}_{tf}_{s}")
    b.adjust(2)
    b.button(text="◀️ Назад", callback_data=f"pair_{sym}")
    b.button(text="🏠 Меню",  callback_data="menu_main")
    b.adjust(2,2,2,2)
    return b.as_markup()

def kb_signal(sym, tf):
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Оновити",       callback_data=f"refresh_{sym}_{tf}")
    b.button(text="📊 Інший ТФ",      callback_data=f"pair_{sym}")
    b.button(text="🔍 Скан ринку",    callback_data="menu_scan")
    b.button(text="📱 Mini App",       callback_data="menu_webapp")
    b.button(text="🏠 Меню",          callback_data="menu_main")
    b.adjust(2,2,1)
    return b.as_markup()

def kb_scan():
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("💱 Forex","scan_forex"),  _btn("₿ Крипто","scan_crypto")],
        [_btn("🌐 Всі ринки","scan_all")],
        [_btn("🏠 Меню","menu_main")],
    ])

def kb_webapp():
    b = InlineKeyboardBuilder()
    if WEBAPP_URL and WEBAPP_URL != "https://your-domain.com":
        b.button(text="📱 Відкрити Mini App", web_app=WebAppInfo(url=WEBAPP_URL))
    else:
        b.button(text="⚠️ Mini App не налаштовано", callback_data="webapp_setup")
    b.button(text="🏠 Меню", callback_data="menu_main")
    b.adjust(1)
    return b.as_markup()

# ── Handlers: команди ─────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(msg: types.Message):
    await msg.answer(WELCOME_MSG.format(name=msg.from_user.first_name or "Трейдер"),
                     reply_markup=kb_main())

@dp.message(Command("help"))
async def cmd_help(msg: types.Message):
    await msg.answer(HELP_MSG, reply_markup=kb_main())

@dp.message(Command("menu"))
async def cmd_menu(msg: types.Message):
    await msg.answer("🏠 <b>Головне меню</b>", reply_markup=kb_main())

@dp.message(Command("scan"))
async def cmd_scan(msg: types.Message):
    await msg.answer("🔍 <b>Авто-скан</b>\n\nОберіть категорію:", reply_markup=kb_scan())

@dp.message()
async def handle_text(msg: types.Message):
    await msg.answer(
        "Використовуйте кнопки меню 👇\n/start — головне меню",
        reply_markup=kb_main()
    )

# ── Handlers: callback ────────────────────────────────────────────────────────

@dp.callback_query(lambda c: c.data == "menu_main")
async def cb_main(cb: CallbackQuery):
    await cb.message.edit_text("🏠 <b>Головне меню</b>", reply_markup=kb_main())

@dp.callback_query(lambda c: c.data == "menu_analyze")
async def cb_analyze(cb: CallbackQuery):
    await cb.message.edit_text("📊 <b>Оберіть пару:</b>", reply_markup=kb_pairs("forex"))

@dp.callback_query(lambda c: c.data.startswith("cat_"))
async def cb_cat(cb: CallbackQuery):
    cat = cb.data[4:]
    await cb.message.edit_text("📊 <b>Оберіть пару:</b>", reply_markup=kb_pairs(cat))

@dp.callback_query(lambda c: c.data.startswith("pair_"))
async def cb_pair(cb: CallbackQuery):
    sym = cb.data[5:]
    await cb.message.edit_text(
        f"⏱ <b>Оберіть таймфрейм для {sym}:</b>\n\n"
        f"💡 <i>H1/H4 — для торгівлі · D1 — для контексту</i>",
        reply_markup=kb_timeframes(sym)
    )

@dp.callback_query(lambda c: c.data.startswith("tf_"))
async def cb_tf(cb: CallbackQuery):
    parts = cb.data.split("_")
    tf  = parts[-1]
    sym = "_".join(parts[1:-1])
    await cb.message.edit_text(
        f"📐 <b>Стратегія для {sym} {tf}:</b>\n\n"
        f"💡 <i>«Всі стратегії» — найповніший аналіз</i>",
        reply_markup=kb_strategies(sym, tf)
    )

@dp.callback_query(lambda c: c.data.startswith("strat_"))
async def cb_strat(cb: CallbackQuery):
    parts  = cb.data.split("_")
    strat  = parts[-1]
    tf     = parts[-2]
    sym    = "_".join(parts[1:-2])
    await cb.message.edit_text(f"⏳ <b>Аналізую {sym} {tf}...</b>\n\n{LOADING_MSG}")
    try:
        r    = await analyzer.analyze(sym, tf, strat)
        text = format_signal(r, sym, tf)
        await cb.message.edit_text(text, reply_markup=kb_signal(sym, tf))
    except Exception as e:
        logger.error(f"analyze error: {e}")
        await cb.message.edit_text(
            f"❌ <b>Помилка аналізу {sym}</b>\n\n"
            f"Причина: <code>{str(e)[:200]}</code>\n\n"
            f"💡 <b>Рішення:</b>\n"
            f"• Додайте безкоштовний ключ Twelve Data у config.py\n"
            f"• Або Alpha Vantage (alphavantage.co)\n"
            f"• Спробуйте інший таймфрейм або пару",
            reply_markup=kb_signal(sym, tf)
        )

@dp.callback_query(lambda c: c.data.startswith("refresh_"))
async def cb_refresh(cb: CallbackQuery):
    parts = cb.data.split("_")
    tf    = parts[-1]
    sym   = "_".join(parts[1:-1])
    await cb.message.edit_text(f"🔄 <b>Оновлюю {sym} {tf}...</b>\n\n{LOADING_MSG}")
    try:
        r    = await analyzer.analyze(sym, tf, "all")
        text = format_signal(r, sym, tf)
        await cb.message.edit_text(text, reply_markup=kb_signal(sym, tf))
    except Exception as e:
        await cb.message.edit_text(
            f"❌ Помилка оновлення: <code>{str(e)[:150]}</code>",
            reply_markup=kb_signal(sym, tf)
        )

@dp.callback_query(lambda c: c.data == "menu_scan")
async def cb_scan_menu(cb: CallbackQuery):
    await cb.message.edit_text(
        "🔍 <b>Авто-скан ринку</b>\n\n"
        "Бот перевіряє пари за 5 стратегіями та видає ТОП сигналів.\n\n"
        "Оберіть категорію:",
        reply_markup=kb_scan()
    )

@dp.callback_query(lambda c: c.data.startswith("scan_"))
async def cb_scan(cb: CallbackQuery):
    cat   = cb.data[5:]
    pairs = SCAN_PAIRS.get(cat, SCAN_PAIRS["forex"])
    await cb.message.edit_text(
        f"🔍 <b>Сканую {len(pairs)} пар на H1...</b>\n\n"
        f"⏳ Зачекайте 20–40 секунд...\n\n" + "⬛"*5 + "⬜"*5
    )
    try:
        results = await analyzer.scan_market(pairs)
        text    = format_scan_result(results)

        b = InlineKeyboardBuilder()
        for r in results[:4]:
            if r["signal"] in ("BUY","SELL"):
                icon = "🟢" if r["signal"]=="BUY" else "🔴"
                b.button(text=f"{icon} {r['symbol']}", callback_data=f"pair_{r['symbol']}")
        b.button(text="🔄 Повторити скан", callback_data=f"scan_{cat}")
        b.button(text="🏠 Меню", callback_data="menu_main")
        b.adjust(2,2,1,1)
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except Exception as e:
        logger.error(f"scan error: {e}")
        await cb.message.edit_text(
            f"❌ Помилка сканування: <code>{str(e)[:150]}</code>",
            reply_markup=kb_scan()
        )

@dp.callback_query(lambda c: c.data == "menu_webapp")
async def cb_webapp(cb: CallbackQuery):
    if WEBAPP_URL and WEBAPP_URL != "https://your-domain.com":
        await cb.message.edit_text(
            "📱 <b>Trading Mini App</b>\n\n"
            "Інтерактивні графіки, аналіз та сигнали прямо в Telegram!\n\n"
            "Натисніть кнопку нижче 👇",
            reply_markup=kb_webapp()
        )
    else:
        await cb.message.edit_text(
            "📱 <b>Mini App — Налаштування</b>\n\n"
            "Щоб увімкнути Mini App:\n\n"
            "1️⃣ Задеплойте папку <code>webapp/</code> на хостинг\n"
            "   (GitHub Pages, Netlify, Vercel — безкоштовно)\n\n"
            "2️⃣ Вставте URL у <code>config.py</code>:\n"
            "   <code>WEBAPP_URL = \"https://your-site.com\"</code>\n\n"
            "3️⃣ Перезапустіть бота\n\n"
            "📖 Детальніше: README.md → розділ Mini App",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [_btn("🏠 Меню","menu_main")]
            ])
        )

@dp.callback_query(lambda c: c.data == "webapp_setup")
async def cb_webapp_setup(cb: CallbackQuery):
    await cb_webapp(cb)

@dp.callback_query(lambda c: c.data == "menu_strategies")
async def cb_strategies(cb: CallbackQuery):
    await cb.message.edit_text(
        "📚 <b>5 Торгових стратегій</b>\n\n"
        "1️⃣ <b>Відбій від рівня</b> ⭐☆☆☆\n"
        "Пін-бар або поглинання біля ключового рівня.\n\n"
        "2️⃣ <b>Пробій + ретест</b> ⭐⭐☆☆\n"
        "Пробій рівня → ретест → продовження руху.\n\n"
        "3️⃣ <b>Тренд + корекція</b> ⭐⭐⭐☆\n"
        "Вхід на корекції до EMA 21/50 в напрямку тренду.\n\n"
        "4️⃣ <b>Діапазонна торгівля</b> ⭐⭐☆☆\n"
        "Купівля знизу, продаж зверху діапазону (флет).\n\n"
        "5️⃣ <b>EMA Crossover + PA</b> ⭐⭐⭐⭐\n"
        "EMA 21 × EMA 50 перетин + паттерн підтвердження.\n\n"
        "💡 <i>Новачкам: починайте зі стратегій 1 і 2</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("📊 Застосувати","menu_analyze")],
            [_btn("🏠 Меню","menu_main")],
        ])
    )

@dp.callback_query(lambda c: c.data == "menu_settings")
async def cb_settings(cb: CallbackQuery):
    await cb.message.edit_text(
        "⚙️ <b>Налаштування</b>\n\n"
        "Для зміни параметрів відредагуйте <code>config.py</code>:\n\n"
        "• <code>EMA_FAST = 21</code> — швидка EMA\n"
        "• <code>EMA_SLOW = 50</code> — повільна EMA\n"
        "• <code>ATR_SL_MULTIPLIER = 1.5</code> — розмір SL\n"
        "• <code>MIN_RR = 2.0</code> — мін. Risk:Reward\n"
        "• <code>TWELVE_DATA_KEY = \"...\"</code> — ключ API\n\n"
        "📡 <b>Джерело даних:</b>\n"
        "Twelve Data (рекомендовано) → Alpha Vantage → yfinance",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [_btn("🏠 Меню","menu_main")]
        ])
    )

@dp.callback_query(lambda c: c.data == "menu_help")
async def cb_help(cb: CallbackQuery):
    await cb.message.edit_text(HELP_MSG, reply_markup=kb_main())

# ── Run ───────────────────────────────────────────────────────────────────────

async def main():
    logger.info("Starting TradeBot v2...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
