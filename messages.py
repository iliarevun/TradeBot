"""Форматування повідомлень — v3 з ADX, Stoch RSI, VWAP, сесія"""
from datetime import datetime

WELCOME_MSG = """👋 Вітаю, <b>{name}</b>!

🤖 <b>TradeBot v3 — AI аналіз ринків</b>

📊 Forex · Крипто · Індекси · Товари
⚡ 5 стратегій Price Action + EMA + ADX
🎯 Auto SL/TP · RSI · MACD · Stoch · VWAP
📱 Mini App з графіками всередині Telegram

<i>⚠️ Тільки для навчання. Не фінансова порада.</i>"""

HELP_MSG = """❓ <b>Довідка TradeBot v3</b>

🟢 <b>BUY</b> — сигнал на купівлю (лонг)
🔴 <b>SELL</b> — сигнал на продаж (шорт)
⚪ <b>NEUTRAL</b> — немає сигналу

<b>Сила сигналу (confidence):</b>
80–100% ✅✅ Дуже сильний
60–79%  ✅  Сильний
40–59%  ⚠️  Помірний
0–39%   ❌  Слабкий (не торгувати)

<b>Нові індикатори v3:</b>
• ADX — сила тренду (>25 = сильний тренд)
• Stochastic RSI — перекупленість/перепроданість
• VWAP — середньозважена ціна за обсягом
• 14 свічкових паттернів (було 10)

<b>Команди:</b>
/start — меню  /scan — скан  /help — довідка"""

LOADING_MSG = "📡 Завантажую дані...\n📊 Рахую ADX · RSI · MACD · Stoch...\n🔍 Шукаю 14 паттернів...\n📐 Визначаю рівні та Fibonacci..."

SESSION_NAMES = {
    "asia":         "🌏 Азіатська сесія",
    "london":       "🇬🇧 Лондонська сесія",
    "new_york":     "🗽 Нью-Йоркська сесія",
    "overlap_close":"🔁 Закриття перетину",
    "off_hours":    "😴 Поза сесіями",
}
TREND_NAMES    = {"bullish":"📈 Висхідний","bearish":"📉 Низхідний","sideways":"➡️ Флет"}
STRENGTH_NAMES = {"strong":"Сильний","moderate":"Помірний","weak":"Слабкий"}
STRUCTURE_NAMES= {"uptrend":"📈 HH+HL","downtrend":"📉 LH+LL","ranging":"➡️ Діапазон"}
PATTERN_NAMES  = {
    "bullish_pinbar":"Бичачий пін-бар 📍","bearish_pinbar":"Ведмежий пін-бар 📍",
    "bullish_engulfing":"Бичаче поглинання 🟢","bearish_engulfing":"Ведмеже поглинання 🔴",
    "doji":"Доджі ➕","inside_bar":"Inside Bar 📦",
    "morning_star":"Ранкова зірка ⭐","evening_star":"Вечірня зірка ⭐",
    "hammer":"Молот 🔨","shooting_star":"Падаюча зірка 💫",
    "three_white":"3 білих солдати 🟢","three_black":"3 чорних ворони 🔴",
    "tweezer_bottom":"Пінцет знизу 🔧","tweezer_top":"Пінцет зверху 🔧",
}

def _pf(price, symbol=""):
    if not price or price == 0: return "N/A"
    try:
        p = float(price)
        if "BTC" in symbol or p > 1000: return f"{p:,.2f}"
        if p > 10: return f"{p:.4f}"
        return f"{p:.5f}"
    except Exception:
        return "N/A"

def _bar(val, total=100, width=10):
    try:
        filled = max(0, min(int(float(val) / total * width), width))
        return "█" * filled + "░" * (width - filled)
    except Exception:
        return "░" * width

def _sig_icon(direction, confidence):
    if direction == "BUY":  return "🟢" if confidence >= 60 else "🟡"
    if direction == "SELL": return "🔴" if confidence >= 60 else "🟠"
    return "⚪"

