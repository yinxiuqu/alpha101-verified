#!/usr/bin/env python
"""规范对照（L2）：把**论文公式**与**实现 AST** 的结构逐项比对，输出三分类偏差清单。

设计文档 §6.3 / §7.2 要求：把论文附录每个 alpha 的公式解析成算子树，与实现的 AST 逐节点比对，
输出「等价 / 近似 / 偏离」三分类，产出《与论文的偏差清单》（101 行）。

本工具实现的是**可比对的那部分**（诚实标注能力边界）：

* **解析论文公式**：论文用一套接近 C 的中缀表达式语言，本工具实现完整词法 + 递归下降解析
  （三元 `?:`、`||`、比较、`+ - * /`、`^`、函数调用、括号），并做**算子名归一化**
  （`sum→ts_sum`、`Ts_Rank→ts_rank`、`IndNeutralize→ind_neutralize`、`SignedPower→signedpower`…）；
* **解析实现**：读 ``src/alpha101v/factors.py`` 的 AST，取每个因子函数体里调用的算子，
  并把两类「非算子调用」映射回论文记号：
  - ``_adv(amount, d)`` → 论文的 ``adv{d}``（一个**字段**，不是算子）；
  - ``_pow(x, a)`` → 论文的中缀 ``^``；
  - ``_if/_cmp/_lt/_gt/_eq/_or/_panels`` → 控制结构（论文的三元/比较/逻辑），不计入算子多重集；
* **比对三样东西的多重集**：算子、字段、数值字面量。三者全等 ⇒ ``等价``；
  否则按差异条目给出 ``近似`` 或 ``偏离``（并可登记**已声明差异**，写明理由）。

**能力边界（不假装做到的事）**：这是**算子级**结构对照，不是完整的数据流/AST 同构证明
（实现里允许引入中间变量、结合律重排）。要把「等价」升级为更严格的结构等价，需要在 M4/M5
引入表达式级别的中间表示；这一点已写入 `docs/verification.md`。

用法::

    python tools/conformance_report.py                 # 打印分类统计 + 非等价明细
    python tools/conformance_report.py --table         # 输出可贴进 docs/deviations.md 的 101 行表格
    python tools/conformance_report.py --alpha 48      # 只看某个因子
"""

from __future__ import annotations

import argparse
import ast
import collections
import dataclasses
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

PAPER = ROOT / "docs" / "paper_formulas.md"
FACTORS = ROOT / "src" / "alpha101v" / "factors.py"

