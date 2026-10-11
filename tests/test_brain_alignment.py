"""BRAIN 行为对齐的**工具正确性**测试（不需要网络、不需要凭据）。

对齐本身（需要平台 PnL）由人工在拿到数据后跑；这里只保证：统计口径正确、
凭据纪律（不接收命令行 cookie）、配额纪律（没有确认就不提交）。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "brain_alignment.py"


def _tool():
    spec = importlib.util.spec_from_file_location("_brain_alignment", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_brain_alignment"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def alignment():
    return _tool()


def _series(values) -> pd.Series:
    return pd.Series(values, index=pd.date_range("2023-01-03", periods=len(values), freq="B"))


def test_compare_pnl_detects_monotone_relationship(alignment):
    """严格单调的两条 PnL（含不同量纲）⇒ Spearman = 1；反号 ⇒ −1。"""
    rng = np.random.default_rng(23)
    platform = _series(rng.normal(size=80))
    local = 3.5 * platform                   # 正数倍：单调关系，量纲完全不同
    result = alignment.compare_pnl(local, platform)
    assert result["days"] == 80
    assert np.isclose(result["spearman"], 1.0)
    assert np.isclose(result["sign_agreement"], 1.0)
    # 注意：像 `3.5*x + 10` 这种**带常数平移**的序列，同号率会掉到 50% 附近——
    # 跨数据源的 PnL 本来就不同量纲，所以主判据是 Spearman（秩），不是同号率。
    shifted = alignment.compare_pnl(3.5 * platform + 10.0, platform)
    assert np.isclose(shifted["spearman"], 1.0)
    assert np.isclose(alignment.compare_pnl(-platform, platform)["spearman"], -1.0)


def test_compare_pnl_needs_enough_overlap(alignment):
    """共同交易日不足 10 天时不给结论（返回 NaN，而不是硬算一个数）。"""
    short = _series([0.1] * 5)
    result = alignment.compare_pnl(short, short)
    assert result["days"] == 5
    assert np.isnan(result["spearman"])


def test_compare_pnl_aligns_on_dates_not_positions(alignment):
    """两条序列只按**日期**对齐（错位不影响结果，缺日会被剔除）。"""
    rng = np.random.default_rng(29)
    platform = _series(rng.normal(size=60))
    local = platform.copy().iloc[10:]        # 少前 10 天
    result = alignment.compare_pnl(local, platform)
    assert result["days"] == 50
    assert np.isclose(result["spearman"], 1.0)


def test_load_platform_pnl_supports_csv_and_json(tmp_path, alignment):
    """平台导出的两种格式都能读：CSV（date,pnl）与 JSON（records / {date: pnl}）。"""
    csv_path = tmp_path / "pnl.csv"
    csv_path.write_text("date,pnl\n2023-01-03,0.001\n2023-01-04,-0.002\n", encoding="utf-8")
    from_csv = alignment.load_platform_pnl(csv_path)
    assert list(from_csv.round(4)) == [0.001, -0.002]

    json_path = tmp_path / "pnl.json"
    json_path.write_text(json.dumps({"records": [["2023-01-03", 0.001], ["2023-01-04", -0.002]]}), encoding="utf-8")
    from_json = alignment.load_platform_pnl(json_path)
    pd.testing.assert_series_equal(from_csv, from_json)

    mapping_path = tmp_path / "pnl_map.json"
    mapping_path.write_text(json.dumps({"2023-01-04": -0.002, "2023-01-03": 0.001}), encoding="utf-8")
    assert list(alignment.load_platform_pnl(mapping_path).round(4)) == [0.001, -0.002]


def test_cli_refuses_to_submit_without_explicit_quota_acknowledgement():
    """配额纪律：没有显式确认时，`--submit` 必须直接报错退出（绝不偷偷消耗用户配额）。"""
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--factor", "alpha5", "--submit"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "配额" in (proc.stdout + proc.stderr)


def test_cli_has_no_command_line_cookie_option():
    """凭据纪律：cookie 只能来自环境变量或文件，不接受命令行参数（避免进 shell 历史/日志）。"""
    source = TOOL.read_text(encoding="utf-8")
    assert '"--cookie"' not in source and "'--cookie'" not in source
    assert "BRAIN_COOKIE" in source
