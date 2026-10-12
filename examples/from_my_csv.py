#!/usr/bin/env python
"""把「你自己的 CSV」接进来算因子：长表 → 面板 → 因子 → 质检。

    python examples/from_my_csv.py

真实使用时把 `read_my_long_table()` 换成读你自己的文件即可（保持列名一致）。
本示例先造一份假的 CSV 再读回来，保证你直接跑就能看到结果。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

import pathlib
import sys

import numpy as np
import pandas as pd

# 免安装即可运行：未 `pip install -e .` 时把仓库的 src/ 加进 sys.path（已安装则为无操作）
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from alpha101v import registry

FIELDS = ("open", "high", "low", "close", "volume", "amount")


def write_fake_csv(path: pathlib.Path, days: int = 150, names: int = 6, seed: int = 7) -> None:
    """造一份「长表」CSV：每行是一个 (date, code) 的行情。"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-03", periods=days, freq="B")
    codes = [f"{600000 + i}.SH" for i in range(names)]
    rows = []
    for code in codes:
        close = 20 * np.exp(np.cumsum(rng.normal(0, 0.02, days)))
        open_ = close * (1 + rng.normal(0, 0.004, days))
        high = np.maximum(close, open_) * (1 + abs(rng.normal(0, 0.004, days)))
        low = np.minimum(close, open_) * (1 - abs(rng.normal(0, 0.004, days)))
        volume = np.exp(rng.normal(np.log(1e5), 0.5, days))
        for i, date in enumerate(dates):
            rows.append({
                "date": date, "code": code, "open": open_[i], "high": high[i], "low": low[i],
                "close": close[i], "volume": volume[i], "amount": volume[i] * close[i],
            })
    pd.DataFrame(rows).to_csv(path, index=False)


def read_my_long_table(path: pathlib.Path) -> dict[str, pd.DataFrame]:
    """★ 换成你自己的读法。要求：长表、列名如 FIELDS、`date` 可解析、`code` 是标的。"""
    long = pd.read_csv(path, parse_dates=["date"]).sort_values(["date", "code"])
    panel: dict[str, pd.DataFrame] = {
        field: long.pivot(index="date", columns="code", values=field).sort_index() for field in FIELDS
    }
    panel["Open"] = panel.pop("open")                                   # 论文写 Open，其余小写
    panel["vwap"] = panel["amount"] / panel["volume"]                    # 没 vwap 时的近似
    panel["returns"] = panel["close"].pct_change(fill_method=None)
    return panel


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = pathlib.Path(tmp) / "my_prices.csv"
        write_fake_csv(csv_path)
        print(f"已造示例 CSV：{csv_path.name}（长表 date,code,{','.join(FIELDS)}）")
        panel = read_my_long_table(csv_path)

    close = panel["close"]
    print(f"面板：{close.shape[1]} 只 × {close.shape[0]} 个交易日 | 列示例 {list(close.columns[:3])}")

    for name in ("alpha101", "alpha4", "alpha5", "alpha41"):
        out = registry.run_factor(name, panel)
        finite = float(np.isfinite(out.to_numpy(dtype=float)).mean())
        print(f"  {name:<9} 覆盖率 {finite:6.1%} | 末行样例 {out.iloc[-1].round(4).to_dict()}")

    # 质检 1：时间截断一致性（PIT 金标准）——任何前视都会让它失败
    cut = 100
    full = registry.run_factor("alpha4", panel)
    truncated = registry.run_factor("alpha4", {k: (v.iloc[:cut] if v is not None and hasattr(v, "iloc") else v)
                                               for k, v in panel.items()})
    pd.testing.assert_frame_equal(truncated, full.iloc[:cut])
    print(f"\n✅ 时间截断一致性通过（前 {cut} 天与全样本逐点相同）——没有前视")

    # 质检 2：别把 NaN 当 0
    nan_ratio = float(np.isnan(full.to_numpy(dtype=float)).mean())
    print(f"ℹ️ alpha4 的 NaN 占比 {nan_ratio:.1%}：NaN 表示信息不足，下游**不要** fillna(0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
