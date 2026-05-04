"""messages.py v4 — повний формат з SMC, MTF, Entry Zone, Probability"""
from datetime import datetime

WELCOME_MSG = """👋 Вітаю, <b>{name}</b>!

🤖 <b>TradeBot v4 — Professional Trading AI</b>

📊 Forex · Крипто · Індекси · Товари
⚡ Smart Money Concepts · MTF Confluence
🎯 Optimal Entry Zone · Probability Score
📓 Торговий журнал з авто-аналізом
🎓 Навчальний розділ з поясненнями
📱 Mini App з реальними графіками

<i>⚠️ Тільки для навчання. Не фінансова порада.</i>"""

HELP_MSG = """❓ <b>Довідка TradeBot v4</b>

<b>Команди:</b>
/start — головне меню
/scan — авто-скан ринку
/journal — торговий журнал
/learn — навчальний розділ
/help — ця довідка

<b>Сигнал:</b>
🟢 BUY · 🔴 SELL · ⚪ NEUTRAL

<b>Оцінка (Probability Grade):</b>
A+ ≥80% · A ≥65% · B ≥50% · C ≥35% · D — не торгувати

<b>Нові функції v4:</b>
• Smart Money Concepts (BOS/CHoCH)
• Liquidity Sweep Detection
• Volume Profile (POC/VAH/VAL)
• RSI+MACD Divergence
• Optimal Entry Zone (Market/Limit/Wait)
• Multi-Timeframe Confluence (3 ТФ)
• Автоматичний звіт після угоди
• Навчання на помилках"""

LOADING_MSG = (
    "📡 Завантажую 3 таймфрейми...\n"
    "📊 SMC · MTF · Volume Profile...\n"
    "🔍 Liquidity Sweeps · Divergence...\n"
    "🎯 Розраховую Optimal Entry Zone..."
)

SESS = {
    "London Open 🇬🇧 (найкращий час)":  "🟢",
    "NY Session 🗽 (відмінний час)":     "🟢",
    "London+NY Overlap 🔥 (пік)":        "🔥",
    "Азіатська сесія 🌏 (тихо)":         "🟡",
    "NY Afternoon (помірно)":             "🟡",
    "Міжсесійний час 😴 (уникати)":       "🔴",
}
TREND_N = {"bullish":"📈 Висхідний","bearish":"📉 Низхідний","sideways":"➡️ Флет","unknown":"❓"}
STR_N   = {"strong":"Сильний","moderate":"Помірний","weak":"Слабкий"}

PAT_N = {
    "bullish_pinbar":"Бичачий пін-бар 📍","bearish_pinbar":"Ведмежий пін-бар 📍",
    "bullish_engulfing":"Бичаче поглинання 🟢","bearish_engulfing":"Ведмеже поглинання 🔴",
    "doji":"Доджі ➕","inside_bar":"Inside Bar 📦",
    "morning_star":"Ранкова зірка ⭐","evening_star":"Вечірня зірка ⭐",
    "hammer":"Молот 🔨","shooting_star":"Падаюча зірка 💫",
    "three_white":"3 білих солдати 🟢🟢🟢","three_black":"3 чорних ворони 🔴🔴🔴",
    "tweezer_bottom":"Пінцет знизу 🔧","tweezer_top":"Пінцет зверху 🔧",
}

def _pf(p, sym=""):
    if not p or p == 0: return "N/A"
    try:
        v = float(p)
        if "BTC" in sym or v > 1000: return f"{v:,.2f}"
        if v > 10: return f"{v:.4f}"
        return f"{v:.5f}"
    except: return "N/A"

def _bar(v, w=10):
    f = max(0, min(int(float(v)/100*w), w))
    return "█"*f + "░"*(w-f)

def _sig(d, c):
    if d=="BUY":  return "🟢" if c>=60 else "🟡"
    if d=="SELL": return "🔴" if c>=60 else "🟠"
    return "⚪"

