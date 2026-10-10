"""M4 因子级差分对拍的门禁（L3）。

* 参照缺失（无 ``.vnpy-ref/``）时整体跳过——差分是**可选证据层**，不是运行依赖；
* 合成面板对拍必须 **0 个「实偏差（待查）」**：一致或已归因；
* 19 个「无法差分」的缺口必须与 vnpy 参照里**未实现**的因子集合完全一致（防文档漂移）；
* 真实面板对拍（可选）：连续行情下不应再出现「离散平局被浮点噪声打破」这一类差异。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REF_DIR = ROOT / ".vnpy-ref"
SMOKE_TIMEOUT = 1800

pytestmark = pytest.mark.skipif(
    not (REF_DIR / "vnpy/alpha/dataset/datasets/alpha_101.py").exists(),
    reason="缺少 .vnpy-ref 参照；运行 `bash tools/fetch_vnpy_reference.sh` 获取（MIT，仅测试期使用）",
)


def _run(*args: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "factor_differential.py"), *args],
        cwd=ROOT, capture_output=True, text=True, timeout=SMOKE_TIMEOUT,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"差分对拍存在「待查」项：\n{output}"
    return output


def test_synthetic_differential_has_no_unexplained_deviation():
    """合成面板：82 个可比因子全部「一致」或「已归因」，不得出现待查项。"""
    output = _run("--quiet")
    assert "实偏差（待查）" not in output, output
    assert "一致" in output, output


def test_not_comparable_set_matches_the_reference():
    """19 个缺口 = vnpy 未实现的 19 个因子（18 个 IndNeutralize + alpha56），逐一对齐。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_fd", ROOT / "tools/factor_differential.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_fd"] = module
    spec.loader.exec_module(module)

    expressions = module.load_expressions()
    implemented = set(expressions)
    gaps = {n for n in range(1, 102) if n not in implemented}
    assert len(implemented) == 82, f"vnpy 参照的实现数变了：{len(implemented)}"
    assert gaps == set(module.NOT_COMPARABLE), f"缺口集合与声明的 19 个不一致：{sorted(gaps)}"
    # 缺口必须全部是「含 IndNeutralize」或 alpha56（cap）
    import re

    source = (REF_DIR / "vnpy/alpha/dataset/datasets/alpha_101.py").read_text(encoding="utf-8")
    for number in gaps:
        if number == 56:
            continue
        block = re.search(rf"# Alpha{number} \(([^)]*)\)", source)
        assert block and "IndNeutralize" in block.group(1), f"alpha{number} 的缺口原因不是 IndNeutralize"


def test_real_panel_differential_is_clean_when_database_available():
    """真实连续行情对拍（可选）：平局几乎不存在 ⇒ 不应出现「同值不同配」这类数值差异。"""
    try:
        import pymongo
    except ImportError:  # pragma: no cover
        pytest.skip("未安装 pymongo")
    try:
        client = pymongo.MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=1500)
        client.admin.command("ping")
        client.close()
    except Exception:  # pragma: no cover
        pytest.skip("本地 MongoDB 不可用")

    # 大面板上全量跑 82 个因子耗时过长（rolling.apply 类算子），这里定点核查
    # 「离散平局/数值病态」这一类的 14 个因子（它们正是在真实行情下最容易出差异的集合）。
    import importlib.util

    spec = importlib.util.spec_from_file_location("_fd_real", ROOT / "tools/factor_differential.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_fd_real"] = module
    spec.loader.exec_module(module)
    targets = ",".join(str(n) for n in sorted(module.NUMERICAL_TIE_CLASS))
    output = _run(
        "--panel", "real", "--n-codes", "60", "--start", "2023-01-03", "--end", "2024-03-29",
        "--alphas", targets, "--quiet",
    )
    assert "实偏差（待查）" not in output, output
