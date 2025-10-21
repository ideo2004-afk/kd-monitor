import yfinance as yf
import talib
import sys
import numpy as np
import requests 
import os # <--- 確保 import os 存在

# ===============================================
# 函式 1: get_tsmc_kd()
# (完全不變)
# ===============================================
def get_tsmc_kd():
    """
    獲取台積電 (2330.TW) 最新的 KD 值
    """
    try:
        data = yf.download("2330.TW", period="3mo", auto_adjust=True)
        if data.empty:
            print("錯誤：無法下載 2330.TW 股價資料")
            return None, None
        data = data.dropna()
        if data.empty:
            print("錯誤：清理 NaN 後資料為空。")
            return None, None
        required_lookback = 20 
        if len(data) < required_lookback:
            print(f"錯誤：資料筆數不足 ({len(data)} 筆)，無法計算 KD。")
            return None, None
        high = data['High'].to_numpy(dtype=float).ravel()
        low = data['Low'].to_numpy(dtype=float).ravel()
        close = data['Close'].to_numpy(dtype=float).ravel()
        k_values, d_values = talib.STOCH(high, low, close,
                                         fastk_period=9,
                                         slowk_period=3,
                                         slowk_matype=0,
                                         slowd_period=3,
                                         slowd_matype=0)
        latest_k = k_values[-1] 
        latest_d = d_values[-1] 
        if np.isnan(latest_k) or np.isnan(latest_d):
            print("警告：計算出的最新值為 NaN，嘗試抓取前一日。")
            if len(k_values) > 1:
                latest_k = k_values[-2]
                latest_d = d_values[-2]
                if np.isnan(latest_k):
                     print("錯誤：前一日資料仍為 NaN。")
                     return None, None
            else:
                print("錯誤：資料長度不足，無法抓取前一日。")
                return None, None
        return latest_k, latest_d
    except Exception as e:
        print(f"計算 KD 時發生錯誤: {e}")
        return None, None

# ===============================================
# 函式 2: send_ntfy_notification()
# (完全不變)
# ===============================================
def send_ntfy_notification(topic, title, message):
    """
    發送通知到 ntfy.sh
    """
    print(f"正在發送 ntfy.sh 通知到主題: {topic}")
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
# --- 主程式入口 (v-github-actions 版) ---
# ===============================================
if __name__ == "__main__":
    
    # --- 步驟 1: 從「環境變數」讀取 ntfy 主題 ---
    # === 這裡是關鍵修改 ===
    NTFY_TOPIC = os.getenv("NTFY_TOPIC")
    # ====================

    if not NTFY_TOPIC:
        print("="*50)
        print("錯誤：找不到 NTFY_TOPIC 環境變數。")
        print("請在 GitHub Secrets 中設定 NTFY_TOPIC。")
        print("="*50)
        sys.exit(1)

    # --- 步驟 2: 抓取 KD 值 ---
    print("--- 任務開始 ---")
    print("正在抓取 KD 值...")
    k, d = get_tsmc_kd()
    
    if k is None:
        print("KD 值獲取失敗，中斷任務。")
        sys.exit(1)
        
    print(f"KD 值獲取成功: K={k:.2f}, D={d:.2f}")

    # --- 步驟 3: 組合回報訊息 ---
    report_title = "台積電(2330.TW) 每日 K 值回報"
    report_message = f"K 值: {k:.2f}\nD 值: {d:.2f}"
    
    # --- 步驟 4: 執行發送 (觸發 ntfy) ---
    send_ntfy_notification(NTFY_TOPIC, report_title, report_message)
    
    print("--- 任務完成 ---")