def format_signal(r: dict, symbol: str, tf: str) -> str:
    d    = r["direction"]; conf = r["confidence"]
    pr   = r["price"];     sym  = symbol
    pf   = lambda p: _pf(p, sym)
    en   = r.get("entry", {}); prob = r.get("probability", {})
    trend= r.get("trend",{}); ctx  = r.get("ctx_trend",{})
    ctx2 = r.get("ctx2_trend",{}); adx = r.get("adx",{})
    smc  = r.get("smc",{}); liq  = r.get("liquidity",{})
    div  = r.get("divergence",{}); of  = r.get("order_flow",{})
    mtf  = r.get("mtf",{}); vp   = r.get("vol_profile",{})
    sess = r.get("session",{}); pats= r.get("candle_patterns",[])
    lv   = r.get("levels",{}); rsi  = r.get("rsi",50)
    stk  = r.get("stoch_k",50); macd= r.get("macd_hist",0)
    wil  = r.get("williams_r",-50); cci = r.get("cci",0)

    if d=="BUY"  and conf>=60: rec="✅ <b>РЕКОМЕНДАЦІЯ: КУПИТИ (LONG)</b>"
    elif d=="SELL" and conf>=60: rec="✅ <b>РЕКОМЕНДАЦІЯ: ПРОДАТИ (SHORT)</b>"
    elif d!="NEUTRAL" and conf>=40: rec=f"⚠️ <b>СЛАБКИЙ {'BUY' if d=='BUY' else 'SELL'} — чекайте підтвердження</b>"
    else: rec="⚪ <b>НЕМАЄ СИГНАЛУ — залишайтесь поза ринком</b>"

    grade = prob.get("grade","—"); probability = prob.get("probability",0)
    grade_icon = "🏆" if probability>=80 else ("🥇" if probability>=65 else ("🥈" if probability>=50 else ("🥉" if probability>=35 else "❌")))

    # Entry
    entry_price  = en.get("entry", pr); entry_lbl = en.get("entry_label","—")
    entry_reason = en.get("entry_reason","—")
    sl=en.get("sl",pr); tp1=en.get("tp1",pr); tp2=en.get("tp2",pr); tp3=en.get("tp3",pr)
    rr1=en.get("rr1",0); rr2=en.get("rr2",0); sl_pips=en.get("sl_pips",0)

    # Patterns
    pats_text = ", ".join(PAT_N.get(p,p) for p in pats) if pats else "не виявлено"

    # Session
    sname = sess.get("name","—"); squal = sess.get("quality",0)
    sicon = SESS.get(sname,"🟡")

    # Factors top-5
    factors = prob.get("factors",[])[:5]
    fact_text = "\n".join(f"  {f[0]} {f[1]}" for f in factors) if factors else "  —"

    # Warnings
    warns = []
    if conf < 40:   warns.append("❌ Confidence < 40% — угоду пропустити")
    if rr1 < 1.5:   warns.append("⚠️ RR < 1:2 — невигідне співвідношення")
    if smc.get("choch"): warns.append("⚠️ CHoCH — можливий розворот тренду")
    if rsi>70 and d=="BUY":   warns.append("⚠️ RSI перекуплений (>70)")
    if rsi<30 and d=="SELL":  warns.append("⚠️ RSI перепроданий (<30)")
    if squal < 60:  warns.append(f"⚠️ Низька якість сесії ({squal}%) — менша волатильність")

    warn_text = "\n".join(warns) if warns else "✅ Критичних попереджень немає"

    ctx2_tf = r.get("context_tf","")

    msg = (
f"{_sig(d,conf)} <b>АНАЛІЗ v4: {symbol} | {tf.upper()}</b>\n"
f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
f"{rec}\n\n"
f"{grade_icon} <b>Probability Grade: {grade}</b>\n"
f"|{_bar(probability)}| {probability}%\n"
f"💪 Confidence: |{_bar(conf)}| {conf}%\n\n"
f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
f"🎯 <b>ОПТИМАЛЬНА ТОЧКА ВХОДУ</b>\n\n"
f"📍 <b>Поточна ціна:</b> <code>{pf(pr)}</code>\n"
f"⚡ <b>Тип входу:</b> {entry_lbl}\n"
f"💡 <b>Причина:</b> {entry_reason}\n\n"
f"🛑 <b>Stop Loss:</b>  <code>{pf(sl)}</code>  ({sl_pips:.1f} пп)\n"
f"🎯 <b>TP1:</b>  <code>{pf(tp1)}</code>  (RR 1:{rr1:.1f})\n"
f"🎯 <b>TP2:</b>  <code>{pf(tp2)}</code>  (RR 1:{rr2:.1f})\n"
f"🎯 <b>TP3:</b>  <code>{pf(tp3)}</code>  (RR 1:5.0)\n\n"
f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
f"📊 <b>MULTI-TIMEFRAME CONFLUENCE</b>\n\n"
f"🗺 <b>Старший ТФ ({ctx2_tf.upper() if ctx2_tf else '?'}):</b> {TREND_N.get(ctx2.get('direction',''),'—')}\n"
f"📈 <b>Контекст ({r.get('context_tf','').upper()}):</b> {TREND_N.get(ctx.get('direction',''),'—')}\n"
f"⚡ <b>Поточний ({tf.upper()}):</b> {TREND_N.get(trend.get('direction',''),'—')} {STR_N.get(trend.get('strength',''),'')}\n"
f"🔗 <b>MTF:</b> {mtf.get('label','—')}\n\n"
f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
f"🧠 <b>SMART MONEY CONCEPTS</b>\n\n"
f"🏗 <b>Структура:</b> {smc.get('structure','—')} | Bias: {smc.get('bias','—')}\n"
f"{'✅' if smc.get('bos') else '❌'} <b>BOS</b> (Break of Structure)\n"
f"{'⚠️' if smc.get('choch') else '✅'} <b>CHoCH</b> {'виявлено — обережно!' if smc.get('choch') else 'не виявлено'}\n"
f"{'🔥' if liq.get('swept_low') else '❌'} <b>Liquidity Sweep знизу</b>{'  → сигнал BUY!' if liq.get('swept_low') else ''}\n"
f"{'🔥' if liq.get('swept_high') else '❌'} <b>Liquidity Sweep зверху</b>{'  → сигнал SELL!' if liq.get('swept_high') else ''}\n\n"
f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
f"📊 <b>ІНДИКАТОРИ</b>\n\n"
f"📊 <b>ADX:</b> {adx.get('adx',0):.0f} {'✅ сильний тренд' if adx.get('strong') else '➡️ слабкий/флет'}\n"
f"{'🔴' if rsi>70 else '🟢' if rsi<30 else '🟡'} <b>RSI:</b> {rsi:.0f} {'перекуплено' if rsi>70 else 'перепродано' if rsi<30 else 'нейтрально'}\n"
f"{'🔴' if stk>80 else '🟢' if stk<20 else '🟡'} <b>Stoch RSI:</b> {stk:.0f}\n"
f"{'🟢' if macd>0 else '🔴'} <b>MACD hist:</b> {'бичачий ↑' if macd>0 else 'ведмежий ↓'}\n"
f"🌊 <b>Williams %R:</b> {wil:.0f} {'перепродано' if wil<-80 else 'перекуплено' if wil>-20 else 'нейтрально'}\n"
f"📐 <b>CCI:</b> {cci:.0f}\n"
f"{'🟢' if div.get('any_bull') else '🔴' if div.get('any_bear') else '⚪'} <b>Дивергенція:</b> "
f"{'Бичача RSI/MACD 🚀' if div.get('any_bull') else 'Ведмежа RSI/MACD 📉' if div.get('any_bear') else 'не виявлено'}\n\n"
f"📦 <b>Volume Profile:</b>\n"
f"  POC: <code>{pf(vp.get('poc'))}</code> | VAH: <code>{pf(vp.get('vah'))}</code> | VAL: <code>{pf(vp.get('val'))}</code>\n"
f"  Ціна {'вище' if vp.get('above_poc') else 'нижче'} POC | {'В зоні вартості ✅' if vp.get('in_value') else 'Поза зоною вартості'}\n\n"
f"🕯 <b>Паттерни:</b> {pats_text}\n"
f"💧 <b>Order Flow:</b> {of.get('bias','—')} (delta: {of.get('delta',0):.2f})\n\n"
f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
f"🏆 <b>ТОП ФАКТОРИ РІШЕННЯ</b>\n\n"
f"{fact_text}\n\n"
f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
f"⚠️ <b>ПОПЕРЕДЖЕННЯ</b>\n\n"
f"{warn_text}\n\n"
f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
f"{sicon} <b>Сесія:</b> {sname}\n"
f"⏰ {r.get('timestamp', datetime.now()).strftime('%H:%M:%S')} UTC\n"
f"<i>⚠️ Не є фінансовою порадою</i>"
    )
    return msg

