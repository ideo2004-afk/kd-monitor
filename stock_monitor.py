import yfinance as yf
import sys
import numpy as np
import requests # 我們只需要 requests
import os
import pandas as pd

# ===============================================
# 函式 0: 從檔案讀取股票清單
# (與 v-config-file 本地版相同)
# ===============================================
def load_stock_list(filepath="stock_list.txt"):
    """
    從指定的文字檔讀取股票清單。
    檔案格式: 名稱, 代號, 跌幅閾值, 回補閾值 (以逗號分隔)
    """
    stock_list_from_file = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                parts = [part.strip() for part in line.split(',')]
                if len(parts) == 4:
                    try:
                        name = parts[0]
                        ticker = parts[1]
                        # 跌幅與回補閾值
                        thresholds = (float(parts[2]), float(parts[3]))
                        stock_list_from_file.append((name, ticker, thresholds))
                    except ValueError:
                        print(f"警告：無法解析行 '{line}' 中的閾值，已跳過。")
                else:
                    print(f"警告：行 '{line}' 格式不正確 (需要 4 個欄位)，已跳過。")
                    
    except FileNotFoundError:
        print(f"錯誤：找不到股票清單檔案 '{filepath}'。")
        sys.exit(1)
    except Exception as e:
        print(f"嚴重錯誤: {e}")
        sys.exit(1)
        
    return stock_list_from_file

# ===============================================
# 參數區 (Parameterization)
# ===============================================
STOCK_LIST = load_stock_list("stock_list.txt") 

# ===============================================
# 函式 1: 計算動態趨勢 (跌幅與回補)
# ===============================================
def calculate_dynamic_trends(stock_name, data, drop_threshold, recovery_threshold):
    """
    計算目前價格相對於近期高點的跌幅，以及相對於近期低點的回補程度。
    回傳: (目前價格, 漲跌幅, 距高點跌幅, 距低點回補)
    """
    print(f"--- 正在計算: {stock_name} (閾值: {drop_threshold}%, {recovery_threshold}%) ---")
    
    try:
        # 清理 NaN 資料 (例如開盤前抓到空行)
        data = data.dropna()
        
        if data.empty or len(data) < 2:
            return None
            
        # 使用最近 30 筆資料作為觀察期
        lookback_period = data.tail(30)
        
        peak_price = lookback_period['High'].max()
        valley_price = lookback_period['Low'].min()
        
        latest_price = data['Close'].iloc[-1]
        prev_price = data['Close'].iloc[-2]
        
        # 1. 當日漲跌幅
        daily_change = ((latest_price - prev_price) / prev_price) * 100
        
        # 2. 距高點跌幅 (Drop from Peak)
        drop_from_peak = ((latest_price - peak_price) / peak_price) * 100
        
        # 3. 距低點回補 (Recovery from Valley)
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
    """
    發送通知到 ntfy.sh
    """
    print(f"\n正在發送 ntfy.sh 通知到主題: {topic}")
    try:
        response = requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode('utf-8'), # 訊息本文，需編碼
            headers={
                "Title": title.encode('utf-8'), # 標題，也需編碼
                "Priority": "high", # 設置高優先級 (可選)
                "Tags": "chart_with_upwards_trend" # 顯示 📈 圖示 (可選)
            }
        )
        response.raise_for_status() # 檢查是否有 HTTP 錯誤
        print("ntfy 通知發送成功！")
    except requests.exceptions.RequestException as e:
        print(f"發送 ntfy 通知時發生錯誤: {e}")

# ===============================================
# --- 主程式入口 (v-config-file-github 版) ---
# ===============================================
def main():
    """
    主執行函式
    """
    # === 這裡是關鍵修改 (GitHub 版) ===
    # --- 步驟 1: 從 GitHub Secrets 讀取 API Keys ---
    NTFY_TOPIC = os.getenv("NTFY_TOPIC")
    
    if not NTFY_TOPIC:
        print("="*50)
        print("錯誤：找不到 NTFY_TOPIC 環境變數。")
        print("請確保您已在 GitHub Secrets 中設定此變數。")
        print("="*50)
        sys.exit(1)
    # =====================================

    print("--- 每日多股票K值回報任務開始 ---")

    # 用來存放每一支股票的報告字串
    final_report_blocks = []
    
    report_title = "每日股市通報" 
    
    # --- 步驟 2: 準備並一次性下載所有股票 ---
    stock_info = {} 
    ticker_list = [] 
    
    # 從載入的 STOCK_LIST 讀取 (保持不變)
    for stock_name, ticker, kd_params in STOCK_LIST: 
        ticker_list.append(ticker)
        stock_info[ticker] = {"name": stock_name, "params": kd_params}

    print(f"正在一次性下載 {len(ticker_list)} 支股票資料...")
    
    all_data = yf.download(tickers=ticker_list, period="3mo", auto_adjust=True)
    
    if all_data.empty:
        print("錯誤：無法下載任何股票資料。任務終止。")
        send_ntfy_notification(NTFY_TOPIC, report_title, "錯誤：無法下載任何 yfinance 資料。")
        sys.exit(1)
        
    print("資料下載完畢，開始逐一計算...")

    # --- 步驟 3: 遍歷處理 (使用已下載的資料) ---
    for ticker in ticker_list:
        
        stock_name = stock_info[ticker]["name"]
        drop_thr, rec_thr = stock_info[ticker]["params"]
        
        # 1. 抓取該股票的資料
        try:
            if len(ticker_list) > 1:
                # 多支股票時 yf.download 會回傳 MultiIndex
                stock_data = pd.DataFrame({
                    'High': all_data['High'][ticker],
                    'Low': all_data['Low'][ticker],
                    'Close': all_data['Close'][ticker]
                })
            else:
                stock_data = all_data[['High', 'Low', 'Close']]
        except KeyError:
            print(f"警告：找不到 {ticker} 資料。")
            final_report_blocks.append(f"📈 {stock_name} ({ticker})\n (資料下載異常)")
            continue
            
        res = calculate_dynamic_trends(stock_name, stock_data, drop_thr, rec_thr)
        
        if res is None:
            final_report_blocks.append(f"📈 {stock_name} ({ticker})\n (計算失敗)")
        else:
            # 組合報告區塊
            report_header = f"📈 {stock_name} ({ticker})"
            
            # 狀態標記
            alert_str = ""
            if res["drop"] <= -drop_thr:
                alert_str += f" ⚠️跌幅達標({res['drop']:.1f}%)"
            if res["recovery"] >= rec_thr:
                alert_str += f" 🟢回補達標({res['recovery']:.1f}%)"
                
            report_body = (
                f"價格：{res['price']:,.2f} ({res['daily_change']:+.1f}%)\n"
                f"近期高點：{res['peak']:,.2f} (距高點 {res['drop']:.1f}%)\n"
                f"近期低點：{res['valley']:,.2f} (距低點 {res['recovery']:+.1f}%)\n"
                f"狀態：{alert_str if alert_str else '正常'}"
            )
            
            final_report_blocks.append(f"{report_header}\n{report_body}")

    # --- 步驟 5: 組合並發送最終報告 ---
    if not final_report_blocks:
        print("沒有任何股票資料被處理，任務結束。")
    else:
        # 組合數據報告
        data_report = "\n\n".join(final_report_blocks)
        send_ntfy_notification(NTFY_TOPIC, report_title, data_report)
    
    print("\n--- 任務完成 ---")

if __name__ == "__main__":
    main()
