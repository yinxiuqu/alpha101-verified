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


def test_no_shell_redirect_accident_files():
    """★ 仓库根不许出现（更不许跟踪）`=...` 这类重定向事故文件。

    实测发生过两次：一次被提交进仓库（`=1.26`，来自 `pip install "numpy>=1.26"` 忘加引号），
    另一次是修这条时**写提交信息又把 `>1.26` 变成了重定向**当场重建 —— 所以既查 git 跟踪、
    也查文件系统（未跟踪的同样会污染工作区，且下次 `git add -A` 就会被带进去）。
    """
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    bad_tracked = [p for p in tracked if p.startswith("=")]
    on_disk = [p.name for p in ROOT.iterdir() if p.name.startswith("=")]
    assert not bad_tracked, f"仓库里**跟踪了**重定向事故文件：{bad_tracked}（用 git rm 清掉）"
    assert not on_disk, (
        f"工作区里出现重定向事故文件：{on_disk}（`git add -A` 会把它带进仓库）"
        "；成因通常是 `pip install \"pkg>=x\"` 忘加引号"
    )
