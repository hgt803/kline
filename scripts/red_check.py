import os
import warnings
from functools import lru_cache

warnings.filterwarnings("ignore", module="urllib3")

import akshare as ak
import pandas as pd
import requests

# ------------------ 全局变量 ------------------
bot_token = os.getenv("TG_BOT_TOKEN")
chat_id = os.getenv("TG_USER_ID")
symbol = "510880"  # 510880 红利 ETF（AkShare 代码）
etf_label = "红利 ETF"
rsi_period = 14  # 14 周
ma60_period = 60  # 60 周
ma120_period = 120  # 120 周

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

# ------------------ RSI 计算（Wilder） ------------------
def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
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


def _market_symbol(symbol: str) -> str:
    return f"sh{symbol}" if symbol.startswith(("5", "6", "9")) else f"sz{symbol}"


def fetch_tencent_weekly_qfq(symbol: str) -> pd.DataFrame:
    secid = _market_symbol(symbol)
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"param": f"{secid},week,,,1200,qfq"}
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    rows = (((data.get("data") or {}).get(secid) or {}).get("qfqweek")) or []
    if not rows:
        raise ValueError("腾讯 qfq 周线获取失败")

    raw = pd.DataFrame(rows)
    if raw.shape[1] < 3:
        raise ValueError("腾讯 qfq 周线字段异常")

    out = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(raw.iloc[:, 0], errors="coerce"),
            "open": pd.to_numeric(raw.iloc[:, 1], errors="coerce"),
            "close": pd.to_numeric(raw.iloc[:, 2], errors="coerce"),
        }
    )
    out = out.dropna(subset=["trade_date", "open", "close"]).sort_values("trade_date")
    return out.drop_duplicates("trade_date", keep="last").reset_index(drop=True)


def fetch_sina_daily(symbol: str) -> pd.DataFrame:
    df = ak.fund_etf_hist_sina(symbol=_sina_symbol(symbol))
    if df is None or df.empty:
        raise ValueError("新浪日线获取失败")
    return _normalize_ohlc(df, "date", "open", "close")


def daily_to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    w = daily.set_index("trade_date").sort_index()
    weekly = w.resample("W-FRI").agg({"open": "first", "close": "last"}).dropna(subset=["close"])
    return weekly.reset_index()


@lru_cache(maxsize=1)
def _a_share_trading_dates() -> frozenset:
    cal = ak.tool_trade_date_hist_sina()
    dates = pd.to_datetime(cal["trade_date"], errors="coerce").dt.date
    return frozenset(d for d in dates if d is not None and not pd.isna(d))


def _has_future_trading_day_this_week(today: pd.Timestamp) -> bool:
    if today.weekday() >= 5:
        return False

    dates = _a_share_trading_dates()
    end = (today + pd.Timedelta(days=4 - today.weekday())).date()
    probe = today.date() + pd.Timedelta(days=1)

    while probe <= end:
        if probe in dates:
            return True
        probe = probe + pd.Timedelta(days=1)
    return False


def filter_completed_weeks(df_weekly: pd.DataFrame) -> pd.DataFrame:
    if df_weekly is None or df_weekly.empty:
        raise ValueError("周线数据为空")

    out = df_weekly.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    out = out.sort_values("trade_date").reset_index(drop=True)

    today = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None).normalize()
    out = out[out["trade_date"] <= today].copy()

    if not out.empty:
        last_date = pd.Timestamp(out.iloc[-1]["trade_date"]).normalize()
        same_week = (
            last_date.isocalendar().year == today.isocalendar().year
            and last_date.isocalendar().week == today.isocalendar().week
        )
        if same_week and _has_future_trading_day_this_week(today):
            out = out.iloc[:-1].copy()

    if out.empty:
        raise ValueError("剔除未收盘周后无可用数据")
    return out.reset_index(drop=True)


def fetch_weekly_with_fallback(symbol: str):
    try:
        return fetch_tencent_weekly_qfq(symbol), "腾讯 qfq 周线"
    except Exception as e:
        print(f"腾讯周线获取失败，回退新浪日线重采样: {e}")
        daily = fetch_sina_daily(symbol)
        return daily_to_weekly(daily), "新浪日线重采样"


def fetch_spot_close(symbol: str, fallback_close: float) -> float:
    try:
        spot_df = ak.fund_etf_spot_em()
        row = spot_df[spot_df["代码"].astype(str) == symbol]
        if not row.empty:
            return float(row.iloc[0]["最新价"])
    except Exception as e:
        print(f"实时价获取失败，使用回退值: {e}")
    return float(fallback_close)


def prepare_weekly_indicators(df_weekly: pd.DataFrame) -> pd.DataFrame:
    out = df_weekly.copy()
    out["rsi"] = compute_rsi(out["close"], rsi_period)
    out["ma60"] = out["close"].rolling(ma60_period).mean()
    out["ma120"] = out["close"].rolling(ma120_period).mean()
    return out

# ------------------ 策略逻辑 ------------------
def _fmt_metric(value, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{float(value):.{digits}f}"


def format_key_metrics(row, spot_close: float) -> str:
    return (
        "📊 关键指标\n"
        f"当场股价：{_fmt_metric(spot_close)}\n"
        f"60 周均线：{_fmt_metric(row['ma60'])}\n"
        f"120 周均线：{_fmt_metric(row['ma120'])}\n"
        f"RSI(14周)：{_fmt_metric(row['rsi'])}"
    )


def format_push(body: str, row, spot_close: float) -> str:
    return f"{etf_label}\n{body}\n\n{format_key_metrics(row, spot_close)}"


def analyze_signal(df_weekly: pd.DataFrame, spot_close: float):
    w = prepare_weekly_indicators(filter_completed_weeks(df_weekly))
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

    latest_date = pd.Timestamp(latest["trade_date"]).strftime("%Y-%m-%d")
    print(
        f"已收盘最新周({latest_date}) -> "
        f"MA60={_fmt_metric(latest['ma60'], 3)}, "
        f"MA120={_fmt_metric(latest['ma120'], 3)}, "
        f"RSI14={_fmt_metric(latest['rsi'], 2)}"
    )
    if len(w) >= 2:
        prev = w.iloc[-2]
        prev_date = pd.Timestamp(prev["trade_date"]).strftime("%Y-%m-%d")
        print(
            f"上周({prev_date}) -> "
            f"MA60={_fmt_metric(prev['ma60'], 3)}, "
            f"MA120={_fmt_metric(prev['ma120'], 3)}, "
            f"RSI14={_fmt_metric(prev['rsi'], 2)}"
        )

    send_telegram(format_push(body, latest, spot_close))

# ------------------ 主程序 ------------------
def main():
    try:
        weekly, source = fetch_weekly_with_fallback(symbol)
        completed = filter_completed_weeks(weekly)
        spot_close = fetch_spot_close(symbol, fallback_close=float(completed.iloc[-1]["close"]))
        print(f"周线来源: {source}")
        analyze_signal(weekly, spot_close)
    except Exception as e:
        print(f"脚本异常: {e}")

if __name__ == "__main__":
    main()