def format_signal(r: dict, symbol: str, tf: str) -> str:
    d, conf = r["direction"], r["confidence"]
    price, sl, tp1, tp2, rr = r["price"], r["sl"], r["tp1"], r["tp2"], r["rr"]
    pf = lambda p: _pf(p, symbol)

    if d == "BUY"  and conf >= 60: rec = "✅ <b>РЕКОМЕНДАЦІЯ: КУПИТИ (LONG)</b>"
    elif d == "SELL" and conf >= 60: rec = "✅ <b>РЕКОМЕНДАЦІЯ: ПРОДАТИ (SHORT)</b>"
    elif d != "NEUTRAL" and conf >= 40: rec = f"⚠️ <b>СЛАБКИЙ {'BUY' if d=='BUY' else 'SELL'} — чекайте підтвердження</b>"
    else: rec = "⚪ <b>НЕМАЄ СИГНАЛУ — залишайтесь поза ринком</b>"

    pats = [PATTERN_NAMES.get(p, p) for p in r.get("candle_patterns", [])]
    pats_text = f"\n🕯 <b>Паттерни:</b> {', '.join(pats)}" if pats else "\n🕯 <b>Паттерни:</b> не виявлено"

    strat_lines = []
    for s in sorted(r["all_strategies"].values(), key=lambda x: -x["score"]):
        icon = "🟢" if s["direction"]=="BUY" else ("🔴" if s["direction"]=="SELL" else "⚪")
        strat_lines.append(f"  {icon} {s['name']}: {_bar(s['score'])} {s['score']}%")

    warnings = []
    if conf < 40:   warnings.append("❌ Сигнал слабкий — угоду пропустити")
    if rr < 1.5:    warnings.append("⚠️ RR нижче 1:2 — невигідне співвідношення")
    ctx = r.get("ctx_trend", {})
    tr  = r.get("trend", {})
    if ctx.get("direction") not in (tr.get("direction"), "sideways") and d != "NEUTRAL":
        warnings.append("⚠️ Старший ТФ суперечить — ризик підвищений")
    rsi = r.get("rsi", 50)
    if rsi > 70 and d == "BUY":  warnings.append("⚠️ RSI перекуплений (>70) — обережно з лонгом")
    if rsi < 30 and d == "SELL": warnings.append("⚠️ RSI перепроданий (<30) — обережно з шортом")
    if r.get("session") == "off_hours":
        warnings.append("⚠️ Поза торговими сесіями — волатильність низька")

    rsi_icon   = "🔴" if rsi > 70 else ("🟢" if rsi < 30 else "🟡")
    macd_bull  = r.get("macd_hist", 0) > 0
    adx_d      = r.get("adx", {})
    adx_val    = adx_d.get("adx", 0)
    adx_strong = adx_val >= 25
    stoch      = r.get("stoch_rsi", 50)
    stoch_icon = "🔴" if stoch > 80 else ("🟢" if stoch < 20 else "🟡")
    vwap       = r.get("vwap")
    vwap_text  = f"<code>{pf(vwap)}</code>" if vwap else "N/A"
    ns = pf(r["levels"].get("nearest_support"))  if r["levels"].get("nearest_support")  else "N/A"
    nr = pf(r["levels"].get("nearest_resistance")) if r["levels"].get("nearest_resistance") else "N/A"

    # Fibonacci
    fib = r["levels"].get("fib_levels", {})
    fib_text = ""
    if fib:
        fib_lines = "  ".join(f"{k}: <code>{pf(v)}</code>" for k, v in list(fib.items())[:3])
        fib_text = f"\n📐 <b>Fibonacci:</b> {fib_lines}"

    session_name = SESSION_NAMES.get(r.get("session", ""), "—")

    msg = (
        f"{_sig_icon(d,conf)} <b>АНАЛІЗ: {symbol} | {tf.upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{rec}\n\n"
        f"💪 <b>Сила сигналу:</b>\n"
        f"|{_bar(conf)}| {conf}%\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>РІВНІ ТОРГІВЛІ</b>\n\n"
        f"📍 <b>Ціна:</b> <code>{pf(price)}</code>\n"
        f"🛑 <b>Stop Loss:</b> <code>{pf(sl)}</code>\n"
        f"🎯 <b>TP1:</b> <code>{pf(tp1)}</code>  (RR 1:{rr:.1f})\n"
        f"🎯 <b>TP2:</b> <code>{pf(tp2)}</code>  (RR 1:3.0)\n"
        f"🔴 <b>Опір:</b> <code>{nr}</code>  🟢 <b>Підтримка:</b> <code>{ns}</code>"
        f"{fib_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>ІНДИКАТОРИ</b>\n\n"
        f"📈 <b>Тренд ({tf.upper()}):</b> {TREND_NAMES.get(tr.get('direction',''),'—')} {STRENGTH_NAMES.get(tr.get('strength',''),'')}\n"
        f"🗺 <b>Тренд ({r.get('context_tf','').upper()}):</b> {TREND_NAMES.get(ctx.get('direction',''),'—')}\n"
        f"🏗 <b>Структура:</b> {STRUCTURE_NAMES.get(r.get('structure',{}).get('structure',''),'—')}\n"
        f"📊 <b>ADX:</b> {adx_val:.0f} — {'✅ Сильний тренд' if adx_strong else '➡️ Слабкий / флет'}\n"
        f"{rsi_icon} <b>RSI ({rsi:.0f}):</b> {'Перекуплено' if rsi>70 else ('Перепродано' if rsi<30 else 'Нейтрально')}\n"
        f"{stoch_icon} <b>Stoch RSI ({stoch:.0f}):</b> {'Перекуплено' if stoch>80 else ('Перепродано' if stoch<20 else 'Нейтрально')}\n"
        f"{'🟢' if macd_bull else '🔴'} <b>MACD:</b> {'Бичачий ↑' if macd_bull else 'Ведмежий ↓'}\n"
        f"📊 <b>VWAP:</b> {vwap_text}\n"
        f"🕐 <b>Сесія:</b> {session_name}"
        f"{pats_text}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 <b>СТРАТЕГІЇ</b>\n\n"
        f"{chr(10).join(strat_lines)}\n\n"
        f"🥇 <b>Краща:</b> {r['best_strategy']['name']} ({r['best_strategy']['score']}%)\n"
    )

    if warnings:
        msg += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        msg += "\n".join(warnings) + "\n"

    top_signals = r["best_strategy"].get("signals", [])[:4]
    if top_signals:
        msg += "\n📋 <b>Сигнали стратегії:</b>\n" + "\n".join(top_signals) + "\n"

    msg += (
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {r['timestamp'].strftime('%H:%M:%S')} UTC\n"
        f"<i>⚠️ Не є фінансовою порадою</i>"
    )
    return msg

