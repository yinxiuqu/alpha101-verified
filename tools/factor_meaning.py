#!/usr/bin/env python
"""生成《101 个因子的机械事实表》—— 含义解读的**可核验底座**。

为什么要有这个工具：给 101 个因子写「意义」，最容易滑向编故事。所以把**能从代码算出来的**
部分先机器化、逐条列清（用到哪些字段、哪些算子、哪些窗口、是截面还是时序、结构是什么形态），
人的解读必须挂在它下面，并显式标注「推断」。

用法::

    python tools/factor_meaning.py              # 打印机械事实表（Markdown）
    python tools/factor_meaning.py --write      # 写入 docs/factor_meaning.md 的表格区
    python tools/factor_meaning.py --check      # 校验文档里的表与注册表一致（防漂移）
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DOC = ROOT / "docs" / "factor_meaning.md"
BEGIN = "<!-- MECH_TABLE:BEGIN（由 tools/factor_meaning.py 生成，勿手改）-->"
END = "<!-- MECH_TABLE:END -->"

TS_OPS = ("ts_sum", "ts_mean", "ts_stddev", "ts_min", "ts_max", "ts_argmax", "ts_argmin", "ts_rank",
          "ts_decay_linear", "decay_linear", "delta", "delay", "correlation", "covariance", "sum",
          "product", "stddev", "min", "max", "adv")
CS_OPS = ("rank", "scale", "ts_rank", "ind_neutralize", "indneutralize")
FIELDS = ("open", "high", "low", "close", "vwap", "volume", "amount", "returns", "cap",
          "ind_sector", "ind_industry", "ind_subindustry")


def classify(expression: str) -> str:
    """给出结构形态（用于快速把握因子在做什么），全部基于公式文本。"""
    tags: list[str] = []
    low = expression.lower()
    if "correlation" in low:
        tags.append("量价相关")
    if "decay_linear" in low:
        tags.append("线性衰减加权")
    if "rank(" in low:
        tags.append("截面排序")
    if "indneutralize" in low or "ind_neutralize" in low:
        tags.append("行业中性")
    if "scale(" in low:
        tags.append("截面缩放")
    if re.search(r"\bstddev\b", low):
        tags.append("波动率")
    if re.search(r"\(\s*close\s*-\s*open|close\s*-\s*open", low):
        tags.append("日内开收盘差")
    if "adv" in low:
        tags.append("成交额均值")
    if re.search(r"-\s*1\s*\*|^\s*-\s*1", low) or low.strip().startswith("-1"):
        tags.append("取负（反向信号）")
    return "、".join(tags) or "—"


def facts() -> list[dict]:
    from alpha101v import registry

    rows: list[dict] = []
    for name in sorted(registry.REGISTRY, key=lambda s: int(s[5:])):
        entry = registry.REGISTRY[name]
        doc = (entry.func.__doc__ or "")
        low = doc.lower()
        used_fields = [f for f in FIELDS if re.search(rf"(?<![a-z_]){f}(?![a-z_])", low)]
        used_ops = [op for op in (*TS_OPS, *CS_OPS) if re.search(rf"(?<![a-z_]){op}\(", low)]
        windows = sorted({float(x) for x in re.findall(r"(?<![\d.])(\d+\.?\d*)(?![\d.%])", doc)
                          if float(x) >= 2})
        rows.append({
            "factor": name, "status": str(entry.status), "params": ",".join(entry.params),
            "fields": ",".join(used_fields) or "—",
            "ops": ",".join(dict.fromkeys(used_ops)) or "—",
            "windows": ",".join(str(int(w)) if float(w).is_integer() else str(w) for w in windows) or "—",
            "shape": classify(doc),
            "formula": doc.strip().split(":", 1)[-1].strip(),
        })
    return rows


def build_table() -> str:
    rows = facts()
    lines = ["#### 机械事实表（101 个因子；由 `tools/factor_meaning.py` 从公式逐条提取）", "",
             "| # | 因子 | 状态 | 输入字段 | 算子 | 窗口(≥2) | 结构形态 | 公式 |",
             "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        formula = r["formula"].replace("|", "\\|")
        lines.append(f"| {i} | `{r['factor']}` | {r['status']} | {r['fields']} | {r['ops']} | "
                     f"{r['windows']} | {r['shape']} | `{formula}` |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成因子机械事实表")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    a = ap.parse_args()
    table = build_table()
    if not a.write and not a.check:
        print(table); return 0
    text = DOC.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        print(f"❌ {DOC} 缺标记区"); return 1
    current = text.split(BEGIN)[1].split(END)[0].strip()
    if a.check:
        if current != table.strip():
            print("❌ 文档里的机械事实表与注册表不一致：跑 --write"); return 1
        print("✅ 机械事实表与注册表一致"); return 0
    DOC.write_text(text.replace(BEGIN + text.split(BEGIN)[1].split(END)[0] + END,
                                BEGIN + "\n" + table + "\n" + END), encoding="utf-8")
    print(f"✅ 已写回 {DOC}（{len(facts())} 个因子）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
