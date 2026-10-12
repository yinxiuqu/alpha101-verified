"""美股验证工具的**纯逻辑**测试（不联网、不需要 tushare 额度）。

两件最容易出错的事在这里钉死：
1. **删除审计**：确实删干净、并把「删了什么/多大/是否为空」写进审计文件；
2. **拆股调整**：tushare 的 `us_daily` 是**未复权**价，若不修正，拆股当天会冒出 −75% 的假暴跌，
   会把所有含 `delta/returns/stddev` 的因子毁掉。工具用 `pre_close` 反推拆股因子——
   这个反推逻辑必须有测试（且明确**不修分红**）。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location("_us_verify", ROOT / "tools" / "us_data_verification.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_us_verify"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def tool(tmp_path, monkeypatch):
    module = _tool()
    monkeypatch.setattr(module, "DATA_DIR", tmp_path / "us_verify")
    monkeypatch.setattr(module, "AUDIT_PATH", tmp_path / "audit.md")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


def test_delete_and_audit_removes_everything_and_records_it(tool):
    """删除阶段：文件与目录都清掉，审计写明确的数量与大小。"""
    tool.DATA_DIR.mkdir(parents=True)
    (tool.DATA_DIR / "daily_AAPL.parquet").write_bytes(b"x" * 2048)
    (tool.DATA_DIR / "daily_MSFT.parquet").write_bytes(b"y" * 1024)
    (tool.DATA_DIR / "sub").mkdir()
    (tool.DATA_DIR / "sub" / "extra.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    assert tool.delete_and_audit() == 0
    assert not tool.DATA_DIR.exists(), "数据目录必须被删掉（含空子目录）"
    audit = tool.AUDIT_PATH.read_text(encoding="utf-8")
    assert "3 个文件" in audit, audit
    assert "已不存在" in audit
    for name in ("daily_AAPL.parquet", "daily_MSFT.parquet", "extra.csv"):
        assert name in audit, f"审计里应逐项列出删掉的文件：{name}"


def test_delete_audit_is_honest_when_nothing_to_delete(tool):
    """没有数据时也要出审计（如实写「无文件可删」），而不是静默通过。"""
    assert tool.delete_and_audit() == 0
    audit = tool.AUDIT_PATH.read_text(encoding="utf-8")
    assert "无文件可删" in audit


def _write_daily(tool, code: str, closes: list[float], pre_closes: list[float], dates=None) -> None:
    tool.DATA_DIR.mkdir(parents=True, exist_ok=True)
    dates = dates or [f"2024{1 + i // 28:02d}{1 + i % 28:02d}" for i in range(len(closes))]
    pd.DataFrame({
        "ts_code": code, "trade_date": dates, "open": closes, "high": closes, "low": closes,
        "close": closes, "pre_close": pre_closes, "vol": 1e6, "amount": [c * 1e6 for c in closes],
        "vwap": closes,
    }).to_parquet(tool.DATA_DIR / f"daily_{code}.parquet", index=False)


def test_split_adjustment_removes_the_fake_crash(tool):
    """★ 拆股反推：4:1 拆股当天 `pre_close = 上一日 close / 4` ⇒ 调整后不应出现假暴跌。"""
    closes = [400.0, 404.0, 100.0, 101.0, 102.0]           # 拆股：400 → 100
    pre_closes = [400.0, 400.0, 101.0, 100.0, 101.0]        # 拆股日 pre_close = 404/4 ≈ 101
    _write_daily(tool, "TEST", closes, pre_closes)

    panel = tool.build_panel()
    returns = panel["returns"]["TEST"].dropna().to_numpy()
    assert np.all(np.abs(returns) < 0.05), f"调整后不该有假暴跌，实测 {returns}"
    # 后复权：拆股后的价格被放大 4 倍（首段保持原值）⇒ 复权因子末尾/开头 = 4
    adjusted, raw = panel["close"]["TEST"].to_numpy(), np.array(closes)
    factor = adjusted / raw
    assert np.isclose(factor[-1] / factor[0], 4.0, rtol=1e-9), factor
    assert np.allclose(factor[:2], 1.0) and np.allclose(factor[2:], 4.0)


def test_split_adjustment_does_not_touch_normal_days(tool):
    """正常日 `pre_close == 上一日 close` ⇒ 调整因子恒为 1，价格原样保留。"""
    closes = [100.0, 101.0, 99.5, 103.0]
    _write_daily(tool, "NORM", closes, [100.0, 100.0, 101.0, 99.5])
    panel = tool.build_panel()
    np.testing.assert_allclose(panel["close"]["NORM"].to_numpy(), closes, rtol=1e-12)


def test_split_adjustment_is_documented_as_not_fixing_dividends(tool):
    """分红不修：这是**已知且写明**的口径（`pre_close` 里含分红时会被当成比值吸收，但工具文档须说明）。"""
    source = (ROOT / "tools" / "us_data_verification.py").read_text(encoding="utf-8")
    assert "修不掉分红" in source or "不修分红" in source
