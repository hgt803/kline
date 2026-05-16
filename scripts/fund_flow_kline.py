#!/usr/bin/env python3
"""
全市场净流入 K 线图（涨红跌绿）+ 青龙 + Telegram 推送版本
"""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

import pandas as pd
import requests

RED, GREEN = "#e74c3c", "#2ecc71"


# =========================
# Telegram 推送（图片）
# =========================
_TELEGRAM_PHOTO_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def resolve_telegram_photo_path(path: Path) -> Path | None:
    """Telegram sendPhoto 仅支持位图，不支持 SVG。"""
    suffix = path.suffix.lower()
    if suffix in _TELEGRAM_PHOTO_SUFFIXES:
        return path if path.is_file() and path.stat().st_size > 0 else None
    if suffix == ".svg":
        png = path.with_suffix(".png")
        if png.is_file() and png.stat().st_size > 0:
            return png
    return None


def telegram_push_image(image_path: str, caption: str = ""):
    bot_token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_USER_ID")

    if not bot_token or not chat_id:
        print("未配置 TG_BOT_TOKEN / TG_USER_ID，跳过 Telegram 推送")
        return

    path = Path(image_path)
    photo_path = resolve_telegram_photo_path(path)
    if photo_path is None:
        if path.suffix.lower() == ".svg":
            print(
                "Telegram 不支持 SVG 图片推送，请安装 matplotlib 生成 PNG，"
                "或使用 --output fund_flow_kline.png"
            )
        else:
            print(f"Telegram 推送跳过：无效或缺失的图片 {path}")
        return

    mime = "image/jpeg" if photo_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"

    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        with open(photo_path, "rb") as f:
            files = {"photo": (photo_path.name, f, mime)}
            data = {"chat_id": chat_id, "caption": caption[:1024]}
            r = requests.post(url, data=data, files=files, timeout=20)

        if r.status_code == 200:
            print("Telegram 推送成功")
        else:
            print("Telegram 推送失败：", r.text)

    except Exception as e:
        print("Telegram 推送异常：", e)


# =========================
# 青龙 PUSH_KEY 推送（文本）
# =========================
def qinglong_push(title: str, content: str):
    push_key = os.getenv("PUSH_KEY")
    if not push_key:
        return

    try:
        url = f"https://sctapi.ftqq.com/{push_key}.send"
        requests.get(url, params={"title": title, "desp": content}, timeout=10)
        print("青龙 PUSH_KEY 推送成功")
    except Exception as e:
        print("青龙推送失败：", e)


# =========================
# CSV 处理
# =========================
def _parse_dates(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().str.replace("/", "-", regex=False)
    try:
        return pd.to_datetime(s, format="mixed", errors="coerce")
    except Exception:
        return pd.to_datetime(s, errors="coerce")


def load_summary(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"未找到数据文件: {path}")

    df = pd.read_csv(path, encoding="utf-8-sig", dtype={"日期": str})
    df["_dt"] = _parse_dates(df["日期"])
    df = df.dropna(subset=["_dt"]).sort_values("_dt")

    df["净流入（亿）"] = pd.to_numeric(df["净流入（亿）"], errors="coerce")
    df = df.dropna(subset=["净流入（亿）"])

    return df


def build_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    daily = df["净流入（亿）"].astype(float)
    close = daily.cumsum()
    open_ = close.shift(1).fillna(0.0)

    return pd.DataFrame({
        "date": df["_dt"].dt.strftime("%Y-%m-%d"),
        "open": open_,
        "high": pd.concat([open_, close], axis=1).max(axis=1),
        "low": pd.concat([open_, close], axis=1).min(axis=1),
        "close": close,
    })


# =========================
# SVG 绘图（保持你原逻辑）
# =========================
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

    n = len(ohlc)
    slot = plot_w / max(n, 1)
    body_w = max(8, min(28, slot * 0.55))

    def y(v): return margin_t + plot_h * (1 - (v - y_min) / (y_max - y_min))
    def x(i): return margin_l + slot * (i + 0.5)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="#fafafa"/>',
        f'<text x="{width/2}" y="28" text-anchor="middle" font-size="16">{title}</text>'
    ]

    for i, row in enumerate(ohlc.to_dict("records")):
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        color = RED if c >= o else GREEN

        xi = x(i)
        svg.append(
            f'<line x1="{xi}" y1="{y(h)}" x2="{xi}" y2="{y(l)}" stroke="{color}"/>'
        )

        svg.append(
            f'<rect x="{xi-body_w/2}" y="{min(y(o), y(c))}" width="{body_w}" height="{abs(y(c)-y(o)) or 2}" fill="{color}"/>'
        )

    svg.append("</svg>")
    return "\n".join(svg)


def save_chart(ohlc: pd.DataFrame, out_path: Path, title: str):
    svg = render_svg(ohlc, title)

    if out_path.suffix.lower() == ".svg":
        out_path.write_text(svg, encoding="utf-8")
        return

    # PNG fallback
    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle

        fig, ax = plt.subplots(figsize=(12, 6))

        for i, row in enumerate(ohlc.itertuples()):
            color = RED if row.close >= row.open else GREEN
            ax.vlines(i, row.low, row.high, color=color)
            ax.add_patch(Rectangle((i-0.3, min(row.open, row.close)),
                                   0.6,
                                   abs(row.close-row.open) or 0.01,
                                   color=color))

        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        plt.savefig(out_path, bbox_inches="tight")
        plt.close()

    except Exception:
        svg_path = out_path.with_suffix(".svg")
        svg_path.write_text(svg, encoding="utf-8")
        print(f"无 matplotlib，已输出 SVG：{svg_path}")


# =========================
# main
# =========================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="fund_flow_summary.csv")
    parser.add_argument("--output", default="fund_flow_kline.png")
    parser.add_argument("--title", default="大盘累计资金 K 线（亿）")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    try:
        df = load_summary(in_path)
        ohlc = build_ohlc(df)
        save_chart(ohlc, out_path, args.title)

        # Telegram 仅支持位图；若主输出为 SVG，额外生成 PNG 用于推送
        push_path = out_path
        if out_path.suffix.lower() == ".svg":
            png_path = out_path.with_suffix(".png")
            save_chart(ohlc, png_path, args.title)
            if png_path.exists():
                push_path = png_path

        msg = f"📊 {args.title}\n已生成：{out_path.name}\n数据：{len(ohlc)} 天"

        # 1️⃣ Telegram 图片推送（主推）
        telegram_push_image(str(push_path), caption=msg)

        # 2️⃣ 青龙 PUSH_KEY 文本推送（备份）
        qinglong_push("资金K线生成完成", msg)

        print("全部推送完成")

    except Exception as e:
        print("生成失败：", e)
        sys.exit(1)


if __name__ == "__main__":
    main()