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


def main():
    tickers = list(TICKERS.keys())
    data = yf.download(tickers=tickers, period="5d", auto_adjust=True, group_by="ticker")

    snapshot = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "抓取當下的最新交易日資料；若美股尚未收盤，close 為盤中最新成交價，非正式收盤價",
        "tickers": {},
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

    os.makedirs("data", exist_ok=True)
    with open("data/warning_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    print(json.dumps(snapshot, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
