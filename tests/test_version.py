"""版本号与仓库卫生的机械守卫（都是实际踩过的坑）。

1. **版本号单一来源**：`alpha101v.__version__` 必须等于 `pyproject.toml` 的 version。
   曾经 `__init__.py` 硬编码 0.1.0、而 dist 元数据是 0.1.1 —— 装的是哪个版本说不清；
2. **不许有 shell 重定向事故文件**：`pip install "numpy>=1.26"` 忘加引号会在仓库根生成
   名为 `=1.26` 的 0 字节文件，且**会被 git 跟踪**跟着进克隆（实测发生过）。
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert m, "pyproject.toml 里找不到 version"
    return m.group(1)


def test_package_version_matches_pyproject():
    """★ 包内 __version__ 必须与 pyproject 一致（漂移过，所以钉死）。"""
    import alpha101v

    assert alpha101v.__version__ == _pyproject_version(), (
        f"版本号漂移：__version__={alpha101v.__version__}，pyproject={_pyproject_version()}"
    )


def test_installed_metadata_matches_pyproject():
    """已安装时，dist 元数据也必须一致（两者不一致说明装的是旧轮子）。"""
    import importlib.metadata as md

    try:
        dist = md.version("alpha101v")
    except md.PackageNotFoundError:  # pragma: no cover - 未安装时跳过
        pytest.skip("alpha101v 未安装为发行版（源码树直接 import）")
    assert dist == _pyproject_version()


def test_no_shell_redirect_accident_files_tracked():
    """★ 不许跟踪 `=...` 这类重定向事故文件（实测 `=1.26` 进过仓库）。"""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    bad = [p for p in tracked if p.startswith("=") or p.lstrip("./").startswith("=")]
    assert not bad, f"仓库里跟踪了 shell 重定向事故文件：{bad}（用 git rm 清掉）"
