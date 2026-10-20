# 安卓端配置（方案 A）

> 目标：把手机上的**微信通知**转发到 Termux 里的 `bridge.py`，再由小爱音箱播报。

## 1. 安装通知转发 App

推荐 **Notifikator**（MIT，开源）：

- 下载：<https://github.com/scottmconway/notifikator/releases>
- 安装后如果打开通知使用权页面，开关是灰色、下方显示「由受限设置控制」：
  1. 设置 → 应用设置 → 应用管理 → **Notifikator** → 右上角 ⋮ → **允许受限设置**（按提示验证密码/指纹）；
  2. 再回到 设置 → 隐私与安全 → 其他权限 → 特殊权限设置 → **设备和应用通知** → Notifikator → 打开「授予通知使用权」；
  3. 页面下方「实时 / 对话 / 通知 / 静音」四项都保持开启。

备选 **MacroDroid**：从应用商店安装（不受侧载限制），触发器用「通知」，动作「HTTP 请求 GET http://127.0.0.1:8765/washer」。

## 2. Notifikator 填写

| 字段 | 值 |
| --- | --- |
| Endpoint / URL | `http://127.0.0.1:8765/notify` |
| Body Template | `{"title":"%title%","text":"%text%","package":"%package%"}` |
| Headers | 留空 |
| Enable Authentication | 不勾 |
| Username / Password | 留空 |

另确认 Notifikator 的 **Enabled** 主开关打开；**WiFi only** 按需（关掉或保证手机连 WiFi）。

## 3. 权限与保活（HyperOS / MIUI 重点）

- Notifikator：省电策略 **无限制**、允许**自启动**、最近任务**加锁**；
- Termux：省电策略 **无限制**、允许自启动、最近任务加锁；Termux:Boot 打开一次；
- 不要开系统/微信的免打扰；
- 微信：设置 → 消息通知 → 打开「接收新消息通知」「**通知显示消息详情**」；
- 微信「服务通知」→ 右上角 ⚙ → 打开「消息通知提醒」。

## 4. 验证

1. 手机锁屏（或把微信切到后台）；
2. 用电脑微信/另一台手机给这个微信发：`洗衣已完成`；
3. 手机应弹出微信通知 → 小爱播报；
4. 若没播报，看 Termux 日志：

```bash
python ~/laundry-xiaoai/tools/showlog.py
```

对照日志：

- 没有 `收到通知：package=com.tencent.mm` → Notifikator 没转发（权限/保活/通知没弹出）；
- `通知被包名过滤掉` → 微信包名不是 `com.tencent.mm`（分身等），改配置 `notify_package_allow`；
- `通知关键词没命中` → 通知文本和关键词不匹配，把日志里的文本补进 `keywords`。

> Notifikator 自带的 **Send Notification** 按钮不能验证播报：它发的测试通知 package 是 `org.scottmconway.notifikator`、文本也不含洗衣关键词，bridge 会按规则跳过——这是正常现象，只说明链路没被误触发。
