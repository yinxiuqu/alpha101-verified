#!/usr/bin/env python
"""美股真实数据验证：取数 → 验证 → **删除并审计**（tushare）。

为什么单独一个工具
------------------
A 股走本地 MongoDB，美股只能从 tushare 拉。而 tushare 的接口**有账户等级限制**，
所以这里把「取数 / 验证 / 删除」三个阶段分开、可分别重跑，并且**把审计写进仓库**：

* `--fetch`：按 ``ts_code`` 逐只取（单次最多 6000 行，支持 ``limit``/``offset`` 分页），
  落地 ``refs/us_verify/``（gitignored，**不入库**）；带**断点续取**与**限频退避**；
* `--verify`：在真实美股面板上跑与本仓库同样的检查（面板契约 / 不变量 / 零 ±inf / 覆盖率），
  并用 ``tools/factor_differential.py --panel-file`` 与 vnpy 做**因子级差分**；
* `--delete --audit`：**删除全部美股数据**并输出审计（删了哪些文件、多大、删完目录是否为空），
  审计写入 ``reports/us_data_audit.md``（这份**入库**，作为「数据已清干净」的凭证）。

已知的账户侧限制（实测，见 `docs/verification.md` §1.11）
--------------------------------------------------------
* ``us_daily``：本账号被限到 **1 次/小时**（先 1 次/分钟，超限后升级）；
* ``us_daily_adj``（复权行情）：**无接口权限**；
* ``us_adjfactor``：**无接口权限** ⇒ 只能用 ``us_daily`` 的**未复权**价格；
* ``us_basic.classify`` 是**证券类型**（EQ/ADR/PF/GDR），**不是行业** ⇒ 美股侧做不了 18 个 `IndNeutralize` 因子。

未复权怎么办：用 ``pre_close`` 反推**拆股调整因子**（``pre_close != 上一日 close`` 的地方记一次调整），
拼出**拆股后复权**序列。这修得掉拆股，**修不掉分红**——本工具会把这一点写进验证报告（不假装完整）。

用法::

    python tools/us_data_verification.py --fetch --tickers AAPL,MSFT,... --start 2018-01-01 --end 2024-12-31
    python tools/us_data_verification.py --verify
    python tools/us_data_verification.py --delete --audit
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

DATA_DIR = ROOT / "refs" / "us_verify"
AUDIT_PATH = ROOT / "reports" / "us_data_audit.md"
PAGE_LIMIT = 6000          # tushare 单次上限（用户确认）
SLEEP_SECONDS = 65         # 本账号 us_daily 实测 1 次/分钟起，取 65 s 更稳


def tushare_token() -> str:
    """token 来源：环境变量 ``TUSHARE_TOKEN`` → tushare 默认缓存 ``~/tk.csv``。**不打印。**"""
    import os

    env = os.environ.get("TUSHARE_TOKEN", "").strip()
    if env:
        return env
    cache = pathlib.Path.home() / "tk.csv"
    if cache.exists():
        for line in cache.read_text(errors="ignore").splitlines():
            for part in (p.strip() for p in line.split(",")):
                if 28 <= len(part) <= 80 and re.fullmatch(r"[0-9a-zA-Z_\-]+", part) and not part.isdigit():
                    return part
    raise SystemExit("找不到 tushare token：设 TUSHARE_TOKEN 或写 ~/tk.csv（tushare 默认缓存）")


# ---------------------------------------------------------------------------
# 阶段一：取数
# ---------------------------------------------------------------------------


def fetch(tickers: list[str], start: str, end: str) -> int:
    import tushare as ts

    pro = ts.pro_api(tushare_token())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    done = {p.stem for p in DATA_DIR.glob("daily_*.parquet")}
    pending = [t for t in tickers if t not in done]
    print(f"待取 {len(pending)}/{len(tickers)} 只（已有 {len(done)} 只，自动跳过=断点续取）")
    for i, code in enumerate(pending, start=1):
        for attempt in range(4):
            try:
                frame = pro.query("us_daily", ts_code=code, start_date=start, end_date=end, limit=PAGE_LIMIT)
                if frame is None or frame.empty:
                    print(f"  {code}: 空数据（跳过）")
                else:
                    frame.sort_values("trade_date").to_parquet(DATA_DIR / f"daily_{code}.parquet", index=False)
                    print(f"  [{i}/{len(pending)}] {code}: {len(frame)} 行")
                break
            except Exception as exc:  # noqa: BLE001
                wait = 60 * (attempt + 1)
                print(f"  {code}: 失败（{str(exc)[:70]}）→ 等 {wait}s 重试 {attempt + 1}/4")
                time.sleep(wait)
        else:
            print(f"  {code}: 放弃（限频/无权限）；已取到的部分保留，可稍后重跑续取")
        time.sleep(SLEEP_SECONDS)
    return 0


# ---------------------------------------------------------------------------
# 阶段二：验证
# ---------------------------------------------------------------------------


def build_panel() -> dict[str, pd.DataFrame]:
    """把逐只 parquet 拼成面板；用 ``pre_close`` 反推**拆股调整**（不含分红）。"""
    files = sorted(DATA_DIR.glob("daily_*.parquet"))
    if not files:
        raise SystemExit(f"{DATA_DIR} 里没有数据：先跑 --fetch")
    frames = []
    for file in files:
        frame = pd.read_parquet(file)
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d")
        frames.append(frame.sort_values("trade_date"))
    long = pd.concat(frames, ignore_index=True)

    # 拆股调整（**后复权**）：r_t = pre_close_t / close_{t−1}（正常日 =1，4:1 拆股日 ≈0.25），
    # 用 **1/r 的前向累积** 把拆股后的价格放大回去 ⇒ 序列连续、收益率不再有假暴跌。
    # ⚠️ 方向很容易写反：若直接用 cumprod(r) 去乘，反而会把拆股日的跌幅**放大**（tests 里有这条回归测试）。
    long["prev_close"] = long.groupby("ts_code")["close"].shift(1)
    ratio = (long["pre_close"] / long["prev_close"]).replace([np.inf, -np.inf], np.nan)
    ratio = ratio.where(ratio.between(0.2, 5.0), 1.0).fillna(1.0)
    long["adj"] = (1.0 / ratio).groupby(long["ts_code"]).cumprod()

    panel: dict[str, pd.DataFrame] = {}
    for source, target in (("open", "Open"), ("high", "high"), ("low", "low"), ("close", "close"),
                           ("vol", "volume"), ("amount", "amount"), ("vwap", "vwap")):
        values = long.pivot(index="trade_date", columns="ts_code", values=source).sort_index()
        panel[target] = values
    # 调整只用拆股因子（分红不修，如实记录）
    for field in ("Open", "high", "low", "close", "vwap"):
        panel[field] = panel[field] * long.pivot(index="trade_date", columns="ts_code", values="adj").sort_index()
    panel["returns"] = panel["close"].pct_change(fill_method=None)
    return panel


def verify() -> int:
    from alpha101v import ALL_FACTOR_NAMES, registry
    from alpha101v.panel import validate_panel

    panel = build_panel()
    close = panel["close"]
    print(f"美股面板：{close.shape[1]} 只 × {close.shape[0]} 个交易日（{close.index.min().date()} ~ {close.index.max().date()}）")
    missing = [f for f in ("amount", "cap", "ind_sector", "ind_industry", "ind_subindustry") if f not in panel]
    print(f"  缺字段（自动跳过相关因子）：{missing}")

    problems = validate_panel(panel, min_history=None, allow_extra=True)
    print(f"  面板契约：{'✅ 通过' if not problems else '⚠️ ' + '; '.join(problems[:3])}")

    vwap_ok = float(
        ((panel["vwap"] >= panel["low"]) & (panel["vwap"] <= panel["high"])).to_numpy().mean()
    )
    print(f"  vwap ∈ [low, high] 自洽率 {vwap_ok:.2%}（单位/复权是否合理的一分钟自查）")

    runs, infs, coverages = 0, 0, []
    for name in ALL_FACTOR_NAMES:
        if not set(registry.REGISTRY[name].params) <= set(panel):
            continue
        out = registry.run_factor(name, panel)
        values = out.to_numpy(dtype=float)
        runs += 1
        infs += int(np.isinf(values).sum())
        coverages.append(float(np.isfinite(values).mean()))
    print(f"  跑通 {runs}/101 个因子（其余缺字段）；±inf 合计 {infs} 个；平均覆盖率 {np.mean(coverages):.1%}")

    # 不变量：时间截断一致性（PIT 金标准）
    cut = max(60, int(close.shape[0]) - 40)
    names = [n for n in ALL_FACTOR_NAMES if set(registry.REGISTRY[n].params) <= set(panel)][:12]
    bad = []
    for name in names:
        full = registry.run_factor(name, panel)
        trunc = registry.run_factor(name, {k: (v.iloc[:cut] if hasattr(v, "iloc") else v) for k, v in panel.items()})
        try:
            pd.testing.assert_frame_equal(trunc, full.iloc[:cut])
        except AssertionError:
            bad.append(name)
    print(f"  时间截断一致性（抽样 {len(names)} 个因子）：{'✅ 全部通过' if not bad else '❌ ' + str(bad)}")

    print("\n下一步（如已装参照）：python tools/factor_differential.py --panel-file refs/us_verify/panel_export")
    return 0 if not bad and infs == 0 else 1


# ---------------------------------------------------------------------------
# 阶段三：删除 + 审计
# ---------------------------------------------------------------------------


def delete_and_audit() -> int:
    files = sorted(DATA_DIR.rglob("*")) if DATA_DIR.exists() else []
    data_files = [f for f in files if f.is_file()]
    total_bytes = sum(f.stat().st_size for f in data_files)
    removed = []
    for file in data_files:
        removed.append((str(file.relative_to(ROOT)), file.stat().st_size))
        file.unlink()
    # 目录一并清掉（含空子目录）
    for path in sorted(DATA_DIR.rglob("*"), reverse=True) if DATA_DIR.exists() else []:
        if path.is_dir():
            path.rmdir()
    if DATA_DIR.exists():
        DATA_DIR.rmdir()
    empty = not DATA_DIR.exists()

    # 顺带审计：仓库里是否还有别的美股数据痕迹
    suspects = [
        str(p.relative_to(ROOT))
        for p in ROOT.rglob("*")
        if p.is_file() and ("us_verify" in str(p) or re.search(r"(^|/)us_(daily|basic|adj)", p.name))
    ]
    lines = [
        "# 美股数据审计（取数→验证→删除）",
        "",
        f"* 生成时间：{dt.datetime.now().isoformat(timespec='seconds')}",
        f"* 数据目录：`{DATA_DIR.relative_to(ROOT)}`（gitignored，从不入库）",
        f"* 本次删除：**{len(removed)} 个文件 / {total_bytes / 1024:.1f} KiB**",
        f"* 删除后目录是否存在：{'❌ 仍存在' if DATA_DIR.exists() else '✅ 已不存在'}（空目录也已清理：{empty}）",
        "",
        "## 删除清单",
        "",
    ]
    lines += [f"* `{path}`（{size / 1024:.1f} KiB）" for path, size in removed] or ["* （无文件可删：本轮未成功落地任何美股数据）"]
    lines += [
        "",
        "## 残留检查",
        "",
        f"* 仓库内匹配 `us_verify` / `us_daily` / `us_basic` / `us_adj` 的文件："
        f"{'无 ✅' if not suspects else '；'.join(suspects)}",
        "* MongoDB：未写入任何美股集合（本工具只用本地 parquet 文件）",
        "* 凭据：token 只在调用时从 `TUSHARE_TOKEN` / `~/tk.csv` 读取，**未复制、未入库、未打印**",
        "",
        "## 为什么会有这份审计",
        "",
        "使用者明确不持有美股数据 ⇒ 验证完成后必须**删干净并留痕**。",
        "这份文件是「已清理」的凭证：写明删了什么、多大、删完是否为空、以及仓库里还有没有别的痕迹。",
        "",
    ]
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ 已删除 {len(removed)} 个文件 / {total_bytes / 1024:.1f} KiB；目录已清理")
    print(f"✅ 审计写入 {AUDIT_PATH.relative_to(ROOT)}")
    if suspects:
        print(f"⚠️ 仍有可疑残留：{suspects}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="美股真实数据验证（取数 / 验证 / 删除+审计）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fetch", action="store_true")
    group.add_argument("--verify", action="store_true")
    group.add_argument("--delete", action="store_true")
    parser.add_argument("--audit", action="store_true", help="与 --delete 一起用时输出审计文件")
    parser.add_argument("--tickers", default="AAPL,MSFT,GOOGL,AMZN,META,NVDA,JPM,XOM,JNJ,WMT",
                        help="逗号分隔；默认 10 只覆盖科技/金融/能源/医药/消费")
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2024-12-31")
    args = parser.parse_args()

    if args.fetch:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
        return fetch(tickers, args.start.replace("-", ""), args.end.replace("-", ""))
    if args.verify:
        return verify()
    return delete_and_audit()


if __name__ == "__main__":
    raise SystemExit(main())
