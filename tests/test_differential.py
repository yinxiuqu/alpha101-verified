"""vnpy 算子层差分对拍（测试包装）。

参照是 vnpy（MIT）的 ``cs_function.py`` / ``ts_function.py``，由
``tools/fetch_vnpy_reference.sh`` 下载到 gitignored 的 ``.vnpy-ref/``（**不入库**）。
参照缺失时本文件自动跳过（CI 不会因为缺少第三方参照而变红），
因此它是**本地/发布前**的 L3 证据，而不是 CI 门禁。

断言的是「结论与文档一致」，而不是某个固定数值：
* 每条**对齐后**对拍必须逐点一致（含 argmax 基准、ts_rank 口径、decay 方向对齐后）；
* 每条**已归因口径差异**必须**确实存在差异**（防止 vnpy 上游改了、文档却还写着旧结论）。
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "differential.py"
FETCH_SCRIPT = ROOT / "tools" / "fetch_vnpy_reference.sh"
REF_DIR = ROOT / ".vnpy-ref"

pytestmark = pytest.mark.skipif(
    not (REF_DIR / "vnpy/alpha/dataset/ts_function.py").exists(),
    reason="缺少 vnpy 参照源码：先运行 `bash tools/fetch_vnpy_reference.sh`（MIT，仅测试期对拍）",
)


def _verdict(output: str, check_name: str) -> str:
    """从对拍表格里取出某一项的判定列。"""
    for line in output.splitlines():
        if line.startswith(f"| `{check_name}` |"):
            return line.split("|")[2].strip()
    raise AssertionError(f"对拍表中没有找到 {check_name!r} 这一项")


def test_differential_has_no_unexplained_differences():
    proc = subprocess.run(
        [sys.executable, str(TOOL)], cwd=ROOT, capture_output=True, text=True
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"差分出现「待查」项或工具异常：\n{output}"
    assert "待查 0 项" in output


def test_aligned_operators_match_vnpy_pointwise():
    """对齐口径后必须逐点一致的部分（这是「本库算子算得对」的第三方证据）。"""
    proc = subprocess.run([sys.executable, str(TOOL)], cwd=ROOT, capture_output=True, text=True)
    output = proc.stdout
    for name in (
        "ts_sum(x,5)",
        "delta(x,3)",
        "delay(x,3)",
        "product(x,5)",
        "sma(x,5)",
        "stddev(x,5,ddof=0)",
        "ts_min(x,5)",
        "ts_max(x,5)",
        "ts_argmax(x,5)",
        "ts_argmin(x,5)",
        "ts_rank(x,5,one_over_n)",
        "correlation(x,y,5)",
        "covariance(x,y,5,ddof=0)",
        'decay_linear(x,5,order="oldest_first")',
        "scale(x,1)",
        'rank(x,method="min",one_over_n) [并列面板]',
        "rank(x,one_over_n) [无并列面板]",
        "stddev(x,5) 默认 [D2 已消失] vs vnpy",
    ):
        assert _verdict(output, name) == "一致（逐点）", f"{name} 未与 vnpy 逐点一致"


def test_documented_differences_still_exist():
    """6 条已归因口径差异必须**实测存在**（否则文档成了空话，应同步更新）。"""
    proc = subprocess.run([sys.executable, str(TOOL)], cwd=ROOT, capture_output=True, text=True)
    output = proc.stdout
    for name in (
        "D1 decay_linear 默认(recent_first) vs vnpy",
        "D3 严格预热 vs vnpy 填值（ts_min）",
        "D4 rank 默认(average) vs vnpy(min) [并列面板]",
        "D5 scale 零和行 vs vnpy",
        "D6 sma（NaN 洞）vs vnpy ts_mean",
        "D7 rank 默认(zero_to_one) vs vnpy(one_over_n)",
        "D7b ts_rank 默认(zero_to_one) vs vnpy(one_over_n)",
        "D8 decay_linear 稀疏(NaN→0) vs vnpy [NaN 洞]",
    ):
        assert _verdict(output, name) == "有差异", f"{name} 的差异消失了，请更新文档与归因"


def test_reference_files_match_recorded_sha256():
    """参照文件必须与 fetch 脚本记录的 SHA256 一致（防止对拍结论建立在另一个版本上）。"""
    text = FETCH_SCRIPT.read_text(encoding="utf-8")
    entries = re.findall(r"^(\S+\.py)\s+([0-9a-f]{64})\s*$", text, re.MULTILINE)
    assert entries, "fetch 脚本里没有解析到 SHA256 记录"
    for rel, expected in entries:
        path = REF_DIR / "vnpy/alpha/dataset" / rel
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, f"{rel} 与记录的 SHA256 不符：上游可能已改动"