def format_scan_result(results: list) -> str:
    if not results: return "❌ Немає результатів"
    buys    = [r for r in results if r["signal"] == "BUY"]
    sells   = [r for r in results if r["signal"] == "SELL"]
    neutral = [r for r in results if r["signal"] == "NEUTRAL"]
    errors  = [r for r in results if r["signal"] == "ERROR"]

    lines = ["🔍 <b>АВТО-СКАН РИНКУ v3</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"]

    for title, grp, emoji in [("КУПИТИ (BUY/LONG)", buys, "🟢"), ("ПРОДАТИ (SELL/SHORT)", sells, "🔴")]:
        if grp:
            lines.append(f"{emoji} <b>{title}</b>")
            for r in grp:
                pats = ", ".join(PATTERN_NAMES.get(p,p) for p in r.get("patterns",[])[:2]) or "—"
                adx  = r.get("adx", 0)
                lines.append(
                    f"  📊 <b>{r['symbol']}</b>  {_bar(r['confidence'],100,5)} {r['confidence']}%\n"
                    f"     {r['best_strategy']} | RSI {r['rsi']} | ADX {adx:.0f} | RR 1:{r['rr']}\n"
                    f"     Паттерни: {pats}"
                )
            lines.append("")

    if neutral:
        lines.append(f"⚪ <b>Нейтральні:</b> {', '.join(r['symbol'] for r in neutral)}")
    if errors:
        lines.append(f"❌ <b>Помилка:</b> {', '.join(r['symbol'] for r in errors)}")

    lines += [
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 Всього: {len(results)} | 🟢 {len(buys)} | 🔴 {len(sells)}",
        f"⏰ {datetime.now().strftime('%H:%M:%S')} UTC",
        "<i>⚠️ Використовуйте Risk Management!</i>",
    ]
    return "\n".join(lines)
