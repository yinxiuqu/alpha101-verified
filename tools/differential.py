#!/usr/bin/env python
"""算子层差分对拍：本库 vs **vnpy（MIT）**（设计文档 §6.4 的 L3，算子层提前做）。

为什么提前做：口径决策（ddof / pct / argmax 基准 / decay 权重方向）一旦被 101 个因子固化，
返工成本极高。本工具在因子放量前先用**第二实现**（不同作者、不同语言：polars DSL）逐点对拍。

参照来源
--------
``vnpy/alpha/dataset/{cs_function,ts_function}.py``（MIT），由
``tools/fetch_vnpy_reference.sh`` 下载到 gitignored 的 ``.vnpy-ref/``（含 SHA256 校验）。
本仓库**不提交**第三方代码；``tests/test_differential.py`` 在参照缺失时自动跳过。

判定纪律（§6.4）
----------------
* 差异**严禁简单判错**，必须归因为三类之一：
  ``一致`` / ``口径差异（已归因，可接受）`` / ``不一致（必须查）``；
* 每条「口径差异」都要**实测差异确实存在**（防止文档漂移成空话）；
* 每条「一致」都要在**可比较区域**（对齐预热期、ddof、并列策略、权重方向后）逐点
  ``allclose(rtol=1e-8)``，且 NaN 位置一致。

首跑结论（2026-10-09，见 ``docs/verification.md`` §2.1）
--------------------------------------------------------
**一致（对齐后逐点）**：``ts_sum`` / ``delta`` / ``delay`` / ``product`` / ``sma`` /
``stddev(ddof=0)`` / ``ts_min`` / ``ts_max`` / ``ts_argmax`` / ``ts_argmin`` /
``ts_rank(pct=True)`` / ``correlation`` / ``covariance(ddof=0)`` /
``decay_linear(order="oldest_first")`` / ``rank(method="min")`` / ``scale``。

**口径差异（已归因，共 6 条）**：
D1 ``decay_linear`` 权重方向（vnpy 取「最老权重最大」；本库默认「最新最大」，可用 order 对齐）
   —— **影响面最大：22 个因子**；
D2 ~~``stddev`` ddof~~：**已消失**（2026-10-10 起本库默认 ``ddof=0``，与 vnpy 一致，见
   ``docs/operators.md`` §3.1/§3.13.3）；
   且 **vnpy 自身不一致**（``cs_std`` 用 polars 默认 ``ddof=1``）；
D3 预热期：vnpy 各算子不统一（``ts_sum`` 严格；``ts_min/max/mean/std/corr`` 用 ``min_samples=1``
   填值），本库统一严格 NaN（§2.3，且有变异测试 m7 守着）；
D4 ``rank`` 并列策略：vnpy 用 ``method="min"``，本库默认 ``average``（可用 ``method="min"`` 对齐）；
D5 ``scale`` 零和行：vnpy 给 0，本库给 NaN（本库拒绝把「无数据」伪装成 0，呼应 §3.3 缺陷 7）；
D6 NaN 洞：vnpy 的 ``nan*`` 归约在 ``min_samples=1`` 下会跨 NaN 出值，本库窗口含 NaN 即 NaN；
D7 ``rank``/``ts_rank`` 归一化：本库默认官方 ``zero_to_one``（``(名次−1)/(n−1) ∈ [0,1]``），
   vnpy 是 ``one_over_n``（``名次/n ∈ (0,1]``）——可用 ``normalization="one_over_n"`` 对齐；
D8 ``decay_linear`` 稀疏模式：本库默认官方 ``dense=False``（窗口内 NaN 当 0），vnpy 另有其 NaN 处理。

用法
----
    python tools/differential.py            # 打印对拍表；有「不一致（待查）」则退出码 1
    python tools/differential.py --quiet    # 只输出结论行
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
REF_DIR = ROOT / ".vnpy-ref"

# 作为脚本直接运行时没有 conftest.py 帮忙，显式把 src 布局加进 sys.path
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
REF_FILES = (
    "vnpy/alpha/dataset/ts_function.py",
    "vnpy/alpha/dataset/cs_function.py",
    "vnpy/alpha/dataset/utility.py",
)

DEFAULT_RTOL = 1e-8


def load_reference():
    """导入 vnpy 参照算子（仅 cs_/ts_ 两类，不碰依赖 talib 的 ta_ 类）。"""
    missing = [name for name in REF_FILES if not (REF_DIR / name).exists()]
    if missing:
        raise FileNotFoundError(
            "缺少 vnpy 参照源码："
            + ", ".join(missing)
            + "；请先运行 `bash tools/fetch_vnpy_reference.sh`（MIT，仅测试期对拍）"
        )
    if str(REF_DIR) not in sys.path:
        sys.path.insert(0, str(REF_DIR))
    from vnpy.alpha.dataset import cs_function, ts_function  # noqa: PLC0415

    return cs_function, ts_function


def make_intraday_panel(days: int = 40, names: int = 4, seed: int = 20261009) -> dict[str, pd.DataFrame]:
    """确定性面板（无 NaN、无并列、无零和行）——用于「对齐后应逐点一致」的对拍。"""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2022-01-03", periods=days, freq="B")
    columns = [f"S{i}" for i in range(names)]
    shape = (days, names)

    close = pd.DataFrame(30.0 + np.cumsum(rng.normal(0.0, 0.4, size=shape), axis=0), index=index, columns=columns)
    volume = pd.DataFrame(np.abs(rng.normal(2e5, 3e4, size=shape)) + 100.0, index=index, columns=columns)
    other = pd.DataFrame(np.abs(rng.normal(15.0, 3.0, size=shape)) + 1.0, index=index, columns=columns)
    return {"close": close, "volume": volume, "other": other}


def to_long(panel: pd.DataFrame):
    """pandas 面板 → vnpy 需要的长表 ``[datetime, vt_symbol, data]``（polars）。"""
    import polars as pl  # 延迟导入：只有真正对拍时才需要

    frame = (
        panel.rename_axis("datetime")
        .reset_index()
        .melt(id_vars="datetime", var_name="vt_symbol", value_name="data")
    )
    return pl.from_pandas(frame).sort(["vt_symbol", "datetime"])


def from_long(out, like: pd.DataFrame) -> pd.DataFrame:
    """vnpy 输出长表 → 与 ``like`` 同 index/columns 的面板。"""
    pdf = out.to_pandas().pivot(index="datetime", columns="vt_symbol", values="data")
    pdf.columns.name = None
    pdf.index.name = None
    return pdf.reindex(index=like.index, columns=like.columns)


@dataclasses.dataclass
class Check:
    """一条对拍：``kind="match"`` 要求对齐后逐点一致；``kind="differ"`` 要求差异确实存在。"""

    name: str
    mine: pd.DataFrame
    ref: pd.DataFrame
    kind: str = "match"
    first_row: int = 0
    rtol: float = DEFAULT_RTOL
    note: str = ""


def quantify(check: Check) -> tuple[float, int]:
    """返回 ``(可比较区域内的最大绝对差, NaN 位置不一致的格子数)``。"""
    mine = check.mine.to_numpy(dtype=float)[check.first_row :]
    ref = check.ref.to_numpy(dtype=float)[check.first_row :]
    both_nan = np.isnan(mine) & np.isnan(ref)
    one_nan = np.isnan(mine) ^ np.isnan(ref)
    finite = np.isfinite(mine) & np.isfinite(ref)
    maxdiff = float(np.max(np.abs(mine[finite] - ref[finite]))) if finite.any() else 0.0
    return maxdiff, int(one_nan.sum())


def build_checks() -> list[Check]:
    cs, ts = load_reference()
    from alpha101v import operators as ops

    panel = make_intraday_panel()
    close, volume, other = panel["close"], panel["volume"], panel["other"]
    d = 5
    ref_close = to_long(close)
    ref_volume = to_long(volume)
    ref_other = to_long(other)

    def ref_ts(func, *frames, window=None):
        proxies = [__import__("vnpy.alpha.dataset.utility", fromlist=["DataProxy"]).DataProxy(f)
                   for f in frames]
        args = proxies + ([window] if window is not None else [])
        return from_long(func(*args).df, close)

    def ref_cs(func, frame):
        from vnpy.alpha.dataset.utility import DataProxy

        return from_long(func(DataProxy(frame)).df, close)

    checks: list[Check] = []

    # ---- 对齐后应逐点一致 ----
    checks.append(Check("ts_sum(x,5)", ops.ts_sum(close, d), ref_ts(ts.ts_sum, ref_close, window=d)))
    checks.append(Check("delta(x,3)", ops.delta(close, 3), ref_ts(ts.ts_delta, ref_close, window=3)))
    checks.append(Check("delay(x,3)", ops.delay(close, 3), ref_ts(ts.ts_delay, ref_close, window=3)))
    checks.append(Check("product(x,5)", ops.product(close, d), ref_ts(ts.ts_product, ref_close, window=d), first_row=d - 1))
    checks.append(Check("sma(x,5)", ops.sma(close, d), ref_ts(ts.ts_mean, ref_close, window=d), first_row=d - 1))
    checks.append(Check(
        "stddev(x,5,ddof=0)", ops.stddev(close, d, ddof=0), ref_ts(ts.ts_std, ref_close, window=d),
        first_row=d - 1, note="对齐 vnpy 的 ddof=0",
    ))
    checks.append(Check("ts_min(x,5)", ops.ts_min(close, d), ref_ts(ts.ts_min, ref_close, window=d), first_row=d - 1))
    checks.append(Check("ts_max(x,5)", ops.ts_max(close, d), ref_ts(ts.ts_max, ref_close, window=d), first_row=d - 1))
    # 本库默认已是 BRAIN 的 days_ago（今天=0）；vnpy 是 arg_max()+1（自窗口起点）⇒ 对拍时显式对齐
    checks.append(Check("ts_argmax(x,5)", ops.ts_argmax(close, d, basis="window_start"), ref_ts(ts.ts_argmax, ref_close, window=d), first_row=d - 1,
                        note="★ 两边都是「自窗口起点 1-based」"))
    checks.append(Check("ts_argmin(x,5)", ops.ts_argmin(close, d, basis="window_start"), ref_ts(ts.ts_argmin, ref_close, window=d), first_row=d - 1))
    checks.append(Check(
        "ts_rank(x,5,one_over_n)", ops.ts_rank(close, d, normalization="one_over_n"),
        ref_ts(ts.ts_rank, ref_close, window=d), first_row=d - 1,
        note="★ 归一化按 vnpy 的 名次/n 对齐（本库默认已是官方 zero_to_one）",
    ))
    checks.append(Check("correlation(x,y,5)", ops.correlation(close, other, d), ref_ts(ts.ts_corr, ref_close, ref_other, window=d), first_row=d - 1))
    checks.append(Check(
        "covariance(x,y,5,ddof=0)", ops.covariance(close, other, d, ddof=0),
        ref_ts(ts.ts_cov, ref_close, ref_other, window=d), first_row=d - 1, note="vnpy ts_cov = corr·σ·σ（σ 用 ddof=0）",
    ))
    checks.append(Check(
        'decay_linear(x,5,order="oldest_first")', ops.decay_linear(close, d, order="oldest_first"),
        ref_ts(ts.ts_decay_linear, ref_close, window=d), first_row=d - 1, note="★ 用 order 对齐后一致",
    ))
    checks.append(Check("scale(x,1)", ops.scale(close, 1.0), ref_cs(cs.cs_scale, ref_close), note="面板无零和行"))

    # 并列面板（制造重复值）用于 rank 口径对齐
    tied = (close / 1.0).round(0)  # 取整制造并列
    ref_tied = to_long(tied)
    checks.append(Check(
        'rank(x,method="min",one_over_n) [并列面板]',
        ops.rank(tied, method="min", normalization="one_over_n"), ref_cs(cs.cs_rank, ref_tied),
        note="★ 按 method=min + 名次/n 对齐后一致（vnpy cs_rank = method=min, pct=True）",
    ))
    checks.append(Check(
        "rank(x,one_over_n) [无并列面板]", ops.rank(close, normalization="one_over_n"),
        ref_cs(cs.cs_rank, ref_close),
        note="无并列 ⇒ average 与 min 等价；归一化按 vnpy 的 名次/n 对齐",
    ))

    # ---- 已归因的口径差异：差异必须**确实存在** ----
    checks.append(Check(
        "D1 decay_linear 默认(recent_first) vs vnpy", ops.decay_linear(close, d),
        ref_ts(ts.ts_decay_linear, ref_close, window=d), kind="differ", first_row=d - 1,
        note="权重方向相反：vnpy 把权重 d,d-1,…,1 套在时间正序窗口上（最老权重最大）",
    ))
    # D2 已消失：本库默认 ddof=0（BRAIN 官方口径）与 vnpy 的 ts_std 一致 ⇒ 改为「对齐」检查
    checks.append(Check(
        "stddev(x,5) 默认 [D2 已消失] vs vnpy", ops.stddev(close, d),
        ref_ts(ts.ts_std, ref_close, window=d), first_row=d - 1,
        note="★ 本库默认 ddof=0（L-B 定案）⇒ 与 vnpy 的 ts_std 逐点一致（曾经的 D2 不复存在）",
    ))
    checks.append(Check(
        "D3 严格预热 vs vnpy 填值（ts_min）", ops.ts_min(close, d),
        ref_ts(ts.ts_min, ref_close, window=d), kind="differ", first_row=0,
        note="vnpy ts_min 用 min_samples=1 填预热期；本库前 d-1 行必须为 NaN",
    ))
    checks.append(Check(
        "D4 rank 默认(average) vs vnpy(min) [并列面板]", ops.rank(tied),
        ref_cs(cs.cs_rank, ref_tied), kind="differ",
        note="并列行的并列策略不同（无并列时两者等价）",
    ))
    zero_row = close.copy()
    zero_row.iloc[3] = 0.0
    checks.append(Check(
        "D5 scale 零和行 vs vnpy", ops.scale(zero_row, 1.0),
        ref_cs(cs.cs_scale, to_long(zero_row)), kind="differ", first_row=0,
        note="零和行：vnpy 给 0，本库给 NaN（拒绝把「无数据」伪装成 0）",
    ))
    holed = close.copy()
    holed.iloc[5, 0] = np.nan
    # D6 的真实分歧点：vnpy 的 ts_mean/ts_std 走 nan 归约 + min_samples=1 ⇒ 会**跨 NaN 出值**；
    # 而 ts_sum 用的是 polars rolling_sum（严格），与我们的 NaN 传播**一致**——两者都实测。
    checks.append(Check(
        "D6 sma（NaN 洞）vs vnpy ts_mean", ops.sma(holed, d),
        ref_ts(ts.ts_mean, to_long(holed), window=d), kind="differ", first_row=0,
        note="窗口含 NaN：vnpy 用 nanmean+min_samples=1 会跨 NaN 出值；本库窗口含 NaN 即 NaN",
    ))
    checks.append(Check(
        "D7 rank 默认(zero_to_one) vs vnpy(one_over_n)", ops.rank(close),
        ref_cs(cs.cs_rank, ref_close), kind="differ",
        note="归一化区间不同：(名次−1)/(n−1) ∈ [0,1] vs 名次/n ∈ (0,1]（用 normalization 对齐）",
    ))
    checks.append(Check(
        "D7b ts_rank 默认(zero_to_one) vs vnpy(one_over_n)", ops.ts_rank(close, d),
        ref_ts(ts.ts_rank, ref_close, window=d), kind="differ", first_row=d - 1,
        note="同 D7：官方 ts_rank 算例 3/(5−1)=0.75，vnpy 为 4/5=0.8",
    ))
    checks.append(Check(
        "D8 decay_linear 稀疏(NaN→0) vs vnpy [NaN 洞]", ops.decay_linear(holed, d),
        ref_ts(ts.ts_decay_linear, to_long(holed), window=d), kind="differ", first_row=0,
        note="官方默认稀疏模式把窗口内 NaN 当 0（分母仍为 1+…+d）；vnpy 的处理不同",
    ))
    checks.append(Check(
        "（对照）ts_sum（NaN 洞）vs vnpy ts_sum", ops.ts_sum(holed, d),
        ref_ts(ts.ts_sum, to_long(holed), window=d), first_row=0,
        note="两边都是 polars/numpy 严格滚动 ⇒ NaN 传播一致（曾被我误判为差异）",
    ))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="算子层差分对拍（本库 vs vnpy）")
    parser.add_argument("--quiet", action="store_true", help="只输出结论")
    args = parser.parse_args()

    try:
        checks = build_checks()
    except FileNotFoundError as exc:
        print(f"[skip] {exc}")
        return 0

    rows: list[tuple[str, str, float, int, str]] = []
    failures: list[str] = []
    for check in checks:
        maxdiff, nan_mismatch = quantify(check)
        matched = nan_mismatch == 0 and maxdiff <= check.rtol
        verdict = "一致（逐点）" if matched else "有差异"
        ok = matched if check.kind == "match" else not matched
        if not ok:
            verdict = "不一致（待查）"
            failures.append(f"{check.name}: maxdiff={maxdiff:.6g} nan_mismatch={nan_mismatch}")
        rows.append((check.name, verdict, maxdiff, nan_mismatch, check.note))

    if not args.quiet:
        print("| 对拍项 | 结果 | max|Δ| | NaN 位置不一致 | 说明 |")
        print("|---|---|---|---|---|")
        for name, verdict, maxdiff, nan_mismatch, note in rows:
            print(f"| `{name}` | {verdict} | {maxdiff:.3g} | {nan_mismatch} | {note} |")
        print()

    matched_count = sum(1 for row in rows if row[1] == "一致（逐点）")
    print(
        f"对拍 {len(rows)} 项：逐点一致 {matched_count} 项，"
        f"已归因口径差异 {len(rows) - matched_count - len(failures)} 项，待查 {len(failures)} 项"
    )
    if failures:
        for item in failures:
            print(f"  ❌ {item}")
        return 1
    print("✅ 全部对拍项符合预期（一致 or 已归因差异），无「待查」项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
