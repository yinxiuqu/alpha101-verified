#!/usr/bin/env python
"""生成《L-B 依据清单》：把本仓库**每一条来自 BRAIN 官方文档的结论**映射到原文出处。

为什么需要它
------------
BRAIN 文档是**登录墙内的专有文档**，不能进仓库（`refs/` 已 gitignore）。因此别人 clone 本仓库时
拿不到原文 —— 这份清单就是「**结论 ↔ 原文出处**」的对照表：每条结论写明
① 用的是哪个算子/页面、② 依据的**短引文**、③ 在本地语料里的位置（Markdown 章节 + **PDF 页码**）、
④ 结论落在本仓库哪个文档的哪一节。这样即使拿不到原文，也能看出「我们依据什么、选了什么、漏在哪」。

页码是**现算的**：逐页 `pdftotext` 搜引文，所以语料刷新后重跑本工具即可更新页码。

用法::

    python tools/make_lb_evidence.py            # 生成 docs/lb_evidence.md
    python tools/make_lb_evidence.py --check    # 只校验：每个引文都能在语料里定位到
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "refs" / "brain_docs"
OUT_PATH = ROOT / "docs" / "lb_evidence.md"


@dataclasses.dataclass(frozen=True)
class Claim:
    """一条来自官方文档的结论。"""

    topic: str          # 结论主题（对应本仓库的决策编号）
    operator: str       # 官方文档里的算子/页面
    quote: str          # 短引文（判据原文，尽量短）
    settled: str        # 本仓库据此定了什么
    where: str          # 结论落在哪个文档的哪一节


CLAIMS: tuple[Claim, ...] = (
    Claim(
        "A11 `decay_linear` 权重方向",
        "ts_decay_linear",
        "more recent values have a higher weight",
        "近期权重最大 ⇒ 本库默认 `order=\"recent_first\"`；vnpy 的相反方向记为 V18",
        "`docs/operators.md` §3.13.1；`docs/deviations.md` §3.2 V18",
    ),
    Claim(
        "A11 `decay_linear` 权重公式",
        "ts_decay_linear",
        "(6*1 + 8*2 + 10*3) / (1+2+3)",
        "权重为 1..d、归一化除以 Σ；与 `test_a17` 的期望值一致",
        "`docs/operators.md` §3.13.1；`tests/test_operators.py::test_a17`",
    ),
    Claim(
        "`decay_linear` 缺失值（稀疏模式）",
        "ts_decay_linear",
        "sparse mode",
        "默认 `dense=False`：窗口内 NaN 当 0、分母仍是 1+…+d ⇒ 本库默认改稀疏（V21）",
        "`docs/operators.md` §3.12/§3.13.3",
    ),
    Claim(
        "A4 `ts_arg_max`/`ts_arg_min` 基准",
        "ts_arg_max",
        "today's value is the maximum, returns 0",
        "官方是 `days_ago`（今天=0）⇒ **本库默认翻转**（原默认 1-based 自窗口起点与官方相反）",
        "`docs/operators.md` §3.3；`docs/ambiguities.md` A4",
    ),
    Claim(
        "A2 `ts_rank` 归一化区间",
        "ts_rank",
        "Normalized rank: 3 / (5 - 1) = 0.75",
        "官方是 `(名次−1)/(n−1) ∈ [0,1]` ⇒ 本库默认 `normalization=\"zero_to_one\"`（V19）",
        "`docs/operators.md` §3.2；`tests/test_operators.py::test_a10`",
    ),
    Claim(
        "A3 `rank` 归一化区间",
        "rank",
        "lowest value to 0.0",
        "官方把最低值映到 0.0、最高值映到 1.0（算例 `(4,3,6,10,2) → (0.5,0.25,0.75,1,0)`）",
        "`docs/operators.md` §3.2；`tests/test_operators.py::test_b01`",
    ),
    Claim(
        "A1 `ts_std_dev` 的 ddof",
        "ts_std_dev",
        "squared deviations",
        "官方算例除以 n ⇒ **ddof=0**（总体口径）；本库默认由 1 改为 0（V20）",
        "`docs/operators.md` §3.1；`tests/test_operators.py::test_a03`",
    ),
    Claim(
        "A20 中缀 `^` 的语义",
        "power",
        "drop the sign of x when y is non-integer",
        "官方把 `power`（非整数指数丢符号）与 `signed_power`（保号）分成两个算子；论文 `^` → `power`",
        "`docs/operators.md` §3.11/§3.13.1；`docs/ambiguities.md` A20",
    ),
    Claim(
        "A20 `signed_power` 的定义式",
        "signed_power",
        "abs(x)",
        "官方 `signed_power(x, y) = sign(x) * (abs(x) ^ y)`，与本库 `signedpower(preserve_sign=True)` 逐字一致",
        "`docs/operators.md` §3.13.2",
    ),
    Claim(
        "§3.4 `scale` 的轴向",
        "scale",
        "across all instruments",
        "官方是**跨全部标的**（逐日截面）Σ|x| = book size ⇒ 本库 `axis=1` 得到确认",
        "`docs/operators.md` §3.4/§3.13.2",
    ),
    Claim(
        "§3.4 区分 `scale` 与 `ts_scale`",
        "ts_scale",
        "0–1 range",
        "`ts_scale` 是时序 min-max 归一化，**不是**论文的 `scale` ⇒ 避免张冠李戴",
        "`docs/operators.md` §3.13.2",
    ),
    Claim(
        "A24 行业中性化语义",
        "group_neutralize",
        "subtracting the group mean",
        "组内减去组均值 ⇒ 与 `ind_neutralize` 的逐日组内去均值一致（获官方确认）",
        "`docs/operators.md` §3.13.2；`docs/ambiguities.md` A24",
    ),
    Claim(
        "§3.12 算术不吞 NaN",
        "add",
        "treat NaNs as 0",
        "`filter=false`（默认）不把 NaN 当 0 ⇒ 本库 NaN 传播口径获确认",
        "`docs/operators.md` §3.12/§3.13.2",
    ),
    Claim(
        "§3.12 `sign` 遇 NaN",
        "sign",
        "If the input is NaN, returns NaN",
        "与本库一致（NaN 传播，不返回 0）",
        "`docs/operators.md` §3.13.2",
    ),
    Claim(
        "§3.12 `log` 的定义域",
        "log",
        "positive values",
        "官方只承诺正值 ⇒ x ≤ 0 未定义；本库给 NaN（不给 −inf）",
        "`docs/operators.md` §3.9/§3.13.2",
    ),
    Claim(
        "§3.10 `min`/`max` 的输入数",
        "max",
        "At least 2 inputs are required",
        "官方 `min/max` 是逐元素多输入 ⇒ 论文里 `min(x, d)`（第二参数是天数）走 `ts_min/ts_max`",
        "`docs/operators.md` §3.10/§3.13.2",
    ),
    Claim(
        "±inf 一律降级为 NaN 的依据",
        "divide",
        "dividing by zero raises an error",
        "官方明说除零是错误并建议加 epsilon ⇒ 本库**不加 epsilon**，在因子输出边界把 ±inf 降级为 NaN",
        "`docs/verification.md` §1.6；`src/alpha101v/registry.py::_sanitize`",
    ),
)


def _pdf_pages(pdf: pathlib.Path) -> dict[int, str]:
    """把 PDF 逐页抽成文本（页码从 1 开始）。缺 pdftotext 或 PDF 时返回空。"""
    if not pdf.exists():
        return {}
    pages: dict[int, str] = {}
    total = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    match = re.search(r"^Pages:\s+(\d+)", total, re.M)
    for page in range(1, int(match.group(1)) + 1 if match else 1):
        text = subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), str(pdf), "-"],
            capture_output=True, text=True,
        ).stdout
        pages[page] = text
    return pages


def locate(quote: str) -> list[str]:
    """在本地语料里定位引文：返回 ['operators.md', 'operators.pdf 第 18 页', ...]。"""
    found: list[str] = []
    needle = re.sub(r"\s+", " ", quote).lower()
    for md in sorted(DOCS_DIR.glob("*.md")):
        text = re.sub(r"\s+", " ", md.read_text(encoding="utf-8")).lower()
        if needle in text:
            found.append(md.name)
    for pdf in sorted(DOCS_DIR.glob("*.pdf")):
        with_text = _pdf_pages(pdf)
        if not with_text:
            continue
        page_hits = [
            str(page) for page, text in with_text.items()
            if needle in re.sub(r"\s+", " ", text).lower()
        ]
        if page_hits:
            found.append(f"{pdf.name} 第 {'/'.join(page_hits[:4])} 页")
    return found


def build() -> tuple[str, list[str]]:
    today = dt.date.today().isoformat()
    missing: list[str] = []
    lines = [
        "# L-B 依据清单：每条官方文档结论 ↔ 原文出处",
        "",
        f"*生成时间：{today}（`python tools/make_lb_evidence.py`，页码现算）*",
        "",
        "## 为什么有这份清单",
        "",
        "WorldQuant BRAIN 的算子文档与教程是**登录墙内的专有文档**，按许可纪律**不入库**"
        "（`refs/` 已在 `.gitignore`）。因此 clone 本仓库的人**看不到原文**——这份清单是"
        "「**结论 ↔ 原文出处**」的对照表：每条结论都写明用的是哪个算子页、依据的**短引文**、"
        "在本地语料里的位置（Markdown 章节 + PDF 页码），以及结论落在本仓库哪一节。",
        "",
        "> 复现方式（需要你自己的 BRAIN 会话）：`BRAIN_COOKIE='t=...' python tools/fetch_brain_docs.py --pdf`",
        "> 会重建整套语料（算子 66 条 / 教程 17 页 / 数据集 150 / 字段 4367），再重跑本工具即可刷新页码。",
        "",
        "## 清单",
        "",
        "| # | 结论主题 | 官方页面 | 判据短引文 | 据此定了什么 | 落在本仓库 | 语料位置 |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, claim in enumerate(CLAIMS, start=1):
        hits = locate(claim.quote)
        if not hits:
            missing.append(f"{claim.topic}（引文：{claim.quote!r}）")
        location = "；".join(f"`{h}`" for h in hits) if hits else "⚠️ **未定位到**"
        lines.append(
            f"| {i} | {claim.topic} | `{claim.operator}` | *\"{claim.quote}\"* | {claim.settled} | "
            f"{claim.where} | {location} |"
        )
    lines += [
        "",
        "## 阅读方式",
        "",
        "1. 想复核某条结论：先看「判据短引文」，再看「落在本仓库」那一节里我们怎么用的；",
        "2. 想自己拿原文：按上面的复现命令抓一遍语料（需要登录态），全文在 `refs/brain_docs/` 下；",
        "3. 想知道**哪些没定案**：`docs/operators.md` §3.13.4 列了「文档也没给出的」（`min/max` 的 NaN 口径、",
        "   滚动算子的 `min_periods`、`if_else` 条件为 NULL 的分支等），本库对这些各自显式决策并测试。",
        "",
        "## 纪律",
        "",
        "* 本清单**只引必要的短句**用于判据对照，不复刻原文；全文与 PDF 仅存本地 `refs/`（gitignored），",
        "  **不提交、不二次分发**；",
        "* 引文一律标注来源为 WorldQuant BRAIN 官方文档；",
        "* 信息不完整时如实标注「未定案」而不是补一个看起来合理的解释（`docs/operators.md` §3.13.4）。",
        "",
    ]
    return "\n".join(lines), missing


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 L-B 依据清单")
    parser.add_argument("--check", action="store_true", help="只校验引文能否在本地语料中定位")
    args = parser.parse_args()

    if not DOCS_DIR.exists():
        print(f"❌ 缺少本地语料 {DOCS_DIR}；先跑 tools/fetch_brain_docs.py --pdf")
        return 1
    text, missing = build()
    if args.check:
        if missing:
            print(f"❌ 有 {len(missing)} 条引文在语料中定位不到：")
            for item in missing:
                print(f"   - {item}")
            return 1
        print(f"✅ {len(CLAIMS)} 条引文全部可在本地语料中定位")
        return 0
    OUT_PATH.write_text(text, encoding="utf-8")
    print(f"✅ 已写 {OUT_PATH}（{len(CLAIMS)} 条结论；未定位到 {len(missing)} 条）")
    for item in missing:
        print(f"   ⚠️ {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
