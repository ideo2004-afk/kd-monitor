import yfinance as yf
import sys
import numpy as np
import requests
import os
import pandas as pd
import json
from dotenv import load_dotenv

# 自動載入 .env 檔案中的環境變數
load_dotenv()

# ===============================================
# 函式 0: 從環境變數或檔案讀取股票清單
# ===============================================
def load_stock_list():
    """
    優先從環境變數 STOCK_CONFIG_JSON 讀取標的清單。
    如果沒有環境變數，則嘗試讀取本地 stock_list.txt (回溯相容)。
    """
    # 優先從環境變數讀取
    config_json = os.getenv("STOCK_CONFIG_JSON")
    if config_json:
        try:
            stocks = json.loads(config_json)
            print("成功從環境變數載入股票配置。")
            return stocks
        except Exception as e:
            print(f"解析 STOCK_CONFIG_JSON 失敗: {e}")
    
    # 回溯相容：讀取本地檔案
    filepath = "stock_list.txt"
    stock_list_from_file = []
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    parts = [part.strip() for part in line.split(',')]
                    if len(parts) >= 4:
                        try:
                            item = {
                                "name": parts[0],
                                "ticker": parts[1],
                                "drop": float(parts[2]),
                                "rec": float(parts[3])
                            }
                            # 如果有第五個欄位，視為成本
                            if len(parts) >= 5:
                                item["cost"] = float(parts[4])
                            stock_list_from_file.append(item)
                        except ValueError:
                            print(f"警告：無法解析行 '{line}' 中的數值。")
            print(f"從本地 '{filepath}' 載入股票配置。")
            return stock_list_from_file
    except Exception as e:
        print(f"讀取 '{filepath}' 時發生錯誤: {e}")

    print("錯誤：無法取得股票清單設定資訊。")
    return []

# ===============================================
# 函式 1: 計算動態趨勢 (跌幅與回補)
# ===============================================
def calculate_dynamic_trends(stock_name, data, drop_threshold, recovery_threshold):
    """
    計算目前價格相對於近期高點的跌幅，以及相對於近期低點的回補程度。
    """
    try:
        data = data.dropna()
        if data.empty or len(data) < 2:
            return None
            
        lookback_period = data.tail(30)
        peak_price = lookback_period['High'].max()
        valley_price = lookback_period['Low'].min()
        
        latest_price = data['Close'].iloc[-1]
        prev_price = data['Close'].iloc[-2]
        
        daily_change = ((latest_price - prev_price) / prev_price) * 100
        drop_from_peak = ((latest_price - peak_price) / peak_price) * 100
        recovery_from_valley = ((latest_price - valley_price) / valley_price) * 100
        
        return {
            "price": latest_price,
            "daily_change": daily_change,
            "peak": peak_price,
            "valley": valley_price,
            "drop": drop_from_peak,
            "recovery": recovery_from_valley
        }
    except Exception as e:
        print(f"計算 {stock_name} 時發生錯誤: {e}")
        return None

# ===============================================
# 函式 2: 發送 ntfy.sh 通知
# ===============================================
def send_ntfy_notification(topic, title, message):
    print(f"\n正在發送通知到 ntfy.sh主題: {topic}")
    try:
        response = requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode('utf-8'),
            headers={
                "Title": title.encode('utf-8'),
                "Priority": "high",
                "Tags": "chart_with_upwards_trend"
            }
        )
        response.raise_for_status()
        print("ntfy 通知發送成功！")
    except requests.exceptions.RequestException as e:
        print(f"發送 ntfy 通知時發生錯誤: {e}")

# ===============================================
# --- 主程式入口 ---
# ===============================================
def main():
    NTFY_TOPIC = os.getenv("NTFY_TOPIC")
    if not NTFY_TOPIC:
        print("錯誤：找不到 NTFY_TOPIC 環境變數。")
        sys.exit(1)

    STOCK_CONFIG = load_stock_list()
    if not STOCK_CONFIG:
        print("沒有配置任何股票標的，任務終止。")
        sys.exit(1)

    print(f"--- 股市監控任務開始 (標的數量: {len(STOCK_CONFIG)}) ---")
    
    ticker_list = [s["ticker"] for s in STOCK_CONFIG]
    final_report_blocks = []
    report_title = "每日股市監控報告"

    print(f"正在下載 {len(ticker_list)} 支股票資料...")
    all_data = yf.download(tickers=ticker_list, period="3mo", auto_adjust=True)
    
    if all_data.empty:
        send_ntfy_notification(NTFY_TOPIC, report_title, "錯誤：無法下載股市資料。")
        sys.exit(1)

    for item in STOCK_CONFIG:
        ticker = item["ticker"]
        name = item["name"]
        drop_thr = item["drop"]
        rec_thr = item["rec"]
        cost = item.get("cost") # 持有成本

        try:
            if len(ticker_list) > 1:
                stock_data = pd.DataFrame({
                    'High': all_data['High'][ticker],
                    'Low': all_data['Low'][ticker],
                    'Close': all_data['Close'][ticker]
                })
            else:
                stock_data = all_data[['High', 'Low', 'Close']]
        except (KeyError, ValueError):
            final_report_blocks.append(f"📈 {name} ({ticker})\n (資料下載異常)")
            continue
            
        res = calculate_dynamic_trends(name, stock_data, drop_thr, rec_thr)
        if res is None:
            final_report_blocks.append(f"📈 {name} ({ticker})\n (計算失敗)")
            continue

        # --- 判斷邏輯與建議 ---
        status_tag = ""
        advice = ""
        
        is_drop_hit = res["drop"] <= -drop_thr
        is_rec_hit = res["recovery"] >= rec_thr
        
        if cost is not None:
            # 已持有標的
            pnl_pct = ((res["price"] - cost) / cost) * 100
            holding_info = f"持有成本：{cost:,.2f} (目前損益：{pnl_pct:+.1f}%)\n"
            
            if is_drop_hit:
                status_tag = "⚠️ 跌幅達標"
                advice = "💡 建議：股價回落，考慮部分獲利了結或設置停損。"
            elif is_rec_hit:
                status_tag = "🟢 回補達標"
                advice = "💡 建議：股價反彈，可考慮逢低加碼或攤平成本。"
            else:
                status_tag = "正常"
                advice = "💡 建議：持有並觀察。"
        else:
            # 觀察標的
            holding_info = "觀察清單 (未持有)\n"
            if is_rec_hit:
                status_tag = "🔥 入手時機"
                advice = "💡 建議：近期強勢回升，可考慮建立首筆部位。"
            elif is_drop_hit:
                status_tag = "⚠️ 觀察中"
                advice = "💡 建議：持續回落中，先不要急著接刀。"
            else:
                status_tag = "正常"
                advice = "💡 建議：耐心等待信號。"

        report_block = (
            f"📈 {name} ({ticker}) | {status_tag}\n"
            f"{holding_info}"
            f"目前：{res['price']:,.2f} ({res['daily_change']:+.1f}%)\n"
            f"近期高點：{res['peak']:,.2f} (距高點 {res['drop']:.1f}%)\n"
            f"近期低點：{res['valley']:,.2f} (距低點 {res['recovery']:+.1f}%)\n"
            f"{advice}"
        )
        final_report_blocks.append(report_block)

    if final_report_blocks:
        total_report = "\n\n".join(final_report_blocks)
        send_ntfy_notification(NTFY_TOPIC, report_title, total_report)
    
    print("--- 任務完成 ---")

if __name__ == "__main__":
    main()
