#!/usr/bin/env python
"""一次性抓取 WorldQuant BRAIN 的平台文档，落盘为 Markdown（可选 PDF）。

抓什么（都是**平台官方文档**，不是论坛帖）
------------------------------------------
====================== ==================================================
``/operators``          66 个算子的完整正文（页面 `Show more` 展开后的内容）+ 官方算例
``/tutorials``          Learn 教程目录（5 个 pack / 17 页）
``/tutorial-pages/{id}`` 教程正文
``/data-sets``          数据集目录（150 个，含描述与覆盖范围）
====================== ==================================================

**不抓**：`/research` 是社区/论坛检索（返回的是帖子标题，不是文档），`/competitions`、`/events`
是运营内容 —— 都与「算子/数据规范」无关，抓了只会稀释语料。

凭据与许可纪律
--------------
* cookie **只从环境变量 `BRAIN_COOKIE` 或 `--cookie-file` 读**，不接受命令行参数（避免进 shell 历史）；
  本工具**不打印、不保存**凭据；
* **平台有速率限制**（实测：连抓 400+ 请求后会回 ``{"message":"API rate limit exceeded"}``）
  ⇒ 默认每次请求间隔 0.35 s，遇 429 按 5/15/45/90 s 退避重试；全量抓取约 300 次请求、耗时数分钟；
* 抓下来的内容是**登录墙内的专有文档**，默认落在 ``refs/``（本仓库已 gitignore）：
  **只作本地规范依据，绝不提交进仓库、绝不二次分发**。要对外引用请只引用必要的短句并注明来源。

用法::

    BRAIN_COOKIE='t=...' python tools/fetch_brain_docs.py                 # 抓全部 + 出 MD
    BRAIN_COOKIE='t=...' python tools/fetch_brain_docs.py --pdf           # 额外渲染 PDF
    BRAIN_COOKIE='t=...' python tools/fetch_brain_docs.py --only operators # 只抓算子
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = "https://api.worldquantbrain.com"
OUT_DIR = ROOT / "refs" / "brain_docs"
SECTIONS = ("operators", "tutorials", "datasets", "datafields")
SLEEP_SECONDS = 0.35
#: 平台限流时的退避（实测：连抓 400+ 请求后会返回 {"message":"API rate limit exceeded"}）
BACKOFF_SECONDS = (5, 15, 45, 90)


# ---------------------------------------------------------------------------
# 取数与文本清洗
# ---------------------------------------------------------------------------


def request_json(
    path_or_url: str,
    cookie: str,
    retries: int = 2,
    allow_missing: bool = False,
    accept: str = "application/json;version=2.0",
) -> object:
    """GET 一个 JSON 端点。401 时明确提示（会话过期）；``allow_missing=True`` 时 404/400 返回 None。

    为什么需要 ``allow_missing``：平台**并未给每个算子都发布详情页**（实测 66 个里有 14 个
    返回 ``No Reference matches the given query``）——这是平台侧的事实，不是抓取失败，
    因此必须容忍缺失、继续抓其余的，而不是整轮崩掉。
    """
    url = path_or_url if path_or_url.startswith("http") else f"{API}{path_or_url}"
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": accept,
                    "Referer": "https://platform.worldquantbrain.com/",
                    "Cookie": cookie,
                },
            )
            with urllib.request.urlopen(request, timeout=45) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                print(f"  ⏳ 触发平台限流，退避 {wait}s 后重试（{url}）", flush=True)
                time.sleep(wait)
                last_error = exc
                continue
            if allow_missing and exc.code in (400, 404):
                return None
            if exc.code == 401:
                raise SystemExit(
                    "❌ 会话失效（HTTP 401）：请在浏览器里重新复制 Cookie（只需 `t=...` 那段），"
                    "再用 BRAIN_COOKIE 环境变量传入。"
                ) from exc
            last_error = exc
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.5 * (attempt + 1))
    raise SystemExit(f"❌ 请求失败 {url}：{last_error}")


def flatten(value: object) -> str:
    """把 content 块里的 str/dict/list 统一抽成文本（尽量保留可读内容）。"""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = [flatten(value[key]) for key in ("value", "text", "content", "rows", "cells", "children") if key in value]
        return " ".join(part for part in parts if part) or json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "\n".join(flatten(item) for item in value)
    return str(value)


def to_text(value: object) -> str:
    """HTML → 纯文本（保留段落/列表结构；去 script/style 与标签）。"""
    text = flatten(value)
    text = re.sub(r"<(script|style).*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"</(p|li|div|h\d|tr)>", "\n", text, flags=re.I)
    text = re.sub(r"<li>", "- ", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def blocks_to_text(payload: dict) -> str:
    blocks = payload.get("content") or []
    return "\n\n".join(part for part in (to_text(b.get("value")) for b in blocks if isinstance(b, dict)) if part)


# ---------------------------------------------------------------------------
# 各段抓取
# ---------------------------------------------------------------------------


def fetch_operators(cookie: str, raw_dir: pathlib.Path) -> str:
    listing = request_json("/operators", cookie)
    assert isinstance(listing, list)
    (raw_dir / "operators.json").write_text(json.dumps(listing, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# WorldQuant BRAIN 算子文档（完整正文）", "",
             f"* 抓取时间：{dt.datetime.now().isoformat(timespec='seconds')}",
             f"* 算子数：**{len(listing)}**（条目来自 `/operators`，正文来自 `/operators/<name>`）", "",
             "> 来源：`https://api.worldquantbrain.com/operators`（登录态）。**专有文档，仅本地规范依据，不得分发。**", ""]
    full = 0
    for item in listing:
        name = item["name"]
        print(f"  operator {name}", flush=True)
        detail = request_json(f"/operators/{name}", cookie, allow_missing=True)
        time.sleep(SLEEP_SECONDS)
        if isinstance(detail, dict) and detail.get("id"):
            (raw_dir / f"operator_{name}.json").write_text(
                json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            body = blocks_to_text(detail)
            full += 1
        else:
            body = ""
        lines += [f"## {name}", "",
                  f"*定义*：`{item.get('definition', '（无）')}`  ",
                  f"*分类*：{item.get('category', '?')} | *层级*：{item.get('level', '?')}  ",
                  f"*一句话*：{item.get('description', '（无）')}", ""]
        if body:
            lines += [body, ""]
    lines.insert(5, f"* 其中有**完整正文**的算子：**{full}**（其余只有一句话描述——平台未发布详情页）")
    (OUT_DIR / "operators.md").write_text("\n".join(lines), encoding="utf-8")
    return f"operators: {len(listing)} 条（{full} 条有完整正文）"


def fetch_tutorials(cookie: str, raw_dir: pathlib.Path) -> str:
    listing = request_json("/tutorials", cookie)
    packs = listing.get("results", []) if isinstance(listing, dict) else []
    (raw_dir / "tutorials.json").write_text(json.dumps(listing, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# WorldQuant BRAIN Learn 教程（完整正文）", "",
             f"* 抓取时间：{dt.datetime.now().isoformat(timespec='seconds')}",
             f"* {len(packs)} 个 pack / {sum(len(p.get('pages', [])) for p in packs)} 页", "",
             "> 来源：`/tutorials` + `/tutorial-pages/{id}`（登录态）。**专有文档，仅本地规范依据，不得分发。**", ""]
    pages = 0
    for pack in packs:
        lines += [f"## {pack.get('title', pack.get('id'))}", "",
                  f"*分类*：{pack.get('category', '?')} | *时长*：{pack.get('duration', '?')}", ""]
        for page in pack.get("pages", []):
            page_id = page["id"]
            print(f"  tutorial {page_id}", flush=True)
            detail = request_json(f"/tutorial-pages/{page_id}", cookie, allow_missing=True)
            time.sleep(SLEEP_SECONDS)
            if detail is not None:
                (raw_dir / f"tutorial_page_{page_id}.json").write_text(
                    json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            body = blocks_to_text(detail) if isinstance(detail, dict) else ""
            pages += 1
            lines += [f"### {page.get('title', page_id)}", "",
                      f"*时长*：{page.get('duration', '?')} | *最后修改*：{page.get('lastModified', '?')}", ""]
            if body:
                lines += [body, ""]
    (OUT_DIR / "tutorials.md").write_text("\n".join(lines), encoding="utf-8")
    return f"tutorials: {len(packs)} pack / {pages} 页"


def fetch_datasets(cookie: str, raw_dir: pathlib.Path) -> str:
    # 注意：`/data-sets` 返回 count=150 但 **next 恒为 null**（平台特性）⇒ 只能手动 offset 翻页，
    # 不能用 next 链。实测 limit 上限 50。
    results: list[dict] = []
    limit, offset, total = 50, 0, None
    while True:
        payload = request_json(f"/data-sets?limit={limit}&offset={offset}", cookie)
        page = payload.get("results", [])
        results.extend(page)
        total = payload.get("count", total)
        print(f"  datasets ... {len(results)}/{total}", flush=True)
        time.sleep(SLEEP_SECONDS)
        if not page or (total is not None and len(results) >= total):
            break
        offset += limit
        if offset > 2000:      # 安全阀：避免平台异常时无限翻页
            break
    (raw_dir / "data_sets.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# WorldQuant BRAIN 数据集目录", "",
             f"* 抓取时间：{dt.datetime.now().isoformat(timespec='seconds')}",
             f"* 数据集数：**{len(results)}**", "",
             "> 来源：`/data-sets`（登录态）。**专有文档，仅本地规范依据，不得分发。**", "",
             "| 数据集 | 名称 | 类别 | 覆盖区域 | 延迟 | 描述 |", "|---|---|---|---|---|---|"]
    for item in results:
        regions = item.get("region") or item.get("regions") or []
        regions = ", ".join(map(str, regions)) if isinstance(regions, list) else str(regions)
        delay = item.get("delay")
        description = re.sub(r"\s+", " ", str(item.get("description", "")))[:220]
        lines.append(
            f"| `{item.get('id', '?')}` | {str(item.get('name', ''))[:60]} | {item.get('category', '?')} | "
            f"{regions[:40]} | {delay} | {description} |"
        )
    (OUT_DIR / "data_sets.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"datasets: {len(results)} 个"


def fetch_data_fields(cookie: str, raw_dir: pathlib.Path, max_fields: int = 5000) -> str:
    """数据字段目录：`/data-fields/summary`（全量字段名）+ `/data-fields`（含描述与所属数据集）。

    ⚠️ `/data-fields` **必须带完整上下文**（instrumentType/region/universe/delay），否则返回
    ``Invalid query``；字段集合随上下文变化，本工具固定抓 **EQUITY / USA / TOP3000 / delay=1**
    （平台最通用的一组）并在报告里标注。
    """
    summary = request_json("/data-fields/summary", cookie, accept="application/json;version=3.0")
    ids = [item.get("id") for item in summary] if isinstance(summary, list) else []
    (raw_dir / "data_fields_summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    lines = ["# WorldQuant BRAIN 数据字段名总表（/data-fields/summary）", "",
             f"* 抓取时间：{dt.datetime.now().isoformat(timespec='seconds')}",
             f"* 字段名数：**{len(ids)}**", "",
             "> 来源：`/data-fields/summary`（Accept: `application/json;version=3.0`）。**专有文档，仅本地依据。**", "",
             "```text"]
    lines += [str(x) for x in ids]
    lines += ["```", ""]
    (OUT_DIR / "data_fields_summary.md").write_text("\n".join(lines), encoding="utf-8")

    query = "instrumentType=EQUITY&region=USA&universe=TOP3000&delay=1"
    results: list[dict] = []
    limit, offset, total = 50, 0, None
    while True:
        payload = request_json(f"/data-fields?{query}&limit={limit}&offset={offset}", cookie)
        page = payload.get("results", [])
        results.extend(page)
        total = payload.get("count", total)
        print(f"  data-fields ... {len(results)}/{total}", flush=True)
        time.sleep(SLEEP_SECONDS)
        if not page or len(results) >= min(total or 0, max_fields) or offset > max_fields:
            break
        offset += limit
    (raw_dir / "data_fields.json").write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    table = ["# WorldQuant BRAIN 数据字段目录（含描述与所属数据集）", "",
             f"* 抓取时间：{dt.datetime.now().isoformat(timespec='seconds')}",
             f"* 上下文：`{query}`（字段集合随上下文变化）",
             f"* 字段数：**{len(results)}**（该上下文共 {total} 个）", "",
             "> 来源：`/data-fields`。**专有文档，仅本地依据，不得分发。**", "",
             "| 字段 | 描述 | 数据集 |", "|---|---|---|"]
    for item in results:
        dataset = item.get("dataset") or {}
        description = re.sub(r"\s+", " ", str(item.get("description", "")))[:200]
        table.append(f"| `{item.get('id', '?')}` | {description} | `{dataset.get('id', '?')}` |")
    (OUT_DIR / "data_fields.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    return f"datafields: 字段名总表 {len(ids)} 个 + 目录 {len(results)}/{total} 个（{query}）"


# ---------------------------------------------------------------------------
# PDF 渲染（pandoc 转 HTML → chromium 打印；系统里两者都在）
# ---------------------------------------------------------------------------


CJK_FONT = "Noto Serif CJK SC"


def render_pdf(markdown_path: pathlib.Path) -> pathlib.Path | None:
    """Markdown → PDF。**主路径 pandoc+xelatex**（本机实测可用且中文正常），chromium 仅作备份。

    备份路径要显式给 ``--user-data-dir``：本机 chromium 154 无该参数时会在
    「Failed to create a unique user data directory for headless」处直接失败。
    """
    pdf_path = markdown_path.with_suffix(".pdf")
    try:
        subprocess.run(
            ["pandoc", str(markdown_path), "-o", str(pdf_path),
             "--pdf-engine=xelatex", "-V", f"CJKmainfont={CJK_FONT}", "-V", "geometry:margin=2cm",
             "--toc", "--metadata", f"title={markdown_path.stem} BRAIN docs"],
            check=True, capture_output=True, timeout=600,
        )
        if pdf_path.exists():
            return pdf_path
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"  ⚠️ pandoc+xelatex 失败（{markdown_path.name}）：{str(exc)[:120]}，改用 chromium")

    html_path = markdown_path.with_suffix(".html")
    try:
        subprocess.run(
            ["pandoc", str(markdown_path), "-s", "--metadata", f"title={markdown_path.stem}",
             "-o", str(html_path)],
            check=True, capture_output=True, timeout=120,
        )
        subprocess.run(
            ["chromium", "--headless=new", "--no-sandbox", "--disable-gpu",
             f"--user-data-dir={pathlib.Path('/tmp') / 'chromium-brain-docs'}",
             f"--print-to-pdf={pdf_path}", html_path.as_uri()],
            check=True, capture_output=True, timeout=300,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"  ⚠️ PDF 渲染失败（{markdown_path.name}）：{str(exc)[:120]}")
        return None
    return pdf_path if pdf_path.exists() else None


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取 BRAIN 平台文档 → Markdown（可选 PDF）")
    parser.add_argument("--only", choices=SECTIONS, help="只抓某一段（默认全抓）")
    parser.add_argument("--cookie-file", help="存放 BRAIN_COOKIE 的文件（只读、不打印）")
    parser.add_argument("--pdf", action="store_true", help="额外渲染 PDF（pandoc + chromium）")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()

    cookie = os.environ.get("BRAIN_COOKIE", "").strip()
    if not cookie and args.cookie_file:
        cookie = pathlib.Path(args.cookie_file).read_text(encoding="utf-8").strip()
    if not cookie:
        parser.error("需要 BRAIN_COOKIE 环境变量或 --cookie-file（本工具不接受命令行里的 cookie）")

    out_dir = pathlib.Path(args.out_dir)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    whoami = request_json("/users/self", cookie)
    print(f"会话有效：{whoami.get('id', '?')}")

    sections = (args.only,) if args.only else SECTIONS
    summary: list[str] = []
    for section in sections:
        print(f"--- {section} ---", flush=True)
        if section == "operators":
            summary.append(fetch_operators(cookie, raw_dir))
        elif section == "tutorials":
            summary.append(fetch_tutorials(cookie, raw_dir))
        elif section == "datasets":
            summary.append(fetch_datasets(cookie, raw_dir))
        else:
            summary.append(fetch_data_fields(cookie, raw_dir))

    inventory = {
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        "endpoints": ["/users/self", "/operators", "/operators/{name}", "/tutorials",
                      "/tutorial-pages/{id}", "/data-sets", "/data-fields/summary", "/data-fields"],
        "summary": summary,
        "files": {},
        "license_note": "登录墙内的专有文档；仅本地规范依据，不得提交进仓库或二次分发",
    }
    for path in sorted(out_dir.glob("*.md")):
        inventory["files"][path.name] = {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()[:16],
        }
    if args.pdf:
        print("--- PDF ---", flush=True)
        for path in sorted(out_dir.glob("*.md")):
            rendered = render_pdf(path)
            if rendered:
                inventory["files"][rendered.name] = {"bytes": rendered.stat().st_size}
                print(f"  ✅ {rendered.name}")
    (out_dir / "inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n完成：")
    for line in summary:
        print(f"  * {line}")
    print(f"  输出目录：{out_dir}（已 gitignore；**不要提交**）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
