#!/usr/bin/env python
"""真实 A 股面板冒烟（设计文档 §7.4 面板契约 + §10.2 数据源）。

做四件事，全部打印可核对的数字：

1. 从本地 MongoDB（``quantaxis``）取一段真实面板（价格 + 成交量额 + 市值），
   按 §7.4 计算 ``vwap = amount/(vol*100)`` 与 ``returns``，并接上**申万 as-of 行业**；
2. 跑面板契约校验（最小历史长度默认 250 交易日）；
3. 用 ``registry`` 跑 5 个试点因子，打印非 NaN 比例与数值范围（**不评估 IC**——
   设计文档 §6.7 明文禁止用统计显著性证明实现正确）；
4. 在真实数据上做两项**正确性**检查：``vwap ∈ [low, high]`` 的单位口径自洽率、
   以及 ``ind_neutralize`` 的**逐日行业内残差和 ≈ 0**（PIT 行业面板的真实端到端检验）。

用法::

    /home/yinxiuqu/anaconda3/envs/qa/bin/python tools/real_panel_smoke.py
    ... --n-codes 60 --start 2024-01-02 --end 2024-03-29 --min-history 0

⚠️ 只读数据源；不使用 QUANTAXIS。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from alpha101v import panel as panel_contract  # noqa: E402
from alpha101v import registry  # noqa: E402
from alpha101v.adapters.industry import load_sw_industry  # noqa: E402
from alpha101v.adapters.mongo import DEFAULT_URI, load_panel  # noqa: E402
from alpha101v.neutralize import ind_neutralize  # noqa: E402


def pick_codes(end: str, n_codes: int, seed: int, uri: str) -> list[str]:
    """从 ``stock_daily_basic`` 当日有市值的股票里随机取样（固定种子 ⇒ 可复现）。"""
    import pymongo

    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        coll = client["quantaxis"]["stock_daily_basic"]
        pool = sorted({str(doc["code"]) for doc in coll.find({"date": end}, {"code": 1})})
    finally:
        client.close()
    if not pool:
        raise SystemExit(f"{end} 在 stock_daily_basic 里没有数据，请换日期")
    rng = np.random.default_rng(seed)
    size = min(n_codes, len(pool))
    return sorted(rng.choice(pool, size=size, replace=False).tolist())


def main() -> int:
    parser = argparse.ArgumentParser(description="真实 A 股面板冒烟")
    parser.add_argument("--n-codes", type=int, default=120)
    parser.add_argument("--start", default="2023-01-03")
    parser.add_argument("--end", default="2024-06-28")
    parser.add_argument("--min-history", type=int, default=250, help="0 表示跳过最小历史长度校验")
    parser.add_argument("--level", default="L1", help="申万层级（L1/L2/L3）")
    parser.add_argument("--seed", type=int, default=20261009)
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--no-industry", action="store_true")
    args = parser.parse_args()

    print(f"■ 取样：{args.start} ~ {args.end}，n_codes={args.n_codes}，行业层级={args.level}")
    codes = pick_codes(args.end, args.n_codes, args.seed, args.uri)
    print(f"  代码数 {len(codes)}，示例 {codes[:6]}")

    industry = None
    panels = load_panel(codes, args.start, args.end, uri=args.uri)
    index, columns = panels["close"].index, panels["close"].columns
    print(f"  面板形状：{len(index)} 交易日 × {len(columns)} 只（{index[0].date()} ~ {index[-1].date()}）")

    if not args.no_industry:
        industry = load_sw_industry(index, columns, level=args.level)
        panels["ind"] = industry
        print(f"  行业覆盖率：{industry.attrs.get('coverage', float('nan')):.1%}（level={args.level}）")

    # ---- 1) 面板契约 ----
    min_history = args.min_history or None
    problems = panel_contract.validate_panel(panels, min_history=min_history)
    print("\n■ 面板契约校验：", "✅ 通过" if not problems else f"❌ {len(problems)} 项问题")
    for problem in problems:
        print(f"  - {problem}")

    # ---- 2) 单位口径自洽率（vwap 必须落在当日 [low, high] 内）----
    low, high, vwap = panels["low"], panels["high"], panels["vwap"]
    mask = vwap.notna() & low.notna() & high.notna()
    inside = ((vwap >= low) & (vwap <= high)) & mask
    ratio = float(inside.to_numpy().sum() / max(mask.to_numpy().sum(), 1))
    print(f"\n■ 单位口径：vwap ∈ [low, high] 自洽率 = {ratio:.4%}（有效格子 {int(mask.to_numpy().sum())}）")

    # ---- 3) 试点因子 ----
    print("\n■ 试点因子（真实数据；**不看 IC**，只看算得出/不产 inf/覆盖面）")
    print("| 因子 | 状态 | 非 NaN 比例 | 均值 | 标准差 | min | max | inf |")
    print("|---|---|---|---|---|---|---|---|")
    factor_series: dict[str, pd.DataFrame] = {}
    for name in sorted(registry.REGISTRY):
        out = registry.run_factor(name, panels)
        factor_series[name] = out
        values = out.to_numpy(dtype=float)
        finite = np.isfinite(values)
        inf_count = int(np.isinf(values).sum())
        ratio_nan = 1.0 - finite.sum() / values.size
        print(
            f"| `{name}` | {registry.REGISTRY[name].status} | {1 - ratio_nan:.2%} | "
            f"{np.nanmean(values):.4g} | {np.nanstd(values):.4g} | "
            f"{np.nanmin(values):.4g} | {np.nanmax(values):.4g} | {inf_count} |"
        )

    # ---- 4) 真实数据上的 ind_neutralize 正交性（PIT 行业面板）----
    failures: list[str] = []
    if industry is not None and "alpha4" in factor_series:
        resid = ind_neutralize(factor_series["alpha4"], industry)
        worst = 0.0
        for day in resid.index:                     # PIT：逐日用**当日**行业标签分组
            sums = resid.loc[day].groupby(industry.loc[day]).sum()
            if sums.size:
                worst = max(worst, float(np.nanmax(np.abs(sums.to_numpy()))))
        print(f"\n■ PIT 行业中性化（对 alpha4）：逐日行业内残差和的最大绝对值 = {worst:.3e}（应 ≈ 0）")
        if not (worst < 1e-9):
            failures.append(f"ind_neutralize 残差和未归零（{worst:.3e}）")

    if problems:
        failures.extend(problems)
    for name, out in factor_series.items():
        values = out.to_numpy(dtype=float)
        if np.isinf(values).any():
            failures.append(f"{name} 产生 ±inf")
        if np.isfinite(values).sum() == 0:
            failures.append(f"{name} 全为 NaN")
    if not (ratio > 0.99):
        failures.append(f"vwap 单位口径自洽率过低：{ratio:.2%}")

    print()
    if failures:
        print("❌ 冒烟失败：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("✅ 真实面板冒烟通过（合同 + 单位口径 + 因子可算 + PIT 中性化正交）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
