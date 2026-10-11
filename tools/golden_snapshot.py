#!/usr/bin/env python
"""golden 快照：生成与校验（设计文档 §6.6 的 L5 门槛）。

为什么需要它
------------
L1（解析期望值 + 权威实现对拍）能证明**今天**算得对；L5 冻结基线能证明**明天还一样**——
pandas/numpy 升级、一次无意的重构、甚至算子默认值的误改，都会在 CI 里当场暴露。
**它只防回归，不证明正确性**（正确性由 L1–L4 负责），这是必须写明的边界。

基线约定
--------
* 面板：固定种子 **5 只股票 × 320 交易日**（对设计文档 §6.6 举例的「5×250」是**有意偏离**：
  250 日正是 A101 的最长窗口，5×250 会让 alpha19/39/48 这类因子整片 NaN，等于没冻结）；
* 冻结对象：101 个因子的输出矩阵（float64）+ 面板哈希 + 逐因子 sha256 + 环境版本；
* 判据（见 :func:`compare`）：**NaN 模式必须完全一致** + 数值 `allclose(rtol, atol)`；
  哈希不一致但数值一致 ⇒ 只报「漂移提示」（跨 pandas 版本的末位差属正常，见 CI 的依赖矩阵）。

用法::

    python tools/golden_snapshot.py --write     # 重新生成基线（**改了算法默认值才做**，需在 PR 里说明）
    python tools/golden_snapshot.py --check     # 校验当前实现与基线一致（CI 用）
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

GOLDEN_DIR = ROOT / "tests" / "golden"
VALUES_PATH = GOLDEN_DIR / "factor_values.npz"
PANEL_PATH = GOLDEN_DIR / "panel.npz"
MANIFEST_PATH = GOLDEN_DIR / "manifest.json"

#: 面板规模（对 §6.6 示例的有意偏离，理由见模块文档串）
PANEL_DAYS = 320
PANEL_NAMES = 5
PANEL_SEED = 20261010
RTOL, ATOL = 1e-9, 1e-12

#: 面板里的数值字段（与 factors 的形参名一致）
NUMERIC_FIELDS = ("close", "Open", "high", "low", "volume", "amount", "vwap", "returns", "cap")
#: 三个行业层级（论文 IndClass.sector/industry/subindustry）
LABEL_FIELDS = ("ind_sector", "ind_industry", "ind_subindustry")


def build_panel() -> dict[str, object]:
    """确定性合成面板：同一 (seed, days, names) 必须逐位可复现。"""
    rng = np.random.default_rng(PANEL_SEED)
    index = pd.date_range("2021-01-04", periods=PANEL_DAYS, freq="B")
    columns = [f"S{i}" for i in range(PANEL_NAMES)]
    shape = (PANEL_DAYS, PANEL_NAMES)

    walk = np.cumsum(rng.normal(0.0, 0.015, size=shape), axis=0)
    rotation = np.sin(
        2 * np.pi * (np.arange(PANEL_DAYS)[:, None] / 7.0 + np.arange(PANEL_NAMES)[None, :] / PANEL_NAMES)
    )
    close = pd.DataFrame(
        30.0 * np.exp(walk + 0.05 * rotation + 0.01 * rng.normal(size=shape)), index=index, columns=columns
    )
    open_ = pd.DataFrame(close.to_numpy() * (1 + rng.normal(0, 0.004, size=shape)), index=index, columns=columns)
    high = pd.DataFrame(
        np.maximum(close.to_numpy(), open_.to_numpy()) * (1 + np.abs(rng.normal(0, 0.004, size=shape))),
        index=index, columns=columns,
    )
    low = pd.DataFrame(
        np.minimum(close.to_numpy(), open_.to_numpy()) * (1 - np.abs(rng.normal(0, 0.004, size=shape))),
        index=index, columns=columns,
    )
    volume = pd.DataFrame(np.exp(rng.normal(np.log(2e5), 0.6, size=shape)), index=index, columns=columns)
    amount = volume * 100.0 * close
    panel: dict[str, object] = {
        "close": close, "Open": open_, "high": high, "low": low, "volume": volume,
        "amount": amount, "vwap": amount / (volume * 100.0),
        "returns": close.pct_change(fill_method=None),
        "cap": pd.DataFrame(np.abs(rng.normal(1e6, 2e5, size=shape)) + 1.0, index=index, columns=columns),
    }
    sectors = ["金融", "制造"]
    industries = ["银行", "医药", "电子"]
    subindustries = ["城商行", "创新药", "半导体", "白电"]
    panel["ind_sector"] = pd.Series([sectors[i % len(sectors)] for i in range(PANEL_NAMES)], index=columns)
    panel["ind_industry"] = pd.Series([industries[i % len(industries)] for i in range(PANEL_NAMES)], index=columns)
    panel["ind_subindustry"] = pd.Series(
        [subindustries[i % len(subindustries)] for i in range(PANEL_NAMES)], index=columns
    )
    return panel


def factor_values(panel: dict[str, object]) -> dict[str, np.ndarray]:
    """在当前实现下算出 101 个因子的输出（NaN 保持 NaN，不做任何填充）。"""
    from alpha101v import registry  # noqa: PLC0415

    values: dict[str, np.ndarray] = {}
    for name in sorted(registry.REGISTRY):
        out = registry.run_factor(name, panel)
        values[name] = np.ascontiguousarray(out.to_numpy(dtype=np.float64))
    return values


def _hash_array(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array, dtype=np.float64).tobytes()).hexdigest()


def environment() -> dict[str, str]:
    import scipy  # noqa: PLC0415

    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
    }


def write_baseline() -> dict[str, object]:
    """生成并落盘基线（npz 数值 + 面板 + manifest）。"""
    panel = build_panel()
    values = factor_values(panel)
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    numeric = {field: panel[field].to_numpy(dtype=np.float64) for field in NUMERIC_FIELDS}  # type: ignore[union-attr]
    index = panel["close"].index  # type: ignore[union-attr]
    labels = {field: np.asarray(panel[field].to_numpy(), dtype=str) for field in LABEL_FIELDS}  # type: ignore[union-attr]
    np.savez_compressed(
        PANEL_PATH,
        index=np.asarray([str(day) for day in index], dtype="datetime64[D]"),
        columns=np.asarray([str(c) for c in panel["close"].columns]),  # type: ignore[union-attr]
        **numeric, **labels,
    )
    np.savez_compressed(VALUES_PATH, **values)

    manifest = {
        "what": "L5 golden 快照：101 个因子输出的冻结基线（只防回归，不证明正确性）",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "generated_by": "python tools/golden_snapshot.py --write",
        "panel": {
            "days": PANEL_DAYS, "names": PANEL_NAMES, "seed": PANEL_SEED,
            "deviation_from_design_doc": (
                "设计文档 §6.6 举例 5×250；本基线用 5×320，因为 250 日正是 A101 最长窗口，"
                "5×250 会让 alpha19/39/48 等在基线上整片 NaN（等于没冻结）"
            ),
            "sha256": {field: _hash_array(numeric[field]) for field in NUMERIC_FIELDS},
            "labels": {field: list(map(str, labels[field])) for field in LABEL_FIELDS},
        },
        "factors": {name: _hash_array(array) for name, array in sorted(values.items())},
        "gate": {
            "nan_pattern": "必须完全一致",
            "values": f"allclose(rtol={RTOL}, atol={ATOL})",
            "hash": "不一致但数值一致 ⇒ 只报「漂移提示」（跨 pandas 版本末位差属正常）",
        },
        "environment": environment(),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_baseline() -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], dict]:
    panel_file = np.load(PANEL_PATH, allow_pickle=False)
    values_file = np.load(VALUES_PATH, allow_pickle=False)
    panel = {field: panel_file[field] for field in NUMERIC_FIELDS}
    values = {name: values_file[name] for name in values_file.files}
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return panel, values, manifest


def compare() -> tuple[list[str], list[str]]:
    """返回 (失败项, 提示项)。失败 = NaN 模式不同或数值超出容差。"""
    failures: list[str] = []
    notices: list[str] = []
    panel_arrays, baseline_values, manifest = load_baseline()

    panel = build_panel()
    for field in NUMERIC_FIELDS:
        current = panel[field].to_numpy(dtype=np.float64)  # type: ignore[union-attr]
        if _hash_array(current) != manifest["panel"]["sha256"][field]:
            failures.append(f"面板字段 {field} 与基线不一致（生成过程不再确定性？）")

    values = factor_values(panel)
    if set(values) != set(baseline_values):
        missing = sorted(set(baseline_values) - set(values))
        extra = sorted(set(values) - set(baseline_values))
        failures.append(f"因子集合与基线不同：缺 {missing}，多 {extra}")

    for name in sorted(set(values) & set(baseline_values)):
        current, baseline = values[name], baseline_values[name]
        if current.shape != baseline.shape:
            failures.append(f"{name}: 形状 {current.shape} ≠ 基线 {baseline.shape}")
            continue
        current_nan, baseline_nan = np.isnan(current), np.isnan(baseline)
        if not np.array_equal(current_nan, baseline_nan):
            failures.append(
                f"{name}: NaN 模式变化（新增 {int((~current_nan & baseline_nan).sum())} 格、"
                f"消失 {int((current_nan & ~baseline_nan).sum())} 格）"
            )
            continue
        keep = ~current_nan
        if not np.allclose(current[keep], baseline[keep], rtol=RTOL, atol=ATOL):
            delta = float(np.max(np.abs(current[keep] - baseline[keep]))) if keep.any() else 0.0
            failures.append(f"{name}: 数值超出容差（max|Δ| = {delta:.3g}）")
        elif _hash_array(current) != manifest["factors"][name]:
            notices.append(f"{name}: 数值在容差内但哈希不同（末位漂移，通常是依赖版本差异）")
    return failures, notices


def main() -> int:
    parser = argparse.ArgumentParser(description="L5 golden 快照（生成 / 校验）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="重新生成基线")
    group.add_argument("--check", action="store_true", help="校验当前实现与基线一致")
    args = parser.parse_args()

    if args.write:
        manifest = write_baseline()
        print(f"✅ 基线已写入 {GOLDEN_DIR}")
        print(f"   面板 {PANEL_NAMES}×{PANEL_DAYS}（seed {PANEL_SEED}）；因子 {len(manifest['factors'])} 个")
        print(f"   环境 {manifest['environment']}")
        return 0

    failures, notices = compare()
    if notices:
        print(f"ℹ️ 漂移提示 {len(notices)} 项（数值一致，哈希不同）：")
        for item in notices[:5]:
            print(f"   - {item}")
    if failures:
        print(f"❌ golden 校验失败 {len(failures)} 项：")
        for item in failures[:20]:
            print(f"   - {item}")
        return 1
    print("✅ golden 校验通过：NaN 模式与数值都与基线一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
