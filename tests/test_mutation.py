"""变异测试（设计文档 §8.4）：故意注入已知 bug，断言测试套件会失败。

判据（§6.5 / §10.4）：**每一个注入都必须让至少一个测试失败。**
这是证明「测试套件真的有效、不是摆设」的唯一方式（§9 R7）。

实现方式
--------
把仓库的 ``src/`` + 相关测试文件复制到临时目录，对源码做**字面替换**注入 bug，
在副本里跑**真实的 pytest 子进程**，然后断言：

1. 副本里确实有测试失败（退出码非 0）；
2. 失败清单里出现**预期抓取者**（每条注入都写明了应由哪个测试抓住）。

这样比 in-process 打补丁更强：它跑的是真实的收集/导入/断言链路，
不会因为 monkeypatch 生效方式的假象而「看起来通过了」。

覆盖范围
--------
设计文档 §8.4 的表有 **7 行**（启动提示词里写「6 个注入」，与表格行数不一致，
此处以表格为准，全部覆盖）。最后一行（``ts_sum`` 的 ``min_periods`` 放宽）在文档里
被归因给 §6.5「时间截断一致性」——**该归因经实测不成立**，见
:func:`test_errata_min_periods_is_caught_by_warmup_assertion_not_truncation`。

运行成本：本文件会起 10 个 pytest 子进程（约 1~2 分钟），CI 里独立成一个步骤（§7.6）。
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OPERATORS = "src/alpha101v/operators.py"
TEST_OPERATORS = "tests/test_operators.py"
TEST_INVARIANTS = "tests/test_invariants.py"


@dataclasses.dataclass(frozen=True)
class Mutation:
    """一条注入：改哪里、怎么改、由谁抓住。"""

    id: str
    source: str
    anchor: str
    replacement: str
    targets: tuple[str, ...]
    catcher: str
    rationale: str


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="m1_scale_axis_flip",
        source=OPERATORS,
        anchor="    total = df.abs().sum(axis=1)",
        replacement="    total = df.abs().sum(axis=0)",
        targets=(TEST_OPERATORS,),
        catcher="test_b05_scale_sum_abs_equals_k_per_row",
        rationale="§8.4 行 1：scale 的截面求和轴由 axis=1 改回 axis=0（原始实现缺陷 3）",
    ),
    Mutation(
        id="m2_rank_pct_false",
        source=OPERATORS,
        anchor="    return df.rank(axis=1, method=method, pct=pct, na_option=\"keep\")",
        replacement="    return df.rank(axis=1, method=method, pct=False, na_option=\"keep\")",
        targets=(TEST_OPERATORS,),
        catcher="test_b01_rank_pct_matches_rankdata_over_n",
        rationale="§8.4 行 2：rank 的 pct=True 改成 False（口径漂移）",
    ),
    Mutation(
        id="m3_decay_linear_reversed_weights",
        source=OPERATORS,
        anchor="    weights = np.arange(1, period + 1, dtype=float)",
        replacement="    weights = np.arange(period, 0, -1, dtype=float)",
        targets=(TEST_OPERATORS,),
        catcher="test_a17_decay_linear_weights",
        rationale="§8.4 行 3：decay_linear 权重反序（最新值权重反而最小）",
    ),
    Mutation(
        id="m4_ts_argmax_missing_plus_one",
        source=OPERATORS,
        anchor="    return float(np.argmax(window_values) + 1)",
        replacement="    return float(np.argmax(window_values))",
        targets=(TEST_OPERATORS,),
        catcher="test_a12_ts_argmax_default_basis_is_window_start",
        rationale="§8.4 行 4：ts_argmax 去掉 +1，自窗口起点基准变成 0-based",
    ),
    Mutation(
        id="m5_stddev_ddof_zero",
        source=OPERATORS,
        anchor="def stddev(df: pd.DataFrame, window: int, ddof: int = 1) -> pd.DataFrame:",
        replacement="def stddev(df: pd.DataFrame, window: int, ddof: int = 0) -> pd.DataFrame:",
        targets=(TEST_OPERATORS,),
        catcher="test_a03_stddev_default_is_ddof1",
        rationale="§8.4 行 5：stddev 默认 ddof 由 1 改成 0（样本→总体口径漂移）",
    ),
    Mutation(
        id="m6_delta_mutates_input",
        source=OPERATORS,
        anchor="    return df - df.shift(period)",
        replacement=(
            "    df.iloc[period:] = df.iloc[period:] - df.shift(period).iloc[period:]\n"
            "    return df"
        ),
        targets=(TEST_INVARIANTS + "::test_inputs_are_not_modified",),
        catcher="test_inputs_are_not_modified[delta]",
        rationale="§8.4 行 6：算子原地改写入参（复刻 §3.3 缺陷 2 的污染事故）",
    ),
    Mutation(
        id="m7_ts_sum_min_periods_loosened",
        source=OPERATORS,
        anchor="    return df.rolling(window=window, min_periods=window).sum()",
        replacement="    return df.rolling(window=window, min_periods=1).sum()",
        targets=(TEST_OPERATORS,),
        catcher="test_a01_ts_sum",
        rationale="§8.4 行 7：ts_sum 的 min_periods 放宽（预热期被填值，破坏 NaN 语义）",
    ),
)

_M7 = MUTATIONS[-1]


def _copy_tree(destination: pathlib.Path) -> pathlib.Path:
    """复制一份可独立运行 pytest 的仓库副本（只带必需文件，避免递归收集）。"""
    destination.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "src", destination / "src", ignore=ignore)
    (destination / "tests").mkdir(exist_ok=True)
    for name in ("test_operators.py", "test_invariants.py"):
        shutil.copy2(ROOT / "tests" / name, destination / "tests" / name)
    shutil.copy2(ROOT / "conftest.py", destination / "conftest.py")
    shutil.copy2(ROOT / "pyproject.toml", destination / "pyproject.toml")
    return destination


def _run_pytest(tree: pathlib.Path, targets: tuple[str, ...]) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "-q", "--tb=no", "-p", "no:cacheprovider"],
        cwd=tree,
        env=env,
        capture_output=True,
        text=True,
    )


def _failed_nodes(output: str) -> list[str]:
    return [
        line.split(" ", 1)[1].split(" - ", 1)[0].strip()
        for line in output.splitlines()
        if line.startswith("FAILED ")
    ]


def _inject(tree: pathlib.Path, mutation: Mutation) -> None:
    path = tree / mutation.source
    text = path.read_text(encoding="utf-8")
    occurrences = text.count(mutation.anchor)
    assert occurrences == 1, (
        f"变异锚点必须唯一命中源码，实际命中 {occurrences} 次：{mutation.anchor!r}"
        "（源码被重构后请同步更新 tests/test_mutation.py 的锚点）"
    )
    path.write_text(text.replace(mutation.anchor, mutation.replacement), encoding="utf-8")


@pytest.fixture(scope="module")
def clean_tree(tmp_path_factory) -> pathlib.Path:
    """干净副本必须全绿——否则下面的「失败」可能只是环境坏了（假阳性）。"""
    tree = _copy_tree(tmp_path_factory.mktemp("clean_repo"))
    proc = _run_pytest(tree, (TEST_OPERATORS, TEST_INVARIANTS))
    assert proc.returncode == 0, (
        "变异测试的前置条件失败：干净副本自己就没跑绿，此时任何「注入后失败」都不可信。\n"
        + (proc.stdout + proc.stderr)[-3000:]
    )
    return tree


@pytest.mark.parametrize("mutation", MUTATIONS, ids=[m.id for m in MUTATIONS])
def test_each_injected_bug_is_caught(mutation: Mutation, clean_tree, tmp_path):
    """每条注入：测试必须失败，且失败清单里必须出现预期抓取者。"""
    tree = _copy_tree(tmp_path / "tree")
    _inject(tree, mutation)

    proc = _run_pytest(tree, mutation.targets)
    output = proc.stdout + proc.stderr
    failed = _failed_nodes(output)

    assert proc.returncode != 0 and failed, (
        f"注入 {mutation.id} 后测试仍然全绿 → 测试套件是摆设。\n"
        f"注入内容：{mutation.rationale}\n{output[-3000:]}"
    )
    assert any(mutation.catcher in node for node in failed), (
        f"注入 {mutation.id} 被抓住了，但抓它的不是预期测试 {mutation.catcher!r}；"
        f"实际失败清单：{failed}\n{output[-3000:]}"
    )


def test_errata_min_periods_is_caught_by_warmup_assertion_not_truncation(clean_tree, tmp_path):
    """★ 文档勘误（§8.4 最后一行）：``min_periods`` 放宽**不会**被「时间截断一致性」抓住。

    理由：放宽 ``min_periods`` 只影响**预热期是否填值**，并不引入未来信息，
    因此 ``[0,T]`` 与 ``[0,t]`` 在 t 处依然相等——截断一致性判据对它天然无感。
    真正的抓取者是 §8.1 的「前 window-1 行必须为 NaN」断言（本文件 m7 走的是
    ``test_a01_ts_sum``，下面额外证明 ``test_a25`` 也抓得住）。

    本测试把这两件事同时钉死，避免后人按文档的错误归因写一个更弱的替代测试。
    """
    tree = _copy_tree(tmp_path / "tree")
    _inject(tree, _M7)

    warmup = _run_pytest(
        tree,
        (TEST_OPERATORS + "::test_a25_min_periods_strict_warmup_for_every_rolling_operator",),
    )
    assert warmup.returncode != 0, (
        "预热期 NaN 断言没能抓住 min_periods 放宽，说明 §8.1 的 min_periods 判据失效。\n"
        + (warmup.stdout + warmup.stderr)[-3000:]
    )

    truncation = _run_pytest(tree, (TEST_INVARIANTS, "-k", "truncation"))
    assert truncation.returncode == 0, (
        "截断一致性竟然抓住了 min_periods 放宽 —— 这与本文件记录的分析不符，"
        "请更新 docs/operators.md 的勘误与本节注释。\n"
        + (truncation.stdout + truncation.stderr)[-3000:]
    )
