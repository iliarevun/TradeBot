"""
TradeBot v4 — Professional Telegram Trading Bot
"""
import asyncio, logging, json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, InputMediaPhoto
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, WEBAPP_URL
from analyzer import MarketAnalyzer
from messages import (
    WELCOME_MSG, HELP_MSG, LOADING_MSG, PAT_N,
    format_signal, format_scan_result, format_trade_report
)
from journal import (
    add_trade, close_trade, get_open_trades,
    get_all_trades, get_stats, format_stats
)
from education import get_lesson, get_category_menu, get_all_categories

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot      = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp       = Dispatcher(storage=MemoryStorage())
analyzer = MarketAnalyzer()

# ── FSM States ────────────────────────────────────────────────────────────────
class TradeStates(StatesGroup):
    waiting_close_price  = State()
    waiting_result_usd   = State()
    waiting_trade_symbol = State()
    waiting_trade_dir    = State()
    waiting_trade_entry  = State()

# ── Символи ───────────────────────────────────────────────────────────────────
PAIRS = {
    "forex": [
        ("EUR/USD 🇪🇺","EURUSD=X"),("GBP/USD 🇬🇧","GBPUSD=X"),
        ("USD/JPY 🇯🇵","USDJPY=X"),("USD/CHF 🇨🇭","USDCHF=X"),
        ("AUD/USD 🇦🇺","AUDUSD=X"),("NZD/USD 🇳🇿","NZDUSD=X"),
        ("USD/CAD 🇨🇦","USDCAD=X"),("EUR/GBP 🌍","EURGBP=X"),
    ],
    "crypto": [
        ("BTC/USD ₿","BTC-USD"),("ETH/USD Ξ","ETH-USD"),
        ("BNB/USD","BNB-USD"),("SOL/USD","SOL-USD"),
        ("XRP/USD","XRP-USD"),("ADA/USD","ADA-USD"),
    ],
    "indices": [
        ("S&P 500","^GSPC"),("NASDAQ","^IXIC"),
        ("DAX","^GDAXI"),("FTSE 100","^FTSE"),
    ],
    "commodities": [
        ("Золото XAU","GC=F"),("Нафта WTI","CL=F"),("Срібло","SI=F"),
    ],
}

SCAN_PAIRS = {
    "forex":  ["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCHF=X","USDCAD=X"],
    "crypto": ["BTC-USD","ETH-USD","BNB-USD","SOL-USD"],
    "all":    ["EURUSD=X","GBPUSD=X","USDJPY=X","BTC-USD","ETH-USD","GC=F","^GSPC"],
}

# Старші таймфрейми для кнопки "Старші ТФ"
SENIOR_TFS = [("W1 (Тиждень)","1wk"),("D1 (День)","1d"),("H4 (4 год)","4h")]
ALL_TFS    = [("M5","5m"),("M15","15m"),("M30","30m"),
              ("H1","1h"),("H4","4h"),("D1","1d"),("W1","1wk")]

# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Аналіз пари",     callback_data="menu_analyze"),
         InlineKeyboardButton(text="🔍 Авто-скан",       callback_data="menu_scan")],
        [InlineKeyboardButton(text="📈 Старші ТФ",       callback_data="menu_senior"),
         InlineKeyboardButton(text="📱 Mini App",        callback_data="menu_webapp")],
        [InlineKeyboardButton(text="📓 Журнал угод",     callback_data="menu_journal"),
         InlineKeyboardButton(text="🎓 Навчання",        callback_data="menu_learn")],
        [InlineKeyboardButton(text="❓ Допомога",        callback_data="menu_help")],
    ])

def kb_pairs(cat="forex"):
    b = InlineKeyboardBuilder()
    cats=[("💱 Forex","forex"),("₿ Крипто","crypto"),("📊 Індекси","indices"),("🥇 Товари","commodities")]
    for lbl,c in cats:
        b.button(text=("✅ " if c==cat else "")+lbl, callback_data=f"cat_{c}")
    b.adjust(4)
    for lbl,sym in PAIRS.get(cat,[]):
        b.button(text=lbl, callback_data=f"pair_{sym}")
    b.adjust(4,2,2,2,2)
    b.button(text="🏠 Меню", callback_data="menu_main")
    return b.as_markup()

