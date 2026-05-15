#!/usr/bin/env python3
"""
查询并显示“全市场汇总的资金净流入”的脚本（AkShare 优先，回退到东方财富 API）。

用法:
  python scripts/fund_flow_all.py [--date YYYY-MM-DD]

功能说明：
  1) 尝试调用 akshare 中的 `stock_individual_fund_flow_rank("今日")` 接口并计算汇总。
  2) 若 akshare 接口不可用或网络错误，则回退到直接请求东方财富的 push2 接口，支持分页与重试。

注意：本脚本仅用于研究与学习目的，抓取目标网站数据请遵守网站使用条款。
"""
from __future__ import annotations

import argparse
import datetime
import sys
import pandas as _pd


def main():
    parser = argparse.ArgumentParser(description="查询全市场资金净流入（使用 AkShare）")
    parser.add_argument("--date", help="查询日期，格式 YYYY-MM-DD，默认今日",
                        default=datetime.date.today().isoformat())
    parser.add_argument("--out", help="保存 CSV 的路径（默认：fund_flow_all_<date>.csv）",
                        default=None)
    parser.add_argument("--summary-out", help="保存摘要 CSV 的路径（默认：fund_flow_summary.csv）",
                        default=None)
    args = parser.parse_args()

    def save_summary_file(path: str, date_str: str, net_in_yi: float, turnover_in_yi: float) -> _pd.DataFrame:
        import os

        if path is None:
            path = "fund_flow_summary.csv"
        if os.path.exists(path):
            prev = _pd.read_csv(path, encoding="utf-8-sig")
            prev = prev[prev["日期"] != date_str]
            combined = _pd.concat([_pd.DataFrame([{"日期": date_str, "净流入（亿）": round(net_in_yi, 2), "成交额（亿）": round(turnover_in_yi, 2)}]), prev], ignore_index=True)
        else:
            combined = _pd.DataFrame([{"日期": date_str, "净流入（亿）": round(net_in_yi, 2), "成交额（亿）": round(turnover_in_yi, 2)}])
        combined["_dt"] = _pd.to_datetime(combined["日期"], errors="coerce")
        combined = combined.sort_values(by="_dt", ascending=False).drop(columns=["_dt"])
        combined.to_csv(path, index=False, encoding="utf-8-sig")
        return combined

    try:
        import akshare as ak
    except Exception as e:
        print("未能导入 akshare。请先安装：pip install akshare")
        print("错误：", e)
        sys.exit(1)

    # 仅查询当天数据（用户要求精简）
    date_str = args.date
    df_ths = None
    try:
        if hasattr(ak, "stock_fund_flow_individual"):
            print(f'调用 ak.stock_fund_flow_individual("即时") ...')
            df_ths = ak.stock_fund_flow_individual("即时")
        else:
            from akshare.stock_feature.stock_fund_flow import stock_fund_flow_individual
            print('调用 akshare.stock_feature.stock_fund_flow.stock_fund_flow_individual("即时") ...')
            df_ths = stock_fund_flow_individual("即时")
    except Exception as e_ths:
        print("THS 接口调用失败：", e_ths)

    if df_ths is not None and hasattr(df_ths, "empty") and not df_ths.empty:
        print("成功获取 THS 个股资金流数据，显示前 5 行：")
        print(df_ths.head().to_string())
        import re

        def parse_amount_local(x: object) -> float:
            if x is None or (_pd.isna(x)):
                return 0.0
            s = str(x).strip()
            if s == "" or s == "--":
                return 0.0
            s = s.replace(",", "")
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

        net_sum = 0.0
        turnover_sum = 0.0
        if "净额" in df_ths.columns:
            net_sum = df_ths["净额"].apply(parse_amount_local).sum()
            print("全市场 个股净额汇总（元）:", net_sum)
        elif "流入资金" in df_ths.columns and "流出资金" in df_ths.columns:
            net_sum = (df_ths["流入资金"].apply(parse_amount_local) - df_ths["流出资金"].apply(parse_amount_local)).sum()
            print("全市场 (流入 - 流出) 汇总（元）:", net_sum)
        if "成交额" in df_ths.columns:
            turnover_sum = df_ths["成交额"].apply(parse_amount_local).sum()
            print("全市场 成交额汇总（元）:", turnover_sum)
        else:
            print("THS 结果中未找到'净额'或'流入资金/流出资金'列，已输出前几行供参考。")

        # 解析并保存摘要
        try:
            def parse_amount(x: object) -> float:
                if x is None or (_pd.isna(x)):
                    return 0.0
                s = str(x).strip()
                if s == "" or s == "--":
                    return 0.0
                s = s.replace(",", "")
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
            if "成交额" in df_ths.columns:
                df_ths["_turnover_parsed"] = df_ths["成交额"].apply(parse_amount)
                turnover_sum = df_ths["_turnover_parsed"].sum()

            # variants and selection (same as before)
            def code_prefix(s: object) -> str:
                try:
                    return str(s).strip()
                except Exception:
                    return ""

            if "股票代码" in df_ths.columns:
                df_ths["_code"] = df_ths["股票代码"].apply(code_prefix)
            else:
                df_ths["_code"] = ""

            variants = {}
            variants["all"] = df_ths["_net_parsed"].sum()
            flows_in = df_ths[df_ths["_net_parsed"] > 0]["_net_parsed"].sum()
            flows_out = -df_ths[df_ths["_net_parsed"] < 0]["_net_parsed"].sum()
            print(f"流入合计（元）: {flows_in} -> {flows_in/1e8:.2f} 亿")
            print(f"流出合计（元）: {flows_out} -> {flows_out/1e8:.2f} 亿")
            variants["exclude_688"] = df_ths[df_ths["_code"].str.startswith("688") == False]["_net_parsed"].sum()
            variants["exclude_300_688"] = df_ths[(df_ths["_code"].str.startswith("300") == False) & (df_ths["_code"].str.startswith("688") == False)]["_net_parsed"].sum()
            variants["sh_only"] = df_ths[df_ths["_code"].str.startswith("6")]["_net_parsed"].sum()
            variants["sz_only"] = df_ths[(df_ths["_code"].str.startswith("0") & (df_ths["_code"].str.startswith("300") == False))]["_net_parsed"].sum()
            if "_turnover_parsed" in df_ths.columns:
                for n in (50, 100, 300, 500):
                    if len(df_ths) >= n:
                        topn = df_ths.sort_values(by="_turnover_parsed", ascending=False).head(n)
                        variants[f"top{n}_by_turn"] = topn["_net_parsed"].sum()

            print("各口径净流入（元）：")
            for k, v in variants.items():
                print(f"  {k}: {v} 元 -> {v/1e8:.2f} 亿")

            # choose and save
            net_in_yi = net_sum / 1e8
            turnover_in_yi = turnover_sum / 1e8
            out_path = args.summary_out if args.summary_out else "fund_flow_summary.csv"
            combined = save_summary_file(out_path, date_str, net_in_yi, turnover_in_yi)
            print("已保存摘要 CSV（单位：亿）：", out_path)
            print(combined.to_string(index=False))
        except Exception as e_sum:
            print("生成或保存摘要失败：", e_sum)

    # 脚本只查询并保存当天数据（无需多日循环）


if __name__ == '__main__':
    main()
