import os
import warnings

warnings.filterwarnings("ignore", module="urllib3")

import akshare as ak
import pandas as pd
import requests

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
def _normalize_ohlc(df: pd.DataFrame, date_col: str, open_col: str, close_col: str) -> pd.DataFrame:
    out = df.rename(columns={date_col: "trade_date", open_col: "open", close_col: "close"})
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    out = out.sort_values("trade_date").reset_index(drop=True)
    out["open"] = out["open"].astype(float)
    out["close"] = out["close"].astype(float)
    return out[["trade_date", "open", "close"]]


def _sina_symbol(symbol: str) -> str:
    return f"sh{symbol}" if symbol.startswith("5") else f"sz{symbol}"


def _fetch_sina_daily(symbol: str) -> pd.DataFrame:
    df = ak.fund_etf_hist_sina(symbol=_sina_symbol(symbol))
    if df is None or df.empty:
        raise ValueError("新浪日线获取失败")
    return _normalize_ohlc(df, "date", "open", "close")


def _fetch_sina_weekly(symbol: str) -> pd.DataFrame:
    daily = _fetch_sina_daily(symbol)
    daily = daily.set_index("trade_date").sort_index()
    weekly = daily.resample("W-FRI").agg(
        {"open": "first", "close": "last"}
    ).dropna(subset=["close"])
    return weekly.reset_index()


def fetch_daily_data(symbol: str) -> pd.DataFrame:
    return _fetch_sina_daily(symbol)


def fetch_weekly_data(symbol: str) -> pd.DataFrame:
    return _fetch_sina_weekly(symbol)


def latest_indicator_row(df: pd.DataFrame):
    work = df.copy()
    work["rsi"] = compute_rsi(work["close"], rsi_period)
    work["ma60"] = work["close"].rolling(ma60_period).mean()
    work["ma120"] = work["close"].rolling(ma120_period).mean()
    return work.iloc[-1]

# ------------------ 策略逻辑 ------------------
def _fmt_metric(value, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{float(value):.{digits}f}"


def format_key_metrics(row) -> str:
    return (
        "📊 关键指标\n"
        f"当场股价：{_fmt_metric(row['close'])}\n"
        f"60 日均线：{_fmt_metric(row['ma60'])}\n"
        f"120 日均线：{_fmt_metric(row['ma120'])}\n"
        f"RSI：{_fmt_metric(row['rsi'])}"
    )


def format_push(body: str, latest) -> str:
    return f"{etf_label}\n{body}\n\n{format_key_metrics(latest)}"


def analyze_signal(df_weekly, metrics_row):
    w = df_weekly.copy()
    w["rsi"] = compute_rsi(w["close"], rsi_period)
    w["ma60"] = w["close"].rolling(ma60_period).mean()
    w["ma120"] = w["close"].rolling(ma120_period).mean()
    latest = w.iloc[-1]

    # 全仓买入条件
    if latest["close"] < latest["ma120"]:
        body = "全仓买入信号：跌破 120 周均线"
    # 8 成仓买入条件
    elif latest["rsi"] < 48 and latest["close"] < latest["ma60"]:
        body = "买入 8 成仓位信号：RSI 偏低且低于 60 周均线"
    # 清仓条件：RSI > 60 且本周K线为绿色
    elif latest["rsi"] > 60 and latest["close"] < latest["open"]:
        body = "清仓信号：RSI 偏高且出现下跌 K 线"
    else:
        body = "这周不宜操作"

    send_telegram(format_push(body, metrics_row))

# ------------------ 主程序 ------------------
def main():
    try:
        df_weekly = fetch_weekly_data(symbol)
        df_daily = fetch_daily_data(symbol)
        metrics_row = latest_indicator_row(df_daily)
        analyze_signal(df_weekly, metrics_row)
    except Exception as e:
        print(f"脚本异常: {e}")

if __name__ == "__main__":
    main()