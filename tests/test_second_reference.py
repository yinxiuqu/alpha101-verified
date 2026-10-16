"""第二独立参照差分工具的**纯逻辑**测试（不需要参照 venv、不联网）。

这里钉住四件事，都是实测踩过的坑：

1. 「小数窗口」候选的提取规则（不能把 `0.001`、`1.5` 这类常数当成窗口）；
2. 「round≠floor 才算冲突」——相同就没有差异；
3. 参照的 rank 是 **0..n−1**，本库 `ordinal` 是 **1..n** ⇒ 必须减 1 才可比；
4. 缺失参照环境时要**明确报错**，而不是抛一个看不懂的异常。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]



def _has_parquet_engine() -> bool:
    """本模块的夹具要用 parquet 写临时面板；引擎缺失时**显式跳过**而不是抛 ImportError。

    实测：CI runner 上 pandas 找不到 pyarrow/fastparquet 时，报的是
    `ImportError: Unable to find a usable engine`，看起来像测试坏了，其实是环境缺件。
    """
    for module in ("pyarrow", "fastparquet"):
        try:
            __import__(module)
            return True
        except ImportError:
            continue
    return False


pytestmark = pytest.mark.skipif(
    not _has_parquet_engine(),
    reason="需要 parquet 引擎（pyarrow 或 fastparquet）写临时面板；环境缺件时显式跳过",
)


REFERENCE_VENV_MISSING = not (ROOT / ".refs" / "venv-ref" / "bin" / "python").exists()
_NEEDS_VENV = pytest.mark.skipif(
    REFERENCE_VENV_MISSING,
    reason="第二参照的独立 venv 不存在（.refs/venv-ref，约 254MB、可随时用 "
           "bash tools/fetch_second_reference.sh 重建）；缺它时显式跳过而非报错",
)

def _tool():
    spec = importlib.util.spec_from_file_location("_second_ref", ROOT / "tools" / "second_reference_differential.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_second_ref"] = module
    spec.loader.exec_module(module)
    return module


def test_window_candidates_exclude_small_constants():
    """`0.001`（防零项）、`1.5`（系数）都不是窗口；≥2.5 的小数才算窗口候选。"""
    tool = _tool()
    expression = "(close - open) / ((high - low) + 0.001) * 1.5 + ts_rank(close, 3.43976)"
    assert tool.fractional_window_constants(expression) == [3.43976]


@_NEEDS_VENV
def test_rounding_conflict_requires_round_to_differ_from_floor():
    """4.25197 的 round 和 floor 都是 4 ⇒ 无差异，不算冲突；9.78759 ⇒ 10 vs 9 ⇒ 冲突。"""
    tool = _tool()
    conflicts = tool.rounding_conflict_expressions({"a": "ts_rank(close, 4.25197)", "b": "ts_rank(close, 9.78759)"})
    assert conflicts["a"] == []
    assert conflicts["b"] == [9.78759]


@_NEEDS_VENV
def test_rank_alignment_shifts_ordinal_to_zero_based():
    """★ 参照 rank 是 0..n−1；本库 ordinal 是 1..n ⇒ 对齐后必须减 1（否则 rank 相乘的因子全错）。"""
    tool = _tool()
    frame = pd.DataFrame([[10.0, 20.0, 30.0, 5.0]])
    snapshot = (tool.factors.rank, tool.factors.ts_rank, tool.factors.stddev,
                tool.factors.decay_linear, tool.factors.ts_argmax, tool.factors.ts_argmin,
                getattr(tool.factors, "power", None))
    try:
        tool.apply_second_reference_alignments({"close": frame})
        patched = tool.factors.rank(frame)
        assert patched.to_numpy().tolist() == [[1.0, 2.0, 3.0, 0.0]], "0..n−1 才对"
    finally:
        (tool.factors.rank, tool.factors.ts_rank, tool.factors.stddev,
         tool.factors.decay_linear, tool.factors.ts_argmax, tool.factors.ts_argmin, power) = snapshot
        if power is not None:
            tool.factors.power = power


@_NEEDS_VENV
def test_reference_long_table_columns_and_adv_alignment():
    """长表列名必须与参照的 `REQUIRED_SOURCE_COLUMNS` 对齐，且 `amount == volume*close`（adv 口径对齐）。"""
    tool = _tool()
    index = pd.date_range("2024-01-02", periods=4, freq="B")
    columns = ["A", "B"]
    close = pd.DataFrame([[10.0, 20.0]] * 4, index=index, columns=columns)
    volume = pd.DataFrame([[100.0, 200.0]] * 4, index=index, columns=columns)
    panel = {
        "close": close, "Open": close, "high": close * 1.01, "low": close * 0.99,
        "volume": volume, "vwap": close, "returns": close.pct_change(fill_method=None),
        "cap": pd.DataFrame([[1.0, 2.0]] * 4, index=index, columns=columns),
        "ind_sector": pd.Series(["S1", "S2"], index=columns),
        "ind_industry": pd.Series(["I1", "I2"], index=columns),
        "ind_subindustry": pd.Series(["U1", "U2"], index=columns),
    }
    table = tool.to_reference_long(panel)
    for required in ("date", "stock_id", "open", "high", "low", "close", "volume", "vwap", "cap",
                     "sector", "industry", "subindustry", "amount"):
        assert required in table.columns, f"缺列 {required}"
    assert np.allclose(table["amount"], table["volume"] * table["close"])
    assert set(table["stock_id"]) == {"A", "B"}


def test_missing_reference_environment_raises_clear_error(tmp_path, monkeypatch):
    """参照 venv 不存在时要给出**可执行**的提示，而不是抛底层异常。"""
    tool = _tool()
    monkeypatch.setattr(tool, "REFERENCE", {**tool.REFERENCE, "venv": tmp_path / "nope", "workdir": tmp_path})
    table = pd.DataFrame({"date": pd.to_datetime(["2024-01-02"]), "stock_id": ["A"], "close": [1.0]})
    with pytest.raises(SystemExit, match="fetch_second_reference"):
        tool.run_reference(table, ["alpha58"])


def test_window_verdict_is_not_an_attribution():
    """★ 回归实测教训：把小数窗口直接判成「已归因」是错的（floor 改写实验反而更差）⇒
    工具里必须保留「未证伪 / 待查」的措辞，防止有人再拿它当升级依据。"""
    source = (ROOT / "tools" / "second_reference_differential.py").read_text(encoding="utf-8")
    assert "未证伪" in source
    assert "已归因：小数窗口" not in source
