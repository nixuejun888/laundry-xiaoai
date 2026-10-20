# 小爱洗衣提醒（laundry-xiaoai）

用**小爱音箱**语音播报博世/西门子洗衣机的「洗完」「烘干完成」「洗衣液/柔顺剂不足」等提醒。

不刷机、不加硬件，利用你已有的手机 + Termux + 小爱音箱：

- **方案 A（默认）**：微信通知 → 手机上的通知转发 App → Termux 里的 HTTP 服务 → 小米云端 TTS → 小爱音箱；
- **方案 B（可选、更稳）**：晶御（Home Connect 中国区）**官方开发者 API** 事件流 → 同一台手机 → 小爱音箱。

两个方案可以只用 A、只用 B，或同时开启（bridge 内置去抖，只会播一次）。

---

## 1. 它能做什么

| 场景 | 播报示例 |
| --- | --- |
| 洗衣机洗完 | 「洗衣机洗好了，记得及时晾晒哦」 |
| 烘干机烘完 | 「衣服烘干了，记得及时取出哦」 |
| 衣物长时间闷在筒里（方案 A） | 「衣服还在洗衣机里，记得及时取出，防止褶皱和异味」 |
| 洗衣液不足（i-DOS 1 仓） | 「洗衣机洗衣液不足，请补充」 |
| 柔顺剂不足（i-DOS 2 仓） | 「洗衣机柔顺剂不足，请补充」 |
| 可选：开始运行 / 暂停 / 开关门 / 报警 | 见「播报模式」 |

## 2. 架构

```
【方案 A · 微信通知（默认，零开发者账号）】

  博世/晶御小程序 ──微信服务通知──▶ 手机微信
                                     │ 系统通知栏
                                     ▼
                           通知转发 App（Notifikator）
                                     │ POST http://127.0.0.1:8765/notify
                                     ▼
   ┌──────────────────────── Termux（同一台手机）────────────────────────┐
   │  bridge.py：HTTP 服务 :8765                                        │
   │   ├─ 按 package / 关键词分类（washer / dryer / linger / supply）     │
   │   ├─ 5 分钟去抖（A+B 同时开也只播一次）                             │
   │   ├─ 免打扰时段 / 音量 / 指定音箱                                   │
   │   └─ 小米云：MiNA TTS 或 MIoT play-text 指令                        │
   └──────────────────────────────────┬─────────────────────────────────┘
                                      ▼
                                 小爱音箱

【方案 B · 晶御官方 API（可选，最稳）】

  洗衣机/烘干机 ──▶ 博世中国区云 API（SSE 事件流）
                          │
                          ▼
              hc_listen.py（Termux，常驻）
                          │ GET http://127.0.0.1:8765/washer
                          ▼
                       bridge.py ──▶ 小爱音箱
```

两个触发源的区别：

| | 方案 A（微信通知） | 方案 B（晶御官方 API） |
| --- | --- | --- |
| 需要开发者账号 | ❌ | ✅（免费注册） |
| 需要通知转发 App | ✅ | ❌ |
| 触发稳定性 | 依赖微信通知设置/后台保活 | 官方事件流，稳定 |
| 能拿到「烘干完成」 | 靠文案关键词 | ✅ 官方事件 |
| 能拿到「耗材不足」 | 仅当微信文案带关键词 | ✅ i-DOS 事件（已实测） |
| 额外耗电/流量 | 几乎没有 | SSE 长连接，每天 1~2 次请求 |

## 3. 你需要准备

- 一台 **Android 手机**（小米/红米最佳），装 **Termux**（本仓库不附带 APK，见下）：
  - Termux（**GitHub 版**，不要和 F-Droid 版混装）<https://github.com/termux/termux-app/releases>
  - Termux:Boot（**GitHub 版**，用于开机自启，必须和 Termux 同来源）<https://github.com/termux/termux-boot/releases>
- 一个小爱音箱（账号下任意一台；单台指定播报请见配置项 `speaker`）
- 小米账号（用于调用 TTS），微信、博世/晶御 App（方案 A）
- （方案 B）Home Connect 开发者账号 + 晶御账号

## 4. 一键安装（Termux）

> 本机 `curl` 在 Termux 上可能因 openssl/libcurl 版本不匹配而报错，所以安装器**只用 Python 标准库**。

在 Termux 里粘贴并回车：

```bash
python -c "import urllib.request as u;exec(u.urlopen('https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main/install.py').read().decode())"
```

安装器会依次完成：

1. 下载全部程序到 `~/laundry-xiaoai/`；
2. 安装 Python 依赖 `miservice`；
3. 引导登录小米账号（密码默认不保存）；
4. 列出音箱并测试一句播报；
5. 可选：配置晶御官方 API（开发者 client_id + 设备码授权）；
6. 生成守护脚本 + 开机自启（`~/.termux/boot/start-laundry.sh`）并做健康检查。

**国内网络提示**：`raw.githubusercontent.com` 可能不稳定。任选一种方式：

