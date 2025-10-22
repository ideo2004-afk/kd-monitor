# (所有 import 和函式 0, 1, 2, 3, 4 都和您剛剛測試的版本相同)
import yfinance as yf
import talib
import sys
import numpy as np
import requests # 我們只需要 requests
import os
import pandas as pd
from openai import OpenAI

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
# (與 v-config-file 本地版相同)
# ===============================================
STOCK_LIST = load_stock_list("stock_list.txt") 

# ===============================================
# 函式 1: 計算 KD 值
# (與 v-config-file 本地版相同)
# ===============================================
def calculate_kd_from_data(stock_name, high_series, low_series, close_series, kd_params):
    """
    從「已傳入」的 Pandas Series 資料中計算 KD 值
    (這個函式「不會」執行網路下載)
    """
    print(f"--- 正在計算: {stock_name} ({kd_params}) ---")
    
    # 解開參數
    fastk, slowk, slowd = kd_params
    
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
            
        required_lookback = 20 
        
        if len(data) < required_lookback or len(data) < 3: 
            print(f"錯誤：{stock_name} 資料筆數不足 ({len(data)} 筆)，無法計算 KD。")
            return (None,) * 6
            
        # 2. 準備陣列
        high = data['High'].to_numpy(dtype=float).ravel()
        low = data['Low'].to_numpy(dtype=float).ravel()
        close = data['Close'].to_numpy(dtype=float).ravel()
        
        # 3. 計算 KD 值
        k_values, d_values = talib.STOCH(high, low, close,
                                         fastk_period=fastk,
                                         slowk_period=slowk,
                                         slowk_matype=0,
                                         slowd_period=slowd,
                                         slowd_matype=0)
        
        if len(k_values) < 2 or len(close) < 2:
            print(f"錯誤：{stock_name} 計算出的序列長度不足 2，無法比較趨勢。")
            return (None,) * 6
            
        # 4. 獲取資料
        latest_k = k_values[-1] 
        latest_d = d_values[-1]
        prev_k = k_values[-2]   
        prev_d = d_values[-2]
        latest_price = close[-1] 
        prev_price = close[-2]   
        
        # 5. 處理 NaN
        if np.isnan(latest_k) or np.isnan(latest_d):
            print(f"警告：{stock_name} 計算出的最新值為 NaN。嘗試抓取前一日的資料...")
            if len(k_values) > 2 and len(close) > 2: 
                latest_k = k_values[-2]
                latest_d = d_values[-2]
                prev_k = k_values[-3]   
                prev_d = d_values[-3]
                latest_price = close[-2] 
                prev_price = close[-3]   
                if np.isnan(latest_k):
                     print(f"錯誤：{stock_name} 前一日資料仍為 NaN，放棄。")
                     return (None,) * 6
            else:
                print(f"錯誤：{stock_name} 資料長度不足，無法抓取前一日資料。")
                return (None,) * 6

        # 6. 回傳 6 個值
        return latest_k, latest_d, prev_k, prev_d, latest_price, prev_price

    except Exception as e:
        print(f"計算 {stock_name} 時發生錯誤: {e}")
        return (None,) * 6

# ===============================================
# 函式 2: 發送 ntfy.sh 通知
# (與 v-config-file 本地版相同)
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
# 函式 3: 計算百分比變化字串
# (與 v-config-file 本地版相同)
# ===============================================
def get_percent_change_str(current, previous):
    """
    計算目前值與前一值的百分比變化，並回傳格式化字串
    """
    if previous == 0 or previous is None or current is None:
        return " (N/A)" # 避免除以零或 None
    
    # 計算百分比
    percent = ((current - previous) / abs(previous)) * 100
    
    # 格式化字串
    return f" {percent:+.1f}%"

# ===============================================
# 函式 4: 呼叫 OpenAI 取得總結
# (與 v-config-file 本地版相同)
# ===============================================
def get_ai_summary(api_key, context_data):
    """
    將彙整的資料發送給 OpenAI 並取得總結
    """
    print("\n--- 正在呼叫 OpenAI 進行總結 ---")
    
    try:
        client = OpenAI(api_key=api_key)
        
        # 組合 Prompt
        prompt = f"""
        請扮演一位專業、言簡意賅的金融市場分析師。
        我將提供一份包含台股（盤中即時）和美股（前日收盤）的市場數據摘要。
        請您根據這份數據，提供一段約 100 字的「市場動態總結」。
        
        您的總結應包含：
        1. 快速點出台股（台積電, 0050）的目前走勢（例如：盤中強勢、盤整）。
        2. 點出美股科技股（TSLA, AMD, NVDA, INTC）的收盤狀況（例如：普遍強勢、漲跌互見）。
        3. 點出任何顯著的警示信號（例如：XXX 進入超買區）。
        
        請使用繁體中文，語氣專業。

        [原始數據]
        {context_data}
        """
        
        completion = client.chat.completions.create(
            model="gpt-4o-mini", # 使用最新、速度快且成本效益高的模型
            messages=[
                {"role": "system", "content": "你是一位專業、言簡意賅的金融市場分析師。"},
                {"role": "user", "content": prompt}
            ]
        )
        
        summary = completion.choices[0].message.content
        print("AI 總結獲取成功。")
        return summary
        
    except Exception as e:
        print(f"呼叫 OpenAI API 時發生錯誤: {e}")
        return None # 發生錯誤時回傳 None

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
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    
    if not NTFY_TOPIC or not OPENAI_API_KEY:
        print("="*50)
        print("錯誤：找不到 NTFY_TOPIC 或 OPENAI_API_KEY 環境變數。")
        print("請確保您已在 GitHub Secrets 中設定這兩個值。")
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

    # --- 步驟 4: 呼叫 AI 進行總結 ---
    ai_context = "\n\n".join(final_report_blocks) 
    ai_summary = get_ai_summary(OPENAI_API_KEY, ai_context)

    # --- 步驟 5: 組合並發送最終報告 ---
    if not final_report_blocks:
        print("沒有任何股票資料被處理，任務結束。")
    else:
        # 組合數據報告
        data_report = "\n\n".join(final_report_blocks)
        
        if ai_summary:
            final_message = (
                f"🧠 **AI 市場總結**\n"
                f"{ai_summary}\n"
                f"\n"
                f"—————\n"
                f"**詳細數據**\n"
                f"—————\n"
                f"{data_report}"
            )
        else:
            print("AI 總結失敗，僅發送原始數據。")
            final_message = data_report
        
        send_ntfy_notification(NTFY_TOPIC, report_title, final_message)
    
    print("\n--- 任務完成 ---")

if __name__ == "__main__":
    main()
