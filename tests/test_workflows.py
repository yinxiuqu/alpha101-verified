"""CI 工作流自身的正确性测试 —— 把本轮踩过的坑固化成防线。

两件事必须机械地守住，因为它们都属于「不会在本地报错、只在 GitHub 上静默失效」的那一类：

1. **YAML 必须能解析**：步骤名里未加引号的 `": "`（如 `- name: Operator layer (M1 gate: 20/20)`）
   会被解析成嵌套映射 ⇒ GitHub 直接判定工作流非法，**连 job 都不创建**（症状是 runs API 查得到 run、
   却没有任何 job 与日志，极难定位）；
2. **`matrix.<var>` 引用的变量必须在 matrix 里定义**：否则同样是工作流级失败。

本地 `pytest` 一直绿，是因为这些错误只在 GitHub 侧暴露 —— 所以必须专门为它们写测试。
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml")) + sorted(
    (ROOT / ".github" / "workflows").glob("*.yaml")
)


def test_workflows_exist():
    assert WORKFLOWS, "找不到任何 CI 工作流文件"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_is_valid_yaml(path: pathlib.Path):
    """★ 必须能解析。含未加引号的 ': ' 的值会在这里当场暴露，而不是等 GitHub 静默失败。"""
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:  # noqa: PERF203
        pytest.fail(f"{path.name} 不是合法 YAML：{exc}")
    assert isinstance(data, dict), f"{path.name} 顶层应是映射"
    assert "jobs" in data, f"{path.name} 缺少 jobs"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_matrix_references_are_defined(path: pathlib.Path):
    """工作流里引用到的每个 `matrix.X` 都必须在 `strategy.matrix` 中定义（否则工作流级失败）。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")
    referenced = set(re.findall(r"matrix\.([A-Za-z0-9_\-]+)", text))
    defined: set[str] = set()
    for job in (data.get("jobs") or {}).values():
        matrix = ((job or {}).get("strategy") or {}).get("matrix") or {}
        defined |= set(matrix)
    missing = referenced - defined
    assert not missing, f"{path.name} 引用了未定义的 matrix 变量：{sorted(missing)}；已定义：{sorted(defined)}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_step_names_avoid_unquoted_colon(path: pathlib.Path):
    """退一步的显式检查：`- name: xxx: yyy` 这种未加引号的行不允许出现（可读的报错信息）。"""
    offenders = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.match(r"^\s*- name: [^\"'].*: .*$", line)
    ]
    assert not offenders, f"{path.name} 有未加引号却含 ': ' 的步骤名：{offenders}"