def format_scan_result(results: list) -> str:
    if not results: return "❌ Немає результатів"
    buys  = [r for r in results if r.get("signal")=="BUY"]
    sells = [r for r in results if r.get("signal")=="SELL"]
    errs  = [r for r in results if r.get("signal")=="ERROR"]

    lines = ["🔍 <b>АВТО-СКАН v4</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"]

    for title, grp, em in [("КУПИТИ (BUY)", buys,"🟢"),("ПРОДАТИ (SELL)",sells,"🔴")]:
        if not grp: continue
        lines.append(f"{em} <b>{title}</b>")
        for r in grp:
            pats = ", ".join(PAT_N.get(p,p) for p in r.get("patterns",[])[:2]) or "—"
            liq_sw = "🔥 LiqSweep " if r.get("liq_sweep") else ""
            div_s  = "📊 Div " if r.get("divergence") else ""
            lines.append(
                f"  📊 <b>{r['symbol']}</b>  Grade: <b>{r.get('grade','—')[:2]}</b>  {r.get('probability',0)}%\n"
                f"     {r.get('mtf','—')}\n"
                f"     {liq_sw}{div_s}ADX {r.get('adx',0):.0f} · RSI {r.get('rsi',0)} · RR 1:{r.get('rr',0)}\n"
                f"     ⚡ {r.get('entry_label','—')}\n"
                f"     🕯 {pats}"
            )
        lines.append("")

    if errs:
        lines.append(f"❌ Помилка: {', '.join(r['symbol'] for r in errs)}")
    lines += [
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🟢 {len(buys)} BUY · 🔴 {len(sells)} SELL · 📊 {len(results)} всього",
        f"⏰ {datetime.now().strftime('%H:%M:%S')} UTC",
        "<i>⚠️ Risk Management завжди!</i>",
    ]
    return "\n".join(lines)