def kb_timeframes(sym, senior=False):
    b = InlineKeyboardBuilder()
    tfs = SENIOR_TFS if senior else ALL_TFS
    for lbl,tf in tfs:
        b.button(text=lbl, callback_data=f"tf_{sym}_{tf}")
    b.adjust(3)
    b.button(text="◀️ Назад", callback_data="menu_analyze" if not senior else "menu_senior")
    b.button(text="🏠 Меню",  callback_data="menu_main")
    b.adjust(*([3]*10), 2)
    return b.as_markup()

def kb_signal(sym, tf):
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Оновити",    callback_data=f"refresh_{sym}_{tf}")
    b.button(text="📊 Інший ТФ",   callback_data=f"pair_{sym}")
    b.button(text="📝 Записати угоду", callback_data=f"log_trade_{sym}_{tf}")
    b.button(text="🔍 Скан",       callback_data="menu_scan")
    b.button(text="🏠 Меню",       callback_data="menu_main")
    b.adjust(2,1,2)
    return b.as_markup()

def kb_scan():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💱 Forex",     callback_data="scan_forex"),
         InlineKeyboardButton(text="₿ Крипто",    callback_data="scan_crypto")],
        [InlineKeyboardButton(text="🌐 Всі ринки", callback_data="scan_all")],
        [InlineKeyboardButton(text="🏠 Меню",      callback_data="menu_main")],
    ])

def kb_journal():
    b = InlineKeyboardBuilder()
    b.button(text="📝 Записати угоду",   callback_data="journal_add")
    b.button(text="📋 Відкриті угоди",   callback_data="journal_open")
    b.button(text="📊 Статистика",       callback_data="journal_stats")
    b.button(text="📜 Історія (10 last)",callback_data="journal_history")
    b.button(text="🏠 Меню",             callback_data="menu_main")
    b.adjust(2,2,1)
    return b.as_markup()

def kb_learn():
    b = InlineKeyboardBuilder()
    for key, title in get_all_categories():
        b.button(text=title, callback_data=f"learn_cat_{key}")
    b.adjust(1)
    b.button(text="🏠 Меню", callback_data="menu_main")
    return b.as_markup()

def kb_learn_cat(cat):
    b = InlineKeyboardBuilder()
    for key, title in get_category_menu(cat):
        b.button(text=title, callback_data=f"learn_topic_{key}")
    b.adjust(1)
    b.button(text="◀️ Назад до категорій", callback_data="menu_learn")
    b.button(text="🏠 Меню",               callback_data="menu_main")
    b.adjust(1)
    return b.as_markup()

def kb_learn_topic(key, cat=""):
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Назад до теми", callback_data=f"learn_cat_{cat}" if cat else "menu_learn")
    b.button(text="🏠 Меню",          callback_data="menu_main")
    b.adjust(2)
    return b.as_markup()

def kb_open_trades(trades):
    b = InlineKeyboardBuilder()
    for t in trades[:8]:
        sym = t.get("symbol","?"); d = t.get("direction","?")
        icon = "🟢" if d=="BUY" else "🔴"
        b.button(text=f"{icon} {sym} #{t['id']}", callback_data=f"close_trade_{t['id']}")
    b.button(text="◀️ Журнал", callback_data="menu_journal")
    b.button(text="🏠 Меню",   callback_data="menu_main")
    b.adjust(2)
    return b.as_markup()

# ── Helpers ───────────────────────────────────────────────────────────────────

def _pf(p, sym=""):
    if not p or p==0: return "N/A"
    try:
        v=float(p)
        if "BTC" in sym or v>1000: return f"{v:,.2f}"
        if v>10: return f"{v:.4f}"
        return f"{v:.5f}"
    except: return "N/A"

