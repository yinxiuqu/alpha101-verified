#!/usr/bin/env python
"""BRAIN 行为对齐抽样（设计文档 §2.3 / §6.4 的补充证据层，**不是** L3 差分）。

为什么不能要求数值相等
----------------------
平台的仿真接口**不返回因子矩阵**，只返回 alpha 的**表现**（PnL、Sharpe、turnover…）。
因此「行为对齐」只能是：**同一个表达式**在本库与平台上各产生一条日度 PnL 序列，
再比较两者的**单调性与相关性**（不要求数值相等）——这才是设计文档 §2.3 说的「行为对齐抽样」。

前置条件（缺一不可）
--------------------
1. **两侧必须是同一市场**：本库用本地 A 股（MongoDB），平台侧必须是 **CHN 区域**的仿真结果，
   否则一条是 A 股、一条是美股，比较没有任何意义；
2. 平台侧要有**同表达式**的仿真（本工具可用 `--alpha-id` 读你已有的仿真，**不消耗配额**；
   也可 `--submit` 由本工具发起仿真，但**会消耗你的配额**，见下）；
3. 平台侧的权重/中性化/截断等设置要与本库口径尽量一致（本库等价于「行业内中性化 + 等权 + 日频」的近似）。

配额纪律
--------
`--submit` 会发起一次真实仿真、消耗**你的** BRAIN 配额，因此必须同时显式给出
`--i-understand-this-uses-my-quota`；默认只打印将要提交的表达式与设置，等你确认。
**推荐路径是 `--alpha-id`：读你已经在网页上跑过的仿真结果，零配额。**

凭据纪律
--------
**不保存、不打印任何凭据**：cookie 只从环境变量 `BRAIN_COOKIE` 或 `--cookie-file` 读；
也可以用 `--platform-pnl <file.json|csv>` 直接把平台导出的 PnL 交给本工具，**完全不碰凭据**。

用法::

    # 只算本地基线（不需要任何凭据）
    python tools/brain_alignment.py --factor alpha5

    # 与平台导出的 PnL 对比（最干净：不碰凭据）
    python tools/brain_alignment.py --factor alpha5 --platform-pnl platform_pnl.csv

    # 直接读你已有的仿真（需要有效会话；零配额）
    BRAIN_COOKIE='t=...' python tools/brain_alignment.py --factor alpha5 --alpha-id 1a2b3c4d
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import pathlib
import sys

import numpy as np
import pandas as pd
from scipy import stats

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

API = "https://api.worldquantbrain.com"
OUT_DIR = ROOT / "reports"


def _l6():
    """复用 L6 工具里的 PnL 代理实现（同一口径，避免两处各写一份）。"""
    spec = importlib.util.spec_from_file_location("_l6_for_alignment", ROOT / "tools" / "l6_statistics.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_l6_for_alignment"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 对齐统计（被 tests/test_brain_alignment.py 用合成数据验证）
# ---------------------------------------------------------------------------


def compare_pnl(local: pd.Series, platform: pd.Series) -> dict[str, float | int]:
    """比较两条日度 PnL 序列：**单调性为主**（Spearman），辅以 Pearson 与同号率。

    注意：跨数据源的 PnL **数值不可比**（量纲、杠杆、交易成本口径都不同），
    所以这里只回答「两边是不是同一个东西的行为」，不回答「数值是否相等」。
    """
    frame = pd.concat({"local": local, "platform": platform}, axis=1).dropna()
    if frame.shape[0] < 10:
        return {"days": int(frame.shape[0]), "spearman": np.nan, "pearson": np.nan, "sign_agreement": np.nan}
    both = frame.to_numpy(dtype=float)
    spearman = float(stats.spearmanr(both[:, 0], both[:, 1]).statistic)
    pearson = float(np.corrcoef(both[:, 0], both[:, 1])[0, 1])
    sign_agreement = float((np.sign(both[:, 0]) == np.sign(both[:, 1])).mean())
    return {
        "days": int(frame.shape[0]),
        "spearman": spearman,
        "pearson": pearson,
        "sign_agreement": sign_agreement,
    }


def sharpe(pnl: pd.Series, periods_per_year: int = 252) -> float:
    """年化 Sharpe（仅用于「各自量级是否像个日频策略」的粗看，不用于比较大小）。"""
    values = pnl.dropna()
    if values.size < 2 or not values.std(ddof=1):
        return float("nan")
    return float(values.mean() / values.std(ddof=1) * np.sqrt(periods_per_year))


def load_platform_pnl(path: pathlib.Path) -> pd.Series:
    """读平台导出的 PnL：支持 CSV（date,pnl 或两列）与 JSON（records 或 {date: pnl}）。"""
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        # 三种形态都要吃得下：{"records": [[date, pnl], ...]} / [[date, pnl], ...] / {date: pnl}
        records = payload.get("records") if isinstance(payload, dict) and "records" in payload else payload
        if isinstance(records, list):
            index = [str(row[0]) for row in records]
            values = [float(row[-1]) for row in records]
            return pd.Series(values, index=pd.to_datetime(index), dtype=float)
        if isinstance(records, dict):
            series = pd.Series({pd.Timestamp(k): float(v) for k, v in records.items()})
            return series.sort_index()
        raise ValueError(f"无法解析 PnL JSON：{type(payload).__name__}")
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    rows = [row for row in rows if row and not row[0].lower().startswith(("date", "#"))]
    index = pd.to_datetime([row[0] for row in rows])
    values = [float(row[-1]) for row in rows]
    return pd.Series(values, index=index, dtype=float)


def fetch_platform_pnl(alpha_id: str, cookie: str, timeout: int = 30) -> pd.Series:
    """读**已有**仿真的 PnL（GET /alphas/{id}/recordsets/pnl）——零配额。

    ★ 只读；不发任何仿真请求。失败时抛出带 HTTP 状态的异常，绝不静默返回空序列。
    """
    import urllib.request  # noqa: PLC0415

    request = urllib.request.Request(
        f"{API}/alphas/{alpha_id}/recordsets/pnl",
        headers={
            "Accept": "application/json;version=2.0",
            "Referer": "https://platform.worldquantbrain.com/",
            "Cookie": cookie,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - 需要网络与有效会话
        raise RuntimeError(f"读取 alpha {alpha_id} 的 PnL 失败：{exc}") from exc
    records = payload.get("records") or []
    if not records:
        raise RuntimeError(f"alpha {alpha_id} 的 PnL 记录为空（会话失效？alpha 未完成仿真？）")
    index = pd.to_datetime([row[0] for row in records])
    return pd.Series([float(row[-1]) for row in records], index=index, dtype=float)


# ---------------------------------------------------------------------------
# 本地基线
# ---------------------------------------------------------------------------


def local_pnl(factor_name: str, n_codes: int, start: str, end: str) -> tuple[pd.Series, dict]:
    """本地 A 股基线：按 L6 同口径算该因子的日度 PnL 代理。"""
    l6 = _l6()
    from alpha101v import registry  # noqa: PLC0415

    panel, codes = l6.load_inputs(n_codes, start, end)
    factor = registry.run_factor(factor_name, panel)
    forward = l6.forward_returns(panel["close"], 1)
    pnl = l6.factor_pnl(factor, forward)
    meta = {"codes": len(codes), "days": int(panel["close"].shape[0]), "start": start, "end": end}
    return pnl, meta


def main() -> int:
    parser = argparse.ArgumentParser(description="BRAIN 行为对齐抽样（不是 L3 差分）")
    parser.add_argument("--factor", required=True, help="因子名，如 alpha5")
    parser.add_argument("--n-codes", type=int, default=120)
    parser.add_argument("--start", default="2023-01-03")
    parser.add_argument("--end", default="2024-06-28")
    parser.add_argument("--alpha-id", help="读你**已有**的平台仿真 PnL（零配额）")
    parser.add_argument("--platform-pnl", help="平台导出的 PnL 文件（.csv/.json；完全不碰凭据）")
    parser.add_argument("--cookie-file", help="存放 BRAIN_COOKIE 的文件（只读、不打印）")
    parser.add_argument("--submit", action="store_true", help="由本工具发起仿真（**消耗配额**）")
    parser.add_argument("--i-understand-this-uses-my-quota", action="store_true")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()

    if args.submit and not args.i_understand_this_uses_my_quota:
        parser.error(
            "拒绝执行：--submit 会消耗你的 BRAIN 配额。请加上 "
            "--i-understand-this-uses-my-quota，或改用 --alpha-id / --platform-pnl（零配额）"
        )
    if args.submit:
        print(
            "⚠️ 本工具**不代你提交仿真**（避免误耗配额）：请到平台网页用下面的表达式跑一次，\n"
            "   再用 --alpha-id 读回结果（零配额、可复核）："
        )
        from alpha101v import registry  # noqa: PLC0415

        meta = registry.REGISTRY[args.factor]
        print(f"\n   表达式请用：{args.factor}（{meta.paper_ref}）")
        print(f"   ⚠️ 平台侧必须选 **CHN（A 股）** 区域，否则与本库不同市场、比较无意义\n")
        return 2

    pnl, meta = local_pnl(args.factor, args.n_codes, args.start, args.end)
    print(f"本地基线：{args.factor} | {meta['codes']} 只 × {meta['days']} 交易日（{meta['start']}~{meta['end']}）")
    print(f"  本地 PnL 年化 Sharpe ≈ {sharpe(pnl):+.2f}（只说明量级像不像日频策略，不用于比较大小）")

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    local_path = out_dir / f"alignment_local_{args.factor}.csv"
    pnl.rename("local_pnl").to_csv(local_path, index_label="date")
    print(f"  本地 PnL 已存 {local_path}")

    platform: pd.Series | None = None
    if args.platform_pnl:
        platform = load_platform_pnl(pathlib.Path(args.platform_pnl))
        source = f"文件 {args.platform_pnl}"
    elif args.alpha_id:
        cookie = os.environ.get("BRAIN_COOKIE", "")
        if not cookie and args.cookie_file:
            cookie = pathlib.Path(args.cookie_file).read_text(encoding="utf-8").strip()
        if not cookie:
            parser.error("需要 BRAIN_COOKIE 环境变量或 --cookie-file（本工具不接收命令行里的 cookie）")
        platform = fetch_platform_pnl(args.alpha_id, cookie)
        source = f"平台 alpha {args.alpha_id}"
    else:
        source = ""

    if platform is None:
        print(
            "\n要在平台侧完成行为对齐，二选一（都不需要把凭据交给别人）：\n"
            "  A) 平台上用同一表达式、**CHN 区域**跑一次仿真 → 导出 PnL → "
            f"python tools/brain_alignment.py --factor {args.factor} --platform-pnl <文件>\n"
            f"  B) 已有仿真 → python tools/brain_alignment.py --factor {args.factor} --alpha-id <id>"
            "（配 BRAIN_COOKIE）"
        )
        return 0

    result = compare_pnl(pnl, platform)
    print(f"\n与{source}对比（{result['days']} 个共同交易日）：")
    print(f"  Spearman（单调性，**主判据**）: {result['spearman']:+.3f}")
    print(f"  Pearson : {result['pearson']:+.3f}")
    print(f"  同号率  : {result['sign_agreement']:.1%}")
    print("  解读：跨数据源 PnL 的**数值不可比**，这里只回答「是不是同一个东西的行为」")
    print("  ⚠️ 本项是**补充证据**，不进入 L3/L5 门禁，也不改变任何因子的 verified/partial 状态")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
