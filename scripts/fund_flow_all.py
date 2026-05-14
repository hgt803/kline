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


def main():
    parser = argparse.ArgumentParser(description="查询全市场资金净流入（使用 AkShare）")
    parser.add_argument("--date", help="查询日期，格式 YYYY-MM-DD，默认今日",
                        default=datetime.date.today().isoformat())
    parser.add_argument("--out", help="保存 CSV 的路径（默认：fund_flow_all_<date>.csv）",
                        default=None)
    parser.add_argument("--summary-out", help="保存摘要 CSV 的路径（默认：fund_flow_summary_<date>.csv）",
                        default=None)
    args = parser.parse_args()

    try:
        import akshare as ak
    except Exception as e:
        print("未能导入 akshare。请先安装：pip install akshare")
        print("错误：", e)
        sys.exit(1)

    # 优先使用 akshare 的排行接口
    try:
        # 优先尝试同花顺（THS）接口：ak.stock_fund_flow_individual("即时")
        df_ths = None
        try:
            if hasattr(ak, "stock_fund_flow_individual"):
                print('调用 ak.stock_fund_flow_individual("即时") ...')
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
            # 优先使用 '净额' 列作为个股净流入，再回退到  流入-流出
            import pandas as _pd
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
            # 不再保存完整明细 CSV，仅保存/更新摘要文件
            # 生成并保存摘要
            try:
                import re
                import pandas as _pd

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

                net_sum = 0.0
                turnover_sum = 0.0
                if "净额" in df_ths.columns:
                    net_sum = df_ths["净额"].apply(parse_amount).sum()
                elif "流入资金" in df_ths.columns and "流出资金" in df_ths.columns:
                    net_sum = (df_ths["流入资金"].apply(parse_amount) - df_ths["流出资金"].apply(parse_amount)).sum()
                if "成交额" in df_ths.columns:
                    turnover_sum = df_ths["成交额"].apply(parse_amount).sum()

                # 转换为单位：亿（1e8），并保存摘要
                net_in_yi = net_sum / 1e8
                turnover_in_yi = turnover_sum / 1e8
                summary = _pd.DataFrame([
                    {"日期": args.date, "净流入（亿）": round(net_in_yi, 2), "成交额（亿）": round(turnover_in_yi, 2)}
                ])
                summary_out = args.summary_out if args.summary_out else f"fund_flow_summary_{args.date}.csv"
                # 读取已有摘要（若存在），更新或追加本日数据，然后按日期倒序保存
                try:
                    import os

                    if os.path.exists(summary_out):
                        prev = _pd.read_csv(summary_out, encoding="utf-8-sig")
                        # 保持列名为中文：'日期','净流入（亿）','成交额（亿）'
                        prev_dates = prev["日期"].astype(str)
                        # 若已存在当日记录，替换
                        prev = prev[prev["日期"] != args.date]
                        combined = _pd.concat([_pd.DataFrame([{"日期": args.date, "净流入（亿）": round(net_in_yi, 2), "成交额（亿）": round(turnover_in_yi, 2)}]), prev], ignore_index=True)
                    else:
                        combined = _pd.DataFrame([{"日期": args.date, "净流入（亿）": round(net_in_yi, 2), "成交额（亿）": round(turnover_in_yi, 2)}])
                    # 按日期倒序（最新在上）保存
                    combined["_dt"] = _pd.to_datetime(combined["日期"], errors="coerce")
                    combined = combined.sort_values(by="_dt", ascending=False).drop(columns=["_dt"])
                    combined.to_csv(summary_out, index=False, encoding="utf-8-sig")
                    print("已保存摘要 CSV（单位：亿）：", summary_out)
                    print(combined.to_string(index=False))
                except Exception as e_file:
                    print("保存或合并摘要失败：", e_file)
            except Exception as e_sum:
                print("生成或保存摘要失败：", e_sum)
            return

        # 若 THS 不可用，再尝试原来的 akshare 大盘资金排行接口
        if hasattr(ak, "stock_individual_fund_flow_rank"):
            print('调用 ak.stock_individual_fund_flow_rank("今日") ...')
            df_rank = ak.stock_individual_fund_flow_rank("今日")
            if df_rank is None or df_rank.empty:
                print("ak 接口返回空数据，尝试回退抓取。")
            else:
                print("成功获取排行数据，显示前 5 行：")
                print(df_rank.head().to_string())
                # 尝试找出主力净流入列并汇总
                main_col = None
                for c in df_rank.columns:
                    if "主力净流入" in str(c) and "净额" in str(c):
                        main_col = c
                        break
                if main_col:
                    import pandas as _pd

                    df_rank[main_col] = _pd.to_numeric(df_rank[main_col], errors="coerce").fillna(0)
                    total_main = df_rank[main_col].sum()
                    print(f"全市场 {main_col} 汇总: {total_main}")
                    # 不再保存完整明细 CSV，仅保存/更新摘要文件
                    # 生成并保存摘要（尽量从排行数据找净流入/成交额）
                    try:
                        def parse_simple_num(x: object) -> float:
                            try:
                                return float(x)
                            except Exception:
                                return 0.0

                        net_sum = df_rank[main_col].apply(parse_simple_num).sum()
                        turnover_cols = [c for c in df_rank.columns if "成交" in str(c) or "成交额" in str(c)]
                        turnover_sum = 0.0
                        if turnover_cols:
                            turnover_sum = df_rank[turnover_cols[0]].apply(parse_simple_num).sum()
                        # 转换为单位：亿（1e8），并保存摘要
                        net_in_yi = net_sum / 1e8
                        turnover_in_yi = turnover_sum / 1e8
                        summary = _pd.DataFrame([
                            {"日期": args.date, "净流入（亿）": round(net_in_yi, 2), "成交额（亿）": round(turnover_in_yi, 2)}
                        ])
                        summary_out = args.summary_out if args.summary_out else f"fund_flow_summary_{args.date}.csv"
                        summary.to_csv(summary_out, index=False, encoding="utf-8-sig")
                        print("已保存摘要 CSV（单位：亿）：", summary_out)
                        print(summary.to_string(index=False))
                    except Exception as e_sum:
                        print("生成或保存摘要失败：", e_sum)
                else:
                    print("未能在结果中定位到'主力净流入-净额'列，已输出前几行供参考。")
                return
    except Exception as e:
        print("调用 ak 接口时发生异常：", e)

    # 回退抓取：直接请求东方财富 push2 分页接口（带重试）
    try:
        print("使用回退抓取：请求东方财富 push2 接口（带重试与分页）...")
        import math
        import time
        import requests
        import pandas as _pd

        def fetch_market_fund_rank_today(retries: int = 3, timeout: int = 10) -> _pd.DataFrame:
            indicator_map = {
                "今日": [
                    "f62",
                    "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124",
                ]
            }
            url = "https://push2.eastmoney.com/api/qt/clist/get"
            params = {
                "fid": indicator_map["今日"][0],
                "po": "1",
                "pz": "100",
                "pn": "1",
                "np": "1",
                "fltt": "2",
                "invt": "2",
                "ut": "b2884a393a59ad64002292a3e90d46a5",
                "fs": "m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:7+f:!2,m:1+t:3+f:!2",
                "fields": indicator_map["今日"][1],
            }

            # 首次请求获取总数
            total = 0
            for attempt in range(retries):
                try:
                    r = requests.get(url, params=params, timeout=timeout)
                    r.raise_for_status()
                    data_json = r.json()
                    total = int(data_json["data"]["total"])
                    break
                except Exception as e:
                    if attempt == retries - 1:
                        raise
                    time.sleep(1 + attempt)

            total_page = math.ceil(total / 100) if total > 0 else 0
            temp_list = []
            for page in range(1, max(1, total_page) + 1):
                params.update({"pn": page})
                for attempt in range(retries):
                    try:
                        r = requests.get(url, params=params, timeout=timeout)
                        r.raise_for_status()
                        data_json = r.json()
                        inner = data_json.get("data", {}).get("diff", [])
                        temp_list.append(_pd.DataFrame(inner))
                        break
                    except Exception:
                        if attempt == retries - 1:
                            raise
                        time.sleep(1 + attempt)

            if not temp_list:
                return _pd.DataFrame()
            temp_df = _pd.concat(temp_list, ignore_index=True)
            temp_df.reset_index(inplace=True)
            temp_df["index"] = range(1, len(temp_df) + 1)
            return temp_df

        df_fallback = fetch_market_fund_rank_today()
        if df_fallback.empty:
            print("回退抓取未返回数据，请检查网络或稍后重试。")
            return
        print("回退接口获取到数据，显示前 5 行：")
        print(df_fallback.head().to_string())
        # 尝试找到主力净流入列并汇总
        candidate_cols = [c for c in df_fallback.columns if "主力净流入" in str(c) and "净额" in str(c)]
        if candidate_cols:
            c = candidate_cols[0]
            df_fallback[c] = _pd.to_numeric(df_fallback[c], errors="coerce").fillna(0)
            print(f"回退抓取汇总 {c}:", df_fallback[c].sum())
        else:
            print("未在回退结果中找到'主力净流入-净额'列，已输出前几行供参考。")
    except Exception as e:
        print("回退抓取失败：", e)


if __name__ == '__main__':
    main()