async def _do_analysis(msg_obj, sym, tf):
    """Запуск аналізу і відправка результату"""
    await msg_obj.edit_text(f"⏳ <b>Аналізую {sym} | {tf.upper()}...</b>\n\n{LOADING_MSG}")
    try:
        r    = await analyzer.analyze(sym, tf, "all")
        text = format_signal(r, sym, tf)
        await msg_obj.edit_text(text, reply_markup=kb_signal(sym, tf))
    except Exception as e:
        logger.error(f"analyze error {sym} {tf}: {e}")
        await msg_obj.edit_text(
            f"❌ <b>Помилка аналізу {sym} | {tf.upper()}</b>\n\n"
            f"<code>{str(e)[:250]}</code>\n\n"
            f"💡 Перевірте API ключ у config.py (TWELVE_DATA_KEY)",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад",callback_data=f"pair_{sym}")],
                [InlineKeyboardButton(text="🏠 Меню", callback_data="menu_main")],
            ])
        )

# ── Commands ──────────────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(msg: types.Message, state: FSMContext):
    await state.clear()
    await msg.answer(WELCOME_MSG.format(name=msg.from_user.first_name or "Трейдер"),
                     reply_markup=kb_main())

@dp.message(Command("help"))
async def cmd_help(msg: types.Message):
    await msg.answer(HELP_MSG, reply_markup=kb_main())

@dp.message(Command("menu"))
async def cmd_menu(msg: types.Message, state: FSMContext):
    await state.clear()
    await msg.answer("🏠 <b>Головне меню</b>", reply_markup=kb_main())

@dp.message(Command("scan"))
async def cmd_scan(msg: types.Message):
    await msg.answer("🔍 <b>Авто-скан ринку</b>\n\nОберіть категорію:", reply_markup=kb_scan())

@dp.message(Command("journal"))
async def cmd_journal(msg: types.Message):
    stats = get_stats()
    text = (f"📓 <b>Торговий журнал</b>\n\n"
            f"📊 Угод: {stats['total']} | 🟢 {stats['wins']} | 🔴 {stats['losses']}\n"
            f"💰 P&L: {'+'if stats['total_pnl']>=0 else ''}{stats['total_pnl']}$")
    await msg.answer(text, reply_markup=kb_journal())

@dp.message(Command("learn"))
async def cmd_learn(msg: types.Message):
    await msg.answer(
        "🎓 <b>Навчальний розділ</b>\n\nОберіть тему для вивчення:",
        reply_markup=kb_learn()
    )

# ── Navigation callbacks ──────────────────────────────────────────────────────

@dp.callback_query(F.data == "menu_main")
async def cb_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("🏠 <b>Головне меню</b>", reply_markup=kb_main())

@dp.callback_query(F.data == "menu_analyze")
async def cb_analyze(cb: CallbackQuery):
    await cb.message.edit_text("📊 <b>Оберіть пару для аналізу:</b>", reply_markup=kb_pairs("forex"))

@dp.callback_query(F.data == "menu_senior")
async def cb_senior(cb: CallbackQuery):
    await cb.message.edit_text(
        "📈 <b>Аналіз на старших таймфреймах</b>\n\n"
        "Спочатку оберіть пару:",
        reply_markup=kb_pairs("forex")
    )

@dp.callback_query(F.data.startswith("cat_"))
async def cb_cat(cb: CallbackQuery):
    cat = cb.data[4:]
    await cb.message.edit_text("📊 <b>Оберіть пару:</b>", reply_markup=kb_pairs(cat))

@dp.callback_query(F.data.startswith("pair_"))
async def cb_pair(cb: CallbackQuery):
    sym = cb.data[5:]
    await cb.message.edit_text(
        f"⏱ <b>Оберіть таймфрейм для {sym}:</b>\n\n"
        f"💡 <i>Старші ТФ (H4/D1/W1) — для контексту\n"
        f"H1/M30 — для торгівлі</i>",
        reply_markup=kb_timeframes(sym)
    )

