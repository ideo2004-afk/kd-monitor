"""
AI 泡沫化預警系統 — 市場快照擷取器

獨立於 stock_monitor.py（個人持股 ntfy 警報），不共用設定、不互相干擾。
由 GitHub Actions 排程執行，把 yfinance 抓到的報價寫成 JSON commit 回本 repo，
供 mempalace-zh/warning-system 每日掃描讀取（該 session 的出口網路政策擋掉了
直接呼叫行情 API，但 git pull 這個 repo 不受影響）。
"""
import yfinance as yf
import json
import os
from datetime import datetime, timezone

TICKERS = {
    "TSM": "台積電 ADR",
    "SMH": "VanEck 半導體ETF",
    "GOOGL": "Google",
    "NVDA": "Nvidia",
    "AVGO": "Broadcom",
    "AMD": "AMD",
    "MU": "美光",
    "ASML": "ASML",
    "AMAT": "應用材料",
    "LRCX": "Lam Research",
    "KLAC": "KLA",
    "INTC": "Intel",
    "GEV": "GE Vernova",
    "VRT": "Vertiv",
    "ANET": "Arista Networks",
}

# 四大核心持股：儀表板頂部週開盤價走勢圖用
CORE_HOLDINGS = ["TSM", "SMH", "GOOGL", "INTC"]

# 陰跌尺/回補尺B軌需要的週線+均線分析：僅 TSM/SMH（減碼階梯核心追蹤標的）
WEEKLY_MA_TICKERS = ["TSM", "SMH"]


def weekly_opens(ticker, days=7):
    """抓最近 N 個交易日的開盤價。yfinance 的日線只回傳有成交的交易日,
    週末/假日本來就不在回傳的時間序列裡,遇到假日 open 是 NaN 也一併濾掉,
    所以折線圖天生只會畫到真正開盤的日子,不用額外判斷日曆。"""
    hist = yf.Ticker(ticker).history(period="1mo", interval="1d")
    hist = hist.dropna(subset=["Open"])
    tail = hist.tail(days)
    return [
        {"date": idx.strftime("%m/%d"), "open": round(float(row["Open"]), 2)}
        for idx, row in tail.iterrows()
    ]


def weekly_ma_analysis(ticker, out_weeks=20):
    """抓週線收盤價，算10週均線(陰跌尺加權合成距離用)與12週均線(≈60個交易日的季線MA60,
    回補尺B軌用)。取代原本 mempalace-zh 那邊用 WebFetch 直接打 Yahoo Finance 圖表 API 的作法——
    這條資料改由 GitHub Actions 抓取、跟每日快照一樣用 git push 帶回去，不受任何 session 的
    出口網路政策影響，也不用使用者手動截圖。"""
    hist = yf.Ticker(ticker).history(period="1y", interval="1wk")
    hist = hist.dropna(subset=["Close"])
    hist["ma10"] = hist["Close"].rolling(window=10).mean()
    hist["ma60"] = hist["Close"].rolling(window=12).mean()

    points = []
    for idx, row in hist.tail(out_weeks).iterrows():
        close = float(row["Close"])
        ma10 = float(row["ma10"]) if row["ma10"] == row["ma10"] else None
        ma60 = float(row["ma60"]) if row["ma60"] == row["ma60"] else None
        points.append({
            "week_end": idx.strftime("%Y-%m-%d"),
            "close": round(close, 2),
            "ma10": round(ma10, 2) if ma10 is not None else None,
            "ma10_distance_pct": round((close - ma10) / ma10 * 100, 2) if ma10 else None,
            "ma60": round(ma60, 2) if ma60 is not None else None,
            "above_ma60": (close > ma60) if ma60 is not None else None,
        })

    consecutive_weeks_below_ma10 = 0
    for p in reversed(points):
        if p["ma10_distance_pct"] is not None and p["ma10_distance_pct"] < 0:
            consecutive_weeks_below_ma10 += 1
        else:
            break

    return points, consecutive_weeks_below_ma10


def main():
    tickers = list(TICKERS.keys())
    data = yf.download(tickers=tickers, period="5d", auto_adjust=True, group_by="ticker")

    snapshot = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "抓取當下的最新交易日資料；若美股尚未收盤，close 為盤中最新成交價，非正式收盤價",
        "tickers": {},
        "core_holdings_weekly_open": {},
    }

    for t in tickers:
        try:
            df = data[t].dropna() if len(tickers) > 1 else data.dropna()
            if len(df) < 2:
                snapshot["tickers"][t] = {"name": TICKERS[t], "error": "insufficient_data"}
                continue
            last_close = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2])
            pct_change = (last_close - prev_close) / prev_close * 100
            snapshot["tickers"][t] = {
                "name": TICKERS[t],
                "price": round(last_close, 2),
                "prev_close": round(prev_close, 2),
                "pct_change": round(pct_change, 2),
                "as_of_date": str(df.index[-1].date()),
            }
        except Exception as e:
            snapshot["tickers"][t] = {"name": TICKERS[t], "error": str(e)}

    for t in CORE_HOLDINGS:
        try:
            pts = weekly_opens(t)
            wk_chg = (pts[-1]["open"] - pts[0]["open"]) / pts[0]["open"] * 100 if len(pts) >= 2 else None
            snapshot["core_holdings_weekly_open"][t] = {
                "name": TICKERS[t],
                "points": pts,
                "week_pct_change": round(wk_chg, 2) if wk_chg is not None else None,
            }
        except Exception as e:
            snapshot["core_holdings_weekly_open"][t] = {"name": TICKERS.get(t, t), "error": str(e)}

    snapshot["weekly_ma_analysis"] = {}
    for t in WEEKLY_MA_TICKERS:
        try:
            points, streak = weekly_ma_analysis(t)
            snapshot["weekly_ma_analysis"][t] = {
                "name": TICKERS[t],
                "points": points,
                "consecutive_weeks_below_ma10": streak,
            }
        except Exception as e:
            snapshot["weekly_ma_analysis"][t] = {"name": TICKERS.get(t, t), "error": str(e)}

    os.makedirs("data", exist_ok=True)
    with open("data/warning_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    print(json.dumps(snapshot, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
