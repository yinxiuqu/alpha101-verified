"""使用指南的**可维护性**测试：别让文档与实际能力悄悄脱节。

一个「给别人用」的项目，最容易腐烂的不是代码而是文档：
字段表抄错一行、链接指向删掉的文件、示例脚本改坏了没人发现。这里用机械手段守住三件事：

1. `docs/usage.md` 里的字段依赖表必须与**注册表**一致（由工具生成、可复算）；
2. 文档里的**本地链接**必须指向真实存在的文件；
3. 两个示例脚本必须**真的能跑通**。
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
USAGE = ROOT / "docs" / "usage.md"
FIELD_TOOL = ROOT / "tools" / "field_requirements.py"


def test_usage_doc_field_tables_match_the_registry():
    """★ 字段表由 `tools/field_requirements.py` 生成：文档与注册表必须一致（防抄错）。"""
    proc = subprocess.run(
        [sys.executable, str(FIELD_TOOL), "--check"], cwd=ROOT, capture_output=True, text=True
    )
    assert proc.returncode == 0, (
        "docs/usage.md 的字段表与注册表不一致；跑 `python tools/field_requirements.py --write` 更新\n"
        + proc.stdout + proc.stderr
    )


def test_usage_doc_local_links_exist():
    """文档里的本地链接必须有效（指向真实文件）——「详细实用」的前提是链接点得开。"""
    text = USAGE.read_text(encoding="utf-8")
    targets = re.findall(r"\]\((\.\.?/[^)#\s]+|[A-Za-z0-9_\-/]+\.(?:md|py))\)", text)
    assert targets, "文档里没有解析到任何本地链接"
    missing = [t for t in targets if not (USAGE.parent / t).resolve().exists() and not (ROOT / t).exists()]
    assert not missing, f"docs/usage.md 里有指向不存在文件的链接：{missing}"


def test_usage_doc_keeps_the_practical_sections():
    """指南必须持续覆盖这些「外人一定会问」的点（少一个就算退化）。"""
    text = USAGE.read_text(encoding="utf-8")
    for topic in ("pip install", "DatetimeIndex", "pct_change(fill_method=None)", "复权",
                  "表 A", "表 B", "时间截断一致性", "ddof", "zero_to_one", "常见问题",
                  "单位", "手", "vwap"):   # 中文数据源最常见的翻车点：手/股、千元/元
        assert topic in text, f"docs/usage.md 丢了关键小节/关键点：{topic}"


@pytest.mark.parametrize("script", ["hello_alpha101.py", "from_my_csv.py"])
def test_examples_run(script):
    """★ 两个示例必须真的能跑通（README/指南让人复制命令，就不能是坏的）。"""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "examples" / script)], cwd=ROOT, capture_output=True, text=True, timeout=600
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    assert "面板" in output, output


def test_hello_example_reports_zero_inf_and_window_hint():
    """示例要顺带教两件事：本库不输出 ±inf；全 NaN 常常是「窗口不够」而不是 bug。"""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "hello_alpha101.py")],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    output = proc.stdout
    assert "零 ±inf：True" in output, output
    assert "窗口不够" in output and "DAYS 改成 320" in output, output