@dp.callback_query(F.data.startswith("tf_"))
async def cb_tf(cb: CallbackQuery):
    parts = cb.data.split("_")
    tf  = parts[-1]
    sym = "_".join(parts[1:-1])
    await _do_analysis(cb.message, sym, tf)

@dp.callback_query(F.data.startswith("refresh_"))
async def cb_refresh(cb: CallbackQuery):
    parts = cb.data.split("_")
    tf  = parts[-1]
    sym = "_".join(parts[1:-1])
    await _do_analysis(cb.message, sym, tf)

# ── Scan ──────────────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "menu_scan")
async def cb_scan_menu(cb: CallbackQuery):
    await cb.message.edit_text(
        "🔍 <b>Авто-скан ринку v4</b>\n\n"
        "Аналіз: SMC · MTF · Liquidity · Divergence · Volume Profile\n\n"
        "Оберіть категорію:",
        reply_markup=kb_scan()
    )

@dp.callback_query(F.data.startswith("scan_"))
async def cb_scan(cb: CallbackQuery):
    cat   = cb.data[5:]
    pairs = SCAN_PAIRS.get(cat, SCAN_PAIRS["forex"])
    await cb.message.edit_text(
        f"🔍 <b>Сканую {len(pairs)} пар на H1...</b>\n\n"
        f"⏳ Зачекайте 20–60 секунд...\n\n"
        f"{'⬛'*5}{'⬜'*5}"
    )
    try:
        results = await analyzer.scan_market(pairs)
        text    = format_scan_result(results)
        b = InlineKeyboardBuilder()
        for r in results[:4]:
            if r.get("signal") in ("BUY","SELL"):
                icon = "🟢" if r["signal"]=="BUY" else "🔴"
                b.button(text=f"{icon} {r['symbol']}", callback_data=f"pair_{r['symbol']}")
        b.button(text="🔄 Повторити", callback_data=f"scan_{cat}")
        b.button(text="🏠 Меню",      callback_data="menu_main")
        b.adjust(2,2,1,1)
        await cb.message.edit_text(text, reply_markup=b.as_markup())
    except Exception as e:
        logger.error(f"scan error: {e}")
        await cb.message.edit_text(
            f"❌ Помилка сканування: <code>{str(e)[:200]}</code>",
            reply_markup=kb_scan()
        )

# ── Journal ───────────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "menu_journal")
async def cb_journal(cb: CallbackQuery):
    stats = get_stats()
    text = (f"📓 <b>Торговий журнал</b>\n\n"
            f"📊 Угод: {stats['total']} | 🟢 {stats['wins']} | 🔴 {stats['losses']}\n"
            f"💰 P&L: {'+'if stats['total_pnl']>=0 else ''}{stats['total_pnl']}$\n"
            f"🎯 Win Rate: {stats['win_rate']}%")
    await cb.message.edit_text(text, reply_markup=kb_journal())

@dp.callback_query(F.data == "journal_stats")
async def cb_journal_stats(cb: CallbackQuery):
    stats = get_stats()
    text  = format_stats(stats)
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Журнал", callback_data="menu_journal")
    b.button(text="🏠 Меню",   callback_data="menu_main")
    b.adjust(2)
    await cb.message.edit_text(text, reply_markup=b.as_markup())

@dp.callback_query(F.data == "journal_open")
async def cb_journal_open(cb: CallbackQuery):
    trades = get_open_trades()
    if not trades:
        b = InlineKeyboardBuilder()
        b.button(text="◀️ Журнал", callback_data="menu_journal")
        await cb.message.edit_text(
            "📋 <b>Відкриті угоди</b>\n\nНемає відкритих угод.",
            reply_markup=b.as_markup()
        )
        return
    lines = [f"📋 <b>Відкриті угоди ({len(trades)}):</b>\n"]
    for t in trades:
        icon = "🟢" if t.get("direction")=="BUY" else "🔴"
        lines.append(
            f"{icon} <b>{t.get('symbol','?')}</b> {t.get('direction','?')}\n"
            f"   Вхід: {_pf(t.get('entry_price',0), t.get('symbol',''))}\n"
            f"   SL: {_pf(t.get('sl',0), t.get('symbol',''))} | TP: {_pf(t.get('tp1',0), t.get('symbol',''))}\n"
            f"   ID: #{t['id']}"
        )
    await cb.message.edit_text(
        "\n".join(lines),
        reply_markup=kb_open_trades(trades)
    )

