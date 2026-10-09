"""来源与依赖守卫（设计文档 §9 R1 GPL 传染 + §7.1 依赖约束）。

许可证与依赖是**可机械判定**的事实，不该靠自觉：
* 仓库源码里不得出现被分析的 GPL 实现的任何代码血缘痕迹（clean-room 纪律留痕）；
* 运行时依赖只能是 ``numpy / pandas / scipy``（vnpy / statsmodels 仅测试期对拍）；
* 许可必须是 MIT。
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

#: 一旦出现在 ``src/`` 里就说明 clean-room 纪律被破坏（设计文档 §5.3 法律边界表）。
#: 注意 ``.as_matrix(`` 是**代码形态**而非裸词：源码注释里说明「原实现用了这个已删除的
#: API」属于正常的缺陷记录，不算抄代码；真的调用它才算。
FORBIDDEN_SOURCE_TOKENS: tuple[str, ...] = (
    "QAFactor",
    "yutiansut",
    "qa_ecosystem",
    ".as_matrix(",  # 原始实现 §3.3 缺陷 1 的写法，若真调用说明抄了原代码
    "GPL-3.0",
    "GNU General Public License",
)

#: 运行时**禁止**出现的第三方模块（顶层包名）。
FORBIDDEN_RUNTIME_MODULES: tuple[str, ...] = (
    "statsmodels",
    "vnpy",
    "polars",
    "matplotlib",
    "pymongo",
    "quantaxis",
    "talib",
    "sklearn",
)


def test_source_tree_has_no_gpl_lineage_tokens():
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*")):
        if path.suffix not in {".py", ".md"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            if token in text:
                offenders.append(f"{path.relative_to(ROOT)}: {token}")
    assert not offenders, "src/ 出现 GPL 实现的血缘痕迹：" + "; ".join(offenders)


def test_license_is_mit_and_no_gpl_license_files():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    assert "Permission is hereby granted, free of charge" in text
    suspicious = [
        p.name
        for p in ROOT.rglob("*")
        if p.is_file() and p.name.upper() in {"COPYING", "COPYING.TXT", "LICENSE.GPL", "GPL-3.0"}
    ]
    assert not suspicious


def test_runtime_import_is_minimal():
    """在一个干净子进程里 import 本包，不得把任何禁止模块带进来（§7.1）。"""
    code = (
        "import sys, alpha101v;"
        f"bad=[m for m in sys.modules if m.split('.')[0] in {FORBIDDEN_RUNTIME_MODULES!r}];"
        "print(','.join(sorted(bad)))"
    )
    env = dict(os.environ, PYTHONPATH=str(SRC))
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", f"运行时被污染：{proc.stdout.strip()}"


def test_declared_runtime_dependencies_are_minimal():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    deps = data["project"]["dependencies"]
    names = {re.split(r"[<>=!~;\s]", dep, maxsplit=1)[0].strip().lower() for dep in deps}
    assert names <= {"numpy", "pandas", "scipy"}, names
    assert "statsmodels" not in names, "statsmodels 只能是测试期依赖"
    test_extra = data["project"]["optional-dependencies"]["test"]
    assert any(dep.lower().startswith("statsmodels") for dep in test_extra)


def test_source_does_not_import_third_party_factor_libraries():
    pattern = re.compile(
        r"^\s*(?:import|from)\s+(statsmodels|vnpy|polars|talib|quantaxis)\b", re.MULTILINE
    )
    offenders = [
        str(path.relative_to(ROOT))
        for path in sorted(SRC.rglob("*.py"))
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"运行时源码引入了被禁依赖：{offenders}"