```bash
# 方式 1：用镜像源下载 install.py（示例镜像，可换其他）
LAUNDRY_XIAOAI_BASE=https://ghproxy.net/https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main \
  python -c "import urllib.request as u;exec(u.urlopen('https://ghproxy.net/https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main/install.py').read().decode())"

# 方式 2：先把仓库下载到手机（任意方式），再本地运行
python /sdcard/Download/laundry-xiaoai/install.py --base file:///sdcard/Download/laundry-xiaoai
```

安装器的可用参数/环境变量：

| 参数 / 环境变量 | 作用 |
| --- | --- |
| `--base URL` / `LAUNDRY_XIAOAI_BASE` | 下载源（GitHub raw 或镜像） |
| `--dir PATH` / `LAUNDRY_XIAOAI_DIR` | 安装目录（默认 `~/laundry-xiaoai`） |
| `--skip-login` | 跳过小米登录交互 |
| `--skip-test` | 跳过测试播报 |
| `--no-start` | 不启动服务 |
| `--hc` / `--no-hc` | 是否配置晶御官方 API |
| `LAUNDRY_XIAOAI_SKIP_LOGIN=1` | 跳过小米登录（同 `--skip-login`） |
| `LAUNDRY_XIAOAI_SKIP_DEPS=1` | 跳过 pip 依赖安装 |
| `LAUNDRY_XIAOAI_SKIP_TEST=1` | 跳过测试播报 |
| `LAUNDRY_XIAOAI_NO_START=1` | 不启动服务 |
| `LAUNDRY_XIAOAI_HC=1` / `=0` | 启用/禁用晶御 API 配置 |

> 用 `python -c "exec(...)"` 方式运行时无法带命令行参数，请用上表的环境变量控制。

## 5. 安卓端配置（方案 A 必需）

### 5.1 安装通知转发 App

任选其一（都能把通知 POST 给本机 HTTP 服务）：

- **Notifikator**（本方案实测）：<https://github.com/scottmconway/notifikator/releases>
  - 如果「授予通知使用权」开关是灰色、显示“由受限设置控制”：先到 **设置 → 应用管理 → Notifikator → 右上角 ⋮ → 允许受限设置**，再回通知使用权页面打开开关；
- **MacroDroid**（如果用商店版，不受侧载限制）：触发器「通知 → 应用=微信 → 文本包含 洗衣已完成」，动作「HTTP 请求 GET `http://127.0.0.1:8765/washer`」。

### 5.2 Notifikator 填写

| 字段 | 值 |
| --- | --- |
| URL | `http://127.0.0.1:8765/notify` |
| Body Template | `{"title":"%title%","text":"%text%","package":"%package%"}` |
| Headers | 留空 |
| Enable Authentication | 不勾 |
| Username / Password | 留空 |

并确认：通知使用权已授予、App 的「Enabled」开关打开、「WiFi only」按需、电池策略设为**无限制**+允许自启动+后台加锁。

### 5.3 微信设置（关键）

1. 微信 → 设置 → 消息通知：开启「接收新消息通知」「**通知显示消息详情**」；
2. 微信「服务通知」→ 右上角 ⚙ → 开启「消息通知提醒」；
3. 测试时手机要**锁屏 / 微信在后台**（微信在前台时不产生系统通知）；
4. 微信/系统里不要开免打扰。

### 5.4 验证链路

```bash
python ~/laundry-xiaoai/tools/selftest.py   # 模拟微信通知，应听到播报
python ~/laundry-xiaoai/tools/showlog.py    # 看 bridge 最近日志
```

## 6. 方案 B：晶御官方 API（可选）

### 6.1 注册开发者应用

1. 打开 <https://developer.home-connect.cn/user/register>，Account Type 选 **Individual**，**邮箱全部小写**；
2. 创建应用：
   - 勾选 **Sync to China**；
   - **Home Connect User Account for Testing** 填晶御 App/小程序里的手机号（`+86` 开头、无空格）；
   - 应用类型选 **Device Flow**（手机端最省事；被拒再改 Authorization Code）；
3. 拿到 **Client ID**（Device Flow 应用通常没有 secret）。

### 6.2 在手机上授权

```bash
python ~/laundry-xiaoai/tools/hc_config.py   # 填 client_id，自动进入设备码授权
python ~/laundry-xiaoai/tools/fix.py         # 启用/重启监听
python ~/laundry-xiaoai/hc_listen.py --list  # 应看到洗衣机、烘干机
python ~/laundry-xiaoai/hc_listen.py --dump  # 只观察事件、不播报（调试用）
```

授权时：打开脚本打印的**完整地址**（必须带 `?user_code=`，只打开域名根会显示 `Cannot GET /`），用晶御账号登录同意；全程不要关 Termux。

### 6.3 官方 API 要点（实测）

- Host：`https://api.home-connect.cn`
- REST 请求必须带 `Accept: application/vnd.bsh.sdk.v1+json`（否则 406）
- 完成事件：
  - 洗衣机：`BSH.Common.Event.ProgramFinished`
  - 烘干机：`LaundryCare.Dryer.Event.DryingProcessFinished`
  - **不要用** `OperationState=Finished`（包含“中途取消”，会误报）；`hc_listen.py` 默认排除