@dp.callback_query(F.data == "journal_history")
async def cb_journal_history(cb: CallbackQuery):
    trades = [t for t in get_all_trades() if t.get("status")=="closed"][-10:]
    if not trades:
        b = InlineKeyboardBuilder()
        b.button(text="◀️ Журнал", callback_data="menu_journal")
        await cb.message.edit_text("📜 Ще немає закритих угод.", reply_markup=b.as_markup())
        return
    lines = ["📜 <b>Остання 10 угод:</b>\n"]
    for t in reversed(trades):
        r = t.get("result_usd", 0); won = r > 0
        icon = "✅" if won else "❌"
        lines.append(
            f"{icon} {t.get('symbol','?')} {t.get('direction','?')} "
            f"{'+'if won else ''}{r:.2f}$ | RR 1:{abs(t.get('result_rr',0)):.1f}"
        )
    b = InlineKeyboardBuilder()
    b.button(text="◀️ Журнал", callback_data="menu_journal")
    b.button(text="🏠 Меню",   callback_data="menu_main")
    b.adjust(2)
    await cb.message.edit_text("\n".join(lines), reply_markup=b.as_markup())

@dp.callback_query(F.data == "journal_add")
async def cb_journal_add(cb: CallbackQuery):
    await cb.message.edit_text(
        "📝 <b>Записати нову угоду</b>\n\n"
        "Оберіть пару для якої хочете записати угоду:",
        reply_markup=kb_pairs("forex")
    )

# Записати угоду після аналізу
@dp.callback_query(F.data.startswith("log_trade_"))
async def cb_log_trade(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("_")
    tf  = parts[-1]; sym = "_".join(parts[2:-1])
    await state.update_data(symbol=sym, tf=tf)

    # Запустити аналіз щоб отримати дані
    try:
        r = await analyzer.analyze(sym, tf, "all")
        entry_data = r.get("entry", {})
        entry_price= entry_data.get("entry", r["price"])

        # Зберегти дані угоди
        trade = {
            "symbol":      sym,
            "timeframe":   tf,
            "direction":   r["direction"],
            "entry_price": entry_price,
            "sl":          entry_data.get("sl"),
            "tp1":         entry_data.get("tp1"),
            "tp2":         entry_data.get("tp2"),
            "rr_planned":  entry_data.get("rr1", 0),
            "confidence":  r["confidence"],
            "probability": r["probability"]["probability"],
            "grade":       r["probability"]["grade"],
            "analysis":    {
                "trend":     r["trend"],
                "smc":       r["smc"],
                "liquidity": r["liquidity"],
                "divergence":r["divergence"],
                "patterns":  r["candle_patterns"],
                "probability":r["probability"],
                "mtf":       r["mtf"],
            }
        }
        trade_saved = add_trade(trade)
        await state.update_data(trade_id=trade_saved["id"])

        pf = lambda p: _pf(p, sym)
        d_icon = "🟢" if r["direction"]=="BUY" else "🔴"
        text = (
            f"✅ <b>Угоду записано!</b>\n\n"
            f"{d_icon} <b>{sym} {r['direction']}</b>\n"
            f"📍 Вхід: <code>{pf(entry_price)}</code>\n"
            f"🛑 SL: <code>{pf(entry_data.get('sl'))}</code>\n"
            f"🎯 TP1: <code>{pf(entry_data.get('tp1'))}</code>\n"
            f"⚖️ RR план: 1:{entry_data.get('rr1',0):.1f}\n"
            f"🏆 Grade: {r['probability']['grade']}\n\n"
            f"ID угоди: <code>#{trade_saved['id']}</code>\n\n"
            f"Коли закриєте угоду — натисніть «Закрити» щоб отримати авто-аналіз."
        )
        b = InlineKeyboardBuilder()
        b.button(text=f"🚪 Закрити #{trade_saved['id']}", callback_data=f"close_trade_{trade_saved['id']}")
        b.button(text="📓 Журнал",  callback_data="menu_journal")
        b.button(text="🏠 Меню",    callback_data="menu_main")
        b.adjust(1,2)
        await cb.message.edit_text(text, reply_markup=b.as_markup())

    except Exception as e:
        await cb.message.edit_text(
            f"❌ Помилка при записі: <code>{str(e)[:200]}</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_journal")]
            ])
        )

