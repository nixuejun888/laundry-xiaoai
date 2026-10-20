# 排错手册

## 播报无声

1. 先确认音箱活着：
   ```bash
   python ~/laundry-xiaoai/bridge.py --list
   python ~/laundry-xiaoai/bridge.py --test washer
   ```
2. `--list` 为空 → 小米登录失效：`python ~/laundry-xiaoai/bridge.py --login`；
3. `--test` 成功但没声音：
   - 检查音箱音量、是否被“免打扰/夜间模式”限制；
   - `bridge.py --test-text --tts-channel miot` 强制走 MIoT（新型号 MiNA TTS 会静默成功）；
   - 看 `/health` 的 `last` 字段与 `channels`。
4. 报 70016 → 账号/密码/验证问题，重新 `--login`（不要反复失败，可能触发风控）。

## 方案 A：微信通知没触发播报

```bash
python ~/laundry-xiaoai/tools/showlog.py
```

| 日志 | 处理 |
| --- | --- |
| 没有 `收到通知` | Notifikator 没转发：检查通知使用权、Enabled、保活、微信通知是否弹出 |
| `package-filtered` | 包名不在白名单（微信分身等），改 `notify_package_allow` |
| `no-keyword` | 把日志里的通知文本特征词加进 `keywords` |
| `cooldown` | 5 分钟内同类别只播一次，属正常 |

微信关键设置：通知显示消息详情、服务通知提醒、测试时锁屏/微信在后台。

## 方案 B：晶御

```bash
python ~/laundry-xiaoai/tools/showlog.py
tail -n 50 ~/.config/laundry-xiaoai/hc_listen.log
```

- `--list` 为空 → 测试账号手机号 / Sync to China；
- 406 → 脚本太旧或缺 vendor Accept；
- 授权页 `Cannot GET /` → 只开了域名根，需带 `?user_code=`；
- 验证码失效 → 30 分钟过期，重新 `--login`；
- 事件通道频繁断开 → 看是否 429；脚本会按 Retry-After 等待。

## 服务挂了/重启后不生效

```bash
python ~/laundry-xiaoai/tools/fix.py
```

它会更新脚本、重写 `run-loop.sh` / `hc-loop.sh` / 开机自启、重启服务并检查 `/health`。

## Termux 自身问题

- `curl` 报 `CANNOT LINK EXECUTABLE`：Termux 的 curl 与 openssl 版本不一致；本项目不依赖 curl，用 Python；
- `pkg` 没有镜像：`termux-change-repo` 或手动写 `$PREFIX/etc/apt/sources.list`；
- Termux 被杀：电池策略无限制 + 自启动 + 后台加锁；Termux:Boot 必须与 Termux 同来源（都用 GitHub 版）。
