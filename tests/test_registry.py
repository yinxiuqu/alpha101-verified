"""因子注册与自动装配机制（设计文档 §7.5）——机制本身也必须有测试。

★ 本轮（M0/M1）注册表必须为空：因子层是 M2/M3 的工作，
「假装有因子」会直接摧毁本项目「可验证」的定位。断言见
:func:`test_registry_is_empty_in_m1`。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alpha101v import registry

_IDX = pd.date_range("2020-01-06", periods=4, freq="B")
_COLS = list("AB")


@pytest.fixture
def clean_registry():
    """快照并清空注册表，避免测试之间互相污染（也保护「M1 无因子」的断言）。"""
    saved = dict(registry.REGISTRY)
    registry.REGISTRY.clear()
    try:
        yield registry.REGISTRY
    finally:
        registry.REGISTRY.clear()
        registry.REGISTRY.update(saved)


def _panel() -> dict[str, pd.DataFrame]:
    close = pd.DataFrame(
        [[10.0, 20.0], [11.0, 19.0], [12.0, 18.0], [13.0, 17.0]], index=_IDX, columns=_COLS
    )
    volume = pd.DataFrame(
        [[100.0, 200.0], [110.0, 190.0], [120.0, 180.0], [130.0, 170.0]], index=_IDX, columns=_COLS
    )
    return {"close": close, "volume": volume}


def test_registry_holds_all_101_factors():
    """M3：导入即注册 101 个因子；状态只有 partial/ambiguous，**绝无 verified**（§6.8）。"""
    import alpha101v.factors  # noqa: F401  （导入即注册）

    assert len(registry.REGISTRY) == 101
    assert set(registry.REGISTRY) == {f"alpha{n}" for n in range(1, 102)}
    report = registry.status_report()
    assert list(report.columns) == ["factor", "status", "fields", "paper_ref", "notes"]
    # L-B（BRAIN 官方文档）定案后 ambiguous 清零，只剩 partial；verified 仍待 M5 golden 快照
    assert set(report["status"]) == {"partial"}
    assert (report["paper_ref"].str.contains("Appendix A")).all()


def test_register_and_auto_wire_by_parameter_name(clean_registry):
    """形参名即面板字段名：无需 101 条映射表（§7.5）。"""

    def demo(close, volume):
        return close / volume

    meta = registry.register("demo", demo, paper_ref="论文 §X 公式 Y", status="partial")
    assert meta.params == ("close", "volume")

    panel = _panel()
    out = registry.run_factor("demo", panel)
    pd.testing.assert_frame_equal(out, panel["close"] / panel["volume"])


def test_run_factor_deep_copies_inputs(clean_registry):
    """★ §7.5 前提①：因子内部原地改写入参，不得污染调用方面板。"""

    def in_place(close):
        close.iloc[0, 0] = -999.0
        return close

    registry.register("in_place", in_place)
    panel = _panel()
    snapshot = panel["close"].copy(deep=True)

    out = registry.run_factor("in_place", panel)

    pd.testing.assert_frame_equal(panel["close"], snapshot)  # 调用方面板一字未变
    assert out.iloc[0, 0] == -999.0  # 因子拿到的是自己的副本


def test_run_factor_can_opt_out_of_copying(clean_registry):
    """``copy_inputs=False`` 是显式的性能取舍，代价必须可见（写出去了就是写出去了）。"""

    def in_place(close):
        close.iloc[0, 0] = -1.0
        return close

    registry.register("in_place2", in_place)
    panel = _panel()
    registry.run_factor("in_place2", panel, copy_inputs=False)
    assert panel["close"].iloc[0, 0] == -1.0


def test_run_factor_requires_all_declared_fields(clean_registry):
    def needs_cap(close, cap):
        return close / cap

    registry.register("needs_cap", needs_cap)
    with pytest.raises(KeyError, match="cap"):
        registry.run_factor("needs_cap", _panel())


def test_run_factor_unknown_name_raises(clean_registry):
    with pytest.raises(KeyError, match="未注册的因子"):
        registry.run_factor("alpha999", _panel())


def test_register_rejects_var_args_and_kwargs(clean_registry):
    """``*args/**kwargs`` 无法按名装配面板，注册时就该拒绝。"""
    with pytest.raises(TypeError, match="args"):
        registry.register("bad", lambda *args: None)
    with pytest.raises(TypeError, match="args"):
        registry.register("bad2", lambda **kwargs: None)


def test_register_rejects_duplicate_and_bad_status(clean_registry):
    registry.register("dup", lambda close: close)
    with pytest.raises(ValueError, match="已注册"):
        registry.register("dup", lambda close: close)
    registry.register("dup", lambda close: close, overwrite=True)  # 显式覆盖可以
    with pytest.raises(ValueError, match="status"):
        registry.register("weird", lambda close: close, status="大概对")


def test_status_report_lists_registered_factors(clean_registry):
    registry.register("a1", lambda close: close, paper_ref="eq.1", status="verified")
    registry.register("a2", lambda close, volume: close, paper_ref="eq.2", status="ambiguous")
    report = registry.status_report()
    assert list(report["factor"]) == ["a1", "a2"]
    assert list(report["status"]) == ["verified", "ambiguous"]
    assert set(report["status"]) <= set(registry.STATUS_VALUES)


def test_registry_metadata_is_immutable(clean_registry):
    meta = registry.register("frozen", lambda close: close)
    with pytest.raises(Exception):
        meta.status = "verified"  # type: ignore[misc]
