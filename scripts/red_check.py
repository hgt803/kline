import os
import pandas as pd
import requests
import akshare as ak

# ------------------ 全局变量 ------------------
bot_token = os.getenv("TG_BOT_TOKEN")
chat_id = os.getenv("TG_USER_ID")
symbol = "510880"  # 510880 红利 ETF（AkShare 代码）
etf_label = "红利 ETF"
rsi_period = 14
ma60_period = 60
ma120_period = 120

# ------------------ Telegram 推送函数 ------------------
def send_telegram(message):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            print("消息已发送")
        else:
            print(f"发送失败: {response.text}")
    except Exception as e:
        print(f"发送异常: {e}")

# ------------------ RSI 计算 ------------------
def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

# ------------------ 数据获取 ------------------
def fetch_weekly_data(symbol: str) -> pd.DataFrame:
    df = ak.fund_etf_hist_em(symbol=symbol, period="weekly", adjust="")
    if df is None or df.empty:
        raise ValueError("获取数据失败")
    df = df.rename(columns={"日期": "trade_date", "开盘": "open", "收盘": "close"})
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.sort_values("trade_date").reset_index(drop=True)
    df["open"] = df["open"].astype(float)
    df["close"] = df["close"].astype(float)
    return df

# ------------------ 策略逻辑 ------------------
def format_push(body: str) -> str:
    return f"{etf_label}\n{body}"


def analyze_signal(df):
    df['rsi'] = compute_rsi(df['close'], rsi_period)
    df['ma60'] = df['close'].rolling(ma60_period).mean()
    df['ma120'] = df['close'].rolling(ma120_period).mean()

    latest = df.iloc[-1]

    # 全仓买入条件
    if latest['close'] < latest['ma120']:
        body = f"全仓买入信号：当前价格 {latest['close']:.2f} 跌破 120 周均线 ({latest['ma120']:.2f})"
    # 8 成仓买入条件
    elif latest['rsi'] < 48 and latest['close'] < latest['ma60']:
        body = f"买入 8 成仓位信号：当前价格 {latest['close']:.2f}, RSI {latest['rsi']:.2f}, 低于 60 周均线 ({latest['ma60']:.2f})"
    # 清仓条件：RSI > 60 且本周K线为绿色
    elif latest['rsi'] > 60 and latest['close'] < latest['open']:
        body = f"清仓信号：当前价格 {latest['close']:.2f}, RSI {latest['rsi']:.2f}, 出现下跌K线"
    else:
        body = "这周不宜操作"

    send_telegram(format_push(body))

# ------------------ 主程序 ------------------
def main():
    try:
        df = fetch_weekly_data(symbol)
        analyze_signal(df)
    except Exception as e:
        print(f"脚本异常: {e}")

if __name__ == "__main__":
    main()