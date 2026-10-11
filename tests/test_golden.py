"""L5 golden 快照门禁（M5，设计文档 §6.6）。

判据（与 `tools/golden_snapshot.py` 一致）：

* **NaN 模式必须完全一致**（哪一格有值、哪一格没有，都不许变）；
* 数值 `allclose(rtol=1e-9, atol=1e-12)`；
* 逐因子 sha256 不一致但数值一致 ⇒ 只算「漂移提示」（跨 pandas 版本的末位差属正常，CI 还跑依赖矩阵）。

⚠️ **golden 只防回归，不证明正确性**：它是「昨天与今天一致」的证据，正确性由 L1–L4 负责。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "tests" / "golden"


def _tool():
    """加载 golden 工具（与 `tools/` 目录里其它工具同样的用法）。"""
    spec = importlib.util.spec_from_file_location("_golden_snapshot", ROOT / "tools/golden_snapshot.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_golden_snapshot"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def golden():
    tool = _tool()
    assert (GOLDEN_DIR / "manifest.json").exists(), "缺少 golden 基线：先跑 tools/golden_snapshot.py --write"
    return tool


def test_golden_baseline_matches_current_implementation(golden):
    """★ 核心门禁：当前实现的 101 个因子输出必须与冻结基线一致（NaN 模式 + 数值）。"""
    failures, notices = golden.compare()
    assert not failures, "golden 快照不一致（可能是无意的算法改动或依赖漂移）：\n" + "\n".join(
        f"  - {item}" for item in failures[:15]
    )
    # 漂移提示不算失败，但必须能被看到（CI 日志里会打印）
    assert isinstance(notices, list)


def test_golden_covers_all_101_factors(golden):
    """基线必须覆盖全部 101 个因子（缺一个就等于那一个没被保护）。"""
    _, values, manifest = golden.load_baseline()
    assert set(values) == {f"alpha{n}" for n in range(1, 102)}
    assert set(manifest["factors"]) == set(values)
    assert len(values) == 101


def test_golden_panel_exercises_the_longest_windows(golden):
    """**选 320 天而不是 250 天的理由必须可验证**：最长窗口（250 日）的因子在基线上要有值。

    若哪天有人把面板缩回 5×250，这些因子会整片 NaN —— 本测试会立刻失败并要求说明。
    """
    _, values, _ = golden.load_baseline()
    for name in ("alpha19", "alpha24", "alpha37", "alpha39", "alpha48", "alpha52"):
        finite = int(np.isfinite(values[name]).sum())
        assert finite > 100, f"{name} 在 golden 基线上只有 {finite} 个有效格（长窗口没被覆盖）"


def test_golden_manifest_records_environment_and_reproduction(golden):
    """清单必须记下环境、面板参数与生成命令 —— 否则基线不可复现、也没法解释漂移。"""
    manifest = json.loads((GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generated_by"] == "python tools/golden_snapshot.py --write"
    assert manifest["panel"]["seed"] == golden.PANEL_SEED
    assert (manifest["panel"]["days"], manifest["panel"]["names"]) == (golden.PANEL_DAYS, golden.PANEL_NAMES)
    assert "deviation_from_design_doc" in manifest["panel"], "必须写明与设计文档 §6.6 示例的偏离理由"
    assert set(manifest["environment"]) == {"python", "numpy", "pandas", "scipy"}
    assert set(manifest["panel"]["sha256"]) == set(golden.NUMERIC_FIELDS)
    # 面板文件与数值文件都必须随基线一起入库（别人 clone 后能独立复算）
    assert (GOLDEN_DIR / "panel.npz").exists()
    assert (GOLDEN_DIR / "factor_values.npz").exists()


def test_golden_baseline_is_deterministic(golden):
    """面板生成必须逐位可复现（否则基线本身就是噪声）。"""
    first = golden.build_panel()
    second = golden.build_panel()
    for field in golden.NUMERIC_FIELDS:
        # equal_nan=True：`returns` 首行本来就是 NaN，而 np.array_equal 默认把 NaN 视作不等
        assert np.array_equal(
            first[field].to_numpy(), second[field].to_numpy(), equal_nan=True
        ), f"{field} 两次生成不一致"
