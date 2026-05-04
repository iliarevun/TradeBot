"""
journal.py — Торговий журнал з авто-аналізом і навчанням на помилках
"""
import json, os, logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)
JOURNAL_FILE = "trade_journal.json"

def _load() -> list:
    if not os.path.exists(JOURNAL_FILE): return []
    try:
        with open(JOURNAL_FILE,"r",encoding="utf-8") as f:
            return json.load(f)
    except: return []

def _save(data: list):
    with open(JOURNAL_FILE,"w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

def add_trade(trade: dict) -> dict:
    data = _load()
    trade["id"]      = int(datetime.now().timestamp())
    trade["created"] = str(datetime.now())
    trade["status"]  = "open"
    data.append(trade)
    _save(data); return trade

def close_trade(trade_id: int, close_price: float, result_usd: float) -> Optional[dict]:
    data = _load()
    for t in data:
        if t.get("id") == trade_id:
            t["status"]      = "closed"
            t["close_price"] = close_price
            t["result_usd"]  = result_usd
            t["closed_at"]   = str(datetime.now())
            entry = t.get("entry_price", close_price)
            sl    = t.get("sl", entry)
            t["result_rr"] = result_usd / max(abs(entry-sl)*10000*0.1, 0.01)
            t["won"] = result_usd > 0
            _save(data); return t
    return None

def get_open_trades() -> list:
    return [t for t in _load() if t.get("status")=="open"]

def get_all_trades() -> list:
    return _load()

def get_stats() -> dict:
    trades = [t for t in _load() if t.get("status")=="closed"]
    if not trades:
        return {"total":0,"wins":0,"losses":0,"win_rate":0,"total_pnl":0,
                "avg_rr":0,"best":0,"worst":0,"mistakes":{}}

    wins   = [t for t in trades if t.get("won")]
    losses = [t for t in trades if not t.get("won")]
    pnl    = sum(t.get("result_usd",0) for t in trades)
    rrs    = [abs(t.get("result_rr",0)) for t in trades]

    # Аналіз помилок
    mistakes = {}
    for t in losses:
        for err in t.get("mistakes",[]):
            mistakes[err] = mistakes.get(err,0)+1

    # Найчастіша помилка
    top_mistake = max(mistakes, key=mistakes.get) if mistakes else None

    return {
        "total":       len(trades),
        "wins":        len(wins),
        "losses":      len(losses),
        "win_rate":    round(len(wins)/len(trades)*100,1) if trades else 0,
        "total_pnl":   round(pnl,2),
        "avg_rr":      round(sum(rrs)/len(rrs),2) if rrs else 0,
        "best":        round(max(t.get("result_usd",0) for t in trades),2),
        "worst":       round(min(t.get("result_usd",0) for t in trades),2),
        "mistakes":    mistakes,
        "top_mistake": top_mistake,
        "streak_win":  _streak(trades, True),
        "streak_loss": _streak(trades, False),
    }

def _streak(trades, want_win):
    streak = 0
    for t in reversed(trades):
        if t.get("won") == want_win: streak += 1
        else: break
    return streak

def format_stats(stats: dict) -> str:
    wr  = stats["win_rate"]; pnl = stats["total_pnl"]
    pnl_icon = "💰" if pnl>=0 else "📉"
    wr_icon  = "🟢" if wr>=55 else ("🟡" if wr>=45 else "🔴")

    lines = [
        "📊 <b>СТАТИСТИКА ЖУРНАЛУ</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📈 Всього угод: <b>{stats['total']}</b>",
        f"{wr_icon} Win Rate: <b>{wr}%</b>  (🟢 {stats['wins']} / 🔴 {stats['losses']})",
        f"{pnl_icon} P&L: <b>{'+'if pnl>=0 else ''}{pnl}$</b>",
        f"⚖️ Середній RR: <b>1:{stats['avg_rr']}</b>",
        f"🏆 Найкраща угода: <b>+{stats['best']}$</b>",
        f"💔 Найгірша угода: <b>{stats['worst']}$</b>",
        f"🔥 Поточна серія перемог: <b>{stats['streak_win']}</b>",
        f"❄️ Поточна серія збитків: <b>{stats['streak_loss']}</b>",
    ]

    if stats.get("top_mistake"):
        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "🎓 <b>НАЙЧАСТІША ПОМИЛКА:</b>",
            f"  ❌ {stats['top_mistake']}",
            "  💡 Зверніть увагу при наступному вході!",
        ]

    mistakes = stats.get("mistakes",{})
    if mistakes:
        top3 = sorted(mistakes.items(), key=lambda x:-x[1])[:3]
        lines += ["", "📋 <b>Всі помилки:</b>"]
        for err, cnt in top3:
            lines.append(f"  • {err}: {cnt}x")

    return "\n".join(lines)
