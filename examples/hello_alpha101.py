#!/usr/bin/env python
"""最小可跑示例：合成面板 → 算 101 个因子 → 打印结果表。

不需要数据库、不需要网络、不需要任何配置：

    python examples/hello_alpha101.py

它顺带演示了三件在使用中必须知道的事：
1. 面板契约（DatetimeIndex + 列=标的代码 + 九个字段 + 三个行业层级）；
2. 缺字段会**明确报错**（这里故意先少给字段，再补齐）；
3. 每个因子的输出是 DataFrame（与面板同形），NaN 表示「信息不足」——**不要 fillna(0)**。
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

# 免安装即可运行：未 `pip install -e .` 时把仓库的 src/ 加进 sys.path（已安装则为无操作）
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from alpha101v import ALL_FACTOR_NAMES, registry

DAYS, NAMES, SEED = 120, 8, 20261012


def make_panel(days: int = DAYS, names: int = NAMES, seed: int = SEED) -> dict[str, object]:
    """一份确定性的合成面板（8 只股票 × 120 个交易日，够跑短窗口因子）。"""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2021-01-04", periods=days, freq="B")
    columns = [f"S{i}" for i in range(names)]
    shape = (days, names)

    close = pd.DataFrame(30 * np.exp(np.cumsum(rng.normal(0, 0.02, shape), axis=0)), index=index, columns=columns)
    open_ = close * (1 + rng.normal(0, 0.004, shape))
    high = np.maximum(close, open_) * (1 + abs(rng.normal(0, 0.004, shape)))
    low = np.minimum(close, open_) * (1 - abs(rng.normal(0, 0.004, shape)))
    volume = pd.DataFrame(np.exp(rng.normal(np.log(2e5), 0.6, shape)), index=index, columns=columns)
    amount = volume * close
    return {
        "close": close,
        "Open": pd.DataFrame(open_, index=index, columns=columns),
        "high": pd.DataFrame(high, index=index, columns=columns),
        "low": pd.DataFrame(low, index=index, columns=columns),
        "volume": volume,
        "amount": amount,
        "vwap": amount / volume,
        "returns": close.pct_change(fill_method=None),      # 注意 fill_method=None
        "cap": pd.DataFrame(abs(rng.normal(1e6, 2e5, shape)) + 1, index=index, columns=columns),
        "ind_sector": pd.Series(["A"] * 4 + ["B"] * 4, index=columns),
        "ind_industry": pd.Series(["A1", "A1", "A2", "A2", "B1", "B1", "B2", "B2"], index=columns),
        "ind_subindustry": pd.Series([f"G{i % 4}" for i in range(names)], index=columns),
    }


def main() -> int:
    panel = make_panel()
    print(f"面板：{panel['close'].shape[1]} 只 × {panel['close'].shape[0]} 个交易日（合成数据）")

    # 1) 单个因子
    out = registry.run_factor("alpha101", panel)
    print(f"\nalpha101 输出形状 {out.shape}（与面板同形）")
    print(out.iloc[:3, :3].round(4).to_string())

    # 2) 缺字段会明确报错（这里演示：只给 close）
    try:
        registry.run_factor("alpha5", {"close": panel["close"]})
    except KeyError as exc:
        print(f"\n只给 close 时算 alpha5 → 明确报错：{str(exc)[:78]}…")

    # 3) 全部 101 个
    print()
    rows = []
    for name in ALL_FACTOR_NAMES:
        values = registry.run_factor(name, panel).to_numpy(dtype=float)
        finite = int(np.isfinite(values).sum())
        rows.append((name, finite, int(np.isinf(values).sum())))
    table = pd.DataFrame(rows, columns=["factor", "finite_cells", "inf_cells"])
    runs = int((table["finite_cells"] > 0).sum())
    print(f"跑通 {runs}/101 个因子；零 ±inf：{bool((table['inf_cells'] == 0).all())}")
    empty = table[table["finite_cells"] == 0]["factor"].tolist()
    if empty:
        print(f"其中 {len(empty)} 个在 120 天里必然全 NaN（窗口不够，不是 bug）：{'、'.join(empty[:12])}")
        print("  ↳ 把本文件顶部的 DAYS 改成 320，它们就会有值（最长窗口是 250 个交易日）")
    print("\n有限格数最少的 5 个：")
    print(table.nsmallest(5, "finite_cells").to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
