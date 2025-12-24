import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta

def run_backtest(df, stock_code, buy_threshold=0.1, sell_threshold=0.1, initial_capital=10000):
    """
    精簡版回測邏輯，包含 0.1% 滑價與期末清算
    """
    if df.empty or len(df) < 2:
        return None

    is_taiwan = ".TW" in stock_code or ".TWO" in stock_code
    if is_taiwan:
        trading_fee_rate = 0.001425 * 0.65
        sell_tax_rate = 0.003
    else:
        trading_fee_rate = 0.005
        sell_tax_rate = 0.0

    slippage = 0.001 # 0.1% 滑價

    # Strategy A: Buy and Hold
    first_price = float(df['Close'].iloc[0])
    last_price = float(df['Close'].iloc[-1])
    shares_a = (initial_capital / (1 + trading_fee_rate + slippage)) / first_price
    final_a = (shares_a * last_price) * (1 - trading_fee_rate - sell_tax_rate - slippage)

    # Strategy B: Trend Following
    cap_b = initial_capital
    shares_b = (cap_b / (1 + trading_fee_rate + slippage)) / first_price
    cap_b = 0
    in_pos_b = True
    peak_price = first_price
    valley_price = first_price
    
    for _, row in df.iterrows():
        current_price = float(row['Close'])
        if in_pos_b:
            if current_price > peak_price: peak_price = current_price
            if current_price <= peak_price * (1 - sell_threshold):
                sell_proceeds = shares_b * current_price
                cap_b = sell_proceeds * (1 - trading_fee_rate - sell_tax_rate - slippage)
                shares_b = 0
                in_pos_b = False
                valley_price = current_price
        else:
            if current_price < valley_price: valley_price = current_price
            if current_price >= valley_price * (1 + buy_threshold):
                cap_b = (cap_b / (1 + trading_fee_rate + slippage))
                shares_b = cap_b / current_price
                cap_b = 0
                in_pos_b = True
                peak_price = current_price

    final_val_b = cap_b
    if in_pos_b:
        final_val_b = (shares_b * last_price) * (1 - trading_fee_rate - sell_tax_rate - slippage)

    return {
        'roi_a': (final_a / initial_capital - 1) * 100,
        'roi_b': (final_val_b / initial_capital - 1) * 100
    }

def main():
    print("=== 進入 2 年期滾動回測模式 ===")
    user_stock = input("請輸入股票代號 (例如 2330, QQQ) [預設 2330]: ").strip() or "2330"
    user_buy_t = float(input("請輸入買入門檻 % (例如 10) [預設 10]: ").strip() or "10") / 100.0
    user_sell_t = float(input("請輸入賣出門檻 % (例如 10) [預設 10]: ").strip() or "10") / 100.0

    stock = f"{user_stock}.TW" if user_stock.isdigit() and len(user_stock) == 4 else user_stock
    
    start_all = datetime(2010, 1, 1)
    end_all = datetime(2025, 12, 20)
    
    print(f"正在抓取 {stock} 完整數據 ({start_all.date()} ~ {end_all.date()})...")
    df_full = yf.download(stock, start=start_all, end=end_all)
    if isinstance(df_full.columns, pd.MultiIndex):
        df_full.columns = df_full.columns.get_level_values(0)

    results = []
    current_start = start_all
    
    # 滾動視窗：每個月一次，每次兩年
    while current_start + relativedelta(years=2) <= end_all:
        window_end = current_start + relativedelta(years=2)
        
        # 取得該範圍的數據
        mask = (df_full.index >= current_start) & (df_full.index < window_end)
        df_window = df_full.loc[mask]
        
        if not df_window.empty and len(df_window) > 20:
            res = run_backtest(df_window, stock, buy_threshold=user_buy_t, sell_threshold=user_sell_t)
            if res:
                win = res['roi_b'] > res['roi_a']
                results.append({
                    'start': current_start.strftime('%Y-%m'),
                    'roi_a': res['roi_a'],
                    'roi_b': res['roi_b'],
                    'win': win
                })
        
        # 下一個月
        current_start += relativedelta(months=1)

    # 輸出結果表格
    print("\n" + "="*60)
    print(f"{'時間區間 (2年)':<15} | {'盤後 (A)':>10} | {'策略 (B)':>10} | {'勝負':<5}")
    print("-" * 60)
    
    wins = 0
    total = len(results)
    
    for r in results:
        win_str = "勝" if r['win'] else " "
        if r['win']: wins += 1
        print(f"{r['start']:<15} | {r['roi_a']:>9.1f}% | {r['roi_b']:>9.1f}% | {win_str}")
    
    print("="*60)
    win_rate = (wins / total * 100) if total > 0 else 0
    print(f"測試總次數: {total}")
    print(f"策略 B 打敗 A 次數: {wins}")
    print(f"勝率 (Win Rate): {win_rate:.1f}%")
    print("="*60)

if __name__ == "__main__":
    main()
