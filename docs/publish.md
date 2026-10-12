# 发布与分发指南（GitHub / PyPI）

本文记录**怎么把这个仓库发出去**，以及发布前必须过的检查。踩过的坑都写在里面。

## 0. 发布前必查（每次都要）

```bash
git ls-files | grep -E "^(refs/|\.refs/|dist/)|(^|/)(aws\.env|tk\.csv)$|brain_docs|venv-ref"
```

必须**为空**。原因：

* `refs/brain_docs/` 是 WorldQuant BRAIN 的**登录墙内专有文档**（按许可纪律只留本地、永不分发）；
* `.refs/` 放参照实现（vnpy / alpha101-pipeline 等），只在**测试期**使用，属于他人代码，不随本仓库分发；
* `aws.env` 是密钥文件；`dist/`、`build/`、`*.egg-info/` 是构建产物。

这些在 `.gitignore` 里都已忽略；上面这条命令是**最后一道人工确认**（历史上我确实误提交过一次参照源码，
靠 `git rm --cached` + 补 `.gitignore` + `reflog expire --expire=now --all && git gc --prune=now` 才清干净）。

## 1. GitHub

```bash
# 先在网页建一个**空仓**（不要勾选 README/.gitignore/LICENSE）：https://github.com/new
cd /home/yinxiuqu/alpha101-verified
git remote add origin https://github.com/yinxiuqu/alpha101-verified.git   # 已配 credential.helper=store 则免密
git push -u origin main
git push origin --tags        # v0.1.0 / v0.1.1
```

* 仓库自带的 `.github/workflows/ci.yml` 会在推送后自动跑：pandas 2.1/2.2/2.3 矩阵 + golden 快照检查 + 规范对照；
* 打标签前记得同步 `pyproject.toml` 的 `version` 与 `CHANGELOG.md`。

## 2. PyPI

包名 `alpha101v` 在 PyPI **未被占用**（2026-10-12 核查为 404）。构建验证（不污染运行时环境）：

```bash
python -m venv .refs/venv-build && .refs/venv-build/bin/pip install -q build
rm -rf dist && .refs/venv-build/bin/python -m build --sdist --wheel
```

产物内容必须自检（**绝不包含专有语料与密钥**）：

```bash
python - <<'PY'
import tarfile, zipfile, pathlib
bad = ("refs/", "aws.env", "brain_docs", "tk.csv", "venv-ref", ".refs/")
for f in pathlib.Path("dist").glob("*"):
    names = tarfile.open(f).getnames() if f.suffix == ".gz" else zipfile.ZipFile(f).namelist()
    hits = [n for n in names if any(b.strip("/") in n for b in bad)]
    print(f.name, len(names), "条目", "命中敏感项", len(hits), hits[:3])
PY
```

实测结果：`alpha101v-0.1.1.tar.gz`（123 KB / 46 条目）与 `alpha101v-0.1.1-py3-none-any.whl`（64 KB / 16 条目）**均为 0 命中**。

发布（需要 PyPI token；**token 不要写进仓库或对话**）：

```bash
.refs/venv-build/bin/pip install -q twine
TWINE_USERNAME=__token__ TWINE_PASSWORD=<你的 PyPI token> \
  .refs/venv-build/bin/python -m twine upload dist/*
```

建议先用 `--repository-url https://test.pypi.org/legacy/` 在 TestPyPI 走一遍。

## 3. 公众号（若要把文章发出去）

文章素材在本仓库 `reports/wechat/`（写作纲要 + 4 张实证图）；排版与发布走**独立的公众号工具工作区**
`/home/yinxiuqu/wechat_articles/`（`aws.env` 放密钥、`.aws-article/config.yaml` 放账号配置）。

⚠️ **已知坑：微信 API 有 IP 白名单**。错误长这样：

```
errcode 40164: invalid ip 119.44.45.10, not in whitelist
```

到 **微信公众平台 → 设置与开发 → 基本配置 → IP 白名单** 把当前出口 IP 加进去即可
（换网络环境后 IP 会变，需要重新加）。
