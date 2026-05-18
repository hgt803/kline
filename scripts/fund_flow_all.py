#!/usr/bin/env python3
"""
查询全市场汇总资金净流入，并通过 Telegram 推送最新一日摘要。

特点：
- 默认只推送最新一天数据到 Telegram，历史 CSV 完整保存。
- 表格在 Telegram 上整齐显示。
"""

from __future__ import annotations
import argparse
import datetime
import sys
import os
import re
import json
import subprocess
from functools import lru_cache
import pandas as _pd
import requests


@lru_cache(maxsize=1)
def _a_share_trading_dates() -> frozenset[datetime.date]:
    import akshare as ak

    df = ak.tool_trade_date_hist_sina()
    dates = _pd.to_datetime(df["trade_date"], errors="coerce").dt.date
    return frozenset(d for d in dates if d is not None and not _pd.isna(d))


def is_a_share_trading_day(d: datetime.date) -> bool:
    return d in _a_share_trading_dates()


def _tencent_parse_quote_line(line: str) -> list[str] | None:
    line = line.strip().rstrip(";")
    if "=\"" not in line:
        return None
    try:
        payload = line.split("=\"", 1)[1].rsplit("\"", 1)[0]
    except Exception:
        return None
    arr = payload.split("~")
    return arr if arr else None


def fetch_tencent_hs_turnover_in_yi() -> float:
    """腾讯接口获取沪深两市成交额（单位：亿）。"""
    url = "https://qt.gtimg.cn/q=sh000001,sz399001"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://stockapp.finance.qq.com/",
    }
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()

    lines = [x for x in resp.text.splitlines() if x.strip()]
    amounts_wanyuan: list[float] = []
    for line in lines:
        arr = _tencent_parse_quote_line(line)
        # 腾讯字段位: 37 为成交额(万元)
        if arr and len(arr) > 37:
            try:
                amounts_wanyuan.append(float(arr[37]))
            except Exception:
                pass

    if len(amounts_wanyuan) < 2:
        raise ValueError("腾讯接口未返回完整沪深成交额")

    total_yuan = sum(amounts_wanyuan) * 1e4
    return total_yuan / 1e8


def fetch_eastmoney_main_net_in_yi(date_str: str) -> float:
    """东方财富大盘资金流接口获取指定日期主力净流入（单位：亿）。"""
    base_url = (
        "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        "?lmt=0&klt=101&secid=1.000001&secid2=0.399001"
        "&fields1=f1,f2,f3,f7"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
        "&ut=b2884a393a59ad64002292a3e90d46a5"
    )
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://data.eastmoney.com/zjlx/dpzjlx.html",
        "Accept": "application/json,text/plain,*/*",
    }

    payload = None
    try:
        resp = requests.get(base_url, headers=headers, timeout=12)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        try:
            raw = subprocess.check_output(["curl", "-sL", base_url], text=True, timeout=15)
            payload = json.loads(raw)
        except Exception as e:
            raise RuntimeError(f"东方财富接口不可用: {e}")

    klines = (((payload or {}).get("data") or {}).get("klines")) or []
    if not klines:
        raise ValueError("东方财富接口未返回 kline 数据")

    for row in klines:
        if not row.startswith(f"{date_str},"):
            continue
        parts = row.split(",")
        if len(parts) < 2:
            break
        return float(parts[1]) / 1e8

    raise ValueError(f"东方财富未找到 {date_str} 的主力净流入数据")

def telegram_push(message: str):
    bot_token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_USER_ID")
    if not bot_token or not chat_id:
        print("未配置 Telegram 推送环境变量 TG_BOT_TOKEN 或 TG_USER_ID")
        return
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        r = requests.post(url, data=data, timeout=10)
        if r.status_code == 200:
            print("Telegram 推送成功")
        else:
            print("Telegram 推送失败:", r.text)
    except Exception as e:
        print("Telegram 推送异常:", e)

def format_markdown_table(df: _pd.DataFrame) -> str:
    """将 DataFrame 格式化为 Telegram Markdown 表格"""
    headers = df.columns.tolist()
    rows = []
    for _, row in df.iterrows():
        r = []
        for col in headers:
            val = row[col]
            if isinstance(val, (int, float)):
                r.append(f"{val:>8.2f}")
            else:
                r.append(f"{str(val):<10}")
        rows.append(r)
    col_widths = [max(len(str(row[i])) for row in [headers]+rows) for i in range(len(headers))]
    header_line = " | ".join(f"{h:<{col_widths[i]}}" for i, h in enumerate(headers))
    separator_line = "-|-".join("-"*w for w in col_widths)
    row_lines = [" | ".join(f"{r[i]:<{col_widths[i]}}" for i in range(len(r))) for r in rows]
    table = "\n".join([header_line, separator_line]+row_lines)
    return f"```\n{table}\n```"

