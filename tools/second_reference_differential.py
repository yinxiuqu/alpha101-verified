#!/usr/bin/env python
"""第二独立参照差分：本库 vs `alpha101-pipeline`（MIT）—— 专攻 19 个 `partial`。

为什么需要它
------------
本库的 19 个 `partial` 因子含 `IndNeutralize` 或需要 `cap`，而**第一参照（vnpy）没有实现它们**
⇒ 「独立逐点对拍」这一必需门槛原理上无法满足。`alpha101-pipeline`（PyPI，MIT 许可，
独立作者、DuckDB/SQL 实现、**覆盖全部 101 个公式含全部 19 个**）正好补上这个缺口。

法律与清洁室
------------
* 只用**宽松许可**（MIT）的实现，且只在**测试期**当参照；作者与来源记录在下方常量里；
* 代码装进仓库内独立 venv（`.refs/venv-ref`，gitignored），**不进运行时依赖**（`pyproject` 不动）；
* 严禁使用 GPL 实现（设计文档 §1.1 第 8 行的许可结论）。

参照自己声明的口径差异（⇒ 必须逐条对齐，否则比的是口径而不是实现）
------------------------------------------------------------------
| 参照的写法 | 本库默认 | 对拍时怎么对齐 |
|---|---|---|
| 截面 `rank()` 返回 **0..n−1 序号**（qlib 风格） | `[0,1]`（官方） | 本库切 `normalization="ordinal"` |
| `ts_rank` 同理 | 同上 | 同上 |
| `adv{N}` = `ts_mean(volume*close, N)`（代理） | `amount`（真成交额） | 面板 `amount := volume*close` |
| 滚动 `stddev` 用 pandas 默认 **ddof=1** | `ddof=0`（官方） | 本库切 `ddof=1` |
| `decay_linear` 需要满窗（NaN 不进） | 默认稀疏（官方） | 本库切 `dense=True` |
| `ts_argmax/argmin` 自窗口起点的 0-based | `days_ago`（官方） | 本库切 `basis="window_start"` |
| `^` 用 `sign(x)*abs(x)^y` | `power`（官方丢符号） | 本库把 `^` 换成 `signedpower` |
| 分数窗口**四舍五入** | `floor`（论文 §3 明写） | **无法对齐** ⇒ 逐因子检测并归因（不豁免） |

用法::

    python tools/second_reference_differential.py --alphas 48,56,58,59,63,67,69,70,76,79,80,82,87,89,90,91,93,97,100
    python tools/second_reference_differential.py --all --out reports/second_reference_diff.csv
    python tools/second_reference_differential.py --alphas 58 --panel synthetic
"""

from __future__ import annotations

import argparse
import functools
import pathlib
import re
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import factor_differential as fd  # noqa: E402  （复用面板构建/to_long 等）

from alpha101v import factors, registry  # noqa: E402

#: 参照的出处与许可（用于合规留痕；**不把它的代码放进本仓库**）
REFERENCE = {
    "name": "alpha101-pipeline",
    "version": "0.6.2",
    "license": "MIT（PyPI 分类器 `License :: OSI Approved :: MIT License`）",
    "url": "https://pypi.org/project/alpha101-pipeline/",
    "venv": ROOT / ".refs" / "venv-ref",
    "runner": ROOT / ".refs" / "sec_ref" / "runner_full.py",
    "workdir": ROOT / ".refs" / "sec_ref",
}

#: 参照把小数窗口**四舍五入**，本库按论文 §3 用 **floor**。判定「这个因子有没有窗口口径冲突」
#: 不能靠「docstring 里出现任何小数」（`0.001`、`1.5` 这类常数会误判），也不能靠记忆里的常数表
#: （实测 alpha58 的 3.92795 就不在表里）。这里按**可判定的规则**从公式里取：
#: 小数且 ≥ 2.5 的数字视为窗口候选（窗口至少 2 天；系数/防零项都远小于 2.5），
#: 再要求 round ≠ floor —— 相同就没有差异，不算冲突。
WINDOW_CANDIDATE_MIN = 2.5


