"""Форматування повідомлень"""
from datetime import datetime

WELCOME_MSG = """👋 Вітаю, <b>{name}</b>!

🤖 <b>TradeBot — AI аналіз ринків</b>

📊 Forex · Крипто · Індекси · Товари
⚡ 5 стратегій Price Action + EMA
🎯 Auto SL/TP · RSI · MACD · Bollinger
📱 Mini App з графіками всередині Telegram

<i>⚠️ Тільки для навчання. Не фінансова порада.</i>"""

HELP_MSG = """❓ <b>Довідка</b>

🟢 <b>BUY</b> — сигнал на купівлю (лонг)
🔴 <b>SELL</b> — сигнал на продаж (шорт)
⚪ <b>NEUTRAL</b> — немає сигналу

<b>Сила сигналу:</b>
80–100% ✅✅ Дуже сильний
60–79%  ✅  Сильний
40–59%  ⚠️  Помірний
0–39%   ❌  Слабкий

<b>Команди:</b>
/start — меню  /scan — скан  /help — довідка"""

LOADING_MSG = "📡 Завантажую дані...\n📊 Рахую індикатори...\n🔍 Шукаю паттерни..."

TREND_NAMES = {"bullish":"📈 Висхідний","bearish":"📉 Низхідний","sideways":"➡️ Флет"}
STRENGTH_NAMES = {"strong":"Сильний","moderate":"Помірний","weak":"Слабкий"}
STRUCTURE_NAMES = {"uptrend":"📈 HH+HL (зростання)","downtrend":"📉 LH+LL (падіння)","ranging":"➡️ Діапазон"}
PATTERN_NAMES = {
    "bullish_pinbar":"Бичачий пін-бар 📍","bearish_pinbar":"Ведмежий пін-бар 📍",
    "bullish_engulfing":"Бичаче поглинання 🟢","bearish_engulfing":"Ведмеже поглинання 🔴",
    "doji":"Доджі ➕","inside_bar":"Inside Bar 📦",
    "morning_star":"Ранкова зірка ⭐","evening_star":"Вечірня зірка ⭐",
    "hammer":"Молот 🔨","shooting_star":"Падаюча зірка 💫",
}

def _pf(price, symbol=""):
    if price == 0: return "N/A"
    if "BTC" in symbol or price > 1000: return f"{price:,.2f}"
    if price > 10: return f"{price:.4f}"
    return f"{price:.5f}"

def _bar(val, total=100, width=10):
    filled = int(val / total * width)
    return "█"*filled + "░"*(width-filled)

def _sig_icon(direction, confidence):
    if direction == "BUY":   return "🟢" if confidence >= 60 else "🟡"
    if direction == "SELL":  return "🔴" if confidence >= 60 else "🟠"
    return "⚪"