def main():
    parser = argparse.ArgumentParser(description="查询全市场资金净流入（净流入: 东方财富优先, 成交额: 腾讯）")
    parser.add_argument("--date", help="查询日期，格式 YYYY-MM-DD，默认今日",
                        default=datetime.date.today().isoformat())
    parser.add_argument("--summary-out", help="保存摘要 CSV 的路径（默认：fund_flow_summary.csv）",
                        default=None)
    args = parser.parse_args()

    date_str = args.date

    def _parse_dates(series) -> _pd.Series:
        s = series.astype(str).str.strip().str.replace("/", "-", regex=False)
        try:
            return _pd.to_datetime(s, format="mixed", errors="coerce")
        except (TypeError, ValueError):
            return _pd.to_datetime(s, errors="coerce")

    def save_summary_file(path: str, date_str: str, net_in_yi: float, turnover_in_yi: float) -> _pd.DataFrame:
        if path is None:
            path = "fund_flow_summary.csv"

        date_parsed = _parse_dates(_pd.Series([date_str])).iloc[0]
        date_iso = date_parsed.strftime("%Y-%m-%d") if not _pd.isna(date_parsed) else date_str
        new_row = {
            "日期": date_iso,
            "净流入（亿）": round(net_in_yi, 2),
            "成交额（亿）": round(turnover_in_yi, 2),
        }

        if os.path.exists(path):
            prev = _pd.read_csv(path, encoding="utf-8-sig", dtype={"日期": str})
            prev["_dt"] = _parse_dates(prev["日期"])
            if not _pd.isna(date_parsed):
                prev = prev[prev["_dt"].dt.normalize() != date_parsed.normalize()]
            else:
                prev = prev[prev["日期"] != date_str]
            prev = prev.drop(columns=["_dt"], errors="ignore")
            combined = _pd.concat([_pd.DataFrame([new_row]), prev], ignore_index=True)
        else:
            combined = _pd.DataFrame([new_row])

        combined["_dt"] = _parse_dates(combined["日期"])
        combined["日期"] = combined["_dt"].dt.strftime("%Y-%m-%d")
        combined = combined.sort_values(by="_dt", ascending=False)
        combined = combined.drop_duplicates(subset=["_dt"], keep="first")
        combined = combined.drop(columns=["_dt"])
        combined.to_csv(path, index=False, encoding="utf-8-sig")
        return combined

    def load_latest_summary_row(path: str) -> _pd.DataFrame | None:
        if path is None:
            path = "fund_flow_summary.csv"
        if not os.path.exists(path):
            return None
        df = _pd.read_csv(path, encoding="utf-8-sig", dtype={"日期": str})
        if df.empty:
            return None
        df["_dt"] = _parse_dates(df["日期"])
        df = df.dropna(subset=["_dt"]).sort_values("_dt", ascending=False)
        if df.empty:
            return None
        return df.drop(columns=["_dt"]).iloc[[0]]

    try:
        import akshare as ak
    except Exception as e:
        print("未能导入 akshare。请先安装：pip install akshare")
        print("错误：", e)
        sys.exit(1)

    net_in_yi = None
    turnover_in_yi = None
    try:
        net_in_yi = fetch_eastmoney_main_net_in_yi(date_str)
        print(f"东方财富净流入获取成功：{net_in_yi:.2f}亿")
    except Exception as e:
        print("东方财富净流入获取失败，回退 AkShare 个股聚合：", e)

    df_ths = None
    if net_in_yi is None:
        try:
            if hasattr(ak, "stock_fund_flow_individual"):
                df_ths = ak.stock_fund_flow_individual("即时")
            else:
                from akshare.stock_feature.stock_fund_flow import stock_fund_flow_individual
                df_ths = stock_fund_flow_individual("即时")
        except Exception as e_ths:
            print("THS 接口调用失败：", e_ths)

    if net_in_yi is None and df_ths is not None and hasattr(df_ths, "empty") and not df_ths.empty:
        def parse_amount(x: object) -> float:
            if x is None or (_pd.isna(x)):
                return 0.0
            s = str(x).strip().replace(",", "")
            neg = False
            if s.startswith("-"):
                neg = True
                s = s[1:]
            mul = 1.0
            if s.endswith("万"):
                mul = 1e4
                s = s[:-1]
            elif s.endswith("亿"):
                mul = 1e8
                s = s[:-1]
            m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
            val = float(m.group()) if m else 0.0
            return (-1.0 if neg else 1.0) * val * mul

        if "净额" in df_ths.columns:
            df_ths["_net_parsed"] = df_ths["净额"].apply(parse_amount)
            net_sum = df_ths["_net_parsed"].sum()
        elif "流入资金" in df_ths.columns and "流出资金" in df_ths.columns:
            df_ths["_in_parsed"] = df_ths["流入资金"].apply(parse_amount)
            df_ths["_out_parsed"] = df_ths["流出资金"].apply(parse_amount)
            df_ths["_net_parsed"] = df_ths["_in_parsed"] - df_ths["_out_parsed"]
            net_sum = df_ths["_net_parsed"].sum()
        else:
            net_sum = 0.0

        net_in_yi = net_sum / 1e8

    if turnover_in_yi is None:
        turnover_in_yi = fetch_tencent_hs_turnover_in_yi()

    if net_in_yi is not None:

        date_parsed = _parse_dates(_pd.Series([date_str])).iloc[0]
        if _pd.isna(date_parsed):
            print(f"日期格式无效（{date_str}），跳过 CSV 写入与推送。")
            return

        record_date = date_parsed.date()
        date_iso = record_date.isoformat()
        out_path = args.summary_out if args.summary_out else "fund_flow_summary.csv"

        if is_a_share_trading_day(record_date):
            combined = save_summary_file(out_path, date_str, net_in_yi, turnover_in_yi)
            print("已保存摘要 CSV（单位：亿）：", out_path)
            print(combined.to_string(index=False))
        else:
            print(f"{date_iso} 非 A 股交易日，跳过 CSV 写入。")

        latest_row = load_latest_summary_row(out_path)
        if latest_row is None:
            print("CSV 无可用记录，跳过 Telegram 推送。")
            return

        push_date = latest_row.iloc[0]["日期"]
        print("Telegram 将推送 CSV 最新一条：")
        print(latest_row.to_string(index=False))

        md_table = format_markdown_table(latest_row)
        content = f"💹 全市场资金流摘要（{push_date}）\n{md_table}"
        telegram_push(content)
    else:
        print("未能获取资金流数据，跳过推送。")

if __name__ == '__main__':
    main()
