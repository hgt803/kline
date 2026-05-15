#!/usr/bin/env python3
"""
根据 fund_flow_summary.csv 中的每日净流入绘制 K 线图（A 股配色：涨红跌绿）。

用法:
  python scripts/fund_flow_kline.py
  python scripts/fund_flow_kline.py --input fund_flow_summary.csv --output fund_flow_kline.svg
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

RED, GREEN = "#e74c3c", "#2ecc71"


def _parse_dates(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().str.replace("/", "-", regex=False)
    try:
        return pd.to_datetime(s, format="mixed", errors="coerce")
    except (TypeError, ValueError):
        return pd.to_datetime(s, errors="coerce")


def load_summary(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"未找到数据文件: {path}")
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={"日期": str})
    if "净流入（亿）" not in df.columns:
        raise ValueError("CSV 需包含列：日期、净流入（亿）")
    df["_dt"] = _parse_dates(df["日期"])
    df = df.dropna(subset=["_dt"]).sort_values("_dt")
    df["净流入（亿）"] = pd.to_numeric(df["净流入（亿）"], errors="coerce")
    df = df.dropna(subset=["净流入（亿）"])
    if df.empty:
        raise ValueError("没有可用的净流入数据")
    return df


def build_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    close = df["净流入（亿）"].astype(float)
    open_ = close.shift(1).fillna(0.0)
    return pd.DataFrame(
        {
            "date": df["_dt"].dt.strftime("%Y-%m-%d"),
            "open": open_,
            "high": pd.concat([open_, close], axis=1).max(axis=1),
            "low": pd.concat([open_, close], axis=1).min(axis=1),
            "close": close,
        }
    )


def render_svg(ohlc: pd.DataFrame, title: str) -> str:
    width, height = 960, 480
    margin_l, margin_r, margin_t, margin_b = 72, 24, 48, 64
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b

    y_min = float(ohlc["low"].min())
    y_max = float(ohlc["high"].max())
    pad = max((y_max - y_min) * 0.08, 50) if y_max != y_min else 100
    y_min -= pad
    y_max += pad
    if y_min <= 0 <= y_max:
        pass
    elif y_max <= 0:
        y_max = pad * 0.1
    elif y_min >= 0:
        y_min = -pad * 0.1

    n = len(ohlc)
    slot = plot_w / max(n, 1)
    body_w = max(8, min(28, slot * 0.55))

    def y_px(v: float) -> float:
        return margin_t + plot_h * (1 - (v - y_min) / (y_max - y_min))

    def x_px(i: int) -> float:
        return margin_l + slot * (i + 0.5)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="#fafafa"/>',
        f'<text x="{width/2:.1f}" y="28" text-anchor="middle" font-size="16" '
        f'font-family="PingFang SC,Microsoft YaHei,sans-serif" fill="#222">{title}</text>',
    ]

    # grid & y labels
    for i in range(5):
        t = i / 4
        val = y_min + (y_max - y_min) * t
        y = y_px(val)
        parts.append(
            f'<line x1="{margin_l}" y1="{y:.1f}" x2="{width-margin_r}" y2="{y:.1f}" '
            f'stroke="#ddd" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{margin_l-8}" y="{y+4:.1f}" text-anchor="end" font-size="11" '
            f'font-family="sans-serif" fill="#666">{val:.0f}</text>'
        )

    # zero line
    if y_min < 0 < y_max:
        zy = y_px(0)
        parts.append(
            f'<line x1="{margin_l}" y1="{zy:.1f}" x2="{width-margin_r}" y2="{zy:.1f}" '
            f'stroke="#999" stroke-width="1" stroke-dasharray="4,4"/>'
        )

    for i, row in enumerate(ohlc.to_dict("records")):
        xi = x_px(i)
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        color = RED if c >= o else GREEN
        y_o, y_c, y_h, y_l = y_px(o), y_px(c), y_px(h), y_px(l)
        parts.append(
            f'<line x1="{xi:.1f}" y1="{y_h:.1f}" x2="{xi:.1f}" y2="{y_l:.1f}" '
            f'stroke="{color}" stroke-width="1.5"/>'
        )
        top = min(y_o, y_c)
        bh = max(abs(y_c - y_o), 2)
        parts.append(
            f'<rect x="{xi-body_w/2:.1f}" y="{top:.1f}" width="{body_w:.1f}" height="{bh:.1f}" '
            f'fill="{color}" stroke="{color}"/>'
        )
        parts.append(
            f'<text x="{xi:.1f}" y="{height-20}" text-anchor="middle" font-size="10" '
            f'font-family="sans-serif" fill="#444" transform="rotate(-25 {xi:.1f} {height-20})">'
            f'{row["date"]}</text>'
        )

    parts.append(
        f'<text x="{margin_l}" y="{height-8}" font-size="11" font-family="sans-serif" fill="#888">'
        f'单位：亿 · 涨红跌绿</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def save_chart(ohlc: pd.DataFrame, out_path: Path, title: str) -> None:
    svg = render_svg(ohlc, title)
    suffix = out_path.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg"):
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            from matplotlib.patches import Rectangle
        except ImportError:
            png_path = out_path.with_suffix(".svg")
            png_path.write_text(svg, encoding="utf-8")
            print(f"未安装 matplotlib，已改为输出 SVG：{png_path}", file=sys.stderr)
            return

        dates = pd.to_datetime(ohlc["date"])
        x = mdates.date2num(dates)
        width = min(0.6, 0.8 * (x[1] - x[0])) if len(x) > 1 else 0.6
        fig, ax = plt.subplots(figsize=(12, 6), dpi=120)
        for xi, row in zip(x, ohlc.itertuples(index=False)):
            o, h, l, c = row.open, row.high, row.low, row.close
            color = RED if c >= o else GREEN
            ax.plot([xi, xi], [l, h], color=color, linewidth=1.2)
            bb, bh = min(o, c), max(abs(c - o), 1e-9) or 0.01
            ax.add_patch(Rectangle((xi - width / 2, bb), width, bh or 0.01, facecolor=color, edgecolor=color))
        ax.axhline(0, color="#888", ls="--", lw=0.8, alpha=0.7)
        ax.set_title(title)
        ax.set_ylabel("净流入（亿）")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate(rotation=30)
        ax.grid(True, ls=":", alpha=0.4)
        fig.tight_layout()
        fig.savefig(out_path, bbox_inches="tight")
        plt.close(fig)
    else:
        out_path.write_text(svg, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="全市场净流入 K 线图（涨红跌绿）")
    parser.add_argument("--input", default="fund_flow_summary.csv", help="摘要 CSV")
    parser.add_argument("--output", default="fund_flow_kline.svg", help="输出图片/SVG")
    parser.add_argument("--title", default="全市场资金净流入 K 线（亿）")
    args = parser.parse_args()

    in_path, out_path = Path(args.input), Path(args.output)
    try:
        df = load_summary(in_path)
        ohlc = build_ohlc(df)
        save_chart(ohlc, out_path, args.title)
    except Exception as e:
        print("生成 K 线图失败：", e, file=sys.stderr)
        sys.exit(1)

    print(f"已生成 K 线图：{out_path.resolve()}（共 {len(ohlc)} 个交易日）")


if __name__ == "__main__":
    main()
