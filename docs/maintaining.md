# 维护与发布流程

本仓库的约定：**每次改动都按下面顺序走一遍**，保证“电脑上跑的、手机上装的、GitHub 上的”一致。

## 0. 工作目录

| 用途 | 路径（本机） |
|---|---|
| 源码仓库 | `H:\DSH_Working\软件相关\laundry-xiaoai-oss` |
| 手机局域网安装包 | `H:\DSH_Working\软件相关\laundry-xiaoai\手机安装包`（HTTP 8788） |
| 同步脚本 | `H:\DSH_Working\软件相关\sync-laundry.sh` |

## 1. 改代码

- 主程序：`bridge.py`、`hc_listen.py`
- 工具：`tools/*.py`
- 安装器：`install.py`
- 文档/示例：`README.md`、`docs/`、`examples/`

## 2. 本地检查（必须）

```bash
cd /h/DSH_Working/软件相关/laundry-xiaoai-oss
python -m py_compile install.py bridge.py hc_listen.py tools/*.py
rm -rf __pycache__ tools/__pycache__
```

关键功能改动建议补测：

```bash
# bridge 干跑（HTTP 流程）
python bridge.py --dry-run --port 18800
curl -s http://127.0.0.1:18800/health

# 安装器（本地静态服务器模拟）
# python -m http.server 8801 --directory .
# python install.py --base http://127.0.0.1:8801 --dir /tmp/x --skip-login --skip-deps --skip-test --no-start
```

## 3. 同步到局域网安装包 + 推送 GitHub

一条命令搞定（会编译检查、复制到 8788 目录、commit、push，push 失败自动切直连重试）：

```bash
bash /h/DSH_Working/软件相关/sync-laundry.sh "feat: 一句话描述这次改动"
```

它做的事：

1. 编译检查所有 Python；
2. 把 `bridge.py`、`hc_listen.py`、`tools/*` 复制到 `手机安装包` 根目录和 `tools/`；
3. `git add -A` + `git commit`（有改动才提交）；
4. `git push origin main`（失败时自动绕过失效代理重试）；
5. 打印最新 commit 和手机端更新命令。

## 4. 手机端更新

在家（局域网）：

```bash
LAUNDRY_XIAOAI_BASE=http://192.168.5.15:8788 python ~/laundry-xiaoai/tools/fix.py
```

或 一键中心 → 9（自动优先局域网源）。

外网（CDN）：

```bash
LAUNDRY_XIAOAI_BASE=https://cdn.jsdelivr.net/gh/nixuejun888/laundry-xiaoai@main python ~/laundry-xiaoai/tools/fix.py
```

## 5. 验收

```bash
python ~/laundry-xiaoai/tools/verify.py   # 期望 8/8
```

新功能按需测：`tools/fix_token.py --check`、`tools/rack.py`、一键中心 → 12。

## 6. 发版（可选）

- 更新 `CHANGELOG.md`（新增版本条目）；
- 打 tag 并发布：

```bash
git tag v0.1.1 && git push origin v0.1.1
# 或
gh release create v0.1.1 --title "v0.1.1" --notes "见 CHANGELOG"
```

## 注意

- **不要**把 `mi.token`、`homeconnect_token.json`、`config.json`、`homeconnect.json` 提交进仓库（`.gitignore` 已排除）；
- 仓库里的示例配置只放占位符，不放真实 client_id / DID / 手机号；
- GitHub 直连不稳定时，push 用脚本自动回退；npm/gh 需要代理时按本机记忆里的配置处理。