# Закрити угоду
@dp.callback_query(F.data.startswith("close_trade_"))
async def cb_close_trade(cb: CallbackQuery, state: FSMContext):
    trade_id = int(cb.data.split("_")[-1])
    await state.update_data(closing_trade_id=trade_id)
    await state.set_state(TradeStates.waiting_close_price)
    await cb.message.edit_text(
        f"🚪 <b>Закриття угоди #{trade_id}</b>\n\n"
        f"Введіть ціну закриття угоди:\n"
        f"<i>(наприклад: 1.09450)</i>"
    )

@dp.message(StateFilter(TradeStates.waiting_close_price))
async def msg_close_price(msg: types.Message, state: FSMContext):
    try:
        price = float(msg.text.strip().replace(",","."))
        await state.update_data(close_price=price)
        await state.set_state(TradeStates.waiting_result_usd)
        await msg.answer(
            f"💰 Введіть результат угоди в доларах:\n"
            f"<i>Наприклад: +1.50 або -0.80</i>"
        )
    except ValueError:
        await msg.answer("❌ Неправильний формат. Введіть число, наприклад: 1.09450")

@dp.message(StateFilter(TradeStates.waiting_result_usd))
async def msg_result_usd(msg: types.Message, state: FSMContext):
    try:
        result = float(msg.text.strip().replace(",",".").replace("+",""))
        data   = await state.get_data()
        trade_id    = data.get("closing_trade_id")
        close_price = data.get("close_price", 0)

        closed = close_trade(trade_id, close_price, result)
        await state.clear()

        if not closed:
            await msg.answer("❌ Угоду не знайдено.", reply_markup=kb_main())
            return

        # Генеруємо повний авто-аналіз
        analysis = closed.get("analysis", {})

        # Додаємо помилки в аналіз для звіту
        mistakes = []
        trend = analysis.get("trend",{})
        d     = closed.get("direction","BUY")
        if trend.get("direction") != ("bullish" if d=="BUY" else "bearish"):
            mistakes.append("Торгівля проти тренду")
        if not analysis.get("patterns"):
            mistakes.append("Відсутній паттерн підтвердження")
        if analysis.get("probability",{}).get("probability",0) < 40:
            mistakes.append("Probability Score < 40%")
        if analysis.get("mtf",{}).get("score",0) < 65:
            mistakes.append("MTF confluence не підтримував напрямок")
        closed["mistakes"] = mistakes

        report = format_trade_report(closed, analysis)

        b = InlineKeyboardBuilder()
        b.button(text="📊 Статистика", callback_data="journal_stats")
        b.button(text="📓 Журнал",     callback_data="menu_journal")
        b.button(text="🏠 Меню",       callback_data="menu_main")
        b.adjust(2,1)
        await msg.answer(report, reply_markup=b.as_markup())

    except ValueError:
        await msg.answer("❌ Неправильний формат. Введіть суму, наприклад: 1.50 або -0.80")