def format_signal(r: dict, symbol: str, tf: str) -> str:
    d, conf = r["direction"], r["confidence"]
    price, sl, tp1, tp2, rr = r["price"], r["sl"], r["tp1"], r["tp2"], r["rr"]
    pf = lambda p: _pf(p, symbol)

    if d == "BUY" and conf >= 60:     rec = "✅ <b>РЕКОМЕНДАЦІЯ: КУПИТИ (LONG)</b>"
    elif d == "SELL" and conf >= 60:  rec = "✅ <b>РЕКОМЕНДАЦІЯ: ПРОДАТИ (SHORT)</b>"
    elif d != "NEUTRAL" and conf>=40: rec = f"⚠️ <b>СЛАБКИЙ {'BUY' if d=='BUY' else 'SELL'} — чекайте підтвердження</b>"
    else:                             rec = "⚪ <b>НЕМАЄ СИГНАЛУ — поза ринком</b>"

    pats = [PATTERN_NAMES.get(p,p) for p in r.get("candle_patterns",[])]
    pats_text = f"\n🕯 <b>Паттерни:</b> {', '.join(pats)}" if pats else ""

    strat_lines = []
    for s in sorted(r["all_strategies"].values(), key=lambda x:-x["score"]):
        icon = "🟢" if s["direction"]=="BUY" else ("🔴" if s["direction"]=="SELL" else "⚪")
        strat_lines.append(f"  {icon} {s['name']}: {_bar(s['score'])} {s['score']}%")

    warnings = []
    if conf < 40: warnings.append("⚠️ Слабкий сигнал — краще пропустити")
    if rr < 1.5:  warnings.append("⚠️ RR нижче 1:2 — невигідно")
    if r["ctx_trend"]["direction"] not in (r["trend"]["direction"],"sideways") and d!="NEUTRAL":
        warnings.append("⚠️ Старший ТФ суперечить — підвищений ризик")
    rsi = r["rsi"]
    if rsi > 70 and d=="BUY":  warnings.append("⚠️ RSI перекуплений (>70)")
    if rsi < 30 and d=="SELL": warnings.append("⚠️ RSI перепроданий (<30)")

    rsi_icon = "🔴" if rsi>70 else ("🟢" if rsi<30 else "🟡")
    macd_icon = "🟢" if r.get("macd_hist",0)>0 else "🔴"
    ns = _pf(r["levels"]["nearest_support"]) if r["levels"]["nearest_support"] else "N/A"
    nr = _pf(r["levels"]["nearest_resistance"]) if r["levels"]["nearest_resistance"] else "N/A"

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
        f"🎯 <b>TP2:</b> <code>{pf(tp2)}</code>  (RR 1:3.0)\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>КОНТЕКСТ</b>\n\n"
        f"📈 <b>Тренд ({tf.upper()}):</b> {TREND_NAMES.get(r['trend']['direction'],'')} {STRENGTH_NAMES.get(r['trend']['strength'],'')}\n"
        f"🗺 <b>Тренд ({r['context_tf'].upper()}):</b> {TREND_NAMES.get(r['ctx_trend']['direction'],'')}\n"
        f"🏗 <b>Структура:</b> {STRUCTURE_NAMES.get(r['structure']['structure'],'')}\n"
        f"{rsi_icon} <b>RSI {rsi:.0f}:</b> {'Перекуплено' if rsi>70 else ('Перепродано' if rsi<30 else 'Нейтрально')}\n"
        f"{macd_icon} <b>MACD:</b> {'Бичачий' if r.get('macd_hist',0)>0 else 'Ведмежий'}\n"
        f"📐 Опір: <code>{nr}</code>  Підтримка: <code>{ns}</code>"
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
        msg += f"\n📋 <b>Сигнали стратегії:</b>\n" + "\n".join(top_signals) + "\n"

    msg += (
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {r['timestamp'].strftime('%H:%M:%S')} UTC\n"
        f"<i>⚠️ Не є фінансовою порадою</i>"
    )
    return msg

def format_scan_result(results: list) -> str:
    if not results: return "❌ Немає результатів"
    buys  = [r for r in results if r["signal"]=="BUY"]
    sells = [r for r in results if r["signal"]=="SELL"]
    neutral=[r for r in results if r["signal"] not in ("BUY","SELL","ERROR")]
    errors= [r for r in results if r["signal"]=="ERROR"]

    lines = ["🔍 <b>АВТО-СКАН РИНКУ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"]

    for title, grp, emoji in [("КУПИТИ (BUY/LONG)", buys, "🟢"), ("ПРОДАТИ (SELL/SHORT)", sells, "🔴")]:
        if grp:
            lines.append(f"{emoji} <b>{title}</b>")
            for r in grp:
                pats = ", ".join(r.get("patterns",[])[:2]) or "—"
                lines.append(
                    f"  📊 <b>{r['symbol']}</b>  {_bar(r['confidence'],100,5)} {r['confidence']}%\n"
                    f"     {r['best_strategy']} | RSI {r['rsi']} | RR 1:{r['rr']}\n"
                    f"     Паттерни: {pats}"
                )
            lines.append("")

    if neutral:
        lines.append(f"⚪ <b>Нейтральні:</b> {', '.join(r['symbol'] for r in neutral)}")
    if errors:
        lines.append(f"❌ <b>Помилка даних:</b> {', '.join(r['symbol'] for r in errors)}")

    lines += [
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 Всього: {len(results)} | 🟢 {len(buys)} | 🔴 {len(sells)}",
        f"⏰ {datetime.now().strftime('%H:%M:%S')} UTC",
        "<i>⚠️ Використовуйте Risk Management!</i>",
    ]
    return "\n".join(lines)