- 耗材事件（已实测）：
  - `LaundryCare.Washer.Event.IDos1FillLevelPoor`（i-DOS 1 仓 = 洗衣液）
  - `LaundryCare.Washer.Event.IDos2FillLevelPoor`（i-DOS 2 仓 = 柔顺剂）
- 限流：约 1000 请求/天、50/分钟；SSE 长连接常驻只算 1 次；脚本断线重连最小 15 秒并指数退避

## 7. 播报模式

`~/.config/laundry-xiaoai/homeconnect.json` 的 `announce.mode`（或运行 `tools/hc_announce.py` 一键切换）：

| 模式 | 播报内容 |
| --- | --- |
| `finished`（默认） | 只播完成 |
| `minimal` | 完成 + 耗材不足（推荐） |
| `important` | 完成 + 开始 / 暂停 / 门开关 / 报警 / 耗材 |
| `all` | important + 剩余时间 / 进度 / 阶段（带节流，较吵） |

```bash
python ~/laundry-xiaoai/tools/hc_announce.py
```

## 8. 目录与常用命令

```
~/laundry-xiaoai/
├─ bridge.py               # 播报服务（127.0.0.1:8765）
├─ hc_listen.py            # 晶御官方 API 监听（方案 B）
├─ install.py              # 一键安装器
├─ tools/
│  ├─ fix.py               # 更新脚本 + 重启服务（守护/开机自启）
│  ├─ diag.py              # 设备/音量/状态诊断
│  ├─ showlog.py           # 查看 bridge 日志
│  ├─ selftest.py          # 模拟通知自测
│  ├─ stop.py              # 停止音箱播放
│  ├─ hc_status.py         # 打印晶御 API 状态字段
│  ├─ hc_announce.py       # 切换播报模式
│  └─ hc_config.py         # 填晶御 client_id 并授权
└─ run-loop.sh / hc-loop.sh（生成）
```

| 命令 | 作用 |
| --- | --- |
| `python ~/laundry-xiaoai/bridge.py --list` | 列出小爱音箱 |
| `python ~/laundry-xiaoai/bridge.py --test washer` | 测试播报 |
| `python ~/laundry-xiaoai/tools/diag.py` | 诊断 |
| `python ~/laundry-xiaoai/tools/fix.py` | 更新并重启 |
| `python ~/laundry-xiaoai/tools/showlog.py` | 看日志 |

HTTP 接口（只监听 127.0.0.1）：

| 接口 | 说明 |
| --- | --- |
| `GET /health` | 健康检查 |
| `GET /washer` / `/dryer` / `/linger` / `/supply` | 按类别播报（带去抖） |
| `GET /test?text=` / `/say?text=` | 播报任意文本（`/say` 不做类别去抖） |
| `POST /notify` | 通知转发入口：`{"text":"...","package":"com.tencent.mm"}` |

## 9. 排错

| 现象 | 处理 |
| --- | --- |
| 小米登录 70016 | 账号/密码或验证问题；`python ~/laundry-xiaoai/bridge.py --login` 重新登录 |
| 小爱没声音、`--test` 成功 | 检查音箱音量/免打扰；OH2 等型号需 MIoT 通道（bridge 会自动选择） |
| 微信通知到了但没播报 | `tools/showlog.py` 看是否 `package-filtered`/`no-keyword`；确认微信开启了消息详情 |
| Notifikator 通知使用权开关灰 | 应用信息 → 允许受限设置 |
| 晶御 `--list` 为空 | 测试账号手机号 ≠ 晶御账号，或没勾 Sync to China |
| 晶御 406 | 脚本版本旧；请求头需 `application/vnd.bsh.sdk.v1+json` |
| 授权页 `Cannot GET /` | 打开的是域名根，需带 `?user_code=...` 的完整链接 |
| 验证码错误/失效 | 设备码 30 分钟过期；重新 `--login` 生成新码 |
| `--dump` 里噪音多 | 正常；`announce.mode` 选 `minimal`，`speak_unknown` 保持 false |
| 剩余时间播报跳变 | 已修复“中途启动误报大阈值”的逻辑；阈值只在向下跨过时播一次 |

## 10. 安全与隐私

- 所有数据都在你手机本地：`~/.config/laundry-xiaoai/`（小米 token、晶御 token、配置）；文件权限 600；
- `bridge.py` 默认只监听 `127.0.0.1`，局域网其他设备无法调用；除非你手动改 `listen_host`（不建议）；
- 仓库不包含任何 APK、账号、token、client secret；`client_id` 属于半公开信息，但 `client_secret` 不要提交；
- 通知转发只处理 `com.tencent.mm`（可配置白名单），避免其他 App 文本误触发。

## 11. 许可

MIT License，见 [LICENSE](LICENSE)。

## 12. 参考

- MiService（小米云接口）：<https://github.com/Yonsm/MiService>
- Home Connect 中国区 API 文档：<https://api-docs.home-connect.com/>
- Notifikator：<https://github.com/scottmconway/notifikator>
- Termux / Termux:Boot：<https://github.com/termux/termux-app> / <https://github.com/termux/termux-boot>
