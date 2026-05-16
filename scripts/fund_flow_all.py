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
import pandas as _pd
import requests

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
    parser = argparse.ArgumentParser(description="查询全市场资金净流入（使用 AkShare）")
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

    try:
        import akshare as ak
    except Exception as e:
        print("未能导入 akshare。请先安装：pip install akshare")
        print("错误：", e)
        sys.exit(1)

    df_ths = None
    try:
        if hasattr(ak, "stock_fund_flow_individual"):
            df_ths = ak.stock_fund_flow_individual("即时")
        else:
            from akshare.stock_feature.stock_fund_flow import stock_fund_flow_individual
            df_ths = stock_fund_flow_individual("即时")
    except Exception as e_ths:
        print("THS 接口调用失败：", e_ths)

    if df_ths is not None and hasattr(df_ths, "empty") and not df_ths.empty:
        import re
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

        if "成交额" in df_ths.columns:
            df_ths["_turnover_parsed"] = df_ths["成交额"].apply(parse_amount)
            turnover_sum = df_ths["_turnover_parsed"].sum()
        else:
            turnover_sum = 0.0

        net_in_yi = net_sum / 1e8
        turnover_in_yi = turnover_sum / 1e8
        out_path = args.summary_out if args.summary_out else "fund_flow_summary.csv"
        combined = save_summary_file(out_path, date_str, net_in_yi, turnover_in_yi)

        print("已保存摘要 CSV（单位：亿）：", out_path)
        print(combined.to_string(index=False))

        # 默认只推送最新一行
        latest_row = combined.iloc[[0]]
        md_table = format_markdown_table(latest_row)
        content = f"💹 全市场资金流摘要（{date_str}）\n{md_table}"
        telegram_push(content)
    else:
        print("未能获取资金流数据，跳过推送。")

if __name__ == '__main__':
    main()