def fractional_window_constants(expression: str) -> list[float]:
    """从公式文本里取「小数窗口候选」：小数且 ≥ 2.5。"""
    return [float(x) for x in re.findall(r"\d+\.\d+", expression) if float(x) >= WINDOW_CANDIDATE_MIN]


def rounding_conflict_expressions(expressions: dict[str, str]) -> dict[str, list[float]]:
    """逐因子给出「会发生 round≠floor 的窗口常数」列表（空 = 无窗口口径冲突）。"""
    result: dict[str, list[float]] = {}
    for name, expression in expressions.items():
        conflicts = [w for w in fractional_window_constants(expression)
                     if round(w) != int(np.floor(w))]
        result[name] = sorted(set(conflicts))
    return result


def to_reference_long(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """面板 → 参照要的长表（`date, stock_id, open/high/low/close/volume, vwap, cap, sector, ...`）。

    * 列名统一成小写（参照的 `REQUIRED_SOURCE_COLUMNS` 是小写）；
    * `amount := volume * close`：参照的 `adv` 就是这个代理 ⇒ 对齐输入而不是比口径；
    * 行业三列由 `ind_sector/ind_industry/ind_subindustry` 映射过去（参照按 `sector/industry/subindustry` 取用）。
    """
    close = panel["close"]
    long_frames = []
    base = {
        "open": panel["Open"], "high": panel["high"], "low": panel["low"], "close": close,
        "volume": panel["volume"], "vwap": panel.get("vwap", (panel["high"] + panel["low"] + close) / 3.0),
        "cap": panel.get("cap"),
        "sector": panel.get("ind_sector"), "industry": panel.get("ind_industry"),
        "subindustry": panel.get("ind_subindustry"),
    }
    first = True
    for name, frame in base.items():
        if frame is None:
            continue
        if isinstance(frame, pd.Series):                 # 静态行业快照 → 广播成面板形状
            frame = pd.DataFrame(
                np.tile(frame.to_numpy(dtype=object), (len(close.index), 1)),
                index=close.index, columns=close.columns,
            )
        stacked = frame.stack(future_stack=True).rename(name)
        long_frames.append(stacked)
        first = False
    table = pd.concat(long_frames, axis=1).reset_index()
    table.columns = ["date", "stock_id", *[c for c in table.columns[2:]]]
    table["date"] = pd.to_datetime(table["date"])
    table["amount"] = table["volume"] * table["close"]      # 对齐参照的 adv 代理
    return table


def run_reference(table: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """调用参照（独立 venv 子进程）→ 返回长表（含每个因子一列）。"""
    # 先检查参照环境：缺 venv 时给出可执行提示，而不是在写 runner 时抛底层 FileNotFoundError
    python = REFERENCE["venv"] / "bin" / "python"
    if not python.exists():
        raise SystemExit(f"参照环境不存在：{python}\n先跑 `bash tools/fetch_second_reference.sh`")
    REFERENCE["workdir"].mkdir(parents=True, exist_ok=True)
    inp = REFERENCE["workdir"] / "panel_in.parquet"
    outp = REFERENCE["workdir"] / "factors_out.parquet"
    table.to_parquet(inp, index=False)
    runner = REFERENCE["runner"]
    runner.parent.mkdir(parents=True, exist_ok=True)
    runner.write_text(
        "import sys, pathlib, json\n"
        "from alpha101_pipeline import run_alpha101_duckdb\n"
        "from alpha101_pipeline.formulas import ALPHAS\n"
        "inp, outp = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])\n"
        "names = sys.argv[3].split(',')\n"
        "spill = outp.parent / 'spill'; spill.mkdir(exist_ok=True)\n"
        "# ⚠️ 必须显式指定：参照默认的自动分块/内存探测在本沙箱里会**挂死**\n"
        "#（/tmp 是受限 tmpfs，DuckDB 落盘失败又不报错）——实测显式配置后 1.3s 跑完。\n"
        "report = run_alpha101_duckdb(input_path=inp, output_path=outp,\n"
        "                            formulas=[(n, ALPHAS[n]) for n in names],\n"
        "                            date_column='date', id_column='stock_id',\n"
        "                            chunked='never', memory_limit='1GB', temp_dir=str(spill))\n"
        "print(json.dumps({k: report[k] for k in ('engine', 'duckdb_version') if k in report}))\n",
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(  # noqa: S603
            [str(python), str(runner), str(inp), str(outp), ",".join(names)],
            capture_output=True, text=True, cwd=ROOT, timeout=1800,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit("参照执行超时（1800s）：检查是否没传 chunked/memory_limit/temp_dir") from None
    if proc.returncode != 0:
        raise SystemExit(f"参照执行失败：\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    print(f"  参照运行完成：{proc.stdout.strip()[:120]}")
    return pd.read_parquet(outp)


def apply_second_reference_alignments(panel: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """把本库切到与参照可比的口径（见模块文档的对齐表；**不改任何因子定义**，只改运行期口径）。"""
    # 参照的截面 rank 是 **0..n−1**（qlib 风格），本库 `ordinal` 是 **1..n** ⇒ 减 1 才是同一口径。
    # rank 是逐元素使用的，所以「减 1」是等价变换；但 rank 进入乘/除时差 1 会被放大，
    # 必须对齐——这正是 alpha56（两个 rank 相乘）一开始全列不匹配的原因。
    ordinal_rank = factors.rank
    ordinal_ts_rank = factors.ts_rank

    def rank_zero_based(df, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return ordinal_rank(df, *args, normalization="ordinal", **kwargs) - 1.0

    def ts_rank_zero_based(df, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return ordinal_ts_rank(df, *args, normalization="ordinal", **kwargs) - 1.0

    factors.rank = rank_zero_based          # type: ignore[assignment]
    factors.ts_rank = ts_rank_zero_based    # type: ignore[assignment]
    factors.stddev = functools.partial(factors.stddev, ddof=1)                       # type: ignore[assignment]
    factors.decay_linear = functools.partial(factors.decay_linear, dense=True)       # type: ignore[assignment]
    factors.ts_argmax = functools.partial(factors.ts_argmax, basis="window_start")   # type: ignore[assignment]
    factors.ts_argmin = functools.partial(factors.ts_argmin, basis="window_start")   # type: ignore[assignment]
    if hasattr(factors, "power"):
        # 参照的 `^` 是 sign(x)*|x|^y（保号）；本库按官方文档用 power（非整数指数丢符号）
        factors.power = factors.signedpower                                            # type: ignore[assignment]
    aligned = {k: (v.copy() if isinstance(v, pd.DataFrame) else v) for k, v in panel.items()}
    if "volume" in aligned and "close" in aligned:
        # adv 对齐：两侧都用 volume*close
        aligned["amount"] = aligned["volume"] * aligned["close"]
    return aligned



def compare(panel: dict[str, pd.DataFrame], reference: pd.DataFrame, count: int) -> list[dict]:
    """逐点比较：返回每个因子的判定与差异统计。"""
    outcomes: list[dict] = []
    reference["date"] = pd.to_datetime(reference["date"])
    rounding_conflicts = rounding_conflict_expressions(
        {n: (registry.REGISTRY[n].func.__doc__ or "") for n in registry.REGISTRY}
    )
    for name in sorted((n for n in registry.REGISTRY if n.startswith("alpha")), key=lambda s: int(s[5:])):
        number = int(name[5:])
        if number > count:
            continue
        try:
            mine_values = registry.run_factor(name, panel, dtype=np.float64)  # 验证口径用 float64
        except Exception as exc:  # noqa: BLE001
            outcomes.append({"factor": name, "verdict": f"本库执行失败：{str(exc)[:60]}", "cells": 0, "mismatch": 0, "max_abs_diff": np.nan})
            continue
        if name not in reference.columns:
            outcomes.append({"factor": name, "verdict": "参照未产出该列", "cells": 0, "mismatch": 0, "max_abs_diff": np.nan})
            continue
        theirs = reference.pivot(index="date", columns="stock_id", values=name)
        theirs = theirs.reindex(index=mine_values.index, columns=mine_values.columns)
        a = mine_values.to_numpy(dtype=float)
        b = theirs.to_numpy(dtype=float)
        both = np.isfinite(a) & np.isfinite(b)
        nan_match = np.isnan(a) & np.isnan(b)
        cells = int(both.sum() + nan_match.sum())
        if both.sum() == 0:
            outcomes.append({"factor": name, "verdict": "无重合有效值", "cells": cells, "mismatch": 0, "max_abs_diff": np.nan})
            continue
        diff = np.abs(a[both] - b[both])
        tolerance = 1e-8 + 1e-6 * np.abs(b[both])
        mismatch = int((diff > tolerance).sum())
        max_abs = float(diff.max())
        nan_mismatch = int((np.isnan(a) ^ np.isnan(b)).sum())
        if mismatch == 0 and nan_mismatch == 0:
            verdict = "一致"
        elif name in rounding_conflicts and rounding_conflicts[name]:
            # ⚠️ 曾经把「公式里有 round≠floor 的小数窗口」直接判为**已归因**——**实测不成立**：
            # 把参照的 alpha58 公式改成 floor 后，不匹配比例反而从 98.9% 升到 100%
            # ⇒ 小数窗口**不是**主因。所以这里只标为「待查（窗口是候选原因之一）」，
            # 绝不据此升级状态。要证明某个机制，必须做**证伪实验**（改参照再比）。
            verdict = f"待查（含小数窗口候选 {rounding_conflicts[name]}，未证伪）"
        else:
            verdict = "待查"
        outcomes.append({
            "factor": name, "verdict": verdict, "cells": cells, "mismatch": mismatch,
            "nan_mismatch": nan_mismatch, "max_abs_diff": max_abs,
        })
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description="第二独立参照差分（alpha101-pipeline，MIT）")
    parser.add_argument("--panel", default="real", choices=("synthetic", "real"))
    parser.add_argument("--n-codes", type=int, default=60)
    parser.add_argument("--start", default="2023-01-03")
    parser.add_argument("--end", default="2024-06-28")
    parser.add_argument("--alphas", help="逗号分隔；默认 19 个 partial")
    parser.add_argument("--all", action="store_true", help="对拍全部 101 个")
    parser.add_argument("--out", default=str(ROOT / "reports" / "second_reference_diff.csv"))
    args = parser.parse_args()

    partial = fd.NO_THIRD_PARTY_REFERENCE if hasattr(fd, "NO_THIRD_PARTY_REFERENCE") else (
        48, 56, 58, 59, 63, 67, 69, 70, 76, 79, 80, 82, 87, 89, 90, 91, 93, 97, 100
    )
    numbers = sorted(partial) if args.alphas is None and not args.all else (
        list(range(1, 102)) if args.all else [int(x) for x in args.alphas.split(",") if x.strip()]
    )

    if args.panel == "synthetic":
        panel = fd.make_panel()
    else:
        import importlib.util  # noqa: PLC0415

        spec = importlib.util.spec_from_file_location("_l6", ROOT / "tools" / "l6_statistics.py")
        l6 = importlib.util.module_from_spec(spec)
        sys.modules["_l6"] = l6
        spec.loader.exec_module(l6)
        panel, _ = l6.load_inputs(args.n_codes, args.start, args.end)   # 自带 cap + 三层行业
    print(f"面板：{panel['close'].shape[1]} 只 × {panel['close'].shape[0]} 交易日（{args.panel}）")
    long_table = to_reference_long(panel)
    names = [f"alpha{n}" for n in numbers]
    reference = run_reference(long_table, names)

    aligned = apply_second_reference_alignments(panel)
    outcomes = compare(aligned, reference, max(numbers))
    outcomes = [o for o in outcomes if int(o["factor"][5:]) in set(numbers)]

    table = pd.DataFrame(outcomes)
    table.to_csv(args.out, index=False)
    print(f"\n参照：{REFERENCE['name']} {REFERENCE['version']}（{REFERENCE['license']}）")
    print(f"对拍 {len(table)} 个因子 → {args.out}")
    summary = table["verdict"].value_counts().to_dict()
    for verdict, count in summary.items():
        print(f"  {verdict}：{count}")
    unresolved = table[table["verdict"] == "待查"]
    if not unresolved.empty:
        print("\n待查（需要继续归因，不允许豁免）：")
        print(unresolved.to_string(index=False))
    return 0 if unresolved.empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
