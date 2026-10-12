#!/usr/bin/env python
"""生成《使用指南》里的两张字段表（并把它们注入 `docs/usage.md`）。

为什么要有这个工具：用户最常见的第一个问题是「**我手上只有这些字段，能跑哪些因子？**」
答案必须**从注册表算出来**、而不是手写在文档里抄错 —— 所以这里自动生成、并有测试守着防漂移。

用法::

    python tools/field_requirements.py            # 打印两张表（Markdown）
    python tools/field_requirements.py --write    # 注入 docs/usage.md 的标记区
    python tools/field_requirements.py --check    # 校验文档与注册表一致（CI/测试用）
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

DOC_PATH = ROOT / "docs" / "usage.md"
BEGIN = "<!-- FIELD_TABLES:BEGIN（由 tools/field_requirements.py 生成，勿手改）-->"
END = "<!-- FIELD_TABLES:END -->"

#: 推荐的数据获取顺序（越靠前越基础）
FIELD_ORDER = (
    "close", "Open", "high", "low", "volume", "vwap", "returns", "amount",
    "cap", "ind_sector", "ind_industry", "ind_subindustry",
)
#: 字段的中文说明（写给人看）
FIELD_NOTES = {
    "close": "收盘价（**必须复权**）",
    "Open": "开盘价（**必须复权**）",
    "high": "最高价（**必须复权**）",
    "low": "最低价（**必须复权**）",
    "volume": "成交量（股数）",
    "vwap": "成交均价（论文 vwap；无 vwap 时可用 `amount/volume` 近似）",
    "returns": "日收益率（`close.pct_change(fill_method=None)`，首行留 NaN）",
    "amount": "成交额（元）——**论文的 `adv{d}` 是美元成交额**，用 volume 替代属近似",
    "cap": "总市值（只被 alpha56 用；`rank` 型 ⇒ 总/流通市值等价）",
    "ind_sector": "行业标签·论文 `IndClass.sector`（PIT/as-of，**不能用今天的快照**）",
    "ind_industry": "行业标签·论文 `IndClass.industry`（PIT/as-of）",
    "ind_subindustry": "行业标签·论文 `IndClass.subindustry`（PIT/as-of）",
}


def build_tables() -> str:
    from alpha101v import registry

    names = sorted(registry.REGISTRY, key=lambda s: int(s[5:]))
    need: dict[str, list[int]] = {field: [] for field in FIELD_ORDER}
    for name in names:
        for field in registry.REGISTRY[name].params:
            need.setdefault(field, []).append(int(name[5:]))

    lines = [
        "#### 表 A：字段 → 需要它的因子",
        "",
        "| 字段 | 含义 | 需要它的因子数 | 因子（编号） |",
        "|---|---|---:|---|",
    ]
    for field in sorted(need, key=lambda f: -len(need[f])):
        numbers = need[field]
        shown = "、".join(str(n) for n in numbers)
        lines.append(f"| `{field}` | {FIELD_NOTES.get(field, '（见面板契约）')} | {len(numbers)} | {shown} |")

    lines += [
        "",
        "#### 表 B：你手上有什么 → 能跑多少因子",
        "",
        "按**推荐获取顺序**累进（`close` 起，逐项补齐）：",
        "",
        "| 已有的字段 | 可跑的因子数 | 新增 |",
        "|---|---:|---|",
    ]
    have: set[str] = set()
    previous = 0
    for field in FIELD_ORDER:
        have.add(field)
        runnable = [n for n in names if set(registry.REGISTRY[n].params) <= have]
        lines.append(f"| 截至 `{field}`（含以上） | **{len(runnable)}** | +{len(runnable) - previous} |")
        previous = len(runnable)
    only_ohlcv = len(
        [n for n in names if set(registry.REGISTRY[n].params) <= {"close", "Open", "high", "low", "volume"}]
    )
    single = [n for n in names if len(registry.REGISTRY[n].params) == 1]
    lines += [
        "",
        f"* **只有 OHLCV**（`close/Open/high/low/volume`）就能跑 **{only_ohlcv}** 个因子；",
        f"* 最省的因子只要**一个字段**：{'、'.join('`' + n + '`' for n in single)}；",
        "* 缺字段时 `registry.run_factor` 会**明确报出缺哪个字段**——不要用 0 或均值去填，"
        "那会让因子变成另一个东西（见 §5 口径）。",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成/注入字段依赖表")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="写回 docs/usage.md 的标记区")
    group.add_argument("--check", action="store_true", help="校验文档与注册表一致")
    args = parser.parse_args()

    generated = build_tables()
    if not args.write and not args.check:
        print(generated)
        return 0

    text = DOC_PATH.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        print(f"❌ {DOC_PATH} 缺少标记区：{BEGIN} … {END}")
        return 1
    current = text.split(BEGIN)[1].split(END)[0].strip()
    if args.check:
        if current != generated.strip():
            print("❌ docs/usage.md 的字段表与注册表不一致：跑 `python tools/field_requirements.py --write`")
            return 1
        print("✅ docs/usage.md 的字段表与注册表一致")
        return 0
    DOC_PATH.write_text(text.replace(BEGIN + text.split(BEGIN)[1].split(END)[0] + END,
                                     BEGIN + "\n" + generated + "\n" + END), encoding="utf-8")
    print(f"✅ 已写回 {DOC_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
