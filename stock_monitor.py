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
    檔案格式: 名稱, 代號, K參數, D參數, D平滑參數 (以逗號分隔)
    跳過 # 開頭的註解行和空行。
    """
    stock_list_from_file = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip() # 移除前後空白
                if not line or line.startswith('#'):
                    continue # 跳過空行或註解行
                
                parts = [part.strip() for part in line.split(',')]
                if len(parts) == 5:
                    try:
                        name = parts[0]
                        ticker = parts[1]
                        # 將 KD 參數轉換為整數
                        kd_params = (int(parts[2]), int(parts[3]), int(parts[4]))
                        stock_list_from_file.append((name, ticker, kd_params))
                    except ValueError:
                        print(f"警告：無法解析行 '{line}' 中的 KD 參數，已跳過。")
                    except Exception as e:
                         print(f"警告：處理行 '{line}' 時發生錯誤: {e}，已跳過。")
                else:
                    print(f"警告：行 '{line}' 格式不正確 (需要 5 個欄位)，已跳過。")
                    
    except FileNotFoundError:
        print(f"錯誤：找不到股票清單檔案 '{filepath}'。")
        # 在 GitHub Actions 中，如果檔案不存在，可能是 checkout 步驟問題
        print("請確保 stock_list.txt 檔案已上傳至 GitHub 儲存庫。")
        sys.exit(1) # 如果找不到檔案，直接結束程式
    except Exception as e:
        print(f"讀取股票清單檔案 '{filepath}' 時發生嚴重錯誤: {e}")
        sys.exit(1)
        
    if not stock_list_from_file:
        print(f"錯誤：股票清單檔案 '{filepath}' 為空或無法解析任何有效資料。")
        sys.exit(1)
        
    print(f"成功從 '{filepath}' 載入 {len(stock_list_from_file)} 支股票。")
    return stock_list_from_file

# ===============================================
# 參數區 (Parameterization)
# ===============================================
STOCK_LIST = load_stock_list("stock_list.txt") 

# ===============================================
# 函式 1: 計算 KD 值 (手動計算，不需 TA-Lib)
# ===============================================
def calculate_kd_from_data(stock_name, high_series, low_series, close_series, kd_params):
    """
    從「已傳入」的 Pandas Series 資料中計算 KD 值
    採用標準公式:
    RSV = (今日收盤價 - 最近 N 天最低價) / (最近 N 天最高價 - 最近 N 天最低價) * 100
    K = (1/3) * RSV + (2/3) * 前一日 K
    D = (1/3) * 今日 K + (2/3) * 前一日 D
    """
    print(f"--- 正在計算: {stock_name} ({kd_params}) ---")
    
    # 解開參數
    n_days, k_smooth, d_smooth = kd_params
    
    try:
        # 1. 組合並清理資料
        data = pd.DataFrame({
            'High': high_series, 
            'Low': low_series, 
            'Close': close_series
        }).dropna()

        if data.empty:
            print(f"錯誤：{stock_name} 清理 NaN 後資料為空。")
            return (None,) * 6 # 回傳 6 個 None
            
        if len(data) < n_days: 
            print(f"錯誤：{stock_name} 資料筆數不足 ({len(data)} 筆)，無法計算 KD。")
            return (None,) * 6
            
        # 2. 計算 RSV
        # 最近 n_days 天的最低價
        low_min = data['Low'].rolling(window=n_days).min()
        # 最近 n_days 天的最高價
        high_max = data['High'].rolling(window=n_days).max()
        
        # RSV (Raw Stochastic Value)
        rsv = (data['Close'] - low_min) / (high_max - low_min) * 100
        rsv = rsv.fillna(50) # 初期值填充

        # 3. 計算 K, D
        k_values = [50.0]
        d_values = [50.0]
        
        # 平滑係數
        k_weight = 1.0 / k_smooth
        d_weight = 1.0 / d_smooth
        
        # 逐日計算 (雖然有效率較低的方法，但程式碼較直觀)
        # 我們只需要最近幾個值，所以從 RSV 開始計算
        rsv_list = rsv.tolist()
        for i in range(1, len(rsv_list)):
            current_k = (k_weight * rsv_list[i]) + ((1 - k_weight) * k_values[-1])
            k_values.append(current_k)
            
            current_d = (d_weight * current_k) + ((1 - d_weight) * d_values[-1])
            d_values.append(current_d)
        
        # 4. 獲取資料
        latest_k = k_values[-1] 
        latest_d = d_values[-1]
        prev_k = k_values[-2]   
        prev_d = d_values[-2]
        latest_price = data['Close'].iloc[-1]
        prev_price = data['Close'].iloc[-2]
        
        # 6. 回傳 6 個值
        return latest_k, latest_d, prev_k, prev_d, latest_price, prev_price

    except Exception as e:
        print(f"計算 {stock_name} 時發生錯誤: {e}")
        return (None,) * 6

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
        kd_params = stock_info[ticker]["params"]
        
        # 1. 抓取該股票的資料
        if len(ticker_list) > 1:
            try:
                high_series = all_data['High'][ticker]
                low_series = all_data['Low'][ticker]
                close_series = all_data['Close'][ticker]
            except KeyError:
                print(f"警告：在下載的資料中找不到 {ticker} 的欄位，可能該股票代號有誤或今日無資料。跳過...")
                report_header = f"📈 {stock_name} ({ticker})"
                report_body = " (資料下載異常)"
                block = f"{report_header}\n{report_body}"
                final_report_blocks.append(block)
                continue # 跳到下一支股票
        else: # 如果只有一支股票
            try:
                high_series = all_data['High']
                low_series = all_data['Low']
                close_series = all_data['Close']
            except KeyError:
                print(f"警告：在下載的資料中找不到欄位，可能股票代號 {ticker} 有誤或今日無資料。跳過...")
                report_header = f"📈 {stock_name} ({ticker})"
                report_body = " (資料下載異常)"
                block = f"{report_header}\n{report_body}"
                final_report_blocks.append(block)
                continue # 跳到下一支股票
            
        k, d, prev_k, prev_d, price, prev_price = calculate_kd_from_data(
            stock_name, high_series, low_series, close_series, kd_params
        )
        
        # 2. 檢查資料是否抓取成功
        if k is None:
            print(f"處理 {stock_name} 失敗，跳過。")
            report_header = f"📈 {stock_name} ({ticker})"
            report_body = " (計算失敗)"
            
        else:
            # 抓取成功，組合報告區塊
            print(f"處理 {stock_name} 成功。")
            report_header = f"📈 {stock_name} ({ticker})"
            
            price_change = get_percent_change_str(price, prev_price)
            k_change = get_percent_change_str(k, prev_k)
            d_change = get_percent_change_str(d, prev_d)
            
            k_str = f"K值：{k:.2f}{k_change}"
            if k > 80:
                k_str += " ⚠️(超買)"
            elif k < 20:
                k_str += " 🟢(超賣)"
                
            d_str = f"D值：{d:.2f}{d_change}"
            if d > 80:
                d_str += " ⚠️"
            elif d < 20:
                d_str += " 🟢"
            
            report_body = (
                f"價格：{price:,.2f}{price_change}\n" 
                f"{k_str}\n" 
                f"{d_str}"
            )
        
        # 3. 組合區塊
        block = (
            f"{report_header}\n"
            f"{report_body}"
        )
        final_report_blocks.append(block)

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