def format_trade_report(trade: dict, analysis: dict) -> str:
    """Автоматичний звіт після закриття угоди"""
    sym  = trade.get("symbol","—"); d = trade.get("direction","—")
    entry= trade.get("entry_price",0); close_p = trade.get("close_price",0)
    result_usd = trade.get("result_usd",0)
    result_rr  = trade.get("result_rr",0)
    won  = result_usd > 0
    pf   = lambda p: _pf(p, sym)

    # Аналіз що відбулося
    r = analysis
    trend   = r.get("trend",{})
    smc     = r.get("smc",{})
    liq     = r.get("liquidity",{})
    div     = r.get("divergence",{})
    pats    = r.get("candle_patterns",[])
    prob    = r.get("probability",{})
    mtf     = r.get("mtf",{})

    lessons = []
    mistakes= []
    goods   = []

    # Аналіз чому так сталось
    if won:
        if trend["direction"] == ("bullish" if d=="BUY" else "bearish"):
            goods.append("✅ Торгували ЗА трендом — правильно!")
        if liq.get("swept_low") and d=="BUY":
            goods.append("✅ Ліквідність знизу була зібрана перед входом — сильний сигнал")
        if div.get("any_bull") and d=="BUY":
            goods.append("✅ Бичача дивергенція підтвердила рух")
        if prob.get("probability",0) >= 60:
            goods.append(f"✅ Probability Score був {prob.get('probability',0)}% — угода мала сенс")
        if mtf.get("score",0) >= 65:
            goods.append(f"✅ MTF confluence підтримував напрямок")
    else:
        if trend["direction"] != ("bullish" if d=="BUY" else "bearish"):
            mistakes.append(f"❌ Торгували ПРОТИ тренду ({trend['direction']}) — небезпечно")
            lessons.append("📚 Урок: Завжди торгуйте в напрямку тренду на старшому ТФ")
        if smc.get("choch"):
            mistakes.append("❌ CHoCH був виявлений — ринок змінював характер")
            lessons.append("📚 Урок: CHoCH = зміна характеру ринку, краще зачекати")
        if prob.get("probability",0) < 40:
            mistakes.append(f"❌ Probability Score {prob.get('probability',0)}% — сигнал був слабким")
            lessons.append("📚 Урок: Не торгуйте якщо Probability < 50%")
        if mtf.get("score",0) < 65:
            mistakes.append("❌ MTF не підтримував напрямок — старші ТФ суперечили")
            lessons.append("📚 Урок: Потрібен збіг мінімум 2 з 3 таймфреймів")
        if not pats:
            mistakes.append("❌ Не було свічкового паттерну підтвердження")
            lessons.append("📚 Урок: Завжди чекайте паттерн підтвердження на вхідному ТФ")

    result_icon = "✅ ПРОФІТ" if won else "❌ ЗБИТОК"
    result_emoji= "💰" if won else "📉"

    report = (
f"{result_emoji} <b>ЗВІТ ПО УГОДІ: {sym}</b>\n"
f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
f"{'🟢' if d=='BUY' else '🔴'} <b>Напрямок:</b> {d}\n"
f"📍 <b>Вхід:</b> <code>{pf(entry)}</code>\n"
f"🚪 <b>Вихід:</b> <code>{pf(close_p)}</code>\n"
f"💵 <b>Результат:</b> {result_icon}: "
f"{'+'if won else ''}{result_usd:.2f}$ (RR 1:{abs(result_rr):.2f})\n\n"
f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
f"🔍 <b>ЩО ВІДБУЛОСЯ І ЧОМУ</b>\n\n"
    )

    if goods:
        report += "✅ <b>Що зроблено правильно:</b>\n"
        report += "\n".join(f"  {g}" for g in goods) + "\n\n"

    if mistakes:
        report += "❌ <b>Помилки та причини невдачі:</b>\n"
        report += "\n".join(f"  {m}" for m in mistakes) + "\n\n"

    if lessons:
        report += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        report += "📚 <b>УРОКИ ДЛЯ НАСТУПНИХ УГОД:</b>\n"
        report += "\n".join(f"  {l}" for l in lessons) + "\n\n"

    # Контекст ринку на момент угоди
    report += (
f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
f"📊 <b>Контекст ринку при угоді:</b>\n"
f"  Тренд: {TREND_N.get(trend.get('direction',''),'—')}\n"
f"  SMC Bias: {smc.get('bias','—')} | BOS: {'✅'if smc.get('bos') else '❌'}\n"
f"  MTF: {mtf.get('label','—')}\n"
f"  Probability: {prob.get('probability',0)}% ({prob.get('grade','—')})\n"
f"  Паттерни: {', '.join(PAT_N.get(p,p) for p in pats) or '—'}\n\n"
f"<i>Збережено в журнал. Продовжуйте вчитись!</i>"
    )
    return report