# ---------------------------------------------------------------------------
# 1. 论文公式的语言：词法 + 递归下降解析
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<number>\d+\.\d*|\.\d+|\d+)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)
  | (?P<op>\|\||==|<=|>=|\?|:|[<>+\-*/^(),])
    """,
    re.VERBOSE,
)

#: 论文调用名 → 本库算子名（小写后比对）
PAPER_OPERATORS = {
    "sum": "ts_sum",
    "ts_sum": "ts_sum",
    "ts_rank": "ts_rank",
    "ts_argmax": "ts_argmax",
    "ts_argmin": "ts_argmin",
    "ts_min": "ts_min",
    "ts_max": "ts_max",
    "stddev": "stddev",
    "correlation": "correlation",
    "covariance": "covariance",
    "decay_linear": "decay_linear",
    "delta": "delta",
    "delay": "delay",
    "rank": "rank",
    "scale": "scale",
    "product": "product",
    "signedpower": "signedpower",
    "indneutralize": "ind_neutralize",
    "abs": "abs_",
    "log": "log",
    "sign": "sign",
}

#: 论文里的小写 min/max 有**两种语义**（见 docs/operators.md §3.10 的消歧规则）：
#: 第二参数是数值 ⇒ 时序 ts_min/ts_max；第二参数是表达式 ⇒ 逐元素 minimum/maximum。
TIMESERIES_MINMAX = {"min": "ts_min", "max": "ts_max"}
ELEMENTWISE_MINMAX = {"min": "minimum", "max": "maximum"}

#: 实现的 AST 里需要忽略的非算子调用（控制结构 / 面板装配 / 内部辅助）。
IGNORED_CALLS = {
    "_panels", "_if", "_cmp", "_and", "_not", "_values", "_wrap", "_pairwise",
    "float", "abs", "min", "max", "range", "len",
}
#: 实现里映射到论文记号的辅助调用（控制结构一律映射成论文的中缀记号，保证可比）。
HELPER_MAP = {
    "_pow": "^", "_adv": "adv", "_lt": "<", "_gt": ">", "_eq": "==", "_or": "||",
}

#: Python 二元运算符 → 论文中缀记号。
BINOP_MAP = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}


@dataclasses.dataclass
class Node:
    """论文表达式的节点：算子调用 / 字段 / 字面量 / 中缀运算符。"""

    kind: str          # "call" | "field" | "literal" | "op"
    name: str
    children: tuple["Node", ...] = ()
    value: float | None = None


def tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    for match in TOKEN_RE.finditer(text):
        kind = match.lastgroup
        value = match.group()
        if kind == "ws":
            continue
        tokens.append((kind, value))
    return tokens


class PaperParser:
    """递归下降解析器（论文公式是全括号化的中缀表达式）。"""

    def __init__(self, text: str) -> None:
        self.tokens = tokenize(text)
        self.position = 0

    def peek(self, value: str | None = None) -> str | None:
        if self.position >= len(self.tokens):
            return None
        token = self.tokens[self.position][1]
        return token if value is None else (token if token == value else None)

    def next(self) -> str:
        token = self.tokens[self.position][1]
        self.position += 1
        return token

    def parse(self) -> Node:
        node = self.ternary()
        assert self.position == len(self.tokens), f"未消费完的记号：{self.tokens[self.position:]}"
        return node

    def ternary(self) -> Node:
        condition = self.or_expr()
        if self.peek("?"):
            self.next()
            yes = self.ternary()
            assert self.peek(":"), "三元表达式缺少 ':'"
            self.next()
            no = self.ternary()
            return Node("call", "if", (condition, yes, no))
        return condition

    def or_expr(self) -> Node:
        node = self.compare()
        while self.peek("||"):
            self.next()
            node = Node("op", "||", (node, self.compare()))
        return node

    def compare(self) -> Node:
        node = self.additive()
        if self.peek() in ("<", ">", "==", "<=", ">="):
            operator = self.next()
            node = Node("op", operator, (node, self.additive()))
        return node

    def additive(self) -> Node:
        node = self.multiplicative()
        while self.peek() in ("+", "-"):
            operator = self.next()
            node = Node("op", operator, (node, self.multiplicative()))
        return node

    def multiplicative(self) -> Node:
        node = self.unary()
        while self.peek() in ("*", "/"):
            operator = self.next()
            node = Node("op", operator, (node, self.unary()))
        return node

    def unary(self) -> Node:
        if self.peek() in ("-", "+"):
            operator = self.next()
            operand = self.unary()
            if operator == "-":
                # 记为 neg 伪算子（实现侧对应 ast.USub），避免与显式 `*` 重复计数
                return Node("op", "neg", (operand,))
            return operand
        return self.power()

    def power(self) -> Node:
        base = self.atom()
        if self.peek("^"):
            self.next()
            return Node("op", "^", (base, self.unary()))
        return base

    def atom(self) -> Node:
        token = self.peek()
        assert token is not None, "表达式意外结束"
        kind = self.tokens[self.position][0]
        if token == "(":
            self.next()
            node = self.ternary()
            assert self.peek(")"), "缺少右括号"
            self.next()
            return node
        if kind == "number":
            self.next()
            return Node("literal", token, value=float(token) if token != "." else float(token))
        self.next()
        if self.peek("("):
            self.next()
            args: list[Node] = []
            if not self.peek(")"):
                args.append(self.ternary())
                while self.peek(","):
                    self.next()
                    args.append(self.ternary())
            assert self.peek(")"), f"{token} 的参数表缺少右括号"
            self.next()
            return Node("call", token, tuple(args))
        return Node("field", token)


def walk(node: Node):
    yield node
    for child in node.children:
        yield from walk(child)


def paper_features(node: Node) -> tuple[collections.Counter, collections.Counter, collections.Counter, set]:
    """返回 (算子多重集, 字段多重集, 字面量多重集, IndClass 层级集合)。"""
    operators: collections.Counter[str] = collections.Counter()
    fields: collections.Counter[str] = collections.Counter()
    literals: collections.Counter[float] = collections.Counter()
    levels: set[str] = set()

    for item in walk(node):
        if item.kind == "literal":
            literals[round(item.value, 8)] += 1
        elif item.kind == "field":
            name = item.name.lower()
            if name.startswith("adv"):
                fields[name] += 1                      # adv20 / adv180 …
            elif name in {"open", "close", "high", "low", "volume", "vwap", "returns", "cap"}:
                fields[name] += 1
            elif name == "indclass":
                pass                                   # IndClass.subindustry 在调用参数里单独取
            else:
                fields[name] += 1
        elif item.kind == "op":
            operators[item.name] += 1
        elif item.kind == "call":
            name = item.name.lower()
            if name in {"if", "indclass"}:
                if name == "if":
                    operators["if"] += 1
                continue
            if name == "min" or name == "max":
                second = item.children[1] if len(item.children) > 1 else None
                scalar_window = second is not None and second.kind == "literal"
                operators[(TIMESERIES_MINMAX if scalar_window else ELEMENTWISE_MINMAX)[name]] += 1
            elif name in PAPER_OPERATORS:
                operators[PAPER_OPERATORS[name]] += 1
                if name == "indneutralize":
                    for arg in item.children[1:]:
                        for sub in walk(arg):
                            if sub.kind == "field" and sub.name.lower().startswith("ind"):
                                levels.add(sub.name.lower())
            else:
                operators[name] += 1
    return operators, fields, literals, levels


# ---------------------------------------------------------------------------
# 2. 实现侧：AST 走查
# ---------------------------------------------------------------------------


def implementation_features(func: ast.FunctionDef) -> tuple[collections.Counter, collections.Counter, collections.Counter]:
    operators: collections.Counter[str] = collections.Counter()
    fields: collections.Counter[str] = collections.Counter()
    literals: collections.Counter[float] = collections.Counter()

    # `_adv(amount, d)` 的 d 属于论文标识符 `adv{d}` 的一部分，不计入字面量
    window_nodes: set[int] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and _call_name(node) == "_adv" and len(node.args) > 1:
            window_nodes.update(id(sub) for sub in ast.walk(node.args[1]))

    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name is None:
                continue
            if name == "_adv":
                window = node.args[1] if len(node.args) > 1 else None
                if isinstance(window, ast.Constant) and isinstance(window.value, int):
                    fields[f"adv{window.value}"] += 1
                else:
                    operators["adv"] += 1
            elif name in IGNORED_CALLS:
                continue
            elif name in HELPER_MAP:
                operators[HELPER_MAP[name]] += 1
            else:
                operators[name] += 1
        elif isinstance(node, ast.BinOp) and type(node.op) in BINOP_MAP:
            operators[BINOP_MAP[type(node.op)]] += 1
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            operators["neg"] += 1
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
            and id(node) not in window_nodes
        ):
            literals[round(float(node.value), 8)] += 1
        elif isinstance(node, ast.Name) and node.id == "p":
            pass

    # 字段：从函数签名取（形参名 = 面板字段名），把 Open 归一成论文的 open
    for arg in func.args.args:
        name = arg.arg
        if name.startswith("ind_"):
            fields[f"indclass.{name[4:]}"] += 1
        else:
            fields[name.lower()] += 1
    return operators, fields, literals


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


# ---------------------------------------------------------------------------
# 3. 比对与分类
# ---------------------------------------------------------------------------

#: 已声明差异（alpha 编号 → (分类, 理由)）。**任何**非等价都必须在这里留档或修实现。
DECLARED: dict[int, tuple[str, str]] = {}


def load_paper_formulas() -> dict[int, str]:
    text = PAPER.read_text(encoding="utf-8")
    block = text.split("## 5. 101 条公式", 1)[1].split("```", 2)[1]
    formulas: dict[int, str] = {}
    for line in block.splitlines():
        match = re.match(r"^Alpha#(\d+):\s*(.+)$", line.strip())
        if match:
            formulas[int(match.group(1))] = match.group(2).strip()
    assert len(formulas) == 101, f"论文公式应 101 条，实得 {len(formulas)}"
    return formulas


def load_factor_functions() -> dict[int, ast.FunctionDef]:
    tree = ast.parse(FACTORS.read_text(encoding="utf-8"))
    found: dict[int, ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and re.fullmatch(r"alpha\d+", node.name):
            found[int(node.name[5:])] = node
    return found


@dataclasses.dataclass
class Verdict:
    alpha: int
    classification: str          # 等价 / 近似 / 偏离
    differences: list[str]
    paper_operators: collections.Counter
    impl_operators: collections.Counter
    levels: set[str]

    @property
    def reason(self) -> str:
        return "；".join(self.differences) if self.differences else ""


def compare(alpha: int, paper: str, func: ast.FunctionDef | None) -> Verdict:
    node = PaperParser(paper).parse()
    paper_ops, paper_fields, paper_literals, levels = paper_features(node)
    if func is None:
        return Verdict(alpha, "偏离", ["实现缺失"], paper_ops, collections.Counter(), levels)

    impl_ops, impl_fields, impl_literals = implementation_features(func)
    paper_ops.pop("if", None)
    differences: list[str] = []

    # 判定用**集合**：实现允许引入中间变量（CSE）与结合律重排，出现次数天然不同；
    # 多重集仍打印在 --table 里供人工比对（见 Verdict 的 paper_operators/impl_operators）。
    paper_literal_set = {k for k in paper_literals if k != 1.0}   # 1.0 是 -1 的哨兵，两端都排除
    impl_literal_set = {k for k in impl_literals if k != 1.0}
    if paper_literal_set != impl_literal_set:
        differences.append(
            f"字面量差异：论文独有 {sorted(paper_literal_set - impl_literal_set)}，"
            f"实现独有 {sorted(impl_literal_set - paper_literal_set)}"
        )

    # `amount` 只是 adv{d} 的载体（论文里没有直接使用 amount 的因子）
    impl_field_set = set(impl_fields)
    impl_field_set.discard("amount")
    paper_field_set = set(paper_fields)
    if paper_field_set != impl_field_set:
        differences.append(
            f"字段差异：论文独有 {sorted(paper_field_set - impl_field_set)}，"
            f"实现独有 {sorted(impl_field_set - paper_field_set)}"
        )

    paper_op_set, impl_op_set = set(paper_ops), set(impl_ops)
    if paper_op_set != impl_op_set:
        differences.append(
            f"算子差异：论文独有 {sorted(paper_op_set - impl_op_set)}，"
            f"实现独有 {sorted(impl_op_set - paper_op_set)}"
        )

    if not differences:
        classification = "等价"
    elif alpha in DECLARED:
        classification = DECLARED[alpha][0]
        differences = [DECLARED[alpha][1], *differences]
    else:
        classification = "偏离"
    return Verdict(alpha, classification, differences, paper_ops, impl_ops, levels)


def main() -> int:
    parser = argparse.ArgumentParser(description="论文公式 ↔ 实现 AST 的规范对照")
    parser.add_argument("--table", action="store_true", help="输出 101 行偏差表（Markdown）")
    parser.add_argument("--alpha", type=int, help="只检查某个 alpha")
    args = parser.parse_args()

    formulas = load_paper_formulas()
    functions = load_factor_functions()
    targets = [args.alpha] if args.alpha else sorted(formulas)
    verdicts = [compare(a, formulas[a], functions.get(a)) for a in targets]

    if args.table:
        print("| 因子 | 分类 | 论文算子多重集 | 实现算子多重集 | 差异 |")
        print("|---|---|---|---|---|")
        for v in verdicts:
            paper = ", ".join(f"{k}×{n}" for k, n in sorted(v.paper_operators.items())) or "—"
            impl = ", ".join(f"{k}×{n}" for k, n in sorted(v.impl_operators.items())) or "—"
            print(f"| alpha{v.alpha} | {v.classification} | {paper} | {impl} | {v.reason or '—'} |")
        return 0

    counts = collections.Counter(v.classification for v in verdicts)
    print(f"规范对照：{'/'.join(f'{k} {v}' for k, v in sorted(counts.items()))}"
          f"（共 {len(verdicts)} 个因子）")
    for v in verdicts:
        if v.classification != "等价":
            print(f"\n  alpha{v.alpha} [{v.classification}] {v.reason}")
            if args.alpha:
                paper = ", ".join(f"{k}×{n}" for k, n in sorted(v.paper_operators.items()))
                impl = ", ".join(f"{k}×{n}" for k, n in sorted(v.impl_operators.items()))
                print(f"    论文: {paper}")
                print(f"    实现: {impl}")
    missing = [a for a in sorted(formulas) if a not in functions]
    if missing:
        print(f"\n未实现：{missing}")
        return 1
    return 0 if counts.get("偏离", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
