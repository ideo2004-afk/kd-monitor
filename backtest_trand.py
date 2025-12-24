import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# New Gemini SDK (google-genai)
try:
    from google import genai
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

load_dotenv()

def run_backtest(df, stock_code, buy_threshold=0.1, sell_threshold=0.1, initial_capital=10000):
    """
    Runs a backtest comparing Strategy A (Hold), Strategy B (Trend), and Strategy C (SMA).
    """
    # Ensure columns are flat
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    is_taiwan = ".TW" in stock_code or ".TWO" in stock_code
    
    if is_taiwan:
        trading_fee_rate = 0.001425 * 0.65
        sell_tax_rate = 0.003
    else:
        trading_fee_rate = 0.005 # 0.5%
        sell_tax_rate = 0.0

    # Strategy A: Buy and Hold
    first_price = float(df['Close'].iloc[0])
    last_price = float(df['Close'].iloc[-1])
    shares_a = (initial_capital / (1 + trading_fee_rate)) / first_price
    final_a = shares_a * last_price

    # Strategy B: Trend Following (Dual Threshold)
    cap_b = initial_capital
    shares_b = (cap_b / (1 + trading_fee_rate)) / first_price
    cap_b = 0
    in_pos_b = True
    peak_price = first_price
    valley_price = first_price
    
    history_b = []
    trans_b = 1
    
    for _, row in df.iterrows():
        current_price = float(row['Close'])
        if in_pos_b:
            if current_price > peak_price: peak_price = current_price
            if current_price <= peak_price * (1 - sell_threshold):
                sell_proceeds = shares_b * current_price
                cap_b = sell_proceeds * (1 - trading_fee_rate - sell_tax_rate)
                shares_b = 0
                in_pos_b = False
                valley_price = current_price
                trans_b += 1
        else:
            if current_price < valley_price: valley_price = current_price
            if current_price >= valley_price * (1 + buy_threshold):
                cap_b = (cap_b / (1 + trading_fee_rate))
                shares_b = cap_b / current_price
                cap_b = 0
                in_pos_b = True
                peak_price = current_price
                trans_b += 1
        history_b.append(cap_b + (shares_b * current_price))

    # Strategy C: SMA 20 with 3-day cool-down
    df_c = df.copy()
    df_c['SMA20'] = df_c['Close'].rolling(window=20).mean()
    cap_c = initial_capital
    shares_c = 0
    in_pos_c = False
    last_trans_day_c = -999
    history_c = []
    trans_c = 0
    
    for i, (idx, row) in enumerate(df_c.iterrows()):
        current_price = float(row['Close'])
        current_sma = float(row['SMA20'])
        if pd.isna(current_sma):
            pass
        else:
            if (i - last_trans_day_c) >= 3:
                if current_price > current_sma and not in_pos_c:
                    cap_c = (cap_c / (1 + trading_fee_rate))
                    shares_c = cap_c / current_price
                    cap_c = 0
                    in_pos_c = True
                    trans_c += 1
                    last_trans_day_c = i
                elif current_price < current_sma and in_pos_c:
                    sell_proceeds = shares_c * current_price
                    cap_c = sell_proceeds * (1 - trading_fee_rate - sell_tax_rate)
                    shares_c = 0
                    in_pos_c = False
                    trans_c += 1
                    last_trans_day_c = i
        history_c.append(cap_c + (shares_c * current_price))

    # Strategy D: ATR Adaptive Volatility
    df_d = df.copy()
    # ATR Calculation (14 days)
    high_low = df_d['High'] - df_d['Low']
    high_close = (df_d['High'] - df_d['Close'].shift()).abs()
    low_close = (df_d['Low'] - df_d['Close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df_d['ATR'] = true_range.rolling(14).mean()
    
    cap_d = initial_capital
    shares_d = (cap_d / (1 + trading_fee_rate)) / first_price
    cap_d = 0
    in_pos_d = True
    peak_price = first_price
    valley_price = first_price
    
    history_d = []
    trans_d = 1
    multiplier = 3.0 # ATR Multiplier
    
    for i, (idx, row) in enumerate(df_d.iterrows()):
        current_price = float(row['Close'])
        current_atr = float(row['ATR'])
        
        if pd.isna(current_atr):
            pass
        else:
            dynamic_t = (current_atr * multiplier) / current_price
            
            if in_pos_d:
                if current_price > peak_price: peak_price = current_price
                if current_price <= peak_price * (1 - dynamic_t):
                    sell_proceeds = shares_d * current_price
                    cap_d = sell_proceeds * (1 - trading_fee_rate - sell_tax_rate)
                    shares_d = 0
                    in_pos_d = False
                    valley_price = current_price
                    trans_d += 1
            else:
                if current_price < valley_price: valley_price = current_price
                if current_price >= valley_price * (1 + dynamic_t):
                    cap_d = (cap_d / (1 + trading_fee_rate))
                    shares_d = cap_d / current_price
                    cap_d = 0
                    in_pos_d = True
                    peak_price = current_price
                    trans_d += 1
        history_d.append(cap_d + (shares_d * current_price))

    return {
        'final_a': final_a,
        'final_b': cap_b + (shares_b * last_price),
        'trans_b': trans_b,
        'history_b': history_b,
        'final_c': cap_c + (shares_c * last_price),
        'trans_c': trans_c,
        'history_c': history_c,
        'final_d': cap_d + (shares_d * last_price),
        'trans_d': trans_d,
        'history_d': history_d,
        'market': '台股' if is_taiwan else '美股/複委託',
        'fee': trading_fee_rate,
        'tax': sell_tax_rate
    }

def get_ai_analysis(stock_code, period, matrix_text, best_b, roi_a):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not AI_AVAILABLE:
        return "提示：如需 AI 自動化分析，請在 .env 中設定 GEMINI_API_KEY 並安裝 google-genai。"
    
    try:
        client = genai.Client(api_key=api_key)
        
        # Use a widely supported model name
        model_id = "gemini-2.0-flash" 
        
        prompt = f"""
你是一位專業、客觀且具備深厚實戰經驗的「首席量化策略官 (Chief Investment Officer)」。
請針對以下這檔股票的 2D 門檻優化獲利矩陣進行深度分析。

【交易環境】
- 股票代碼: {stock_code}
- 測試期間: {period}
- 基準報酬 (Strategy A - 長期持有): {roi_a:.1f}%
- 最佳波段組合報酬 (Strategy B): {best_b:.1f}%

【策略邏輯提醒】
- 買入門檻 (Buy_t)：當股價自最近「谷底」回升 X% 時買入。
- 賣出門檻 (Sell_t)：當股價自買入後的「高峰」回落 Y% 時賣出。

【獲利矩陣數據 (買進入門檻 \\ 賣出門檻)】
{matrix_text}
(註：標註 * 代表該組合「勝過」長期持有報酬率)

【請提供專業且具建設性的策略分析 (繁體中文)】：
1. **策略價值評估 (Alpha vs Beta)**：
   - 觀察最佳組合 B 與基準 A 的差異。
   - **空頭市場特別注意**：如果 A 是大賠，而 B 能減輕虧損甚至轉正，代表策略具有極佳的「避險/防禦價值」，請給予肯定分析。
   - **多頭市場特別注意**：B 是否能有效放大獲益，還是只是被動隨大盤上漲。
2. **參數平原與穩健性診斷**：
   - 觀察 * 標記的分佈。如果是「整片聚集 (Plateau)」，代表策略具備高容錯率與實戰價值；如果是「零星散佈 (Islands)」，請警告過度擬合 (Overfitting) 的風險。
3. **最終實戰結論與建議**：
   - 總結這檔股票的股性（波動大、適合趨勢跟隨，還是穩健增長適合存股）。
   - 給出具體的參數建議或風險提示。如果策略確實無效，請坦誠建議維持長期持有。
"""
        response = client.models.generate_content(
            model=model_id,
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"AI 分析失敗: {str(e)}"

def parse_date(date_str):
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ('%Y-%m-%d', '%Y%m%d'):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

def main():
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description='Dual-Threshold Stock Backtesting & Optimization Tool')
    parser.add_argument('--stock', type=str, help='Stock code (e.g. 2330, AAPL)')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD), defaults to 5 years before end date')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD), defaults to today')
    parser.add_argument('--buy_t', type=float, default=0.1, help='Buy threshold (e.g. 0.1 for 10 percent)')
    parser.add_argument('--sell_t', type=float, default=0.1, help='Sell threshold (e.g. 0.1 for 10 percent)')
    parser.add_argument('--optimize', action='store_true', help='Search for best (Buy, Sell) threshold pair')
    
    args = parser.parse_args()

    # Interactive mode if no arguments or missing key ones
    if len(sys.argv) == 1:
        print("=== 進入互動式模式 (直接按 Enter 可使用預設值) ===")
        args.stock = input("a. 股票代號 (例如 2330, TSLA) [預設 2330]: ").strip() or "2330"
        args.start = input("b. 起始時間 (例如 20220101): ").strip() or None
        args.end = input("c. 結束時間 (例如 今天): ").strip() or None
        # In interactive mode, we default to optimization if the user just ran the script
        args.optimize = True 
        print("----------------------------------------------")

    # Dynamic date logic with flexible parsing
    end_dt = parse_date(args.end) if args.end else datetime.now()
    if not end_dt:
        print(f"錯誤: 無法解析結束日期 '{args.end}'")
        return
    end_date_str = end_dt.strftime('%Y-%m-%d')

    start_dt = parse_date(args.start) if args.start else (end_dt - timedelta(days=5*365))
    if not start_dt:
        print(f"錯誤: 無法解析起始日期 '{args.start}'")
        return
    start_date_str = start_dt.strftime('%Y-%m-%d')

    stock = f"{args.stock}.TW" if args.stock.isdigit() and len(args.stock) == 4 else args.stock
    
    print(f"正在抓取 {stock} 數據 ({start_date_str} ~ {end_date_str})...")
    # Set group_by='column' to handle potential MultiIndex more explicitly if needed, but we flatten it anyway
    df = yf.download(stock, start=start_date_str, end=end_date_str)
    if df.empty: return

    # Flatten columns right after download to avoid index errors
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if args.optimize:
        print(f"\n===== 2D 門檻優化搜尋 ({start_date_str} ~ {end_date_str}) =====")
        market_test = run_backtest(df.head(10), stock_code=stock)
        print(f"模式: {market_test['market']} (手續費: {market_test['fee']*100:.3f}%, 稅: {market_test['tax']*100:.1f}%)")
        print("-" * 60)
        
        thresholds = np.arange(0.03, 0.16, 0.02)
        matrix_data = {}
        best_roi_b = -999
        best_buy_t = 0
        best_sell_t = 0
        
        for bt in thresholds:
            matrix_data[bt] = {}
            for st in thresholds:
                res = run_backtest(df, stock_code=stock, buy_threshold=bt, sell_threshold=st)
                roi = (res['final_b']/10000 - 1) * 100
                matrix_data[bt][st] = roi
                if roi > best_roi_b:
                    best_roi_b = roi
                    best_buy_t = bt
                    best_sell_t = st

        res_a = run_backtest(df, stock_code=stock, buy_threshold=0.1, sell_threshold=0.1)
        roi_a = (res_a['final_a']/10000 - 1) * 100

        # Construct Matrix Text for AI
        matrix_header = "買\\賣 | " + " | ".join([f"{t*100:>3.0f}%" for t in thresholds])
        matrix_divider = "-" * (8 + len(thresholds)*7)
        matrix_text = matrix_header + "\n" + matrix_divider + "\n"
        
        res_c = run_backtest(df, stock_code=stock)
        roi_c = (res_c['final_c']/10000 - 1) * 100
        
        res_d = run_backtest(df, stock_code=stock)
        roi_d = (res_d['final_d']/10000 - 1) * 100
        
        print("\n獲利矩陣 (獲利高原分析):")
        print(f"基準對照 Strategy A (長期持有): {roi_a:.1f}%")
        print(f"對手策略 Strategy C (月線趨勢): {roi_c:.1f}%")
        print(f"自適應策略 Strategy D (ATR 3.0): {roi_d:.1f}%")
        print(matrix_divider)
        print(matrix_header)
        print(matrix_divider)

        for bt in thresholds:
            row_str = f"{bt*100:>3.0f}%  | "
            for st in thresholds:
                val = matrix_data[bt][st]
                mark = "*" if val > roi_a else " "
                row_str += f"{val:>4.0f}%{mark}| "
            print(row_str)
            matrix_text += row_str + "\n"
        
        print(matrix_divider)
        print(f"基準報酬 (Hold): {roi_a:.1f}% | 最佳組合 (B): 買回升 {best_buy_t*100:.0f}% / 賣回落 {best_sell_t*100:.0f}% -> {best_roi_b:.1f}%")
        
        # AI Analysis Call
        print("\n正在傳送到 Gemini AI 進行深度量化分析...")
        ai_report = get_ai_analysis(stock, f"{start_date_str}~{end_date_str}", matrix_text, best_roi_b, roi_a)
        print("\n===== Gemini 量化分析報告 =====")
        print(ai_report)
        print("================================")
    else:
        res = run_backtest(df, stock_code=stock, buy_threshold=args.buy_t, sell_threshold=args.sell_t)
        print(f"\n回測結果: {stock} ({res['market']})")
        print(f"區間: {start_date_str} ~ {end_date_str}")
        print(f"模式: 手續費 {res['fee']*100:.3f}%, 稅 {res['tax']*100:.1f}%")
        print(f"門檻設定: 買入 (谷底回升) {args.buy_t*100:.1f}%, 賣出 (高峰回落) {args.sell_t*100:.1f}%")
        print("-" * 50)
        print(f"數字 A (存股持有): ${res['final_a']:.2f} ({(res['final_a']/10000-1)*100:.1f}%)")
        print(f"數字 C (月線策略): ${res['final_c']:.2f} ({(res['final_c']/10000-1)*100:.1f}%) | 交易 {res['trans_c']} 次")
        print(f"數字 D (自適應策): ${res['final_d']:.2f} ({(res['final_d']/10000-1)*100:.1f}%) | 交易 {res['trans_d']} 次")
        print(f"數字 B (趨勢策略): ${res['final_b']:.2f} ({(res['final_b']/10000-1)*100:.1f}%) | 交易 {res['trans_b']} 次")
        print("-" * 50)

        plt.figure(figsize=(12, 6))
        first_price_val = float(df['Close'].iloc[0])
        plt.plot(df.index, (10000/first_price_val) * df['Close'], label='Strategy A (Hold)', alpha=0.5)
        plt.plot(df.index, res['history_c'], label='Strategy C (SMA20)', linestyle='--')
        plt.plot(df.index, res['history_d'], label='Strategy D (ATR)', linestyle='-.')
        plt.plot(df.index, res['history_b'], label=f'Strategy B ({args.buy_t*100:.0f}%/{args.sell_t*100:.0f}%)')
        plt.title(f"Backtest: {stock} ({res['market']})")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig("backtest_result.png")
        print(f"圖表已儲存至: backtest_result.png")

if __name__ == "__main__":
    main()
