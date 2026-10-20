# 架构说明

## 组件

| 组件 | 位置 | 作用 |
| --- | --- | --- |
| `bridge.py` | 手机 Termux | HTTP 服务（127.0.0.1:8765）：分类、去抖、免打扰、音量、TTS |
| `hc_listen.py` | 手机 Termux | 方案 B：登录晶御开发者 API、维持 SSE 事件流、翻译事件、调用 bridge |
| 通知转发 App | Android | 读取微信通知并 POST 给 bridge（方案 A） |
| `tools/fix.py` | 手机 Termux | 更新脚本、生成 run-loop/hc-loop、开机自启、重启服务 |
| `tools/diag.py` | 手机 Termux | 诊断：设备列表、音量、token、测试播报 |
| 小爱音箱 | 家庭 | 接收小米云 TTS / MIoT play-text 指令并播报 |

## 方案 A 数据流

1. 博世/晶御小程序推送服务通知到微信 → 手机系统通知栏；
2. Notifikator 的 `NotificationListenerService` 收到通知；
3. 按 Body 模板生成 JSON，POST 到 `http://127.0.0.1:8765/notify`；
4. `bridge.py`：
   - 包名白名单（默认只允许 `com.tencent.mm`）；
   - 关键词分类（supply / washer / dryer / linger）；
   - 类别去抖（默认 300 秒，linger 1800 秒）；
   - 免打扰时段跳过；
   - 调用小米云播报（自动选择 MiNA TTS 或 MIoT play-text）。
5. 小爱音箱播报。

## 方案 B 数据流

1. `hc_listen.py --login` 走 OAuth（Device Flow 或 Authorization Code）拿到 access/refresh token；
2. `GET /api/homeappliances` 拿到洗衣机/烘干机 `haId`；
3. 为每台设备维持 `GET /api/homeappliances/{haId}/events` 的 SSE 长连接；
4. 收到 `BSH.Common.Event.ProgramFinished`（洗衣机）或
   `LaundryCare.Dryer.Event.DryingProcessFinished`（烘干机）→ 调用 bridge 的 `/washer`、`/dryer`；
5. 其他事件按 `announce.mode` 翻译成中文后调用 bridge 的 `/say?text=`。

## 去抖与互斥

- bridge 按“类别”记录上次播报时间，方案 A/B 同时触发时后到的返回 `skipped: cooldown`，保证只播一次；
- `hc_listen.py` 另外做事件级节流（同 key 间隔、全局间隔、阈值只播一次）；
- `/say` 接口不做类别去抖（由 hc_listen 节流），但免打扰时段仍然生效。

## 型号兼容

- 大多数小爱音箱支持 MiNA 云端 TTS；
- 新型号（如硬件 OH2/OH2P）MiNA TTS 会“返回成功但不响”，bridge 自动改走 MIoT play-text（siid/aiid 查表），可用 `miot_tts` 覆盖；
- 播报通道可用 `tts_channel` 强制为 `mina` 或 `miot` 调试。

## 配置文件

- `~/.config/laundry-xiaoai/config.json`：bridge 配置（登录后生成，默认值与示例见 `examples/config.example.json`）；
- `~/.config/laundry-xiaoai/homeconnect.json`：方案 B 配置；
- `~/.config/laundry-xiaoai/mi.token`、`homeconnect_token.json`：令牌（权限 600，勿提交）。