# ── Education ─────────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "menu_learn")
async def cb_learn(cb: CallbackQuery):
    await cb.message.edit_text(
        "🎓 <b>Навчальний розділ TradeBot v4</b>\n\n"
        "Тут ви знайдете пояснення всіх технік трейдингу:\n"
        "паттерни, стратегії, концепції, психологія.\n\n"
        "Кожна тема — з поясненням, прикладами та ілюстраціями.\n\n"
        "Оберіть категорію:",
        reply_markup=kb_learn()
    )

@dp.callback_query(F.data.startswith("learn_cat_"))
async def cb_learn_cat(cb: CallbackQuery):
    cat = cb.data[10:]
    topics = get_category_menu(cat)
    from education import LESSONS
    title = LESSONS.get(cat,{}).get("title","—")
    await cb.message.edit_text(
        f"🎓 <b>{title}</b>\n\nОберіть тему:",
        reply_markup=kb_learn_cat(cat)
    )

@dp.callback_query(F.data.startswith("learn_topic_"))
async def cb_learn_topic(cb: CallbackQuery):
    key    = cb.data[12:]
    lesson = get_lesson(key)
    if not lesson:
        await cb.answer("Урок не знайдено", show_alert=True)
        return

    title   = lesson.get("title","")
    text    = lesson.get("text","")
    example = lesson.get("example","")
    img_q   = lesson.get("image_query","")

    full_text = f"🎓 <b>{title}</b>\n{text}"
    if example:
        full_text += f"\n{example}"

    # Знаходимо категорію для кнопки "Назад"
    cat_key = ""
    from education import LESSONS
    for k, v in LESSONS.items():
        if any(t[0]==key for t in v.get("topics",[])):
            cat_key = k; break

    kb = kb_learn_topic(key, cat_key)

    # Якщо є image_query — шукаємо зображення через Unsplash
    if img_q:
        photo_url = f"https://source.unsplash.com/800x500/?{img_q.replace(' ',',')}"
        try:
            await cb.message.delete()
            await cb.message.answer_photo(
                photo=photo_url,
                caption=full_text[:1024],
                reply_markup=kb
            )
            # Якщо текст довший — надсилаємо решту
            if len(full_text) > 1024:
                await cb.message.answer(full_text[1024:], reply_markup=kb)
            return
        except Exception as e:
            logger.warning(f"Photo failed: {e}")

    # Fallback без фото
    await cb.message.edit_text(full_text[:4000], reply_markup=kb)

# ── Webapp ────────────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "menu_webapp")
async def cb_webapp(cb: CallbackQuery):
    if WEBAPP_URL and WEBAPP_URL != "https://your-domain.com":
        b = InlineKeyboardBuilder()
        b.button(text="📱 Відкрити Mini App", web_app=WebAppInfo(url=WEBAPP_URL))
        b.button(text="🏠 Меню", callback_data="menu_main")
        b.adjust(1)
        await cb.message.edit_text(
            "📱 <b>Trading Mini App</b>\n\n"
            "Реальні графіки · Аналіз · Калькулятор · Журнал\n\n"
            "Натисніть кнопку 👇",
            reply_markup=b.as_markup()
        )
    else:
        await cb.message.edit_text(
            "📱 <b>Mini App — Налаштування</b>\n\n"
            "1️⃣ Задеплойте <code>webapp/index.html</code> на GitHub Pages або Netlify\n"
            "2️⃣ Вставте URL у <code>config.py</code>: <code>WEBAPP_URL = \"https://...\"</code>\n"
            "3️⃣ Перезапустіть бота",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Меню", callback_data="menu_main")]
            ])
        )

@dp.callback_query(F.data == "menu_help")
async def cb_help(cb: CallbackQuery):
    await cb.message.edit_text(HELP_MSG, reply_markup=kb_main())

@dp.message()
async def handle_text(msg: types.Message, state: FSMContext):
    cur = await state.get_state()
    if cur: return  # FSM обробляє
    await msg.answer(
        "Використовуйте кнопки меню 👇\n/start — головне меню",
        reply_markup=kb_main()
    )

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    logger.info("Starting TradeBot v4...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
