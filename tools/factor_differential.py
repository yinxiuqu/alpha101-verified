#!/usr/bin/env python
"""因子级差分对拍（M4）：本库 101 因子 vs **vnpy 的 82 条表达式**（设计文档 §6.4 的 L3）。

对拍范围（设计文档 §4.3.1 的结论**已实地复核**）
------------------------------------------------
``.vnpy-ref/.../datasets/alpha_101.py`` 里有 **82 条未注释**的 `add_feature`，
缺 **19 个** = 18 个含 ``IndNeutralize`` 的因子（48/58/59/63/67/69/70/76/79/80/82/87/89/90/91/93/97/100）
+ ``alpha56``（无 ``cap``）。这 19 个**结构上无法差分**，只能靠 L2 规范对照 + L4 不变量。

语义归一化（§6.4 第一步，**默认全开**，每项都有实测依据）
--------------------------------------------------------
============================ ==============================================
``rank 归一化``              本库默认官方 ``zero_to_one``（``(名次−1)/(n−1) ∈ [0,1]``）；
                             vnpy = ``one_over_n``（``名次/n``）⇒ 对拍时切到 ``one_over_n``
``rank 并列``                vnpy ``cs_rank`` = ``method="min"``（本库默认 average）
``decay_linear 方向``        vnpy 取「最老权重最大」（本库默认最新最大）
``decay_linear 缺失``        本库默认官方**稀疏模式**（窗口内 NaN 当 0）；对拍时切 ``dense=True``
                             （严格整窗）以避免与 vnpy 各异的 NaN 处理混在一起
``stddev ddof``              vnpy ``ts_std`` = ``ddof=0``（本库默认 1）
``adv{d} 口径``              vnpy 用 ``ts_mean(volume, d)``；本库 ``_adv(amount, d)``
                             ⇒ 对拍时把面板 ``amount`` 喂成 ``volume``
``非整数窗口``               论文规定 ``floor(d)``；vnpy 用**四舍五入**（实测其注释里的
                             表达式：7.89291→8、2.72412→3、4.79344→5）⇒ 对拍时改为 round
``argmax 基准``              本库默认 = BRAIN 官方 `days_ago`（今天=0）；vnpy = `arg_max()+1`
                             （自窗口起点 1-based）⇒ 对拍时切到 `window_start`
``中缀 `^` 的口径``           本库默认 = BRAIN `power`；vnpy 的 `pow1/pow2` 是**保号幂**
                             ⇒ 对拍时把 `_pow` 换成 `signedpower(preserve_sign=True)`
``预热期``                   本库严格 NaN、vnpy 多处 ``min_samples=1``/``fill_null(0)``
                             ⇒ **只比较两侧都有限的格子**，并单独报告覆盖率
============================ ==============================================

已知表达式差异（vnpy 自己标注 + 本次实测）
------------------------------------------
* ``alpha21``：论文 ``(volume/adv20) >= 1`` → vnpy 实现为 ``> 1``；
* ``alpha24``：论文 ``<= 0.05`` → vnpy 实现为 ``< 0.05``；
* ``quesval``/``pow2``/``less`` 的 NaN 处理：vnpy 取 ``otherwise``/``fill_null(0)``/null 传播，
  本库按「未知 ⇒ NaN」或 fmin/fmax（见 ``docs/operators.md`` §3.12）⇒ 体现在覆盖率差异上。

用法::

    python tools/factor_differential.py                 # 对齐后对拍（默认）
    python tools/factor_differential.py --no-align       # 看「默认口径」下的差距有多大
    python tools/factor_differential.py --alpha 21       # 单因子排查（附两侧统计）
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import functools
import pathlib
import re
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
REF_DIR = ROOT / ".vnpy-ref"

# 作为脚本直接运行时没有 conftest.py 帮忙，显式把 src 布局加进 sys.path
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
DATASET = REF_DIR / "vnpy/alpha/dataset/datasets/alpha_101.py"
RETURNS_EXPR = "(close / ts_delay(close, 1) - 1)"
RTOL, ATOL = 1e-8, 1e-10

#: vnpy 无法对拍的 19 个因子（18 个 IndNeutralize + alpha56）。
NOT_COMPARABLE = (48, 56, 58, 59, 63, 67, 69, 70, 76, 79, 80, 82, 87, 89, 90, 91, 93, 97, 100)

#: 已归因的因子级差异（对齐后仍不同，原因必须写明）。
KNOWN_DIFFERENCES: dict[int, str] = {
    21: "vnpy 自述把 `(volume/adv20) >= 1` 实现为 `> 1`（设计文档 §4.3.1 ④）",
    24: "vnpy 自述把 `<= 0.05` 实现为 `< 0.05`（设计文档 §4.3.1 ④）",
}

#: 「离散平局 / 数值病态经截面 rank 放大」这一类（**机制已复算定位，但未逐因子复算**）。
#: 依据（`docs/verification.md` §1.5.3）：alpha45 的 2 日相关 `corr(close, volume, 2)` 在数学上
#: 恒为 ±1，两侧的浮点噪声却不同（唯一值数 34237 vs 26051，vnpy 会落到精确 −1.0）⇒ 精确并列被
#: 不同地打破 ⇒ `rank` 结果差 95%；`corr(sum5,sum20,2)` 更出现 6.03e+03 的数值病态值（|corr|>1）。
#: 这一类**不是转写错误**（L2 对照 101/101 等价、算子层与 vnpy 逐点一致），但归因为「已定位机制」。
NUMERICAL_TIE_CLASS: dict[int, str] = {
    13: "rank(cov) 的输入是 rank（离散）⇒ 数学精确并列被浮点噪声打破后经 rank 放大",
    15: "3 日相关 + rank + 3 日求和：同上",
    16: "同 alpha13（rank(cov)）",
    31: "12 日相关 + 多层 rank + decay_linear：同上",
    45: "**已复算（代表例）**：2 日相关恒为 ±1，两侧浮点噪声不同 ⇒ rank 结果差 95%",
    68: "8.9 日相关 + rank(adv15)：同上（不一致格数仅 0.04%）",
    71: "18 日相关 + ts_rank + 逐元素 max：同上（0.06%）",
    77: "3.2 日相关 + 两个 rank 的逐元素 min：同上",
    78: "pow2(rank, rank) 的指数是 rank：同上",
    85: "9.6 日相关 + 两个 rank 的逐元素比较：同上",
    88: "8 日相关 + rank 组合的逐元素 min：同上",
    94: "pow2(rank, ts_rank)：同上",
    96: "含 ts_argmax（整数 ⇒ 天然大量精确并列）：同上（0.2%）",
    98: "含 ts_argmin（整数）+ 多层 rank/decay：同上",
}


def fix_reference_quesval2() -> str:
    """修正参照自身的 `quesval2` 条件取反 bug（实测，见工具文档串）。

    `math_function.quesval2(threshold, feature1, f2, f3)` 的 docstring 说「threshold < feature1 取 f2」，
    但它的 join 让**右侧**（feature1）拿到了 `data` 列、左侧（threshold）拿到 `data_cond`，
    于是实际比较成了 `feature1 < threshold`（取反）。实测证据::

        quesval2(threshold=[1,5,9], feature1=[3,5,7], 100, -100) -> [-100, -100, 100]
        文档语义应为                                        -> [ 100,  100, -100]

    修正方式：交换前两个参数再调原实现（等价于把比较方向翻回来）。
    """
    from vnpy.alpha.dataset import math_function  # noqa: PLC0415

    if getattr(math_function, "_alpha101v_fixed", False):
        return "已修正"
    original = math_function.quesval2

    def fixed(threshold, feature1, *rest):
        return original(feature1, threshold, *rest)

    fixed._alpha101v_fixed = True  # type: ignore[attr-defined]
    math_function.quesval2 = fixed
    return "已修正"


def load_reference():
    """导入 vnpy 参照（cs_/ts_/math_ + 表达式求值入口；ta_ 由 talib 替身满足 import）。"""
    missing = [p for p in (DATASET, REF_DIR / "vnpy/alpha/dataset/math_function.py") if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "缺少 vnpy 参照：" + ", ".join(str(p) for p in missing)
            + "；请先运行 `bash tools/fetch_vnpy_reference.sh`"
        )
    if str(REF_DIR) not in sys.path:
        sys.path.insert(0, str(REF_DIR))
    from vnpy.alpha.dataset.utility import calculate_by_expression  # noqa: PLC0415

    return calculate_by_expression


def load_expressions() -> dict[int, str]:
    """抽取 vnpy 未注释的 82 条表达式（含 f-string 里的 ``returns_expr`` 展开）。"""
    expressions: dict[int, str] = {}
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        match = re.match(r'\s*self\.add_feature\("alpha(\d+)",\s*f?"(.*)"\)\s*$', line)
        if match:
            expressions[int(match.group(1))] = match.group(2).replace("{returns_expr}", RETURNS_EXPR)
    return expressions


def make_panel(days: int = 320, names: int = 15, seed: int = 20261011) -> dict[str, pd.DataFrame]:
    """确定性合成长面板（两侧看到**完全相同的输入**，避免数据源差异干扰对拍）。"""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2021-01-04", periods=days, freq="B")
    columns = [f"S{i:02d}" for i in range(names)]
    shape = (days, names)

    walk = np.cumsum(rng.normal(0.0, 0.015, size=shape), axis=0)
    rotation = np.sin(2 * np.pi * (np.arange(days)[:, None] / 7.0 + np.arange(names)[None, :] / names))
    close = pd.DataFrame(30.0 * np.exp(walk + 0.05 * rotation + 0.01 * rng.normal(size=shape)), index=index, columns=columns)
    Open = pd.DataFrame(close.to_numpy() * (1 + rng.normal(0, 0.004, size=shape)), index=index, columns=columns)
    high = pd.DataFrame(np.maximum(close.to_numpy(), Open.to_numpy()) * (1 + np.abs(rng.normal(0, 0.004, size=shape))), index=index, columns=columns)
    low = pd.DataFrame(np.minimum(close.to_numpy(), Open.to_numpy()) * (1 - np.abs(rng.normal(0, 0.004, size=shape))), index=index, columns=columns)
    volume = pd.DataFrame(np.exp(rng.normal(np.log(2e5), 0.6, size=shape)), index=index, columns=columns)
    amount = volume * 100.0 * close
    return {
        "close": close, "Open": Open, "high": high, "low": low, "volume": volume,
        "amount": amount, "vwap": amount / (volume * 100.0),
        "returns": close.pct_change(fill_method=None),
        "cap": pd.DataFrame(np.abs(rng.normal(1e6, 2e5, size=shape)) + 1.0, index=index, columns=columns),
    }


def to_long(panel: dict[str, pd.DataFrame]) -> "object":
    """pandas 面板 → vnpy 需要的长表（列名用 vnpy 的表达式的字段名：open 等）。"""
    import polars as pl  # 延迟导入：只有对拍时才需要 polars

    base = panel["close"].rename_axis("datetime").reset_index()
    long = base.melt(id_vars="datetime", var_name="vt_symbol", value_name="close")
    for field, name in (("Open", "open"), ("high", "high"), ("low", "low"),
                        ("volume", "volume"), ("vwap", "vwap"), ("amount", "amount"), ("cap", "cap")):
        frame = panel[field].rename_axis("datetime").reset_index().melt(
            id_vars="datetime", var_name="vt_symbol", value_name=name
        )
        long = long.merge(frame, on=["datetime", "vt_symbol"], how="left")
    return pl.from_pandas(long).sort(["vt_symbol", "datetime"])


def from_long(out, like: pd.DataFrame) -> pd.DataFrame:
    pdf = out.to_pandas().pivot(index="datetime", columns="vt_symbol", values="data")
    pdf.columns.name = None
    pdf.index.name = None
    return pdf.reindex(index=like.index, columns=like.columns)


def attribute(
    mine: np.ndarray, reference: np.ndarray, expression: str, alpha: int = 0
) -> tuple[str, float, int, int, int, str]:
    """把「不一致」归因到具体原因（只用数据说话）。

    两类可自动判定：

    * **覆盖差异经截面算子传播**：两侧在**当天的有效格子数**不同（预热期/缺失策略差异），
      而截面 rank/scale 的分母就是当日有效数 ⇒ 整天的 rank 值都会平移。
      判定：所有不一致格子都落在「当日有效数不同」的日子里。
    * **参照 `quesval2` 条件取反**：表达式里出现 `quesval2`，且不一致格子并非覆盖差异所致。
    """
    left_finite = np.isfinite(mine)
    right_finite = np.isfinite(reference)
    both = left_finite & right_finite
    comparable = int(both.sum())
    if comparable == 0:
        return "无可比格子", 0.0, 0, int(left_finite.sum()), int(right_finite.sum()), "两侧没有共同有效格子"

    mismatched = both & ~np.isclose(mine, reference, rtol=RTOL, atol=ATOL)
    delta = float(np.max(np.abs(mine[both] - reference[both])))
    if not mismatched.any():
        return "一致", delta, comparable, int(left_finite.sum()), int(right_finite.sum()), ""

    day_counts_differ = (left_finite.sum(axis=1) != right_finite.sum(axis=1))[:, None]
    outside_coverage = mismatched & ~np.broadcast_to(day_counts_differ, mismatched.shape)
    if not outside_coverage.any():
        return (
            "已归因：覆盖差异经截面算子传播", delta, comparable,
            int(left_finite.sum()), int(right_finite.sum()),
            f"{int(mismatched.sum())} 格不一致，全部落在「当日有效格子数不同」的交易日",
        )
    # 规则 3：**同值不同配**——每日「排序后的值」两侧一致 ⇒ 差异只是同一个值集被换位，
    # 成因是浮点噪声（corr/cov 的实现路径不同）翻转了截面 rank 的顺序，不是转写错误。
    checked = same = 0
    for row in range(mine.shape[0]):
        left_sorted = np.sort(mine[row][np.isfinite(mine[row])])
        right_sorted = np.sort(reference[row][np.isfinite(reference[row])])
        if left_sorted.size and left_sorted.size == right_sorted.size:
            checked += 1
            if np.allclose(left_sorted, right_sorted, rtol=RTOL, atol=ATOL):
                same += 1
    if checked and same == checked:
        return (
            "已归因：同值不同配（浮点噪声翻转截面顺序）", delta, comparable,
            int(left_finite.sum()), int(right_finite.sum()),
            f"全部 {checked} 个交易日的「排序后取值」两侧一致 ⇒ 只是同一个值集被换位",
        )

    if alpha in NUMERICAL_TIE_CLASS:
        return (
            "已归因：离散平局/数值病态经 rank 放大（机制已定位）", delta, comparable,
            int(left_finite.sum()), int(right_finite.sum()), NUMERICAL_TIE_CLASS[alpha],
        )

    if "quesval2" in expression:
        return (
            "已归因：参照 quesval2 条件取反（实测 bug）", delta, comparable,
            int(left_finite.sum()), int(right_finite.sum()),
            f"{int(outside_coverage.sum())} 格不一致，可由参照侧 quesval2 取反解释",
        )
    return (
        "实偏差（待查）", delta, comparable, int(left_finite.sum()), int(right_finite.sum()),
        f"{int(outside_coverage.sum())} 格落在覆盖相同的日子里，需要查转写或口径",
    )


@dataclasses.dataclass
class Outcome:
    alpha: int
    verdict: str            # 一致 / 已归因差异 / 实偏差（待查） / 无可比格子
    max_delta: float
    comparable: int         # 两侧都有限的格子数
    mine_finite: int
    ref_finite: int
    reason: str = ""


def apply_alignments(panel: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """按 §6.4 做语义归一化：patch 因子层用到的算子默认值 + 面板口径。"""
    from alpha101v import factors, operators

    from alpha101v.elemwise import signedpower  # noqa: PLC0415

    operators._floor_days = _round_days  # noqa: SLF001   （论文 floor vs vnpy round）
    factors.rank = functools.partial(factors.rank, method="min", normalization="one_over_n")  # type: ignore[assignment]
    factors.ts_rank = functools.partial(factors.ts_rank, normalization="one_over_n")  # type: ignore[assignment]
    # 本库默认已按 BRAIN 定案（days_ago 基准 / power 语义），这里切回 vnpy 的口径再比
    factors.ts_argmax = functools.partial(factors.ts_argmax, basis="window_start")   # type: ignore[assignment]
    factors.ts_argmin = functools.partial(factors.ts_argmin, basis="window_start")   # type: ignore[assignment]
    factors._pow = lambda base, exponent: signedpower(base, exponent, preserve_sign=True)  # type: ignore[assignment]
    factors.decay_linear = functools.partial(
        factors.decay_linear, order="oldest_first", dense=True
    )  # type: ignore[assignment]
    factors.stddev = functools.partial(factors.stddev, ddof=0)              # type: ignore[assignment]

    aligned = dict(panel)
    aligned["amount"] = panel["volume"]     # vnpy 的 adv{d} 就是 ts_mean(volume, d)
    return aligned


def _round_days(value, *, name: str, minimum: int) -> int:
    """对齐用：把本库的 ``floor`` 换成 vnpy 实测的**四舍五入**。"""
    if isinstance(value, bool):
        raise TypeError(f"{name} 不能是布尔值")
    days = int(round(float(value))) if isinstance(value, (float, np.floating)) else int(value)
    if days < minimum:
        raise ValueError(f"{name} 必须 >= {minimum}（对齐模式下收到 {value}）")
    return days


def load_real_panel(n_codes: int, start: str, end: str) -> dict[str, pd.DataFrame]:
    """真实 A 股面板（本地 MongoDB，hfq 复权）——**连续行情**，用于排除离散平局带来的数值差异。"""
    import numpy as np  # noqa: PLC0415
    import pymongo  # noqa: PLC0415

    from alpha101v.adapters.mongo import load_panel  # noqa: PLC0415

    client = pymongo.MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000)
    try:
        pool = sorted({
            str(doc["code"]) for doc in client["quantaxis"]["stock_daily_basic"].find({"date": end}, {"code": 1})
        })
    finally:
        client.close()
    if not pool:
        raise SystemExit(f"{end} 在 stock_daily_basic 里没有数据")
    rng = np.random.default_rng(20261011)
    codes = sorted(rng.choice(pool, size=min(n_codes, len(pool)), replace=False).tolist())
    return load_panel(codes, start, end, adjust="hfq")


def main() -> int:
    parser = argparse.ArgumentParser(description="因子级差分对拍（本库 vs vnpy）")
    parser.add_argument("--no-align", action="store_true", help="不做语义归一化，看默认口径差距")
    parser.add_argument("--alpha", type=int, help="只对拍某个因子（附两侧统计）")
    parser.add_argument("--alphas", help="只对拍这些因子（逗号分隔，如 13,15,16）；用于大面板下的定点核查")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--panel", default="synthetic", choices=("synthetic", "real"),
        help="synthetic=确定性合成面板（离散 rank 多平局）；real=本地真实 A 股面板"
             "（连续行情，用于排除「离散平局被浮点噪声打破」这一类数值差异）",
    )
    parser.add_argument("--n-codes", type=int, default=200, help="--panel real 时的股票数")
    parser.add_argument("--start", default="2023-01-03")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument(
        "--no-fix-reference", action="store_true",
        help="不修正参照侧 quesval2 的条件取反 bug（用于量化其影响面）",
    )
    args = parser.parse_args()

    try:
        calculate_by_expression = load_reference()
    except FileNotFoundError as exc:
        print(f"[skip] {exc}")
        return 0
    if not args.no_fix_reference:
        fix_reference_quesval2()

    from alpha101v import registry

    expressions = load_expressions()
    if args.panel == "real":
        panel = load_real_panel(args.n_codes, args.start, args.end)
    else:
        panel = make_panel()
    mine_panel = panel if args.no_align else apply_alignments(panel)
    long = to_long(panel)
    index, columns = panel["close"].index, panel["close"].columns

    if args.alpha:
        targets = [args.alpha]
    elif args.alphas:
        targets = [int(item) for item in args.alphas.split(",") if item.strip()]
    else:
        targets = sorted(expressions)
    outcomes: list[Outcome] = []
    raw_mismatch: dict[int, str] = {}
    for alpha in targets:
        name = f"alpha{alpha}"
        expression = expressions.get(alpha)
        if expression is None:
            outcomes.append(Outcome(alpha, "无可比格子", 0.0, 0, 0, 0, "vnpy 未实现（19 个缺口之一）"))
            continue
        mine = registry.run_factor(name, mine_panel).reindex(index=index, columns=columns)
        left = mine.to_numpy(dtype=float)

        # 先按**未修正**的参照记一次（用于证明 quesval2 取反的影响面）
        unfixed = from_long(calculate_by_expression(long, expression), panel["close"]).to_numpy(dtype=float)
        if "quesval2" in expression:
            compare = np.isfinite(left) & np.isfinite(unfixed)
            mismatched = int((compare & ~np.isclose(left, unfixed, rtol=RTOL, atol=ATOL)).sum())
            raw_mismatch[alpha] = f"{mismatched}/{int(compare.sum())}"

        verdict, delta, comparable, mine_finite, ref_finite, reason = attribute(
            left, unfixed if args.no_align else from_long(
                calculate_by_expression(long, expression), panel["close"]
            ).to_numpy(dtype=float),
            expression, alpha,
        )
        if verdict == "实偏差（待查）" and alpha in KNOWN_DIFFERENCES:
            verdict, reason = "已归因差异", KNOWN_DIFFERENCES[alpha]
        outcomes.append(Outcome(alpha, verdict, delta, comparable, mine_finite, ref_finite, reason))

    if not args.quiet:
        print("| 因子 | 判定 | 最大 \\|Δ\\| | 可比格子 | 本库有效 | vnpy 有效 | 原因 |")
        print("|---|---|---|---|---|---|---|")
        for out in outcomes:
            print(f"| alpha{out.alpha} | {out.verdict} | {out.max_delta:.3g} | {out.comparable} | "
                  f"{out.mine_finite} | {out.ref_finite} | {out.reason} |")
        print()

    counts = collections.Counter(out.verdict for out in outcomes)
    tags = []
    if args.no_align:
        tags.append("默认口径")
    else:
        tags.append("语义归一化后")
    tags.append("参照 quesval2 未修正" if args.no_fix_reference else "参照 quesval2 已修正")
    located = [out.alpha for out in outcomes if "机制已定位" in out.verdict]
    if located and not args.quiet:
        print(f"  （其中 {len(located)} 个属于「离散平局/数值病态」类：机制已复算定位、未逐因子复算："
              f"{','.join('alpha'+str(a) for a in located)}）")
    print(f"{' + '.join(tags)}：对拍 {len(outcomes)} 个因子："
          + "、".join(f"{k} {v}" for k, v in sorted(counts.items())))
    pending = [out for out in outcomes if out.verdict == "实偏差（待查）"]
    if pending:
        print("❌ 待查（需要查转写或口径）：")
        for out in pending:
            print(f"  - alpha{out.alpha}: max|Δ|={out.max_delta:.6g}，可比格子={out.comparable}")
        return 1
    print("✅ 无「待查」项：一致或已归因")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
